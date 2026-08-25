# OpenHardware — the Cortex-M0+ core against the rp2040js corpus.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The oracle is wrong in three places, and this file says exactly where
#
# 13,300 of 13,500 cases match outright. The other 200 are **oracle bugs**, not
# core bugs, and they are not skipped -- they are *predicted*. Each one asserts
# that the registers agree, that only C differs, and that the oracle's C is
# precisely the value rp2040js's own expression computes. If rp2040js is ever
# fixed, these predictions fail and this file is what tells us.
#
# Claiming an oracle is wrong is a strong claim, so here is the evidence, three
# independent lines of it:
#
# 1. **ARM DDI0419, `Shift_C`.** A shift of zero returns the carry it was given.
#    It does not compute a new one.
#
# 2. **The JavaScript.** rp2040js's ASRS (register) ends
#    `this.C = input & (1 << (shiftN - 1))`. At `shiftN == 0` that is
#    `1 << -1`, and JavaScript masks a shift count to five bits, so it
#    evaluates to `1 << 31` -- the carry becomes bit 31 of the input by
#    accident of the language, not by decision. `test_the_javascript_that_
#    produces_the_wrong_carry` demonstrates this rather than asserting it.
#
# 3. **rp2040js contradicts itself.** Its LSLS (immediate) writes
#    `this.C = imm5 ? ... : this.C` and its LSLS (register) writes
#    `this.C = shiftCount ? ... : this.C`. Both guard the shift-by-zero case.
#    ASRS (register) and RORS do not. The same file applies the rule twice and
#    omits it twice; the two that guard are the two that match the
#    architecture.
#
# The previous handoff already recorded that rp2040js was silicon-diffed once
# via gdbdiff and that the bugs found were "ADCS overflow, CMP carry and LSRS
# edges" -- the same neighbourhood as these three.
#
# **So: a passing run here means "agrees with rp2040js, except where rp2040js
# is demonstrably wrong."** That is weaker than the 8086 work's "agrees with an
# AMD D8088", and every claim built on it has to say so.

import pytest

from core.cortexm0.abi import Cpu, MemoryFault, Unimplemented
from tests.cortexm0.conftest import PC, SANDBOX, load_family

#: Every family the generator emits. Named here rather than globbed, so a
#: corpus that is missing a family fails loudly instead of quietly testing less.
FAMILIES = (
    "lsls_imm", "lsrs_imm", "asrs_imm",
    "adds_reg", "subs_reg", "adds_imm3", "subs_imm3",
    "movs_imm8", "cmp_imm8", "adds_imm8", "subs_imm8",
    "ands", "eors", "lsls_reg", "lsrs_reg", "asrs_reg", "adcs", "sbcs",
    "rors", "tst", "negs", "cmp_reg", "cmn", "orrs", "muls", "bics", "mvns",
)

C_FLAG = 1 << 29

#: How many cases the standard corpus holds: every family at `--count 500`,
#: which is what `tools/get_armv6m_tests.sh` runs.
#:
#: A floor rather than an equality. Generating MORE is always fine and is what
#: somebody chasing a rare flag case would do; generating fewer silently is
#: the failure this guards, because `--count` is a command-line argument and
#: forgetting it costs 99.6% of the check with nothing to show for it.
CASES_PER_FAMILY = 500
EXPECTED_CASES = len(FAMILIES) * CASES_PER_FAMILY


def oracle_carry_bug(family: str, encoding: int, regs: list[int]) -> int | None:
    """The C flag rp2040js produces where its code is wrong, else None.

    This reimplements the *bug*, deliberately. Predicting the wrong answer is
    what makes the divergence a checked fact rather than an excuse: a case that
    diverges some other way is still a failure.
    """
    rdn = encoding & 0x7
    rm = (encoding >> 3) & 0x7
    value = regs[rdn]
    amount = regs[rm] & 0xFF

    if family in ("asrs_reg", "rors") and amount == 0:
        # `1 << (0 - 1)` and `!!(result & 0x80000000)` respectively: both end
        # up reading bit 31 instead of leaving the carry alone.
        return (value >> 31) & 1
    if family == "lsls_reg" and amount > 32:
        # `1 << (32 - amount)` with a negative count, which JavaScript masks
        # to five bits. Exactly 32 is not a bug -- `1 << 0` reads bit 0, which
        # is what the architecture asks for -- so only `> 32` is listed.
        return (value >> ((32 - amount) & 31)) & 1
    return None


