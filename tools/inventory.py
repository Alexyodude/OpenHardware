#!/usr/bin/env python3
# OpenHardware — derive the repository inventory from the repository itself.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Report what this repository contains: tests, mechanisms, files, ledger cells.

The numbers are **computed, never claimed**. A hand-maintained inventory saying
"65 tests" is wrong the moment someone adds a test, and this repository has
already caught that failure twice in its own rule documents — `licence-hygiene.md`
and `upstream-sync.md` each drifted from the code they described inside a single
session. An inventory is exactly the kind of document that rots fastest, so
this one is generated on demand instead of written down.

Seven collectors, one per thing worth counting:

* `collect_tests`   — parses each test file with `ast`
* `collect_mechanisms` — reads `rules/*.md` frontmatter
* `collect_files`   — asks git what this repository tracks
* `collect_ledgers` — parses every ledger under `docs/features/`
* `collect_boards`  — reads every board definition under `webui/boards/`
* `collect_assets`  — searches for the CAD behind each board, and grades it
* `collect_twins`   — the four digital-twin layers per board (OH-174)

Each raises rather than returning an empty result. A report that renders
cheerfully with nothing in it is indistinguishable from a report of a healthy
repository, which is the vacuous green this project exists to prevent.

`collect_assets` is the one that reports on things this repository does not
have. Every cell it emits carries an evidence class, because *a schematic
exists* and *a schematic was opened and parsed* are answers to different
questions and a survey that renders them in the same cell has stopped being
useful. Reading "absent" across a row is the intended output, not a failure.

**Known model limit:** `collect_tests` counts `def test_*` via `ast`, so it
counts a parametrised test once where pytest counts it many times. No test here
is parametrised today, and `test_ast_count_matches_pytest_collection` fails
loudly if that ever stops being true — the divergence is designed to be noisy
rather than silent.
"""

from __future__ import annotations

import argparse
import ast
import collections
import enum
import json
import pathlib
import subprocess
import sys
import typing

try:
    from tools import board_sources, kicad
    from tools.import_3d_model import COMPOSED, MODELS
    from tools.import_board import READERS
    from tools.import_pindefs import DISPUTED, NO_PACKAGE_AT_ALL, NOT_PUBLISHED, NOT_TRACED
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules
    from webui.boards import catalogue
    from webui.emulator_server import resolve_static
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    # Unlike the four checkers, this tool imports its siblings. Running it as
    # `python tools/inventory.py` puts `tools/` on sys.path rather than the repo
    # root, so the package is not importable. Rather than force
    # `python -m tools.inventory` and break the `python tools/<name>.py`
    # convention CLAUDE.md documents for every other tool, put the repo root on
    # the path and retry. Both invocations then work.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import board_sources, kicad
    from tools.import_3d_model import COMPOSED, MODELS
    from tools.import_board import READERS
    from tools.import_pindefs import DISPUTED, NO_PACKAGE_AT_ALL, NOT_PUBLISHED, NOT_TRACED
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules
    from webui.boards import catalogue
    from webui.emulator_server import resolve_static

TESTS_DIR = pathlib.Path("tests/rules")
RULES_DIR = pathlib.Path("rules")
FEATURES_DIR = pathlib.Path("docs/features")
BOARDS_DIR = pathlib.Path("webui/boards")
#: Where `python tools/get_board_sources.py seeed-xiao` puts the vendor's CAD.
#: Fetched, never vendored, and git-ignored — a survey of what a vendor
#: publishes must not quietly become a copy of it.
#:
#: The registry in `tools/board_sources.py` is the authority on this path:
#: `source("seeed-xiao").dest(root)` computes it, and `Source.name` is
#: documented as stable because other tools hold paths built from it. It is
#: still spelled out here rather than looked up, because a lookup at import
#: time turns a missing registry entry into a module that will not load, and
#: this one is read by every `--markdown` run. `test_the_vendor_dir_is_the
#: _registry_s_own_path` binds the two instead, so they cannot drift quietly.
VENDOR_DIR = pathlib.Path("third_party/seeed-xiao")
#: The one list of supply labels, OH-170's. `tools/import_pindefs.py` has no
#: supply rule of its own, so the set is read out of the test that counts
#: supply pads, by `ast`, rather than copied here.
SUPPLY_SOURCE = pathlib.Path("tests/rules/test_import_pindefs.py")
#: What `webui/static/board3d-panel.js` fetches to learn which board has a model.
MODEL_INDEX = "/models/index.json"
#: Top-level directories, in the order the report lists them. Anything
#: outside them lands in `other`, which is deliberately visible: the
#: separation from upstream is only kept by noticing when something
#: unexpected appears at the root.
KNOWN_AREAS = (
    "webui",
    "tools",
    "tests",
    "docs",
    "rules",
    "skills",
    "patches",
    ".github",
)


class InventoryError(Exception):
    """A source of inventory data is missing, empty, or unreadable."""


def collect_tests(tests_dir: pathlib.Path = TESTS_DIR) -> dict[str, int]:
    """Map each test file to the number of `def test_*` functions it declares."""
    if not tests_dir.is_dir():
        raise InventoryError(f"{tests_dir}: test directory does not exist")
    paths = sorted(tests_dir.glob("test_*.py"))
    if not paths:
        raise InventoryError(f"{tests_dir}: contains no test files")

    counts: dict[str, int] = {}
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise InventoryError(f"{path}: does not parse: {exc}") from exc
        counts[path.as_posix()] = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return counts


def collect_mechanisms(
    rules_dir: pathlib.Path = RULES_DIR,
) -> list[tuple[str, str, bool, str | None]]:
    """Every declared mechanism as (rule, tier, armed, checker)."""
    try:
        rules = load_rules(rules_dir)
    except RuleParseError as exc:
        # Surface every failure as InventoryError so a caller catches one type.
        # main() catches only InventoryError, so letting this through would
        # print a traceback instead of a diagnostic.
        raise InventoryError(f"{rules_dir}: {exc}") from exc

    rows = [
        (rule.name, mech.tier, mech.armed, mech.checker)
        for rule in rules
        for mech in rule.mechanisms
    ]
    if not rows:
        raise InventoryError(f"{rules_dir}: rules declare no mechanisms at all")
    return rows


def collect_files(repo: pathlib.Path | None = None) -> dict[str, list[str]]:
    """Every tracked file, grouped by top-level directory.

    This used to ask `git diff fork-point HEAD` — what did we change
    relative to upstream. That question died with the fork: PICSimLab is no
    longer in this tree, so there is no fork point to diff against and
    **every tracked file is ours**. Asking git what it tracks is the same
    question more directly put, and it needs no tag pushed to a remote for
    CI to work — which is what kept `.github/workflows/rules.yml` from
    ever running.

    Grouping is by area rather than git status letter for the same reason:
    with nothing inherited, `added` against `modified` says nothing, while
    `webui 34, tools 13` says what the repository is made of.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        NotADirectoryError,
    ) as exc:
        raise InventoryError(f"git ls-files failed: {exc}") from exc

    grouped: dict[str, list[str]] = collections.defaultdict(list)
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        head = path.split("/")[0]
        grouped[head if head in KNOWN_AREAS else "other"].append(path)

    if not grouped:
        raise InventoryError("git tracks no files here; this is not the repository")
    return dict(grouped)


