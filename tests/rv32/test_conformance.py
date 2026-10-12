# OpenHardware - the RV32 core against rvcpp, on the space rvcpp is right about.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Legal-space agreement, and the delta hazard that would fake it.

`test_gating.py` covers what each part must refuse, which rvcpp cannot answer.
This file covers the other half -- what the instructions actually compute --
where rvcpp is a good oracle and the only one that exists for RV32 here.

**A passing run means "agrees with rvcpp on encodings rvcpp is entitled to
execute".** That is weaker than the i8086 work's "agrees with an AMD D8088",
and weaker still than it looks, because rvcpp is a simulator by the same author
as the Hazard3 silicon rather than an independent reading of the manual. Every
claim built on it has to say so.

## The delta hazard, inherited from a format we do not control

`tools/gen_armv6m_tests.mjs` records why its corpus stores a *complete* final
state: SST8088 stores a delta, and `tools/sst8088.py` calls that "the one thing
that will bite a harness author", because a naive comparison checks the one
register the delta names and declares a pass.

rvcpp's trace is exactly such a delta -- one line per instruction, naming only
the register written. So this file cannot simply compare the named register. It
checks the named register *and* that every other register still holds what the
case put there. Without the second half, a core that wrote the right answer to
x12 and corrupted x11 would pass every case in the corpus.
"""

from __future__ import annotations

from tests.rv32.conftest import (
    CORPUS, FAMILIES, PC, TARGETS, every_case, legal_on, load_family,
)
from tests.rv32.test_gating import attempt, extension_mask


def run_case(cpu, abi, case: dict, target: str):
    """Execute one case, or return None if this core has no such instruction."""
    cpu.clear_memory()
    cpu.set_extensions(extension_mask(abi, TARGETS[target]))
    word = int(case["encoding"], 16)
    cpu.write_word(PC, word if case["width"] == 32 else word | (0x0001 << 16))
    initial = [0] * 32
    for number, value in case["initial"].items():
        initial[int(number)] = int(value, 16)
    cpu.set_regs(initial, pc=PC)
    try:
        cpu.step()
    except (abi.Unimplemented, abi.MemoryFault):
        return None
    except abi.Illegal:  # pragma: no cover - test_gating owns this axis
        return None
    return initial, cpu.get_regs()


def test_the_core_agrees_with_rvcpp_where_rvcpp_may_execute(cpu, abi):
    """Every executed case, on every target allowed to run it."""
    wrong = []
    compared = 0
    for family, case in every_case():
        oracle = case.get("rvcpp")
        if not oracle or oracle["status"] != "executed":
            continue
        for target in TARGETS:
            if not legal_on(case, target):
                continue
            outcome = run_case(cpu, abi, case, target)
            if outcome is None:
                continue
            initial, final = outcome
            compared += 1
            for number, value in oracle["writes"].items():
                index = int(number)
                if final.x[index] != value:
                    wrong.append(
                        f"{target} {family}/{case['mnemonic']} "
                        f"({case['encoding']}) initial={case['initial']}: "
                        f"x{index} is {final.x[index]:#010x}, rvcpp made it "
                        f"{value:#010x}")
    assert not wrong, "\n".join(wrong)
    assert compared, (
        "nothing was compared. Either the corpus lost its rvcpp cells or this "
        "core implements none of the encodings in it -- both are failures, and "
        "an empty comparison reporting success is what this guards against.")


def test_no_register_outside_the_oracles_delta_moves(cpu, abi):
    """The half that makes the comparison above mean anything.

    rvcpp's trace names one register per instruction. Checking only that
    register would pass a core that also scribbled on the other 31, which is
    precisely the false pass `tools/sst8088.py` warns about for the 8088 corpus.
    """
    wrong = []
    for family, case in every_case():
        oracle = case.get("rvcpp")
        if not oracle or oracle["status"] != "executed":
            continue
        written = {int(number) for number in oracle["writes"]}
        for target in TARGETS:
            if not legal_on(case, target):
                continue
            outcome = run_case(cpu, abi, case, target)
            if outcome is None:
                continue
            initial, final = outcome
            for index in range(32):
                if index in written:
                    continue
                if final.x[index] != initial[index]:
                    wrong.append(
                        f"{target} {family}/{case['mnemonic']} "
                        f"({case['encoding']}): x{index} moved from "
                        f"{initial[index]:#010x} to {final.x[index]:#010x}, and "
                        f"rvcpp wrote only {sorted(written)}")
    assert not wrong, "\n".join(wrong)


def test_the_corpus_records_the_oracle_for_every_case(cpu, abi):
    """No case may assert behaviour with no source for it.

    A case with no `rvcpp` cell and no `requires` would be an assertion from
    nowhere. Gating cases are allowed to have no oracle result to agree with --
    that is the point of them -- but they must carry the encoding-table
    citation that stands in for it.
    """
    unsourced = [
        f"{family}/{case['mnemonic']} ({case['encoding']})"
        for family, case in every_case()
        if "rvcpp" not in case and not case.get("requires_source")
    ]
    assert not unsourced, "\n".join(unsourced)


def test_every_family_the_generator_emits_is_named_in_families():
    """FAMILIES, the generator and the committed corpus name the same families.

    FAMILIES is named rather than globbed so that a missing file fails
    loudly. Nothing checked the other direction, and `rv32zcb` fell into it:
    generated and committed at OH-146, and read by no test until OH-219. The
    generator's names come from `build` without the oracle, so this runs on a
    machine with no rvcpp.
    """
    from tools import gen_rv32_tests

    emitted = set(gen_rv32_tests.build(1, want_oracle=False))
    committed = {path.stem for path in CORPUS.glob("*.json")}
    assert emitted == set(FAMILIES) == committed, (
        f"the generator emits {sorted(emitted)}, FAMILIES names "
        f"{sorted(FAMILIES)} and the corpus holds {sorted(committed)}. A "
        f"family left out of FAMILIES is one no test here reads."
    )


def test_rv32zcb_runs_whole_on_an_rp2350_and_the_c5_refuses_its_zbb_cases(cpu, abi):
    """The Zc family, every case on every target, from the corpus.

    The RP2350 has Zcb and Zbb, so every case executes there and leaves the
    registers rvcpp recorded. The ESP32-C5 has Zcb and no Zbb: it executes
    every case except those whose `requires` names Zbb -- the unaries whose
    chapter 27 pages say "Zbb is also required" -- and refuses exactly those
    as Illegal. The C3 and C6 have no Zcb and refuse every case. rvcpp
    executed all of them, so each refusal is the manual's verdict and not the
    oracle's.
    """
    cases = load_family("rv32zcb")
    split = {"Zbb" in case["requires"] for case in cases}
    assert split == {True, False}, (
        "rv32zcb no longer has cases both with and without Zbb, so the C5's "
        "half of this test would check nothing")
    wrong = []
    for case in cases:
        name = f"{case['mnemonic']} ({case['encoding']}) initial={case['initial']}"
        if case["rvcpp"]["status"] != "executed":
            wrong.append(f"rvcpp did not execute {name}")
            continue
        outcome = run_case(cpu, abi, case, "RP2350")
        if outcome is None:
            wrong.append(f"RP2350 did not execute {name}")
        else:
            final = outcome[1]
            for number, value in case["rvcpp"]["writes"].items():
                if final.x[int(number)] != value:
                    wrong.append(f"RP2350 {name}: x{number} is "
                                 f"{final.x[int(number)]:#010x}, rvcpp made it "
                                 f"{value:#010x}")
        expected = "illegal" if "Zbb" in case["requires"] else "executed"
        verdict = attempt(cpu, abi, case, "ESP32-C5")
        if verdict != expected:
            wrong.append(f"ESP32-C5 answered {verdict!r} for {name}, "
                         f"requires={case['requires']}; expected {expected!r}")
        for absent in ("ESP32-C3", "ESP32-C6"):
            verdict = attempt(cpu, abi, case, absent)
            if verdict != "illegal":
                wrong.append(f"{absent} answered {verdict!r} for {name}, which "
                             f"has no Zcb")
    assert not wrong, "\n".join(wrong[:20])
