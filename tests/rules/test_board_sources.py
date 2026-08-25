# OpenHardware - tests for the vendor source registry and its one fetcher.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import json
import pathlib
import subprocess

import pytest

from tools.board_sources import (
    ARTEFACT_CLASSES,
    SOURCES,
    SURVEY,
    Artefact,
    Artefacts,
    Evidence,
    Fetch,
    Licence,
    Published,
    Source,
    SourceError,
    Transport,
    fetchable,
    source,
    sources,
)
from tools.get_board_sources import fetch

REPO = pathlib.Path(__file__).resolve().parents[2]
FETCHER = REPO / "tools" / "get_board_sources.py"


def _nothing() -> Artefacts:
    """Six answered cells, none of them the subject of the test using them."""
    blank = Artefact(Published.NO, Evidence.ABSENT, "nothing here")
    return Artefacts(blank, blank, blank, blank, blank, blank)


def _origin(root, files):
    """A git repository holding `files`, servable over `file://`.

    `uploadpack.allowFilter` is set because the fetcher clones with
    `--filter=blob:none`, and a partial clone is refused unless the *serving*
    repository allows it. GitHub allows it; a bare local repository does not
    until told to, and without this the fixture would fail for a reason that
    has nothing to do with the code under test.
    """
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    for command in (
        ["init", "-q"],
        ["config", "uploadpack.allowFilter", "true"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "test"],
        ["add", "-A", "-f"],
        ["commit", "-qm", "vendor"],
    ):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    return root


def _source(url, wanted=(), skipped=()):
    """A registry row pointing at a local origin, with only fetch under test."""
    return Source(
        name="probe",
        vendor="Probe Instruments",
        model="one repository",
        size="tiny",
        licence=Licence("MIT", "design files", False, Evidence.OPENED, "fixture"),
        fetch=Fetch(Transport.GIT_SPARSE, url, wanted, skipped),
        artefacts=_nothing(),
        cite="fixture",
    )


def _tree(dest):
    return sorted(
        path.relative_to(dest).as_posix()
        for path in dest.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(dest).parts
    )


# --- the table -------------------------------------------------------------


def test_every_source_has_a_distinct_name():
    """`name` is the key, the CLI argument and the directory under third_party."""
    names = [candidate.name for candidate in SOURCES]
    assert len(set(names)) == len(names), f"duplicate source names: {names}"


def test_a_vendor_is_not_the_key_because_a_vendor_is_not_unique():
    """The survey carries two Raspberry Pi rows for two download portals.

    Keying on vendor would have silently dropped one of them, and the same
    shape is coming for every vendor that ships more than one portal.
    """
    assert source("seeed-xiao").name == "seeed-xiao"
    with pytest.raises(SourceError, match="Seeed Studio|no source called"):
        source("Seeed Studio")


def test_an_unknown_source_names_the_ones_that_exist():
    with pytest.raises(SourceError) as caught:
        source("nordic-nrf52840-dk")
    message = str(caught.value)
    assert "nordic-nrf52840-dk" in message
    for candidate in SOURCES:
        assert candidate.name in message, "the error must list what is available"


def test_the_seeed_row_lands_where_the_existing_tools_already_look():
    """Two other tools hold paths built from this name; renaming it breaks them.

    `tools/inventory.py` grades board assets out of that directory and
    `tools/import_board.py` reads the KiCad library out of it. Neither imports
    this registry, so nothing but this test couples them.

    The second half used to come from `tools/import_kicad_board.py`'s own
    `VENDOR` constant. OH-41 retired that file, so the library path is spelled
    here -- which is what `tests/rules/test_kicad.py` already does, and is the
    only remaining place it is written down.
    """
    from tools.inventory import VENDOR_DIR

    dest = source("seeed-xiao").dest(REPO)
    assert dest == REPO / VENDOR_DIR

    library = dest / "Seeed Studio XIAO Series Library"
    assert library.is_relative_to(dest), f"{library} is no longer under {dest}"


