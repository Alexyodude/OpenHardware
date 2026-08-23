# OpenHardware — tests for the repository inventory generator.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib
import re
import subprocess
import sys

import pytest

from tools.inventory import (
    InventoryError,
    collect_boards,
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


def test_a_path_that_is_not_a_repository_raises(tmp_path):
    with pytest.raises(InventoryError, match="failed"):
        collect_files(tmp_path)


def test_the_repository_reports_its_own_areas():
    files = collect_files(REPO)
    for area in ("webui", "tools", "tests"):
        assert files.get(area), f"expected tracked files under {area}/"


def test_no_upstream_source_is_tracked_here():
    """The separation from PICSimLab, pinned.

    This repository was extracted from a fork of `lcgamboa/picsimlab` and must
    not drift back into being one. PICSimLab is consumed as an external
    install (`webui/picsimlab.py`) and its source is never vendored; the one
    change we need to its C++ lives in `patches/` as a diff, not as a copy of
    the file it patches.

    `other` is the escape hatch in `KNOWN_AREAS`, so anything appearing at the
    root that nobody declared shows up here rather than passing unnoticed.
    """
    files = collect_files(REPO)
    upstream_dirs = {"src", "share", "lib", "package", "debian", "bscripts"}
    tracked_roots = {path.split("/")[0] for paths in files.values() for path in paths}
    assert not (tracked_roots & upstream_dirs), (
        f"upstream source has reappeared in this tree: "
        f"{sorted(tracked_roots & upstream_dirs)}"
    )


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
    for heading in ("TESTS", "MECHANISMS", "FILES tracked", "LEDGERS", "BOARDS"):
        assert heading in out


def test_markdown_render_has_a_table_per_section_and_states_provenance():
    out = render_markdown()
    # Count separator *lines*, not occurrences: a four-column table contains
    # "|---" four times on one line.
    separators = sum(1 for line in out.splitlines() if line.startswith("|---"))
    assert separators == 5, "expected one table per section"
    assert "Generated from" in out
    assert "do not edit this by hand" in out


# --- collect_boards --------------------------------------------------------


def test_missing_boards_directory_raises(tmp_path):
    with pytest.raises(InventoryError, match="does not exist"):
        collect_boards(tmp_path / "nope")


def test_boards_directory_without_definitions_raises(tmp_path):
    with pytest.raises(InventoryError, match="no board definitions"):
        collect_boards(tmp_path)


def test_a_board_without_a_pads_list_raises(tmp_path):
    (tmp_path / "b.json").write_text('{"board": "b"}', encoding="utf-8")
    with pytest.raises(InventoryError, match="expected a `pads` list"):
        collect_boards(tmp_path)


def test_unparseable_board_raises(tmp_path):
    (tmp_path / "b.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(InventoryError, match="b.json"):
        collect_boards(tmp_path)


def test_only_pads_with_a_pin_index_count_as_wired(tmp_path):
    (tmp_path / "b.json").write_text(
        '{"board": "b", "pads": ['
        '{"pin": 3}, {"pin": 0}, {"pin": null}, {}'
        "]}",
        encoding="utf-8",
    )
    board = collect_boards(tmp_path)[0]
    assert (board.pads, board.wired) == (4, 2), (
        "pin 0 is a real pin index and must count; null and absent must not"
    )


def test_missing_provenance_is_reported_as_missing_not_defaulted(tmp_path):
    (tmp_path / "b.json").write_text('{"board": "b", "pads": []}', encoding="utf-8")
    board = collect_boards(tmp_path)[0]
    assert board.vendor is None and board.licence is None


# --- the README cannot drift from the directory ----------------------------


def _readme_board_groups() -> tuple[set[str], set[str]]:
    """The two board name sets the README claims, as (wired, outline-only).

    Parses the section rather than the whole file so that a board name
    mentioned in prose elsewhere -- `Arduino Uno` turns up in plenty of
    sentences -- cannot silently satisfy this check.
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    section = re.search(r"\n## Boards\n(.*?)(?=\n## )", text, re.DOTALL)
    assert section, "README.md has no `## Boards` section"
    body = section.group(1)

    marker = "Outline and pad labels only, not yet wired:"
    assert marker in body, "README.md's Boards section lost its outline-only heading"
    wired_half, outline_half = body.split(marker)

    def names_in_bullets(part: str) -> set[str]:
        # Only bullet lines hold board names. The prose around them also uses
        # backticks -- for `pin`, `webui/boards/`, `assumption` -- and reading
        # those as boards would make the check pass on nonsense.
        return {
            name
            for line in part.splitlines()
            if line.startswith("- ")
            for name in re.findall(r"`([^`]+)`", line)
        }

    return names_in_bullets(wired_half), names_in_bullets(outline_half)


def test_readme_board_list_matches_the_directory():
    boards = collect_boards(REPO / "webui" / "boards")
    readme_wired, readme_outline = _readme_board_groups()

    actual_wired = {b.name for b in boards if b.wired}
    actual_outline = {b.name for b in boards if not b.wired}

    assert readme_wired == actual_wired, (
        "README.md's wired board list has drifted from webui/boards/; "
        f"only in README: {sorted(readme_wired - actual_wired)}; "
        f"only on disk: {sorted(actual_wired - readme_wired)}"
    )
    assert readme_outline == actual_outline, (
        "README.md's outline-only board list has drifted from webui/boards/; "
        f"only in README: {sorted(readme_outline - actual_outline)}; "
        f"only on disk: {sorted(actual_outline - readme_outline)}"
    )


def test_the_readme_does_not_write_down_board_counts():
    """The counts belong to the generator, not to prose.

    `CLAUDE.md` is explicit that an inventory is the document that rots
    fastest, and this repository has already caught two rule files describing
    code they no longer matched. The board *names* are drift-tested above; a
    hand-typed total has no such guard, so it must not appear at all.
    """
    section = re.search(
        r"\n## Boards\n(.*?)(?=\n## )",
        (REPO / "README.md").read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert section
    stray = re.findall(r"\b\d+\s+(?:boards?|pads?|definitions?)\b", section.group(1))
    assert not stray, f"board counts written down by hand: {stray}"
