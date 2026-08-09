#!/usr/bin/env python3
# OpenHardware — parse feature ledgers into validated cells.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parser for the feature ledgers under ``docs/features/``.

Every malformed row raises. A ledger parser that skips rows it cannot read
deletes features silently, and a feature nobody can see is a feature nobody
builds.
"""

from __future__ import annotations

import dataclasses
import pathlib

TIERS = ("F0", "F1", "F2", "F3")
STATUSES = ("planned", "in-progress", "done")
SCHEDULED = ("in-progress", "done")
COLUMNS = 6
_EMPTY = {"", "-", "—"}


class LedgerError(Exception):
    """A ledger row is malformed, incomplete, or contradictory."""


@dataclasses.dataclass(frozen=True)
class Cell:
    id: str
    tier: str
    oracle: str
    tolerance: str
    status: str
    fixture: str


def _rows(text: str) -> list[tuple[int, list[str]]]:
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":"} for cell in cells if cell):
            continue  # separator row
        if cells[0].lower() == "id":
            continue  # header row
        rows.append((number, cells))
    return rows


def parse_ledger(path: pathlib.Path) -> list[Cell]:
    rows = _rows(path.read_text(encoding="utf-8"))
    if not rows:
        raise LedgerError(f"{path}: contains no cells")

    cells: list[Cell] = []
    seen: set[str] = set()
    for number, values in rows:
        where = f"{path}:{number}"
        if len(values) != COLUMNS:
            raise LedgerError(f"{where}: expected {COLUMNS} columns, got {len(values)}")
        cell = Cell(*values)
        if not cell.id:
            raise LedgerError(f"{where}: row has no id")
        if cell.id in seen:
            raise LedgerError(f"{where}: duplicate id {cell.id!r}")
        seen.add(cell.id)
        if cell.tier not in TIERS:
            raise LedgerError(f"{where}: tier {cell.tier!r} not in {list(TIERS)}")
        if cell.status not in STATUSES:
            raise LedgerError(f"{where}: status {cell.status!r} not in {list(STATUSES)}")
        if cell.status in SCHEDULED and cell.oracle in _EMPTY:
            raise LedgerError(
                f"{where}: status {cell.status!r} but no oracle; "
                f"a cell with no oracle cannot be scheduled"
            )
        if cell.status == "done" and cell.fixture in _EMPTY:
            raise LedgerError(f"{where}: status 'done' but no fixture")
        cells.append(cell)
    return cells