def test_a_source_can_record_that_a_vendor_publishes_nothing_of_a_kind():
    """The finding OH-27 needed and could not express.

    Seeed is the vendor this project imports 25 boards from, and it publishes
    no schematic in any format and no PCB layout at all. A schema that could
    only describe what a vendor *has* would render that as blank fields and
    read as "not looked into yet".
    """
    seeed = source("seeed-xiao")
    for missing in ("schematic_source", "schematic_pdf", "pcb_layout"):
        assert missing in seeed.absent(), f"{missing} must be a recorded absence"
        cell = getattr(seeed.artefacts, missing)
        assert cell.published is Published.NO
        assert cell.evidence is Evidence.ABSENT


def test_absent_means_searched_not_merely_unrecorded():
    """`absent()` counts only cells graded ABSENT, never a `NO` on weaker evidence."""
    stated_no = Artefact(Published.NO, Evidence.STATED, "the vendor page says so")
    row = _source("file:///nowhere")._replace(
        artefacts=_nothing()._replace(model_3d=stated_no)
    )
    assert "model_3d" not in row.absent()
    assert set(row.absent()) == set(ARTEFACT_CLASSES) - {"model_3d"}


def test_every_cell_that_says_no_says_what_was_searched():
    for candidate in SOURCES:
        for name in ARTEFACT_CLASSES:
            cell = getattr(candidate.artefacts, name)
            if cell.published is Published.NO:
                assert cell.note.strip(), (
                    f"{candidate.name}.{name} says no without saying what was looked for"
                )


def test_every_skipped_path_carries_a_reason():
    """A skip list with no reasons beside it becomes folklore in one release."""
    for candidate in SOURCES:
        for path, why in candidate.fetch.skipped:
            assert path.strip(), f"{candidate.name} skips an empty path"
            assert len(why.strip()) > 20, (
                f"{candidate.name} skips {path} without a reason worth reading: {why!r}"
            )


def test_every_row_cites_the_survey_it_came_from():
    for candidate in SOURCES:
        assert "OH-23" in candidate.cite, f"{candidate.name} cites no survey row"
        assert candidate.licence.cite.strip(), f"{candidate.name}: licence with no cite"


def test_a_licence_read_from_one_of_many_repositories_says_so():
    """The reason this is not a dict of vendor to licence string.

    A vendor shipping one repository per board has a licence per repository,
    and the survey found a SparkFun board repository whose README points at a
    LICENSE.md the repository does not contain. Storing one licence per vendor
    would state terms for 1,412 repositories nobody opened.
    """
    for candidate in SOURCES:
        if "per board" in candidate.model:
            assert candidate.licence.sampled, (
                f"{candidate.name} ships one repository per board, so its licence "
                f"cannot be claimed for the vendor"
            )
    assert not source("seeed-xiao").licence.sampled, (
        "one repository for the whole range means the licence does cover it all"
    )


# --- one code path, no vendor in it ----------------------------------------


def test_three_vendors_fetch_through_one_transport():
    """OH-24's done-criterion, as a check rather than a claim."""
    git_backed = [
        candidate
        for candidate in fetchable()
        if candidate.fetch.transport is Transport.GIT_SPARSE
    ]
    assert len(git_backed) == len(fetchable()), "fetchable() let a transport through"
    vendors = {candidate.vendor for candidate in git_backed}
    assert len(vendors) >= 3, f"only {sorted(vendors)} fetch through the one path"


def test_the_fetcher_names_no_vendor():
    """The mechanised form of "no vendor-specific branch".

    Everything vendor-shaped — name, URL, what to fetch, what to skip and why
    — lives in the table. If any of it reappears in the fetcher, the thing
    this ticket set out to delete has grown back.
    """
    text = FETCHER.read_text(encoding="utf-8")
    leaked = [
        value
        for candidate in SOURCES
        for value in (candidate.name, candidate.vendor, candidate.fetch.url)
        if value in text
    ]
    assert not leaked, f"{FETCHER.name} names sources it should only be given: {leaked}"


