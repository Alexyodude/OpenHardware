# OpenHardware — tests for the repository inventory generator.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import ast
import dataclasses
import json
import pathlib
import re
import subprocess
import sys

import pytest

import webui.emulator_server as server
from tools import board_sources
from tools.import_pindefs import DISPUTED, NO_PACKAGE_AT_ALL, NOT_PUBLISHED, NOT_TRACED
from tools.inventory import (
    MODEL_INDEX,
    NO_SOURCE,
    NOT_BUILT,
    VENDOR_DIR,
    Evidence,
    InventoryError,
    Layer,
    Twin,
    _file_geometry,
    _twin_heading,
    collect_assets,
    collect_boards,
    collect_files,
    collect_ledgers,
    collect_mechanisms,
    collect_tests,
    collect_twins,
    is_supply,
    render_markdown,
    render_text,
    supply_labels,
)
from webui.boards import catalogue

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
    for heading in (
        "TESTS",
        "MECHANISMS",
        "FILES tracked",
        "LEDGERS",
        "BOARDS",
        "ASSETS",
        "TWINS",
    ):
        assert heading in out


def test_markdown_render_has_a_table_per_section_and_states_provenance():
    out = render_markdown()
    # Count separator *lines*, not occurrences: a four-column table contains
    # "|---" four times on one line.
    separators = sum(1 for line in out.splitlines() if line.startswith("|---"))
    assert separators == 7, "expected one table per section"
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


# --- collect_assets --------------------------------------------------------
#
# The asset report answers, per board: is there a schematic, a PCB design, a
# 3D model, a pin definition, a licence — and how strong is the claim. These
# tests are mostly about the *weak* answers, because a survey earns its keep
# by being trusted when it says no.


def _board_file(directory, name, footprint=None, licence=None, pads=None, registry=None):
    """Write one board definition, with only the fields under test."""
    source = {}
    if footprint is not None:
        source["footprint"] = footprint
    if licence is not None:
        source["licence"] = licence
    if registry is not None:
        source["registry"] = registry
    board = {"board": name, "pads": pads if pads is not None else [{"pin": None}]}
    if source:
        board["source"] = source
    (directory / f"{name}.json").write_text(json.dumps(board), encoding="utf-8")


def _vendor_checkout(root, files):
    """A git checkout holding `files`, the way the fetch script leaves one.

    Committed as well as written, because `collect_assets` reads the git tree
    to tell "the vendor does not publish this" from "we did not fetch it".
    """
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A", "-f"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "vendor",
        ],
        cwd=root,
        check=True,
    )
    return root


def test_assets_missing_boards_directory_raises(tmp_path):
    with pytest.raises(InventoryError, match="does not exist"):
        collect_assets(tmp_path / "absent", tmp_path / "vendor")


def test_assets_boards_directory_without_definitions_raises(tmp_path):
    with pytest.raises(InventoryError, match="no board definitions"):
        collect_assets(tmp_path, tmp_path / "vendor")


def test_an_unfetched_vendor_tree_is_unsearchable_not_absent(tmp_path):
    """The difference this whole grading scheme exists for.

    `third_party/` is git-ignored, so a fresh clone has no vendor tree at all.
    Reporting `absent` there would turn one missing fetch into twenty-six
    findings about what a vendor publishes, which is the vacuous-green failure
    inverted: a confident negative nobody checked.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B")

    report = collect_assets(boards, tmp_path / "never-fetched")[0]
    assert report.schematic.evidence is Evidence.UNSEARCHABLE
    assert "get_board_sources.py" in report.schematic.detail, (
        "the cell must say how to make the search possible"
    )


def test_a_fetched_tree_holding_nothing_reports_absent(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B")
    vendor = _vendor_checkout(tmp_path / "vendor", {"README.md": "nothing here"})

    report = collect_assets(boards, vendor)[0]
    assert report.schematic.evidence is Evidence.ABSENT
    assert "B" in report.schematic.detail and ".kicad_sch" in report.schematic.detail, (
        f"an absent cell must say what was looked for: {report.schematic.detail}"
    )


def test_a_schematic_in_source_form_is_told_apart_from_a_pdf(tmp_path):
    """Source or PDF is the difference between a netlist and a picture.

    OH-28 can turn `.kicad_sch` into a netlist. Nothing can turn a PDF into
    one, so a report that renders both as "schematic: yes" promises work that
    cannot be done.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Source", footprint="Source")
    _board_file(boards, "Paper", footprint="Paper")
    vendor = _vendor_checkout(
        tmp_path / "vendor",
        {"cad/Source.kicad_sch": "(kicad_sch)", "cad/Paper.pdf": "%PDF-1.4"},
    )

    cells = {report.name: report.schematic for report in collect_assets(boards, vendor)}
    assert cells["Source"].form == "source"
    assert cells["Paper"].form == "PDF"
    assert cells["Source"].evidence is cells["Paper"].evidence is Evidence.PRESENT
    assert cells["Paper"].summary() == "present:PDF"


def test_a_schematic_is_never_credited_to_a_neighbouring_board(tmp_path):
    """The `ESP32-C6` / `ESP32-C61` bug, in its board-file form.

    `webui/boards/catalogue.py` records that `startswith` matched a chip
    against a different real part. Here the same shortcut would hand
    `XIAO-ESP32-C3-DIP` its neighbour's schematic, and the report would be
    wrong in the one direction nobody goes looking: a filled-in cell.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "XIAO-ESP32-C3-DIP", footprint="XIAO-ESP32-C3-DIP")
    vendor = _vendor_checkout(
        tmp_path / "vendor", {"XIAO-ESP32-C3-DIP-SMD.kicad_sch": "(kicad_sch)"}
    )

    report = collect_assets(boards, vendor)[0]
    assert report.schematic.evidence is Evidence.ABSENT


def test_an_asset_in_a_directory_named_for_the_footprint_counts(tmp_path):
    """Vendors file per-board CAD in a per-board directory as often as not."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="XIAO-RP2040-DIP")
    vendor = _vendor_checkout(
        tmp_path / "vendor", {"hardware/XIAO-RP2040-DIP/schematic.pdf": "%PDF-1.4"}
    )

    report = collect_assets(boards, vendor)[0]
    assert report.schematic.evidence is Evidence.PRESENT
    assert report.schematic.form == "PDF"


