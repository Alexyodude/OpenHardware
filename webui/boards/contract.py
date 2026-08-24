#!/usr/bin/env python3
# OpenHardware - what a board module must supply before firmware can run on it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The **runtime** board contract.

## This is not `tools/check_board_contract.py`

Two things in this repository are called "the board contract" and they have
nothing to do with each other. That one verifies a PICSimLab `bsim_`/`board_`
C++ pair covers `board.h`'s pure virtuals -- upstream's shape, checked against
upstream's headers. This one is about `webui/boards/<chip>.py`, which is ours,
is Python, and never meets PICSimLab at all.

The names are close enough to mislead, so every symbol here says *runtime* and
the test file is `test_board_runtime_contract.py`. If you are reading this
because a checker failed, check which one.

## What the contract was before this file

One line, in `webui/api.py`:

    if not hasattr(description, "install"):

That is the whole of it. `install(cpu)` is genuinely required and genuinely
sufficient to *load* an image -- but it is not sufficient to *enter* one, and
the missing half was not missing so much as misplaced. `api.py` also holds

    VECTOR_TABLE_OFFSETS = {"RP2040": (0, RP2040_BOOT2_BYTES)}
    UF2_FAMILY_BY_CHIP = {"RP2040": "RP2040"}

which are facts about a chip living in the module that speaks HTTP. Nothing
was wrong with them there while one board could run anything; the moment a
second one could, "where is this chip's vector table" became a question with
two answers and one home.

**So the contract is the list of things a board must answer, and each entry
names the caller that asks.** A requirement whose caller cannot be named is not
a requirement, it is a wish -- which is the failure mode the ticket warned
about: *"The contract must not become a list of registers a board is expected
to fill in."*

## What is deliberately not required, and why each

**Peripherals.** Not one. `rp2040.py`'s growth rule is that a peripheral is
added when a real image faults on it and not before, and a contract listing
peripherals would invert exactly that. A board with no UART is not
incomplete; it is a board no image has needed a UART from yet.

**Clock.** No caller. `webui/boards/rp2040.py` models virtual time as a rate
its TIMER declares, and nothing outside that peripheral reads it.

**Pin mux -- and this one is deferred rather than dismissed.** No board module
supplies pins today; the pad-to-chip-pin data lives in the index
`tools/import_pindefs.py` builds, which is OH-26's. Requiring pins here would
mean inventing the plumbing before a caller exists.

What must survive for whoever does wire it up is the measurement, because it
is not the obvious answer. Of 550 pads across 25 boards, **321 resolve to a
chip pin and 0 of those have a flat integer index.** Eight boards cannot be
described by an integer `pin` field at all -- SAMD21 `PA02`, MG24 `PC0`,
nRF54L15 `P2.08` -- because those vendors publish no flat GPIO numbering, and
an nRF54L15's `P0` is five pins wide, so the usual 32-per-port arithmetic
yields a number appearing in no Nordic document. **A pin is therefore a string
chip name with an optional integer**, never an integer. Reproduce with
`python tools/import_pindefs.py --all --summary`.
"""

from __future__ import annotations

import dataclasses
import importlib
import pathlib
import types

BOARDS_DIR = pathlib.Path(__file__).resolve().parent

#: Modules beside this one that are not board descriptions.
NOT_A_BOARD = frozenset({"__init__", "catalogue", "contract"})


class RuntimeContractError(Exception):
    """A board module does not supply something a caller needs.

    Named `Runtime` for the reason this module's docstring gives at length:
    `tools/check_board_contract.py` raises about a different contract
    entirely, and two exceptions called `ContractError` in one repository is a
    traceback nobody can place.
    """


@dataclasses.dataclass(frozen=True)
class Requirement:
    """One thing a board must supply, and the caller that asks for it.

    `why` is not documentation. It is the admission test: a requirement whose
    caller cannot be named in one sentence does not go in `REQUIRED`, because
    that is how a contract becomes a wish-list that every future board pays
    for.
    """

    name: str
    why: str


#: Everything a board module must define. Two entries, and each names a caller.
#:
#: Kept this short on purpose. The temptation with a contract is to write down
#: what a board *ought* to have; what makes this one hold is that both entries
#: break something specific when absent, and the failure is quoted in `why`.
REQUIRED: tuple[Requirement, ...] = (
    Requirement(
        "install",
        "webui/api.py runtime_for(): a board with no install(cpu) maps no "
        "memory, so an image has nothing to load into",
    ),
    Requirement(
        "VECTOR_TABLE_OFFSETS",
        "webui/api.py _place(): where the reset vector sits relative to the "
        "image base. An RP2040 image is linked past 256 bytes of boot2 and a "
        "SAMD21 image is not, so guessing one for the other enters at a word "
        "that is not a stack pointer",
    ),
)


def missing(module: types.ModuleType) -> list[str]:
    """Every required part `module` does not supply, named.

    A list rather than the first failure, so a board written from scratch
    learns everything it owes in one run instead of one per attempt.
    """
    return [
        requirement.name
        for requirement in REQUIRED
        if not hasattr(module, requirement.name)
    ]


def check(module: types.ModuleType) -> None:
    """Raise unless `module` supplies everything, naming what it does not.

    The message carries the `why` as well as the name, because "SAMD21 is
    missing VECTOR_TABLE_OFFSETS" tells a reader what to type and not what to
    put in it.
    """
    absent = missing(module)
    if not absent:
        return
    reasons = "\n".join(
        f"  {requirement.name}: {requirement.why}"
        for requirement in REQUIRED
        if requirement.name in absent
    )
    raise RuntimeContractError(
        f"{module.__name__} does not satisfy the runtime board contract. "
        f"Missing {', '.join(absent)}:\n{reasons}"
    )


def board_module_names(directory: pathlib.Path | None = None) -> list[str]:
    """Every `webui/boards/<chip>.py`, by module name.

    Derived from the directory rather than listed, the same convention
    `catalogue.described_chips` uses and for the same reason: adding a board
    stays "add one file".
    """
    directory = BOARDS_DIR if directory is None else directory
    return sorted(
        f"webui.boards.{path.stem}"
        for path in directory.glob("*.py")
        if path.stem not in NOT_A_BOARD
    )


def board_modules() -> list[types.ModuleType]:
    """Every board description, imported."""
    return [importlib.import_module(name) for name in board_module_names()]
