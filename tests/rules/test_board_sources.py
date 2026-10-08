# OpenHardware - tests for the vendor source registry and its one fetcher.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import collections
import json
import pathlib
import re
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


def _from_the_survey(candidate: Source) -> bool:
    return candidate.cite.startswith("OH-23 survey")


def test_every_row_cites_the_survey_or_the_ticket_that_opened_it():
    """A row the OH-23 survey did not carry names the ticket that listed the
    repository, and reads its licence from a file it fetches. That file is
    a licence the row opened, or, where the repository holds none, the
    README that states one (OH-194): graded `stated`, because a README
    asserting a licence is not the licence."""
    for candidate in SOURCES:
        assert candidate.licence.cite.strip(), f"{candidate.name}: licence with no cite"
        if _from_the_survey(candidate):
            continue
        assert re.match(r"OH-\d+: ", candidate.cite), f"{candidate.name} cites no ticket"
        readme = pathlib.PurePosixPath(candidate.licence.file).name.upper().startswith(
            "README")
        assert candidate.licence.evidence is (
            Evidence.STATED if readme else Evidence.OPENED), candidate.name
        assert candidate.licence.file in candidate.fetch.wanted, candidate.name
        assert candidate.licence.quote.strip(), candidate.name


def test_a_licence_read_from_a_fetched_file_is_in_that_file():
    """Whitespace is normalised: the checkout is CRLF here and the text wraps."""
    checked, unfetched = [], []
    for candidate in SOURCES:
        if not candidate.licence.file:
            continue
        path = candidate.dest(REPO) / candidate.licence.file
        if not path.is_file():
            unfetched.append(candidate.name)
            continue
        text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
        for words in (candidate.licence.quote, candidate.licence.notice):
            assert " ".join(words.split()) in text, f"{path} does not read {words!r}"
        checked.append(candidate.name)
    if unfetched:
        pytest.skip(f"SKIPPED after checking {checked}: {unfetched} not fetched; "
                    f"run python tools/get_board_sources.py <name>")


def test_a_layout_cell_that_states_a_kicad_version_states_the_files_own():
    """`pcb_layout` names the board file it opened and the version it read
    there, and which version a board file is decides how tools/kicad.py
    reads it: 20171130 is KiCad 5, respelled (OH-198), and anything later is
    read as it stands. So the version is the file's `(version ...)`, read
    off the fetched file, and not a note's say-so."""
    stating = re.compile(r"(\S+\.kicad_pcb), KiCad version (\d{8})")
    checked, unfetched = [], []
    for candidate in SOURCES:
        found = stating.search(" ".join(candidate.artefacts.pcb_layout.note.split()))
        if found is None:
            continue
        path = candidate.dest(REPO) / found.group(1)
        if not path.is_file():
            unfetched.append(candidate.name)
            continue
        with path.open(encoding="utf-8") as board:
            opening = board.read(200)
        stated = re.match(r"\(kicad_pcb\s+\(version\s+(\d+)\)", opening)
        assert stated is not None, f"{path} opens {opening[:60]!r}"
        assert stated.group(1) == found.group(2), (
            f"{candidate.name}: pcb_layout says version {found.group(2)} and "
            f"{path.name} is version {stated.group(1)}")
        checked.append(candidate.name)
    assert checked or unfetched, "no layout cell states a KiCad version, so this checks nothing"
    if unfetched:
        pytest.skip(f"SKIPPED after checking {checked}: {unfetched} not fetched; "
                    f"run python tools/get_board_sources.py <name>")


#: The artefact classes a file's suffix decides, and those suffixes. A PDF
#: or a board-support file is not known by its name, so those two are not here.
_BY_SUFFIX = {
    "schematic_source": (".sch", ".kicad_sch", ".schdoc", ".dsn"),
    "pcb_layout": (".kicad_pcb", ".brd", ".pcbdoc"),
    "footprints_symbols": (".kicad_mod", ".kicad_sym", ".lbr", ".lib", ".dcm"),
    "model_3d": (".step", ".stp", ".wrl", ".stl"),
}


