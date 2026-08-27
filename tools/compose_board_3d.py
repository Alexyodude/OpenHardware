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

## When even that runs out

The Uno's **USB-B socket** is in none of those libraries: KiCad's
`Connector_USB` holds three USB-A, seven USB-C, a Micro-B and a Mini-B and no
type B of any kind. It is also the most recognisable thing on the board after
the headers, so `tools/model_from_datasheet.py` builds it -- in Blender, out of
Arduino's own package geometry, with the one dimension that is not in any file
here cited to the USB standard. A component with `modelled=True` comes from
there, and the panel says which parts those are rather than letting them pass
as published.

## What is still deliberately not drawn

`ABSENT` is the honest end of the road: parts where no library has the right
model and the vendor's own drawing says the near miss is a miss. Both of the
Uno's remaining two are timing parts a few millimetres across, and each entry
carries the measurement that rules the obvious candidate out -- so the next
person reads the number rather than repeating the search.
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
    KICAD_3D,
    OUT,
    UNSTYLED,
    Extent,
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
    #: True when the mesh is one this project MADE, in Blender, because nobody
    #: publishes one -- `tools/model_from_datasheet.py` builds it and states
    #: where each of its numbers came from. A fourth kind of source and the
    #: worst, so it is a flag rather than a silent difference: the page says so.
    modelled: bool = False

    @property
    def url(self) -> str:
        # `KICAD_3D` is GitLab, which is the library; the GitHub mirror this
        # fetched from until 2026-08-27 is a different and smaller tree. See
        # that constant for the counts.
        return f"{KICAD_3D}/{self.library}.3dshapes/{self.model}.step"

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
    Component(
        "POWERSUPPLY_DC-21MM", "Connector_BarrelJack", "BarrelJack_Horizontal",
        "X1's nine through-hole pads span 5.99 x 5.77 mm and the vendor draws "
        "its body from x -5.08 to 3.91 and y -6.35 to 7.14. The model is "
        "14.20 x 9.30 x 14.60 mm. It is anchored on its LEGS rather than its "
        "body, which is the whole reason `place` learned to do that: a barrel "
        "is entirely to one side of its pins. "
        "**270 and not 90, and every other check said 90 was fine.** Anchored "
        "on pins that are symmetric about their own centre, a jack turned "
        "180 degrees measures perfectly and points its barrel INTO the board. "
        "Against the vendor's silkscreen the four turns miss by 5.36, 7.50, "
        "5.35 and 0.01 mm, so the right one is not a matter of taste.",
        turn=270.0,
    ),
    Component(
        "MLF32", "Package_DFN_QFN", "QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm",
        "U3's 33 surface-mount pads span 4.90 x 4.90 mm and the model is "
        "5.00 x 5.00 mm. MLF is Atmel's name for QFN and 32 pads on a 5 mm "
        "body is a 0.5 mm pitch. The ATmega16U2 that does the Uno's USB.",
    ),
    Component(
        "SOT223", "Package_TO_SOT_SMD", "SOT-223",
        "U1's four surface-mount pads span 6.20 x 4.62 mm against a model of "
        "7.00 x 6.50 mm. SOT-223 is the package in the EAGLE name and the "
        "model's, which is as direct as a correspondence gets.",
    ),
    Component(
        "PANASONIC_D", "Capacitor_SMD", "CP_Elec_6.3x5.4",
        "PC1 and PC2 have two surface-mount pads 4.80 mm apart. Panasonic's D "
        "case is a 6.3 mm diameter can 5.4 mm tall, which is this model's own "
        "name, and its land pattern measures 8.61 x 8.60 mm.",
    ),
    Component(
        "TS42", "Button_Switch_SMD", "SW_SPST_B3S-1000",
        "RESET's five surface-mount pads span 8.40 x 4.50 mm and the model is "
        "9.00 x 6.60 x 4.30 mm. Omron's B3S-1000 is the 6 mm surface-mount "
        "tactile switch this footprint is drawn for.",
    ),
    Component(
        "PN61729", "modelled", "USB_B_PN61729",
        "X2's four signal pins and two 2.2 mm shell posts, and a body of "
        "11.80 x 15.75 mm, are all Arduino's own package geometry -- this "
        "model is BUILT from that table rather than matched to it, so it "
        "cannot disagree. Only the 10.44 mm shell height comes from elsewhere, "
        "and it is the USB Series-B standard rather than a guess. See "
        "tools/model_from_datasheet.py, which cites every number it uses.",
        # No turn: the model is built in the vendor package's own frame, which
        # is the one thing a modelled part gets to choose and the reason it is
        # worth building rather than matching.
        modelled=True,
    ),
)

