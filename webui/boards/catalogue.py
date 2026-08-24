#!/usr/bin/env python3
# OpenHardware - what each board is, and whether it can run anything.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Answer, per board: what chip, what instruction set, and can it run firmware?

The board list itself is already generated (`tools/inventory.py`), and the
runnable-core list is already generated (`webui/targets.py`). Neither answers
the question a person actually asks, which is *"does this board work?"* -- and
that question has three separate parts that are easy to blur together:

1. **Which chip is on it.** Derived from the board's own name.
2. **Which instruction set that chip speaks.** A fact about silicon; not
   derivable from anything in this repository, so it is a cited table.
3. **Whether a core for that instruction set exists and is built**, and whether
   a board description exists to give it a memory map and peripherals. Both
   computed from the filesystem.

A board only reports as runnable when all of 3 holds. Nothing here is allowed
to say a board works because its chip is well known.

## The chip comes from the name, matched against the chips we know

A derivation rather than a stored field, because the board files do not carry
one -- they are KiCad footprints with pads, and inventing an `mcu` key in 26
JSON files would be exactly the hand-maintained list this repository keeps
deleting.

**The rule is "longest known chip that the name starts with", not "the middle
field".** The obvious middle-field rule is wrong and was wrong here: the
package is not always one field. `XIAO-ESP32-C3-DIP-SMD` has a two-word
package and parsed as a chip called `ESP32-C3-DIP`, which then fell through to
"not in the survey" -- a board quietly filed as unknown while its two siblings
resolved correctly. Matching against `CHIPS` cannot do that, because a chip
that is not in the table raises instead.

The two boards that do not start with `XIAO-` at all (`Arduino Uno`, and
`XIAO-XIAO STM32C5-SMD` with its doubled prefix) are named explicitly rather
than silently mis-parsed.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

try:
    from tools import build_core
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools import build_core

BOARDS_DIR = pathlib.Path(__file__).resolve().parent

#: Instruction set per chip, and which core directory would implement it.
#:
#: **This is a fact table, not a generated one**, and it is the only such table
#: here. What ISA a chip speaks cannot be computed from this repository; it
#: comes from `docs/architectures.md`, which records the evidence class for
#: each row and the contradictions it found. `core` is the directory name a
#: core would live under, whether or not it exists yet -- that existence is
#: looked up, never assumed.
CHIPS: dict[str, tuple[str, str]] = {
    "RP2040": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    "SAMD21": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    "RP2350": ("Armv8-M (Cortex-M33) + RV32 (Hazard3)", "cortexm33"),
    "MG24": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF54l15": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF54LM20A": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF52840": ("Armv7E-M (Cortex-M4F)", "cortexm4"),
    "ESP32-C3": ("RV32IMC", "riscv32"),
    "ESP32-C5": ("RV32IMAC + Zcb/Zcmp/Zcmt", "riscv32"),
    "ESP32-C6": ("RV32IMAC", "riscv32"),
    "ESP32-S3": ("Xtensa LX7", "xtensa"),
    "ATmega328P": ("AVR", "avr"),
    # No product page confirms this part exists, and "STM32C5" is not an ST
    # family anyone could place. Recorded as unknown rather than guessed at --
    # see the 2026-08-24 handoff's known-limitations list.
    "STM32C5": ("unknown -- part not confirmed to exist", "unknown"),
}

#: Boards whose name does not follow `XIAO-<CHIP>-<PACKAGE>`. Named here so
#: they are handled, rather than parsed into something plausible and wrong.
IRREGULAR: dict[str, str] = {
    "Arduino Uno": "ATmega328P",
    # Seeed's own footprint really is doubled; `XIAO-XIAO STM32C5-SMD.kicad_mod`
    # exists in their KiCad library. Faithful, and still unparseable by rule.
    "XIAO-XIAO STM32C5-SMD": "STM32C5",
}


class CatalogueError(Exception):
    """A board this module cannot describe."""


@dataclasses.dataclass(frozen=True)
class Board:
    """One board, and the three separate facts about whether it works."""

    name: str
    chip: str
    isa: str
    core: str
    core_exists: bool
    core_built: bool
    described: bool

    @property
    def runnable(self) -> bool:
        """Every part must hold. A built core with no board description has no
        memory map and no peripherals; a description with no core has nothing
        to execute it."""
        return self.core_built and self.described

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "chip": self.chip,
            "isa": self.isa,
            "core": self.core,
            "core_exists": self.core_exists,
            "core_built": self.core_built,
            "described": self.described,
            "runnable": self.runnable,
        }


def chip_for(board_name: str) -> str:
    """The chip on a board, from its name.

    Raises rather than guessing. A board whose name this cannot parse is a
    board someone must look at -- silently filing it under an invented chip is
    how a catalogue starts lying.
    """
    if board_name in IRREGULAR:
        return IRREGULAR[board_name]
    if not board_name.startswith("XIAO-"):
        raise CatalogueError(
            f"cannot tell which chip is on {board_name!r}: it does not start "
            f"with XIAO-. Add it to IRREGULAR."
        )
    rest = board_name[len("XIAO-"):]
    # Longest first, so `ESP32-C3` wins over a hypothetical `ESP32`, and
    # case-insensitively, because Seeed spells nRF54l15 and nRF54LM20A
    # differently from each other.
    for chip in sorted(CHIPS, key=len, reverse=True):
        if rest.lower().startswith(chip.lower()):
            return chip
    raise CatalogueError(
        f"{board_name!r} names no chip in CHIPS. Add the chip with its "
        f"instruction set, citing docs/architectures.md."
    )


def board_names(directory: pathlib.Path | None = None) -> list[str]:
    """Every imported board, from the files rather than from a list."""
    directory = BOARDS_DIR if directory is None else directory
    return sorted(path.stem for path in directory.glob("*.json"))


def described_chips(directory: pathlib.Path | None = None) -> set[str]:
    """Chips with a board description module beside this file.

    `rp2040.py` describing an RP2040 is the convention, and it is a convention
    rather than a registry so that adding a chip is adding one file.
    """
    directory = BOARDS_DIR if directory is None else directory
    return {
        path.stem.upper().replace("-", "")
        for path in directory.glob("*.py")
        if path.stem not in ("__init__", "catalogue")
    }


def catalogue(directory: pathlib.Path | None = None) -> list[Board]:
    """Every board, with all three facts looked up rather than assumed."""
    cores = set(build_core.cores())
    described = described_chips(directory)

    out: list[Board] = []
    for name in board_names(directory):
        chip = chip_for(name)
        isa, core = CHIPS.get(chip, ("unknown -- not in the survey", "unknown"))
        core_exists = core in cores
        built = False
        if core_exists:
            try:
                built = build_core.library_path(core).is_file()
            except build_core.BuildError:
                built = False
        out.append(Board(
            name=name,
            chip=chip,
            isa=isa,
            core=core,
            core_exists=core_exists,
            core_built=built,
            described=chip.upper().replace("-", "") in described,
        ))
    return out


def missing_cores(directory: pathlib.Path | None = None) -> dict[str, list[str]]:
    """Instruction sets with boards waiting on them, and what each blocks.

    Ordered by the number of boards it would unlock, because that is the only
    ordering the backlog has that is not a guess.
    """
    waiting: dict[str, list[str]] = {}
    for board in catalogue(directory):
        if board.runnable:
            continue
        waiting.setdefault(board.isa, []).append(board.name)
    return dict(sorted(waiting.items(), key=lambda kv: (-len(kv[1]), kv[0])))