def collect_ledgers(
    features_dir: pathlib.Path = FEATURES_DIR,
) -> dict[str, collections.Counter]:
    """Cell counts per status, for every ledger under docs/features/."""
    if not features_dir.is_dir():
        raise InventoryError(f"{features_dir}: features directory does not exist")
    paths = sorted(features_dir.glob("*.md"))
    if not paths:
        raise InventoryError(f"{features_dir}: contains no ledgers")

    try:
        return {
            path.as_posix(): collections.Counter(
                cell.status for cell in parse_ledger(path)
            )
            for path in paths
        }
    except LedgerError as exc:
        raise InventoryError(f"{features_dir}: {exc}") from exc


class Board(typing.NamedTuple):
    """One board definition, and how much of it the simulator can reach."""

    name: str
    pads: int
    wired: int
    vendor: str | None
    licence: str | None
    art: bool


def collect_boards(boards_dir: pathlib.Path = BOARDS_DIR) -> list[Board]:
    """Every board under `webui/boards/`, with its pad and wiring counts.

    `wired` is the number of pads carrying a simulator pin index, and it is the
    only field here that says whether a board *does* anything over rcontrol.
    A pad whose `pin` is null has no PICSimLab pin behind it — every XIAO file
    says so in its own `assumption` field, and gives the reason: a guessed pin
    number would wire the circuit wrongly and report success. Since OH-160 the
    same files also carry a `chip_pin`, the MCU pin the board's own module
    reads a level through; that is the 3D view's join and a different count,
    printed by `python tools/import_pindefs.py --all --summary`, not this one.

    So the count that matters is not how many boards exist. Reporting "26
    boards" without the wiring split would claim twenty-five that cannot be
    connected to anything, which is the vacuous green this whole tool exists
    to prevent.
    """
    if not boards_dir.is_dir():
        raise InventoryError(f"{boards_dir}: boards directory does not exist")
    paths = sorted(boards_dir.glob("*.json"))
    if not paths:
        raise InventoryError(f"{boards_dir}: contains no board definitions")

    boards = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryError(f"{path}: {exc}") from exc
        pads = data.get("pads")
        if not isinstance(pads, list):
            raise InventoryError(
                f"{path}: expected a `pads` list, got {type(pads).__name__}"
            )
        # On an imported board `source` names the vendor file, or the
        # footprint in one, its pads were read from: a XIAO's names a
        # footprint in Seeed's library. On the Arduino Uno, whose pads were
        # traced from PICSimLab's artwork, it names the vendor file they are
        # checked against instead (tests/rules/test_uno_geometry.py). A board file
        # with no `source` has its provenance reported as missing rather than
        # defaulted to a vendor name, because "we do not know where this came
        # from" is the finding.
        source = data.get("source") or {}
        boards.append(
            Board(
                name=data.get("board", path.stem),
                pads=len(pads),
                wired=sum(1 for pad in pads if pad.get("pin") is not None),
                vendor=source.get("vendor"),
                licence=source.get("licence"),
                art=path.with_suffix(".svg").is_file(),
            )
        )
    return boards


class Evidence(enum.Enum):
    """How strong a claim one asset cell is making, strongest first.

    `docs/architectures.md` marks each of its findings with the class of
    evidence behind it, because "the datasheet says 400 MHz" and "a repost
    says 360 MHz" are not the same claim and averaging them helps nobody. An
    asset survey has that problem in a sharper form: *a schematic exists* and
    *a schematic was opened and parsed* are answers to different questions,
    and the gap between them is where a survey stops being useful.

    The two weakest classes are the ones to read carefully, because they look
    alike and are not. `ABSENT` means the search ran and there is nothing --
    a finding about the tree searched, which is not everything the vendor
    publishes. `UNSEARCHABLE` means the search could not run
    at all, which is a finding about *this checkout*: `third_party/` is
    git-ignored, so a fresh clone has no vendor tree, and reporting `absent`
    there would manufacture twenty-six negative results out of a fetch nobody
    performed.

    The gloss travels with the member rather than in a table beside it, so a
    class cannot be added without the report learning how to explain it.
    """

    PARSED = ("parsed", "this tool opened the file and read what is in it")
    PRESENT = ("present", "a file is on disk; nothing here has opened it")
    INDEXED = ("indexed", "the vendor's git tree names it; it is not on this disk")
    ABSENT = ("absent", "the search ran and found nothing")
    UNSEARCHABLE = (
        "unsearchable",
        "the search could not run: no vendor tree, or no source recorded",
    )

    def __init__(self, label: str, gloss: str) -> None:
        self.label = label
        self.gloss = gloss


#: What counts as each asset, as (form, suffixes) in the order the report
#: prefers them. `form` names the distinction only where it changes what can
#: be done with the file: a schematic in source form can become a netlist
#: (OH-28), a schematic as a PDF can be read by a person and nothing else.
#: The non-KiCad suffixes are here because the boards this project wants are
#: not all published in KiCad; Eagle and Altium cover nearly all of the rest.
SCHEMATIC_FORMS = (("source", (".kicad_sch", ".sch", ".schdoc")), ("PDF", (".pdf",)))
PCB_FORMS = ((None, (".kicad_pcb", ".brd", ".pcbdoc")),)
MODEL_FORMS = ((None, (".step", ".stp", ".wrl", ".stl", ".3mf")),)
#: File stems that carry a licence. `COPYING` is here because GPL trees use it.
LICENCE_STEMS = frozenset({"license", "licence", "copying"})
#: The asset cells, in report order. Named once so the two renderers and the
#: completeness count cannot disagree about what "all of them" means.
ASSET_CELLS = ("schematic", "pcb", "model3d", "pins", "licence")


class Asset(typing.NamedTuple):
    """One cell of the asset report: what was found, and how well it is known."""

    evidence: Evidence
    #: The value behind the cell — the path that was found, the counts that
    #: were read, or the reason the search could not run. Never a bare "no".
    detail: str
    #: The form of the asset, where the form changes what it is good for.
    #: Only the schematic sets it: `source` or `PDF`.
    form: str | None = None

    def summary(self) -> str:
        """The cell as one short token, for the fixed-width text report."""
        return f"{self.evidence.label}:{self.form}" if self.form else self.evidence.label


