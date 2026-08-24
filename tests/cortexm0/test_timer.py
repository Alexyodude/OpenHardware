# OpenHardware — an emulated TIMER, and a delay that is not a counted loop.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The hang class this is about
#
# Every other register modelled here fails loudly when it is missing: the
# address is unmapped, the access faults, and the message names it. A counter
# fails differently. `timer_busy_wait_us_32()` spins
#
#     while (timer->timerawl - start < delay_us) { tight_loop_contents(); }
#
# so a TIMERAWL that is mapped, answers, and never changes runs forever. There
# is nothing to make loud — the model is answering exactly the question asked,
# with a value that happens never to move.
#
# `tests/cortexm0/timer/delay.c` is the blink rewritten to wait on that
# register instead of counting to 64 in a volatile local. The counted version
# terminates on any emulator, correct timer or not, because nothing outside the
# core is involved; this one does not.
#
# ## Virtual time is instructions, and the tests say so
#
# The core has no cycle model, so time is counted in retired instructions and
# `webui/boards/rp2040.py` picks how many make a microsecond. The tests below
# assert the *rate the board declares*, never a wall-clock figure, because the
# model does not claim one.

import pathlib
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0.abi import Cpu, MemoryFault
from webui.boards import rp2040

HERE = pathlib.Path(__file__).resolve().parent / "timer"
IMAGE = HERE / "delay.bin"

LOAD = 0x10000100
LED = 1 << 25

#: What `delay.c` asks for between toggles.
DELAY_US = 200

#: Long enough for several toggles at 200 emulated microseconds each.
BUDGET = 200_000

TIMERAWL = rp2040.TIMER + rp2040.TIMER_TIMERAWL


@pytest.fixture
def board(cpu):
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    return cpu


def start(cpu: Cpu) -> None:
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    cpu.write_block(LOAD, IMAGE.read_bytes())
    sp = cpu.read_word(LOAD)
    entry = cpu.read_word(LOAD + 4)
    cpu.set_regs([0] * 13 + [sp, 0, entry & ~1], apsr=0)


def run_and_watch(cpu: Cpu, budget: int = BUDGET) -> list[int]:
    """Step, recording every step at which the LED pin changes state."""
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    transitions: list[int] = []
    last = 0
    for step in range(budget):
        cpu.step()
        now = cpu.read_word(out) & LED
        if now != last:
            transitions.append(step)
            last = now
    return transitions


# --- the counter itself -----------------------------------------------------


def test_the_timer_reads_zero_on_a_freshly_installed_board(board):
    """Zero because `map_counter` records where it started, not because the
    core is new. The `cpu` fixture is session-scoped and has run thousands of
    instructions by now — which is exactly the case an absolute counter would
    get wrong, and this asserts it does not."""
    assert board.read_word(TIMERAWL) == 0


def spin(board, instructions: int) -> None:
    """Retire `instructions` NOPs, rewinding PC so one encoding serves them all.

    `MOV r8, r8` is the Armv6-M NOP-equivalent the assembler emits, and
    resetting PC each time is cheaper than filling SRAM with thousands of
    copies — the counter is about how many instructions retired, not where.
    """
    board.write_halfword(rp2040.SRAM, 0x46C0)
    for _ in range(instructions):
        board.set_regs([0] * 15 + [rp2040.SRAM], apsr=0)
        board.step()


def test_the_timer_advances_at_the_rate_the_board_declares(board):
    """The whole difference between this and `map_register`: a stored word
    would still read zero after any number of instructions, and a busy-wait on
    it would never end.

    Asserted against the board's own constant rather than a wall-clock figure.
    The model counts retired instructions and says so; it does not claim
    microseconds of real time, and a test that implied it did would be making
    the claim the board's docstring is careful to refuse.
    """
    ticks = 4
    before = board.executed()
    spin(board, rp2040.TIMER_INSTRUCTIONS_PER_TICK * ticks)
    # A delta, not an absolute. `executed()` is the machine's whole lifetime
    # and the `cpu` fixture is shared across the suite, so asserting it equals
    # a fixed number passes alone and fails in company -- which is what the
    # first version of this test did.
    assert board.executed() - before == rp2040.TIMER_INSTRUCTIONS_PER_TICK * ticks
    assert board.read_word(TIMERAWL) == ticks


def test_the_timer_does_not_advance_between_ticks(board):
    """It is an integer count, so one instruction short of a tick still reads
    the tick before. Pinned because a model that interpolated would be
    inventing resolution the counter does not have."""
    spin(board, rp2040.TIMER_INSTRUCTIONS_PER_TICK - 1)
    assert board.read_word(TIMERAWL) == 0
    spin(board, 1)
    assert board.read_word(TIMERAWL) == 1


