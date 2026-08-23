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
(`tools/get_seeed_hardware.sh`). This module reads it.

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


def read_footprint(path: pathlib.Path) -> Footprint:
    """Read one `.kicad_mod`."""
    tree = parse_sexp(path.read_text(encoding="utf-8"))
    if head(tree) != "footprint":
        raise KicadError(f"{path}: not a footprint (root is {head(tree)!r})")
    name = tree[1] if len(tree) > 1 and isinstance(tree[1], str) else path.stem

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