class BoardAssets(typing.NamedTuple):
    """What one board has behind it, cell by cell."""

    name: str
    schematic: Asset
    pcb: Asset
    model3d: Asset
    pins: Asset
    licence: Asset

    def missing(self) -> tuple[str, ...]:
        """The cells this report cannot show anything for.

        `UNSEARCHABLE` counts as missing alongside `ABSENT`, and the wording
        matters: this is "the report has nothing here", not "the vendor
        published nothing". A board is never called complete on the strength
        of a search that did not run — OH-13 set that precedent when the
        board list refused to call twenty-five unwired boards supported.
        """
        return tuple(
            cell
            for cell in ASSET_CELLS
            if getattr(self, cell).evidence
            in (Evidence.ABSENT, Evidence.UNSEARCHABLE)
        )


class _Tree(typing.NamedTuple):
    """The vendor CAD tree, or the reason there is nothing to search."""

    root: pathlib.Path
    on_disk: tuple[str, ...]
    indexed: tuple[str, ...]
    unsearchable: str | None


def _vendor_tree(vendor_dir: pathlib.Path, name: str = "seeed-xiao") -> _Tree:
    """Everything the vendor tree holds, split by whether it was fetched.

    `name` is the registry source whose fetch makes the tree, for the command
    a reader is told to run.

    The index half is the reason this consults git at all.
    `tools/get_board_sources.py` clones **sparsely by default** — the KiCad
    library and `document/`, nothing else — because the full tree is ~196 MB
    of marketing PNGs. A disk-only search over a sparse checkout would report
    "no schematic" for a schematic sitting in the repository unfetched, which
    is a false negative wearing the clothes of a finding.
    """
    if not vendor_dir.is_dir():
        return _Tree(
            vendor_dir,
            (),
            (),
            f"{vendor_dir.as_posix()} is not fetched here; "
            f"run: python tools/get_board_sources.py {name}",
        )

    on_disk: list[str] = []
    for entry in sorted(vendor_dir.iterdir()):
        if entry.name == ".git":
            continue
        if entry.is_file():
            on_disk.append(entry.name)
            continue
        on_disk += [
            path.relative_to(vendor_dir).as_posix()
            for path in entry.rglob("*")
            if path.is_file()
        ]
    on_disk.sort()

    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "HEAD", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
            cwd=vendor_dir,
        )
    except subprocess.CalledProcessError as exc:
        raise InventoryError(
            f"{vendor_dir}: git ls-tree failed: {(exc.stderr or '').strip() or exc}. "
            f"This should be the clone `python tools/get_board_sources.py {name}` "
            f"makes; delete it and fetch again."
        ) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise InventoryError(f"{vendor_dir}: cannot run git here: {exc}") from exc

    fetched = set(on_disk)
    indexed = sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip() not in fetched
    )
    return _Tree(vendor_dir, tuple(on_disk), tuple(indexed), None)


def _source_tree(registered: board_sources.Source) -> _Tree:
    """The tree a registry source is fetched into, under the working directory
    as `_file_geometry` resolves it.

    A `GIT_SPARSE` source is a clone, read as `_vendor_tree` reads Seeed's.
    An `HTTPS_ARCHIVE` is a zip unpacked by hand, so it has no index and holds
    only what is on disk -- and `git ls-tree` run in it would ask this
    repository, which tracks nothing under `third_party/`, and not the vendor.
    """
    dest = registered.dest(pathlib.Path("."))
    if registered.fetch.transport is board_sources.Transport.GIT_SPARSE:
        return _vendor_tree(dest, registered.name)
    if not dest.is_dir():
        return _Tree(
            dest,
            (),
            (),
            f"{dest.as_posix()} is not fetched here; "
            f"run: python tools/get_board_sources.py {registered.name}",
        )
    on_disk = sorted(
        path.relative_to(dest).as_posix() for path in dest.rglob("*") if path.is_file()
    )
    return _Tree(dest, tuple(on_disk), (), None)


def _named_for(
    paths: tuple[str, ...], footprint: str, suffixes: tuple[str, ...]
) -> str | None:
    """The first path naming `footprint` exactly and ending in one of `suffixes`.

    Exact names only: the file's stem *is* the footprint, or one of its parent
    directories *is*. Prefix matching is refused, and
    `webui/boards/catalogue.py` spends four paragraphs on why — `startswith`
    matched `ESP32-C6` against `ESP32-C61`, a different real part. The same
    shortcut here would match `XIAO-ESP32-C3-DIP` against
    `XIAO-ESP32-C3-DIP-SMD.kicad_sch` and file one board's schematic under its
    neighbour's name. A missed schematic is a false `absent` somebody can go
    and fix; a schematic filed under the wrong board is a wrong answer nobody
    can see.
    """
    for path in paths:
        candidate = pathlib.PurePosixPath(path)
        if candidate.suffix.lower() not in suffixes:
            continue
        if candidate.stem == footprint or footprint in candidate.parent.parts:
            return path
    return None


def _vendor_cell(
    forms: tuple[tuple[str | None, tuple[str, ...]], ...],
    footprint: str | None,
    tree: _Tree,
) -> Asset:
    """One cell for an asset that would live in the vendor's tree.

    On-disk hits beat indexed ones whatever the form, because `PRESENT` is the
    stronger claim; the form is reported either way, so preferring a fetched
    PDF over an unfetched source file loses nothing.
    """
    if tree.unsearchable:
        return Asset(Evidence.UNSEARCHABLE, tree.unsearchable)
    if not footprint:
        return Asset(
            Evidence.UNSEARCHABLE,
            "the board file records no `source.footprint`, so there is no name "
            "to search the vendor tree for",
        )

    for form, suffixes in forms:
        hit = _named_for(tree.on_disk, footprint, suffixes)
        if hit:
            return Asset(Evidence.PRESENT, f"{tree.root.as_posix()}/{hit}", form)
    for form, suffixes in forms:
        hit = _named_for(tree.indexed, footprint, suffixes)
        if hit:
            return Asset(
                Evidence.INDEXED,
                f"{hit} — in the vendor's git tree, not fetched",
                form,
            )

    wanted = "/".join(suffix for _, group in forms for suffix in group)
    return Asset(
        Evidence.ABSENT,
        f"nothing named {footprint} with a {wanted} suffix under "
        f"{tree.root.as_posix()}",
    )


def _pin_cell(path: pathlib.Path, pads: list) -> Asset:
    """The pin-definition cell, the only one this tool reads for itself.

    `PARSED` is the honest class here and nowhere else: the pad map was
    opened, decoded and counted a few lines above. The counts go in the detail
    because "there is a pin definition" is a much weaker statement than it
    sounds — on twenty-five of these boards every `pin` is null, and a cell
    saying only `parsed` would read as though they were wired.
    """
    if not pads:
        return Asset(Evidence.ABSENT, f"{path.as_posix()} declares no pads")
    wired = sum(1 for pad in pads if pad.get("pin") is not None)
    return Asset(
        Evidence.PARSED,
        f"{len(pads)} pads, {wired} carrying a simulator pin index",
    )


