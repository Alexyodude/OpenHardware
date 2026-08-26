# OpenHardware — SysTick, and the frame an Armv6-M exception leaves behind.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this is for
#
# An Arduino sketch cannot reach `setup()` on any Arm board without this.
# Measured on 2026-08-26: a real Arduino-core SAMD21 image runs 318,216
# instructions, gets through `SystemInit` and `init`, and then stalls forever
# inside `delay()` -- because `micros()` returns `(_ulTickCount + PENDSTSET) *
# 1000` plus a sub-millisecond term, and `_ulTickCount` moves only in
# `SysTick_Handler`. Without exception delivery `delay(2)` never returns, and
# `main()` calls `delay(1)` before `setup()`.
#
# ## Where the numbers come from
#
# **Every value below was produced by rp2040js**, this project's Armv6-M
# oracle, and not by reading DDI0419 and writing down what it seemed to say.
# `tools/gen_armv6m_exception.mjs` is the harness; run it to see them:
#
#     node tools/gen_armv6m_exception.mjs
#
# `test_the_recorded_oracle_answers_still_match` runs it wherever a built
# rp2040js exists and compares field by field, so the copies here cannot drift
# from the thing they were copied from. It is the only test in this file that
# skips, and it skips the way `test_samd21_blink.py` does when no compiler
# exists -- never quietly, and never as a pass.
#
# ## The one thing the oracle is NOT asked
#
# **When the tick arrives.** rp2040js counts simulated clock cycles; this core
# has no cycle model and counts retired instructions, which `Cpu::tick_systick`
# states at the place the approximation is made. So the two cannot agree on the
# rate, every case here forces the exception pending instead of waiting for it,
# and the rate is checked separately -- against arithmetic, in
# `test_the_period_is_one_more_than_the_reload_value`.
#
# ## Why the handler is `b .` and not `bx lr` in the entry cases
#
# It matters for the oracle rather than for this core, and it cost a debugging
# round: rp2040js takes the exception at the top of `executeInstruction` and
# then executes an instruction in the *same call*, so a handler of `bx lr`
# enters and returns before anything can look. This core makes entry its own
# step. That is a difference in step accounting, not in the machine, and it is
# the reason the two harnesses are not written identically.

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The System Control Space, at the addresses Armv6-M fixes. Spelled here
#: rather than imported from a board, because no board owns them: every
#: Cortex-M0+ has these at exactly these addresses.
SYST_CSR = 0xE000E010
SYST_RVR = 0xE000E014
SYST_CVR = 0xE000E018
SYST_CALIB = 0xE000E01C
SCB_ICSR = 0xE000ED04
SCB_VTOR = 0xE000ED08
SCB_SHPR3 = 0xE000ED20

SYST_ENABLE = 1 << 0
SYST_TICKINT = 1 << 1
SYST_COUNTFLAG = 1 << 16
ICSR_PENDSTCLR = 1 << 25
ICSR_PENDSTSET = 1 << 26

#: SysTick is exception 15, so its vector is the sixteenth word of the table.
EXC_SYSTICK = 15

#: The addresses `tools/gen_armv6m_exception.mjs` uses, so a value can be
#: compared against the oracle's without translating it first.
VECTORS = 0x20000000
HANDLER = 0x20001000
RESUME = 0x20002000
STACK_TOP = 0x20003000

#: Deliberately not 0, 1, 2, 3: sequential sentinels let an off-by-one frame
#: still look plausible, and the frame is exactly where an off-by-one lives.
R0 = 0xA0A00000
R1 = 0xA1A10001
R2 = 0xA2A20002
R3 = 0xA3A30003
R4 = 0x44444444
R12 = 0xACACACAC
LR = 0x1EEEEEEF

#: N set, Z clear, C set, V clear -- an asymmetric pattern, so a model that
#: dropped the flags entirely and one that inverted them both fail.
APSR = 0xA0000000

