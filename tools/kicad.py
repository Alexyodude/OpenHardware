#!/usr/bin/env python3
# OpenHardware - read KiCad footprints and symbol libraries.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Parse `.kicad_mod` and `.kicad_sym` into pads, graphics and pin names.

`webui/pinmap.py` records the problem this solves:

    Nothing upstream knows where a board's pins are. [...] a UI that lets you
    drag a wire onto a physical header needs data that does not exist yet.

For PICSimLab's own boards that data had to be measured off `board.svg` by
hand. For any board whose vendor publishes KiCad files it does not: a
footprint carries pad centres in millimetres, to three decimal places, as
authored by the people who made the board.

Seeed Studio publishes exactly that for the XIAO series, MIT licensed
(`python tools/get_board_sources.py seeed-xiao`). This module reads it.

## Why a real parser and not a regex

The first attempt at reading these files used a regex over `(pad "1" smd
roundrect\\n\\t\\t(at 7.62 -8.455 90)`. It worked on that file and would have
broken on the next one: `at` is optional-argument (rotation may be absent),
pads nest `(options)` and `(primitives)` blocks, and `fp_poly` contains a
`(pts ...)` list of unbounded length. S-expressions are a tree; matching them
with a flat pattern is guessing.

So this is a small recursive descent parser -- about forty lines -- and
everything above it works on the tree.

## What a footprint gives, and what it does not

Present: pad number, type, centre, size, layers; and graphic primitives on
each layer, which is what makes a drawn outline possible.

Absent: **pin names**. A footprint's pad "1" is a position, not a signal --
the name `D0` lives in the symbol library, keyed by the same number. The two
must be joined, and `read_symbol_pins` is the other half.

Also absent: **3D geometry**. Footprints reference STEP files under
`${AMZPATH}`, an external path Seeed does not ship. `webui/models3d.js` builds
components procedurally anyway.
"""

from __future__ import annotations

import collections
import dataclasses
import math
import pathlib
import re

#: KiCad stores millimetres. The web UI works in pixels on a board image.
#: 0.1 inch = 2.54 mm is the header pitch every through-hole board uses, and
#: `webui/pinmap.py` treats that pitch as what identifies a header run, so a
#: scale that keeps it a round number of pixels keeps that check meaningful.
DEFAULT_PX_PER_MM = 8.0


class KicadError(Exception):
    """A file was not the shape this parser can read."""


# --- s-expression ------------------------------------------------------------

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()]+')

#: A backslash escape inside a quoted string, as KiCad's own reader takes it
#: (`DSNLEXER::NextTok` in common/dsnlexer.cpp): one to two hex digits after
#: `x`, one to three octal digits, or one character. Matched on the UTF-8
#: bytes, because that reader works on bytes and a numeric escape is a byte.
_ESCAPE = re.compile(rb"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)", re.DOTALL)
_ESCAPED = {
    b'"': b'"', b"\\": b"\\", b"a": b"\x07", b"b": b"\x08", b"f": b"\x0c",
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"v": b"\x0b",
    # A goofed hex escape, `\x` with no digit, is an `x`.
    b"x": b"x",
}


def _unescape(quoted: str) -> str:
    """A quoted string's contents as KiCad reads them.

    KiCad writes `\\\\` for a backslash, `\\"` for a quote and `\\n`, `\\r`
    for line breaks (`OUTPUTFORMATTER::Quotes`), so a net named
    `/GPIO5\\SPI_CS` is stored with its backslash doubled. Anything its
    reader does not take as an escape keeps the backslash.
    """
    def one(match: re.Match) -> bytes:
        sequence = match.group(1)
        if sequence[:1] == b"x" and len(sequence) > 1:
            return bytes([int(sequence[1:], 16)])
        if sequence[:1] in b"01234567":
            return bytes([int(sequence, 8) & 0xFF])
        return _ESCAPED.get(sequence, b"\\" + sequence)

    try:
        return _ESCAPE.sub(one, quoted.encode("utf-8")).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KicadError(
            f"the string {quoted!r} un-escapes to bytes that are not UTF-8"
        ) from exc


def parse_sexp(text: str) -> list:
    """Parse one s-expression into nested lists. Strings keep their quotes off."""
    tokens = _TOKEN.findall(text)
    if not tokens:
        raise KicadError("empty file")

    pos = 0

    def node():
        nonlocal pos
        if tokens[pos] != "(":
            raise KicadError(f"expected '(' at token {pos}: {tokens[pos]!r}")
        pos += 1
        out: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "(":
                out.append(node())
            elif tok == ")":
                pos += 1
                return out
            else:
                pos += 1
                out.append(_unescape(tok[1:-1]) if tok.startswith('"') else tok)
        raise KicadError("unbalanced parentheses")

    tree = node()
    return tree


def head(node: list) -> str:
    """The tag of an s-expression node, or '' if it has none."""
    return node[0] if node and isinstance(node[0], str) else ""


def children(node: list, tag: str):
    """Direct child nodes with the given tag."""
    return [c for c in node if isinstance(c, list) and head(c) == tag]


def first(node: list, tag: str) -> list | None:
    found = children(node, tag)
    return found[0] if found else None


def _floats(node: list) -> list[float]:
    out = []
    for item in node[1:]:
        if isinstance(item, str):
            try:
                out.append(float(item))
            except ValueError:
                break
        else:
            break
    return out


# --- footprints ---------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Pad:
    """One pad, positioned in the footprint's own millimetre space."""

    number: str
    kind: str  # smd | thru_hole | np_thru_hole | connect
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    #: `rect | roundrect | circle | oval | custom`, the vendor's own token.
    #: Needed to DRAW a pad and irrelevant to placing one, which is why it
    #: arrived late: a castellated half-hole is a circle and a chip land is a
    #: rectangle, and 253 of the 1,679 pads on the five composed XIAOs are
    #: round.
    shape: str = ""
    #: The pad's own turn, in degrees, and **it is ABSOLUTE rather than
    #: relative to the footprint**. Measured on the RP2350: of the 20 pads in
    #: footprints placed at 90 degrees, all 20 say 90; of the 79 in footprints
    #: at 180, all say 180. So a pad's angle in board space IS this number,
    #: and a pad drawn without it is the wrong shape 224 times out of 316.
    rotation_deg: float = 0.0
    #: `("F.Cu", "F.Paste", "F.Mask")` and so on, the vendor's own list.
    #: **Which side a pad's copper is on is the pad's statement, not its
    #: footprint's**: the RP2350 has 16 pads on `B.Cu` inside front-side
    #: footprints and 24 on `*.Cu`, which is both.
    layers: tuple[str, ...] = ()
    #: The net the pad is on, which only a board states: a pad in a lone
    #: `.kicad_mod` is on nothing yet, and so is an unconnected one. `""`
    #: then. `tools/import_board.py` names a `.kicad_pcb`'s pads by it.
    net: str = ""
    #: `(property pad_prop_castellated)`: KiCad's flag for a plated half-hole
    #: cut by the board's edge, as against the whole hole beside it.
    castellated: bool = False

    @property
    def front(self) -> bool:
        return bool({"F.Cu", "*.Cu", "F&B.Cu"} & set(self.layers))

    @property
    def back(self) -> bool:
        return bool({"B.Cu", "*.Cu", "F&B.Cu"} & set(self.layers))