def _licence_file(paths: tuple[str, ...]) -> str | None:
    """The licence file nearest the root of the tree, if there is one.

    Nearest, because a `COPYING` buried in one sample project covers that
    project; the one at the top covers the CAD.
    """
    candidates = [
        path
        for path in paths
        if pathlib.PurePosixPath(path).stem.lower() in LICENCE_STEMS
    ]
    return min(candidates, key=lambda path: (path.count("/"), path), default=None)


def _licence_cell(licence: str | None, tree: _Tree) -> Asset:
    """How well the licence claim over a board naming only a footprint is backed.

    A licence string in a board file is a note an importer wrote, and the
    classes keep it apart from a file on disk. Such a board names no registry
    row, so no row's `licence.file` says which file its licence is read from;
    the licence-named file nearest the root of the tree its footprint is
    searched in stands in, unopened. A board whose `source.registry` names a
    row is graded by `_registry_licence_cell` instead, because a file named
    like a licence need not be the hardware's: both Olimex trees hold a
    LICENSE that is the GPL-3.0's text, for their software.
    """
    if not licence:
        return Asset(Evidence.ABSENT, "the board file records no `source.licence`")
    if tree.unsearchable:
        return Asset(
            Evidence.UNSEARCHABLE,
            f"{licence} recorded in the board file, uncorroborated: "
            f"{tree.unsearchable}",
        )

    on_disk = _licence_file(tree.on_disk)
    if on_disk:
        return Asset(Evidence.PRESENT, f"{licence}; {tree.root.as_posix()}/{on_disk}")
    indexed = _licence_file(tree.indexed)
    if indexed:
        return Asset(
            Evidence.INDEXED,
            f"{licence}; {indexed} — in the vendor's git tree, not fetched",
        )
    return Asset(
        Evidence.ABSENT,
        f"{licence} recorded in the board file, but {tree.root.as_posix()} holds "
        f"no licence file to back it",
    )


def _registry_licence_cell(
    licence: str | None, registered: board_sources.Source, tree: _Tree
) -> Asset:
    """How well a registry board's licence claim is backed, graded on the one
    file its registry row reads the licence from (`licence.file`) and on no
    other, in that row's own tree.

    That file need not hold the licence's text: a README states one, and the
    registry grades it `stated` where a licence text it opened is `opened`.
    The classes here say only whether the file is on this disk, so the
    detail carries the row's grade too, and a README never reads as a licence.

    A row naming no file reads `absent` whether or not its tree is fetched:
    there is nothing on any disk to look for, and the row's `cite` says what
    the licence was read from instead.
    """
    if not licence:
        return Asset(Evidence.ABSENT, "the board file records no `source.licence`")
    named = registered.licence.file
    graded = f"graded {registered.licence.evidence.label}"
    root = tree.root.as_posix()
    if not named:
        return Asset(
            Evidence.ABSENT,
            f"{licence} recorded in the board file, but the registry row "
            f"{registered.name} reads its licence from no file in {root}; "
            f"it cites, {graded}: {registered.licence.cite}",
        )
    if tree.unsearchable:
        return Asset(
            Evidence.UNSEARCHABLE,
            f"{licence} recorded in the board file, uncorroborated: the registry "
            f"row {registered.name} reads it from {named}, {graded}, and "
            f"{tree.unsearchable}",
        )
    if named in tree.on_disk:
        return Asset(Evidence.PRESENT, f"{licence}; {root}/{named}, {graded}")
    if named in tree.indexed:
        return Asset(
            Evidence.INDEXED,
            f"{licence}; {named}, {graded} — in the git tree of {root}, not fetched",
        )
    return Asset(
        Evidence.ABSENT,
        f"{licence} recorded in the board file, but {root} does not hold {named}, "
        f"the file the registry row {registered.name} reads its licence from, {graded}",
    )


def collect_assets(
    boards_dir: pathlib.Path = BOARDS_DIR,
    vendor_dir: pathlib.Path = VENDOR_DIR,
) -> list[BoardAssets]:
    """Per board: schematic, PCB, 3D model, pin definition, licence, each graded.

    Nothing here is typed by hand. The five cells are searched for on the
    filesystem every time the report runs, so a board added with no schematic
    reports no schematic without anyone editing anything — which is the point.
    The alternative is a five-column table of yes and no, which is precisely
    the hand-maintained inventory `CLAUDE.md` forbids by name on the grounds
    that it is the document that rots fastest.

    A board whose `source.registry` names a row is backed by the file that
    row reads its licence from, in that row's tree. A board naming only a
    `source.footprint` is backed by a licence file in `vendor_dir`, where
    that footprint is searched for. A board naming neither names no tree,
    and reads so.
    """
    if not boards_dir.is_dir():
        raise InventoryError(f"{boards_dir}: boards directory does not exist")
    paths = sorted(boards_dir.glob("*.json"))
    if not paths:
        raise InventoryError(f"{boards_dir}: contains no board definitions")

    tree = _vendor_tree(vendor_dir)
    registry_trees: dict[str, tuple[board_sources.Source, _Tree]] = {}

    reports = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryError(f"{path}: {exc}") from exc
        pads = data.get("pads")
        if not isinstance(pads, list):
            raise InventoryError(
                f"{path}: expected a `pads` list, got {type(pads).__name__}"
            )
        source = data.get("source") or {}
        footprint = source.get("footprint")
        registry = source.get("registry")
        if registry:
            if registry not in registry_trees:
                try:
                    registered = board_sources.source(registry)
                except board_sources.SourceError as exc:
                    raise InventoryError(f"{path}: source.registry: {exc}") from exc
                registry_trees[registry] = (registered, _source_tree(registered))
            registered, registry_tree = registry_trees[registry]
            licence = _registry_licence_cell(
                source.get("licence"), registered, registry_tree
            )
        elif footprint:
            licence = _licence_cell(source.get("licence"), tree)
        else:
            licence = _licence_cell(
                source.get("licence"),
                _Tree(
                    path,
                    (),
                    (),
                    "the board file records no `source.registry` and no "
                    "`source.footprint`, so it names no tree to read a licence file in",
                ),
            )
        reports.append(
            BoardAssets(
                name=data.get("board", path.stem),
                schematic=_vendor_cell(SCHEMATIC_FORMS, footprint, tree),
                pcb=_vendor_cell(PCB_FORMS, footprint, tree),
                model3d=_vendor_cell(MODEL_FORMS, footprint, tree),
                pins=_pin_cell(path, pads),
                licence=licence,
            )
        )
    return reports


