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
FAMILIES = ("rv32i_op", "rv32m_op", "rv32a", "rv32c", "absent_extension")

#: rvcpp's map, so a captured final state means the same thing on both sides.
#: From `third_party/hazard3/test/sim/rvcpp/main.cpp`: `RAM_BASE 0x80000000`
#: and a reset vector of `RAM_BASE + 0x40`.
RAM_BASE = 0x80000000
RAM_SIZE = 0x4000
PC = RAM_BASE
SANDBOX = RAM_BASE + 0x1000

#: The two parts that make the gating question concrete, as extension letters.
#: The letters are the citable thing -- `docs/architectures.md` 4.2 quotes the
#: C3 datasheet as **RV32IMC, no A** -- and `core.riscv32.abi` holds the
#: matching bitmasks. Both are named here so a disagreement between them is a
#: test failure rather than a silent reinterpretation.
TARGETS = {
    "ESP32-C3": frozenset("MC"),
    "ESP32-C6": frozenset("MAC"),
}


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
