#!/usr/bin/env python3
# OpenHardware - turn a vendor's CAD into a board description, or refuse.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Read one CAD file and emit the board JSON, whatever CAD the vendor writes.

This replaced `tools/import_kicad_board.py`, which read a `.kicad_mod` joined
to a `.kicad_sym` and nothing else. That worked because Seeed publishes KiCad
and Seeed was the only vendor in this repository. It was retired by OH-41 once
this tool reproduced its output exactly. The survey in `docs/research/board-sources/` says that does
not generalise: Adafruit and SparkFun publish EAGLE, Arduino publishes both,
ST publishes Altium and PDF, and several vendors publish a picture.

So the front half is generic: a reader per format behind one importer, the
same board JSON out. `tools/kicad.py` and `tools/eagle.py` are the readers and
neither knows this module exists.

## Refusing is a feature, not a gap

Every board description in `webui/boards/` ends its `derivation` with
**"Nothing here was measured off an image."** `webui/pinmap.py` records what
happens when that is not true: the Arduino Uno's pad centres had to be pulled
out of `board.svg` by hand, and the file still carries an `assumption` field
explaining which parts of the result are guesses.

An importer that quietly did that for every vendor without machine-readable
geometry would make that sentence a lie in twenty-six files at once. So a
format that has no coordinates in it is refused **by name**, saying what is
missing and what would have worked. `REFUSED` is that list, and it is longer
than `READERS` on purpose — refusing is the common case in this market.

The extension alone is not enough to decide. Cadence Allegro writes `.brd`
too, and the Raspberry Pi Pico design files ship one; `tools/eagle.py` refuses
it after looking inside rather than producing nonsense from a binary blob.

## What it does not do

**It does not write into `webui/boards/`.** The output goes to stdout, or to a
directory given with `--out`. It emits the JSON and not the SVG artwork the
`image.file` field names, so what it produces is a board *proposal*: landing
it needs artwork alongside, and the run says so on stderr rather than leaving
a description pointing at a file nobody made.

    python tools/import_board.py <board.brd> --select J1
    python tools/import_board.py <footprint.kicad_mod> --select <symbol root>

`--select` names the part of the file to read: an EAGLE board places many
elements and only one of them is the header, and a KiCad symbol library holds
many symbols and only one names this footprint's pins. Neither is guessed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import typing

try:
    from tools import eagle, kicad
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import eagle, kicad

#: Space around the outline so a pad on the very edge is not clipped by the
#: viewBox. The same 1.0 mm the retired `tools/import_kicad_board.py` used,
#: which is what let the two tools' output be compared without an offset --
#: the comparison that made retiring it possible.
MARGIN_MM = 1.0
#: Two pads are on the same header run when their shared coordinate agrees to
#: better than this. Nothing in CAD is fuzzy — the pads in a run share an
#: exact coordinate — so this only absorbs binary floating point.
SAME_LINE_MM = 0.001


class BoardImportError(Exception):
    """The file cannot become a board description, and here is why."""


class PadSpec(typing.NamedTuple):
    """One pad, normalised: millimetres from the top-left, Y increasing down.

    Both readers deliver this, so nothing above here knows which CAD it came
    from. EAGLE puts Y upward from the bottom-left and KiCad puts it downward
    from the footprint origin; each reader resolves its own convention, once,
    rather than leaving a flag for the caller to get wrong.
    """

    label: str
    number: str
    x_mm: float
    y_mm: float
    group: str


class Geometry(typing.NamedTuple):
    """What any reader must produce: a named board, its size, and its pads."""

    name: str
    width_mm: float
    height_mm: float
    pads: tuple[PadSpec, ...]
    derivation: str
    #: What the CAD calls itself, when that is not what the file is called.
    #: Almost always None. It is not None for exactly one file in this
    #: project's vendor tree, and `build_board` records the path rather than
    #: the name because of it.
    declared_name: str | None


def _runs(points: list[float]) -> list[float]:
    """The distinct coordinate lines in `points`, in order."""
    lines: list[float] = []
    for value in sorted(points):
        if not lines or abs(value - lines[-1]) > SAME_LINE_MM:
            lines.append(value)
    return lines