def test_a_file_in_the_index_but_not_on_disk_is_indexed_not_absent(tmp_path):
    """A sparse checkout must not be read as a vendor publishing nothing.

    `python tools/get_board_sources.py seeed-xiao` fetches the KiCad library
    and `document/` and nothing else, because the full tree is ~196 MB of
    marketing PNGs. A disk-only search would call a real unfetched schematic
    absent.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B")
    vendor = _vendor_checkout(tmp_path / "vendor", {"cad/B.kicad_pcb": "(kicad_pcb)"})
    (vendor / "cad" / "B.kicad_pcb").unlink()

    report = collect_assets(boards, vendor)[0]
    assert report.pcb.evidence is Evidence.INDEXED
    assert "not fetched" in report.pcb.detail


def test_a_vendor_directory_that_is_not_a_checkout_raises(tmp_path):
    """Do not silently downgrade to a disk-only search.

    Half a search reported as a whole one is the failure mode this module
    exists to prevent, so the tool says what is wrong and stops.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B")
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "B.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

    with pytest.raises(InventoryError, match="git"):
        collect_assets(boards, loose)


def test_the_pin_cell_counts_pads_and_says_how_many_are_wired(tmp_path):
    """`parsed` alone would read as though the board were connected.

    Twenty-five of the twenty-six boards here have a complete pad map and not
    one simulator pin index in it, so the counts belong in the cell.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", pads=[{"pin": 3}, {"pin": 0}, {"pin": None}, {}])

    report = collect_assets(boards, tmp_path / "vendor")[0]
    assert report.pins.evidence is Evidence.PARSED
    assert "4 pads, 2 carrying a simulator pin index" in report.pins.detail


def test_a_board_declaring_no_pads_has_no_pin_definition(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", pads=[])

    report = collect_assets(boards, tmp_path / "vendor")[0]
    assert report.pins.evidence is Evidence.ABSENT


def test_a_licence_string_is_not_the_same_claim_as_a_licence_file(tmp_path):
    """The board file's `source.licence` is a note; the LICENSE is the licence."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Backed", footprint="Backed", licence="MIT")
    _board_file(boards, "Bare", footprint="Bare", licence="MIT")

    backed = _vendor_checkout(tmp_path / "backed", {"LICENSE": "MIT ..."})
    bare = _vendor_checkout(tmp_path / "bare", {"README.md": "no licence here"})

    with_file = {r.name: r.licence for r in collect_assets(boards, backed)}["Backed"]
    without = {r.name: r.licence for r in collect_assets(boards, bare)}["Bare"]

    assert with_file.evidence is Evidence.PRESENT
    assert "LICENSE" in with_file.detail
    assert without.evidence is Evidence.ABSENT
    assert "MIT" in without.detail, "the recorded string is still worth reporting"


def test_a_licence_at_the_top_of_the_tree_beats_one_inside_a_sample(tmp_path):
    """A `COPYING` in one bundled project covers that project, not the CAD."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B", licence="MIT")
    vendor = _vendor_checkout(
        tmp_path / "vendor",
        {"LICENSE": "MIT ...", "projects/demo/COPYING": "GPL-2.0 ..."},
    )

    report = collect_assets(boards, vendor)[0]
    assert report.licence.detail.endswith("/LICENSE")


def test_a_board_recording_no_licence_reports_absent(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B")
    vendor = _vendor_checkout(tmp_path / "vendor", {"LICENSE": "MIT ..."})

    report = collect_assets(boards, vendor)[0]
    assert report.licence.evidence is Evidence.ABSENT
    assert "source.licence" in report.licence.detail


# A board whose `source.registry` names a source is backed by a licence file
# in THAT source's tree, which `tools/board_sources.py` puts under the
# repository root as `Source.dest` says. Until OH-204 every board's licence
# was looked for in Seeed's tree, so the Uno's CC BY-SA 4.0 read `present` on
# the strength of Seeed's MIT LICENSE, and so did every manifest board's.


def test_a_registry_board_is_not_backed_by_seeeds_licence_when_its_own_tree_holds_none(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    uno = board_sources.source("arduino-uno")
    assert uno.fetch.transport is board_sources.Transport.HTTPS_ARCHIVE
    tree = uno.dest(pathlib.Path("."))
    tree.mkdir(parents=True)
    (tree / "UNO-TH_Rev3e.brd").write_text("<eagle/>", encoding="utf-8")
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Uno", licence="CC BY-SA 4.0", registry="arduino-uno")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.ABSENT,
        "CC BY-SA 4.0 recorded in the board file, but third_party/arduino-uno does "
        "not hold License.txt, the file the registry row arduino-uno reads its "
        "licence from, graded opened",
    ), cell


def test_a_registry_board_is_backed_by_the_licence_file_in_its_own_tree(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    tree = board_sources.source("arduino-uno").dest(pathlib.Path("."))
    tree.mkdir(parents=True)
    (tree / "License.txt").write_text("CC BY-SA 4.0 ...", encoding="utf-8")
    seeed = _vendor_checkout(tmp_path / "seeed", {"README.md": "no licence here"})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Uno", licence="CC BY-SA 4.0", registry="arduino-uno")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.PRESENT, "CC BY-SA 4.0; third_party/arduino-uno/License.txt, graded opened"
    ), cell


def test_a_registry_board_cloned_sparsely_reads_its_own_index(tmp_path, monkeypatch):
    """A git source's licence that is in its index and not on disk is
    `indexed`, as a file in Seeed's index is; Seeed's LICENSE on disk is not
    this board's."""
    monkeypatch.chdir(tmp_path)
    kb2040 = board_sources.source("adafruit-kb2040")
    assert kb2040.fetch.transport is board_sources.Transport.GIT_SPARSE
    clone = _vendor_checkout(
        kb2040.dest(pathlib.Path(".")), {"license.txt": "...", "Adafruit KB2040.brd": "x"}
    )
    (clone / "license.txt").unlink()
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "KB2040", licence="CC BY-SA 3.0 Unported", registry="adafruit-kb2040")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.INDEXED,
        "CC BY-SA 3.0 Unported; license.txt, graded opened — in the git tree of "
        "third_party/adafruit-kb2040, not fetched",
    ), cell