@dataclasses.dataclass(frozen=True)
class Segment:
    """A drawn line, in millimetres, on one layer."""

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float


@dataclasses.dataclass(frozen=True)
class Stroke:
    """A drawn line WITH the width it was drawn at, in board millimetres.

    Separate from `Segment` rather than a width added to it, because the two
    answer different questions. A `Segment` on `Edge.Cuts` is a boundary: it
    has a position and its width is meaningless, and every consumer of the
    outline chains segments end to end where a width would be noise. A stroke
    on the silkscreen is INK: it covers area, and the width is most of what
    makes it visible. The vendors bear this out -- Seeed draw their board-level
    silk at 0.152 mm and some of their footprint silk at 0.010, which is a
    hairline nobody can see and which a widthless reader would have drawn at
    the same weight as the rest.
    """

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float


@dataclasses.dataclass(frozen=True)
class Via:
    """A plated hole joining layers, at its finished outside diameter.

    Drawn because a board has 82 to 307 of them and a tented one is a visible
    bump in the soldermask. The DRILL is not carried: a via on these boards is
    covered, so what shows is the annular ring and not the hole.
    """

    x_mm: float
    y_mm: float
    diameter_mm: float


#: The two copper layers anything can see. A four- or six-layer board's inner
#: copper is inside the laminate, so it is counted and not drawn -- the RP2350
#: routes 149 segments on In2 through In4 and the nRF54L15 381, none of which
#: is visible from either side.
OUTER_COPPER = ("F.Cu", "B.Cu")