#: Packages that are on the board, are worth seeing, and are NOT drawn -- with
#: the reason, which travels to the page. An empty reason would be worse than
#: the omission: a person looking at a board with no USB socket should be told
#: why rather than left to wonder whether the importer broke.
ABSENT: dict[str, str] = {
    "QS": (
        "the 16 MHz crystal. Arduino's own silkscreen makes its body "
        "6.86 x 4.57 mm, and every through-hole crystal in KiCad's Crystal "
        "library is an HC49 at 10.90 or 11.05 mm across -- near enough to pass "
        "a footprint check and half as long again as the real can. The size "
        "check would have accepted it; the vendor's own drawing is what says "
        "no."
    ),
    "RESONATOR": (
        "the ceramic resonator. Its pads are surface-mount and its body is "
        "3.20 x 1.60 mm by the vendor's silkscreen; KiCad's only three-pin "
        "resonators are 7 mm through-hole cans standing 12.5 mm tall. "
        "`confirm` refuses it on mounting, which is the check that exists "
        "because the size tolerance let this one through."
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

#: Where `tools/model_from_datasheet.py` leaves the parts it builds.
MODELLED = REPO / "third_party" / "modelled"


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


def box_around(name: str, put: Mesh) -> dict[str, object]:
    """An axis-aligned box around a placed component, in the scene's frame.

    What a wire may not pass through. A box and not the mesh: `wires.js`
    resolves contact against boxes and spheres because a rope is stepped up to
    eight times a frame, and a triangle test against seventeen thousand of them
    is not a thing to do sixty times a second. A header is a box to within its
    own gaps, and a wire resting on the top of one is the picture that matters.
    """
    points = [(p[at], p[at + 1], p[at + 2])
              for _colour, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    return {
        "name": name,
        "min": [round(min(v[axis] for v in points), 4) for axis in range(3)],
        "max": [round(max(v[axis] for v in points), 4) for axis in range(3)],
    }


def component_mesh(component: Component, deflection: float) -> tuple[Mesh, object]:
    """Fetch and tessellate one KiCad model, in its own z-up millimetres.

    Left in KiCad's frame rather than glTF's, because `place` has to rotate it
    about the board's vertical and that is KiCad's z -- permuting first would
    mean rotating about a different axis and remembering which.
    """
    if component.modelled:
        made = MODELLED / f"{component.model}.obj"
        if not made.is_file():
            raise Unavailable(
                f"{made} has not been built. Run: "
                f"python tools/model_from_datasheet.py --part {component.model}"
            )
        return read_obj(made)

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


def read_obj(path: pathlib.Path) -> tuple[Mesh, Extent]:
    """A Wavefront OBJ and its `.mtl`, as the same `Mesh` a STEP tessellates to.

    **Narrow on purpose**, like `write_glb` at the other end of the pipeline:
    triangles, vertex normals and one colour per material group. Blender writes
    exactly that and nothing here needs more. Anything it cannot read it
    refuses by line, rather than skipping a face and drawing most of a part.

    Quads are triangulated by fanning, which is correct for the convex faces a
    box export produces and is not a general polygon triangulation -- `slab`
    has the real one, and needs it because a board outline is concave.
    """
    colours: dict[str, str] = {}
    material = path.with_suffix(".mtl")
    if material.is_file():
        name = ""
        for line in material.read_text(encoding="utf-8").splitlines():
            if line.startswith("newmtl "):
                name = line.split(None, 1)[1].strip()
            elif line.startswith("Kd ") and name:
                red, green, blue = (float(v) for v in line.split()[1:4])
                colours[name] = (f"#{round(red * 255):02x}"
                                 f"{round(green * 255):02x}"
                                 f"{round(blue * 255):02x}")

    vertices: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    groups: dict[str, tuple[list[float], list[float], list[int]]] = {}
    current = UNSTYLED

    def emit(corner: str) -> int:
        """One `v/vt/vn` reference, appended to the current group."""
        parts = corner.split("/")
        vertex = vertices[int(parts[0]) - 1]
        normal = (normals[int(parts[2]) - 1]
                  if len(parts) > 2 and parts[2] else (0.0, 0.0, 1.0))
        positions, into_normals, _indices = groups.setdefault(
            current, ([], [], []))
        positions.extend(vertex)
        into_normals.extend(normal)
        return len(positions) // 3 - 1

    for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("v "):
            vertices.append(tuple(float(v) for v in line.split()[1:4]))
        elif line.startswith("vn "):
            normals.append(tuple(float(v) for v in line.split()[1:4]))
        elif line.startswith("usemtl "):
            current = colours.get(line.split(None, 1)[1].strip(), UNSTYLED)
        elif line.startswith("f "):
            corners = line.split()[1:]
            if len(corners) < 3:
                raise ValueError(f"{path}:{number}: a face with "
                                 f"{len(corners)} corners is not a polygon")
            made = [emit(corner) for corner in corners]
            indices = groups[current][2]
            for at in range(1, len(made) - 1):
                indices.extend((made[0], made[at], made[at + 1]))

    if not groups:
        raise ValueError(f"{path}: no faces, so there is nothing to draw")
    every = [v for v in vertices]
    return Mesh(groups), Extent(
        min(v[0] for v in every), max(v[0] for v in every),
        min(v[1] for v in every), max(v[1] for v in every),
        min(v[2] for v in every), max(v[2] for v in every),
    )


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


#: How far below the board plane a vertex has to be before it counts as a
#: LEAD. KiCad models sit on z = 0 with through-hole legs hanging under it, so
#: anything materially negative is a leg. Loose enough that a surface-mount
#: pad's own plating, which is a few hundredths under, is not mistaken for one.
LEAD_DEPTH_MM = 0.5


def leads_of(mesh: Mesh) -> list[tuple[float, float]]:
    """The xy of every vertex below the board plane: a through-hole part's legs.

    Empty for a surface-mount model, which is the whole reason this is useful
    twice -- it says which KIND of part a mesh is, and for a through-hole one
    it says where the pins are without needing pad data a STEP does not carry.
    """
    return [(positions[at], positions[at + 1])
            for _colour, (positions, _n, _i) in mesh.groups.items()
            for at in range(0, len(positions), 3)
            if positions[at + 2] < -LEAD_DEPTH_MM]


def confirm(element: eagle.Element, box, turn: float,
            mesh: Mesh | None = None) -> str | None:
    """Does this mesh fit the pads it is supposed to stand on, the way round
    it is about to be placed?

    Returns a complaint, or `None` when they agree. Three things are checked
    and the last two were each added after they were needed:

    * **Size.** The mesh's footprint must contain the pad span within a
      tolerance -- a body is generally at least as big as its pads and never
      much smaller. A `DIL28-3` mapped to a DIP-8 fails by 20 mm.
    * **Orientation, in order and NOT sorted.** The first version of this
      compared `sorted` spans so that it would not care which way round a part
      was. That made it blind to the one mistake it most needed to catch:
      EAGLE lays a `1X10` along x and KiCad lays a `PinHeader_1x10` along y, so
      every header on the Uno was placed across the board and the check said
      nothing, because 22.86 x 2.54 sorts the same as 2.54 x 22.86.
    * **Mounting.** A through-hole model on surface-mount pads is a different
      part in the right place, whatever its footprint measures. `Y2` on the Uno
      is a 3.20 x 1.60 mm surface-mount resonator -- read off the vendor's own
      silkscreen -- and KiCad's only three-pin resonators are 7 mm
      through-hole cans 12.5 mm tall. The size check passed it, because 7 mm
      against 2 mm of pads is inside a tolerance that has to allow a body wider
      than its pins. Mounting is what tells them apart, and a mesh says which
      it is by whether it has anything below the board.
    """
    x0, y0, x1, y1 = element.pad_extent()
    pads = (x1 - x0, y1 - y0)
    span = footprint(box, turn, element)

    if mesh is not None:
        through = bool(element.pads_of("thru_hole"))
        legged = bool(leads_of(mesh))
        if through and not legged:
            return ("the element has through-hole pads and the model has "
                    "nothing below the board, so it is a surface-mount part")
        if not through and legged:
            return ("the element has only surface-mount pads and the model "
                    "has legs below the board, so it is a through-hole part")
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


#: How far a placed body may sit from where the vendor drew it before the
#: placement is refused. A body and a silkscreen are different outlines -- one
#: is the part and one is a drawing of where it goes -- so they do not agree
#: exactly. 1.5 mm is loose against the 0.40 mm worst case among the fourteen
#: parts that were right, and tight against the 7.50 mm of the one that was not.
SILK_TOLERANCE_MM = 1.5


def silk_miss(element: eagle.Element, put: Mesh,
              centre: tuple[float, float]) -> float | None:
    """How far the placed mesh sits from the body the vendor drew, in mm.

    `None` where the package has no silkscreen and there is nothing to compare.

    **This is the check that knows which way a part faces**, and it exists
    because nothing else did. `confirm` measures a model against the pads, and
    `place` anchors it on them -- both of which are blind to a part turned
    180 degrees, because a pin field is very often symmetric about its own
    centre. The Arduino Uno's barrel jack was exactly that: every earlier check
    passed while its barrel pointed into the board instead of out over the
    edge, 7.50 mm from where Arduino's own silkscreen puts it.

    The silkscreen is the vendor saying where the body goes, in the same file
    as the pads and transformed the same way, so this compares two things that
    both came from the vendor and neither from a table written here.
    """
    if element.silk is None:
        return None
    x0, y0, x1, y1 = element.silk
    spelling = ("MR" if element.mirrored else "R") + str(int(element.rotation))
    corners = [eagle.place(cx, cy, (element.x_mm, element.y_mm), spelling)
               for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    drawn_x = [c[0] for c in corners]
    drawn_y = [c[1] for c in corners]

    # Back out of the scene's frame into the board's, undoing only the centring
    # and the z flip -- so a sign error in `place` shows up here rather than
    # cancelling.
    mesh_x = [p[at] + centre[0]
              for _c, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    mesh_y = [-p[at + 2] + centre[1]
              for _c, (p, _n, _i) in put.groups.items()
              for at in range(0, len(p), 3)]
    return max(
        abs((min(drawn_x) + max(drawn_x)) / 2 - (min(mesh_x) + max(mesh_x)) / 2),
        abs((min(drawn_y) + max(drawn_y)) / 2 - (min(mesh_y) + max(mesh_y)) / 2),
    )


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

    **The legs are the anchor when there are legs**, which removes the
    assumption this used to carry. Centring a body on its pads is right for a
    DIP and a header, whose shrouds are symmetric about their pins, and wrong
    for a barrel jack, whose barrel is entirely to one side: centred on its
    body, the jack sits a few millimetres too far into the board and its barrel
    stops short of the edge it is supposed to overhang.

    A through-hole model says where its own pins are -- they are the geometry
    below the board plane -- and that is exactly what the pads describe. So the
    anchor is the centre of the legs, and only a surface-mount model, which has
    none, falls back to the centre of the body.
    """
    spin = math.radians(turn)
    turn_cos, turn_sin = math.cos(spin), math.sin(spin)
    rot = math.radians(element.rotation)
    rot_cos, rot_sin = math.cos(rot), math.sin(rot)

    def turned(x: float, y: float) -> tuple[float, float]:
        return (x * turn_cos - y * turn_sin, x * turn_sin + y * turn_cos)

    # The legs if it has any, the whole body if it has not. Measured off the
    # vertices rather than off the bounding box, so it is the same number the
    # placement below uses.
    anchor_points = leads_of(mesh) or [
        (positions[at], positions[at + 1])
        for _colour, (positions, _n, _i) in mesh.groups.items()
        for at in range(0, len(positions), 3)
    ]
    every = [turned(x, y) for x, y in anchor_points]
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
    #: A box around each placed component, for the renderer's wire physics.
    #: **Measured here because it is measured here already** -- the same
    #: vertices `silk_miss` and the overhang checks walk. A renderer that had
    #: to work these out itself would be re-deriving, from a mesh, numbers this
    #: tool had in its hand.
    solids: list[dict[str, object]] = []
    #: The subset of `drawn` whose mesh this project made rather than fetched.
    #: Carried separately all the way to the caption, because "KiCad's
    #: published meshes" stops being the whole truth the moment one is not.
    modelled: list[str] = []
    pad_top = spec.thickness_mm
    cache: dict[str, tuple[Mesh, object]] = {}
    for element in board.elements:
        component = by_package.get(element.package)
        if component is None:
            continue
        if component.slug not in cache:
            cache[component.slug] = component_mesh(component, deflection)
        mesh, box = cache[component.slug]
        complaint = confirm(element, box, component.turn, mesh)
        if complaint is not None:
            raise SystemExit(
                f"{spec.board}: {element.name} is a {element.package} and "
                f"CORRESPONDENCE gives it {component.library}/{component.model}, "
                f"but {complaint}. Fix the table rather than the tolerance."
            )
        put = place(mesh, element, component.turn, spec.thickness_mm, centre)
        solids.append(box_around(element.name, put))
        miss = silk_miss(element, put, centre)
        if miss is not None and miss > SILK_TOLERANCE_MM:
            raise SystemExit(
                f"{spec.board}: {element.name} ({element.package}) lands "
                f"{miss:.2f} mm from the body Arduino's own silkscreen draws "
                f"there, which is more than {SILK_TOLERANCE_MM} mm. Almost "
                f"always a `turn` that is 180 degrees out: the pins are "
                f"symmetric so every other check passes. Try the other three."
            )
        pieces.append(put)
        drawn.append(f"{element.name} ({component.model})")
        if component.modelled:
            modelled.append(f"{element.name} ({component.model})")
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
    if modelled:
        print(f"  modelled {len(modelled)}: {', '.join(modelled)} "
              f"-- built here, not fetched; see tools/model_from_datasheet.py")
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
            "modelled": modelled,
            "solids": solids,
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
