#!/usr/bin/env python3
# OpenHardware - a board's 3D model, composed from CAD nobody published a mesh for.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Stand real component meshes on a real board outline, for a board with no model.

`tools/import_3d_model.py` fetches a vendor's own mechanical model and
tessellates it. That is the better answer and it is the one to reach for first.
This module is what to do when there is no such file, and the Arduino Uno is
the case it was written for: it is the only *buildable* board in this
repository still drawn as an extruded footprint, and it is the one most people
open first.

## Nobody publishes an Uno mesh, and here is where that was checked

Recorded in the same sentence as the conclusion, which
`docs/HANDOFF_2026-08-27_the-bench.md` section 3.1 cost a day by not doing:

  * Arduino's own docs page for the Uno Rev3 links `A000066-cad-files.zip`,
    303,265 bytes, CC BY-SA 4.0. Opened 2026-08-27: an EAGLE `.brd`, an EAGLE
    `.sch` and a licence. **No STEP, no WRL, no mesh.**
  * KiCad's `kicad-packages3D` has no Arduino board model. `Module.3dshapes`
    holds two files and both are a Wemos D1 Mini.
  * `docs/research/board-sources/sources.json` had already recorded
    `model_3d: no` for Arduino on 2026-08-25. This agrees with it.

## So it is composed, from three sources and no invented numbers

  * **Where everything is** -- Arduino's EAGLE `.brd`, read by `tools/eagle.py`.
    The outline is 12 segments on layer 20, which is the Uno's real silhouette
    including its 1 mm corner chamfers and the notch on the right edge. Every
    component's position, rotation and mirror is the file's own.
  * **What everything looks like** -- KiCad's `kicad-packages3D`, which
    `tools/import_3d_model.py` already fetches this project's LEDs and buzzer
    from. Real meshes of real parts, CC-BY-SA-4.0.
  * **The colour of the board** -- `#313d63`, read out of PICSimLab's
    `share/boards/Arduino Uno/board.svg`, where it fills the board-body path.
    That path's own data is the same silhouette, which is what makes it the
    board's colour rather than a colour that happens to be in the drawing.

**No height is typed in from a datasheet.** Not one of the 116 packages in the
`.brd` declares a height -- counted, not assumed -- so a component drawn as an
extruded box would need a thickness invented per package. That is section 3.6's
lead-tip defect in a new place: a plausible number, from a second source, that
disagrees with the geometry silently. Every height here comes off a mesh, and a
package with no mesh is not drawn.

## A correspondence proposed by name and confirmed by geometry

`CORRESPONDENCE` says which KiCad model *is* each EAGLE package. Every line of
it is a judgement, so none of them is trusted: `confirm` measures the element's
own pads against the mesh it was given and refuses a model that does not span
them. A `DIL28-3` mapped to a DIP-8 draws a plausible little chip in the right
place and is wrong, and nothing but the numbers would say so.

That check has teeth because the pads are the one thing both sources describe.
`ZU4`'s pads span 33.02 x 7.62 mm; `DIP-28_W7.62mm` is a 28-pin package on
7.62 mm rows, and 33.02 is 13 x 2.54. They agree because they are the same part.

## What is deliberately not drawn

The **USB-B connector**, element `X2`, package `PN61729`. It is the Uno's most
recognisable feature after the headers and `Connector_USB.3dshapes` holds five
entries, two of them STEP, and neither is a USB-B. There is no honest mesh, so
there is no connector -- and `absent` carries the reason to the page, the same
way the XIAO ESP32-C3 says its model is on GrabCAD.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import pathlib
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import eagle  # noqa: E402
from tools.import_3d_model import (  # noqa: E402
    CACHE,
    DEFLECTION,
    OUT,
    Frame,
    Mesh,
    Unavailable,
    box_of,
    handedness_of,
    read,
    tessellate,
    write_glb,
)


