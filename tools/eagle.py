#!/usr/bin/env python3
# OpenHardware - read EAGLE board files into pads, nets and an outline.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Parse an EAGLE `.brd` into placed pads, the nets on them, and the outline.

`tools/kicad.py` does this for Seeed, who publish KiCad. Nobody else does.
Adafruit and SparkFun publish EAGLE, Arduino publishes both, and the survey in
`docs/research/board-sources/` found EAGLE to be the most common format a
board vendor actually ships. This is the second parser behind
`tools/import_board.py`, which is what makes the importer a front end rather
than a Seeed tool.

## EAGLE 6 and later is XML, whatever the survey said

`docs/research/board-sources/sources.json` records SparkFun's `.sch` and `.brd`
as "EagleCAD, proprietary binary". They are not. Autodesk moved EAGLE to an
XML format at version 6, and the file this module was written against declares
`<eagle version="9.6.2">` with a plain `<?xml ...?>` header. The binary
description is true of EAGLE 5 and earlier, and of Cadence Allegro `.brd`,
which shares the extension and is **not** this format — see `read_board`,
which refuses it by name rather than producing nonsense from a binary blob.

## Units and origin, which are not KiCad's

* **Millimetres.** EAGLE stores coordinates in mm in the XML regardless of
  the grid unit the drawing displays — the file read here has
  `<grid unit="inch">` and mm coordinates throughout.
* **Y increases upward**, from an origin at the bottom-left. KiCad footprints
  put Y downward, and so does every `webui/boards/*.json` in this repository,
  because those are SVG pixel coordinates.

**This module reports the vendor's numbers unchanged.** A pad written
`y="52.07"` is reported as `52.07`. Flipping the axis is the importer's job
and happens once, at the point millimetres become pixels, so that a test can
compare what is parsed here against the literal text of the vendor's file.

## Placement, and how it was checked

A package holds pads at coordinates relative to its own origin; an `<element>`
places that package at a board coordinate with an optional rotation like
`R90`, `MR180` (mirrored) or `SR90` (spun). `place` mirrors in x first, then
rotates counter-clockwise, then translates.

That order is a convention, not something the file states, so it was checked
against evidence the transform does not use: **a routed signal's copper must
end on the pads it connects.** Over the SparkFun Thing Plus ESP32-C6 board,
across all eight rotation and mirror combinations:

* 120 of 131 contact references on routed nets land within 0.01 mm of the pad
  centre computed here;
* the other 11 miss by between 0.81 mm and 2.09 mm — less than one pad in
  every case, and six of them by exactly an SMT jumper's own pad pitch,
  because EAGLE routes to the jumper's other pad. None is a distance a
  misplaced component could produce;
* dropping the mirror takes 120 to 104 and the worst residual to 10.7 mm, and
  dropping the rotation takes it to 88. So the check is sensitive to the thing
  it is checking, which is the part that makes it worth running.

The other 76 contact references sit on poured nets, where there is no wire to
land on, and are excluded rather than counted as failures.

**What this does not establish:** rotating the other way also scores 120.
Every rotated package on that board has a point-symmetric pad set — a two-pad
0603 at R90 and at R270 puts the same pads in the same places — so the
*sign* of the rotation is taken from EAGLE's documented behaviour and not from
this evidence. The magnitude and the mirroring are pinned; the direction is
not, and a board with an asymmetric rotated package would settle it.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib
import xml.etree.ElementTree as ET

#: The EAGLE layer holding the board outline. 20 is `Dimension` in every
#: EAGLE installation; it is a fixed layer number, not a per-file choice.
DIMENSION_LAYER = "20"


class EagleError(Exception):
    """A file is not EAGLE XML, or does not hold what was asked of it."""


@dataclasses.dataclass(frozen=True)
class Pad:
    """One pad, placed in the board's millimetre space with Y upward.

    `kind` uses `tools/kicad.py`'s vocabulary rather than EAGLE's own, so the
    importer above can select through-hole pads without knowing which parser
    produced them. EAGLE's `<pad>` is always drilled and its `<smd>` never is,
    so the mapping is exact and needs no inference.
    """

    number: str
    kind: str  # thru_hole | smd
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    #: The signal on this pad, which is the only place a *name* for it exists.
    #: A package pad is numbered, not named; `GND` and `IO7/SCL` come from
    #: `<signals>`. None means the pad is not connected to anything.
    net: str | None


@dataclasses.dataclass(frozen=True)
class Segment:
    """A drawn line in millimetres. Named to match `tools/kicad.py`'s."""

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float