B_SELF = 0xE7FE
BX_LR = 0x4770
PUSH_R4_LR = 0xB510
POP_R4_PC = 0xBD10

#: What `tools/gen_armv6m_exception.mjs` printed on 2026-08-26. Every one of
#: these is rp2040js's answer, not this repository's.
ORACLE = {
    "entry_aligned": {
        "frame": 0x20002FE0,
        "stacked": [R0, R1, R2, R3, R12, LR, RESUME, 0xA1000000],
        "lr": 0xFFFFFFF9,
        "ipsr": 15,
    },
    "entry_misaligned": {
        "frame": 0x20002FD8,
        "stacked": [R0, R1, R2, R3, R12, LR, RESUME, 0xA1000200],
        "lr": 0xFFFFFFF9,
        "ipsr": 15,
    },
}


def build(cpu, sp: int, handler: tuple[int, ...] = (B_SELF,)) -> None:
    """Lay out a vector table, a handler and a program, and start in it.

    The whole machine is in SRAM. That says nothing about where any real part
    puts its flash, and it is the point: `VTOR` is what makes the table's
    address the caller's business, so a test of the mechanism should not have
    to pick a chip.
    """
    cpu.write_word(SCB_VTOR, VECTORS)
    cpu.write_word(VECTORS + 4 * EXC_SYSTICK, HANDLER | 1)
    for index, halfword in enumerate(handler):
        cpu.write_halfword(HANDLER + 2 * index, halfword)
    cpu.write_halfword(RESUME, B_SELF)
    cpu.set_regs(
        [R0, R1, R2, R3, R4, 0, 0, 0, 0, 0, 0, 0, R12, sp, LR, RESUME],
        apsr=APSR,
    )


def arm(cpu, reload_value: int) -> None:
    """Start SysTick counting, with the interrupt enabled."""
    cpu.write_word(SYST_RVR, reload_value)
    cpu.write_word(SYST_CVR, 0)
    cpu.write_word(SYST_CSR, SYST_ENABLE | SYST_TICKINT)


def step_until(cpu, predicate, budget: int = 200) -> int:
    """Step until `predicate(pc)`, and return how many steps it took."""
    for taken in range(budget):
        if predicate(cpu.get_regs().as_list()[15]):
            return taken
        cpu.step()
    raise AssertionError(
        f"never reached the wanted PC in {budget} steps; "
        f"pc=0x{cpu.get_regs().as_list()[15]:08x}"
    )


# --- the registers themselves -----------------------------------------------


def test_the_system_control_space_exists_without_a_board(cpu):
    """A core with no board has no memory at all -- and still has SysTick.

    That is the claim `cpu.h` makes when it puts these addresses in the core:
    the System Control Space is the processor, so it cannot be installed and
    cannot be absent. Every other address in this suite answers only because a
    board or a fixture added a region.
    """
    cpu.clear_registers()
    cpu.clear_regions()
    assert cpu.is_mapped(SYST_CSR)
    assert cpu.is_mapped(SCB_ICSR)
    assert not cpu.in_range(SYST_CSR, 4)


def test_a_disabled_systick_does_not_count(cpu):
    """The reset state, and the one every conformance case runs in."""
    cpu.write_word(SYST_RVR, 10)
    cpu.write_word(SYST_CVR, 0)
    build(cpu, STACK_TOP)
    for _ in range(20):
        cpu.step()
    assert cpu.read_word(SYST_CVR) == 0
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET == 0


def test_the_counter_counts_down_and_reloads(cpu):
    build(cpu, STACK_TOP)
    cpu.write_word(SYST_RVR, 3)
    cpu.write_word(SYST_CVR, 0)
    cpu.write_word(SYST_CSR, SYST_ENABLE)  # no TICKINT: counting only
    seen = []
    for _ in range(9):
        cpu.step()
        seen.append(cpu.read_word(SYST_CVR))
    # Zero is a value the counter is seen at, for one tick, before the reload
    # -- so the period is RVR PLUS ONE. That is the part's own behaviour and
    # the reason `SysTick_Config(n)` writes `n - 1`; a model that fired every
    # RVR ticks would make every `delay` fractionally short.
    assert seen == [3, 2, 1, 0, 3, 2, 1, 0, 3]