@dataclasses.dataclass(frozen=True)
class Component:
    """One EAGLE package and the KiCad model that *is* that part.

    `why` is the evidence, not a restatement of the mapping. A line here is a
    claim about two libraries agreeing, and the next person to read it needs to
    know what was measured rather than that somebody was confident.
    """

    package: str
    library: str
    model: str
    why: str
    #: Degrees counter-clockwise taking the KiCad model's own axes onto the
    #: EAGLE package's, applied before the element's own rotation.
    #:
    #: **Not zero, and this is the bug that made it a field.** The two
    #: libraries lay a part out differently: EAGLE's `1X10` puts its ten pads
    #: along x, spanning 22.86 x 0.00 mm, and KiCad's `PinHeader_1x10` runs
    #: along y. Composed without this the headers stood across the board
    #: instead of along it, and the assembly measured 68.58 x 91.44 mm on a
    #: board 53.34 mm deep -- a picture that is obviously wrong once measured
    #: and looks like a rendering glitch on screen.
    turn: float = 0.0


    @property
    def url(self) -> str:
        return (f"https://raw.githubusercontent.com/KiCad/kicad-packages3D/"
                f"master/{self.library}.3dshapes/{self.model}.step")

    @property
    def slug(self) -> str:
        return f"{self.library}-{self.model}".replace(".", "_")


#: EAGLE package name -> the KiCad model of that part. Each span quoted below
#: was measured on 2026-08-27 with `eagle.Element.pad_extent`, and `confirm`
#: re-measures it on every run rather than trusting these comments.
CORRESPONDENCE: tuple[Component, ...] = (
    Component(
        "DIL28-3", "Package_DIP", "DIP-28_W7.62mm",
        "ZU4's pads span 33.02 x 7.62 mm. 7.62 mm is the row spacing in the "
        "model's own name and 33.02 is 13 x 2.54, which is 28 pins in two "
        "rows. The ATmega328P.",
        turn=90.0,
    ),
    Component(
        "1X10", "Connector_PinHeader_2.54mm", "PinHeader_1x10_P2.54mm_Vertical",
        "IOH's pads span 22.86 mm in one row, which is 9 x 2.54 -- ten pins.",
        turn=90.0,
    ),
    Component(
        "1X08", "Connector_PinHeader_2.54mm", "PinHeader_1x08_P2.54mm_Vertical",
        "IOL and POWER each span 17.78 mm in one row, which is 7 x 2.54.",
        turn=90.0,
    ),
    Component(
        "1X06", "Connector_PinHeader_2.54mm", "PinHeader_1x06_P2.54mm_Vertical",
        "AD spans 12.70 mm in one row, which is 5 x 2.54.",
        turn=90.0,
    ),
    Component(
        "2X03", "Connector_PinHeader_2.54mm", "PinHeader_2x03_P2.54mm_Vertical",
        "ICSP and ICSP1 each span 2.54 x 5.08 mm -- two rows of three. Which "
        "way round is the element's own rotation and not this table's problem.",
        turn=90.0,
    ),
    Component(
        "2X02", "Connector_PinHeader_2.54mm", "PinHeader_2x02_P2.54mm_Vertical",
        "JP2 spans 2.54 x 2.54 mm, which is two rows of two.",
        # Square, so the turn cannot be derived from the shape and cannot
        # matter either. Given for consistency with its neighbours.
        turn=90.0,
    ),
)

#: Packages that are on the board, are worth seeing, and are NOT drawn -- with
#: the reason, which travels to the page. An empty reason would be worse than
#: the omission: a person looking at a board with no USB socket should be told
#: why rather than left to wonder whether the importer broke.
ABSENT: dict[str, str] = {
    "PN61729": (
        "the USB-B socket. Connector_USB.3dshapes holds five entries and two "
        "of them are STEP -- a Micro-B and a Mini-B -- and there is no USB_B "
        "of any kind. Drawing one of the others would be a different connector "
        "in the right place."
    ),
}


@dataclasses.dataclass(frozen=True)
class Composition:
    """A board that is composed rather than fetched, and what it is made of."""

    board: str
    #: Under `third_party/`, which is gitignored: this is a fetched input.
    brd: pathlib.Path
    #: The elements whose pads are the board's pad map. The model is centred on
    #: these, because `webui/static/board3d.js` centres it on the same pads --
    #: and unlike a XIAO, whose castellations are symmetric, an Uno's headers
    #: sit well off the middle of its board.
    headers: tuple[str, ...]
    #: The PCB, in millimetres. EAGLE carries no board thickness, and 1.6 mm is
    #: what `board3d.js` already assumes for every extruded footprint -- so
    #: this is the existing assumption reused, not a new one.
    thickness_mm: float
    #: `#rrggbb`, and where it was read from.
    colour: str
    colour_source: str


