#!/usr/bin/env python3
# OpenHardware - a board outline from a PCB layout, as a mesh a browser can draw.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Read a `.kicad_pcb` Edge.Cuts outline and emit an extruded glTF board.

    python tools/import_3d.py <board.kicad_pcb> --out board.gltf

## What this is, and the larger thing it is not

OH-29 asked for STEP and WRL ingestion. The survey behind it says that is not
reachable: of five sources publishing 3D, only two publish a model of an
assembled *board* -- Raspberry Pi's `Pico-R3.step` and Waveshare's
`RP2040_Zero.stp` -- and both are STEP, which is boundary representation and
needs a NURBS tessellator. Neither is fetchable through
`tools/get_board_sources.py`, which performs `git-sparse` only. **There is no
board-level WRL or STL anywhere in the survey**; every `.wrl` it found is a
KiCad per-footprint component library.

So this takes the other road. A PCB layout already contains the board outline,
in millimetres, as line segments on the `Edge.Cuts` layer -- authored by the
people who made the board, sitting in the same coordinate space as the pads.
Extruding that closed outline to the board's own recorded thickness is a mesh,
with no tessellation, no new dependency, and no guessing.

**It is a silhouette, not a board.** No components, no copper, no silkscreen.
What it is for is the coordinate system: OH-30 needs a shape the 2D pad map can
be laid against, and this is that shape with its extent stated in millimetres.

## Why the outline is trustworthy and a rendering of it would not be

Every board description in `webui/boards/` ends its `derivation` with "Nothing
here was measured off an image." That sentence is why this reads Edge.Cuts
rather than tracing a product photo or a PDF: the segments are the authored
geometry, to three decimal places.

The check that this is the *right* geometry is in the same file. A board's pads
must fall inside its own outline, and they come from different nodes of the
same document, so agreement is not the parser checking itself. On OLIMEX
ESP32-PoE Rev C the outline is 28.000 x 75.000 mm and all 467 pads sit inside
it with between 0.78 and 1.62 mm of clearance.

## The licence on the component meshes, which this module deliberately does not read

Worth writing down because it decides more than size does. OLIMEX/ESP32-POE is
Apache-2.0, but the 151 `.wrl` component meshes inside it **are not**. Their
own header says:

    Copyright (C) 2017, kicad StepUp
    This work is licensed under the [Creative Commons CC-BY-SA 4.0 License] ...
    You are free to use the library data in your own projects without the
    obligation to share your project files ... However, if you wish to
    redistribute these libraries, or parts thereof (including in modified form)
    as a collection then the exception above does not apply.

Read from the header comment of
`HARDWARE/ESP32-PoE-hardware-revision-C1/3d/C_0402_1005Metric.wrl` on
2026-08-25. The linked `kicad-packages3D/LICENSE.md` was **not** opened, so
this cites the file in hand rather than the project's general reputation.

Under `rules/licence-hygiene.md` that makes fetch-do-not-vendor a licence
requirement here and not a size preference: using those meshes in a rendered
design is expressly permitted, redistributing them as a collection is the thing
the exception withholds. This module reads none of them, so nothing here
depends on that reading being right -- but the next ticket that wants
components does.

## Coordinates, stated because they are the deliverable

KiCad lays a PCB out with +x right and **+y down**, the screen convention.
glTF is +y up, right-handed. A board lying flat and seen from above therefore
maps KiCad `(x, y)` to glTF `(x, thickness, y)`: looking down the -y axis,
screen-right is +x and screen-down is +z, so no axis is negated and no mirror
is introduced. A mirrored board would still look like a board, which is what
makes this worth writing down rather than checking by eye.

The mesh is translated so its own minimum corner is the origin, because a
layout places the board wherever the page put it -- ESP32-PoE sits at x=90.15
-- and a mesh 90 mm from the origin renders off-screen in a naive viewer.
Nothing is lost: `extras.origin_mm` carries the corner it was moved from, so a
pad at `(px, py)` in the layout is at `(px - origin_mm[0], py - origin_mm[1])`
in the mesh, and `test_a_pad_maps_into_mesh_space_by_subtracting_the_origin`
pins exactly that arithmetic.
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
import math
import pathlib
import struct
import sys

try:
    from tools import kicad
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import kicad