def test_a_registry_board_whose_tree_is_not_fetched_names_its_licence_file_and_the_fetch(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Uno", licence="CC BY-SA 4.0", registry="arduino-uno")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.UNSEARCHABLE,
        "CC BY-SA 4.0 recorded in the board file, uncorroborated: the registry row "
        "arduino-uno reads it from License.txt, graded opened, and "
        "third_party/arduino-uno is not fetched here; run: python "
        "tools/get_board_sources.py arduino-uno",
    ), cell


# OH-212: a registry board's licence is graded on the one file its registry
# row reads the licence from, `licence.file`, and never on a file whose name
# looks like a licence. Both Olimex trees hold a LICENSE that is the GPL-3.0's
# text, for their software; their hardware's CERN-OHL is read from README.md.
# OH-213: and the cell carries the row's grade of that file, because a README
# stating a licence is not the licence's text, and the registry grades it
# `stated` where Arduino's License.txt is `opened`.


def test_a_registry_boards_licence_rests_on_the_file_its_row_names_not_a_licence_named_one(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    evb = board_sources.source("olimex-esp32-c6-evb")
    assert evb.licence.file == "README.md", evb.licence
    _vendor_checkout(
        evb.dest(pathlib.Path(".")),
        {
            "LICENSE": "GNU GENERAL PUBLIC LICENSE Version 3",
            "README.md": "Hardware is released under CERN OHL v1.2 license",
        },
    )
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "EVB", licence="CERN-OHL-1.2", registry="olimex-esp32-c6-evb")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.PRESENT,
        "CERN-OHL-1.2; third_party/olimex-esp32-c6-evb/README.md, graded stated",
    ), cell


def test_a_licence_named_file_the_registry_row_does_not_name_backs_nothing(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    evb = board_sources.source("olimex-esp32-c6-evb")
    _vendor_checkout(
        evb.dest(pathlib.Path(".")), {"LICENSE": "GNU GENERAL PUBLIC LICENSE Version 3"}
    )
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "EVB", licence="CERN-OHL-1.2", registry="olimex-esp32-c6-evb")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.ABSENT,
        "CERN-OHL-1.2 recorded in the board file, but third_party/olimex-esp32-c6-evb "
        "does not hold README.md, the file the registry row olimex-esp32-c6-evb "
        "reads its licence from, graded stated",
    ), cell


def _registry_row_reading_no_file(monkeypatch):
    """The registry with one git source added whose licence is read from no
    file, cited from a sibling repository instead. Synthetic, so a test of
    that shape does not rest on a live row keeping it (OH-213)."""
    nothing = board_sources.Artefact(
        board_sources.Published.NO, board_sources.Evidence.ABSENT, "nothing here"
    )
    row = board_sources.Source(
        name="probe-no-licence-file",
        vendor="Probe Instruments",
        model="one repository per board",
        size="tiny",
        licence=board_sources.Licence(
            "CC BY-SA 4.0", "design files", True, board_sources.Evidence.OPENED,
            "LICENSE.md in a sibling repository",
        ),
        fetch=board_sources.Fetch(
            board_sources.Transport.GIT_SPARSE, "file:///nowhere", (), ()
        ),
        artefacts=board_sources.Artefacts(*[nothing] * 6),
        cite="fixture",
    )
    monkeypatch.setattr(board_sources, "SOURCES", board_sources.SOURCES + (row,))
    return row


def test_a_registry_row_reading_its_licence_from_no_file_reads_absent_and_says_what_it_cites(
    tmp_path, monkeypatch
):
    """A licence-named file in the fetched tree does not back it either."""
    monkeypatch.chdir(tmp_path)
    probe = _registry_row_reading_no_file(monkeypatch)
    _vendor_checkout(probe.dest(pathlib.Path(".")), {"LICENSE.md": "CC BY-SA 4.0 ..."})
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Probe", licence="CC BY-SA 4.0", registry=probe.name)

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.ABSENT,
        "CC BY-SA 4.0 recorded in the board file, but the registry row "
        "probe-no-licence-file reads its licence from no file in "
        "third_party/probe-no-licence-file; it cites, graded opened: LICENSE.md "
        "in a sibling repository",
    ), cell


def test_a_registry_row_reading_its_licence_from_no_file_reads_absent_unfetched_too(
    tmp_path, monkeypatch
):
    """The other half of `_registry_licence_cell`'s docstring: with no tree
    fetched there is still no file to look for, so the cell is `absent` on
    the row's own say-so, not `unsearchable` pending a fetch that could not
    change it."""
    monkeypatch.chdir(tmp_path)
    probe = _registry_row_reading_no_file(monkeypatch)
    assert not probe.dest(pathlib.Path(".")).exists()
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Probe", licence="CC BY-SA 4.0", registry=probe.name)

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.ABSENT,
        "CC BY-SA 4.0 recorded in the board file, but the registry row "
        "probe-no-licence-file reads its licence from no file in "
        "third_party/probe-no-licence-file; it cites, graded opened: LICENSE.md "
        "in a sibling repository",
    ), cell