def test_a_cell_graded_absent_is_what_the_fetched_listing_holds():
    """`ABSENT` says a complete listing was searched and the class is not
    there, and a fetched clone holds that listing: the sparse, blobless
    fetch still has every tree, so `git ls-tree -r HEAD` lists every file.
    A file of an absent class is allowed only under a directory the cell's
    note names whole -- its path from the top, ending `/`, standing alone as
    a word -- as seeed-xiao's names the clock project's `3d_models/` its
    thirteen .stl are in; `HARDWARE/<rev>/3d/` names no directory. And a
    count a model cell states, `42 .step`, is the listing's (OH-194: the
    Olimex C3's model cell said ABSENT over 74 component models)."""

    def named(directory: str, note: str) -> bool:
        return re.search(rf"(?<![\w/.<>-]){re.escape(directory)}(?=[\s,;:)]|$)",
                         note) is not None

    checked, unfetched = [], []
    for candidate in SOURCES:
        dest = candidate.dest(REPO)
        if candidate.fetch.transport is not Transport.GIT_SPARSE:
            continue
        if not (dest / ".git").is_dir():
            unfetched.append(candidate.name)
            continue
        listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=dest,
                                 capture_output=True, text=True, check=True).stdout.splitlines()
        suffixes = collections.Counter(pathlib.PurePosixPath(path).suffix.lower()
                                       for path in listing)
        for name, known in _BY_SUFFIX.items():
            cell = getattr(candidate.artefacts, name)
            if cell.evidence is Evidence.ABSENT:
                unnamed = [path for path in listing
                           if pathlib.PurePosixPath(path).suffix.lower() in known
                           and not any(named(f"{parent.as_posix()}/", cell.note)
                                       for parent in pathlib.PurePosixPath(path).parents
                                       if parent.as_posix() != ".")]
                assert not unnamed, (
                    f"{candidate.name}.{name} is graded absent and the listing holds "
                    f"{len(unnamed)}, first {unnamed[:3]}")
        stated = {f".{suffix.lower()}": int(count.replace(",", ""))
                  for count, suffix in re.findall(r"(\d[\d,]*) \.(step|stp|wrl|stl)\b",
                                                  candidate.artefacts.model_3d.note, re.I)}
        assert stated == {suffix: suffixes[suffix] for suffix in stated}, (
            candidate.name, stated)
        checked.append(candidate.name)
    if unfetched:
        pytest.skip(f"SKIPPED after checking {checked}: {unfetched} not fetched; "
                    f"run python tools/get_board_sources.py <name>")


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


def test_a_file_named_in_wanted_lands_without_its_neighbours(tmp_path):
    """A board repository keeps its CAD at the top level beside a schematic
    and pictures, where a directory cannot separate them."""
    origin = _origin(
        tmp_path / "origin",
        {
            "board.brd": "layout",
            "board.sch": "schematic",
            "license.txt": "terms",
            "assets/photo.jpg": "picture",
        },
    )
    row = _source(origin.as_uri(), wanted=("board.brd", "license.txt"))

    dest = fetch(row, tmp_path / "root")
    assert _tree(dest) == ["board.brd", "license.txt"]


def test_a_file_name_with_glob_characters_is_fetched_as_written(tmp_path):
    """`[rev A]` unescaped is a character class, which matches `r.brd`."""
    origin = _origin(
        tmp_path / "origin", {"board [rev A].brd": "layout", "board r.brd": "other"}
    )
    row = _source(origin.as_uri(), wanted=("board [rev A].brd",))

    dest = fetch(row, tmp_path / "root")
    assert _tree(dest) == ["board [rev A].brd"]


def test_a_wanted_name_in_the_wrong_case_is_refused_before_anything_lands(tmp_path):
    """Windows' filesystem would find `License.txt` as `license.txt`; git's
    tree does not, and it is git's tree the name is checked against."""
    origin = _origin(
        tmp_path / "origin",
        {"license.txt": "terms", "board.brd": "layout", "board.sch": "schematic"},
    )
    row = _source(origin.as_uri(), wanted=("License.txt",))

    with pytest.raises(SourceError) as caught:
        fetch(row, tmp_path / "root")
    assert "License.txt" in str(caught.value), caught.value
    assert _tree(row.dest(tmp_path / "root")) == []


def test_a_directory_named_with_a_trailing_slash_is_refused(tmp_path):
    """`Hardware/` is not a path git lists as itself, so it is not guessed at."""
    origin = _origin(tmp_path / "origin", {"Hardware/board.brd": "layout"})
    row = _source(origin.as_uri(), wanted=("Hardware/",))

    with pytest.raises(SourceError) as caught:
        fetch(row, tmp_path / "root")
    assert "Hardware/" in str(caught.value), caught.value


def test_a_top_level_path_outside_wanted_is_refused(tmp_path):
    """A tree holding more than the table asked for is not what it says."""
    origin = _origin(tmp_path / "origin", {"board.brd": "layout", "notes.txt": "notes"})
    row = _source(origin.as_uri(), wanted=("board.brd",))
    dest = fetch(row, tmp_path / "root")
    (dest / "stray.txt").write_text("left here", encoding="utf-8")

    with pytest.raises(SourceError) as caught:
        fetch(row, tmp_path / "root")
    assert "stray.txt" in str(caught.value), caught.value


def test_a_row_of_directories_still_lands_the_top_level_files_cone_mode_does(tmp_path):
    """seeed-xiao's licence is its top-level LICENSE, which cone mode lands."""
    origin = _origin(
        tmp_path / "origin",
        {"LICENSE": "terms", "Hardware/board.brd": "layout", "pinout/p.png": "picture"},
    )
    row = _source(origin.as_uri(), wanted=("Hardware",), skipped=(("pinout", "big"),))

    dest = fetch(row, tmp_path / "root")
    assert _tree(dest) == ["Hardware/board.brd", "LICENSE"]


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
    # A row that does not cite the survey is not a surveyed repository cited
    # some other way to leave this check.
    for candidate in SOURCES:
        if not _from_the_survey(candidate):
            assert _survey_row(survey, candidate.fetch.url) is None, candidate.name
    for candidate in filter(_from_the_survey, SOURCES):
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
