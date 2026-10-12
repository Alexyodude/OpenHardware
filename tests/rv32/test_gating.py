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
    MODELLED, PC, SANDBOX, TARGETS, every_case, faithfully_configurable,
    legal_on, load_family,
)

#: Families the core does not implement yet, and why that is not a gating
#: failure. OH-34 is building the core now; when it lands, this set shrinks and
#: `test_the_core_reports_its_own_holes` is what notices. Listing them is what
#: keeps "unimplemented" from quietly absorbing "wrongly executed".
#: `rv32c` left on 2026-08-25 under OH-54. `refusal_is_testable` derives
#: from this set, so removing the entry tightened every compressed case
#: from "unimplemented is honest" to "must be refused per part" in one
#: edit -- which is what the comment below always promised it would.
#: `rv32m_op` left on 2026-08-25 under OH-55, `rv32c` under OH-54.
EXPECTED_HOLES = {"rv32a"}


def refusal_is_testable(case: dict) -> bool:
    """Whether this core can yet be asked to *refuse* this encoding.

    Gating a 16-bit encoding needs a 16-bit decoder. While `rv32c` was in
    EXPECTED_HOLES a compressed word could not distinguish "needs an extension
    I lack" from "is a shape I cannot read", and `Unimplemented` was the honest
    answer rather than a wrong one. OH-54 wrote the decoder, so every
    compressed case is now testable and this returns True throughout.

    Derived from EXPECTED_HOLES rather than listed separately, so when OH-34
    lands the C decoder every caller tightens at once and there is no second
    list to forget.
    """
    return case["width"] == 32 or "rv32c" not in EXPECTED_HOLES


def extension_mask(abi, names) -> int:
    """Extension names to the bitmask `core/riscv32/abi.py` uses.

    Only the modelled ones. An unmodelled name is dropped rather than raising,
    because a target legitimately has extensions this core cannot represent --
    `faithfully_configurable` is what decides whether that matters for the case
    in hand, and doing it here as well would make one question two.
    """
    bits = {
        "M": abi.EXT_M,
        "A": abi.EXT_A,
        "C": abi.EXT_C,
        "Zba": abi.EXT_ZBA,
        "Zbb": abi.EXT_ZBB,
        "Zbkb": abi.EXT_ZBKB,
        "Zcb": abi.EXT_ZCB,
        "Zcmp": abi.EXT_ZCMP,
        "Zcmt": abi.EXT_ZCMT,
        "Zbs": abi.EXT_ZBS,
        "Xh3bextm": abi.EXT_XH3BEXTM,
    }
    assert set(bits) == set(MODELLED), (
        f"MODELLED says {sorted(MODELLED)} and this map has {sorted(bits)}. "
        f"They are the same list written twice and must not drift: a name in "
        f"MODELLED with no bit here would be silently dropped from every mask."
    )
    mask = 0
    for name in names:
        if name in bits:
            mask |= bits[name]
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
            if not faithfully_configurable(case, target):
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
            if not faithfully_configurable(case, target):
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


def test_zba_is_refused_on_both_esp32_parts_and_run_on_an_rp2350(cpu, abi):
    """The gating case OH-42 adds, from the corpus rather than by hand.

    Neither ESP32-C part has Zba: the C3 is RV32IMC and the C6 RV32IMAC. The
    RP2350's datasheet string has `_zba_`. So one encoding, three parts, two
    different correct answers -- and rvcpp executes it for all three
    (`rv_core.cpp:265`), which is why the verdict is derived from the
    extension letters instead.
    """
    case = load_family("rv32zba")[0]
    assert case["requires"] == ["Zba"], case

    for absent in ("ESP32-C3", "ESP32-C6"):
        assert attempt(cpu, abi, case, absent) == "illegal", (
            f"{case['mnemonic']} ({case['encoding']}) was not refused on an "
            f"{absent}. {case['requires_source']}"
        )
    assert attempt(cpu, abi, case, "RP2350") == "executed", (
        f"{case['mnemonic']} was not executed on an RP2350, whose datasheet "
        f"ISA string contains _zba_"
    )
    assert case["rvcpp"]["status"] == "executed", (
        "the corpus no longer records rvcpp executing this, so the premise "
        "that the oracle cannot see gating needs rechecking"
    )