def test_a_transport_this_tool_does_not_perform_is_refused_by_name(tmp_path):
    """Listed and excluded, never quietly missing.

    Six surveyed vendors publish a per-board zip behind a product page. The
    registry carries them so the market is not misrepresented as uniformly
    git-shaped, and the fetcher says plainly that it does not do that, with
    the URL to do it by hand.
    """
    archived = [
        candidate
        for candidate in SOURCES
        if candidate.fetch.transport is Transport.HTTPS_ARCHIVE
    ]
    assert archived, "if every source became git-backed, this test has expired"
    for candidate in archived:
        assert candidate not in fetchable()
        with pytest.raises(SourceError) as caught:
            fetch(candidate, tmp_path)
        assert candidate.fetch.url in str(caught.value)


# --- the fetch itself ------------------------------------------------------


def test_a_sparse_fetch_lands_what_the_table_asked_for_and_nothing_it_skipped(tmp_path):
    origin = _origin(
        tmp_path / "origin",
        {
            "Hardware/board.sch": "schematic",
            "Hardware/board.brd": "layout",
            "pinout/huge.png": "a picture of a pinout, not a pinout",
        },
    )
    row = _source(origin.as_uri(), wanted=("Hardware",), skipped=(("pinout", "big"),))

    dest = fetch(row, tmp_path / "root")
    assert _tree(dest) == ["Hardware/board.brd", "Hardware/board.sch"]


def test_all_fetches_the_skipped_paths_too(tmp_path):
    origin = _origin(
        tmp_path / "origin",
        {"Hardware/board.sch": "schematic", "pinout/huge.png": "picture"},
    )
    row = _source(origin.as_uri(), wanted=("Hardware",), skipped=(("pinout", "big"),))

    dest = fetch(row, tmp_path / "root", everything=True)
    assert _tree(dest) == ["Hardware/board.sch", "pinout/huge.png"]


def test_a_source_with_nothing_to_narrow_fetches_everything(tmp_path):
    origin = _origin(tmp_path / "origin", {"a.sch": "one", "b/c.brd": "two"})
    dest = fetch(_source(origin.as_uri()), tmp_path / "root")
    assert _tree(dest) == ["a.sch", "b/c.brd"]


def test_a_fetch_that_does_not_land_the_wanted_paths_raises(tmp_path):
    """The generic form of the retiring script's footprint count.

    That script counted `.kicad_mod` and `.kicad_sym` because a silent empty
    fetch makes the importer report zero boards over zero footprints, which
    reads exactly like success. Stated in terms of the table instead of one
    vendor's file extensions, it works for every source.
    """
    origin = _origin(tmp_path / "origin", {"Elsewhere/board.sch": "schematic"})
    row = _source(origin.as_uri(), wanted=("Hardware",))

    with pytest.raises(SourceError) as caught:
        fetch(row, tmp_path / "root")
    message = str(caught.value)
    assert "Hardware" in message, "the error must name what was missing"
    assert "Elsewhere" in message, "and what the repository holds instead"


def test_re_fetching_keeps_the_clone_and_only_renarrows(tmp_path):
    """Nothing here deletes a tree another tool is already reading out of."""
    origin = _origin(
        tmp_path / "origin", {"Hardware/board.sch": "schematic", "pinout/p.png": "pic"}
    )
    row = _source(origin.as_uri(), wanted=("Hardware",), skipped=(("pinout", "big"),))
    root = tmp_path / "root"

    dest = fetch(row, root)
    marker = dest / ".git" / "oh24-marker"
    marker.write_text("this clone", encoding="utf-8")

    again = fetch(row, root)
    assert again == dest
    assert marker.read_text(encoding="utf-8") == "this clone", "the clone was replaced"
    assert _tree(dest) == ["Hardware/board.sch"]


# --- the table cannot drift from the survey it cites -----------------------