@dataclasses.dataclass(frozen=True)
class Element:
    """One placed component and the pads it puts on the board.

    **The placement is carried as well as applied.** `pads` already has the
    transform baked in, which is all a pad map needs; putting a *model* of the
    part on the board needs the transform itself, because a mesh has to be
    moved the same way the pads were. Added for OH-75, which stands a DIP-28
    and four headers on an Arduino Uno.
    """

    name: str
    library: str
    package: str
    pads: tuple[Pad, ...]
    #: Where the package's own origin sits on the board, in millimetres.
    x_mm: float = 0.0
    y_mm: float = 0.0
    #: Counter-clockwise degrees, and whether it is mirrored -- EAGLE's `rot`
    #: already decoded, so a caller never parses `"MR180"` a second time.
    #: `place()` is the authority on the order these are applied in.
    rotation: float = 0.0
    mirrored: bool = False

    def pads_of(self, kind: str) -> tuple[Pad, ...]:
        return tuple(pad for pad in self.pads if pad.kind == kind)

    def pad_extent(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) over every pad, in board millimetres.

        What a proposed 3D model for this package is checked against: a mesh
        that does not span the pads its own footprint puts down is not that
        part. Raises rather than returning an empty box, because "this element
        has no pads" is a different answer from "its pads are at the origin".
        """
        if not self.pads:
            raise EagleError(
                f"element {self.name!r} ({self.package}) places no pads, so it "
                f"has no extent to compare anything against"
            )
        xs = [pad.x_mm for pad in self.pads]
        ys = [pad.y_mm for pad in self.pads]
        return min(xs), min(ys), max(xs), max(ys)


@dataclasses.dataclass(frozen=True)
class Board:
    name: str
    version: str
    elements: tuple[Element, ...]
    outline: tuple[Segment, ...]

    def element(self, name: str) -> Element:
        for candidate in self.elements:
            if candidate.name == name:
                return candidate
        raise EagleError(
            f"{self.name}: no element called {name!r}. This board places: "
            f"{', '.join(candidate.name for candidate in self.elements)}"
        )

    def extent_mm(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) of the drawn outline.

        Arcs are taken as their chords: an EAGLE outline wire may carry a
        `curve` attribute, and the bulge is ignored here. On a rounded
        rectangle the straight edges already define the bounding box, so this
        is exact; on an outline that is *only* arcs it would under-report by
        the sagitta. Stated rather than silently assumed away.
        """
        if not self.outline:
            raise EagleError(
                f"{self.name}: no wires on layer {DIMENSION_LAYER} (Dimension), so "
                f"the board has no outline to measure. Refusing to invent one."
            )
        xs = [value for seg in self.outline for value in (seg.x1_mm, seg.x2_mm)]
        ys = [value for seg in self.outline for value in (seg.y1_mm, seg.y2_mm)]
        return min(xs), min(ys), max(xs), max(ys)


def place(
    x_mm: float, y_mm: float, origin: tuple[float, float], rot: str | None
) -> tuple[float, float]:
    """Move a package-local point to board coordinates.

    Mirror in x, then rotate counter-clockwise, then translate — the order
    checked against routed copper in this module's docstring. `rot` is EAGLE's
    own spelling: an optional `S` (spin, which does not move the pad), an
    optional `M` (mirrored), then `R` and the angle in degrees.
    """
    degrees, mirrored = _rotation(rot)
    if mirrored:
        x_mm = -x_mm
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return (
        origin[0] + x_mm * cos - y_mm * sin,
        origin[1] + x_mm * sin + y_mm * cos,
    )


def _rotation(rot: str | None) -> tuple[float, bool]:
    """`"MR90"` to `(90.0, True)`. Errors name the value they could not read."""
    if not rot:
        return 0.0, False
    mirrored = "M" in rot
    digits = rot.lstrip("SMR")
    try:
        return float(digits or 0.0), mirrored
    except ValueError as exc:
        raise EagleError(
            f"cannot read the rotation {rot!r}: expected an optional S and M, "
            f"then R and an angle, as in R90 or MR180"
        ) from exc


def _float(node: ET.Element, attribute: str, where: str) -> float:
    raw = node.get(attribute)
    if raw is None:
        raise EagleError(f"{where}: <{node.tag}> has no {attribute!r} attribute")
    try:
        return float(raw)
    except ValueError as exc:
        raise EagleError(
            f"{where}: <{node.tag}> {attribute}={raw!r} is not a number"
        ) from exc