def test_a_board_naming_only_a_footprint_is_backed_by_the_licence_file_in_seeeds_tree(
    tmp_path,
):
    """A footprint is searched for in Seeed's tree, so that is where its
    board's licence file is looked for."""
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Footprint", footprint="Footprint", licence="MIT")

    cell = collect_assets(boards, seeed)[0].licence
    assert (cell.evidence, cell.detail) == (
        Evidence.PRESENT, f"MIT; {seeed.as_posix()}/LICENSE"
    ), cell


def test_a_board_naming_neither_a_registry_nor_a_footprint_has_no_tree_to_back_it(tmp_path):
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Nothing", licence="MIT")

    cell = collect_assets(boards, seeed)[0].licence
    assert cell.evidence is Evidence.UNSEARCHABLE, cell
    assert "source.registry" in cell.detail, cell.detail


def test_a_registry_name_no_source_has_is_refused_naming_it(tmp_path):
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Typo", licence="MIT", registry="arduino-unoo")

    with pytest.raises(InventoryError, match=r"Typo\.json.*arduino-unoo"):
        collect_assets(boards, seeed)


def test_the_unos_licence_cell_rests_on_arduinos_own_licence_file(monkeypatch):
    monkeypatch.chdir(REPO)
    if not (REPO / "third_party" / "arduino-uno" / "License.txt").is_file():
        pytest.skip(
            "SKIPPED: third_party/arduino-uno/License.txt is not fetched. Run: "
            "python tools/get_board_sources.py arduino-uno, which prints the URL "
            "to download by hand"
        )
    cells = {
        report.name: report.licence
        for report in collect_assets(REPO / "webui" / "boards", REPO / VENDOR_DIR)
    }
    assert (cells["Arduino Uno"].evidence, cells["Arduino Uno"].detail) == (
        Evidence.PRESENT, "CC BY-SA 4.0; third_party/arduino-uno/License.txt, graded opened"
    ), cells["Arduino Uno"]


def test_every_fetched_registry_boards_licence_cell_names_the_file_its_row_reads(monkeypatch):
    """Over the real boards: wherever the file a board's registry row reads
    its licence from is on this disk, the cell is present on that file, with
    the row's grade of it. Until OH-212 the two Olimex cells were backed by
    their GPL-3.0 LICENSE; until OH-213 their README, which states a licence,
    read as Adafruit's licence text does."""
    monkeypatch.chdir(REPO)
    boards_dir = REPO / "webui" / "boards"
    rows = {}
    for path in sorted(boards_dir.glob("*.json")):
        board = json.loads(path.read_text(encoding="utf-8"))
        source = board.get("source") or {}
        if source.get("registry"):
            rows[board.get("board", path.stem)] = (
                source["licence"], board_sources.source(source["registry"])
            )
    expected = {
        name: (Evidence.PRESENT, f"{licence}; {row.dest(pathlib.Path('.')).as_posix()}/"
                                 f"{row.licence.file}, graded {row.licence.evidence.label}")
        for name, (licence, row) in rows.items()
        if row.licence.file and (row.dest(REPO) / row.licence.file).is_file()
    }
    if not expected:
        pytest.skip(
            f"SKIPPED: none of the {len(rows)} registry boards' licence files is "
            f"fetched; run python tools/get_board_sources.py <name>"
        )
    cells = {
        report.name: report.licence
        for report in collect_assets(boards_dir, REPO / VENDOR_DIR)
    }
    assert {name: (cells[name].evidence, cells[name].detail) for name in expected} == expected


def test_the_markdown_says_why_a_licence_cell_is_absent(tmp_path, monkeypatch):
    """An absent schematic is the one search the prose above the table
    describes. An absent licence is one of several -- the board file records
    none, the row's fetched tree lacks its file, the row names no file -- so
    the cell prints its reason, or a row naming no file reads as if its file
    were missing."""
    import tools.inventory as inventory

    monkeypatch.chdir(REPO)
    probe = _registry_row_reading_no_file(monkeypatch)
    assert not probe.dest(REPO).exists()
    seeed = _vendor_checkout(tmp_path / "seeed", {"LICENSE": "MIT ..."})
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Probe", licence="CC BY-SA 4.0", registry=probe.name)
    collect = inventory.collect_assets
    cell = collect(boards, seeed)[0].licence
    assert cell.evidence is Evidence.ABSENT, cell
    monkeypatch.setattr(inventory, "collect_assets", lambda: collect(boards, seeed))

    row = next(
        line for line in render_markdown().splitlines() if line.startswith("| `Probe` |")
    )
    assert row.endswith(f"| `absent` {cell.detail} |"), row