def test_a_faulting_step_does_not_age_the_machine(board):
    """`step` leaves the processor untouched on a fault, PC included, so a
    caller stepping a halted core in a loop must not watch its clock run. A
    counter that advanced anyway would let a stuck program satisfy a timeout it
    never actually waited out."""
    board.set_regs([0] * 15 + [0x40008000], apsr=0)   # nothing is mapped there
    before = board.executed()
    with pytest.raises(MemoryFault):
        board.step()
    assert board.executed() == before
    assert board.read_word(TIMERAWL) == 0


def test_the_timer_ignores_writes(board):
    """`TIMER_TIMERAWL_ACCESS "RO"` in pico-sdk's timer.h. A writable counter
    would let firmware set the clock back and wait forever."""
    board.write_word(TIMERAWL, 0xFFFFFFFF)
    assert board.read_word(TIMERAWL) == 0


def test_the_registers_this_board_does_not_model_still_fault(board):
    """TIMERAWH, TIMELR and TIMEHR are real and unmodelled: the 64-bit read
    path and the latched pair. Faulting names the address; answering zero would
    make `time_us_64()` return a plausible number that is wrong."""
    for offset in (0x24, 0x0C, 0x08):
        with pytest.raises(MemoryFault):
            board.read_word(rp2040.TIMER + offset)


def test_the_alarms_are_absent_rather_than_stubbed(board):
    """`sleep_ms()` arms an alarm and waits for its interrupt, and this core
    has no exceptions to deliver one with. Stubbing ALARM0 to accept a write
    would let firmware arm a timer that can never fire — a hang with a
    register behind it, which is worse than a fault."""
    with pytest.raises(MemoryFault):
        board.read_word(rp2040.TIMER + 0x10)          # ALARM0


# --- the image that waits on it ---------------------------------------------


def test_the_delayed_blink_toggles_more_than_once(cpu):
    """One toggle means the program reached the first XOR. Several mean the
    busy-wait ended and came back — which is the claim, because a frozen
    counter would stop after exactly one."""
    start(cpu)
    transitions = run_and_watch(cpu)
    assert len(transitions) > 2, f"LED changed state {len(transitions)} times"


def test_the_delay_lasts_as_long_as_the_firmware_asked_for(cpu):
    """200 emulated microseconds between toggles, measured in the board's own
    units. The tolerance is poll granularity, not slop: the wait ends at
    whichever read first sees the threshold crossed, and each pass through the
    loop is several instructions, so the interval lands a few instructions
    either side rather than exactly on it."""
    start(cpu)
    transitions = run_and_watch(cpu)
    periods = [b - a for a, b in zip(transitions[1:], transitions[2:])]
    assert periods, "not enough toggles to measure a period"
    expected = DELAY_US * rp2040.TIMER_INSTRUCTIONS_PER_TICK
    for period in periods:
        assert abs(period - expected) < 50, (
            f"period {period} instructions, expected about {expected} "
            f"({DELAY_US} us at {rp2040.TIMER_INSTRUCTIONS_PER_TICK}/us)"
        )


def test_the_period_is_not_perfectly_constant_and_that_is_correct(cpu):
    """Recorded rather than smoothed over. `test_blink.py` asserts its counted
    loop has exactly one period, and a reader moving between the two files
    would reasonably expect the same here. It is not the same: a wait that ends
    on a polled threshold cannot land on the same instruction every time, and a
    model that made it do so would be modelling something the hardware does not
    do either."""
    start(cpu)
    transitions = run_and_watch(cpu)
    periods = {b - a for a, b in zip(transitions[1:], transitions[2:])}
    assert len(periods) > 1, (
        f"every period was exactly {periods}, which a polled wait should not "
        f"produce -- check the delay is really reading the counter"
    )


def test_the_committed_binary_matches_its_source(cpu):
    """`delay.bin` is committed so this suite runs without a toolchain, and is
    rebuilt and compared wherever a compiler exists."""
    found = shutil.which("arm-none-eabi-gcc")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        pathlib.Path.home(),
        ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe",
    )
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    if not gcc.is_file():
        pytest.skip(f"no arm-none-eabi-gcc on PATH or at {gcc}")

    with tempfile.TemporaryDirectory() as tmp:
        elf = pathlib.Path(tmp) / "delay.elf"
        binary = pathlib.Path(tmp) / "delay.bin"
        subprocess.run(
            [str(gcc), "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-ffreestanding",
             "-nostdlib", "-T", str(HERE / "delay.ld"), "-o", str(elf),
             str(HERE / "delay.c")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [str(objcopy), "-O", "binary", str(elf), str(binary)],
            check=True, capture_output=True,
        )
        assert binary.read_bytes() == IMAGE.read_bytes(), (
            "timer/delay.bin does not match what timer/delay.c compiles to."
        )
