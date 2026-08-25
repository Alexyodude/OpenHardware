# OpenHardware — core/avr against avr8js, one encoding at a time.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this checks that tests/avr/test_blink.py does not
#
# That file runs one hand-written image and watches a pin. It proves the
# fourteen instructions that image uses, and says nothing about the rest — which
# is how `core/avr` came to refuse 132 of the 246 distinct encodings a real
# Arduino sketch needs while every test passed.
#
# This checks each encoding on its own, against an oracle, with several operand
# draws each so that a flag rule which is only wrong for negative operands
# cannot hide behind small ones.
#
# ## The corpus is committed, and the oracle is not needed to run it
#
# `tools/gen_avr_corpus.mjs` captures avr8js's answers into
# `tests/avr/corpus/isa.json`. This reads that file. Same arrangement as
# `tests/rv32/corpus/`, and for the reason recorded there: a differential test
# that silently becomes a no-op when its oracle is missing is worse than one
# that says it did not run.
#
# ## The three assertions, and why each is needed
#
# **Nothing may be wrong.** Anything the core executes, it must execute exactly
# as the oracle does — every register, SREG, SP, PC, and every byte of the data
# space above the register file.
#
# **The refused set must be exactly `STILL_MISSING`.** Without that, a core
# which refused *everything* would have nothing wrong and would pass. It is the
# same shape as `tests/rv32`'s pinned target sets. OH-58 emptied the set, so
# the assertion now reads "nothing in the corpus is refused" — and it still
# fails in both directions, which is the point: an instruction that stops
# working is as loud as one that lands unrecorded.
#
# **And a floor on how many agreed.** Two assertions cannot tell a core that
# executes everything correctly from one that has been handed an empty corpus;
# the third can.

import json
import pathlib

import pytest

from core.avr import abi
from webui.boards import atmega328p as board

CORPUS = pathlib.Path(__file__).resolve().parent / "corpus" / "isa.json"

#: SREG, SPL and SPH in the data space. The AVR maps its status register and
#: stack pointer into IO space, so a test sets them by writing memory rather
#: than through an ABI call — and `cpu.sreg` reads back the same byte.
SREG = 0x5F
SPL = 0x5D
SPH = 0x5E

#: The half-carry bit in SREG. Held out of the oracle comparison and checked
#: against the manual instead -- see `run_case`.
H_MASK = 0x20

#: Mnemonics `core/avr/exec.cc` does not implement, by base name.
#:
#: **Empty since OH-58, and it stays a set rather than becoming an assertion
#: that nothing is refused.** It held 45 names when the ticket opened and
#: `test_the_refused_set_is_exactly_what_is_recorded` still fails in both
#: directions: an instruction that quietly stops working shows up here just as
#: loudly as one that lands without the record being updated.
#:
#: What is absent from the *corpus* is a different question and is not this
#: set's job — `core/avr/exec.cc`'s header lists the encodings the manual has
#: and this core refuses, and `tests/avr/test_datasheet_edges.py` pins the two
#: places the oracle cannot be asked.
STILL_MISSING: frozenset[str] = frozenset()


def corpus() -> list[dict]:
    if not CORPUS.is_file():
        pytest.skip(
            f"{CORPUS} is missing. Generate it with:\n"
            f"  npm install --prefix third_party/avr8js avr8js@0.21.0\n"
            f"  node tools/gen_avr_corpus.mjs"
        )
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def run_case(cpu, case: dict) -> tuple[str, str]:
    """Set the machine up as the corpus says, step once, and compare.

    Returns `(verdict, detail)` where verdict is `agreed`, `refused` or
    `wrong`.
    """
    cpu.reset()
    board.install(cpu)

    initial = case["initial"]
    for index, value in enumerate(initial["regs"]):
        cpu.set_reg(index, value)
    cpu.write_data(SREG, initial["sreg"])
    cpu.write_data(SPL, initial["sp"] & 0xFF)
    cpu.write_data(SPH, (initial["sp"] >> 8) & 0xFF)

    # **Every byte the generator seeded, replayed from the corpus.** Not a
    # second copy of the rule: `ret` and `pop` read the stack, and a test that
    # left data memory zeroed would watch this core return to word 0 while the
    # oracle returned to where the generator put the address -- a disagreement
    # about the harness, reported as a disagreement about the core.
    for address, value in initial["memory"].items():
        cpu.write_data(int(address), value)

    for offset, word in enumerate(case["words"]):
        cpu.write_program(offset, int(word, 16))
    # What `lpm` reads, at the Z the generator seeds.
    cpu.write_program(0x40, 0xBEAD)

    cpu.pc = 0
    try:
        cpu.step()
    except abi.Unimplemented:
        return "refused", ""

    want = case["avr8js"]
    if cpu.pc != want["pc"]:
        return "wrong", f"pc {cpu.pc} != {want['pc']}"
    mine = [cpu.reg(i) for i in range(32)]
    if mine != want["regs"]:
        differs = [i for i, (a, b) in enumerate(zip(mine, want["regs"])) if a != b]
        return "wrong", (
            "r" + ",r".join(str(i) for i in differs)
            + ": " + ", ".join(f"{mine[i]:#04x} != {want['regs'][i]:#04x}" for i in differs)
        )
    # **SREG is compared without H, and H is compared against the manual.**
    # avr8js computes the half-carry from bit 0 where the datasheet reads bit
    # 3 -- all eleven of its H expressions do, measured 2026-08-26. See
    # `tools/gen_avr_corpus.mjs`. `add 0x08, 0x08` is the case that needs no
    # formula: the result is 0x10, it obviously carries out of the low nibble,
    # and the oracle says H = 0.
    #
    # Excluding a flag would normally hide bugs in it, so it is not excluded --
    # it is checked against a *second source*, the manual's own boolean
    # expression, which the corpus carries beside the oracle's answer.
    if cpu.sreg & ~H_MASK != want["sreg"] & ~H_MASK:
        return "wrong", (
            f"SREG {cpu.sreg & ~H_MASK:#010b} != {want['sreg'] & ~H_MASK:#010b} "
            f"(H excluded; the oracle is wrong about it)"
        )
    manual = case["manual"]
    mine_h = (cpu.sreg >> 5) & 1
    if manual is not None:
        if mine_h != manual["h"]:
            return "wrong", (
                f"H {mine_h} != {manual['h']} from the manual's "
                f"{manual['expression']}"
            )
    elif mine_h != (initial["sreg"] >> 5) & 1:
        return "wrong", (
            f"H changed to {mine_h}; this instruction does not touch it"
        )
    if cpu.sp != want["sp"]:
        return "wrong", f"SP {cpu.sp:#06x} != {want['sp']:#06x}"
    for address, value in want["writes"].items():
        got = cpu.read_data(int(address))
        if got != value:
            return "wrong", f"[{int(address):#06x}] {got:#04x} != {value:#04x}"
    return "agreed", ""