@dataclasses.dataclass(frozen=True)
class Footprint:
    name: str
    pads: tuple[Pad, ...]
    segments: tuple[Segment, ...]

    def pads_of(self, kind: str) -> tuple[Pad, ...]:
        return tuple(p for p in self.pads if p.kind == kind)

    def extent_mm(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) over pads and drawn segments."""
        xs: list[float] = []
        ys: list[float] = []
        for pad in self.pads:
            xs += [pad.x_mm - pad.width_mm / 2, pad.x_mm + pad.width_mm / 2]
            ys += [pad.y_mm - pad.height_mm / 2, pad.y_mm + pad.height_mm / 2]
        for seg in self.segments:
            xs += [seg.x1_mm, seg.x2_mm]
            ys += [seg.y1_mm, seg.y2_mm]
        if not xs:
            raise KicadError(f"{self.name}: footprint has no pads and no graphics")
        return min(xs), min(ys), max(xs), max(ys)


def _pads_of(tree: list) -> list[Pad]:
    """Every `(pad ...)` directly under a footprint node.

    Shared by `read_footprint` and `read_board`: a footprint inside a
    `.kicad_pcb` is the same node as the one a `.kicad_mod` holds alone, and
    reading it twice in two places is two things to fix when the format moves.
    """
    pads: list[Pad] = []
    for node in children(tree, "pad"):
        # (pad "1" smd roundrect (at x y [rot]) (size w h) ...)
        if len(node) < 4:
            continue
        number, kind = node[1], node[2]
        at, size = first(node, "at"), first(node, "size")
        if at is None or size is None:
            continue
        coords, dims = _floats(at), _floats(size)
        if len(coords) < 2 or len(dims) < 2:
            continue
        where = first(node, "layers")
        # `(net 29 "/GPIO-14")` or `(net "GND")`: with the net's number or
        # without it, and the name last in both.
        net = first(node, "net")
        pads.append(Pad(
            number, kind, coords[0], coords[1], dims[0], dims[1],
            shape=node[3] if isinstance(node[3], str) else "",
            # Absent means zero, which is why this reads the length rather
            # than indexing and hoping -- the same care `read_board` takes
            # over a footprint's own optional rotation.
            rotation_deg=coords[2] if len(coords) > 2 else 0.0,
            layers=tuple(x for x in (where or [])[1:] if isinstance(x, str)),
            net=net[-1] if net is not None and len(net) > 1 and isinstance(net[-1], str) else "",
            castellated=any(prop[1:] == ["pad_prop_castellated"]
                            for prop in children(node, "property")),
        ))
    return pads


def read_footprint(path: pathlib.Path) -> Footprint:
    """Read one `.kicad_mod`."""
    tree = parse_sexp(path.read_text(encoding="utf-8"))
    if head(tree) != "footprint":
        raise KicadError(f"{path}: not a footprint (root is {head(tree)!r})")
    name = tree[1] if len(tree) > 1 and isinstance(tree[1], str) else path.stem

    pads = _pads_of(tree)

    segments: list[Segment] = []
    for node in children(tree, "fp_line"):
        start, end, layer = first(node, "start"), first(node, "end"), first(node, "layer")
        if start is None or end is None:
            continue
        a, b = _floats(start), _floats(end)
        if len(a) < 2 or len(b) < 2:
            continue
        segments.append(
            Segment(layer[1] if layer and len(layer) > 1 else "", a[0], a[1], b[0], b[1])
        )
    # A rectangle is four segments; expanding it here keeps every consumer
    # working in one primitive instead of four.
    for node in children(tree, "fp_rect"):
        start, end, layer = first(node, "start"), first(node, "end"), first(node, "layer")
        if start is None or end is None:
            continue
        a, b = _floats(start), _floats(end)
        if len(a) < 2 or len(b) < 2:
            continue
        name_ = layer[1] if layer and len(layer) > 1 else ""
        x1, y1, x2, y2 = a[0], a[1], b[0], b[1]
        segments += [
            Segment(name_, x1, y1, x2, y1),
            Segment(name_, x2, y1, x2, y2),
            Segment(name_, x2, y2, x1, y2),
            Segment(name_, x1, y2, x1, y1),
        ]

    if not pads:
        raise KicadError(f"{path}: no pads found; refusing to report an empty footprint")
    return Footprint(name, tuple(pads), tuple(segments))


# --- boards --------------------------------------------------------------------
#
# **A `.kicad_pcb` is the same source class as Arduino's EAGLE `.brd`**, which
# `tools/compose_board_3d.py` already stands component meshes on to build the
# Uno. OH-93's survey found Seeed publishes one for six of the eight chips this
# repository still draws as an extruded slab -- on the wiki, which is why the
# GitHub census in `docs/research/board-sources/` says they publish no PCB.
#
# **What a board file gives, and what it does not.** Present: the outline on
# `Edge.Cuts`, and every component's footprint name, position, rotation and
# side, authored by the people who made the board.
#
# **`(model ...)` blocks are present on four boards of the five and this said
# they were absent**, which was true of the ESP32-C3 -- the board the pipeline
# was built on, and the only one that carries none. Corrected 2026-08-30 by
# OH-98, which counted 59, 57, 91 and 83 of them on the C6, RP2350, C5 and
# nRF54L15. `_models_of` reads them.
#
# **Reading them changes almost nothing, which is the surprise.** Counted
# across all five boards, by (board, package) pair: 17 name a model that can
# actually be fetched, and all 17 agree with the correspondence
# `compose_board_3d` had already derived by measurement. 43 more state nothing
# usable -- silent, or naming Seeed's own unpublished `${AMZPATH}`. And the
# single disagreement is one where the VENDOR is wrong: the C6 states
# `USB_C_Receptacle_GCT_USB4105-xx-A_16P`, which is 7.78 mm deep where the
# same footprint's own `Description` says 7.3.
#
# So a placement still names a FOOTPRINT rather than a mesh in the cases that
# matter, and the step from one to the other is still a judgement confirmed
# against pad geometry. See OH-93 and OH-98.
#
# **An outline is not necessarily drawn on the board.** A footprint may carry
# `Edge.Cuts` graphics too, and KiCad mills those exactly as it mills the
# board's own -- so "the outline" is both, and where the vendor happened to
# draw it is the incidental detail this module exists to hide.
#
# Four of Seeed's six projects do it that way and it is not a corner case:
# their `MOUDLE14P-XIAO-HALF-HOLE` footprint IS the XIAO outline, 4 `fp_line`
# and 4 `fp_arc` spanning 20.955 x 17.780 mm, and every board that uses it
# leaves only the two routed slots at the top level. Reading the top level
# alone measured the ESP32-C6 as **1.270 x 12.954 mm** -- the slots, and
# nothing else. That is a plausible-looking board rather than an error, which
# is what makes it worth the paragraph: the XIAO ESP32-C3 draws its whole
# silhouette at the top level, so the first board read this way was the one
# that hid the difference.


@dataclasses.dataclass(frozen=True)
class Arc:
    """A drawn arc, as the three points KiCad stores rather than a centre.

    `mid` is a point ON the curve, not the centre of it. Reading it as a centre
    puts every rounded corner of a board in the wrong place by roughly the
    corner radius, and the result still looks like a board.
    """

    layer: str
    x1_mm: float
    y1_mm: float
    xm_mm: float
    ym_mm: float
    x2_mm: float
    y2_mm: float
    #: The width it was drawn at, for an arc that is a length of TRACK. Zero
    #: on an outline arc, where a width means nothing -- `Edge.Cuts` is a
    #: boundary and every consumer of it chains endpoints. Defaulted rather
    #: than split into a second type, because the flattening is the hard part
    #: and it is identical: `compose_board_3d.arc_points` solves for the
    #: centre from the three stored points and knows nothing about widths.
    width_mm: float = 0.0


@dataclasses.dataclass(frozen=True)
class StatedModel:
    """One `(model ...)` block: a mesh the footprint says it is.

    **Evidence, not proof**, and OH-98 is the ticket that measured how it can
    be wrong on the four files already here: most name a library the vendor
    does not publish, one names a file KiCad's library does not hold, one
    gives a resistor's mesh to a diode, and one carries five whole-XIAO
    alternates of which the wrong one is the visible one. So this reports what
    the file says and decides nothing; `compose_board_3d` is where a statement
    is weighed against the pads.
    """

    path: str
    #: `(hide yes)`. KiCad's own way of saying "an alternate, not this part".
    hidden: bool = False
    #: `(offset ...)`, `(rotate ...)` and `(scale ...)`, in the block's own
    #: order and units -- millimetres and degrees. Carried rather than applied,
    #: because a reader that dropped them would place a correct mesh wrongly
    #: and look like a rendering bug.
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def variable(self) -> str:
        """The `${...}` the path begins with, or `""`.

        **This is the one guard that matters and it is why it has a name.**
        `${KICAD7_3DMODEL_DIR}` is KiCad's own published library and can be
        fetched; `${AMZPATH}` is Seeed's own and is not shipped anywhere. The
        `MOUDLE14P-XIAO-HALF-HOLE` footprint carries five whole-XIAO
        alternates under `${AMZPATH}` and the one that is NOT `(hide yes)` is
        `Seeeduino XIAO SAMD21 v4.step` -- so a reader that trusted the hide
        flag alone would stand a complete SAMD21 board on top of an RP2350.
        """
        if not self.path.startswith("${"):
            return ""
        return self.path[2:self.path.index("}")] if "}" in self.path else ""


@dataclasses.dataclass(frozen=True)
class Placement:
    """One component on a board: which footprint, where, and which way up."""

    library: str          #: `"XIAO ESP32C3_v1.3:C0201"` -- library and name
    reference: str        #: `"C1"`, or `""` where the file gives none
    x_mm: float
    y_mm: float
    rotation_deg: float
    back: bool            #: on the underside, so its footprint is mirrored
    pads: tuple[Pad, ...]  #: in the FOOTPRINT's own space, before placement
    #: `(min_x, min_y, max_x, max_y)` of the part's BODY, in the footprint's
    #: own local millimetres and KiCad's own y-down frame, or `None` where it
    #: draws none.
    #:
    #: **From `*.Fab`, which is KiCad's assembly layer and not its
    #: silkscreen.** The distinction is the point: silkscreen is ink printed
    #: on the board near a part, placed wherever it is legible, while `F.Fab`
    #: is the drawing of where the part's own body sits. EAGLE has no such
    #: separation, so `tools/eagle.py` reads layers 21 and 51 and gets the
    #: body among other things; here the right layer exists and is named.
    #:
    #: The pads say where the PINS are and this says where the BODY is, which
    #: is a different fact and the only one that pins down which way a part
    #: faces -- see `compose_board_3d.silk_miss`, which is blind without it.
    body: tuple[float, float, float, float] | None = None
    #: Where the footprint draws its PIN-1 MARKER, in the same local frame as
    #: `body`, or `None` where it draws none.
    #:
    #: **`body` says where the part sits and this says which way round it
    #: is.** A body outline is symmetric on most packages, so comparing one
    #: against a placed model survives a half turn; the marker is the one
    #: feature on the drawing that does not. See `_mark_of`.
    mark: tuple[float, float] | None = None
    #: Every `(model ...)` the footprint carries, hidden ones included.
    #:
    #: **Hidden ones are kept rather than filtered here** because which of
    #: five alternates a vendor left visible is itself a fact worth reporting,
    #: and a reader that never saw them could not say "four are hidden and the
    #: fifth is a whole different board". See `StatedModel`.
    models: tuple[StatedModel, ...] = ()

    @property
    def name(self) -> str:
        """The footprint's own name, without the library that holds it."""
        return self.library.split(":", 1)[-1]


