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

import dataclasses
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
                out.append(tok[1:-1].replace('\\"', '"') if tok.startswith('"') else tok)
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


@dataclasses.dataclass(frozen=True)
class Segment:
    """A drawn line, in millimetres, on one layer."""

    layer: str
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float


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
        pads.append(Pad(number, kind, coords[0], coords[1], dims[0], dims[1]))
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
# side, authored by the people who made the board. Absent: `(model ...)`
# blocks -- Seeed strips them -- so a placement names a FOOTPRINT and not a
# mesh, and the step from one to the other is a judgement that has to be
# confirmed against pad geometry rather than trusted. See OH-93.


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
        placements.append(Placement(
            library=library,
            reference=_reference_of(node),
            x_mm=coords[0],
            y_mm=coords[1],
            # Rotation is optional and absent means zero, which is why this
            # reads the length rather than indexing and hoping.
            rotation_deg=coords[2] if len(coords) > 2 else 0.0,
            back=bool(side and len(side) > 1 and str(side[1]).startswith("B.")),
            pads=tuple(_pads_of(node)),
        ))

    if not placements:
        raise KicadError(f"{path}: no footprints; refusing to report an empty board")
    if not outline and not arcs:
        raise KicadError(f"{path}: nothing on {layer}, so there is no outline. "
                         f"A board drawn without one would be a bounding box "
                         f"around its parts, which is not its shape")
    return Board(path.stem, tuple(outline), tuple(arcs), tuple(placements))


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