def run_case(cpu: Cpu, case: dict) -> tuple[list[int], int]:
    cpu.clear_memory()
    cpu.set_regs(case["initial"]["regs"], case["initial"]["flags"])
    cpu.write_halfword(PC, case["encoding"])
    # The generator writes a NOP after the instruction so a mis-sized fetch is
    # visible; mirrored here so memory matches what the oracle saw.
    cpu.write_halfword(PC + 2, 0xBF00)
    for index, word in enumerate(case["initial"]["ram"]):
        cpu.write_word(SANDBOX + index * 4, word)
    cpu.step()
    regs = cpu.get_regs()
    return regs.as_list(), regs.apsr


def test_every_family_the_generator_emits_is_present(corpus_dir):
    missing = [f for f in FAMILIES if not (corpus_dir / f"{f}.json.gz").is_file()]
    assert not missing, f"corpus is missing {missing}; regenerate it"


def test_the_whole_corpus_matches_except_where_the_oracle_is_wrong(corpus_dir, cpu):
    """The conformance run. One test, looping, because `tools/inventory.py`
    counts `def test_*` with `ast` and CLAUDE.md forbids parametrize."""
    unexplained = []
    predicted = 0
    total = 0

    for family in FAMILIES:
        for case in load_family(corpus_dir, family):
            total += 1
            got_regs, got_apsr = run_case(cpu, case)
            want_regs = case["final"]["regs"]
            want_apsr = case["final"]["flags"]
            if (got_regs, got_apsr) == (want_regs, want_apsr):
                continue

            bug = oracle_carry_bug(family, case["encoding"], case["initial"]["regs"])
            same_registers = got_regs == want_regs
            only_c_differs = (got_apsr & ~C_FLAG) == (want_apsr & ~C_FLAG)
            oracle_matches_bug = bug is not None and bool(want_apsr & C_FLAG) == bool(bug)

            if same_registers and only_c_differs and oracle_matches_bug:
                predicted += 1
                continue
            unexplained.append(
                f"{family} {case['name']}: encoding 0x{case['encoding']:04x}, "
                f"regs {'match' if same_registers else 'DIFFER'}, "
                f"apsr got 0x{got_apsr:08x} want 0x{want_apsr:08x}"
            )

    assert not unexplained, (
        f"{len(unexplained)} case(s) diverge from rp2040js in a way this file "
        f"does not explain:\n  " + "\n  ".join(unexplained[:10])
    )
    # **A floor, and not `>= len(FAMILIES)`.**
    #
    # That was the assertion here and it is worth naming what it allowed: the
    # generator's `--count` is a command-line argument, so a corpus rebuilt
    # with `--count 1` would be twenty-seven cases and pass. Every divergence
    # explained, nothing wrong, and the core checked against a twenty-seventh
    # of one per cent of what it used to be.
    #
    # `--count 500` is what `tools/get_armv6m_tests.sh` runs and what the
    # committed arrangement means, so the floor is the number that produces:
    # 27 families x 500. Regenerating smaller is a decision somebody has to
    # make on purpose, here, rather than by forgetting a flag.
    assert total >= EXPECTED_CASES, (
        f"only {total} cases ran, against {EXPECTED_CASES} expected. A corpus "
        f"generated with a smaller --count is not a smaller version of this "
        f"check, it is a different one -- regenerate with "
        f"tools/get_armv6m_tests.sh, or lower this on purpose."
    )
    # Not `== 200`: the count scales with --count. What must hold is that
    # every divergence was predicted, which the assertion above already
    # proved, and that divergences did not somehow vanish -- which would mean
    # the oracle changed and this file's reasoning needs rereading.
    assert predicted > 0, (
        "no predicted divergences. Either rp2040js fixed its three shift-carry "
        "bugs -- in which case delete oracle_carry_bug and this assertion -- or "
        "the corpus no longer covers the shift families."
    )


def test_the_javascript_that_produces_the_wrong_carry():
    """Demonstrate the oracle's bug rather than asserting it.

    `1 << -1` is `1 << 31` in JavaScript, because the language masks a shift
    count to five bits. Python does not, so the expression has to be spelled
    with the mask to reproduce it -- which is itself the point: the oracle's
    carry is a language accident, and this is what it evaluates to.
    """
    assert (1 << ((0 - 1) & 31)) == 0x80000000
    # And the LSLS large-shift case, for two amounts either side of the one it
    # gets right.
    assert (1 << ((32 - 32) & 31)) == 0x00000001   # correct: bit 0
    assert (1 << ((32 - 33) & 31)) == 0x80000000   # wrong: should be no carry
    assert (1 << ((32 - 40) & 31)) == 0x01000000   # wrong