@dataclasses.dataclass(frozen=True)
class Board:
    """One `.kicad_pcb`: its outline, and everything standing on it."""

    name: str
    outline: tuple[Segment, ...]
    arcs: tuple[Arc, ...]
    placements: tuple[Placement, ...]
    #: The ink the vendor prints on the board, front and back, in board
    #: millimetres -- both the board's own `gr_line`s and every footprint's.
    #: Empty until OH-110; a composed board drew none of it and looked like a
    #: slab with boxes on it beside a vendor's own assembly export.
    silk: tuple[Stroke, ...] = ()
    #: What was on those layers and is NOT in `silk`, counted by kind. A
    #: caption that says "232 strokes" while dropping 99 texts is worse than
    #: one that says both.
    silk_unread: tuple[tuple[str, int], ...] = ()
    #: The routed copper on the two OUTER layers, in board millimetres. Inner
    #: layers are inside the board and nothing can see them, so they are
    #: counted in `traces_unread` rather than carried.
    traces: tuple[Stroke, ...] = ()
    #: Track laid as a curve. Kept as arcs because flattening one needs the
    #: centre solved from three points, and `compose_board_3d.arc_points`
    #: already does that for the outline.
    trace_arcs: tuple[Arc, ...] = ()
    vias: tuple[Via, ...] = ()
    #: Copper that is not drawn, counted by why. Inner layers, and the filled
    #: polygons of a zone -- see `compose_board_3d.artwork` for why a pour is
    #: not attempted.
    traces_unread: tuple[tuple[str, int], ...] = ()

    def extent_mm(self) -> tuple[float, float, float, float]:
        """`(min_x, min_y, max_x, max_y)` of the outline, in millimetres.

        Arcs contribute all three of their points. For an arc of a quarter turn
        or less -- which is what a board's rounded corner is -- the extremes in
        x and y are among those three, so this is exact for the shape it is
        used on and an under-estimate for a half-turn arc no board outline has.
        A tighter bound would need the arc's centre, which KiCad does not store
        and which would have to be solved for from the three points.
        """
        xs: list[float] = []
        ys: list[float] = []
        for seg in self.outline:
            xs += [seg.x1_mm, seg.x2_mm]
            ys += [seg.y1_mm, seg.y2_mm]
        for arc in self.arcs:
            xs += [arc.x1_mm, arc.xm_mm, arc.x2_mm]
            ys += [arc.y1_mm, arc.ym_mm, arc.y2_mm]
        if not xs:
            raise KicadError(f"{self.name}: no Edge.Cuts graphics, so the board "
                             f"has no outline to measure")
        return min(xs), min(ys), max(xs), max(ys)

    def size_mm(self) -> tuple[float, float]:
        """Width and height of the outline."""
        left, bottom, right, top = self.extent_mm()
        return right - left, top - bottom


def _reference_of(node: list) -> str:
    """A footprint's reference designator, from either place it can live.

    KiCad 7 moved it from `(fp_text reference "C1" ...)` into
    `(property "Reference" "C1" ...)`, and files of both vintages are in the
    wild -- Seeed's six projects span generator versions. Reading only the new
    form returns "" for every part of an older board, which is not an error
    anywhere and quietly makes the alignment report unreadable.
    """
    for prop in children(node, "property"):
        if len(prop) > 2 and prop[1] == "Reference" and isinstance(prop[2], str):
            return prop[2]
    for text in children(node, "fp_text"):
        if len(text) > 2 and text[1] == "reference" and isinstance(text[2], str):
            return text[2]
    return ""


