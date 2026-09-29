# OpenHardware — tests for the repository inventory generator.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import json
import pathlib
import re
import subprocess
import sys

import pytest

import webui.emulator_server as server
from tools.inventory import (
    MODEL_INDEX,
    NO_SOURCE,
    NOT_BUILT,
    VENDOR_DIR,
    Evidence,
    InventoryError,
    Layer,
    Twin,
    _twin_heading,
    collect_assets,
    collect_boards,
    collect_files,
    collect_ledgers,
    collect_mechanisms,
    collect_tests,
    collect_twins,
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


def _board_file(directory, name, footprint=None, licence=None, pads=None):
    """Write one board definition, with only the fields under test."""
    source = {}
    if footprint is not None:
        source["footprint"] = footprint
    if licence is not None:
        source["licence"] = licence
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
    partial = Twin("Partial", held, held, Layer(False, "0/1", "none on D0"), held)
    assert _twin_heading([whole, partial]) == (
        "1 of 2 boards hold all four; by layer: geometry 2, model 2, pins 1, runs 2"
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


def test_a_blanked_chip_pin_fails_the_pins_layer_and_a_supply_pad_does_not(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    document = _real_board(boards, "XIAO-ESP32-C6-DIP")
    assert collect_twins(boards)[0].pins.holds

    for pad in document["pads"]:
        if pad["label"] == "GND":
            pad["chip_pin"] = None
    (boards / "XIAO-ESP32-C6-DIP.json").write_text(json.dumps(document), encoding="utf-8")
    assert collect_twins(boards)[0].pins.holds, "GND is a supply pad"

    for pad in document["pads"]:
        if pad["label"] == "D0":
            pad["chip_pin"] = None
    (boards / "XIAO-ESP32-C6-DIP.json").write_text(json.dumps(document), encoding="utf-8")
    pins = collect_twins(boards)[0].pins
    assert not pins.holds
    assert pins.detail.endswith("none on D0"), pins.detail


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


def test_geometry_names_the_cad_file_or_says_there_is_none(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "Footprint", footprint="XIAO-RP2040-DIP")
    _board_file(boards, "Unsourced")
    (boards / "Filed.json").write_text(json.dumps({
        "board": "Filed", "pads": [], "source": {"file": "third_party/x/board.brd"},
    }), encoding="utf-8")

    geometry = {twin.name: twin.geometry for twin in collect_twins(boards)}
    assert geometry["Filed"] == (True, "file", "third_party/x/board.brd")
    assert geometry["Footprint"] == (True, "footprint", "XIAO-RP2040-DIP")
    assert not geometry["Unsourced"].holds
    assert "source.file" in geometry["Unsourced"].detail


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
    assert late.geometry.holds
    assert late.model.summary == NO_SOURCE
    assert late.pins.summary == "0/1"
    assert not late.runs.holds
    assert late.missing() == ("model", "pins", "runs")


def test_the_supply_rule_is_read_from_its_one_home_and_a_missing_one_raises(tmp_path):
    assert {"GND", "VBUS", "3V3_OUT"} <= supply_labels()

    elsewhere = tmp_path / "test_x.py"
    elsewhere.write_text('SUPPLY_LABELS = frozenset({"RAIL"})\n', encoding="utf-8")
    assert supply_labels(elsewhere) == {"RAIL"}

    elsewhere.write_text("OTHER = 1\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="SUPPLY_LABELS"):
        supply_labels(elsewhere)