def _grouped(pads: list[tuple[str, str, float, float]]) -> tuple[PadSpec, ...]:
    """Name each pad's header run from the run it is actually in.

    A header is a line of pads sharing one coordinate, and which coordinate
    they share is what makes the run horizontal or vertical. That is read off
    the pads rather than assumed: the retired `tools/import_kicad_board.py`
    decided with `header-top if y < 0 else header-bottom`, which is true of a
    KiCad footprint centred on its origin and false of an EAGLE board whose
    origin is a corner. Reading the runs works for both.

    Two runs get the names the existing board files use. More than two get
    numbered, because `header-top` for one of five rows would be a guess
    dressed as a label.
    """
    columns = _runs([x for _, _, x, _ in pads])
    rows = _runs([y for _, _, _, y in pads])
    vertical = len(columns) <= len(rows)
    lines = columns if vertical else rows

    if len(lines) == 2:
        names = ["header-left", "header-right"] if vertical else ["header-top", "header-bottom"]
    else:
        stem = "header-column" if vertical else "header-row"
        names = [f"{stem}-{index + 1}" for index in range(len(lines))]

    specs = []
    for label, number, x, y in pads:
        value = x if vertical else y
        index = min(range(len(lines)), key=lambda i: abs(lines[i] - value))
        specs.append(PadSpec(label, number, round(x, 4), round(y, 4), names[index]))
    return tuple(sorted(specs, key=lambda pad: (pad.y_mm, pad.x_mm)))


def _from_eagle(
    path: pathlib.Path, select: tuple[str, ...], symbols: pathlib.Path | None
) -> Geometry:
    """Read an EAGLE board, taking the header pads off the placed elements named.

    `select` names them and is required when more than one element carries
    through-hole pads, which is the usual case: the board this reader was
    written against places 28 header pads on `J1`, four USB shield tabs on
    `J2` and two jumper pads on `MEAS`. Picking the biggest would be right
    there and wrong on a board with a DIP socket, so it asks.

    **Several, because a board's header is not always one element.** This took
    one name until 2026-08-27, when the Arduino Uno turned out to break every
    pad it has across four: `IOH` (1X10) and `IOL` (1X08) along the top edge,
    `POWER` (1X08) and `AD` (1X06) along the bottom. 10 + 8 + 8 + 6 is the 32
    pads that board has. A single-element reader could describe a quarter of an
    Uno, and there is no correct quarter to pick.

    Order does not matter and duplicates are refused rather than silently
    deduplicated: naming an element twice means somebody believes it holds two
    different things, and quietly agreeing with half of that is worse than
    saying so.
    """
    if symbols is not None:
        raise BoardImportError(
            f"{path}: --symbols is a KiCad option. An EAGLE board carries its "
            f"own net names in <signals>, so there is no second file to join."
        )
    board = eagle.read_board(path)
    candidates = [
        element for element in board.elements if element.pads_of("thru_hole")
    ]
    if not candidates:
        raise BoardImportError(
            f"{path}: places {len(board.elements)} elements and not one of them "
            f"has a through-hole pad, so there is no header to wire to."
        )
    if not select:
        if len(candidates) > 1:
            listing = ", ".join(
                f"{element.name} ({len(element.pads_of('thru_hole'))} pads, "
                f"{element.package})"
                for element in candidates
            )
            raise BoardImportError(
                f"{path}: more than one element has through-hole pads, so which "
                f"one is the header is not something to guess. Choose with "
                f"--select: {listing}"
            )
        chosen = [candidates[0]]
    else:
        repeated = sorted({name for name in select if select.count(name) > 1})
        if repeated:
            raise BoardImportError(
                f"{path}: --select names {', '.join(repeated)} more than once. "
                f"An element is placed once and its pads are read once."
            )
        chosen = []
        for name in select:
            element = board.element(name)
            if not element.pads_of("thru_hole"):
                raise BoardImportError(
                    f"{path}: element {name!r} is a {element.package}, which has "
                    f"no through-hole pads"
                )
            chosen.append(element)

    min_x, min_y, max_x, max_y = board.extent_mm()
    pads = [
        (
            # A pad with no signal keeps its number. Naming it after a
            # neighbour, or leaving it blank, would both read as knowledge.
            pad.net if pad.net else pad.number,
            pad.number,
            pad.x_mm - min_x + MARGIN_MM,
            # EAGLE's Y runs upward from the bottom-left. This subtraction is
            # the only place the axis is flipped, and everything downstream is
            # Y-down like the SVG it becomes.
            max_y - pad.y_mm + MARGIN_MM,
        )
        for element in chosen
        for pad in element.pads_of("thru_hole")
    ]
    width = max_x - min_x + 2 * MARGIN_MM
    height = max_y - min_y + 2 * MARGIN_MM
    named = ", ".join(f"{e.name} ({e.package})" for e in chosen)
    return Geometry(
        name=path.stem,
        width_mm=width,
        height_mm=height,
        pads=_grouped(pads),
        derivation=(
            f"Generated by tools/import_board.py from the vendor's own EAGLE "
            f"{board.version} board file, "
            f"{'element' if len(chosen) == 1 else 'elements'} {named}. Pad "
            f"centres are the coordinates the file states, in millimetres, with "
            f"EAGLE's upward Y axis flipped once against a "
            f"{max_x - min_x:.2f} x {max_y - min_y:.2f} mm outline taken from "
            f"layer {eagle.DIMENSION_LAYER} (Dimension), plus a {MARGIN_MM} mm "
            f"margin. Pad names are the net each pad is on, from <signals>. "
            f"Nothing here was measured off an image."
        ),
        declared_name=None,
    )


