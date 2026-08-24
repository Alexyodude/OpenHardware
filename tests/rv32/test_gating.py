# OpenHardware - what each part must refuse, which the oracle cannot say.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The half of conformance that rvcpp is structurally unable to check.

`webui/boards/catalogue.py` records that rvcpp is "right on the legal space,
wrong at the illegal-instruction edge". These tests are that edge. Every
verdict here comes from the ISA manual's encoding tables, and the corpus
carries rvcpp's own behaviour beside it so the disagreement is a checked fact
rather than a remembered caveat.

The distinction the whole file rests on is already in `core/riscv32/abi.py`:
`Illegal` is a fact about the *part* -- an ESP32-C3 meeting an atomic -- while
`Unimplemented` is a hole in *this emulator*. Conflating them would make an
unfinished core look like a correctly strict one.
"""

from __future__ import annotations

from tests.rv32.conftest import (
    PC, SANDBOX, TARGETS, every_case, legal_on, load_family,
)

#: Families the core does not implement yet, and why that is not a gating
#: failure. OH-34 is building the core now; when it lands, this set shrinks and
#: `test_the_core_reports_its_own_holes` is what notices. Listing them is what
#: keeps "unimplemented" from quietly absorbing "wrongly executed".
EXPECTED_HOLES = {"rv32m_op", "rv32c", "rv32a"}


def refusal_is_testable(case: dict) -> bool:
    """Whether this core can yet be asked to *refuse* this encoding.

    Gating a 16-bit encoding needs a 16-bit decoder, and this core has none
    while `rv32c` is in EXPECTED_HOLES. Until then a compressed word cannot
    distinguish "needs an extension I lack" from "is a shape I cannot read",
    and `Unimplemented` is the honest answer rather than a wrong one.

    Derived from EXPECTED_HOLES rather than listed separately, so when OH-34
    lands the C decoder every caller tightens at once and there is no second
    list to forget.
    """
    return case["width"] == 32 or "rv32c" not in EXPECTED_HOLES


def extension_mask(abi, letters) -> int:
    """Extension letters to the bitmask `core/riscv32/abi.py` uses."""
    bits = {"M": abi.EXT_M, "A": abi.EXT_A, "C": abi.EXT_C}
    mask = 0
    for letter in letters:
        if letter not in bits:
            raise AssertionError(
                f"no bit in core.riscv32.abi for extension {letter!r}; "
                f"known: {sorted(bits)}"
            )
        mask |= bits[letter]
    return mask


def attempt(cpu, abi, case: dict, target: str) -> str:
    """Run one encoding on one target. Returns 'executed', 'illegal' or 'hole'."""
    cpu.clear_memory()
    cpu.set_extensions(extension_mask(abi, TARGETS[target]))
    word = int(case["encoding"], 16)
    if case["width"] == 32:
        cpu.write_word(PC, word)
    else:
        cpu.write_word(PC, word | (0x0001 << 16))   # a c.nop behind it
    regs = [0] * 32
    for number, value in case["initial"].items():
        regs[int(number)] = int(value, 16)
    cpu.set_regs(regs, pc=PC)
    try:
        cpu.step()
    except abi.Illegal:
        return "illegal"
    except abi.Unimplemented:
        return "hole"
    except abi.MemoryFault:
        return "executed"        # it decoded; the address is not the question
    return "executed"


def test_an_atomic_is_refused_on_a_c3_and_permitted_on_a_c6(cpu, abi):
    """The demonstration OH-35 exists for, on one encoding, both ways.

    An ESP32-C3 is RV32IMC and must raise illegal-instruction on an A-extension
    encoding. An ESP32-C6 is RV32IMAC and must not. rvcpp executes it for both,
    which is why the verdict below is sourced from the encoding table instead.
    """
    case = load_family("rv32a")[0]
    assert case["requires"] == ["A"], case

    assert attempt(cpu, abi, case, "ESP32-C3") == "illegal", (
        f"{case['mnemonic']} ({case['encoding']}) was not refused on an "
        f"ESP32-C3. It is RV32IMC: {case['requires_source']}"
    )
    assert attempt(cpu, abi, case, "ESP32-C6") != "illegal", (
        f"{case['mnemonic']} ({case['encoding']}) was refused on an ESP32-C6, "
        f"which is RV32IMAC and has the A extension."
    )
    # The oracle, on the same encoding, in the corpus rather than in a comment.
    assert case["rvcpp"]["status"] == "executed", (
        "the corpus no longer records rvcpp executing this. If rvcpp gained "
        "extension gating, this whole file's premise needs rechecking."
    )


def test_no_legal_encoding_is_refused_on_either_part(cpu, abi):
    """Gating must not over-reach: a permitted extension is never `Illegal`.

    This is the half that catches a core being *too* strict, which a lockstep
    run against rvcpp would also miss -- rvcpp executes everything, so a core
    that refused half the M extension would diverge without anyone learning
    that the refusal, not the arithmetic, was wrong.
    """
    wrong = []
    for family, case in every_case():
        for target in TARGETS:
            if not legal_on(case, target):
                continue
            if attempt(cpu, abi, case, target) == "illegal":
                wrong.append(f"{target} refused {family}/{case['mnemonic']} "
                             f"({case['encoding']}), requires={case['requires']}")
    assert not wrong, "\n".join(wrong)


def test_every_absent_extension_is_refused_on_every_part(cpu, abi):
    """The other half: an encoding whose extension is off must be `Illegal`.

    Not `Unimplemented`. A core that answered "I have not written that yet"
    where the part answers "I refuse that" would pass a lockstep run against
    rvcpp and still be wrong about the silicon.

    **One tolerance, and it is derived rather than listed.** Gating a 16-bit
    encoding requires a 16-bit decoder, and this core has none yet -- `rv32c`
    is in EXPECTED_HOLES. While that is true, a compressed encoding cannot
    distinguish "needs an extension I lack" from "is a shape I cannot read",
    and answering `Unimplemented` is the honest result rather than a wrong one.
    The moment OH-34 lands the C decoder, `rv32c` leaves EXPECTED_HOLES and
    this tolerance disappears on its own -- there is no second list to forget.
    """
    compressed_undecodable = "rv32c" in EXPECTED_HOLES
    wrong = []
    tolerated = 0
    for family, case in every_case():
        for target in TARGETS:
            if legal_on(case, target):
                continue
            verdict = attempt(cpu, abi, case, target)
            if verdict == "illegal":
                continue
            if verdict == "hole" and not refusal_is_testable(case):
                tolerated += 1
                continue
            wrong.append(
                f"{target} answered {verdict!r} for {family}/"
                f"{case['mnemonic']} ({case['encoding']}), which needs "
                f"{case['requires']} and must be refused. "
                f"Source: {case['requires_source']}")
    assert not wrong, "\n".join(wrong)

    if not compressed_undecodable:
        assert tolerated == 0, (
            "the C decoder exists now, so no compressed encoding may answer "
            "Unimplemented in place of Illegal.")


def test_the_oracle_executed_what_these_parts_must_refuse(cpu, abi):
    """rvcpp's blind spot, asserted from the corpus rather than remembered.

    Every case that no target may execute, which rvcpp executed anyway. If this
    ever finds none, rvcpp has gained extension gating and `catalogue.py`'s
    ORACLES entry, this file and OH-35 are all describing a fixed tool.
    """
    blind = [
        (family, case) for family, case in every_case()
        if not any(legal_on(case, target) for target in TARGETS)
        and case.get("rvcpp", {}).get("status") == "executed"
    ]
    assert blind, (
        "no case in the corpus is both universally illegal and executed by "
        "rvcpp. Either the corpus lost its absent_extension family or the "
        "oracle changed."
    )
    # And this core refuses every one of them, which is the point of the corpus.
    testable = [(f, c) for f, c in blind if refusal_is_testable(c)]
    assert testable or "rv32c" in EXPECTED_HOLES, (
        "every universally-illegal case is compressed and the C decoder is "
        "supposedly present, so refusal should be testable and is not.")
    for family, case in testable:
        for target in TARGETS:
            assert attempt(cpu, abi, case, target) == "illegal", (
                f"{target} did not refuse {case['mnemonic']} "
                f"({case['encoding']}) -- rvcpp executes it, so a lockstep run "
                f"would have agreed and both would be wrong."
            )


def test_the_core_reports_its_own_holes(cpu, abi):
    """Which families are unimplemented, kept separate from which are refused.

    OH-34 is still building this core, so some legal encodings answer
    `Unimplemented`. That is a hole in the emulator, not a claim about a part,
    and it is tracked here so it shrinks visibly rather than being tolerated
    silently. When a family drops out of EXPECTED_HOLES this fails and the set
    gets edited -- deliberately, by someone reading it.
    """
    holes = set()
    for family, case in every_case():
        for target in TARGETS:
            if legal_on(case, target) and attempt(cpu, abi, case, target) == "hole":
                holes.add(family)
    assert holes <= EXPECTED_HOLES, (
        f"new unimplemented families: {sorted(holes - EXPECTED_HOLES)}. "
        f"A family that used to execute now does not.")
    if holes < EXPECTED_HOLES:
        raise AssertionError(
            f"{sorted(EXPECTED_HOLES - holes)} is implemented now. Remove it "
            f"from EXPECTED_HOLES so the next regression is visible.")


def test_the_extension_letters_match_the_abi_bitmasks(abi):
    """TARGETS and `core.riscv32.abi`'s constants must not drift apart.

    Two spellings of one fact -- the letters here, ESP32_C3 and ESP32_C6 there.
    Nothing else would notice them disagreeing, and a wrong bitmask would make
    every gating assertion above test the wrong part.
    """
    assert extension_mask(abi, TARGETS["ESP32-C3"]) == abi.ESP32_C3
    assert extension_mask(abi, TARGETS["ESP32-C6"]) == abi.ESP32_C6
    assert abi.EXT_A & abi.ESP32_C3 == 0, "an ESP32-C3 is RV32IMC: no atomics"
    assert abi.EXT_A & abi.ESP32_C6 != 0, "an ESP32-C6 is RV32IMAC: atomics"