def test_missing_names_every_cell_with_nothing_behind_it(tmp_path):
    """The report has to be able to say a board is incomplete, and which part.

    OH-13 set the precedent when the generated board list refused to call
    twenty-five unwired boards supported. `unsearchable` counts as missing
    alongside `absent` for the same reason: a search that did not run is not
    evidence that anything is there.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", footprint="B", licence="MIT", pads=[{"pin": 1}])
    vendor = _vendor_checkout(tmp_path / "vendor", {"LICENSE": "MIT ..."})

    report = collect_assets(boards, vendor)[0]
    assert report.missing() == ("schematic", "pcb", "model3d")

    unfetched = collect_assets(boards, tmp_path / "never-fetched")[0]
    assert unfetched.missing() == ("schematic", "pcb", "model3d", "licence")


def test_every_evidence_class_explains_itself():
    """A class the report cannot gloss is a class a reader cannot use.

    The gloss lives on the enum member rather than in a legend beside it, so
    this is a shape check rather than a drift check — there is no second
    place for it to drift from.
    """
    labels = [evidence.label for evidence in Evidence]
    assert len(set(labels)) == len(labels), f"duplicate evidence labels: {labels}"
    for evidence in Evidence:
        assert evidence.gloss.strip(), f"{evidence.label} has no gloss"


# --- the asset report cannot drift from the directory ----------------------


def test_the_asset_report_covers_exactly_the_boards_on_disk():
    """One row per board definition, named the way the board list names it.

    The drift guard OH-13 put on the README board list, applied to the report
    that grades those boards: a board added to `webui/boards/` appears here
    and a board removed disappears, with nobody editing a table.
    """
    boards_dir = REPO / "webui" / "boards"
    reported = [report.name for report in collect_assets(boards_dir, REPO / VENDOR_DIR)]
    listed = [board.name for board in collect_boards(boards_dir)]

    assert sorted(reported) == sorted(listed), (
        "the asset report has drifted from webui/boards/; "
        f"only in the report: {sorted(set(reported) - set(listed))}; "
        f"only in the board list: {sorted(set(listed) - set(reported))}"
    )
    assert len(reported) == len(set(reported)), f"a board is reported twice: {reported}"


def test_a_new_board_with_no_schematic_reports_no_schematic_by_itself(tmp_path):
    """The acceptance condition of OH-27, run as an experiment.

    A board that appears in the directory has to show up graded without anyone
    touching the report — otherwise this is the hand-maintained five-column
    table of yes and no that `CLAUDE.md` forbids, wearing a generator's coat.

    Run against a directory of its own rather than `webui/boards/`: a test
    that writes into the real board directory would be visible to every other
    thing reading it while it ran.
    """
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "First", footprint="First")
    vendor = _vendor_checkout(tmp_path / "vendor", {"cad/First.kicad_sch": "(sch)"})

    before = {report.name for report in collect_assets(boards, vendor)}
    _board_file(boards, "Late arrival", footprint="Late arrival")
    after = {report.name: report for report in collect_assets(boards, vendor)}

    assert set(after) - before == {"Late arrival"}
    assert after["Late arrival"].schematic.evidence is Evidence.ABSENT
    assert "schematic" in after["Late arrival"].missing()
    assert after["First"].schematic.evidence is Evidence.PRESENT


def test_the_report_says_which_boards_are_incomplete():
    """Incompleteness is the finding, not a failure to render.

    Today every board is missing something, and the text report must show
    each of them rather than quietly listing the ones that came out well.
    """
    text = render_text()
    reports = collect_assets(REPO / "webui" / "boards", REPO / VENDOR_DIR)
    incomplete = [report for report in reports if report.missing()]
    assert incomplete, "if every board is complete, this test has outlived its point"
    for report in incomplete:
        assert report.name in text, f"{report.name} is graded but not rendered"


def test_the_vendor_dir_is_the_registry_s_own_path():
    """`VENDOR_DIR` must equal what `tools/board_sources.py` computes.

    The comment beside `VENDOR_DIR` used to promise it would become a lookup
    once OH-24 replaced the fetcher with a registry. OH-24 landed and OH-40
    retired the script, so the promise came due — but a lookup at *import*
    time would turn a missing registry entry into a module that will not
    load, and this one is imported by every `--markdown` run.

    So the path stays spelled out and this binds it instead. `Source.name` is
    documented as stable precisely because other tools hold paths built from
    it; if that ever stops being true, this fails rather than the asset
    search quietly reporting `unsearchable` for a tree that is sitting there.
    """
    from tools.board_sources import source

    assert VENDOR_DIR == source("seeed-xiao").dest(pathlib.Path("."))


def test_nothing_tells_anyone_to_run_the_retired_fetcher():
    """OH-40's done-criterion, in the form that is actually true.

    The ticket says "nothing outside third_party/ mentions get_seeed_hardware".
    Taken literally that is both unachievable and wrong, and this test is the
    corrected version:

    * This file has to name the string in order to look for it.
    * `tools/board_sources.py` and `tools/get_board_sources.py` name it in the
      past tense, to record what they replaced and which precedent they kept.
      That reasoning is the most useful thing in either docstring.
    * `docs/` holds a dated handoff and closed tickets. Rewriting those to
      name a tool that did not exist when they were written would falsify a
      record rather than fix a reference.

    What matters is that no surface *instructs* anyone to run a file that is
    no longer there. So this looks for the invocation, not the name.
    """
    invocation = "bash tools/" + "get_seeed_hardware.sh"
    telling = []
    for directory in ("tools", "tests"):
        for path in sorted((REPO / directory).rglob("*.py")):
            if invocation in path.read_text(encoding="utf-8"):
                telling.append(path.relative_to(REPO).as_posix())

    assert not (REPO / "tools" / "get_seeed_hardware.sh").exists(), "the script is retired"
    # tools/import_kicad_board.py carries the other instruction, and OH-41
    # retires that file and its error message together.
    #
    # A subset rather than an exact list, and the difference matters. Exact
    # would fail the moment OH-41 clears the last exemption -- a tripwire
    # whose only possible instruction is "delete this line", which is friction
    # carrying no information. Subset still fails loudly if a *new* surface
    # starts telling someone to run the retired script, which is the thing
    # worth catching, and it lets the exemption empty out on its own.
    assert set(telling) <= {"tools/import_kicad_board.py"}, telling


# --- collect_twins ---------------------------------------------------------
#
# Each layer is made to fail on purpose in a temp copy: a check that has never
# failed is evidence of nothing.


def _real_board(directory, name):
    """Copy one committed board file into `directory` and return its document."""
    text = (REPO / "webui" / "boards" / f"{name}.json").read_text(encoding="utf-8")
    (directory / f"{name}.json").write_text(text, encoding="utf-8")
    return json.loads(text)


def _static(tmp_path, monkeypatch, boards):
    """A served `static/` whose model index names `boards` as {name: (file, composed)}."""
    static = tmp_path / "static"
    (static / "models").mkdir(parents=True)
    for url, _ in boards.values():
        (static / url.lstrip("/")).write_bytes(b"glTF")
    index = {
        name: {"file": url, "composed": composed}
        for name, (url, composed) in boards.items()
    }
    (static / MODEL_INDEX.lstrip("/")).write_text(
        json.dumps({"boards": index}), encoding="utf-8"
    )
    monkeypatch.setattr(server, "STATIC_DIR", static)
    return static


def test_the_twin_report_covers_exactly_the_boards_on_disk():
    listed = sorted(board.name for board in collect_boards(REPO / "webui" / "boards"))
    reported = sorted(twin.name for twin in collect_twins(REPO / "webui" / "boards"))
    assert reported == listed


def test_the_twin_heading_counts_whole_boards_and_each_layer():
    held = Layer(True, "x", "x")
    whole = Twin("Whole", held, held, held, held)
    partial = Twin("Partial", held, held, Layer(False, "0/1", "unanswered on D0"), held)
    unbuilt = Twin("Unbuilt", held, Layer(False, NOT_BUILT, "x"), held, held)
    unfetched = Twin("Unfetched", Layer(False, "footprint:not fetched", "x"), held, held, held)
    assert _twin_heading([whole, partial, unbuilt, unfetched]) == (
        "1 of 4 boards hold all four; by layer: geometry 3 (1 not fetched here), "
        "model 3 (1 not built here), pins 3, runs 4"
    )


def _twin_order():
    """Most complete first, then by name, worked out here rather than by inventory."""
    twins = collect_twins()
    return [twin.name for twin in sorted(twins, key=lambda t: (len(t.missing()), t.name))]


def test_the_text_twins_section_has_one_row_per_board_most_complete_first():
    lines = render_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("TWINS — "))
    header = next(i for i in range(start, len(lines)) if lines[i].startswith("  geometry"))
    rows = [line for line in lines[header + 1:] if line.strip()]
    expected = _twin_order()
    assert len(rows) == len(expected), rows
    for row, name in zip(rows, expected):
        assert row.endswith(f"  {name}"), (row, name)


def test_the_markdown_twins_section_has_one_row_per_board_most_complete_first():
    lines = render_markdown().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Twins — "))
    rows = [line for line in lines[start:] if line.startswith("| `")]
    names = [re.match(r"\| `([^`]+)`", row).group(1) for row in rows]
    assert names == _twin_order()


def test_the_model_layer_is_what_the_page_draws_and_a_renamed_mesh_is_not(
    tmp_path, monkeypatch
):
    boards = tmp_path / "boards"
    boards.mkdir()
    _real_board(boards, "XIAO-RP2040-DIP")
    _real_board(boards, "Arduino Uno")
    static = _static(tmp_path, monkeypatch, {
        "XIAO-RP2040-DIP": ("/models/RP2040.glb", False),
        "Arduino Uno": ("/models/Arduino-Uno.glb", True),
    })

    twins = {twin.name: twin.model for twin in collect_twins(boards)}
    assert twins["XIAO-RP2040-DIP"] == (True, "vendor", "/models/RP2040.glb")
    assert twins["Arduino Uno"] == (True, "composed", "/models/Arduino-Uno.glb")

    (static / "models" / "RP2040.glb").rename(static / "models" / "RP2040.glb.bak")
    renamed = {twin.name: twin.model for twin in collect_twins(boards)}
    assert renamed["XIAO-RP2040-DIP"].summary == NOT_BUILT
    assert "/models/RP2040.glb is not served" in renamed["XIAO-RP2040-DIP"].detail
    assert "import_3d_model.py --all" in renamed["XIAO-RP2040-DIP"].detail
    assert renamed["Arduino Uno"].holds

    (static / MODEL_INDEX.lstrip("/")).unlink()
    unindexed = {twin.name: twin.model for twin in collect_twins(boards)}
    assert unindexed["Arduino Uno"].summary == NOT_BUILT
    assert f"{MODEL_INDEX} is not served" in unindexed["Arduino Uno"].detail
    assert "compose_board_3d.py" in unindexed["Arduino Uno"].detail


def test_not_built_here_and_cannot_be_built_read_differently(tmp_path, monkeypatch):
    """The meshes are gitignored, so a fresh checkout is not a board with no model."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _real_board(boards, "XIAO-RP2040-DIP")
    _real_board(boards, "XIAO-XIAO STM32C5-SMD")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "no-static")

    twins = {twin.name: twin.model for twin in collect_twins(boards)}
    unbuilt, sourceless = twins["XIAO-RP2040-DIP"], twins["XIAO-XIAO STM32C5-SMD"]
    assert not unbuilt.holds and not sourceless.holds
    assert (unbuilt.summary, sourceless.summary) == (NOT_BUILT, NO_SOURCE)
    assert "builds it" in unbuilt.detail and "builds it" not in sourceless.detail