COMPOSITIONS: tuple[Composition, ...] = (
    Composition(
        board="Arduino Uno",
        brd=REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd",
        headers=("IOH", "IOL", "POWER", "AD"),
        thickness_mm=1.6,
        colour="#313d63",
        colour_source=(
            "PICSimLab's share/boards/Arduino Uno/board.svg, where it fills "
            "the board-body path -- whose own path data is this same "
            "silhouette, which is what makes it the board's colour rather "
            "than one that happens to be in the drawing"
        ),
    ),
)

#: How far a mesh's footprint may sit from the pads it is supposed to stand on
#: before the mapping is refused. Generous, because a package's pads and its
#: body are legitimately different sizes -- a DIP's body is narrower than its
#: rows and a header's shroud is wider than its pins. What this catches is a
#: model of the wrong SIZE of the right kind of part, which is the mistake a
#: name-based table actually makes.
SPAN_TOLERANCE_MM = 3.0

#: KiCad's own convention, and the frame every component mesh arrives in.
PART_UP = 2


def loop(segments: tuple[eagle.Segment, ...]) -> list[tuple[float, float]]:
    """Chain drawn segments into one closed ring of points.

    EAGLE writes the outline in no particular order and in no particular
    direction, so this walks from an end to whichever segment shares it. It
    **refuses an outline that does not close** rather than joining the ends,
    because a board whose outline has a gap is a board this cannot describe,
    and a silently-closed polygon would be a plausible wrong shape.
    """
    if not segments:
        raise ValueError("no outline segments")
    remaining = [((s.x1_mm, s.y1_mm), (s.x2_mm, s.y2_mm)) for s in segments]
    start, here = remaining.pop(0)
    ring = [start, here]
    while remaining:
        for index, (a, b) in enumerate(remaining):
            if _near(a, here):
                here = b
            elif _near(b, here):
                here = a
            else:
                continue
            remaining.pop(index)
            ring.append(here)
            break
        else:
            raise ValueError(
                f"the outline does not chain: {len(remaining)} segment(s) left "
                f"and none touches {here}. A board outline with a gap in it is "
                f"not a shape this can extrude."
            )
    if not _near(ring[0], ring[-1]):
        raise ValueError(
            f"the outline chains but does not close: it ends at {ring[-1]} "
            f"having started at {ring[0]}"
        )
    return ring[:-1]


def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Within a tenth of a micron. EAGLE writes coordinates to 3 decimals."""
    return abs(a[0] - b[0]) < 1e-4 and abs(a[1] - b[1]) < 1e-4


def _area(ring: list[tuple[float, float]]) -> float:
    """Twice the signed area. Positive when the ring runs counter-clockwise."""
    total = 0.0
    for index, (x, y) in enumerate(ring):
        nx, ny = ring[(index + 1) % len(ring)]
        total += x * ny - nx * y
    return total


def ear_clip(ring: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Triangulate a simple polygon by clipping ears.

    The Uno's outline is not convex -- the notch on its right edge is the
    point -- so a fan from one vertex would put triangles outside the board.
    Ear clipping handles any simple polygon and needs no library, which is the
    same reasoning `tools/import_3d_model.py` gives for hand-writing its glTF.
    """
    order = list(range(len(ring)))
    if _area(ring) < 0:
        order.reverse()
    triangles: list[tuple[int, int, int]] = []
    guard = 0
    while len(order) > 3:
        guard += 1
        if guard > len(ring) * len(ring):
            raise ValueError(
                f"no ear found in a {len(order)}-vertex remainder; the outline "
                f"is not a simple polygon"
            )
        for at in range(len(order)):
            prev = order[at - 1]
            here = order[at]
            nxt = order[(at + 1) % len(order)]
            if not _is_ear(ring, prev, here, nxt, order):
                continue
            triangles.append((prev, here, nxt))
            order.pop(at)
            break
    triangles.append((order[0], order[1], order[2]))
    return triangles


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _is_ear(ring, prev: int, here: int, nxt: int, order: list[int]) -> bool:
    """Convex at `here`, and no other vertex inside the triangle it cuts off."""
    if _cross(ring[prev], ring[here], ring[nxt]) <= 0:
        return False
    for other in order:
        if other in (prev, here, nxt):
            continue
        point = ring[other]
        if (_cross(ring[prev], ring[here], point) >= 0
                and _cross(ring[here], ring[nxt], point) >= 0
                and _cross(ring[nxt], ring[prev], point) >= 0):
            return False
    return True