def _survey():
    """The OH-23 survey, or a skip saying it is not here.

    Skipped rather than defaulted, in the manner of the `upstream` fixture and
    the checkers' exit 3: a drift test that passes because it could not find
    the thing it compares against is the vacuous green this repository keeps
    deleting. Research under `docs/research/` is deliberately unadopted, so
    the registry never reads it at runtime — only this test does, and only to
    prove the hand-written rows still say what the evidence said.
    """
    path = REPO / SURVEY
    if not path.is_file():
        pytest.skip(f"SKIPPED: {SURVEY.as_posix()} is not in this checkout (OH-23)")
    return json.loads(path.read_text(encoding="utf-8"))


def _survey_row(survey, url):
    """The survey row for a registry URL, matched on the URL itself."""
    bare = url[: -len(".git")] if url.endswith(".git") else url
    for row in survey["sources"]:
        if row.get("url") == bare:
            return row
    return None


def test_the_evidence_classes_are_the_surveys_own_vocabulary():
    """A synonym invented here would read as a disagreement about the world."""
    survey = _survey()
    assert {evidence.label for evidence in Evidence} == set(survey["evidence_classes"])
    for evidence in Evidence:
        assert evidence.gloss.strip(), f"{evidence.label} has no gloss"


def test_every_registry_row_still_matches_the_survey_row_it_cites():
    """The one hand-written thing, checked against the evidence behind it.

    Every cell here was copied from the survey by hand, which is exactly the
    operation `CLAUDE.md` says rots fastest. It cannot be generated — what a
    vendor publishes is a fact about somebody else's server, and adopting
    research is a decision rather than a computation — so it is copied once
    and then pinned.
    """
    survey = _survey()
    for candidate in SOURCES:
        row = _survey_row(survey, candidate.fetch.url)
        assert row is not None, (
            f"{candidate.name} cites the survey but no survey row has its URL "
            f"({candidate.fetch.url})"
        )
        assert candidate.vendor == row["vendor"], (
            f"{candidate.name}: vendor {candidate.vendor!r} against survey "
            f"{row['vendor']!r}"
        )
        assert candidate.licence.name in row["licence"]["value"], (
            f"{candidate.name}: licence {candidate.licence.name!r} is not what the "
            f"survey read ({row['licence']['value']!r})"
        )
        assert candidate.size in row["size"]["value"], (
            f"{candidate.name}: size {candidate.size!r} against survey "
            f"{row['size']['value']!r}"
        )

        for name in ARTEFACT_CLASSES:
            cell = getattr(candidate.artefacts, name)
            surveyed = row["artefacts"][name]
            assert cell.published.value == surveyed["value"], (
                f"{candidate.name}.{name}: registry says {cell.published.value!r}, "
                f"survey says {surveyed['value']!r}"
            )
            assert cell.evidence.label == surveyed["evidence"], (
                f"{candidate.name}.{name}: registry grades it "
                f"{cell.evidence.label!r}, survey graded it {surveyed['evidence']!r}"
            )


def test_the_survey_is_marked_unadopted_and_the_registry_is_the_adoption():
    """`docs/research/` is evidence; this table is the decision made from it."""
    survey = _survey()
    assert survey.get("adopted") is False, (
        "if the survey has been adopted, the registry is no longer the only "
        "place the decision is written down"
    )


# --- the command line ------------------------------------------------------


def test_listing_the_registry_runs_and_names_every_source():
    import sys

    result = subprocess.run(
        [sys.executable, "tools/get_board_sources.py", "--list"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for candidate in SOURCES:
        assert candidate.name in result.stdout
        assert candidate.fetch.url in result.stdout


def test_the_list_says_what_a_source_does_not_publish():
    import sys

    result = subprocess.run(
        [sys.executable, "tools/get_board_sources.py", "--list"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "publishes no schematic_source" in result.stdout, (
        "the absence is the finding; it has to be visible without opening the table"
    )