#: The four layers OH-174 defines, in report order, each with when it holds.
TWIN_LAYERS = (
    ("geometry", "the board file's `source` names vendor CAD found on this disk"),
    ("model", "the 3D view draws a vendor or composed mesh, not the footprint"),
    ("pins", "every non-supply pad names a `chip_pin` or says specifically why not"),
    ("runs", "catalogue.catalogue() gives the board firmware evidence"),
)
#: The two ways a named CAD file is not found, which must not read alike.
NOT_FETCHED = "not fetched"
NAMES_NOTHING = "names nothing"
GEOMETRY_FALLBACKS = (
    (f"...:{NOT_FETCHED}", "it is in a vendor tree this checkout has not fetched"),
    (f"...:{NAMES_NOTHING}", "the tree is here and holds no such file"),
)
#: What a vendor footprint is, for `source.footprint`.
FOOTPRINT_SUFFIXES = (".kicad_mod",)
#: The `why_null` reasons that leave a pad unanswered; see `_pins_layer`.
UNANSWERED = frozenset({NOT_PUBLISHED, NO_PACKAGE_AT_ALL, NOT_TRACED, DISPUTED})
#: The two ways the 3D view falls back to the footprint, which must not read alike.
NOT_BUILT = "footprint:not built"
NO_SOURCE = "footprint:no source"
MODEL_FALLBACKS = (
    (NOT_BUILT, "a mesh is named for this board and not served on this disk"),
    (NO_SOURCE, "nothing here names a mesh for this board, so none can be built"),
)


class Layer(typing.NamedTuple):
    """One layer of one board: whether it holds, a short token, and what it rests on."""

    holds: bool
    summary: str
    detail: str


class Twin(typing.NamedTuple):
    """One board's four layers."""

    name: str
    geometry: Layer
    model: Layer
    pins: Layer
    runs: Layer

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name, _ in TWIN_LAYERS if not getattr(self, name).holds)


def supply_labels(source: pathlib.Path = SUPPLY_SOURCE) -> frozenset[str]:
    """`SUPPLY_LABELS` as `source` assigns it, read without importing a test.

    Refused unless it is assigned once at module level, as `frozenset({...})`
    of strings: a second binding is the one Python would use, and
    `frozenset("GND")` is a set of three letters.
    """
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise InventoryError(f"{source}: {exc}") from exc
    assigned = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "SUPPLY_LABELS"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if len(assigned) != 1:
        raise InventoryError(
            f"{source}: SUPPLY_LABELS is assigned {len(assigned)} times at module "
            f"level; one assignment is the only form read"
        )
    call = assigned[0].value
    if (
        not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or call.func.id != "frozenset"
        or len(call.args) != 1
        or call.keywords
        or not isinstance(call.args[0], ast.Set)
    ):
        raise InventoryError(
            f"{source}: SUPPLY_LABELS is not frozenset({{...}}) of a set literal"
        )
    try:
        labels = frozenset(ast.literal_eval(call.args[0]))
    except ValueError as exc:
        raise InventoryError(f"{source}: SUPPLY_LABELS: {exc}") from exc
    if not labels or not all(isinstance(label, str) for label in labels):
        raise InventoryError(f"{source}: SUPPLY_LABELS is not a non-empty set of strings")
    return labels


def is_supply(label: str, supplies: frozenset[str]) -> bool:
    """The predicate tests/rules/test_import_pindefs.py applies to SUPPLY_LABELS.

    A copy until OH-172 gives the rule one home;
    `test_inventory_calls_supply_exactly_the_pads_test_import_pindefs_does`
    holds the two together.
    """
    return label.split("/")[0].upper() in supplies or label.upper() in supplies


def _declared_footprints(tree: _Tree) -> dict[str, str]:
    """Declared footprint name -> the fetched `.kicad_mod` declaring it.

    A file's name is not always its footprint's: `XIAO-STM32C5-SMD.kicad_mod`
    declares `XIAO-XIAO STM32C5-SMD`.
    """
    declared: dict[str, str] = {}
    for relative in tree.on_disk:
        if pathlib.PurePosixPath(relative).suffix.lower() not in FOOTPRINT_SUFFIXES:
            continue
        try:
            footprint = kicad.read_footprint(tree.root / relative)
        except kicad.KicadError:
            # A footprint with no pads is nobody's board.
            continue
        declared.setdefault(footprint.name, relative)
    return declared


def _file_geometry(named: str) -> Layer:
    """A file tools/import_board.py reads, inside a registry source's tree."""
    path = pathlib.Path(named)
    if path.suffix.lower() not in READERS:
        return Layer(
            False,
            f"file:{NAMES_NOTHING}",
            f"{named} is not one of the formats tools/import_board.py reads: "
            f"{', '.join(sorted(READERS))}",
        )
    resolved = path.resolve()
    owner = next(
        (
            candidate
            for candidate in board_sources.sources()
            if resolved.is_relative_to(candidate.dest(pathlib.Path(".")).resolve())
        ),
        None,
    )
    if owner is None:
        return Layer(
            False,
            f"file:{NAMES_NOTHING}",
            f"{named} is inside no source in tools/board_sources.py",
        )
    if not owner.dest(pathlib.Path(".")).is_dir():
        return Layer(
            False,
            f"file:{NOT_FETCHED}",
            f"{named}: {owner.dest(pathlib.Path('.')).as_posix()} is not fetched here; "
            f"run: python tools/get_board_sources.py {owner.name}",
        )
    if not resolved.is_file():
        return Layer(False, f"file:{NAMES_NOTHING}", f"{named} is not a file here")
    return Layer(True, "file", path.as_posix())


def _footprint_geometry(footprint: str, tree: _Tree, declared_names: dict[str, str]) -> Layer:
    if tree.unsearchable:
        return Layer(False, f"footprint:{NOT_FETCHED}", tree.unsearchable)
    hit = _named_for(tree.on_disk, footprint, FOOTPRINT_SUFFIXES)
    if hit:
        return Layer(True, "footprint", f"{tree.root.as_posix()}/{hit}")
    declared = declared_names.get(footprint)
    if declared:
        return Layer(
            True, "footprint", f"{tree.root.as_posix()}/{declared}, declaring {footprint}"
        )
    hit = _named_for(tree.indexed, footprint, FOOTPRINT_SUFFIXES)
    if hit:
        return Layer(
            False,
            f"footprint:{NOT_FETCHED}",
            f"{hit} — in the vendor's git tree, not fetched",
        )
    return Layer(
        False,
        f"footprint:{NAMES_NOTHING}",
        f"no .kicad_mod under {tree.root.as_posix()} is named {footprint} or declares it",
    )


