#!/usr/bin/env python3
# OpenHardware — reader for the SingleStepTests/8088 conformance corpus.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parse `SingleStepTests/8088` cases into something a harness can execute.

This corpus is the only **hardware** ground truth this project has. Every other
oracle here is software -- the protocol, the simulator, a datasheet -- and
`.claude/rules/conformance-fixtures.md` §7 says so plainly. These cases were
captured from a physical AMD D8088 (8441DMA, 1982) in Maximum Mode, so a core
that matches them matches silicon, not another emulator's opinion.

## The one thing that will bite a harness author

**`final` is a delta, not a state.** V2 of the suite records only what changed:

    "initial": {"regs": {"ax": 22348, ..., "ip": 37865, "flags": 64646}, ...}
    "final":   {"regs": {"ip": 37867}}

A harness that compares its result against `final.regs` directly would check
one register and declare a pass. `expected_regs` below merges the delta over
the initial state so the comparison covers all fourteen. The same applies to
memory.

Flags are all-or-nothing: the whole 16-bit register appears if any bit moved.

## What is deliberately not interpreted here

The `cycles` array is carried through untouched. It is the oracle for the three
`F2` timing cells in `docs/features/i8086.md`, and those are the last slice --
decoding it before there is a core to time would be inventing a format nobody
is reading yet. For F0 register and memory conformance the corpus README is
explicit that the queue and cycle fields can be ignored entirely.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import pathlib

#: Every register a case reports, in the order the corpus lists them.
REGISTERS = (
    "ax", "bx", "cx", "dx",
    "cs", "ss", "ds", "es",
    "sp", "bp", "si", "di",
    "ip", "flags",
)

#: Bit positions in the 8086/8088 FLAGS word. Bits 1, 3, 5, 12-15 are not
#: assigned on this part; a comparison must not assume what they hold, which is
#: why `flag_bits` reports only the nine that are defined.
FLAG_BITS = {
    "CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7,
    "TF": 8, "IF": 9, "DF": 10, "OF": 11,
}


class CorpusError(Exception):
    """A corpus file is missing, unreadable, or not shaped like SST8088 v2."""


@dataclasses.dataclass(frozen=True)
class Case:
    """One hardware-captured test."""

    name: str
    #: The instruction bytes, prefixes included.
    code: tuple[int, ...]
    initial_regs: dict[str, int]
    initial_ram: dict[int, int]
    initial_queue: tuple[int, ...]
    #: Already merged over `initial`. See the module docstring.
    expected_regs: dict[str, int]
    expected_ram: dict[int, int]
    cycles: tuple
    hash: str
    index: int

    @property
    def changed_registers(self) -> tuple[str, ...]:
        """Which registers the hardware actually moved."""
        return tuple(
            name
            for name in REGISTERS
            if self.expected_regs[name] != self.initial_regs[name]
        )

    @property
    def starts_prefetched(self) -> bool:
        """Half the corpus begins with a full instruction queue."""
        return bool(self.initial_queue)

    def flag_bits(self, value: int) -> dict[str, int]:
        """Split a FLAGS word into the nine bits this part defines."""
        return {name: (value >> bit) & 1 for name, bit in FLAG_BITS.items()}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CorpusError(message)


def _ram(entries: object, where: str) -> dict[int, int]:
    _require(isinstance(entries, list), f"{where}: ram is not a list")
    out: dict[int, int] = {}
    for entry in entries:
        _require(
            isinstance(entry, list) and len(entry) == 2,
            f"{where}: ram entry {entry!r} is not [address, value]",
        )
        address, value = entry
        _require(
            isinstance(address, int) and isinstance(value, int),
            f"{where}: ram entry {entry!r} is not integral",
        )
        # The 8088 address space wraps at FFFFF; an address outside it means
        # the file is not what this reader thinks it is.
        _require(
            0 <= address <= 0xFFFFF,
            f"{where}: ram address {address:#x} is outside the 1 MB space",
        )
        _require(0 <= value <= 0xFF, f"{where}: ram value {value} is not a byte")
        out[address] = value
    return out


def parse_case(raw: object, where: str) -> Case:
    """Turn one decoded JSON object into a `Case`, or raise."""
    _require(isinstance(raw, dict), f"{where}: case is not an object")
    for key in ("name", "bytes", "initial", "final"):
        _require(key in raw, f"{where}: case has no {key!r}")

    initial, final = raw["initial"], raw["final"]
    _require(isinstance(initial, dict), f"{where}: initial is not an object")
    _require(isinstance(final, dict), f"{where}: final is not an object")

    initial_regs = initial.get("regs")
    _require(isinstance(initial_regs, dict), f"{where}: initial.regs missing")
    missing = [name for name in REGISTERS if name not in initial_regs]
    _require(
        not missing,
        f"{where}: initial.regs is incomplete, missing {missing}. The initial "
        f"state must name every register; only `final` is a delta.",
    )

    final_regs = final.get("regs", {})
    _require(isinstance(final_regs, dict), f"{where}: final.regs is not an object")
    unknown = [name for name in final_regs if name not in REGISTERS]
    _require(not unknown, f"{where}: final.regs names unknown registers {unknown}")

    initial_ram = _ram(initial.get("ram", []), f"{where}.initial")
    expected_ram = dict(initial_ram)
    expected_ram.update(_ram(final.get("ram", []), f"{where}.final"))

    return Case(
        name=raw["name"],
        code=tuple(raw["bytes"]),
        initial_regs={name: initial_regs[name] for name in REGISTERS},
        initial_ram=initial_ram,
        initial_queue=tuple(initial.get("queue") or ()),
        expected_regs={
            name: final_regs.get(name, initial_regs[name]) for name in REGISTERS
        },
        expected_ram=expected_ram,
        cycles=tuple(raw.get("cycles") or ()),
        hash=raw.get("hash", ""),
        index=raw.get("idx", -1),
    )


def load(path: pathlib.Path) -> list[Case]:
    """Read one opcode file, gzipped or not.

    Raises on a file holding no cases. An empty result is indistinguishable
    from a corpus that failed to download, and a harness reporting "0 failures"
    over nothing is the defect `.claude/rules/conformance-fixtures.md` §4 was
    written about.
    """
    if not path.is_file():
        raise CorpusError(f"no corpus file at {path}")

    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{path}: cannot read as SST8088 JSON: {exc}") from exc

    _require(isinstance(data, list), f"{path}: top level is not a list of cases")
    _require(bool(data), f"{path}: holds no test cases")
    return [parse_case(case, f"{path.name}[{i}]") for i, case in enumerate(data)]


def opcode_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Every corpus file in a directory, sorted. Raises when there are none."""
    found = sorted(
        p for p in directory.iterdir()
        if p.suffix == ".gz" or (p.suffix == ".json" and p.stem != "README")
    )
    if not found:
        raise CorpusError(
            f"{directory} holds no corpus files. Fetch them with "
            f"bscripts/get_8088_tests.sh -- they are ~2 GB and deliberately "
            f"not vendored."
        )
    return found