def _graphic(node: list, tag: str) -> tuple[str, list[float]] | None:
    """`(layer, floats)` for a `(start ...)`/`(end ...)` pair, or None."""
    layer = first(node, "layer")
    start, end = first(node, tag), first(node, "end")
    if start is None or end is None:
        return None
    a, b = _floats(start), _floats(end)
    if len(a) < 2 or len(b) < 2:
        return None
    return (layer[1] if layer and len(layer) > 1 else ""), [a[0], a[1], b[0], b[1]]


def _on_board(placed: Placement, x_mm: float, y_mm: float) -> tuple[float, float]:
    """A footprint-local point in the BOARD's millimetres, KiCad's own frame.

    **This is the same transform `compose_board_3d.from_kicad` applies to
    pads**, written in the other frame: that one converts to Y-up on the way
    in, this one stays in KiCad's Y-down storage frame because that is the
    frame `gr_line` coordinates are already in, and these two have to end up
    in one tuple. Derived from that function rather than from first
    principles, which is why the signs read backwards from the usual rotation:
    a rotation that is counter-clockwise as DRAWN is clockwise in a frame
    whose y runs down the page.
    """
    turn = math.radians(placed.rotation_deg)
    cos, sin = math.cos(turn), math.sin(turn)
    if placed.back:
        # A part on the underside is mirrored across the footprint's own y
        # axis before it is turned, as `compose_board_3d.from_kicad` mirrors
        # its pads. **`pad_on_board` does not mirror a pad**, and the copper
        # says it is right not to. Whether a footprint's graphics are stored
        # already flipped as its pads are is not settled here; OH-182's note
        # records what dropping this mirror would change.
        x_mm = -x_mm
    return (placed.x_mm + x_mm * cos + y_mm * sin,
            placed.y_mm - x_mm * sin + y_mm * cos)


def pad_on_board(placed: Placement, pad: Pad) -> tuple[float, float]:
    """A placed footprint's pad centre in the BOARD's millimetres, KiCad's own frame.

    **Turned and moved, never mirrored, on either side of the board.** When
    KiCad flips a footprint onto the back it flips the pads' own offsets and
    stores them flipped, so mirroring them again as `_on_board` mirrors a
    graphic puts every pad off the footprint's centre line on the wrong side
    of it. The copper is what settles it: a track ends on the pad it
    connects, and `test_a_back_side_headers_pads_sit_on_their_own_nets_copper`
    finds each of the Olimex ESP32-PoE's two back-side headers on its copper
    only this way.
    """
    turn = math.radians(placed.rotation_deg)
    cos, sin = math.cos(turn), math.sin(turn)
    return (placed.x_mm + pad.x_mm * cos + pad.y_mm * sin,
            placed.y_mm - pad.x_mm * sin + pad.y_mm * cos)


def _fp_graphics(node: list, layer: str, placed: Placement
                 ) -> tuple[list[Segment], list[Arc]]:
    """One footprint's `layer` graphics, in board coordinates.

    `fp_rect` is expanded into four segments here for the same reason
    `read_footprint` and `read_board` expand their own rects: every consumer
    then works in one primitive. No vendor board here draws an edge that way
    today -- what would be surprising is a rect on the outline layer silently
    contributing nothing while the identical `gr_rect` beside it does.
    """
    segments: list[Segment] = []
    arcs: list[Arc] = []

    def put(x_mm: float, y_mm: float) -> tuple[float, float]:
        return _on_board(placed, x_mm, y_mm)

    for line in children(node, "fp_line"):
        got = _graphic(line, "start")
        if not got or got[0] != layer:
            continue
        x1, y1, x2, y2 = got[1]
        segments.append(Segment(layer, *put(x1, y1), *put(x2, y2)))
    for rect in children(node, "fp_rect"):
        got = _graphic(rect, "start")
        if not got or got[0] != layer:
            continue
        x1, y1, x2, y2 = got[1]
        corners = [put(x1, y1), put(x2, y1), put(x2, y2), put(x1, y2)]
        for start, end in zip(corners, corners[1:] + corners[:1]):
            segments.append(Segment(layer, *start, *end))
    for arc in children(node, "fp_arc"):
        where = first(arc, "layer")
        if not (where and len(where) > 1 and where[1] == layer):
            continue
        start, mid, end = first(arc, "start"), first(arc, "mid"), first(arc, "end")
        if start is None or mid is None or end is None:
            continue
        a, m, b = _floats(start), _floats(mid), _floats(end)
        if min(len(a), len(m), len(b)) < 2:
            continue
        arcs.append(Arc(layer, *put(a[0], a[1]), *put(m[0], m[1]), *put(b[0], b[1])))
    return segments, arcs


#: Everything a vendor draws on the silkscreen that `_silk_of` does not read,
#: named so that "232 strokes" is never quietly also saying "and 99 pieces of
#: text you cannot see". Counted and reported rather than dropped.
#:
#: Text is the big one and it needs a font -- KiCad stores `gr_text` as a
#: string and a size, and turning that into geometry means shipping glyph
#: outlines. The rest is a handful per board: 2 to 16 arcs, 2 to 7 circles and
#: 3 to 12 polygons across the five composed XIAOs, against 47 to 232 lines.
SILK_UNREAD = ("text", "arc", "circle", "poly", "curve", "bbox")