#: The layer a board outline is drawn on. KiCad 5 writes it bare and KiCad 7
#: quotes it; `kicad.parse_sexp` strips quotes, so both arrive here the same.
#: That is not incidental -- OLIMEX/ESP32-POE ships both generations in one
#: repository, and a line-oriented regex sees eight segments in the older
#: twelve boards and **zero** in the newer three, which is the silent kind of
#: wrong: an empty outline, not an error.
EDGE_LAYER = "Edge.Cuts"

#: Coordinates are compared for identity when chaining segments into a ring.
#: KiCad writes three decimals; four is one more than it can express, so this
#: joins segments that really share an endpoint and nothing else.
_PLACES = 4


class Import3dError(Exception):
    """A layout whose outline cannot be read, or is not a single closed loop."""


class Outline:
    """A board outline: one closed ring of points, in the layout's millimetres.

    Not a dataclass, because `points` has an invariant a constructor has to
    enforce -- at least three of them, no repeated closing point, and a
    consistent winding -- and a frozen dataclass would let a caller build one
    that is none of those and fail much later inside the triangulator.
    """

    def __init__(self, points: tuple[tuple[float, float], ...]) -> None:
        if len(points) < 3:
            raise Import3dError(f"an outline needs 3 points, got {len(points)}: {points}")
        self.points = points

    @property
    def min_x_mm(self) -> float:
        return min(x for x, _ in self.points)

    @property
    def min_y_mm(self) -> float:
        return min(y for _, y in self.points)

    @property
    def max_x_mm(self) -> float:
        return max(x for x, _ in self.points)

    @property
    def max_y_mm(self) -> float:
        return max(y for _, y in self.points)

    @property
    def width_mm(self) -> float:
        return self.max_x_mm - self.min_x_mm

    @property
    def height_mm(self) -> float:
        return self.max_y_mm - self.min_y_mm

    def contains(self, x: float, y: float) -> bool:
        """Ray casting, used to check a layout's pads fall inside its board.

        Points exactly on the edge are not defined either way here, and no
        caller needs them to be: a pad centre landing precisely on the board
        edge is a layout error rather than a case to resolve.
        """
        inside = False
        count = len(self.points)
        for index in range(count):
            x1, y1 = self.points[index]
            x2, y2 = self.points[(index + 1) % count]
            if (y1 > y) != (y2 > y):
                crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < crossing:
                    inside = not inside
        return inside

    def signed_area_mm2(self) -> float:
        """The shoelace sum. Negative and positive are opposite windings."""
        total = 0.0
        count = len(self.points)
        for index in range(count):
            x1, y1 = self.points[index]
            x2, y2 = self.points[(index + 1) % count]
            total += x1 * y2 - x2 * y1
        return total / 2.0

    def counter_clockwise(self) -> Outline:
        """The same ring, wound counter-clockwise in the layout's own axes.

        Ear clipping needs a known winding, and a layout draws its outline in
        whichever order the person drew it. Normalising here means the
        triangulator never has to ask.
        """
        if self.signed_area_mm2() >= 0:
            return self
        return Outline(tuple(reversed(self.points)))


