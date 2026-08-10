# OpenHardware — tests for the repository inventory generator.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib
import re
import subprocess
import sys

import pytest

from tools.inventory import (
    InventoryError,
    collect_files,
    collect_ledgers,
    collect_mechanisms,
    collect_tests,
    render_markdown,
    render_text,
)

REPO = pathlib.Path(__file__).resolve().parents[2]

TWO_TESTS = """
def test_one():
    assert True


def test_two():
    assert True


def helper():
    return 1
"""


# --- collect_tests ---------------------------------------------------------


def test_counts_only_test_functions(tmp_path):
    (tmp_path / "test_sample.py").write_text(TWO_TESTS, encoding="utf-8")
    assert collect_tests(tmp_path) == {(tmp_path / "test_sample.py").as_posix(): 2}


def test_missing_test_directory_raises(tmp_path):
    with pytest.raises(InventoryError, match="does not exist"):
        collect_tests(tmp_path / "absent")


def test_directory_without_test_files_raises(tmp_path):
    (tmp_path / "notes.md").write_text("not a test", encoding="utf-8")
    with pytest.raises(InventoryError, match="no test files"):
        collect_tests(tmp_path)


def test_unparseable_test_file_raises(tmp_path):
    (tmp_path / "test_broken.py").write_text("def test_(:\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="does not parse"):
        collect_tests(tmp_path)


# --- collect_mechanisms ----------------------------------------------------


def test_missing_rules_directory_raises_inventory_error(tmp_path):
    # Must surface as InventoryError, not RuleParseError: main() catches only
    # InventoryError, so a leaked type would print a traceback.
    with pytest.raises(InventoryError):
        collect_mechanisms(tmp_path / "absent")


def test_empty_rules_directory_raises_inventory_error(tmp_path):
    with pytest.raises(InventoryError):
        collect_mechanisms(tmp_path)


# --- collect_ledgers -------------------------------------------------------


def test_missing_features_directory_raises(tmp_path):
    with pytest.raises(InventoryError, match="does not exist"):
        collect_ledgers(tmp_path / "absent")


def test_features_directory_without_ledgers_raises(tmp_path):
    with pytest.raises(InventoryError, match="no ledgers"):
        collect_ledgers(tmp_path)


def test_malformed_ledger_raises_inventory_error(tmp_path):
    (tmp_path / "bad.md").write_text(
        "| id | tier | oracle | tolerance | status | fixture |\n"
        "|---|---|---|---|---|---|\n"
        "| a | F9 | manual | exact | planned | - |\n",
        encoding="utf-8",
    )
    with pytest.raises(InventoryError):
        collect_ledgers(tmp_path)


# --- collect_files ---------------------------------------------------------


def test_unresolvable_fork_point_raises():
    with pytest.raises(InventoryError, match="failed"):
        collect_files("no-such-tag-exists-here")


def test_real_fork_point_reports_additions_and_the_one_delta():
    files = collect_files()
    assert files["A"], "expected added files since fork-point"
    # The fork's only upstream modification, logged in docs/upstream-deltas.md.
    assert files.get("M") == ["src/lib/board.h"]


# --- self-consistency ------------------------------------------------------


def test_ast_count_matches_pytest_collection():
    """The ast model must agree with pytest's own view of the suite.

    collect_tests counts `def test_*` with ast, so a parametrised test counts
    once here and many times in pytest. Nothing is parametrised today. If that
    changes, this fails loudly rather than letting the inventory quietly report
    a number nobody can reproduce.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/rules/", "--collect-only", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    assert match, f"could not read pytest's count from:\n{result.stdout[-500:]}"
    assert sum(collect_tests().values()) == int(match.group(1))


def test_every_armed_checker_is_a_file_the_inventory_reports():
    """An armed mechanism must name a file that exists in this fork."""
    tracked = {p for paths in collect_files().values() for p in paths}
    missing = [
        checker
        for _, tier, armed, checker in collect_mechanisms()
        if armed and tier == "SCRIPT-ENFORCED" and checker not in tracked
    ]
    assert not missing, f"armed checkers absent from the file inventory: {missing}"


# --- rendering -------------------------------------------------------------


def test_text_render_names_every_section():
    out = render_text()
    for heading in ("TESTS", "MECHANISMS", "FILES since", "LEDGERS"):
        assert heading in out


def test_markdown_render_has_a_table_per_section_and_states_provenance():
    out = render_markdown()
    # Count separator *lines*, not occurrences: a four-column table contains
    # "|---" four times on one line.
    separators = sum(1 for line in out.splitlines() if line.startswith("|---"))
    assert separators == 4, "expected one table per section"
    assert "Generated from" in out
    assert "do not edit this by hand" in out
