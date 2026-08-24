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

Six collectors, one per thing worth counting:

* `collect_tests`   — parses each test file with `ast`
* `collect_mechanisms` — reads `rules/*.md` frontmatter
* `collect_files`   — asks git what this repository tracks
* `collect_ledgers` — parses every ledger under `docs/features/`
* `collect_boards`  — reads every board definition under `webui/boards/`
* `collect_assets`  — searches for the CAD behind each board, and grades it

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
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    # Unlike the four checkers, this tool imports its siblings. Running it as
    # `python tools/inventory.py` puts `tools/` on sys.path rather than the repo
    # root, so the package is not importable. Rather than force
    # `python -m tools.inventory` and break the `python tools/<name>.py`
    # convention CLAUDE.md documents for every other tool, put the repo root on
    # the path and retry. Both invocations then work.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules

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
    only field here that says whether a board *does* anything. A pad whose
    `pin` is null draws and refuses a wire — every XIAO file states exactly
    that in its own `assumption` field, and gives the reason: a guessed pin
    number would wire the circuit wrongly and report success.

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
        # `source` is absent on hand-written boards and present on every
        # imported one. Missing provenance is reported as missing rather than
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
    a finding about the vendor. `UNSEARCHABLE` means the search could not run
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


def _vendor_tree(vendor_dir: pathlib.Path) -> _Tree:
    """Everything the vendor tree holds, split by whether it was fetched.

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
            f"run: python tools/get_board_sources.py seeed-xiao",
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
            f"This should be the clone `python tools/get_board_sources.py seeed-xiao` "
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
    """How well the licence claim over a board's assets is backed.

    A licence string in a board file is a note an importer wrote. A licence
    file in the tree it came from is the licence. The classes keep those apart
    rather than letting the note stand in for the thing.
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
    """
    if not boards_dir.is_dir():
        raise InventoryError(f"{boards_dir}: boards directory does not exist")
    paths = sorted(boards_dir.glob("*.json"))
    if not paths:
        raise InventoryError(f"{boards_dir}: contains no board definitions")

    tree = _vendor_tree(vendor_dir)

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
        reports.append(
            BoardAssets(
                name=data.get("board", path.stem),
                schematic=_vendor_cell(SCHEMATIC_FORMS, footprint, tree),
                pcb=_vendor_cell(PCB_FORMS, footprint, tree),
                model3d=_vendor_cell(MODEL_FORMS, footprint, tree),
                pins=_pin_cell(path, pads),
                licence=_licence_cell(source.get("licence"), tree),
            )
        )
    return reports


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


def _gather() -> _Inventory:
    """Collect every section once, so the two renderers cannot disagree."""
    return _Inventory(
        collect_tests(),
        collect_mechanisms(),
        collect_files(),
        collect_ledgers(),
        collect_boards(),
        collect_assets(),
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
        "checkout, which is a fact about the checkout and not about the vendor.",
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
        + " | ".join(_asset_md(getattr(report, cell)) for cell in ASSET_CELLS)
        + " |"
        for report in _assets_by_completeness(inv.assets)
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