def slab(ring: list[tuple[float, float]], thickness: float, colour: str,
         centre: tuple[float, float]) -> Mesh:
    """The PCB: the outline extruded, in glTF axes and millimetres.

    glTF y is up and z runs the short way, so an EAGLE (x, y) becomes
    (x, height, -y) -- the same negation `board3d.js` applies to a pad, and for
    the same reason: EAGLE's y grows upward and the scene's z grows toward the
    camera, so getting it wrong mirrors the board end for end.
    """
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []

    def put(x: float, y: float, up: float, normal: tuple[float, float, float]) -> int:
        positions.extend((x - centre[0], up, -(y - centre[1])))
        normals.extend(normal)
        return len(positions) // 3 - 1

    faces = ear_clip(ring)
    for a, b, c in faces:
        top = [put(*ring[i], thickness, (0.0, 1.0, 0.0)) for i in (a, b, c)]
        indices.extend(top)
        bottom = [put(*ring[i], 0.0, (0.0, -1.0, 0.0)) for i in (a, c, b)]
        indices.extend(bottom)

    for index, point in enumerate(ring):
        nxt = ring[(index + 1) % len(ring)]
        along = (nxt[0] - point[0], nxt[1] - point[1])
        length = math.hypot(*along) or 1.0
        # The outward normal of a counter-clockwise ring is the edge turned a
        # quarter to the right, and z is negated with y.
        normal = (along[1] / length, 0.0, along[0] / length)
        corners = [put(*point, 0.0, normal), put(*nxt, 0.0, normal),
                   put(*nxt, thickness, normal), put(*point, thickness, normal)]
        indices.extend((corners[0], corners[1], corners[2]))
        indices.extend((corners[0], corners[2], corners[3]))

    return Mesh({colour: (positions, normals, indices)})


