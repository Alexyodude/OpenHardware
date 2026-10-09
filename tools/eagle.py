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
`R90`, `MR180` (mirrored) or `SR90` (spun). `place` turns counter-clockwise
first, then mirrors in x, then translates (OH-211). KiCad 7's own EAGLE
importer reads `MRd` the same way: `orientFootprintAndText` sets the
footprint's orientation to d + 180 and then flips it top to bottom
(pcbnew/plugins/eagle/eagle_plugin.cpp at tag 7.0.0, lines 1563-1566), and a
half turn followed by a flip top to bottom is a mirror in x.

That order is a convention, not something the file states, so it was checked
against evidence the transform does not use: **a routed signal's copper must
end on the pads it connects.** Over the SparkFun Thing Plus ESP32-C6 board:

* all 131 contact references on routed, unpoured nets land within 0.01 mm of
  the pad centre computed here;
* mirroring first and turning second -- the order this module used until
  OH-211 -- lands 120, with a worst miss of 2.08 mm. The two orders agree at
  MR0 and MR180 and are half a turn apart at MR90 and MR270, and the 11 it
  missed are the contacts of the board's mirrored parts at MR90 and MR270;
* turning clockwise lands 109, dropping the mirror lands 104 with a worst
  residual of 10.7 mm, and dropping the rotation lands 88. So the check is
  sensitive to the thing it is checking, which is the part that makes it
  worth running. Mirroring first scores 120 whichever way it turns, which is
  why the direction of the turn was not pinned here until the order was.

The other 76 contact references sit on poured nets, where there is no wire to
land on, and are excluded rather than counted as failures. Those numbers are
`test_routed_copper_lands_on_the_computed_pad_centres`'s; across all eight
EAGLE boards on disk, every routed contact of a mirrored part on an unpoured
net lands, which is
`test_every_routed_contact_of_a_mirrored_eagle_part_lands_on_its_own_nets_copper`.
"""

from __future__ import annotations

import collections
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
    #: `rect | roundrect | circle | oval | custom`, and the ANGLE the pad's
    #: own rectangle makes with the board's x axis once it has been placed --
    #: not the angle stored in the file. Both are for DRAWING the copper and
    #: neither affects where a pad is, which is why they default and why every
    #: caller that only wants positions can ignore them.
    #:
    #: Empty and zero for an EAGLE board: `tools/eagle.py` reads `<smd>` and
    #: `<pad>`, neither of which this project has yet needed the shape of.
    shape: str = ""
    rotation_deg: float = 0.0
    #: Which side this pad's copper is on. A through-hole pad is on both, and
    #: says so; a surface-mount pad is on the side its footprint states.
    front: bool = True
    back: bool = False
    #: An unplated hole, which KiCad writes as a pad, `np_thru_hole`, and
    #: `compose_board_3d.from_kicad` gives the kind `smd`. Nothing is soldered
    #: to it and nothing is plated in it, so a placement holding one is not
    #: drawn by its copper (OH-163). Never set by this reader: EAGLE writes a
    #: hole as a `<hole>` and not as a pad.
    hole: bool = False


@dataclasses.dataclass(frozen=True)
class Segment:
    """A drawn line in millimetres. Named to match `tools/kicad.py`'s."""

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float


@dataclasses.dataclass(frozen=True)
class Stroke:
    """A drawn line with the width it was drawn at. Named to match kicad's.

    Silkscreen is ink, so it covers area and the width is most of what makes
    it visible -- which is the whole difference from `Segment`, whose width on
    a board OUTLINE means nothing.
    """

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float