def test_writing_the_current_value_clears_it_whatever_the_value(cpu):
    """`SysTick_Config` writes zero and expects a full first period. Any value
    does the same thing, which is the architecture and not a shortcut."""
    build(cpu, STACK_TOP)
    cpu.write_word(SYST_RVR, 100)
    cpu.write_word(SYST_CSR, SYST_ENABLE)
    for _ in range(5):
        cpu.step()
    # Four counting ticks, because the first was spent loading RVR.
    assert cpu.read_word(SYST_CVR) == 96
    cpu.write_word(SYST_CVR, 0xDEADBEEF)
    assert cpu.read_word(SYST_CVR) == 0


def test_countflag_is_set_by_a_wrap_and_cleared_by_the_read(cpu):
    """The one register in this core whose read changes it, which is why
    `SystemControl` is a struct rather than five mapped words."""
    build(cpu, STACK_TOP)
    cpu.write_word(SYST_RVR, 2)
    cpu.write_word(SYST_CVR, 0)
    cpu.write_word(SYST_CSR, SYST_ENABLE)
    assert cpu.read_word(SYST_CSR) & SYST_COUNTFLAG == 0
    for _ in range(3):  # load, 2, then 0 -- see the period note above
        cpu.step()
    assert cpu.read_word(SYST_CSR) & SYST_COUNTFLAG
    assert cpu.read_word(SYST_CSR) & SYST_COUNTFLAG == 0, (
        "COUNTFLAG survived being read, so a wrap that already happened "
        "reports itself as new every time it is asked"
    )


def test_a_reload_of_zero_stops_the_counter(cpu):
    """The architecture's answer, and what `SysTick_Config` leans on when it
    refuses a reload it cannot represent."""
    build(cpu, STACK_TOP)
    cpu.write_word(SYST_RVR, 0)
    cpu.write_word(SYST_CVR, 0)
    cpu.write_word(SYST_CSR, SYST_ENABLE | SYST_TICKINT)
    for _ in range(50):
        cpu.step()
    assert cpu.read_word(SYST_CVR) == 0
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET == 0
    assert cpu.get_regs().as_list()[15] == RESUME


def test_the_calibration_word_reads_zero_meaning_unknown(cpu):
    """Zero TENMS is "the calibration value is not known", which is exactly
    true of a core whose clock is retired instructions. An invented ten
    milliseconds would let firmware compute a tick rate and believe it."""
    assert cpu.read_word(SYST_CALIB) == 0


def test_the_priority_registers_accept_a_write_and_change_nothing(cpu):
    """`NVIC_SetPriority(SysTick_IRQn, ...)` is the second line of Arduino's
    `init()`. With one exception source there is nothing to arbitrate, so this
    pins that the write lands somewhere rather than faulting -- and says so,
    rather than leaving a reader to think priority is modelled."""
    cpu.write_word(SCB_SHPR3, 0xC0000000)
    assert cpu.read_word(SCB_SHPR3) == 0xC0000000


# --- entry ------------------------------------------------------------------


def test_the_wrap_makes_the_exception_pending_before_it_is_taken(cpu):
    """Pending and taken are two different moments, and the gap is visible.

    The tick cannot take the exception where it happens: by then the
    instruction that retired has already moved PC, so the return address would
    be right by luck. `ICSR.PENDSTSET` is the state in between, and Arduino's
    `micros()` reads exactly this bit to fill the sub-millisecond gap.
    """
    build(cpu, STACK_TOP)
    arm(cpu, 2)
    for _ in range(3):  # load, 2, then 0
        cpu.step()
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET
    assert cpu.get_regs().as_list()[15] == RESUME, "taken too early"
    cpu.step()
    assert cpu.get_regs().as_list()[15] == HANDLER
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET == 0