def _nets(board: ET.Element) -> dict[tuple[str, str], str]:
    """(element, pad) to signal name, from `<signals>`.

    This is the join that gives a pad a *name*. A package pad is numbered; the
    label a person reads off the silkscreen is the net, and the two only meet
    here. `tools/kicad.py` needs a separate `.kicad_sym` file for the same
    thing; EAGLE keeps it in the board.
    """
    named: dict[tuple[str, str], str] = {}
    for signal in board.findall("signals/signal"):
        name = signal.get("name")
        if name is None:
            continue
        for ref in signal.findall("contactref"):
            element, pad = ref.get("element"), ref.get("pad")
            if element is not None and pad is not None:
                named[(element, pad)] = name
    return named


def _packages(board: ET.Element) -> dict[tuple[str, str], ET.Element]:
    """(library, package) to the package node, for placement to look up."""
    found: dict[tuple[str, str], ET.Element] = {}
    for library in board.findall("libraries/library"):
        lib_name = library.get("name")
        if lib_name is None:
            continue
        for package in library.findall("packages/package"):
            pkg_name = package.get("name")
            if pkg_name is not None:
                found[(lib_name, pkg_name)] = package
    return found


def _element_pads(
    node: ET.Element,
    package: ET.Element,
    nets: dict[tuple[str, str], str],
    where: str,
) -> tuple[Pad, ...]:
    name = node.get("name") or ""
    origin = (_float(node, "x", where), _float(node, "y", where))
    rot = node.get("rot")

    pads: list[Pad] = []
    for drilled in package.findall("pad"):
        number = drilled.get("name") or ""
        x, y = place(
            _float(drilled, "x", where), _float(drilled, "y", where), origin, rot
        )
        # `diameter` is optional: EAGLE lets the design rules decide it, and
        # then the attribute is absent. The drill is always there, so it is
        # the fallback. This affects only the drawn size of the pad — the
        # centre, which is the thing this repository actually wires to, is
        # exact either way.
        size = drilled.get("diameter")
        width = float(size) if size else _float(drilled, "drill", where)
        pads.append(Pad(number, "thru_hole", x, y, width, width, nets.get((name, number))))

    for surface in package.findall("smd"):
        number = surface.get("name") or ""
        x, y = place(
            _float(surface, "x", where), _float(surface, "y", where), origin, rot
        )
        # dx/dy are the pad's own axes; a rotated element turns them too, but
        # only the extent uses them and a swapped width and height changes
        # nothing this importer emits. Left unrotated, and said so.
        pads.append(
            Pad(
                number,
                "smd",
                x,
                y,
                _float(surface, "dx", where),
                _float(surface, "dy", where),
                nets.get((name, number)),
            )
        )
    return tuple(pads)