def test_zbs_is_refused_on_both_esp32_parts_and_run_on_an_rp2350(cpu, abi):
    """The second extension whose three targets do not agree, from the corpus.

    Worth its own case beside the Zba one rather than left to the sweep,
    because Zbs is the first group whose encodings live under **two** opcodes:
    the register forms under OP and the immediates under OP_IMM, sharing a
    funct3 with SLLI and SRLI. A core could gate one opcode and not the other
    and the sweep would still pass on whichever half it happened to reach
    first, so both are asserted here by name.
    """
    cases = load_family("rv32zbs")
    assert all(case["requires"] == ["Zbs"] for case in cases)

    opcodes = {int(case["encoding"], 16) & 0x7F for case in cases}
    assert opcodes == {0x33, 0x13}, (
        f"the Zbs family covers opcodes {sorted(hex(o) for o in opcodes)}; both "
        f"the register forms (0x33) and the immediates (0x13) must be in it"
    )

    for opcode in sorted(opcodes):
        case = next(c for c in cases if int(c["encoding"], 16) & 0x7F == opcode)
        for absent in ("ESP32-C3", "ESP32-C6"):
            assert attempt(cpu, abi, case, absent) == "illegal", (
                f"{case['mnemonic']} ({case['encoding']}) was not refused on an "
                f"{absent}. {case['requires_source']}"
            )
        assert attempt(cpu, abi, case, "RP2350") == "executed", (
            f"{case['mnemonic']} was not executed on an RP2350, whose datasheet "
            f"ISA string contains _zbs_"
        )
        assert case["rvcpp"]["status"] == "executed", (
            "rvcpp no longer executes this, so the premise that the oracle "
            "cannot see gating needs rechecking"
        )


def test_the_c_and_zca_equivalence_is_only_claimed_for_parts_without_an_fpu(cpu, abi):
    """Why `C` is in the RP2350's set when its ISA string says `zca`.

    `C` is `Zca` + `Zcf` + `Zcd`; `Zcf` needs F and `Zcd` needs D. On a part
    with neither, `C` and `Zca` cover the same encodings and the substitution
    is sound. The `absent_extension` family is the proof that this core does
    not merely assume it: those cases are `C.FLW`/`C.FLWSP`, which are the
    encodings the equivalence *excludes*, and every target must still refuse
    them.

    If a part with an FPU is ever added to TARGETS, this test is what should
    fail first -- before some corpus case quietly starts passing on it.
    """
    fpu_cases = [c for c in load_family("absent_extension") if c["requires"] == ["F"]]
    assert fpu_cases, "the F cases that make this argument checkable are gone"

    for target, extensions in TARGETS.items():
        assert "F" not in extensions and "D" not in extensions, (
            f"{target} has an FPU, so `C` may no longer stand in for `Zca` in "
            f"its extension set: C.FLW and C.FLWSP become legal on it and the "
            f"corpus would start calling them illegal"
        )
    for case in fpu_cases:
        for target in TARGETS:
            assert not legal_on(case, target)


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
            if not faithfully_configurable(case, target):
                continue
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

    # The ESP32-C5, which has a board description and three extension groups
    # A C5 stopped being "a C6 as far as this core can go" at OH-146: all
    # three Zc groups have bits and implementations now, so the full TARGETS
    # row must equal the abi's own ESP32_C5 constant -- the mask
    # `webui/boards/esp32c5.py` hands over once its EXECUTES grows the
    # groups.
    assert extension_mask(abi, TARGETS["ESP32-C5"]) == abi.ESP32_C5, (
        "the C5's own mask covers every group the part has"
    )
    assert TARGETS["ESP32-C5"] - MODELLED == set(), (
        f"the C5's unmodelled groups are "
        f"{sorted(TARGETS['ESP32-C5'] - MODELLED)}: OH-146 modelled all "
        f"three Zc groups, so a nonempty set here is a regression -- or a "
        f"new datasheet row nobody implemented"
    )
    # Imported here rather than at module scope: this is the only test in the
    # file that reaches out of `core/riscv32` into a board description, and a
    # top-level import would make every other one depend on `webui/`.
    from webui.boards import esp32c5

    assert set(esp32c5.ABSENT) == TARGETS["ESP32-C5"] - MODELLED

    # The RP2350 is one constant (OH-219): `abi.RP2350` is the mask its board
    # configures, and it must be this row through this map. Until OH-219 the
    # test held a second, narrower constant here, without the Zbb and Zbkb
    # OH-208 had modelled, while the board ran the wider one unchecked.
    assert extension_mask(abi, TARGETS["RP2350"]) == abi.RP2350, (
        f"TARGETS['RP2350'] & MODELLED is "
        f"{sorted(TARGETS['RP2350'] & MODELLED)}, whose mask is "
        f"{extension_mask(abi, TARGETS['RP2350']):#x}, but "
        f"abi.RP2350 is {abi.RP2350:#x}"
    )
    assert abi.EXT_ZBA & abi.RP2350 != 0, "the RP2350 has Zba"
    assert abi.EXT_ZBA & abi.ESP32_C6 == 0, "an ESP32-C6 does not"
    # What the row has and MODELLED lacks is one name, and it is a spelling
    # rather than an extension: `kExtC` stands for Zca on a part with no FPU
    # (`test_the_c_and_zca_equivalence_is_only_claimed_for_parts_without_an_fpu`).
    assert TARGETS["RP2350"] - MODELLED == {"Zca"}, (
        f"the RP2350's unmodelled names are "
        f"{sorted(TARGETS['RP2350'] - MODELLED)}. Any but Zca is a datasheet "
        f"group with no bit, and `faithfully_configurable` excludes every "
        f"case needing it from every sweep here instead of asserting it. No "
        f"Zca means it has a bit of its own, and conftest.py's reasoning "
        f"for spelling it C has to change with it."
    )