def test_the_entry_frame_matches_the_oracle_word_for_word(cpu):
    """**The eight stacked words, against rp2040js.**

    Only the locations are architected, not the order they are written in, so
    a model built from a reading can put the right values in the wrong slots
    and pass every test that checks them as a set.
    """
    build(cpu, STACK_TOP)
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    regs = cpu.get_regs().as_list()
    expected = ORACLE["entry_aligned"]
    assert regs[13] == expected["frame"]
    stacked = [cpu.read_word(regs[13] + 4 * i) for i in range(8)]
    assert stacked == expected["stacked"]
    assert regs[14] == expected["lr"]
    assert cpu.read_word(SCB_ICSR) & 0x1FF == expected["ipsr"]


def test_an_odd_stack_pointer_is_realigned_and_the_frame_records_it(cpu):
    """**The case a model built from an aligned SP alone gets wrong.**

    SP is forced down to an eight-byte boundary and bit 9 of the stacked xPSR
    remembers whether it had to move. Get it wrong and the stack drifts four
    bytes -- but only on exceptions that happen to arrive at an odd word, so
    every test that fires one exception still passes and a program that runs
    for a while corrupts.
    """
    build(cpu, STACK_TOP - 4)
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    regs = cpu.get_regs().as_list()
    expected = ORACLE["entry_misaligned"]
    assert regs[13] == expected["frame"]
    stacked = [cpu.read_word(regs[13] + 4 * i) for i in range(8)]
    assert stacked == expected["stacked"]


def test_the_stacked_xpsr_carries_the_thumb_bit(cpu):
    """Armv6-M has no ARM state to return to, so a cleared T on the way back
    is a fault on real silicon rather than a mode change."""
    build(cpu, STACK_TOP)
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    xpsr = cpu.read_word(cpu.get_regs().as_list()[13] + 0x1C)
    assert xpsr & (1 << 24), f"EPSR.T clear in stacked xPSR 0x{xpsr:08x}"


def test_the_handler_is_entered_through_the_vector_table_at_vtor(cpu):
    """Moving the table moves the handler. Without VTOR the entry would read
    address zero, which on a SAMD21 is flash and on an RP2040 is boot ROM --
    two different wrong answers from the same missing register."""
    build(cpu, STACK_TOP)
    elsewhere = 0x20004000
    cpu.write_word(SCB_VTOR, elsewhere)
    cpu.write_word(elsewhere + 4 * EXC_SYSTICK, (HANDLER + 0x40) | 1)
    cpu.write_halfword(HANDLER + 0x40, B_SELF)
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc != RESUME)
    assert cpu.get_regs().as_list()[15] == HANDLER + 0x40


# --- return -----------------------------------------------------------------


def test_a_handler_returning_through_bx_lr_restores_everything(cpu):
    build(cpu, STACK_TOP, handler=(BX_LR,))
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    step_until(cpu, lambda pc: pc == RESUME)
    regs = cpu.get_regs().as_list()
    assert [regs[0], regs[1], regs[2], regs[3], regs[12]] == [R0, R1, R2, R3, R12]
    assert regs[4] == R4
    assert regs[13] == STACK_TOP
    assert regs[14] == LR
    assert cpu.get_regs().apsr == APSR
    assert cpu.read_word(SCB_ICSR) & 0x1FF == 0, "still in Handler mode"


def test_a_handler_returning_through_pop_pc_restores_everything(cpu):
    """**The path a compiler actually emits, and the one that gets missed.**

    A handler that touches a callee-saved register opens with `push {r4, lr}`
    and closes with `pop {r4, pc}` -- so the EXC_RETURN reaches PC from memory
    rather than from a register, and SP has to be written before PC for the
    unstack to read the frame from the right place.
    """
    build(cpu, STACK_TOP, handler=(PUSH_R4_LR, POP_R4_PC))
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    step_until(cpu, lambda pc: pc == RESUME)
    regs = cpu.get_regs().as_list()
    assert [regs[0], regs[1], regs[2], regs[3], regs[12]] == [R0, R1, R2, R3, R12]
    assert regs[13] == STACK_TOP
    assert regs[14] == LR


