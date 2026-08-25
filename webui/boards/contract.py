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

## And then a machine arrived that had no vector table

`VECTOR_TABLE_OFFSETS` was one of two universal requirements here, on the
strength of a caller that could be named. The caller was real; what was wrong
was the word *universal*. `core/avr` is the first non-Arm core a board can use,
and an AVR begins executing at address zero -- so an Arduino Uno description
could satisfy this contract only by declaring `(0,)` and meaning nothing by it,
after which the catalogue would report the board runnable while nothing could
enter it.

The fix is to ask the core. `core_requirements(core)` reads `REQUIRES` out of
`core/<core>/machine.py`, so "where does the reset vector sit" is asked of
boards on a machine that has one and of no others. `REQUIRED` keeps only what
survives that test on every machine, which today is `install`.

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

from webui.boards import catalogue

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


#: What every board must define, whatever machine it is. **One entry.**
#:
#: It used to be two. `VECTOR_TABLE_OFFSETS` was the other, and it was here on
#: the strength of a caller -- `api.py _place()` -- that turned out to be
#: asking on behalf of one instruction set rather than all of them. An AVR
#: begins executing at address zero and has no such table, so a universal
#: requirement for it would have forced `webui/boards/atmega328p.py` to declare
#: `(0,)` and mean nothing by it. The catalogue would then have reported
#: Arduino Uno runnable while nothing could enter it, which is the
#: claim-you-cannot-keep failure `rules/board-claims.md` exists to prevent,
#: arriving through a door nobody was watching.
#:
#: So it moved to `core_requirements`, below. What is left here is genuinely
#: universal: a board with no `install(cpu)` maps no memory on any machine.
#:
#: Kept short on purpose. The temptation with a contract is to write down what
#: a board *ought* to have; what makes this one hold is that every entry breaks
#: something specific when absent, and the failure is quoted in `why`.
REQUIRED: tuple[Requirement, ...] = (
    Requirement(
        "install",
        "webui/api.py runtime_for(): a board with no install(cpu) maps no "
        "memory, so an image has nothing to load into",
    ),
)


def core_requirements(core: str) -> tuple[Requirement, ...]:
    """What `core/<core>/machine.py` asks of a board, on top of `REQUIRED`.

    **The core is asked rather than listed here**, which is the whole of the
    entry-model fix. `core/cortexm0/machine.py` needs `VECTOR_TABLE_OFFSETS`
    because it reads an initial stack pointer and a reset handler out of two
    words; `core/avr/machine.py` needs nothing, because an AVR begins at word
    zero. Neither fact belongs in a module that speaks HTTP, and neither
    belongs to *boards in general*.

    Raises when the core has no `machine` module, rather than answering "this
    board owes nothing". A core that cannot host a board is a fact worth
    saying: `core/riscv32` is built today and has no `machine.py`, so no
    RISC-V board can be entered, and reporting an empty requirement list would
    make that look like a board that satisfies everything.
    """
    name = f"core.{core}.machine"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as error:
        raise RuntimeContractError(
            f"the {core} core cannot host a board: {name} does not exist, so "
            f"nothing knows how this machine powers on or what its registers "
            f"are called. See core/cortexm0/machine.py for the shape."
        ) from error
    return tuple(Requirement(part, why) for part, why in module.REQUIRES)


def requirements(core: str | None = None) -> tuple[Requirement, ...]:
    """Everything a board on `core` must supply.

    `core=None` asks only what is universal, which is what a caller that does
    not yet know the machine can check. It is the weaker question and it says
    so by needing an argument to become the strong one.
    """
    if core is None:
        return REQUIRED
    return REQUIRED + core_requirements(core)


def missing(module: types.ModuleType, core: str | None = None) -> list[str]:
    """Every required part `module` does not supply, named.

    A list rather than the first failure, so a board written from scratch
    learns everything it owes in one run instead of one per attempt.
    """
    return [
        requirement.name
        for requirement in requirements(core)
        if not hasattr(module, requirement.name)
    ]


def check(module: types.ModuleType, core: str | None = None) -> None:
    """Raise unless `module` supplies everything, naming what it does not.

    The message carries the `why` as well as the name, because "SAMD21 is
    missing VECTOR_TABLE_OFFSETS" tells a reader what to type and not what to
    put in it.
    """
    wanted = requirements(core)
    absent = missing(module, core)
    if not absent:
        return
    reasons = "\n".join(
        f"  {requirement.name}: {requirement.why}"
        for requirement in wanted
        if requirement.name in absent
    )
    machine = "" if core is None else f" as a {core} board"
    raise RuntimeContractError(
        f"{module.__name__} does not satisfy the runtime board contract"
        f"{machine}. Missing {', '.join(absent)}:\n{reasons}"
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


def core_for(module: types.ModuleType) -> str:
    """Which core a board module's chip runs on -- `rp2040` -> `cortexm0`.

    The inverse of `webui/api.py`'s `description_module`, and it has to
    normalise the same way `catalogue.described_chips` does, because a module
    stem is lowercase and undelimited while `catalogue.CHIPS` spells its keys
    the way the vendor does: the file is `atmega328p.py` and the chip is
    `ATmega328P`.

    Raises rather than returning None. A board module whose chip is not in the
    survey cannot be checked against any core's requirements, and answering
    "no core" would let it pass a contract nobody applied.
    """
    stem = module.__name__.rsplit(".", 1)[-1]
    wanted = stem.upper().replace("-", "")
    for chip, (_isa, core) in catalogue.CHIPS.items():
        if chip.upper().replace("-", "") == wanted:
            return core
    raise RuntimeContractError(
        f"{module.__name__} describes a chip that catalogue.CHIPS does not "
        f"list, so there is no core to check it against. Expected one of "
        f"{', '.join(sorted(catalogue.CHIPS))}"
    )