def _geometry_layer(source: dict, tree: _Tree, declared_names: dict[str, str]) -> Layer:
    """`source.file` first, because a path is exact; else `source.footprint`."""
    if source.get("file"):
        return _file_geometry(source["file"])
    if source.get("footprint"):
        return _footprint_geometry(source["footprint"], tree, declared_names)
    return Layer(
        False,
        "none",
        "the board file records no `source.file` or `source.footprint`",
    )


def _model_layer(name: str, index: dict | None, builders: dict[str, str]) -> Layer:
    """What `board3d-panel.js` would draw, from what the server would serve.

    The page reads `boards[name].file` out of the index and draws the mesh if
    that URL serves; `resolve_static` is what serves both.
    """
    entry = (index or {}).get(name) or {}
    url = entry.get("file")
    if url and resolve_static(url) is not None:
        kind = "composed" if entry.get("composed") else "vendor"
        return Layer(True, kind, url)
    if name not in builders:
        return Layer(
            False,
            NO_SOURCE,
            "neither MODELS nor COMPOSED in tools/import_3d_model.py names this board",
        )
    if index is None:
        unserved = f"{MODEL_INDEX} is not served"
    elif url:
        unserved = f"{url} is not served"
    else:
        unserved = f"{MODEL_INDEX} names no mesh for it"
    return Layer(False, NOT_BUILT, f"{unserved}; {builders[name]} builds it")


def _pins_layer(pads: list, supplies: frozenset[str]) -> Layer:
    """A non-supply pad answers if it names a `chip_pin` or its `why_null` is
    specific. No reason at all is not, and neither are four of
    tools/import_pindefs.py's: `NOT_PUBLISHED` and `NO_PACKAGE_AT_ALL` say no
    package covers the pad, `NOT_TRACED` adds that the vendor's CAD reached
    no pad of the chip either, and `DISPUTED` says the packages disagree.
    """
    signal = named = reasoned = 0
    unanswered = []
    for pad in pads:
        label = pad.get("label") or ""
        if is_supply(label, supplies):
            continue
        signal += 1
        why = pad.get("why_null")
        if pad.get("chip_pin") is not None:
            named += 1
        elif why and why not in UNANSWERED:
            reasoned += 1
        else:
            unanswered.append(label)
    detail = (
        f"{named} of {signal} non-supply pads name a `chip_pin` and {reasoned} "
        f"say why not; {len(pads) - signal} supply pads excluded"
    )
    if unanswered:
        detail += f"; unanswered on {', '.join(unanswered)}"
    summary = f"{named}+{reasoned}/{signal}" if reasoned else f"{named}/{signal}"
    return Layer(bool(signal) and not unanswered, summary, detail)


def _runs_layer(stem: str, placed: dict, refused: str | None) -> Layer:
    """The catalogue's own firmware evidence for this board.

    `catalogue.catalogue()` places every board or raises, and `api.runtime_for`
    asks it before running anything, so a refusal is every board's answer.
    """
    if refused is not None:
        return Layer(False, "refused", f"catalogue.catalogue() refuses: {refused}")
    board = placed.get(stem)
    if board is None:
        return Layer(False, "unlisted", f"catalogue.catalogue() lists no {stem!r}")
    if board.firmware_evidence is None:
        return Layer(
            False,
            f"{board.chip}:no",
            f"the catalogue gives {board.chip} on this board no firmware evidence",
        )
    return Layer(True, board.chip, board.firmware_evidence)


def collect_twins(
    boards_dir: pathlib.Path = BOARDS_DIR,
    vendor_dir: pathlib.Path = VENDOR_DIR,
) -> list[Twin]:
    """Per board, the four layers, each read from the code that owns it."""
    if not boards_dir.is_dir():
        raise InventoryError(f"{boards_dir}: boards directory does not exist")
    paths = sorted(boards_dir.glob("*.json"))
    if not paths:
        raise InventoryError(f"{boards_dir}: contains no board definitions")

    tree = _vendor_tree(vendor_dir)
    declared_names = _declared_footprints(tree)
    supplies = supply_labels()
    served = resolve_static(MODEL_INDEX)
    try:
        index = json.loads(served[0])["boards"] if served else None
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise InventoryError(f"{MODEL_INDEX}: {exc!r}") from exc
    builders = {
        board: "python tools/import_3d_model.py --all"
        for model in MODELS
        for board in model.boards
    }
    builders.update(
        (board, "python tools/compose_board_3d.py") for board, _, _ in COMPOSED
    )
    try:
        placed = {board.name: board for board in catalogue.catalogue(boards_dir)}
        refused = None
    except catalogue.CatalogueError as exc:
        placed, refused = {}, str(exc)

    twins = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryError(f"{path}: {exc}") from exc
        pads = data.get("pads")
        if not isinstance(pads, list):
            raise InventoryError(
                f"{path}: expected a `pads` list, got {type(pads).__name__}"
            )
        name = data.get("board", path.stem)
        twins.append(
            Twin(
                name=name,
                geometry=_geometry_layer(data.get("source") or {}, tree, declared_names),
                model=_model_layer(name, index, builders),
                pins=_pins_layer(pads, supplies),
                runs=_runs_layer(path.stem, placed, refused),
            )
        )
    return twins


def _head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


class _Inventory(typing.NamedTuple):
    tests: dict[str, int]
    mechanisms: list[tuple[str, str, bool, str | None]]
    files: dict[str, list[str]]
    ledgers: dict[str, collections.Counter]
    boards: list[Board]
    assets: list[BoardAssets]
    twins: list[Twin]


def _gather() -> _Inventory:
    """Collect every section once, so the two renderers cannot disagree."""
    return _Inventory(
        collect_tests(),
        collect_mechanisms(),
        collect_files(),
        collect_ledgers(),
        collect_boards(),
        collect_assets(),
        collect_twins(),
    )


def _armed(mechanisms: list[tuple[str, str, bool, str | None]]) -> int:
    return sum(1 for _, _, is_armed, _ in mechanisms if is_armed)


def _tests_by_size(tests: dict[str, int]) -> list[tuple[str, int]]:
    """Largest file first, then alphabetical — one ordering for both renderers."""
    return sorted(tests.items(), key=lambda kv: (-kv[1], kv[0]))


def _breakdown(counter: collections.Counter) -> str:
    return ", ".join(f"{count} {status}" for status, count in sorted(counter.items()))


def _boards_by_reach(boards: list[Board]) -> list[Board]:
    """Wired boards first, then alphabetical — one ordering for both renderers.

    Sorting by what the simulator can reach rather than by name puts the
    honest answer at the top of the list instead of at whatever position the
    alphabet happens to give it.
    """
    return sorted(boards, key=lambda b: (-b.wired, b.name))


def _assets_by_completeness(assets: list[BoardAssets]) -> list[BoardAssets]:
    """Most complete first, then alphabetical — one ordering for both renderers.

    The same choice `_boards_by_reach` makes, for the same reason: sorting by
    what is actually there puts whatever this repository has managed to
    substantiate at the top, rather than at whatever position the alphabet
    happens to give it.
    """
    return sorted(assets, key=lambda report: (len(report.missing()), report.name))