def _silk_of(node: list, prefix: str, put) -> tuple[list[Stroke], list[str]]:
    """Silkscreen lines under `node`, in board millimetres, and what was not.

    `prefix` is `"gr"` at the top level of a board and `"fp"` inside a
    footprint, and `put` is the transform into board space -- the identity for
    the first and `_on_board` for the second. One reader for both, because the
    two differ in exactly those two things and in nothing else; a footprint's
    silkscreen and a board's are the same ink on the same layer.
    """
    strokes: list[Stroke] = []
    unread: list[str] = []
    for child in node:
        if not isinstance(child, list):
            continue
        tag = head(child)
        if not tag.startswith(f"{prefix}_"):
            continue
        kind = tag[len(prefix) + 1:]
        layer = first(child, "layer")
        named = layer[1] if layer and len(layer) > 1 else ""
        if not str(named).endswith("SilkS"):
            continue
        if kind in SILK_UNREAD:
            unread.append(kind)
            continue
        if kind == "line":
            got = _graphic(child, "start")
            if got is None:
                continue
            x1, y1, x2, y2 = got[1]
            strokes.append(Stroke(named, *put(x1, y1), *put(x2, y2),
                                  _stroke_width(child)))
        elif kind == "rect":
            got = _graphic(child, "start")
            if got is None:
                continue
            x1, y1, x2, y2 = got[1]
            width = _stroke_width(child)
            corners = [put(x1, y1), put(x2, y1), put(x2, y2), put(x1, y2)]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                strokes.append(Stroke(named, *start, *end, width))
        else:
            unread.append(kind)
    return strokes, unread


def _routing_of(tree: list) -> tuple[list[Stroke], list[Arc], list[Via],
                                     collections.Counter]:
    """Every length of track, curve and via on the two outer copper layers.

    **Track is not graphics and it is not read with the graphics.** A
    `segment` carries a net and a width and no layer of drawing intent; it
    lives at the top level of the board beside `via` and `zone`, not inside a
    footprint. Reading it here rather than through `_silk_of` keeps that
    difference visible, and the two want different things anyway: a stroke on
    the silkscreen is ink and a segment is metal under it.

    A `zone` is counted and never read. Its `filled_polygon` is a keyhole
    outline that walks into every thermal relief and back out again -- 26,368
    points across the RP2350's 95 of them -- and ear-clipping a polygon with
    coincident edges is a different problem from ear-clipping a board.
    """
    strokes: list[Stroke] = []
    arcs: list[Arc] = []
    vias: list[Via] = []
    unread: collections.Counter = collections.Counter()

    for node in tree:
        if not isinstance(node, list):
            continue
        tag = head(node)
        if tag == "via":
            at, size = first(node, "at"), first(node, "size")
            if at is None or size is None:
                continue
            where, across = _floats(at), _floats(size)
            if len(where) >= 2 and across:
                vias.append(Via(where[0], where[1], across[0]))
            continue
        if tag not in ("segment", "arc"):
            if tag == "zone":
                unread["zone"] += 1
            continue
        layer = first(node, "layer")
        named = layer[1] if layer and len(layer) > 1 else ""
        if named not in OUTER_COPPER:
            unread[str(named) or "no layer"] += 1
            continue
        width = _stroke_width(node)
        if tag == "segment":
            got = _graphic(node, "start")
            if got is None:
                continue
            strokes.append(Stroke(named, *got[1], width))
            continue
        start, mid, end = first(node, "start"), first(node, "mid"), first(node, "end")
        if start is None or mid is None or end is None:
            continue
        a, m, b = _floats(start), _floats(mid), _floats(end)
        if min(len(a), len(m), len(b)) >= 2:
            arcs.append(Arc(named, a[0], a[1], m[0], m[1], b[0], b[1], width))
    return strokes, arcs, vias, unread


def _stroke_width(node: list) -> float:
    """The width a graphic was drawn at, from either place KiCad puts it.

    Modern files nest it as `(stroke (width w) (type solid))` and older ones
    write `(width w)` directly. Both spellings appear across the five vendor
    boards here, so reading only one of them silently gives every stroke on
    some boards a width of zero.
    """
    stroke = first(node, "stroke")
    width = first(stroke, "width") if stroke is not None else first(node, "width")
    if width is not None and len(width) > 1:
        try:
            return float(width[1])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _body_of(node: list) -> tuple[float, float, float, float] | None:
    """The footprint's body outline from its `*.Fab` layer, or None.

    `F.Fab` on the front and `B.Fab` on the back, matched by suffix rather
    than by name: a part is drawn on the assembly layer of the side it is
    mounted on, and which side that is has already been decided by the
    placement's own `layer`.

    **A closed outline wins over loose lines, and that is not a tidy-up.**
    Seeed's `USB2.0-TYPE-C` draws its 7.341 x 8.992 mm body as an `fp_rect`
    AND four `fp_line`s forming a 1.651 x 12.5 mm box behind it -- the
    keep-out a cable needs, which is not the part. Taking everything on the
    layer unioned the two and reported a 12.5 mm body, which is what let a
    connector sit a quarter turn out with every check agreeing (OH-105). The
    RP2350 draws only the rectangle, and its number was the right one all
    along; that disagreement between two boards using the same footprint is
    what gave this away.

    So: a body is a SHAPE. Lines are read only where a footprint draws no
    closed one, which is the case for a chamfered outline drawn edge by edge.

    **Text is not read** either, for the reason `eagle._silk_extent` gives: a
    reference designator is placed wherever it is legible, as often beside a
    part as on it, and including one would make a 1 mm capacitor measure five.

    **`*.SilkS` is read only where `*.Fab` draws nothing** (OH-124). Seeed's
    QFN32G -- the C3's and the C6's own processor -- draws its whole body on
    the silkscreen and nothing on Fab at all, and a body of None disabled
    the silk-extent check AND the mark check: the two most prominent parts
    on those boards had no turn check of any kind. On silk the preference
    INVERTS: lines win over closed shapes, because a silk `fp_poly` in these
    libraries is a POLARITY MARK (the C3's D1, its U.FL antennas), and a
    0.3 mm marker triangle taken as the body would misstate the extent every
    offset is divided by. The failure mode left is safe by construction: a
    body that IS the marker puts the mark at its own centre, and
    `MARK_OFFSET_FRACTION` rejects a centred mark rather than calling a turn
    off it. Courtyard, paste and adhesive layers are never read.
    """
    def closed_points(suffix: str) -> tuple[list[float], list[float]]:
        xs: list[float] = []
        ys: list[float] = []
        for graphic in children(node, "fp_rect"):
            got = _graphic(graphic, "start")
            if got and got[0].endswith(suffix):
                xs += [got[1][0], got[1][2]]
                ys += [got[1][1], got[1][3]]
        for graphic in children(node, "fp_poly"):
            where = first(graphic, "layer")
            if not (where and len(where) > 1 and str(where[1]).endswith(suffix)):
                continue
            points = first(graphic, "pts")
            for point in children(points or [], "xy"):
                coords = _floats(point)
                if len(coords) >= 2:
                    xs.append(coords[0])
                    ys.append(coords[1])
        return xs, ys

    def line_points(suffix: str) -> tuple[list[float], list[float]]:
        xs: list[float] = []
        ys: list[float] = []
        for graphic in children(node, "fp_line"):
            got = _graphic(graphic, "start")
            if got and got[0].endswith(suffix):
                xs += [got[1][0], got[1][2]]
                ys += [got[1][1], got[1][3]]
        return xs, ys

    for suffix, preference in ((".Fab", (closed_points, line_points)),
                               (".SilkS", (line_points, closed_points))):
        for gather in preference:
            xs, ys = gather(suffix)
            if xs:
                return (min(xs), min(ys), max(xs), max(ys))
    return None


