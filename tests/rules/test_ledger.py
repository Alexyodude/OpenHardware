# OpenHardware — tests for the feature ledger parser.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib

import pytest

from tools.ledger import Cell, LedgerError, parse_ledger

HEADER = (
    "| id | tier | oracle | tolerance | status | fixture |\n"
    "|---|---|---|---|---|---|\n"
)


def write(tmp_path, rows: str) -> pathlib.Path:
    path = tmp_path / "ledger.md"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def test_parses_a_planned_cell(tmp_path):
    path = write(tmp_path, "| i8086.mov | F0 | ISA manual 2-21 | exact | planned | - |\n")
    assert parse_ledger(path) == [
        Cell("i8086.mov", "F0", "ISA manual 2-21", "exact", "planned", "-")
    ]


def test_unknown_tier_raises(tmp_path):
    path = write(tmp_path, "| a | F9 | manual | exact | planned | - |\n")
    with pytest.raises(LedgerError, match="F9"):
        parse_ledger(path)


def test_unknown_status_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual | exact | shipped | - |\n")
    with pytest.raises(LedgerError, match="shipped"):
        parse_ledger(path)


def test_scheduled_cell_without_oracle_raises(tmp_path):
    path = write(tmp_path, "| a | F0 |  | exact | in-progress | - |\n")
    with pytest.raises(LedgerError, match="no oracle"):
        parse_ledger(path)


def test_done_cell_without_fixture_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual | exact | done | - |\n")
    with pytest.raises(LedgerError, match="no fixture"):
        parse_ledger(path)


def test_wrong_column_count_raises(tmp_path):
    path = write(tmp_path, "| a | F0 | manual |\n")
    with pytest.raises(LedgerError, match="expected 6 columns"):
        parse_ledger(path)


def test_duplicate_id_raises(tmp_path):
    rows = (
        "| a | F0 | manual | exact | planned | - |\n"
        "| a | F1 | manual | exact | planned | - |\n"
    )
    with pytest.raises(LedgerError, match="duplicate id"):
        parse_ledger(write(tmp_path, rows))


def test_ledger_with_no_rows_raises(tmp_path):
    with pytest.raises(LedgerError, match="no cells"):
        parse_ledger(write(tmp_path, ""))