def _asset_tallies(assets: list[BoardAssets]) -> str:
    """Per cell, how many boards have anything at all — one string, both renderers."""
    return ", ".join(
        f"{cell} {sum(1 for report in assets if cell not in report.missing())}"
        for cell in ASSET_CELLS
    )


def _twins_by_completeness(twins: list[Twin]) -> list[Twin]:
    """Most complete first, then alphabetical — as `_assets_by_completeness`."""
    return sorted(twins, key=lambda twin: (len(twin.missing()), twin.name))


def _twin_heading(twins: list[Twin]) -> str:
    """The summary line. A fetch or build this checkout has not run is counted
    beside its layer, so a fresh clone's zeros do not read as facts about boards.
    """
    whole = sum(1 for twin in twins if not twin.missing())
    unfetched = sum(
        1 for twin in twins if twin.geometry.summary.endswith(f":{NOT_FETCHED}")
    )
    unbuilt = sum(1 for twin in twins if twin.model.summary == NOT_BUILT)
    tallies = []
    for name, _ in TWIN_LAYERS:
        held = f"{name} {sum(1 for twin in twins if getattr(twin, name).holds)}"
        if name == "geometry" and unfetched:
            held += f" ({unfetched} not fetched here)"
        if name == "model" and unbuilt:
            held += f" ({unbuilt} not built here)"
        tallies.append(held)
    return (
        f"{whole} of {len(twins)} boards hold all four; "
        f"by layer: {', '.join(tallies)}"
    )


def _asset_md(asset: Asset) -> str:
    """One markdown cell: the class, and the thing it rests on where there is one.

    A found file is named; a cell with nothing behind it shows the class
    alone, because the prose above the table already says where the search ran
    and repeating that sentence seventy-eight times would bury the rows that
    have something in them.
    """
    if asset.evidence in (Evidence.ABSENT, Evidence.UNSEARCHABLE):
        return f"`{asset.summary()}`"
    return f"`{asset.summary()}` {asset.detail}"


def _licence_md(asset: Asset) -> str:
    """The licence cell, which keeps an absent cell's reason.

    An absent schematic is the one search the prose describes. An absent
    licence is one of several -- the board file records none, the row's tree
    lacks the file it names, the row names no file -- and without its detail
    a row naming no file reads as if its file were missing.
    """
    if asset.evidence is Evidence.UNSEARCHABLE:
        return f"`{asset.summary()}`"
    return f"`{asset.summary()}` {asset.detail}"


def _board_provenance(board: Board) -> str:
    if board.vendor and board.licence:
        return f"{board.vendor}, {board.licence}"
    return "no recorded provenance"


def render_text() -> str:
    inv = _gather()
    armed = _armed(inv.mechanisms)
    lines = [f"OpenHardware inventory at {_head()}", ""]

    lines.append(f"TESTS — {sum(inv.tests.values())} across {len(inv.tests)} files")
    for path, count in _tests_by_size(inv.tests):
        lines.append(f"  {count:>4}  {path}")

    lines.append("")
    lines.append(f"MECHANISMS — {armed} armed, {len(inv.mechanisms) - armed} unarmed")
    for rule, tier, is_armed, checker in inv.mechanisms:
        lines.append(
            f"  {'ARMED  ' if is_armed else 'unarmed'}  {tier:<16}  {rule}  ->  {checker}"
        )

    lines.append("")
    lines.append(
        f"FILES tracked — {sum(len(p) for p in inv.files.values())}"
    )
    for area, paths in sorted(inv.files.items()):
        lines.append(f"  {len(paths):>4}  {area}")

    lines.append("")
    lines.append(f"LEDGERS — {len(inv.ledgers)}")
    for path, counter in inv.ledgers.items():
        lines.append(f"  {sum(counter.values()):>4}  {path}  ({_breakdown(counter)})")

    wired = [b for b in inv.boards if b.wired]
    lines.append("")
    lines.append(
        f"BOARDS — {len(inv.boards)} definitions; {len(wired)} wired to the "
        f"simulator, {len(inv.boards) - len(wired)} outline only"
    )
    # **"Outline only" is about the rcontrol pin index and not about the MCU
    # pin**, and the two have been separate counts since OH-160. Printed
    # rather than left for a reader to assume, because the number below is
    # 0/14 for a board whose every header pad now names a GPIO and follows a
    # register.
    lines.append(
        "         (the pin index a PICSimLab board defines; `chip_pin` is the "
        "other join — python tools/import_pindefs.py --all --summary)"
    )
    for board in _boards_by_reach(inv.boards):
        lines.append(
            f"  {board.wired:>3}/{board.pads:<3} pins  {board.name:<24}"
            f"  {_board_provenance(board)}"
            f"{'' if board.art else '  [no artwork]'}"
        )

    whole = [report for report in inv.assets if not report.missing()]
    lines.append("")
    lines.append(
        f"ASSETS — {len(whole)} of {len(inv.assets)} boards carry all five; "
        f"by cell: {_asset_tallies(inv.assets)}"
    )
    lines.append(
        f"  Vendor CAD is searched for under {VENDOR_DIR.as_posix()}/, where"
    )
    lines.append("  python tools/get_board_sources.py seeed-xiao puts it.")
    lines.append(
        "  schematic, pcb and model3d count only files named for the footprint in"
    )
    lines.append(
        "  that tree; CAD fetched anywhere else is not searched, and model3d is"
    )
    lines.append("  not what the 3D view draws.")
    lines += [
        "  licence: the board file's source.registry names a row of",
        "  tools/board_sources.py, the row names the file it read the licence",
        "  from, and the cell looks for that file in the row's own tree. That",
        "  file may state the licence rather than hold its text, so the cell's",
        "  detail, which --markdown prints, carries the row's grade of how it",
        "  was read: stated where the file is a README asserting the licence,",
        "  opened where the row opened the file and read the licence in it, a",
        "  licence's text or a sentence a board file carries. A board naming",
        "  only a footprint is backed by a licence-named file in the tree above,",
        "  which nothing opens. A licence cell is absent where the board file",
        "  records no licence, the tree holds no file to back it, or the",
        "  registry row names no file, citing where it read the licence instead.",
    ]
    lines.append("  Evidence, strongest first:")
    for evidence in Evidence:
        lines.append(f"    {evidence.label:<13} {evidence.gloss}")
    lines.append("")
    lines.append("  " + "".join(f"{cell:<15}" for cell in ASSET_CELLS) + "board")
    for report in _assets_by_completeness(inv.assets):
        cells = "".join(
            f"{getattr(report, cell).summary():<15}" for cell in ASSET_CELLS
        )
        lines.append(f"  {cells}{report.name}")

    widths = (25, 21, 9, 15)
    lines.append("")
    lines.append(f"TWINS — {_twin_heading(inv.twins)}")
    lines.append("  A layer holds when:")
    for name, gloss in TWIN_LAYERS:
        lines.append(f"    {name:<20} {gloss}")
    lines.append("  A named file is not found two ways, after `footprint:` or `file:`:")
    for token, gloss in GEOMETRY_FALLBACKS:
        lines.append(f"    {token:<20} {gloss}")
    lines.append("  The model layer falls back to the footprint two ways:")
    for token, gloss in MODEL_FALLBACKS:
        lines.append(f"    {token:<20} {gloss}")
    lines.append("")
    lines.append(
        "  "
        + "".join(f"{name:<{width}}" for (name, _), width in zip(TWIN_LAYERS, widths))
        + "board"
    )
    for twin in _twins_by_completeness(inv.twins):
        cells = "".join(
            f"{getattr(twin, name).summary:<{width}}"
            for (name, _), width in zip(TWIN_LAYERS, widths)
        )
        lines.append(f"  {cells}{twin.name}")

    return "\n".join(lines)