def _mark_of(node: list) -> tuple[float, float] | None:
    """The footprint's pin-1 marker from its `*.Fab` layer, or None.

    **`*.Fab` and an `fp_circle`, which is where KiCad puts a pin-1 dot.**
    `tools/model_from_datasheet.py` already reads exactly this shape off
    Seeed's own footprints to decide which corner of a modelled QFN is pin 1,
    and OH-100's test asserts that circle sits in pad 1's quadrant. This makes
    the same reading available to every placement rather than to one part.

    The assembly layer AHEAD of the silkscreen, for the reason `_body_of`
    gives at length: silkscreen goes wherever it is legible and `*.Fab` is
    the drawing of the part itself. The centroid of what was read is
    returned, and the caller decides whether it is off-centre enough to be a
    marker at all -- see `compose_board_3d.MARK_OFFSET_FRACTION`.

    **The vendors used five spellings and this read one** (OH-124). The
    survey dumped every "nothing here can see" placement: the C3's and C6's
    processors put the dot as an `fp_circle` on `F.SilkS`; the C3's SOT-25s
    as an `fp_poly` on `F.Fab`; its D1 and the U.FL antennas as `fp_poly` on
    `F.SilkS`; its charge LED as an `fp_arc` there. So each layer is read
    for circles first, then polys, then arcs -- a circle is the
    unambiguous dot, while a poly on Fab may equally be the body itself,
    whose centroid sits at the body centre and is REJECTED by the offset
    floor rather than mistaken for a corner mark -- and `*.SilkS` is
    consulted only where `*.Fab` yields nothing at all.
    """
    def on(shape: str, suffix: str):
        for graphic in children(node, shape):
            layer = first(graphic, "layer")
            if layer and len(layer) > 1 and str(layer[1]).endswith(suffix):
                yield graphic

    def circles(suffix: str) -> list[tuple[float, float]]:
        marks = []
        for circle in on("fp_circle", suffix):
            at = _floats(first(circle, "center") or [])
            if len(at) >= 2:
                marks.append((at[0], at[1]))
        return marks

    def polys(suffix: str) -> list[tuple[float, float]]:
        marks = []
        for poly in on("fp_poly", suffix):
            points = [_floats(point)
                      for point in children(first(poly, "pts") or [], "xy")]
            points = [c for c in points if len(c) >= 2]
            if points:
                marks.append((sum(c[0] for c in points) / len(points),
                              sum(c[1] for c in points) / len(points)))
        return marks

    def arcs(suffix: str) -> list[tuple[float, float]]:
        marks = []
        for arc in on("fp_arc", suffix):
            points = [_floats(first(arc, name) or [])
                      for name in ("start", "mid", "end")]
            points = [c for c in points if len(c) >= 2]
            if points:
                marks.append((sum(c[0] for c in points) / len(points),
                              sum(c[1] for c in points) / len(points)))
        return marks

    for suffix in (".Fab", ".SilkS"):
        for gather in (circles, polys, arcs):
            marks = gather(suffix)
            if marks:
                return (sum(m[0] for m in marks) / len(marks),
                        sum(m[1] for m in marks) / len(marks))
    return None


def _models_of(node: list) -> tuple[StatedModel, ...]:
    """Every `(model ...)` a footprint carries, in the file's own order.

    **Reported, not judged.** A block says a path, whether it is hidden, and
    the three transforms to apply; whether any of that is TRUE of the part is
    `compose_board_3d`'s question, and OH-98 records four separate ways these
    statements are wrong on the four files already on this disk.
    """
    def triple(name: str, fallback: tuple[float, float, float]):
        block = first(node_model, name)
        if block is None:
            return fallback
        xyz = _floats(first(block, "xyz") or [])
        return (xyz[0], xyz[1], xyz[2]) if len(xyz) >= 3 else fallback

    out: list[StatedModel] = []
    for node_model in children(node, "model"):
        if len(node_model) < 2:
            continue
        hide = first(node_model, "hide")
        out.append(StatedModel(
            path=str(node_model[1]),
            # `(hide yes)`. Anything else -- including its absence -- is
            # visible, which is the reading that keeps the SAMD21 alternate
            # dangerous rather than quietly safe.
            hidden=bool(hide and len(hide) > 1 and str(hide[1]) == "yes"),
            offset=triple("offset", (0.0, 0.0, 0.0)),
            rotate=triple("rotate", (0.0, 0.0, 0.0)),
            scale=triple("scale", (1.0, 1.0, 1.0)),
        ))
    return tuple(out)