def _from_kicad(
    path: pathlib.Path, select: tuple[str, ...], symbols: pathlib.Path | None
) -> Geometry:
    """Read a KiCad footprint, joined to a symbol library for the pin names.

    A footprint's pad "1" is a position, not a signal; the name lives in a
    `.kicad_sym` keyed by the same number. When `--symbols` is not given the
    library is looked for beside the footprint, which is how every vendor tree
    seen so far is laid out — and if there is not exactly one, that is said
    rather than guessed at.

    **`select` is a symbol root here and there is exactly one**, where EAGLE's
    is a list of placed elements. More than one is refused rather than having
    the first quietly win: a footprint is a single part, so a caller passing two
    roots has confused this file with a board.
    """
    if len(select) > 1:
        raise BoardImportError(
            f"{path}: --select given {len(select)} times, but a KiCad footprint "
            f"is one part and takes one symbol root. Several is an EAGLE board's "
            f"answer, where each header is a separately placed element."
        )
    footprint = kicad.read_footprint(path)
    library = symbols if symbols is not None else _symbol_library(path)
    root = select[0] if select else footprint.name
    try:
        names = kicad.read_symbol_pins(library, root)
    except kicad.KicadError as exc:
        # kicad's own message already names the library and lists what is
        # in it; repeating that here would print the path three times.
        raise BoardImportError(f"{path}: {exc} Name one with --select.") from exc

    pads = footprint.pads_of("thru_hole") or footprint.pads_of("smd")
    if not pads:
        raise BoardImportError(f"{path}: footprint has no through-hole or SMD pads")

    min_x, min_y, max_x, max_y = footprint.extent_mm()
    entries = [
        (
            names.get(pad.number, pad.number),
            pad.number,
            pad.x_mm - min_x + MARGIN_MM,
            # KiCad footprints already run Y downward, so there is nothing to
            # flip here. That asymmetry with EAGLE is the reason each reader
            # normalises rather than the caller.
            pad.y_mm - min_y + MARGIN_MM,
        )
        for pad in pads
    ]
    unnamed = sorted(number for _, number, _, _ in entries if number not in names)
    return Geometry(
        name=path.stem,
        width_mm=max_x - min_x + 2 * MARGIN_MM,
        height_mm=max_y - min_y + 2 * MARGIN_MM,
        pads=_grouped(entries),
        derivation=(
            f"Generated by tools/import_board.py from the vendor's own KiCad "
            f"footprint. Pad centres are exact millimetres from a "
            f"{max_x - min_x:.2f} x {max_y - min_y:.2f} mm extent including a "
            f"{MARGIN_MM} mm margin. Pin names joined from {library.name} on pad "
            f"number{'' if not unnamed else f'; {len(unnamed)} pad(s) had no entry and kept their number'}. "
            f"Nothing here was measured off an image."
        ),
        declared_name=footprint.name if footprint.name != path.stem else None,
    )