def render_markdown() -> str:
    inv = _gather()
    armed = _armed(inv.mechanisms)

    out = [
        "# OpenHardware inventory",
        "",
        f"Generated from `{_head()}` by `tools/inventory.py`. Every number here is "
        "computed from the repository; do not edit this by hand.",
        "",
        f"## Tests — {sum(inv.tests.values())}",
        "",
        "| file | tests |",
        "|---|---|",
    ]
    out += [f"| `{path}` | {count} |" for path, count in _tests_by_size(inv.tests)]

    out += [
        "",
        f"## Mechanisms — {armed} armed, {len(inv.mechanisms) - armed} unarmed",
        "",
        "| rule | tier | armed | checker |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {rule} | `{tier}` | {'yes' if is_armed else 'no'} | `{checker}` |"
        for rule, tier, is_armed, checker in inv.mechanisms
    ]

    out += [
        "",
        f"## Files tracked — {sum(len(p) for p in inv.files.values())}",
        "",
        "| area | count |",
        "|---|---|",
    ]
    out += [
        f"| `{area}` | {len(paths)} |"
        for area, paths in sorted(inv.files.items())
    ]

    out += [
        "",
        f"## Ledgers — {len(inv.ledgers)}",
        "",
        "| ledger | cells | breakdown |",
        "|---|---|---|",
    ]
    out += [
        f"| `{path}` | {sum(counter.values())} | {_breakdown(counter)} |"
        for path, counter in inv.ledgers.items()
    ]

    wired = [b for b in inv.boards if b.wired]
    out += [
        "",
        f"## Boards — {len(inv.boards)} definitions, {len(wired)} wired to the simulator",
        "",
        "A board is *wired* when its pads carry simulator pin indices. The rest "
        "draw to scale and deliberately refuse connections: a pad with a null "
        "pin would otherwise wire the circuit wrongly and report success.",
        "",
        "**That is the PICSimLab pin index and not the MCU pin.** Since OH-160 "
        "every board file also carries a `chip_pin` read out of the vendor's "
        "board-support package, and the boards whose chip has a module report a "
        "running program's pin levels through the same table — so an "
        "*outline only* row here is not a board that answers nothing. "
        "`python tools/import_pindefs.py --all --summary` counts that join.",
        "",
        "| board | pads | wired | artwork | provenance |",
        "|---|---|---|---|---|",
    ]
    out += [
        f"| `{board.name}` | {board.pads} | {board.wired} "
        f"| {'yes' if board.art else 'no'} | {_board_provenance(board)} |"
        for board in _boards_by_reach(inv.boards)
    ]

    whole = [report for report in inv.assets if not report.missing()]
    out += [
        "",
        f"## Assets — {len(whole)} of {len(inv.assets)} boards carry all five",
        "",
        f"By cell: {_asset_tallies(inv.assets)}. Vendor CAD is searched for under "
        f"`{VENDOR_DIR.as_posix()}/`, where `python tools/get_board_sources.py seeed-xiao` puts it; "
        "a cell reading `unsearchable` means that tree is absent from this "
        "checkout, which is a fact about the checkout and not about the vendor. "
        "`schematic`, `pcb` and `model3d` count only files named for the "
        "footprint in that tree; CAD fetched anywhere else is not searched, and "
        "`model3d` is not what the 3D view draws.",
        "",
        "`licence`: the board file's `source.registry` names a row of "
        "`tools/board_sources.py`, the row names the file it read the licence "
        "from, and the cell looks for that file in the row's own tree. That file "
        "may state the licence rather than hold its text, so the cell's detail "
        "carries the row's grade of how it was read: `graded stated` where the "
        "file is a README asserting the licence, `graded opened` where the row "
        "opened the file and read the licence in it, a licence's text or a "
        "sentence a board file carries. A board naming only a footprint is backed "
        "by a licence-named file in the tree above, which nothing opens. A licence "
        "cell is `absent` where the board file records no licence, the tree holds "
        "no file to back it, or the registry row names no file, citing where it "
        "read the licence instead; its detail says which.",
        "",
    ]
    out += [f"* `{evidence.label}` — {evidence.gloss}" for evidence in Evidence]
    out += [
        "",
        "| board | " + " | ".join(ASSET_CELLS) + " |",
        "|---" * (len(ASSET_CELLS) + 1) + "|",
    ]
    out += [
        f"| `{report.name}` | "
        + " | ".join(
            (_licence_md if cell == "licence" else _asset_md)(getattr(report, cell))
            for cell in ASSET_CELLS
        )
        + " |"
        for report in _assets_by_completeness(inv.assets)
    ]

    out += ["", f"## Twins — {_twin_heading(inv.twins)}", ""]
    out += [f"* `{name}` holds when {gloss}" for name, gloss in TWIN_LAYERS]
    out += [
        f"* `{token}` — {gloss}"
        for token, gloss in GEOMETRY_FALLBACKS + MODEL_FALLBACKS
    ]
    out += [
        "",
        "| board | " + " | ".join(name for name, _ in TWIN_LAYERS) + " |",
        "|---" * (len(TWIN_LAYERS) + 1) + "|",
    ]
    out += [
        f"| `{twin.name}` | "
        + " | ".join(
            f"`{getattr(twin, name).summary}` {getattr(twin, name).detail}"
            for name, _ in TWIN_LAYERS
        )
        + " |"
        for twin in _twins_by_completeness(inv.twins)
    ]

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--markdown", action="store_true", help="emit markdown instead of plain text"
    )
    args = parser.parse_args()
    try:
        print(render_markdown() if args.markdown else render_text())
    except InventoryError as exc:
        print(f"inventory: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