@dataclasses.dataclass(frozen=True)
class Via:
    """A plated hole joining layers, at its outside diameter. Named to match
    `tools/kicad.py`'s, and carrying no drill for the same reason: a via on
    these boards is covered, so what shows is the ring and not the hole."""

    x_mm: float
    y_mm: float
    diameter_mm: float


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
    #: `(min_x, min_y, max_x, max_y)` of the package's silkscreen, in the
    #: package's own local millimetres, or `None` where it draws none.
    #:
    #: **The pads say where the pins are and this says where the BODY is**,
    #: which is a different fact and the only one that pins down which way a
    #: part faces. A barrel jack's pins are symmetric about their own centre
    #: whichever way the barrel points, so anything anchored on pins alone can
    #: be 180 degrees out and measure perfectly -- which is exactly what
    #: happened to the Arduino Uno's, by 7.50 mm, until this was read.
    silk: tuple[float, float, float, float] | None = None
    #: Where the vendor draws the package's PIN-1 MARKER, in the package's own
    #: local millimetres, or `None` where they draw none.
    #:
    #: **A body says where a part sits and this says which way round it is**,
    #: which `silk` cannot: a body outline is symmetric on most packages, so
    #: comparing it against a placed model survives a half turn. The marker is
    #: the one thing on the drawing that does not. See
    #: `compose_board_3d.mark_miss`, and `_silk_mark` for what counts as one.
    mark: tuple[float, float] | None = None
    #: The element's `value`. The package alone can mislead: Adafruit's
    #: Feather ESP32-C6 places its module as package `ESP32-PICO-MINI`, value
    #: `ESP32-C6-MINI_MINI`.
    value: str | None = None
    #: The package draws the board's own outline, so it is the board and not
    #: a part on it (OH-163): `kicad.Placement.edge`, carried across by
    #: `compose_board_3d.from_kicad`. Never set here, because this reader
    #: takes the outline from the board's plain wires on layer 20 and no
    #: package's.
    edge: bool = False

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
    #: The ink printed on the board, in board millimetres with y upward.
    #: Empty for an EAGLE board -- this reader does not gather layer 21 into
    #: strokes today, and a composed Uno therefore has no silkscreen while a
    #: composed XIAO does. Stated rather than silently uneven.
    silk: tuple[Stroke, ...] = ()
    #: What was on those layers and is not in `silk`, counted by kind, so a
    #: caption can say what it left out.
    silk_unread: tuple[tuple[str, int], ...] = ()
    #: A KiCad board's silkscreen text, as `kicad.Text` items in KiCad's own
    #: y-down frame -- **the one field here NOT in this module's y-up frame**,
    #: because what turns it into ink is KiCad's own layout arithmetic, done
    #: where KiCad does it; `compose_board_3d.letter` negates y on the strokes
    #: it makes, as `from_kicad` does every other coordinate (OH-163). Empty
    #: for an EAGLE board, whose `<text>` stays counted in `silk_unread`.
    kicad_text: tuple[object, ...] = ()
    #: The routed copper on the two outer layers, and the plated holes joining
    #: them. Both readers fill these; what neither draws is counted below.
    traces: tuple[Stroke, ...] = ()
    trace_arcs: tuple[object, ...] = ()
    vias: tuple[Via, ...] = ()
    traces_unread: tuple[tuple[str, int], ...] = ()

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

    Turn counter-clockwise, then mirror in x, then translate — the order
    checked against routed copper in this module's docstring (OH-211). `rot`
    is EAGLE's own spelling: an optional `S` (spin, which does not move the
    pad), an optional `M` (mirrored), then `R` and the angle in degrees.

    **A turn by d followed by a mirror in x is the same map as the mirror
    followed by a turn by -d**, and it is computed the second way. At MR0 and
    MR180, where turning first and mirroring first agree, that is then the
    very arithmetic this did before OH-211, bit for bit, so a composed board
    changes only where a placement moved.
    """
    degrees, mirrored = _rotation(rot)
    if mirrored:
        x_mm = -x_mm
        degrees = (-degrees) % 360.0
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
    turn, mirrored = _rotation(rot)

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
        pads.append(Pad(
            number, "thru_hole", x, y, width, width, nets.get((name, number)),
            # **EAGLE's pad shapes are not KiCad's**, so they are translated
            # here rather than passed through: `long` is an oval, `square`
            # and `offset` are rectangles, and `round` and `octagon` are near
            # enough a circle at the size a pad is drawn. A through-hole pad
            # with no `shape` at all takes EAGLE's own default, which is
            # round -- the Uno's 308 pads say nothing and are all round.
            shape=_EAGLE_PAD_SHAPES.get(drilled.get("shape") or "round", "circle"),
            rotation_deg=turn + _rotation(drilled.get("rot"))[0],
            # A drilled pad goes through the board, so its copper is on both
            # sides. EAGLE has no per-pad layer for it and does not need one.
            front=True, back=True,
        ))

    for surface in package.findall("smd"):
        number = surface.get("name") or ""
        x, y = place(
            _float(surface, "x", where), _float(surface, "y", where), origin, rot
        )
        # dx/dy are the pad's own axes and the pad's own ANGLE turns them,
        # which is why that angle is carried now: a pad map only ever wanted
        # centres, and drawing the copper wants the rectangle. Layer 1 is
        # EAGLE's top and 16 its bottom -- **of the PACKAGE**, and a mirrored
        # element puts the whole package on the other face, which `_ink`
        # already did for its silkscreen and this did not do for its copper
        # (OH-180): the Uno's GROUND solder jumper is mirrored and its two
        # pads were drawn on top from OH-110 on, and the QT Py's ESP32-C3's
        # 33 pads with it, on a board whose file puts them underneath.
        layer = surface.get("layer") or "1"
        if mirrored:
            layer = {"1": "16", "16": "1"}.get(layer, layer)
        pads.append(
            Pad(
                number,
                "smd",
                x,
                y,
                _float(surface, "dx", where),
                _float(surface, "dy", where),
                nets.get((name, number)),
                shape="roundrect" if surface.get("roundness") else "rect",
                rotation_deg=turn + _rotation(surface.get("rot"))[0],
                front=layer == "1",
                back=layer == "16",
            )
        )
    if mirrored:
        # A mirrored element is turned and then reflected in x -- the rule
        # `place` applies to every pad centre above (OH-211) -- and a
        # reflection reverses the sense of an angle, so the pad's own angle
        # plus the element's turn comes out negated. The Uno's GROUND jumper
        # is mirrored (MR0), as are the QT Py's ESP32-C3 and the Thing Plus's
        # underside resistors, which is what exercises it. (This said the Uno
        # placed nothing mirrored until OH-180 read the file.)
        pads = [dataclasses.replace(pad, rotation_deg=-pad.rotation_deg)
                for pad in pads]
    return tuple(pads)


#: EAGLE's `<pad shape>` in `tools/kicad.py`'s vocabulary, which is the one
#: `compose_board_3d.pad_outline` draws from. Two libraries, one drawing.
_EAGLE_PAD_SHAPES = {
    "round": "circle", "octagon": "circle",
    "square": "rect", "offset": "rect", "long": "oval",
}


#: EAGLE's silkscreen layers: 21 is `tPlace`, the outline a component's body
#: is drawn as, and 51 is `tDocu`, where a library that keeps the courtyard
#: separate from the assembly drawing puts the rest of it. Both are read
#: because vendors disagree about which to use and this needs the body, not a
#: layer number.
SILK_LAYERS = ("21", "51")


def _silk_extent(package: ET.Element) -> tuple[float, float, float, float] | None:
    """The package's drawn body, in its own local millimetres, or None.

    Wires only. A `<text>` is a reference designator that EAGLE places outside
    the part as often as on it, and including one would make a 5 mm capacitor
    measure 15. Circles and rectangles are not read either: no package in the
    tree this was written against draws its body with them, and a partial
    extent that looks complete is worse than none at all.
    """
    xs: list[float] = []
    ys: list[float] = []
    for wire in package.findall("wire"):
        if wire.get("layer") in SILK_LAYERS:
            xs += [float(wire.get("x1")), float(wire.get("x2"))]
            ys += [float(wire.get("y1")), float(wire.get("y2"))]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _silk_mark(package: ET.Element) -> tuple[float, float] | None:
    """The package's pin-1 marker, in its own local millimetres, or None.

    **What counts as one is CURVATURE**, and that is a reading of the drawing
    rather than a guess at intent. A package body is drawn with straight
    wires; the two things a library curves on the silkscreen are the DIP
    notch, written as a wire with a `curve` attribute, and the corner dot,
    written as a `<circle>`. Arduino's own `DIL28-3` draws the first at
    x -18.542, the end its pad 1 is at, and its `MLF32` draws the second at
    (-1.600, 1.600), the corner its pad 1 is at.

    The centroid of every such feature is returned, and the caller decides
    whether it is off-centre enough to mean anything -- because curvature
    alone does not: `PANASONIC_D` draws its can as two arcs whose centroid is
    the package origin to the micron, and `TS42` draws a button as two
    concentric circles. Both are outlines that happen to be round, and both
    correctly say nothing about which way round the part goes. See
    `compose_board_3d.MARK_OFFSET_FRACTION` for the number that separates them
    and the margin it was measured to have.
    """
    marks: list[tuple[float, float]] = []
    for wire in package.findall("wire"):
        if wire.get("layer") in SILK_LAYERS and wire.get("curve") is not None:
            marks.append(((float(wire.get("x1")) + float(wire.get("x2"))) / 2,
                          (float(wire.get("y1")) + float(wire.get("y2"))) / 2))
    for circle in package.findall("circle"):
        if circle.get("layer") in SILK_LAYERS:
            marks.append((float(circle.get("x")), float(circle.get("y"))))
    if not marks:
        return None
    return (sum(m[0] for m in marks) / len(marks),
            sum(m[1] for m in marks) / len(marks))


def _open(path: pathlib.Path, wanted: str, text: str | None = None) -> ET.Element:
    """The `<eagle>` root of `path`, or an error saying what the file is instead.

    Shared by the board and schematic readers because the way an EAGLE file
    fails to be one is the same either way, and the message that matters --
    naming the binary formats that share these extensions — should not exist
    in two versions that can drift apart. `text`, where given, is parsed in
    place of the file, and `path` only names it.
    """
    try:
        root = ET.fromstring(text) if text is not None else ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise EagleError(
            f"{path}: not XML, so not an EAGLE 6-or-later {wanted} ({exc}). "
            f"EAGLE 5 and earlier are binary, and so are Cadence Allegro .brd "
            f"and Altium .SchDoc; none can be read here."
        ) from exc
    except OSError as exc:
        raise EagleError(f"{path}: {exc}") from exc

    if root.tag != "eagle":
        raise EagleError(
            f"{path}: XML, but the root element is <{root.tag}>, not <eagle>"
        )
    return root


#: EAGLE's two silkscreen INK layers in `tools/kicad.py`'s vocabulary, which
#: is what draws them: 21 is `tPlace` and 22 is `bPlace`. Layer 51 (`tDocu`)
#: deliberately stays out -- `_silk_extent` reads it for a BODY extent, but as
#: ink it holds courtyards and keep-outs a real board does not print.
INK_LAYERS = {"21": "F.SilkS", "22": "B.SilkS"}


def _ink(board: ET.Element, elements: list[Element],
         packages: dict) -> tuple[tuple[Stroke, ...], tuple[tuple[str, int], ...]]:
    """Every straight silkscreen wire on the board, as placed strokes.

    **The Arduino Uno printed nothing because this did not exist** (OH-122):
    `read_board` built `Board` with the `silk` default, so `compose` said
    `ink front 0, ink back 0` -- with no `not ink` line either -- while the
    KiCad boards drew 81-1518 strokes a face. Counted in Arduino's file: 428
    layer-21 wires on placed packages and 4 board-level, all straight, NO
    FONT NEEDED.

    Two sources, transformed exactly as their pads are:

      * board-level `<plain>` wires, already in board coordinates;
      * each element's package wires, through `place` with the element's own
        spelling -- and **a mirrored element swaps its ink to the other
        face**, because EAGLE's `MR` puts the whole package on the underside.

    What is NOT read is counted by kind, the same contract `kicad._silk_of`
    keeps: curved wires (the DIP notch), rectangles, circles, polygons and
    text, so the composer prints what it left out instead of leaving silence.
    """
    strokes: list[Stroke] = []
    unread: collections.Counter = collections.Counter()

    def take(wire: ET.Element, layer: str,
             transform=None) -> None:
        if wire.get("curve") is not None:
            unread["arc"] += 1
            return
        x1, y1 = float(wire.get("x1")), float(wire.get("y1"))
        x2, y2 = float(wire.get("x2")), float(wire.get("y2"))
        if transform is not None:
            x1, y1 = transform(x1, y1)
            x2, y2 = transform(x2, y2)
        strokes.append(Stroke(layer, x1, y1, x2, y2,
                              float(wire.get("width") or 0.0)))

    for wire in board.findall("plain/wire"):
        layer = INK_LAYERS.get(wire.get("layer"))
        if layer is not None:
            take(wire, layer)
    for kind in ("rectangle", "circle", "polygon", "text"):
        for node in board.findall(f"plain/{kind}"):
            if node.get("layer") in INK_LAYERS:
                unread[kind] += 1

    for element in elements:
        package = packages[(element.library, element.package)]
        spelling = (("MR" if element.mirrored else "R")
                    + str(int(element.rotation)))
        origin = (element.x_mm, element.y_mm)

        def placed(x: float, y: float,
                   _origin=origin, _spelling=spelling) -> tuple[float, float]:
            return place(x, y, _origin, _spelling)

        for wire in package.findall("wire"):
            layer = INK_LAYERS.get(wire.get("layer"))
            if layer is None:
                continue
            if element.mirrored:
                layer = "B.SilkS" if layer == "F.SilkS" else "F.SilkS"
            take(wire, layer, placed)
        for kind in ("rectangle", "circle", "polygon", "text"):
            for node in package.findall(kind):
                if node.get("layer") in INK_LAYERS:
                    unread[kind] += 1
    return tuple(strokes), tuple(sorted(unread.items()))


def read_board(path: pathlib.Path, text: str | None = None) -> Board:
    """Read one EAGLE `.brd`, or `text` already read from it.

    Refuses anything that is not EAGLE XML **by name**. The extension is not
    enough: Cadence Allegro writes `.brd` too, and the Raspberry Pi Pico
    design files ship one. Handing a binary Allegro board to an XML parser
    would fail somewhere deep with a message about byte 0, so the check is up
    front and says which format was found instead.
    """
    root = _open(path, "board", text)
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
                _silk_extent(package),
                _silk_mark(package),
                node.get("value"),
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
    tracks, vias, unrouted = _routing(board, str(path))
    silk, silk_unread = _ink(board, elements, packages)
    return Board(path.stem, root.get("version") or "unknown", tuple(elements),
                 tuple(outline), silk=silk, silk_unread=silk_unread,
                 traces=tracks, vias=vias,
                 traces_unread=unrouted)


#: EAGLE's copper layers by number: 1 is the top and 16 the bottom, named here
#: in `tools/kicad.py`'s vocabulary because that is what draws them.
#:
#: **Layer 19 is `Unrouted` and it must never be in this table.** An airwire is
#: a connection the router has NOT made -- a straight line from one pad to
#: another through whatever is in the way -- and the Arduino Uno carries two.
#: Drawn as copper they would be two traces crossing the board that are not
#: on it.
COPPER_LAYERS = {"1": "F.Cu", "16": "B.Cu"}


def _routing(board: ET.Element, where: str
             ) -> tuple[tuple[Stroke, ...], tuple[Via, ...],
                        tuple[tuple[str, int], ...]]:
    """The routed copper: `<signal>` wires and vias, in board millimetres.

    A signal's wires are already in board space -- EAGLE routes on the board,
    not inside a package -- so unlike a pad there is no placement to apply.

    **A `curve` attribute is not read**, and the Uno has none: EAGLE stores a
    curved wire as its two endpoints plus a bulge in degrees, and taking the
    endpoints alone would draw the chord. Counted rather than silently
    straightened.
    """
    strokes: list[Stroke] = []
    vias: list[Via] = []
    unread: dict[str, int] = {}
    for signal in board.findall("signals/signal"):
        for wire in signal.findall("wire"):
            layer = COPPER_LAYERS.get(wire.get("layer") or "")
            if layer is None:
                name = f"layer {wire.get('layer')}"
                unread[name] = unread.get(name, 0) + 1
                continue
            if wire.get("curve"):
                unread["curved"] = unread.get("curved", 0) + 1
                continue
            strokes.append(Stroke(
                layer,
                _float(wire, "x1", where), _float(wire, "y1", where),
                _float(wire, "x2", where), _float(wire, "y2", where),
                _float(wire, "width", where),
            ))
        for hole in signal.findall("via"):
            # `diameter` is optional here for the reason it is optional on a
            # pad: the design rules decide it when the file does not, and the
            # drill is always written.
            size = hole.get("diameter")
            across = float(size) if size else _float(hole, "drill", where)
            vias.append(Via(_float(hole, "x", where),
                            _float(hole, "y", where), across))
    return tuple(strokes), tuple(vias), tuple(sorted(unread.items()))


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
