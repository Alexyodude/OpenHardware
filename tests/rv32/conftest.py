# OpenHardware - fixtures for the RV32 conformance corpus.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The corpus, the two parts it is checked against, and the map both use.

Unlike `tests/cortexm0/conftest.py`, the corpus here is **committed** rather
than generated into a git-ignored `third_party/` tree. The reason is specific:
half of it asserts what a part must *refuse*, and that half needs no oracle at
all -- its verdicts come from the ISA manual's encoding tables. A corpus that
skipped when rvcpp was absent would skip in exactly the situation OH-35 exists
to cover, since rvcpp is the thing that cannot answer the question.

Regenerate with `python tools/gen_rv32_tests.py`, which does need the oracle.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CORPUS = pathlib.Path(__file__).parent / "corpus"

#: Every family the generator emits. Named rather than globbed, so a corpus
#: missing a family fails loudly instead of quietly testing less -- the same
#: contract `tests/cortexm0/test_conformance.py` keeps with its FAMILIES.
FAMILIES = ("rv32i_op", "rv32m_op", "rv32a", "rv32c", "rv32zba", "rv32zbs",
            "absent_extension")

#: rvcpp's map, so a captured final state means the same thing on both sides.
#: From `third_party/hazard3/test/sim/rvcpp/main.cpp`: `RAM_BASE 0x80000000`
#: and a reset vector of `RAM_BASE + 0x40`.
RAM_BASE = 0x80000000
RAM_SIZE = 0x4000
PC = RAM_BASE
SANDBOX = RAM_BASE + 0x1000

#: The parts that make the gating question concrete, as **what the datasheet
#: says the silicon has** -- not as what this core can model. The two are kept
#: apart on purpose; see `MODELLED` below.
#:
#: Written as explicit sets rather than `frozenset("MC")`. The string form was
#: fine while every extension was one letter and stops being fine the moment
#: one is not: `frozenset("Zba")` is `{"Z", "b", "a"}`, which would silently
#: make every target claim three extensions that do not exist.
#:
#: `docs/architectures.md` 4.2 quotes the C3 datasheet as **RV32IMC, no A**.
#: The RP2350 row is the datasheet's own ISA string, 3.8:
#:
#:     rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp
#:
#: **`C` appears in the RP2350 set and not in that string, and that is an
#: inference, stated here rather than buried.** The RISC-V spec defines `C` as
#: exactly `Zca` + `Zcf` + `Zcd`; `Zcf` needs F and `Zcd` needs D. The RP2350
#: has neither, so over the encodings that exist on it, `C` and `Zca` denote
#: the same legal set and a corpus case marked `requires: ["C"]` is legal on it.
#: `test_the_c_and_zca_equivalence_is_only_claimed_for_partitions_without_an_fpu`
#: pins that reasoning so it cannot be reused for a part with an FPU, where it
#: is false.
TARGETS = {
    "ESP32-C3": frozenset({"M", "C"}),
    "ESP32-C6": frozenset({"M", "A", "C"}),
    "RP2350": frozenset(
        {"M", "A", "C", "Zca", "Zba", "Zbb", "Zbs", "Zbkb", "Zcb", "Zcmp"}
    ),
}

#: What `core/riscv32` can be *told about* today: one entry per bit in
#: `core.riscv32.abi`. Deliberately smaller than the RP2350's row above.
#:
#: A target whose datasheet set exceeds this cannot be configured faithfully,
#: and the honest response is to say which cases that affects rather than to
#: shrink the target and assert that an RP2350 refuses `clz`. It does not; this
#: core simply cannot be told that it has Zbb yet.
MODELLED = frozenset({"M", "A", "C", "Zba", "Zbs"})


def faithfully_configurable(case: dict, target: str) -> bool:
    """Whether this core can be set up as `target` *for this case*.

    Configuring with `TARGETS[target] & MODELLED` gives the right verdict for
    every case except one kind: a case requiring something the target has and
    the core cannot represent. For those the core would answer `Illegal` where
    the silicon executes, so they are excluded and counted rather than
    asserted.

        correct verdict  : requires <= TARGETS[t]
        core's verdict   : requires <= (TARGETS[t] & MODELLED)
        these agree iff  : requires & (TARGETS[t] - MODELLED) is empty

    Note this does **not** exclude a case requiring something no target has --
    `absent_extension`'s F cases stay in, because F is in no target's set and
    both sides say illegal. Excluding them would delete the most valuable test
    in the suite.
    """
    return not (frozenset(case["requires"]) & (TARGETS[target] - MODELLED))


def load_family(family: str) -> list[dict]:
    path = CORPUS / f"{family}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing. The corpus is committed, so this means it was "
            f"deleted rather than never generated. Rebuild it with:\n"
            f"  python tools/gen_rv32_tests.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def every_case() -> list[tuple[str, dict]]:
    """(family, case) for the whole corpus, in a stable order."""
    return [(family, case) for family in FAMILIES for case in load_family(family)]


def legal_on(case: dict, target: str) -> bool:
    """Whether `target` must execute this encoding rather than refuse it.

    **Derived, never stored.** A per-target column in the corpus would be a
    third thing to keep in step with the encoding and the extension letters,
    and adding the C5 or an RP2350 would mean editing every row. This way a
    target is one entry in TARGETS.
    """
    return frozenset(case["requires"]) <= TARGETS[target]


@pytest.fixture(scope="session")
def abi():
    return pytest.importorskip("core.riscv32.abi")


@pytest.fixture()
def cpu(abi):
    """A core with rvcpp's memory map and no extensions enabled.

    Extensions are deliberately left off: `core/riscv32/abi.py` says nothing is
    enabled until a board says so, because a core that arrived believing it had
    M and C would be making a claim about a part before anyone said which part.
    Every test here says which part first.
    """
    with abi.Cpu() as instance:
        instance.add_region(RAM_BASE, RAM_SIZE)
        yield instance