def _symbol_library(footprint: pathlib.Path) -> pathlib.Path:
    """The one `.kicad_sym` beside a footprint, or an error naming what is there."""
    found = sorted(footprint.parent.glob("*.kicad_sym"))
    if len(found) == 1:
        return found[0]
    raise BoardImportError(
        f"{footprint}: needs a symbol library for the pin names, and "
        f"{footprint.parent} holds {len(found)} of them"
        f"{': ' + ', '.join(p.name for p in found) if found else ''}. "
        f"Name one with --symbols."
    )


#: Suffix to reader. Short on purpose: these are the formats a machine can
#: take pad coordinates out of, and there are two.
READERS = {
    ".brd": _from_eagle,
    ".kicad_mod": _from_kicad,
}

#: Suffix to the reason it is refused. Longer than `READERS`, which is the
#: honest shape of this market rather than an admission of missing work.
#: Every entry names what the format *is*, so the message tells a reader
#: whether to go looking for another file or to stop.
REFUSED = {
    ".pdf": "a rendering of a schematic, not geometry: it has no pad coordinates",
    ".dsn": "OrCAD Capture, a proprietary binary; the Raspberry Pi Pico ships one",
    ".schdoc": "Altium schematic, a proprietary binary",
    ".pcbdoc": "Altium layout, a proprietary binary",
    ".sch": "an EAGLE or Altium schematic: it carries nets but no board geometry, "
    "so pads have no position",
    ".lbr": "an EAGLE library: it has packages, but nothing places them on a board "
    "and there are no nets to name the pads",
    ".step": "3D solid geometry, with no pad numbering and no nets",
    ".stp": "3D solid geometry, with no pad numbering and no nets",
    ".stl": "a 3D mesh: no pads, no nets, not even surfaces that mean anything",
    ".wrl": "3D geometry for rendering, with no pad numbering and no nets",
    ".png": "a picture of a board, which has pixels where it needs coordinates",
    ".jpg": "a picture of a board, which has pixels where it needs coordinates",
    ".jpeg": "a picture of a board, which has pixels where it needs coordinates",
    ".webp": "a picture of a board, which has pixels where it needs coordinates",
    ".svg": "a drawing of a board: text, but shapes rather than named pads, and "
    "the scale is whatever the artwork chose",
}

#: What `REFUSED` says after the reason, once. `webui/pinmap.py` is the
#: evidence that the alternative was tried and cost a person an afternoon.
_NOT_MEASURED = (
    "Pad centres will not be measured off it. webui/pinmap.py records that the "
    "Arduino Uno's had to be done that way by hand, and every board file in "
    "this repository carries a derivation ending 'Nothing here was measured "
    "off an image.' What is needed instead is a file with coordinates in it: "
    "EAGLE .brd or KiCad .kicad_mod. tools/board_sources.py records which "
    "vendors publish one."
)


def read_geometry(
    path: pathlib.Path,
    select: tuple[str, ...] = (),
    symbols: pathlib.Path | None = None,
) -> Geometry:
    """Read any supported CAD file, or refuse it saying what is missing.

    `select` is a tuple because EAGLE needs several -- see `_from_eagle`. It
    stays one parameter rather than two because both readers are answering the
    same question, "which part of this file is the header"; KiCad simply has
    one answer, and `_from_kicad` says so rather than quietly using the first.
    """
    # **A bare string is refused rather than iterated.** `select` took one name
    # until 2026-08-27; a caller that still passes `"J1"` would otherwise be
    # read character by character and fail with "no element called 'J'", which
    # names a element nobody wrote and sends the reader to the wrong file. This
    # is the mistake this repository's own tests made the hour the signature
    # changed, which is the whole argument for the check.
    if isinstance(select, str):
        raise BoardImportError(
            f"select must be a tuple of element names, not the string "
            f"{select!r}. A board's pads can span several placed elements, so "
            f"pass ({select!r},) for one."
        )
    if not path.is_file():
        raise BoardImportError(f"{path}: no such file")

    suffix = path.suffix.lower()
    reader = READERS.get(suffix)
    if reader is None:
        reason = REFUSED.get(suffix)
        if reason is None:
            raise BoardImportError(
                f"{path}: nothing here reads {suffix or 'a file with no suffix'}. "
                f"Readable: {', '.join(sorted(READERS))}."
            )
        raise BoardImportError(f"{path}: {suffix} is {reason}. {_NOT_MEASURED}")

    try:
        return reader(path, select, symbols)
    except (eagle.EagleError, kicad.KicadError) as exc:
        # Both parsers raise their own type. Re-raised as one so a caller
        # catches once, with the parser's message kept whole.
        raise BoardImportError(str(exc)) from exc