def test_an_encoding_outside_the_slice_is_refused_not_executed(cpu):
    """`SVC` is 0xDF00. This core models no exceptions, so it must stop rather
    than behave like a NOP, and it must leave PC where it was.

    This test used to use `B` at 0xE000, and it failed the day branches were
    implemented -- which is the test doing its job. Whatever encoding stands
    here has to be one the core genuinely refuses; pretending an SVC returned
    would let a program continue past a call that never happened.
    """
    cpu.clear_memory()
    cpu.set_regs([0] * 15 + [PC], apsr=0)
    cpu.write_halfword(PC, 0xDF00)
    with pytest.raises(Unimplemented):
        cpu.step()
    assert cpu.get_regs().r[15] == PC


def test_a_fetch_outside_the_modelled_memory_is_a_fault_not_a_zero(cpu):
    """The peripheral space at 0x40000000 is real on an RP2040 and not modelled.

    Reading it as zero is the dangerous failure: firmware polls a clock's ready
    bit almost immediately, and a zero answer spins forever, which looks like a
    hang rather than a missing feature.

    Flash was the address here until flash became real. Both regions being
    modelled is why this now points at the peripherals.
    """
    cpu.clear_memory()
    cpu.set_regs([0] * 15 + [0x40000000], apsr=0)
    with pytest.raises(MemoryFault):
        cpu.step()


def test_the_core_has_no_memory_until_a_board_gives_it_some(cpu):
    """0x10000000 is flash on an RP2040 and nothing on this core.

    This test used to assert the opposite -- that flash was modelled -- back
    when the core hardcoded the RP2040's map. It does not, and that is the
    point: a SAMD21 shares this core and puts its flash at zero, so a core
    with an opinion about where flash lives could only ever serve one board.
    """
    cpu.clear_regions()
    with pytest.raises(MemoryFault):
        cpu.write_halfword(0x10000100, 0x2042)


def test_a_board_supplied_region_is_where_firmware_executes(cpu):
    """The counterpart. Once something adds flash, code runs from it."""
    cpu.clear_regions()
    cpu.add_region(0x10000000, 0x1000, executable=True, fill=0xFF)
    cpu.write_halfword(0x10000100, 0x2042)      # MOVS r0, #0x42
    cpu.set_regs([0] * 15 + [0x10000100], apsr=0)
    cpu.step()
    regs = cpu.get_regs()
    assert regs.r[0] == 0x42
    assert regs.r[15] == 0x10000102


def test_running_off_the_end_of_an_image_stops_instead_of_executing_zeros(cpu):
    """Erased flash reads 0xFF, which is what a real part reads and also the
    loud answer: 0xFFFF is not a valid Thumb encoding.

    Filling flash with zeros instead makes every untouched word `MOVS r0, r0`,
    so a program that runs past its own code executes a million no-ops and
    looks like it is working. Measured before this changed: 5,000 instructions
    of zero-filled flash with no fault at all.
    """
    cpu.clear_regions()
    cpu.add_region(0x10000000, 0x1000, executable=True, fill=0xFF)
    cpu.set_regs([0] * 15 + [0x10000000], apsr=0)
    with pytest.raises(Unimplemented):
        cpu.step()


def test_the_same_core_serves_a_board_with_a_different_memory_map(cpu):
    """The claim the layering exists for, tested rather than asserted.

    A SAMD21 shares this core with an RP2040 and puts its flash at zero rather
    than at 0x10000000. While the core held those addresses as `constexpr`,
    that claim was false and nothing noticed, because every test used an
    RP2040. So this builds a SAMD21-shaped map -- 256 KB of flash at 0, 32 KB
    of SRAM at 0x20000000 -- and runs an instruction out of it.

    It deliberately does **not** add `webui/boards/samd21.py`. Doing so would
    flip two boards to "runnable" in the catalogue on the strength of a memory
    map alone, with no peripherals and no image ever run on them.
    """
    cpu.clear_regions()
    cpu.add_region(0x00000000, 256 * 1024, executable=True, fill=0xFF)
    cpu.add_region(0x20000000, 32 * 1024, executable=True)

    cpu.write_halfword(0x00000100, 0x2077)          # MOVS r0, #0x77
    cpu.set_regs([0] * 15 + [0x00000100], apsr=0)
    cpu.step()
    assert cpu.get_regs().r[0] == 0x77

    # And its SRAM really is 32 KB, not the RP2040's 264 KB.
    assert cpu.in_range(0x20007FFC)
    assert not cpu.in_range(0x20009000)