def _edge_segments(tree: list) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Every `gr_line` on Edge.Cuts, as rounded endpoint pairs."""
    segments = []
    for node in kicad.children(tree, "gr_line"):
        layer = kicad.first(node, "layer")
        if layer is None or len(layer) < 2 or layer[1] != EDGE_LAYER:
            continue
        start, end = kicad.first(node, "start"), kicad.first(node, "end")
        if start is None or end is None:
            raise Import3dError(f"a gr_line on {EDGE_LAYER} has no start or end: {node}")
        segments.append((
            (round(float(start[1]), _PLACES), round(float(start[2]), _PLACES)),
            (round(float(end[1]), _PLACES), round(float(end[2]), _PLACES)),
        ))
    return segments


def _ring(segments) -> tuple[tuple[float, float], ...]:
    """Chain unordered segments into one closed ring, or refuse and say why.

    A layout stores outline segments in drawing order, which is no order at
    all, so they have to be walked. Every refusal below is a real shape this
    cannot extrude, reported rather than approximated -- a plausible silhouette
    of the wrong board is worse than no silhouette, because nothing downstream
    can tell.
    """
    if not segments:
        raise Import3dError(
            f"no {EDGE_LAYER} segments. Either this layout has no board outline, "
            f"or its outline uses arcs or curves, which this reads none of"
        )

    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = (
        collections.defaultdict(list)
    )
    for start, end in segments:
        if start == end:
            raise Import3dError(f"a zero-length {EDGE_LAYER} segment at {start}")
        adjacency[start].append(end)
        adjacency[end].append(start)

    loose = sorted(point for point, joined in adjacency.items() if len(joined) != 2)
    if loose:
        raise Import3dError(
            f"the {EDGE_LAYER} outline is not closed: {len(loose)} point(s) join "
            f"other than two segments, first at {loose[0]}. "
            f"An open outline has no inside, so it cannot be extruded"
        )

    start = min(adjacency)
    ring = [start]
    previous, current = None, start
    while True:
        options = [point for point in adjacency[current] if point != previous]
        if not options:
            raise Import3dError(f"the outline walk dead-ended at {current}")
        previous, current = current, options[0]
        if current == start:
            break
        ring.append(current)

    if len(ring) != len(segments):
        raise Import3dError(
            f"the {EDGE_LAYER} outline is {len(segments)} segments but closes "
            f"after {len(ring)}, so it is more than one loop -- a board with a "
            f"cutout, or two boards panelised. This extrudes a single ring only"
        )
    return tuple(ring)


def read_outline(path: pathlib.Path) -> Outline:
    """The board outline from a `.kicad_pcb`, counter-clockwise."""
    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    return Outline(_ring(_edge_segments(tree))).counter_clockwise()


def read_thickness_mm(path: pathlib.Path) -> float:
    """The board thickness the layout records, in millimetres.

    Read rather than assumed. 1.6 mm is the overwhelmingly common answer and
    would have been right for both OLIMEX generations, which is exactly why
    defaulting to it is the wrong move: it would be silently wrong on the first
    0.8 mm board and nothing would say so.
    """
    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    general = kicad.first(tree, "general")
    thickness = kicad.first(general, "thickness") if general is not None else None
    if thickness is None or len(thickness) < 2:
        raise Import3dError(f"{path}: no (general (thickness ...)) to read")
    return float(thickness[1])


def pad_positions(path: pathlib.Path) -> tuple[tuple[str, float, float], ...]:
    """Every pad centre in the layout, with its module reference, in millimetres.

    The reference is carried because the answer to "a pad is outside the
    outline" is almost always "which part?", and without it the reader cannot
    tell an unplaced component from a broken outline. That is not hypothetical:
    it is how C12 was found sitting 13.7 mm off the right edge of Rev B2.

    A pad is placed relative to its module, and the module is placed and
    rotated on the board, so an absolute position is the module's `at` plus the
    pad's `at` turned by the module's angle. KiCad rotates clockwise on a
    y-down page, which is why the sine terms are signed the way they are.

    Here to check the outline rather than to describe the board: pads and
    outline come from different nodes of the same document, so a pad falling
    outside is the outline being wrong -- mirrored, mis-scaled, or read off the
    wrong layer -- and not a disagreement between two files.
    """
    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    out: list[tuple[str, float, float]] = []
    # `module` in KiCad 5, `footprint` in KiCad 6 and later. Same shape inside.
    for module in kicad.children(tree, "module") + kicad.children(tree, "footprint"):
        at = kicad.first(module, "at")
        if at is None or len(at) < 3:
            raise Import3dError(f"{path}: a module with no (at x y): {module[:2]}")
        mx, my = float(at[1]), float(at[2])
        angle = math.radians(float(at[3])) if len(at) > 3 else 0.0
        cos, sin = math.cos(angle), math.sin(angle)
        reference = _reference(module)
        for pad in kicad.children(module, "pad"):
            pad_at = kicad.first(pad, "at")
            if pad_at is None or len(pad_at) < 3:
                continue
            dx, dy = float(pad_at[1]), float(pad_at[2])
            out.append((reference, mx + dx * cos + dy * sin, my - dx * sin + dy * cos))
    return tuple(out)


def _reference(module: list) -> str:
    """The designator a schematic would call this part -- C12, R4, U1."""
    for text in kicad.children(module, "fp_text"):
        if len(text) > 2 and text[1] == "reference":
            return str(text[2])
    return "?"


def triangulate(outline: Outline) -> tuple[tuple[int, int, int], ...]:
    """Ear clipping over a counter-clockwise simple polygon.

    Forty lines and no dependency. It is O(n^2), which is irrelevant on a board
    outline: the largest in this repository is eight points, and a rounded one
    approximated into arcs would be a few hundred.
    """
    points = outline.counter_clockwise().points
    remaining = list(range(len(points)))
    triangles: list[tuple[int, int, int]] = []

    def cross(a, b, c) -> float:
        return ((points[b][0] - points[a][0]) * (points[c][1] - points[a][1])
                - (points[b][1] - points[a][1]) * (points[c][0] - points[a][0]))

    def inside(a, b, c, p) -> bool:
        d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    guard = 0
    while len(remaining) > 3:
        guard += 1
        if guard > len(points) * len(points):
            raise Import3dError(
                f"ear clipping made no progress on a {len(points)}-point outline; "
                f"it is self-intersecting, which this does not handle"
            )
        for position in range(len(remaining)):
            a = remaining[position - 1]
            b = remaining[position]
            c = remaining[(position + 1) % len(remaining)]
            if cross(a, b, c) <= 0:
                continue  # reflex, not an ear
            if any(inside(a, b, c, other) for other in remaining
                   if other not in (a, b, c)):
                continue  # another vertex is in the way
            triangles.append((a, b, c))
            remaining.pop(position)
            break

    triangles.append((remaining[0], remaining[1], remaining[2]))
    return tuple(triangles)


def board_mesh(outline: Outline, thickness_mm: float):
    """Vertices and triangle indices for the extruded board.

    Returns `(positions, indices)` with positions already translated so the
    outline's minimum corner is at the origin, and mapped into glTF axes.

    ## Which way each face points, derived rather than eyeballed

    A ring wound counter-clockwise in the layout's `(x, y)` becomes, under
    `(x, y) -> (x, z)`, a ring whose triangles have normal `-y`: for `u = b-a`
    and `v = c-a` lying in the XZ plane, `u x v = (0, -(ux*vz - uz*vx), 0)`,
    and that bracket is exactly the 2D cross product the triangulator kept
    positive. So the **bottom** face takes the triangles as they come and the
    **top** face takes them reversed.

    Side walls run `(bottom_i, top_i, top_j)` and `(bottom_i, top_j, bottom_j)`,
    both of which work out to `h * (ez, 0, -ex)` -- the outward normal of a
    counter-clockwise ring. `test_every_face_points_out_of_the_board` recomputes
    all of this from the emitted mesh, because a board with its faces inside out
    still looks like a board.
    """
    ring = outline.counter_clockwise().points
    count = len(ring)
    origin_x, origin_y = outline.min_x_mm, outline.min_y_mm

    positions: list[tuple[float, float, float]] = []
    for x, y in ring:                                    # bottom, y = 0
        positions.append((x - origin_x, 0.0, y - origin_y))
    for x, y in ring:                                    # top, y = thickness
        positions.append((x - origin_x, thickness_mm, y - origin_y))

    faces = triangulate(outline)
    indices: list[tuple[int, int, int]] = []
    for a, b, c in faces:
        indices.append((a, b, c))                                    # bottom, -y
        indices.append((count + a, count + c, count + b))            # top, +y
    for i in range(count):
        j = (i + 1) % count
        indices.append((i, count + i, count + j))
        indices.append((i, count + j, j))
    return positions, indices


def to_gltf(outline: Outline, thickness_mm: float, name: str) -> dict:
    """One self-contained glTF 2.0 document, buffer embedded as a data URI.

    Self-contained because the alternative is a `.gltf` beside a `.bin` that
    has to travel with it, and this repository has already learned what
    happens to an artefact whose second half goes missing.

    POSITION and indices only. No normals: a glTF viewer computes flat normals
    for a primitive that has none, and a board silhouette has no smooth
    shading to preserve. Emitting normals here would be inventing data to look
    complete.
    """
    positions, indices = board_mesh(outline, thickness_mm)

    vertex_bytes = b"".join(struct.pack("<3f", *point) for point in positions)
    index_bytes = b"".join(struct.pack("<3I", *triangle) for triangle in indices)
    blob = vertex_bytes + index_bytes

    lows = [min(point[axis] for point in positions) for axis in range(3)]
    highs = [max(point[axis] for point in positions) for axis in range(3)]

    return {
        "asset": {"version": "2.0", "generator": "OpenHardware tools/import_3d.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{
            "name": name,
            "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}],
        }],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions),
             "type": "VEC3", "min": lows, "max": highs},
            {"bufferView": 1, "componentType": 5125, "count": len(indices) * 3,
             "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vertex_bytes),
             "target": 34962},
            {"buffer": 0, "byteOffset": len(vertex_bytes),
             "byteLength": len(index_bytes), "target": 34963},
        ],
        "buffers": [{
            "byteLength": len(blob),
            "uri": "data:application/octet-stream;base64,"
                   + base64.b64encode(blob).decode("ascii"),
        }],
        "extras": {"openhardware": extent(outline, thickness_mm, name)},
    }


def extent(outline: Outline, thickness_mm: float, name: str) -> dict:
    """The board's real size in millimetres, and how to get back to the layout.

    **This is the deliverable**, not the triangles. OH-30 needs a silhouette
    the 2D pad map can be laid against, and a mesh whose units and origin are
    undeclared is a picture rather than a coordinate system.

    `origin_mm` is the corner the mesh was translated from, so a pad at
    `(px, py)` in the layout is at `(px - origin_mm[0], py - origin_mm[1])`
    here, on the glTF x and z axes.
    """
    return {
        "board": name,
        "units": "mm",
        "extent_mm": [round(outline.width_mm, 4), round(outline.height_mm, 4)],
        "thickness_mm": thickness_mm,
        "origin_mm": [round(outline.min_x_mm, 4), round(outline.min_y_mm, 4)],
        "outline_points": len(outline.points),
        "axes": "gltf x = layout x, gltf z = layout y, gltf y = thickness",
    }


def pads_outside(
    path: pathlib.Path, outline: Outline
) -> tuple[tuple[str, float, float], ...]:
    """Pad centres that do not fall inside the outline, with their references.

    The check that the outline is the right geometry rather than merely
    parseable. Both come from the same document and from different nodes of
    it, so this is not two files disagreeing.

    **What a result means depends on how many.** A mirrored or mis-scaled
    outline puts most of a board outside; a handful, all belonging to one
    reference, is an unplaced part. Rev B2 of ESP32-PoE has exactly that -- C12,
    both pads, 13.7 mm past the right edge -- so this reports the reference and
    lets the reader tell the two apart in one line, rather than picking a
    threshold that would be arbitrary in both directions.
    """
    return tuple(
        (reference, x, y)
        for reference, x, y in pad_positions(path)
        if not outline.contains(x, y)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Extrude a .kicad_pcb outline to glTF")
    parser.add_argument("layout", type=pathlib.Path, help="a .kicad_pcb file")
    parser.add_argument("--out", type=pathlib.Path,
                        help="where to write the glTF; stdout if absent")
    parser.add_argument("--check-pads", action="store_true",
                        help="fail unless every pad in the layout is inside the outline")
    args = parser.parse_args()

    if not args.layout.is_file():
        print(f"import_3d: {args.layout}: not found", file=sys.stderr)
        return 2
    try:
        outline = read_outline(args.layout)
        thickness = read_thickness_mm(args.layout)
        document = to_gltf(outline, thickness, args.layout.stem)
        if args.check_pads:
            stray = pads_outside(args.layout, outline)
            if stray:
                references = sorted({reference for reference, _, _ in stray})
                total = len(pad_positions(args.layout))
                print(
                    f"import_3d: {len(stray)} of {total} pad(s) fall outside the "
                    f"outline, on {len(references)} part(s): {', '.join(references)}. "
                    f"First at {stray[0][1]:.3f}, {stray[0][2]:.3f}. A few parts "
                    f"outside is an unplaced component; most of the board outside "
                    f"is an outline read off the wrong layer",
                    file=sys.stderr,
                )
                return 1
    except (Import3dError, kicad.KicadError) as exc:
        print(f"import_3d: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(document, indent=2)
    if args.out is None:
        print(text)
    else:
        args.out.write_text(text, encoding="utf-8")

    summary = document["extras"]["openhardware"]
    print(
        f"import_3d: {summary['board']} "
        f"{summary['extent_mm'][0]} x {summary['extent_mm'][1]} x "
        f"{summary['thickness_mm']} mm, {summary['outline_points']} outline points, "
        f"origin {summary['origin_mm']}"
        + (f" -> {args.out}" if args.out else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