def build_board(
    geometry: Geometry,
    path: pathlib.Path,
    source: dict[str, str],
    px_per_mm: float = kicad.DEFAULT_PX_PER_MM,
) -> dict:
    """The board JSON, in the schema `webui/boards/*.json` already uses."""
    scale = px_per_mm
    board = {
        "board": geometry.name,
        "image": {
            "width": round(geometry.width_mm * scale),
            "height": round(geometry.height_mm * scale),
            "file": f"webui/boards/{geometry.name}.svg",
        },
        "derivation": f"{geometry.derivation} Scaled at {scale} px/mm.",
        "assumption": (
            "Every `pin` is null. That field is the simulator's pin index, defined "
            "by a PICSimLab board implementation, and none exists for this board "
            "yet. A pad with pin null draws and refuses a wire, which is correct; "
            "a guessed number would wire the circuit wrongly and report success."
        ),
        "source": dict(source, file=path.as_posix()),
        "pads": [
            {
                "label": pad.label,
                "pin": None,
                "x": round(pad.x_mm * scale, 1),
                "y": round(pad.y_mm * scale, 1),
                "group": pad.group,
                "pad": pad.number,
            }
            for pad in geometry.pads
        ],
    }
    if geometry.declared_name:
        # The one place a CAD file disagrees with itself, recorded rather than
        # papered over. `XIAO-STM32C5-SMD.kicad_mod` declares
        # `(footprint "XIAO-XIAO STM32C5-SMD")`, and it is the only one of the
        # 37 in that library that does. `source.file` above is the fix that
        # matters: an asset search keyed on a declared name finds nothing,
        # while a path is always right.
        board["source"]["declared_name"] = geometry.declared_name
    return board


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=pathlib.Path, help="the vendor's CAD file")
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="NAME",
        help="EAGLE: which placed element carries the header. Repeat it for a "
        "board whose pads are split across several, as the Arduino Uno's are. "
        "KiCad: the symbol root to take pin names from, once",
    )
    parser.add_argument(
        "--symbols", type=pathlib.Path, help="KiCad symbol library (.kicad_sym)"
    )
    parser.add_argument("--vendor", default="", help="recorded in source.vendor")
    parser.add_argument("--licence", default="", help="recorded in source.licence")
    parser.add_argument(
        "--scale", type=float, default=kicad.DEFAULT_PX_PER_MM, help="pixels per mm"
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        help="directory to write <board>.json into; prints to stdout without it",
    )
    args = parser.parse_args()

    try:
        geometry = read_geometry(args.file, tuple(args.select), args.symbols)
    except BoardImportError as exc:
        print(f"import_board: {exc}", file=sys.stderr)
        return 2

    source = {"vendor": args.vendor, "licence": args.licence}
    board = build_board(geometry, args.file, source, args.scale)
    text = json.dumps(board, indent=2) + "\n"

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        destination = args.out / f"{geometry.name}.json"
        destination.write_text(text, encoding="utf-8")
        print(f"{destination}  ({len(board['pads'])} pads)")
    else:
        print(text, end="")

    print(
        f"note: {board['image']['file']} was NOT generated. This is a board "
        f"proposal, not a landed board — it needs artwork at that path before "
        f"anything can draw it.",
        file=sys.stderr,
    )
    if geometry.declared_name:
        print(
            f"note: the CAD declares itself {geometry.declared_name!r} while the "
            f"file is called {geometry.name!r}. source.file records the path, so "
            f"an asset search does not depend on which one is right.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