def test_a_blanked_chip_pin_fails_the_pins_layer_unless_it_says_specifically_why(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    document = _real_board(boards, "XIAO-ESP32-C6-DIP")
    assert collect_twins(boards)[0].pins.holds

    def rewrite(label, **fields):
        for pad in document["pads"]:
            if pad["label"] == label:
                pad.update(fields)
        (boards / "XIAO-ESP32-C6-DIP.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        return collect_twins(boards)[0].pins

    assert rewrite("GND", chip_pin=None).holds, "GND is a supply pad"

    pins = rewrite("D0", chip_pin=None)
    assert not pins.holds and pins.detail.endswith("unanswered on D0"), pins.detail
    for unanswered in (NOT_PUBLISHED, NO_PACKAGE_AT_ALL, NOT_TRACED, DISPUTED):
        pins = rewrite("D0", why_null=unanswered)
        assert not pins.holds, f"import_pindefs' {unanswered!r} answers nothing"
    pins = rewrite("D0", why_null="a dedicated debug pad, not a GPIO")
    assert (pins.holds, pins.summary) == (True, "10+1/11")


def test_a_board_with_only_supply_pads_does_not_hold_the_pins_layer(tmp_path):
    """0 of 0 is a check that matched nothing, not a pass."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "B", pads=[{"label": "GND", "chip_pin": None}])
    pins = collect_twins(boards)[0].pins
    assert (pins.holds, pins.summary) == (False, "0/0")


def test_a_chip_dropped_from_firmware_verified_fails_the_runs_layer(tmp_path, monkeypatch):
    boards = tmp_path / "boards"
    boards.mkdir()
    _real_board(boards, "XIAO-ESP32-C6-DIP")
    assert collect_twins(boards)[0].runs == (
        True, "ESP32-C6", catalogue.FIRMWARE_VERIFIED["ESP32-C6"]
    )

    monkeypatch.delitem(catalogue.FIRMWARE_VERIFIED, "ESP32-C6")
    runs = collect_twins(boards)[0].runs
    assert (runs.holds, runs.summary) == (False, "ESP32-C6:no")


def test_runs_follows_the_catalogue_s_evidence_for_the_board_not_the_chip(
    tmp_path, monkeypatch
):
    """OH-176 lets the catalogue withhold evidence from one board whose chip runs."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _real_board(boards, "XIAO-ESP32-C6-DIP")
    _real_board(boards, "XIAO-ESP32-C6-SMD")
    placed = catalogue.catalogue

    def withheld(directory=None):
        return [
            dataclasses.replace(board, firmware_evidence=None)
            if board.name == "XIAO-ESP32-C6-DIP" else board
            for board in placed(directory)
        ]

    monkeypatch.setattr(catalogue, "catalogue", withheld)
    assert "ESP32-C6" in catalogue.FIRMWARE_VERIFIED
    runs = {twin.name: twin.runs for twin in collect_twins(boards)}
    assert (runs["XIAO-ESP32-C6-DIP"].holds, runs["XIAO-ESP32-C6-DIP"].summary) == (
        False, "ESP32-C6:no"
    )
    assert runs["XIAO-ESP32-C6-SMD"].holds


def test_a_footprint_resolves_by_file_name_or_declared_name_and_otherwise_says_which_failure(
    tmp_path,
):
    boards = tmp_path / "boards"
    boards.mkdir()
    for name, footprint in (
        ("Named", "Named"),
        ("Declared", "Long Name"),
        ("Ghost", "XIAO-NO-SUCH-BOARD"),
        ("Sparse", "Gone"),
    ):
        _board_file(boards, name, footprint=footprint)
    _board_file(boards, "Unsourced")
    pad = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))'
    vendor = _vendor_checkout(tmp_path / "vendor", {
        "lib/Named.kicad_mod": f'(footprint "Named" {pad})',
        "lib/Short.kicad_mod": f'(footprint "Long Name" {pad})',
        "lib/Gone.kicad_mod": f'(footprint "Gone" {pad})',
    })
    (vendor / "lib" / "Gone.kicad_mod").unlink()

    geometry = {twin.name: twin.geometry for twin in collect_twins(boards, vendor)}
    assert geometry["Named"].holds and geometry["Named"].detail.endswith("lib/Named.kicad_mod")
    assert geometry["Declared"].holds, "STM32C5's file is not named for its footprint"
    assert "lib/Short.kicad_mod, declaring Long Name" in geometry["Declared"].detail
    assert geometry["Ghost"][:2] == (False, "footprint:names nothing")
    assert geometry["Sparse"][:2] == (False, "footprint:not fetched")
    assert geometry["Unsourced"][:2] == (False, "none")

    unfetched = {
        twin.name: twin.geometry for twin in collect_twins(boards, tmp_path / "never")
    }
    assert unfetched["Named"][:2] == (False, "footprint:not fetched")
    assert "get_board_sources.py" in unfetched["Named"].detail