def test_the_odd_stack_pointer_comes_back_exactly_as_it_went_in(cpu):
    """Return puts back the four bytes entry took, and only if it took them."""
    build(cpu, STACK_TOP - 4, handler=(BX_LR,))
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    step_until(cpu, lambda pc: pc == RESUME)
    assert cpu.get_regs().as_list()[13] == STACK_TOP - 4


def test_an_exc_return_in_thread_mode_is_a_wild_branch_and_not_a_return(cpu):
    """Only Handler mode can return from an exception.

    In Thread mode 0xFFFFFFF9 is an address nothing maps, and the honest
    answer is the fault that says so -- not unstacking a frame that nothing
    stacked, which would put eight words of whatever is under SP into the
    register file and carry on.
    """
    build(cpu, STACK_TOP)
    regs = [R0, R1, R2, R3, R4, 0, 0, 0, 0, 0, 0, 0, R12, STACK_TOP, 0xFFFFFFF9, RESUME]
    cpu.write_halfword(RESUME, 0x4770)  # bx lr
    cpu.set_regs(regs, apsr=APSR)
    with pytest.raises(Exception) as caught:
        cpu.step()
        cpu.step()
    assert "fffffff8" in str(caught.value).lower(), caught.value


# --- masking, and not pre-empting itself ------------------------------------


def test_primask_holds_the_exception_off_without_losing_it(cpu):
    """`CPSID i`, then `CPSIE i`.

    A critical section this core kept interrupting would be a corrupted
    program with no message, which is why `exec.cc` implements CPS rather than
    reporting it: exception delivery without masking is *wrong* rather than
    incomplete. And the tick is held, not dropped -- dropping it would lose a
    millisecond of `millis()` every time one landed inside a critical section.
    """
    build(cpu, STACK_TOP, handler=(BX_LR,))
    cpu.write_halfword(RESUME, 0xB672)      # cpsid i
    cpu.write_halfword(RESUME + 2, B_SELF)  # b .
    arm(cpu, 1)
    cpu.step()  # cpsid i
    for _ in range(20):
        cpu.step()
    assert cpu.get_regs().as_list()[15] == RESUME + 2, "entered a masked handler"
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET, "the tick was dropped"

    cpu.write_halfword(RESUME + 2, 0xB662)  # cpsie i
    cpu.step()
    cpu.step()
    assert cpu.get_regs().as_list()[15] == HANDLER


def test_systick_does_not_pre_empt_its_own_handler(cpu):
    """Same priority, so the architecture makes it wait -- and it is taken the
    instant the handler returns rather than being lost. Tail-chaining.

    The reload here is one tick, so a second wrap is certain while the handler
    is still running: a core that let it in would recurse until the stack ran
    into whatever is below it.
    """
    build(cpu, STACK_TOP, handler=(B_SELF,))
    arm(cpu, 1)
    step_until(cpu, lambda pc: pc == HANDLER)
    frame = cpu.get_regs().as_list()[13]
    for _ in range(50):
        cpu.step()
    assert cpu.get_regs().as_list()[13] == frame, "the handler was re-entered"


def test_writing_pendstset_raises_the_exception_without_a_wrap(cpu):
    """The software half of `ICSR`: a request in one direction and a report in
    the other. Nothing here drives it, and it is modelled because a register
    that reads back what a wrap put there and ignores what software writes is
    the wrong-answer failure this core refuses elsewhere."""
    build(cpu, STACK_TOP, handler=(BX_LR,))
    cpu.write_word(SCB_ICSR, ICSR_PENDSTSET)
    cpu.step()
    assert cpu.get_regs().as_list()[15] == HANDLER