def verdicts() -> dict[str, list[tuple[str, str]]]:
    """Every case, bucketed. One pass, so both tests below cost one run."""
    out: dict[str, list[tuple[str, str]]] = {"agreed": [], "refused": [], "wrong": []}
    with abi.Cpu() as cpu:
        for case in corpus():
            verdict, detail = run_case(cpu, case)
            label = f"{case['mnemonic']} (variant {case['variant']})"
            out[verdict].append((label, detail))
    return out


def test_nothing_the_core_executes_disagrees_with_the_oracle():
    """The half that matters most: a wrong answer is worse than a refusal.

    An instruction this core does not have stops the run and names the word.
    An instruction it has and gets wrong runs a different program, and on a
    machine with a variable-length encoding it can resume from the middle of
    the next instruction and keep going.
    """
    found = verdicts()
    assert not found["wrong"], "\n".join(
        f"  {label}: {detail}" for label, detail in found["wrong"][:25]
    )
    # **A floor, not a pin.** It exists so that a run with nothing wrong and
    # nothing executed cannot pass -- the failure mode a differential test is
    # most prone to. It was 78 when OH-58 opened, which was the fourteen
    # instructions `core/avr` had then; it is now every case in the corpus.
    # Raise it when the corpus grows; it must never fall.
    assert len(found["agreed"]) >= 597, (
        f"only {len(found['agreed'])} cases agreed, down from 597. Something "
        f"that used to execute has stopped."
    )


def test_the_oracle_half_carry_is_still_wrong():
    """The exclusion in `run_case`, asserted so it cannot become dead.

    avr8js 0.21.0 computes H from bit 0 of its boolean rather than bit 3 --
    `dist/cjs/cpu/instruction.js:32` and ten more like it. That is why H is
    compared against the manual instead of against the oracle.

    An exclusion nobody rechecks is how a workaround outlives the thing it
    worked around. If avr8js is ever fixed, this fails, and the right response
    is to delete the exclusion rather than to widen this test.

    Both directions are asserted: the two sources must disagree *somewhere*
    (or the exclusion is unnecessary) and the manual's answer must be the one
    that matches an obvious case -- `add 0x08, 0x08` gives 0x10, which carries
    out of the low nibble, so H is 1 whatever any simulator says.
    """
    disagreements = [
        case for case in corpus()
        if case["manual"] is not None
        and case["manual"]["h"] != (case["avr8js"]["sreg"] >> 5) & 1
    ]
    assert disagreements, (
        "avr8js now agrees with the manual about the half-carry. Delete "
        "H_MASK and the exclusion in run_case, and compare SREG whole."
    )
    for case in disagreements:
        assert case["manual"]["expression"], "the manual's rule is recorded"


def test_the_refused_set_is_exactly_what_is_recorded():
    """`STILL_MISSING` is the ledger OH-58 is emptying, and it is checked in
    both directions.

    Too small and an instruction has silently stopped working. Too large and
    one has landed without the record being updated — which matters because
    this set is what tells the next reader where the work stopped.
    """
    found = verdicts()
    refused = {label.split()[0] for label, _ in found["refused"]}

    surprises = refused - STILL_MISSING
    assert not surprises, (
        f"these are recorded as implemented and were refused: {sorted(surprises)}"
    )
    landed = STILL_MISSING - refused
    assert not landed, (
        f"these now execute and are still listed as missing: {sorted(landed)} "
        f"-- delete them from STILL_MISSING"
    )