def component_mesh(component: Component, deflection: float) -> tuple[Mesh, object]:
    """Fetch and tessellate one KiCad model, in its own z-up millimetres.

    Left in KiCad's frame rather than glTF's, because `place` has to rotate it
    about the board's vertical and that is KiCad's z -- permuting first would
    mean rotating about a different axis and remembering which.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    step = CACHE / f"component-{component.slug}.step"
    if not step.is_file():
        print(f"  fetch  {component.url}")
        with urllib.request.urlopen(component.url) as response:  # noqa: S310
            step.write_bytes(response.read())
    shape, styles, _document = read(step)
    box = box_of(shape)
    #: Identity: x stays x, z stays up, y stays y. `place` does the moving.
    frame = Frame(long_axis=0, up=1, short_axis=2,
                  handedness=handedness_of((0, 1, 2)),
                  origin=(0.0, 0.0, 0.0))
    return tessellate(shape, styles, deflection, frame), box


def footprint(box, turn: float, element: eagle.Element) -> tuple[float, float]:
    """The mesh's span along the board's own x and y, once fully turned.

    Both the component's `turn` and the element's own rotation, because that is
    what decides which way the part actually lies on this board. A quarter turn
    swaps the two numbers, which is exactly the difference `confirm` has to be
    able to see.
    """
    angle = math.radians(turn + element.rotation)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    return (box.width * cos + box.height * sin,
            box.width * sin + box.height * cos)


def confirm(element: eagle.Element, box, turn: float) -> str | None:
    """Does this mesh fit the pads it is supposed to stand on, the way round
    it is about to be placed?

    Returns a complaint, or `None` when they agree. Two things are checked and
    the second was added after it was needed:

    * **Size.** The mesh's footprint must contain the pad span within a
      tolerance -- a body is generally at least as big as its pads and never
      much smaller. A `DIL28-3` mapped to a DIP-8 fails by 20 mm.
    * **Orientation, in order and NOT sorted.** The first version of this
      compared `sorted` spans so that it would not care which way round a part
      was. That made it blind to the one mistake it most needed to catch:
      EAGLE lays a `1X10` along x and KiCad lays a `PinHeader_1x10` along y, so
      every header on the Uno was placed across the board and the check said
      nothing, because 22.86 x 2.54 sorts the same as 2.54 x 22.86.
    """
    x0, y0, x1, y1 = element.pad_extent()
    pads = (x1 - x0, y1 - y0)
    span = footprint(box, turn, element)
    for axis, (mesh_side, pad_side) in enumerate(zip(span, pads)):
        which = "x" if axis == 0 else "y"
        if mesh_side < pad_side - SPAN_TOLERANCE_MM:
            return (f"turned as the table says, the model spans "
                    f"{span[0]:.2f} x {span[1]:.2f} mm and the pads it must "
                    f"cover span {pads[0]:.2f} x {pads[1]:.2f} -- it is "
                    f"{pad_side - mesh_side:.2f} mm too short in {which}")
        if mesh_side > pad_side + SPAN_TOLERANCE_MM * 4:
            return (f"turned as the table says, the model spans "
                    f"{span[0]:.2f} x {span[1]:.2f} mm against pads spanning "
                    f"{pads[0]:.2f} x {pads[1]:.2f} -- it is "
                    f"{mesh_side - pad_side:.2f} mm too long in {which}")
    return None


def place(mesh: Mesh, element: eagle.Element, turn: float, thickness: float,
          centre: tuple[float, float]) -> Mesh:
    """Move a component's mesh onto the board, the way its pads were moved.

    `tools/eagle.py`'s `place` mirrors in x, then rotates counter-clockwise,
    then translates -- an order checked there against routed copper. This does
    the same thing to a mesh, so a component lands exactly where the pads this
    repository already trusts put it.

    **`turn` happens first, before the mirror**, and the order is not
    arbitrary: it takes the KiCad model into the frame EAGLE's own package is
    drawn in, and everything after it is what EAGLE says to do to *that*. Turn
    after mirroring and a mirrored part comes out reflected in the wrong axis.

    **Anchored on the pads, not on either library's origin.** The two do not
    agree about where a package begins: KiCad puts a header's origin on pin 1,
    EAGLE puts it in the middle of the pin field, and `AD` -- a 1x06 whose pin
    1 is 6.35 mm from its element origin -- landed a full 2.54 mm off the end
    of the board because of it. Rather than a table of per-package offsets,
    which would be one more hand-kept thing to get wrong, the mesh's own
    footprint centre is put on the element's own pad centre. The pads are the
    one thing both libraries describe, which is what makes them the anchor.

    **The assumption that leaves**, stated because it is real: a component's
    body must be centred on its pads. True of every part in `CORRESPONDENCE` --
    a DIP's body and a header's shroud are both symmetric about their pins --
    and false of, say, a barrel jack, whose barrel is all to one side. A part
    like that needs its anchor derived some other way before it goes in here.
    """
    spin = math.radians(turn)
    turn_cos, turn_sin = math.cos(spin), math.sin(spin)
    rot = math.radians(element.rotation)
    rot_cos, rot_sin = math.cos(rot), math.sin(rot)

    def turned(x: float, y: float) -> tuple[float, float]:
        return (x * turn_cos - y * turn_sin, x * turn_sin + y * turn_cos)

    # The turned footprint's own centre, measured off the vertices rather than
    # off the bounding box, so that it is the same number the placement uses.
    every = [turned(positions[at], positions[at + 1])
             for _colour, (positions, _n, _i) in mesh.groups.items()
             for at in range(0, len(positions), 3)]
    mid_x = (min(p[0] for p in every) + max(p[0] for p in every)) / 2
    mid_y = (min(p[1] for p in every) + max(p[1] for p in every)) / 2

    x0, y0, x1, y1 = element.pad_extent()
    anchor = ((x0 + x1) / 2, (y0 + y1) / 2)

    def onto_board(x: float, y: float, direction: bool = False) -> tuple[float, float]:
        tx, ty = turned(x, y)
        if not direction:
            tx, ty = tx - mid_x, ty - mid_y
        if element.mirrored:
            tx = -tx
        return (tx * rot_cos - ty * rot_sin, tx * rot_sin + ty * rot_cos)

    moved: dict[str, tuple[list[float], list[float], list[int]]] = {}
    for colour, (positions, normals, indices) in mesh.groups.items():
        out_positions: list[float] = []
        out_normals: list[float] = []
        for at in range(0, len(positions), 3):
            dx, dy = onto_board(positions[at], positions[at + 1])
            bx, by = anchor[0] + dx, anchor[1] + dy
            # KiCad z is up and rises from the board plane; glTF y is up and
            # the PCB's top face is at `thickness`.
            out_positions.extend((bx - centre[0], thickness + positions[at + 2],
                                  -(by - centre[1])))
            # A normal is a direction, so it is turned but never translated.
            tnx, tny = onto_board(normals[at], normals[at + 1], direction=True)
            out_normals.extend((tnx, normals[at + 2], -tny))
        moved[colour] = (out_positions, out_normals, list(indices))
    return Mesh(moved)


def merge(*meshes: Mesh) -> Mesh:
    """One mesh from several, keeping the colour groups and reindexing."""
    groups: dict[str, tuple[list[float], list[float], list[int]]] = {}
    for mesh in meshes:
        for colour, (positions, normals, indices) in mesh.groups.items():
            into = groups.setdefault(colour, ([], [], []))
            base = len(into[0]) // 3
            into[0].extend(positions)
            into[1].extend(normals)
            into[2].extend(index + base for index in indices)
    return Mesh(groups)


def compose(spec: Composition, deflection: float, check: bool) -> int:
    """Read, confirm, compose and write one board. Returns the byte count."""
    print(f"{spec.board}:")
    if not spec.brd.is_file():
        print(f"  SKIPPED: {spec.brd} is not fetched. Run: "
              f"python tools/get_board_sources.py arduino-uno")
        return 3

    board = eagle.read_board(spec.brd)
    ring = loop(board.outline)
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    print(f"  outline {len(ring)} points, "
          f"{max(xs) - min(xs):.3f} x {max(ys) - min(ys):.3f} mm, "
          f"{len(ear_clip(ring))} triangles")

    # **Centred on the pads, not on the PCB.** `board3d.js` puts the model's
    # origin at the centre of the pad map's own extent; on a XIAO those agree
    # because the castellations are symmetric, and on an Uno they are 7.7 mm
    # apart. Centring on the PCB here would draw the whole board off to one
    # side of its own pad markers.
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)
    print(f"  centre  on {len(header_pads)} header pads at "
          f"({centre[0]:.3f}, {centre[1]:.3f}) mm; the PCB's own centre is "
          f"({(min(xs) + max(xs)) / 2:.3f}, {(min(ys) + max(ys)) / 2:.3f})")

    by_package = {component.package: component for component in CORRESPONDENCE}
    pieces = [slab(ring, spec.thickness_mm, spec.colour, centre)]
    drawn: list[str] = []
    pad_top = spec.thickness_mm
    cache: dict[str, tuple[Mesh, object]] = {}
    for element in board.elements:
        component = by_package.get(element.package)
        if component is None:
            continue
        if component.slug not in cache:
            cache[component.slug] = component_mesh(component, deflection)
        mesh, box = cache[component.slug]
        complaint = confirm(element, box, component.turn)
        if complaint is not None:
            raise SystemExit(
                f"{spec.board}: {element.name} is a {element.package} and "
                f"CORRESPONDENCE gives it {component.library}/{component.model}, "
                f"but {complaint}. Fix the table rather than the tolerance."
            )
        put = place(mesh, element, component.turn, spec.thickness_mm, centre)
        pieces.append(put)
        drawn.append(f"{element.name} ({component.model})")
        # **How high a pad marker has to ride on THIS board.** A XIAO's pads
        # are castellations on the edge and a marker sits on the PCB. An Uno's
        # are inside a header shroud, so a marker left on the board is buried
        # by the very component that proves it is a header -- and a wire would
        # be dropped on a pin it cannot see. A person clips a lead to the PIN,
        # so the marker goes on the pin tip, and the tip is measured off the
        # header that is actually there rather than looked up.
        if element.name in spec.headers:
            pad_top = max(pad_top, max(
                value for _colour, (positions, _n, _i) in put.groups.items()
                for value in positions[1::3]))

    print(f"  drawn   {len(drawn)}: {', '.join(drawn)}")
    print(f"  markers ride at {pad_top:.3f} mm, the top of the header pins; "
          f"the PCB's own top face is at {spec.thickness_mm:.3f}")
    for package, why in sorted(ABSENT.items()):
        here = [e.name for e in board.elements if e.package == package]
        if here:
            print(f"  absent  {'/'.join(here)} ({package}): {why[:60]}...")

    whole = merge(*pieces)
    print(f"  mesh    {whole.triangles():,} triangles, "
          f"{len(whole.groups)} colours")
    if check:
        print("  write   skipped (--check)")
        return 0

    out = OUT / f"{_slug(spec.board)}.glb"
    size = write_glb(
        whole, out, spec.board, str(spec.brd.name),
        (max(xs) - min(xs), max(ys) - min(ys), spec.thickness_mm),
        extras={
            "composed": True,
            "board": spec.board,
            # **Where the PCB is, relative to this model's origin.** The origin
            # is the pad centre, because that is what `board3d.js` positions a
            # model by; on this board the PCB's own centre is 6.86 mm away from
            # it. Without this the wire collider -- which is a box around the
            # PCB -- would sit that far off the board it is meant to be.
            # Absent on every fetched model, where the two centres coincide,
            # and the renderer defaults it to zero for exactly that reason.
            "pcb_offset": [
                round((min(xs) + max(xs)) / 2 - centre[0], 4),
                round(-((min(ys) + max(ys)) / 2 - centre[1]), 4),
            ],
            # **How big the pad field is, in millimetres.** The page scales a
            # model by a constant 8 px/mm, which is what
            # `tools/import_board.py` generates a board JSON at -- and is not
            # what PICSimLab's Arduino Uno artwork is. That is about
            # 5.66 px/mm, so the model came out 41% too large and its headers
            # stood well outside their own pad markers. Handing over the span
            # lets the renderer divide one by the other and get the scale from
            # the two things that describe the same pads, rather than from a
            # constant that happens to be true of nine boards.
            "pad_span": [
                round(max(hx) - min(hx), 4),
                round(max(hy) - min(hy), 4),
            ],
            "pad_top": round(pad_top, 4),
            "pcb_colour": spec.colour,
            "pcb_colour_source": spec.colour_source,
            "geometry": (
                "Arduino's own EAGLE board file, CC BY-SA 4.0: the outline "
                "from layer 20 and every component's position, rotation and "
                "mirror as the file states them"
            ),
            "components": (
                "KiCad kicad-packages3D, CC-BY-SA-4.0 with the library "
                "exception; fetched, not vendored"
            ),
            "drawn": drawn,
            "absent": [
                {"package": package, "why": why,
                 "elements": [e.name for e in board.elements
                              if e.package == package]}
                for package, why in sorted(ABSENT.items())
                if any(e.package == package for e in board.elements)
            ],
        })
    print(f"  write   {out.relative_to(REPO)}  {size:,} bytes")
    return size


def _slug(board: str) -> str:
    return board.replace(" ", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--board", help="one board; every composed one without it")
    parser.add_argument("--check", action="store_true",
                        help="report and write nothing")
    parser.add_argument("--deflection", type=float, default=DEFLECTION)
    args = parser.parse_args(argv)

    wanted = [spec for spec in COMPOSITIONS
              if args.board is None or spec.board == args.board]
    if not wanted:
        print(f"no composed board called {args.board!r}. Known: "
              f"{', '.join(spec.board for spec in COMPOSITIONS)}")
        return 2

    total = 0
    for spec in wanted:
        try:
            written = compose(spec, args.deflection, args.check)
        except Unavailable as exc:
            print(f"SKIPPED: OpenCASCADE is not installed ({exc}). "
                  f"pip install cadquery-ocp")
            return 3
        if written == 3:
            return 3
        total += written
    if not args.check and total:
        from tools.import_3d_model import write_index
        index = write_index()
        print(f"{total:,} bytes of glTF; index at {index.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