def test_a_named_file_must_be_on_disk_and_says_which_way_it_is_not(tmp_path, monkeypatch):
    """`source.file` is what import_board.py writes, and a string is not a file."""
    monkeypatch.chdir(tmp_path)
    fetched, unfetched = board_sources.sources()[:2]
    (tmp_path / "third_party" / fetched.name).mkdir(parents=True)
    (tmp_path / "third_party" / fetched.name / "board.brd").write_text("x", encoding="utf-8")

    here = _file_geometry(f"third_party/{fetched.name}/board.brd")
    assert here == (True, "file", f"third_party/{fetched.name}/board.brd")
    assert _file_geometry(f"third_party/{fetched.name}/nowhere.brd")[:2] == (
        False, "file:names nothing"
    )
    assert _file_geometry("nowhere/at/all.brd")[:2] == (False, "file:names nothing")
    away = _file_geometry(f"third_party/{unfetched.name}/board.brd")
    assert away[:2] == (False, "file:not fetched")
    assert f"get_board_sources.py {unfetched.name}" in away.detail

    # A real file inside a fetched source that tools/import_board.py cannot read.
    (tmp_path / "third_party" / fetched.name / "README.md").write_text("x", encoding="utf-8")
    notes = _file_geometry(f"third_party/{fetched.name}/README.md")
    assert notes[:2] == (False, "file:names nothing") and ".brd" in notes.detail

    # A real CAD file outside every source, reached directly or by climbing out.
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "board.brd").write_text("x", encoding="utf-8")
    for outside in (
        (tmp_path / "other" / "board.brd").as_posix(),
        f"third_party/{fetched.name}/../../other/board.brd",
    ):
        assert _file_geometry(outside)[:2] == (False, "file:names nothing"), outside