def test_writing_pendstclr_takes_a_pending_exception_back(cpu):
    build(cpu, STACK_TOP, handler=(BX_LR,))
    arm(cpu, 2)
    for _ in range(3):
        cpu.step()
    assert cpu.read_word(SCB_ICSR) & ICSR_PENDSTSET
    cpu.write_word(SCB_ICSR, ICSR_PENDSTCLR)
    cpu.step()
    assert cpu.get_regs().as_list()[15] == RESUME


# --- the rate, which the oracle cannot adjudicate ---------------------------


def test_the_period_is_one_more_than_the_reload_value(cpu):
    """**The approximation, measured.** rp2040js counts clock cycles and this
    counts retired instructions, so no oracle can say whether this number is
    right -- what it can be is *consistent*, which is what firmware doing
    `delay(ms)` actually depends on.

    Seventeen instructions apart for a reload of 16, and the two halves of
    that number are worth separating: sixteen is the count itself plus the
    tick the counter spends at zero, and the seventeenth is the step that
    stacks the frame -- entry executes no instruction and still costs one.
    """
    build(cpu, STACK_TOP, handler=(BX_LR,))
    arm(cpu, 16)
    entries = []
    for step in range(200):
        cpu.step()
        if cpu.get_regs().as_list()[15] == HANDLER:
            entries.append(step)
    gaps = {b - a for a, b in zip(entries, entries[1:])}
    assert len(entries) >= 5, entries
    assert gaps == {17}, sorted(gaps)


def test_a_stopped_core_does_not_age(cpu):
    """A program halted by a fault must not go on collecting ticks, or a
    caller stepping a halted core in a loop watches its clock advance."""
    build(cpu, STACK_TOP)
    arm(cpu, 4)
    cpu.write_halfword(RESUME, 0x4700 | (5 << 3))  # bx r5, and r5 is zero
    with pytest.raises(Exception):
        for _ in range(3):
            cpu.step()
    before = cpu.read_word(SYST_CVR)
    for _ in range(10):
        with pytest.raises(Exception):
            cpu.step()
    assert cpu.read_word(SYST_CVR) == before


# --- the oracle itself ------------------------------------------------------


def test_the_recorded_oracle_answers_still_match():
    """**Re-derive `ORACLE` from rp2040js and compare.**

    The values in this file are copies, and a copy drifts. This is the same
    guard `test_samd21_blink.py` puts on its committed binary: wherever the
    thing they were copied from exists, they are rebuilt and checked, and
    where it does not, this is the only test here that skips.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH, so rp2040js cannot be asked")
    done = subprocess.run(
        [node, str(REPO / "tools" / "gen_armv6m_exception.mjs")],
        capture_output=True, text=True, cwd=REPO,
    )
    if done.returncode == 3:
        pytest.skip(done.stderr.strip())
    assert done.returncode == 0, done.stderr
    fresh = json.loads(done.stdout)
    for case, expected in ORACLE.items():
        got = fresh[case]
        assert got["frame"] == expected["frame"], case
        assert got["stacked"] == expected["stacked"], case
        assert got["lr"] == expected["lr"], case
        assert got["ipsr"] == expected["ipsr"], case
    # The round trips are asserted above against this core; here they are
    # pinned against the oracle so that "restores everything" means the same
    # thing in both places.
    for case in ("return_bx_lr", "return_bx_lr_misaligned", "return_pop_pc"):
        trip = fresh[case]
        assert trip["sp_after"] == trip["sp_before"], case
        assert trip["pc"] == RESUME, case
        assert trip["regs"] == [R0, R1, R2, R3, R4, R12], case
        assert trip["lr"] == LR, case
        assert trip["ipsr"] == 0, case
    assert fresh["masked"]["ipsr"] == 0
    assert fresh["masked"]["still_pending"] is True
