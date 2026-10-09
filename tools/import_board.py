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
`image.file` field names, and nothing reads that field -- `webui/pinmap.py`
reads the image's width and height -- so the run says on stderr that the
file was not made, rather than leaving the name looking like a file.

    python tools/import_board.py <board.brd> --select J1
    python tools/import_board.py <board.kicad_pcb> --select J3 --select J4
    python tools/import_board.py <footprint.kicad_mod> --select <symbol root>

`--select` names the part of the file to read: a board places many elements
or footprints and only some of them are the header, and a KiCad symbol
library holds many symbols and only one names this footprint's pins. None of
it is guessed.
"""

from __future__ import annotations

import argparse
import json
import math
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


#: For an EAGLE board, each selected element's device as the vendor's
#: schematic states it: element name to `(package, pads)`, where `pads`
#: holds, per pin, the pads that pin's `<connect>` names. A castellated
#: header's pin is a hole and its half-hole at the edge, `pad="1 1C"`.
Connects = typing.Mapping[str, tuple[str, tuple[tuple[str, ...], ...]]]


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


#: The group of a pad on the module's UNDERSIDE (OH-216), in place of a
#: header run's name: such a pad is on no header, and the page carves its pin
#: out of the metal under the board rather than over it. A group because the
#: group is what reaches the page (`webui/pinmap.py` carries it to
#: `webui/api.py`'s `pad_view`), and because it is what was false: the
#: retired importer tagged these pads `header-top` by the sign of their y.
UNDERSIDE = "underside"


def _land(pad: kicad.Pad) -> tuple[float, float, float, float]:
    """A pad's copper as `(min_x, min_y, max_x, max_y)`, turned by its own
    angle, in the frame its centre is in. Exact for the quarter turns every
    footprint here uses, a bounding box for any other."""
    turn = math.radians(pad.rotation_deg)
    cos, sin = abs(math.cos(turn)), abs(math.sin(turn))
    half_w = (pad.width_mm * cos + pad.height_mm * sin) / 2
    half_h = (pad.width_mm * sin + pad.height_mm * cos) / 2
    return pad.x_mm - half_w, pad.y_mm - half_h, pad.x_mm + half_w, pad.y_mm + half_h


def _under_the_module(
    path: pathlib.Path, footprint: kicad.Footprint, module: kicad.Board | None,
    module_path: pathlib.Path | None,
) -> set[str]:
    """The numbers of a module footprint's pads that meet the module's
    UNDERSIDE, from what the vendor's files state (OH-216).

    **A footprint's layers cannot say it.** It is the HOST's land pattern:
    every land of a Seeed XIAO SMD footprint is `F.Cu`, the castellations'
    and the underside test points' alike, because both are soldered to the
    host's top. What the footprint does state is where the module sits --
    its `F.Fab` outline, the module's own 17.8 x 21 mm -- and a pin whose
    every land lies wholly inside that outline is covered by the module,
    so it can only meet the module's underside. A castellation's land
    reaches past the outline to the half-hole on its edge.

    **The converse is not true**, and that is what `module` is for: an
    underside test point near the edge has a land reaching past the outline
    too -- the nRF54L15's two NFC pads do. The module's own board file
    (Seeed's `.kicad_pcb`) says which copper is the module's: a land over a
    plated-through pad is a castellation, and one over copper on `B.Cu`
    alone, with no plated-through pad, meets the underside. It is placed
    over the module by the turn that lands every pad the outline found on
    back-side copper; a footprint with no such pad gives it nothing to be
    placed by, and then the module is not read.

    Where the two disagree -- a pin the outline puts under the module that
    no back-side copper answers under any turn -- this refuses, naming them.
    """
    fab = [seg for seg in footprint.segments if seg.layer == "F.Fab"]
    if not fab:
        if module is not None:
            raise BoardImportError(
                f"{path}: draws no F.Fab outline, so where the module sits is "
                f"not stated and {module_path} cannot be placed under it"
            )
        return set()
    xs = [v for seg in fab for v in (seg.x1_mm, seg.x2_mm)]
    ys = [v for seg in fab for v in (seg.y1_mm, seg.y2_mm)]
    outline = (min(xs), min(ys), max(xs), max(ys))
    lands: dict[str, list[tuple[float, float, float, float]]] = {}
    for pad in footprint.pads:
        lands.setdefault(pad.number, []).append(_land(pad))
    inside = {
        number for number, boxes in lands.items()
        if all(outline[0] < x0 and outline[1] < y0 and x1 < outline[2] and y1 < outline[3]
               for x0, y0, x1, y1 in boxes)
    }
    if module is None or not inside:
        return inside

    centre = ((outline[0] + outline[2]) / 2, (outline[1] + outline[3]) / 2)
    bx0, by0, bx1, by1 = module.extent_mm()
    middle = ((bx0 + bx1) / 2, (by0 + by1) / 2)
    copper = [(pad, *kicad.pad_on_board(placed, pad))
              for placed in module.placements for pad in placed.pads
              if pad.front or pad.back]

    def over(boxes, quarter: int) -> list[tuple[kicad.Pad, float]]:
        """The module pads whose centres lie in these lands, each with its
        distance from the land's centre, the footprint turned `quarter`
        quarters about its outline's centre onto the board's."""
        cos, sin = (1, 0, -1, 0)[quarter], (0, 1, 0, -1)[quarter]
        found = []
        for x0, y0, x1, y1 in boxes:
            dx, dy = (x0 + x1) / 2 - centre[0], (y0 + y1) / 2 - centre[1]
            at = (middle[0] + dx * cos - dy * sin, middle[1] + dx * sin + dy * cos)
            # A quarter turn swaps which side of the land runs along x.
            half_x, half_y = (x1 - x0) / 2, (y1 - y0) / 2
            if quarter % 2:
                half_x, half_y = half_y, half_x
            found += [(pad, math.hypot(px - at[0], py - at[1])) for pad, px, py in copper
                      if abs(px - at[0]) <= half_x and abs(py - at[1]) <= half_y]
        return found

    def back_only(found: list[tuple[kicad.Pad, float]]) -> list[float]:
        """How far each back-side-only pad in `found` is from its land."""
        return [gap for pad, gap in found if pad.back and not pad.front]

    def edge_under(quarter: int) -> frozenset[str]:
        """The pins reaching the outline that meet back-side copper and no
        plated-through pad, the module turned `quarter` quarters."""
        found = {number: over(boxes, quarter) for number, boxes in lands.items()
                 if number not in inside}
        return frozenset(number for number, pads in found.items()
                         if back_only(pads) and not any(p.front and p.back for p, _ in pads))

    # **Not every pin under the module is answered, and need not be.** The
    # outline is the statement for those; the module is read for the edge.
    # Measured: the C5's battery lands sit 0.77 mm off its battery pads, and
    # its pad 25 stands where the module has no pad at all. So the turn is
    # the one answering the most of them, and of turns answering as many --
    # the nRF54LM20A DIP's test points are a grid a half turn lays onto
    # itself -- the one standing its lands nearest the copper answering them.
    answered = {}
    for quarter in range(4):
        gaps = [min(gap) for gap in (back_only(over(lands[number], quarter))
                                     for number in inside) if gap]
        answered[quarter] = (len(gaps), -round(sum(gaps), 3))
    best = max(answered.values())
    readings = {edge_under(quarter) for quarter, score in answered.items() if score == best}
    if best[0] == 0 or len(readings) != 1:
        raise BoardImportError(
            f"{path}: the pins {sorted(inside, key=_number_order)} lie wholly "
            f"inside its F.Fab outline, so under the module, and {module_path} "
            f"answers { {q * 90: n for q, (n, _) in answered.items()} } of them "
            f"with back-side copper turned 0/90/180/270 degrees. The turn "
            f"answering most, nearest, is what places the module; "
            + ("none answers any." if best[0] == 0 else
               f"the turns tied at {best} disagree about the pins at the "
               f"edge: {[sorted(r, key=_number_order) for r in readings]}.")
        )
    (edge,) = readings
    return inside | edge


def _number_order(number: str) -> tuple[int, str]:
    """Pad numbers in the order a person counts them: 2 before 10."""
    return (int(number), "") if number.isdigit() else (1 << 30, number)


def _from_eagle(
    path: pathlib.Path,
    select: tuple[str, ...],
    symbols: pathlib.Path | None,
    connects: Connects | None,
    module: pathlib.Path | None,
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
    if module is not None:
        raise BoardImportError(
            f"{path}: --module places a module's own board under a module "
            f"FOOTPRINT; an EAGLE board is the board itself."
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

    # One pin is one pad. Which pads are one pin is the schematic's
    # statement, never inferred from pad names or nets: two GND pins on one
    # header are two pins.
    first: dict[str, set[str]] = {}
    for element in chosen if connects is not None else ():
        if element.name not in connects:
            raise BoardImportError(
                f"{path}: the schematic states no device for {element.name}"
            )
        package, pins = connects[element.name]
        if package != element.package:
            raise BoardImportError(
                f"{path}: {element.name} is a {element.package} on the board and "
                f"a {package} in the schematic; the two files disagree about "
                f"which footprint it is"
            )
        listed = [pad for pads in pins for pad in pads]
        numbers = [pad.number for pad in element.pads]
        unsure = sorted({number for number in numbers if listed.count(number) != 1}
                        | set(listed) - set(numbers))
        if unsure:
            raise BoardImportError(
                f"{path}: {element.name}'s pads {unsure} are not each in exactly "
                f"one of the schematic's connects {[' '.join(p) for p in pins]}"
            )
        # One pin is on one net. A connect whose pads the board puts on two
        # would keep the first pad's net and drop the other's without a word.
        nets = {pad.number: pad.net or "no net" for pad in element.pads}
        for pads in pins:
            if len({nets[pad] for pad in pads}) > 1:
                where = ", ".join(f"{pad} on {nets[pad]}" for pad in pads)
                raise BoardImportError(
                    f"{path}: {element.name}'s connect '{' '.join(pads)}' makes "
                    f"one pin of pads on different nets: {where}"
                )
        first[element.name] = {pads[0] for pads in pins}
    kept = [
        (element, pad)
        for element in chosen
        for pad in element.pads_of("thru_hole")
        if element.name not in first or pad.number in first[element.name]
    ]
    merged = sum(len(element.pads_of("thru_hole")) for element in chosen) - len(kept)

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
        for _, pad in kept
    ]
    width = max_x - min_x + 2 * MARGIN_MM
    height = max_y - min_y + 2 * MARGIN_MM
    named = ", ".join(f"{e.name} ({e.package})" for e in chosen)
    pins = (
        f"Where the schematic's device connects one pin to several pads, they "
        f"are one pad here, at the pad its <connect> names first; {merged} "
        f"pads were merged so. " if merged else ""
    )
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
            f"{pins}Nothing here was measured off an image."
        ),
        declared_name=None,
    )


def _from_kicad(
    path: pathlib.Path,
    select: tuple[str, ...],
    symbols: pathlib.Path | None,
    connects: Connects | None,
    module: pathlib.Path | None,
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

    `module` is the module's own board file, where the vendor publishes one:
    it says which pads at the outline's edge meet the module's underside
    (`_under_the_module`), which the footprint alone cannot.
    """
    if connects is not None:
        raise BoardImportError(
            f"{path}: connects are an EAGLE board's, read from its schematic; a "
            f"KiCad footprint's pins are joined through --symbols."
        )
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
    # A lone footprint's pads are on no net, so the number is the only thing
    # joining a pad to its pin; without one the pad would be labelled "".
    for pad in pads:
        if not pad.number:
            raise BoardImportError(
                f"{path}: footprint {footprint.name} has a {pad.kind} pad at "
                f"({pad.x_mm:g}, {pad.y_mm:g}) in its own millimetres that the "
                f"file gives neither a number nor a net, so it has no name to "
                f"carry and none is invented for it."
            )

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
    try:
        board = kicad.read_board(module) if module is not None else None
    except kicad.KicadError as exc:
        raise BoardImportError(f"{path}: --module {module}: {exc}") from exc
    under = _under_the_module(path, footprint, board, module)
    # Header runs are read off the pads that are on one; an underside pad is
    # on none, and counted among them it would add runs that are not there.
    grouped = _grouped([entry for entry in entries if entry[1] not in under])
    underside = tuple(PadSpec(label, number, round(x, 4), round(y, 4), UNDERSIDE)
                      for label, number, x, y in entries if number in under)
    module_rule = (
        f", or, reaching it, over copper that {module.name}, the module's own "
        f"board file, puts on B.Cu alone and over no plated-through pad"
        if module is not None else ""
    )
    return Geometry(
        name=path.stem,
        width_mm=max_x - min_x + 2 * MARGIN_MM,
        height_mm=max_y - min_y + 2 * MARGIN_MM,
        pads=tuple(sorted(grouped + underside, key=lambda pad: (pad.y_mm, pad.x_mm))),
        derivation=(
            f"Generated by tools/import_board.py from the vendor's own KiCad "
            f"footprint. Pad centres are exact millimetres from a "
            f"{max_x - min_x:.2f} x {max_y - min_y:.2f} mm extent including a "
            f"{MARGIN_MM} mm margin. Pin names joined from {library.name} on pad "
            f"number{'' if not unnamed else f'; {len(unnamed)} pad(s) had no entry and kept their number'}. "
            f"A pin is in group '{UNDERSIDE}' where it meets the module's "
            f"underside: every land of it wholly inside the footprint's F.Fab "
            f"outline{module_rule}. "
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


def _from_kicad_board(
    path: pathlib.Path,
    select: tuple[str, ...],
    symbols: pathlib.Path | None,
    connects: Connects | None,
    module: pathlib.Path | None,
) -> Geometry:
    """Read a whole KiCad board, taking the header pads off the footprints named.

    `select` names them by reference, as it names an EAGLE board's elements,
    and is always needed: a board places many footprints and which of them is
    the header is not something to guess.

    **One pin is one pad, and here the board file says which pads are one
    pin.** KiCad joins a footprint's pads to its symbol's pins by number, so
    pads that share a number are one pin: a castellated header gives each pin
    a hole and a half-hole at the edge, numbered alike. They are one pad here,
    at the whole hole -- the pad KiCad does not flag `pad_prop_castellated`.
    Pads that share a number and sit on different nets are refused, because
    one pin is on one net. An unnumbered pad is no pin at all, and numbered
    pads on no net connect nothing, so neither is ever merged.

    A pad is named after its net, as an EAGLE board's is, and a pad on no net
    keeps its number. A pad with neither is refused where it sits, because it
    would be named "" and nothing should invent a name for it (OH-184). Pads
    are grouped by the footprint they belong to.
    """
    if symbols is not None or connects is not None or module is not None:
        raise BoardImportError(
            f"{path}: --symbols and connects join a footprint's or an EAGLE "
            f"board's pads to their pins, and --module places a module's own "
            f"board under its footprint. A .kicad_pcb's pads carry their own "
            f"nets, numbers and layers, so there is nothing to join."
        )
    board = kicad.read_board(path)

    def through(placed: kicad.Placement) -> list[kicad.Pad]:
        return [pad for pad in placed.pads if pad.kind == "thru_hole"]

    offered = ", ".join(
        f"{placed.reference} ({len(through(placed))} pads, {placed.name})"
        for placed in board.placements
        if through(placed)
    )
    if not select:
        raise BoardImportError(
            f"{path}: which footprints carry the header is not something to "
            f"guess. Name them by reference with --select: {offered}"
        )
    repeated = sorted({name for name in select if select.count(name) > 1})
    if repeated:
        raise BoardImportError(
            f"{path}: --select names {', '.join(repeated)} more than once. "
            f"A footprint is placed once and its pads are read once."
        )
    chosen = []
    for name in select:
        placed = [one for one in board.placements if one.reference == name]
        if len(placed) != 1:
            raise BoardImportError(
                f"{path}: {len(placed)} footprints have the reference {name!r}, "
                f"and --select needs exactly one. Those with through-hole pads: "
                f"{offered}"
            )
        if not through(placed[0]):
            raise BoardImportError(
                f"{path}: {name} is a {placed[0].name}, which has no "
                f"through-hole pads"
            )
        chosen.append(placed[0])

    kept: list[tuple[kicad.Placement, kicad.Pad]] = []
    for placed in chosen:
        pins: dict[str, list[kicad.Pad]] = {}
        for pad in through(placed):
            pins.setdefault(pad.number, []).append(pad)
        for number, pads in pins.items():
            if not number:
                for pad in pads:
                    if not pad.net:
                        x, y = kicad.pad_on_board(placed, pad)
                        raise BoardImportError(
                            f"{path}: {placed.reference} ({placed.name}) has a "
                            f"plated through-hole pad at ({round(x, 4):g}, "
                            f"{round(y, 4):g}) on the board that the file gives "
                            f"neither a number nor a net, so it has no name to "
                            f"carry and none is invented for it."
                        )
                kept += [(placed, pad) for pad in pads]
                continue
            nets = {pad.net for pad in pads}
            if len(nets) > 1:
                where = ", ".join(
                    f"pad {number} at ({pad.x_mm:g}, {pad.y_mm:g}) on "
                    f"{pad.net or 'no net'}"
                    for pad in pads
                )
                raise BoardImportError(
                    f"{path}: {placed.reference} numbers {len(pads)} pads "
                    f"{number}, which makes them one pin, and puts them on "
                    f"different nets: {where}"
                )
            if nets == {""}:
                kept += [(placed, pad) for pad in pads]
                continue
            whole = [pad for pad in pads if not pad.castellated]
            kept.append((placed, (whole or pads)[0]))
    merged = sum(len(through(placed)) for placed in chosen) - len(kept)

    min_x, min_y, max_x, max_y = board.extent_mm()
    specs = []
    for placed, pad in kept:
        # Turned and moved by the footprint's own placement; KiCad's Y
        # already runs down, so nothing is flipped. See `kicad.pad_on_board`
        # for why a pad on the back is not mirrored.
        x, y = kicad.pad_on_board(placed, pad)
        specs.append(PadSpec(
            pad.net or pad.number, pad.number,
            round(x - min_x + MARGIN_MM, 4), round(y - min_y + MARGIN_MM, 4),
            placed.reference,
        ))
    named = ", ".join(f"{placed.reference} ({placed.name})" for placed in chosen)
    pins_rule = (
        f"Where a footprint gives several pads on one net one number, they are "
        f"one pin and one pad here, at the first of them KiCad does not flag "
        f"castellated -- the whole hole, not the half-hole the board's edge "
        f"cuts -- or the first of all where every one is; unnumbered pads and "
        f"pads on no net are never merged; {merged} pads were merged so. "
        if merged else ""
    )
    return Geometry(
        name=path.stem,
        width_mm=max_x - min_x + 2 * MARGIN_MM,
        height_mm=max_y - min_y + 2 * MARGIN_MM,
        pads=tuple(sorted(specs, key=lambda spec: (spec.y_mm, spec.x_mm))),
        derivation=(
            f"Generated by tools/import_board.py from the vendor's own KiCad "
            f"board file, {'footprint' if len(chosen) == 1 else 'footprints'} "
            f"{named}. Pad centres are the coordinates the file states, in "
            f"millimetres, placed by each footprint's position and rotation "
            f"against a {max_x - min_x:.2f} x {max_y - min_y:.2f} mm outline "
            f"taken from Edge.Cuts, plus a {MARGIN_MM} mm margin. Pad names are "
            f"the net each pad is on, and each pad's group is the footprint it "
            f"belongs to. {pins_rule}Nothing here was measured off an image."
        ),
        declared_name=None,
    )


#: Suffix to reader. Short on purpose: these are the formats a machine can
#: take pad coordinates out of.
READERS = {
    ".brd": _from_eagle,
    ".kicad_mod": _from_kicad,
    ".kicad_pcb": _from_kicad_board,
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
    "EAGLE .brd, KiCad .kicad_pcb or .kicad_mod. tools/board_sources.py records which "
    "vendors publish one."
)


def read_geometry(
    path: pathlib.Path,
    select: tuple[str, ...] = (),
    symbols: pathlib.Path | None = None,
    connects: Connects | None = None,
    module: pathlib.Path | None = None,
) -> Geometry:
    """Read any supported CAD file, or refuse it saying what is missing.

    `select` is a tuple because EAGLE needs several -- see `_from_eagle`. It
    stays one parameter rather than two because both readers are answering the
    same question, "which part of this file is the header"; a KiCad footprint
    simply has one answer, and `_from_kicad` says so rather than quietly using
    the first. A KiCad board's answer is several references, as an EAGLE
    board's is several elements.

    `connects`, for an EAGLE board, makes each pin one pad; see `Connects`. A
    KiCad board needs none: its pads say which are one pin by their number.

    `module`, for a module's KiCad footprint, is the module's own board file,
    read for which of its pads are on the module's underside; see
    `_under_the_module`.
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
        return reader(path, select, symbols, connects, module)
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
        # **The scale as a FIELD, not only a sentence** (OH-121). The
        # derivation always said "Scaled at 8.0 px/mm" and the page could not
        # read prose, so it re-derived the scale by dividing its pixel span by
        # a pad_span measured off a DIFFERENT pad field -- 28 sub-pads against
        # one pad per castellation -- and drew every composed SMD model 9%
        # small. A generated map states its own scale; only the traced Uno
        # map, which has no single true scale (its artwork is anisotropic),
        # leaves it absent and lets the page fit one.
        "px_per_mm": scale,
        "image": {
            "width": round(geometry.width_mm * scale),
            "height": round(geometry.height_mm * scale),
            "file": f"webui/boards/{geometry.name}.svg",
        },
        "derivation": f"{geometry.derivation} Scaled at {scale} px/mm.",
        # **This is the geometry half only, and it is not the last word on a
        # registered board.** Since OH-160 `tools/import_pindefs.py
        # --write-boards` rewrites this `assumption` and adds `chip_pin`,
        # `chip_index`, `why_null` and a `pindefs` block, all read out of the
        # board-support packages -- so re-importing a board that is in that
        # tool's registry STRIPS the pin join until it is run again. Run it
        # after this; `test_the_committed_board_files_match_the_generator`
        # names the file if it is forgotten, in a different suite and only
        # where the packages have been fetched.
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
        "KiCad board: a footprint reference carrying the header, repeated the "
        "same way. KiCad footprint: the symbol root to take pin names from, once",
    )
    parser.add_argument(
        "--symbols", type=pathlib.Path, help="KiCad symbol library (.kicad_sym)"
    )
    parser.add_argument(
        "--module",
        type=pathlib.Path,
        help="KiCad footprint of a module: the module's own .kicad_pcb, read for "
        "which pads at its outline's edge are on its underside",
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
        geometry = read_geometry(args.file, tuple(args.select), args.symbols,
                                 module=args.module)
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
        f"note: {board['image']['file']} was NOT generated, and nothing reads "
        f"image.file; webui/pinmap.py reads the image's width and height.",
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