def test_a_named_file_that_is_not_vendor_cad_does_not_hold(monkeypatch):
    """Each of these exists, or may, and none is a board's CAD."""
    monkeypatch.chdir(REPO)
    for fake in (
        "README.md",
        "webui/boards/Arduino Uno.json",
        "C:/Windows/win.ini",
        "third_party/seeed-xiao/../../README.md",
    ):
        layer = _file_geometry(fake)
        assert layer[:2] == (False, "file:names nothing"), (fake, layer)


def test_a_new_board_nothing_knows_is_a_row_with_its_layers_missing(tmp_path, monkeypatch):
    """A board that is not a XIAO, with no model and no pindefs, must not crash
    the report: it shows up missing layers without anyone editing the report."""
    boards = tmp_path / "boards"
    boards.mkdir()
    _real_board(boards, "XIAO-ESP32-C6-DIP")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "no-static")
    before = {twin.name for twin in collect_twins(boards)}

    (boards / "Late arrival.json").write_text(json.dumps({
        "board": "Late arrival",
        "pads": [{"label": "IO5", "pin": None}, {"label": "GND", "pin": None}],
        "source": {"file": "third_party/late/arrival.brd"},
    }), encoding="utf-8")
    after = {twin.name: twin for twin in collect_twins(boards)}

    assert set(after) - before == {"Late arrival"}
    late = after["Late arrival"]
    assert late.geometry.summary == "file:names nothing"
    assert late.model.summary == NO_SOURCE
    assert late.pins.summary == "0/1"
    assert not late.runs.holds
    assert late.missing() == ("geometry", "model", "pins", "runs")
    # The catalogue places every board or none, and runtime_for asks it first.
    assert after["XIAO-ESP32-C6-DIP"].runs.summary == "refused"
    assert "Late arrival" in after["XIAO-ESP32-C6-DIP"].runs.detail


def test_the_supply_rule_is_read_from_its_one_home_and_a_missing_one_raises(tmp_path):
    assert {"GND", "VBUS", "3V3_OUT"} <= supply_labels()

    elsewhere = tmp_path / "test_x.py"
    elsewhere.write_text('SUPPLY_LABELS = frozenset({"RAIL"})\n', encoding="utf-8")
    assert supply_labels(elsewhere) == {"RAIL"}

    elsewhere.write_text("OTHER = 1\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="SUPPLY_LABELS"):
        supply_labels(elsewhere)


def test_the_supply_rule_refuses_every_form_it_would_misread(tmp_path):
    """Each case is a temp copy of the real file, changed in one place."""
    real = (REPO / "tests" / "rules" / "test_import_pindefs.py").read_text(encoding="utf-8")
    literal = re.compile(r"SUPPLY_LABELS = frozenset\(\{.*?\}\)", re.S)
    assert len(literal.findall(real)) == 1
    copy = tmp_path / "test_import_pindefs.py"
    cases = {
        "rebound later": real + '\nSUPPLY_LABELS = SUPPLY_LABELS | frozenset({"VUSB"})\n',
        "extended in place": real + '\nSUPPLY_LABELS |= frozenset({"VUSB"})\n',
        "a string, not a set": literal.sub('SUPPLY_LABELS = frozenset("GND")', real),
        "another call": literal.sub('SUPPLY_LABELS = set({"GND"})', real),
        "no argument": literal.sub("SUPPLY_LABELS = frozenset()", real),
    }
    for case, text in cases.items():
        copy.write_text(text, encoding="utf-8")
        with pytest.raises(InventoryError, match="SUPPLY_LABELS"):
            supply_labels(copy)
            pytest.fail(f"{case}: read without complaint")

    copy.write_text(real, encoding="utf-8")
    assert supply_labels(copy) == supply_labels()
    # A name bound inside a function is that function's, not the module's.
    copy.write_text(
        real + '\ndef local():\n    SUPPLY_LABELS = frozenset({"X"})\n',
        encoding="utf-8",
    )
    assert supply_labels(copy) == supply_labels()


def test_inventory_calls_supply_exactly_the_pads_test_import_pindefs_does():
    """`is_supply` copies the predicate OH-170's count applies; this holds the
    copy to the original, pad by pad, until OH-172 gives the rule one home.

    The original is the condition in `test_every_pad_either_names_its_pin_or_
    says_why_it_has_none` that tests `SUPPLY_LABELS`, read out of that test
    and evaluated as written.
    """
    from tests.rules import test_import_pindefs as counted

    ours = supply_labels()
    assert ours == counted.SUPPLY_LABELS
    source = pathlib.Path(counted.__file__).read_text(encoding="utf-8")
    counting = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_every_pad_either_names_its_pin_or_says_why_it_has_none"
    )
    conditions = [
        node.test for node in ast.walk(counting)
        if isinstance(node, ast.If) and "SUPPLY_LABELS" in ast.unparse(node.test)
    ]
    assert len(conditions) == 1, [ast.unparse(test) for test in conditions]
    theirs = compile(ast.Expression(conditions[0]), counted.__file__, "eval")

    labels = [
        (path.stem, pad["label"])
        for path in sorted((REPO / "webui" / "boards").glob("*.json"))
        for pad in json.loads(path.read_text(encoding="utf-8"))["pads"]
    ]
    # No label on disk is lower case or joins a supply to a pin with `/`, so
    # these reach the two halves of the predicate the boards never exercise.
    labels += [("probe", label) for label in ("gnd", "Vbus", "GND/PA0", "D0/GND", "d0")]
    supplies = 0
    for board, label in labels:
        # This repository's own test code, with no builtins in reach.
        expected = eval(theirs, {
            "__builtins__": {},
            "SUPPLY_LABELS": counted.SUPPLY_LABELS,
            "label": label,
        })
        assert is_supply(label, ours) == expected, (board, label)
        supplies += expected
    assert supplies, "no pad on any board is a supply, so nothing was compared"