def read_board(path: pathlib.Path, layer: str = "Edge.Cuts") -> Board:
    """Read one `.kicad_pcb`: the board outline and every placement on it.

    `layer` is which layer carries the outline, and it is a parameter because
    it is the one thing here a vendor can reasonably disagree about -- not
    because anything today passes something else.
    """
    tree = parse_sexp(path.read_text(encoding="utf-8"))
    if head(tree) != "kicad_pcb":
        raise KicadError(f"{path}: not a board (root is {head(tree)!r})")

    outline: list[Segment] = []
    for node in children(tree, "gr_line"):
        got = _graphic(node, "start")
        if got and got[0] == layer:
            outline.append(Segment(got[0], *got[1]))
    # A rectangle is four segments, expanded here so every consumer works in
    # one primitive -- the same choice `read_footprint` makes for `fp_rect`.
    for node in children(tree, "gr_rect"):
        got = _graphic(node, "start")
        if not got or got[0] != layer:
            continue
        x1, y1, x2, y2 = got[1]
        outline += [
            Segment(layer, x1, y1, x2, y1), Segment(layer, x2, y1, x2, y2),
            Segment(layer, x2, y2, x1, y2), Segment(layer, x1, y2, x1, y1),
        ]

    arcs: list[Arc] = []
    for node in children(tree, "gr_arc"):
        where = first(node, "layer")
        if not (where and len(where) > 1 and where[1] == layer):
            continue
        start, mid, end = first(node, "start"), first(node, "mid"), first(node, "end")
        if start is None or mid is None or end is None:
            continue
        a, m, b = _floats(start), _floats(mid), _floats(end)
        if min(len(a), len(m), len(b)) < 2:
            continue
        arcs.append(Arc(layer, a[0], a[1], m[0], m[1], b[0], b[1]))

    silk, unread = _silk_of(tree, "gr", lambda x, y: (x, y))

    placements: list[Placement] = []
    for node in children(tree, "footprint"):
        library = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        at = first(node, "at")
        if at is None:
            continue
        coords = _floats(at)
        if len(coords) < 2:
            continue
        side = first(node, "layer")
        placed = Placement(
            library=library,
            reference=_reference_of(node),
            x_mm=coords[0],
            y_mm=coords[1],
            # Rotation is optional and absent means zero, which is why this
            # reads the length rather than indexing and hoping.
            rotation_deg=coords[2] if len(coords) > 2 else 0.0,
            back=bool(side and len(side) > 1 and str(side[1]).startswith("B.")),
            pads=tuple(_pads_of(node)),
            body=_body_of(node),
            mark=_mark_of(node),
            models=_models_of(node),
        )
        placements.append(placed)
        drawn, curved = _fp_graphics(node, layer, placed)
        outline += drawn
        arcs += curved
        printed, missed = _silk_of(
            node, "fp", lambda x, y, at=placed: _on_board(at, x, y))
        silk += printed
        unread += missed

    if not placements and children(tree, "module"):
        # KiCad 5 called a placed part `(module ...)`, and nothing here has
        # been checked against that format, so it is refused by name rather
        # than read as though it were a footprint.
        raise KicadError(
            f"{path}: places {len(children(tree, 'module'))} parts as (module "
            f"...), which is KiCad 5's format; KiCad 5 format (module) is not "
            f"read. KiCad 6 or later writes (footprint ...)"
        )
    if not placements:
        raise KicadError(f"{path}: no footprints; refusing to report an empty board")
    if not outline and not arcs:
        raise KicadError(f"{path}: nothing on {layer}, so there is no outline. "
                         f"A board drawn without one would be a bounding box "
                         f"around its parts, which is not its shape")
    tracks, curves, vias, skipped = _routing_of(tree)
    return Board(path.stem, tuple(outline), tuple(arcs), tuple(placements),
                 silk=tuple(silk),
                 silk_unread=tuple(sorted(collections.Counter(unread).items())),
                 traces=tuple(tracks), trace_arcs=tuple(curves),
                 vias=tuple(vias),
                 traces_unread=tuple(sorted(skipped.items())))


# --- symbol libraries ----------------------------------------------------------


def _symbol_roots(tree: list) -> list[str]:
    return [s[1] for s in children(tree, "symbol") if len(s) > 1 and isinstance(s[1], str)]


def read_symbol_pins(path: pathlib.Path, root: str) -> dict[str, str]:
    """Map pad number to pin name for one symbol in a `.kicad_sym`.

    KiCad splits a symbol into unit sub-symbols named `<root>_1_1`, `<root>_0_1`
    and so on, and the pins live in the sub-symbols rather than the root. Both
    are searched, and the pins of every unit are merged: a two-unit part would
    otherwise report half its pins with no indication that it had done so.
    """
    tree = parse_sexp(path.read_text(encoding="utf-8"))
    if head(tree) != "kicad_symbol_lib":
        raise KicadError(f"{path}: not a symbol library (root is {head(tree)!r})")

    wanted = [
        s
        for s in children(tree, "symbol")
        if len(s) > 1 and isinstance(s[1], str) and s[1].split("_1_")[0].split("_0_")[0] == root
    ]
    if not wanted:
        available = sorted({r.split("_1_")[0].split("_0_")[0] for r in _symbol_roots(tree)})
        raise KicadError(f"{path}: no symbol {root!r}. Available: {available}")

    pins: dict[str, str] = {}
    for symbol in wanted:
        for unit in [symbol, *children(symbol, "symbol")]:
            for pin in children(unit, "pin"):
                name_node, number_node = first(pin, "name"), first(pin, "number")
                if name_node is None or number_node is None:
                    continue
                if len(name_node) > 1 and len(number_node) > 1:
                    pins[number_node[1]] = name_node[1]
    if not pins:
        raise KicadError(f"{path}: symbol {root!r} declares no pins")
    return pins


def symbol_roots(path: pathlib.Path) -> list[str]:
    """Every distinct symbol root in a library, sorted."""
    tree = parse_sexp(path.read_text(encoding="utf-8"))
    roots = {r.split("_1_")[0].split("_0_")[0] for r in _symbol_roots(tree)}
    return sorted(roots)