def _open(path: pathlib.Path, wanted: str) -> ET.Element:
    """The `<eagle>` root of `path`, or an error saying what the file is instead.

    Shared by the board and schematic readers because the way an EAGLE file
    fails to be one is the same either way, and the message that matters --
    naming the binary formats that share these extensions — should not exist
    in two versions that can drift apart.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise EagleError(
            f"{path}: not XML, so not an EAGLE 6-or-later {wanted} ({exc}). "
            f"EAGLE 5 and earlier are binary, and so are Cadence Allegro .brd "
            f"and Altium .SchDoc; none can be read here."
        ) from exc
    except OSError as exc:
        raise EagleError(f"{path}: {exc}") from exc

    root = tree.getroot()
    if root.tag != "eagle":
        raise EagleError(
            f"{path}: XML, but the root element is <{root.tag}>, not <eagle>"
        )
    return root


def read_board(path: pathlib.Path) -> Board:
    """Read one EAGLE `.brd`.

    Refuses anything that is not EAGLE XML **by name**. The extension is not
    enough: Cadence Allegro writes `.brd` too, and the Raspberry Pi Pico
    design files ship one. Handing a binary Allegro board to an XML parser
    would fail somewhere deep with a message about byte 0, so the check is up
    front and says which format was found instead.
    """
    root = _open(path, "board")
    board = root.find("drawing/board")
    if board is None:
        raise EagleError(
            f"{path}: an EAGLE file, but it holds no <board> — a .sch has "
            f"<schematic> and a .lbr has <library>, and neither carries the "
            f"placed geometry this needs"
        )

    nets = _nets(board)
    packages = _packages(board)

    elements: list[Element] = []
    for node in board.findall("elements/element"):
        name = node.get("name") or ""
        key = (node.get("library") or "", node.get("package") or "")
        package = packages.get(key)
        if package is None:
            raise EagleError(
                f"{path}: element {name!r} places package {key[1]!r} from library "
                f"{key[0]!r}, which the file does not contain"
            )
        where = f"{path}: element {name!r}"
        degrees, mirrored = _rotation(node.get("rot"))
        elements.append(
            Element(
                name,
                key[0],
                key[1],
                _element_pads(node, package, nets, where),
                _float(node, "x", where),
                _float(node, "y", where),
                degrees,
                mirrored,
            )
        )
    if not elements:
        raise EagleError(f"{path}: places no elements; refusing to report an empty board")

    outline = [
        Segment(
            DIMENSION_LAYER,
            _float(wire, "x1", str(path)),
            _float(wire, "y1", str(path)),
            _float(wire, "x2", str(path)),
            _float(wire, "y2", str(path)),
        )
        for wire in board.findall("plain/wire")
        if wire.get("layer") == DIMENSION_LAYER
    ]
    return Board(path.stem, root.get("version") or "unknown", tuple(elements), tuple(outline))


# --- schematics ---------------------------------------------------------------
#
# A board file says where the copper is. A schematic says what is connected to
# what, and that is a different question with a different answer: the header
# pad silkscreened `GPIO5` on the board this was written against is on the
# module's `IO23`, and no amount of reading the layout would reveal it.


@dataclasses.dataclass(frozen=True)
class Part:
    """One component in the schematic, by its reference designator."""

    name: str
    library: str
    deviceset: str
    device: str
    value: str | None


@dataclasses.dataclass(frozen=True)
class PinRef:
    """One end of a net: a named pin on a named part."""

    part: str
    gate: str
    pin: str


@dataclasses.dataclass(frozen=True)
class Net:
    """One net, and everything on it.

    EAGLE splits a net into `<segment>`s, one per drawn run of wire. They are
    the same electrical node, so the segments are flattened here; keeping them
    apart would make a net look like several and break every question worth
    asking of it.
    """

    name: str
    pins: tuple[PinRef, ...]

    def on(self, part: str) -> tuple[PinRef, ...]:
        return tuple(ref for ref in self.pins if ref.part == part)


@dataclasses.dataclass(frozen=True)
class Schematic:
    name: str
    version: str
    parts: tuple[Part, ...]
    nets: tuple[Net, ...]

    def part(self, name: str) -> Part:
        for candidate in self.parts:
            if candidate.name == name:
                return candidate
        raise EagleError(
            f"{self.name}: no part called {name!r}. This schematic has "
            f"{len(self.parts)} parts, among them: "
            f"{', '.join(p.name for p in self.parts[:12])}"
        )

    def pins_of(self, part: str) -> tuple[str, ...]:
        """Every pin of `part` that any net reaches.

        Pins with nothing on them do not appear: a schematic lists a part's
        pins in its library symbol, and this reads the nets. An unconnected
        pin is absent rather than reported as connected to nothing, which is
        the same distinction `absent` and `unsearchable` draw elsewhere.
        """
        return tuple(
            sorted({ref.pin for net in self.nets for ref in net.on(part)})
        )


def read_schematic(path: pathlib.Path) -> Schematic:
    """Read one EAGLE `.sch` into parts and flattened nets.

    Refuses a board file by name: `.sch` and `.brd` are the same XML dialect
    with different payloads, and reading one as the other would report zero
    nets over a file full of them, which reads exactly like a board with
    nothing connected.
    """
    root = _open(path, "schematic")
    schematic = root.find("drawing/schematic")
    if schematic is None:
        holds = "a <board>" if root.find("drawing/board") is not None else "neither"
        raise EagleError(
            f"{path}: an EAGLE file, but it holds no <schematic> ({holds}). "
            f"Connectivity lives in the schematic; the board file has the "
            f"copper and tools/eagle.py's read_board is what reads that."
        )

    parts = tuple(
        Part(
            node.get("name") or "",
            node.get("library") or "",
            node.get("deviceset") or "",
            node.get("device") or "",
            node.get("value"),
        )
        for node in schematic.findall("parts/part")
    )
    if not parts:
        raise EagleError(f"{path}: lists no parts; refusing to report an empty schematic")

    nets = []
    for node in schematic.findall("sheets/sheet/nets/net"):
        name = node.get("name")
        if name is None:
            continue
        refs = tuple(
            PinRef(ref.get("part") or "", ref.get("gate") or "", ref.get("pin") or "")
            for segment in node.findall("segment")
            for ref in segment.findall("pinref")
        )
        nets.append(Net(name, refs))
    if not nets:
        raise EagleError(
            f"{path}: {len(parts)} parts and not one net. A schematic with no "
            f"connectivity is not one; refusing to report it as empty."
        )
    return Schematic(path.stem, root.get("version") or "unknown", parts, tuple(nets))
