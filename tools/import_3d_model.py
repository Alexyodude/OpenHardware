#!/usr/bin/env python3
# OpenHardware - the vendor's own board, tessellated once so a browser can draw it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Fetch a vendor STEP model of a board and write it out as glTF.

    python tools/import_3d_model.py --chip SAMD21
    python tools/import_3d_model.py --all
    python tools/import_3d_model.py --chip SAMD21 --check   # report, write nothing

## Why this exists, and the correction it carries

`webui/static/board3d.js` draws a footprint extruded into a slab and says so
in the page, because when OH-30 built it there was nothing else to draw.
OH-29's census is why: a full `git ls-tree` of `Seeed-Studio/OSHW-XIAO-Series`
found 0 `.step`, 0 `.stp` and 0 `.wrl`, and OH-29 recorded that Seeed publishes
no board 3D at all.

**That census looked in the git repository and the models are on the wiki.**
Seeed publishes one per board under `files.seeedstudio.com`, and every
`.kicad_mod` in `third_party/seeed-xiao` has been naming them the whole time:

    (model "${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeeduino XIAO SAMD21 v4.step"

`AMZPATH` is a KiCad environment variable pointing at a library the vendor does
not ship, which is exactly why nothing found it. `Seeeduino XIAO SAMD21 v4.step`
is the filename inside the wiki's zip, character for character.

## Why OpenCASCADE rather than a tessellator written here

Measured on the SAMD21 model, 2026-08-26: 2,228 faces, of which **992 are
`B_SPLINE_SURFACE_WITH_KNOTS`**, and no tessellated entity of any kind. The two
solids that are nine tenths of the model are 52% and 47% spline, so a mesher
that handled only planes and cylinders would render half of each and produce a
board full of holes -- worse than the honest extrusion it replaces. The file
also carries **no `PCURVE`, `SURFACE_CURVE` or `DEFINITIONAL_REPRESENTATION`**,
so trimming would mean projecting 3D edge loops into parameter space by Newton
iteration on 992 spline surfaces. That is a CAD kernel, not a ticket.

**OCP is a tool dependency and not a runtime one**, the same arrangement
`tools/gen_avr_corpus.mjs` has with node and avr8js: this exits 3 and says
SKIPPED where OCP is absent, and nothing the browser loads gains a dependency.

**The meshes are not committed, and that is a licence decision rather than a
size one.** Seeed's `OSHW-XIAO-Series` repository is MIT and the board JSONs
record it; these files come from the wiki's file server instead, which states
no licence at all. `rules/licence-hygiene.md` §4 is explicit that a dependency
arriving in a directory nobody exempted is a question for a person rather than
a header to rewrite -- so `webui/static/models/` is gitignored and a checkout
without it draws the extruded footprint and says so.

## What is emitted, and in what frame

glTF 2.0 binary, one primitive per colour, **in millimetres**. The spec's unit
is the metre and this deviates on purpose: every length in this repository is
millimetres -- the board JSONs, `webui/pinmap.py`, OH-29's own Done-when -- and
a model in metres would be multiplied straight back by a thousand at the one
place it is read. `asset.extras.units` says so in the file.

**The four files do not share an axis convention and one of them is not laid
out the way the others are**, which is the thing about this job that is not
bookkeeping. Seeed's SAMD21 and RP2040 models are Z-up; the ESP32-S3 and
nRF52840 models are Y-up; and the RP2040's board runs the short way across its
own x. Assuming any of that produced a board lying on its side or turned
ninety degrees, and the tell was a picture rather than an error. `Frame` works
it out per file and emits one canonical frame: PCB long side along glTF x,
thickness along y with the underside at zero, short side along z.

The origin is **the PCB solid's centre, not the assembly's**. The USB-C
connector overhangs the board edge by 1.3 mm, so a model centred on the
assembly sits 0.65 mm off its own pads -- close enough to look almost right,
which is the worst amount to be wrong by.

## What it refuses to claim

The alignment residual is **printed, not asserted to be zero**. Two independent
sources of millimetres -- the vendor's footprint, via
`tools/import_kicad_board.py`, and the vendor's mechanical model -- agree to
whatever they agree to, and saying so is the difference between an import and
a hope.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import struct
import sys
import urllib.request
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Where fetched archives land. Gitignored -- `.gitignore:26` -- because
#: "fetch, do not vendor" applies here more sharply than anywhere else in the
#: repository: these four zips are 34 MB and the meshes they produce are 3.
CACHE = REPO / "third_party" / "seeed-3d"

#: Where the meshes go. Served by `webui/emulator_server.py`, which needs the
#: `.glb` content type for them and has it.
OUT = REPO / "webui" / "static" / "models"

#: Millimetres of chord error the tessellation is allowed.
#:
#: **Measured rather than picked.** On the SAMD21 model 0.2 mm gives 28,342
#: triangles and 0.02 mm gives 40,624 -- a 43% increase in size for a
#: difference no one can see on a 20 mm board rendered 400 pixels wide. 0.05
#: sits where the curve flattens, at 36,984, and 0.05 mm is also finer than the
#: three decimal places the pad map is exact to.
DEFLECTION = 0.05

#: Radians of angular deviation, OCC's second tessellation control. Its own
#: default; named here so that both knobs are visible rather than one.
ANGULAR = 0.5


@dataclasses.dataclass(frozen=True)
class Model:
    """One vendor archive, and which boards in the catalogue it is a model of."""

    chip: str
    url: str
    #: The published `Content-Length`, checked on fetch. **A vendor who
    #: replaces a file silently is the failure this catches**; the alternative
    #: is a checksum, which would be this repository asserting a number the
    #: vendor never published.
    size: int
    boards: tuple[str, ...]


#: The four reachable models, verified by HTTP HEAD on 2026-08-26.
#:
#: **The XIAO ESP32-C3 is missing and that is a fact rather than an oversight.**
#: Its wiki links GrabCAD -- a third-party host behind a login, with its own
#: terms -- and not `files.seeedstudio.com`. So `XIAO-ESP32-C3-DIP`,
#: `-DIP-SMD` and `-SMD` keep the extruded footprint, and the page says which
#: it is showing rather than leaving a reader to notice that one board looks
#: different.
MODELS: tuple[Model, ...] = (
    Model(
        chip="SAMD21",
        url="https://files.seeedstudio.com/wiki/Seeeduino-XIAO/res/"
            "seeeduino-xiao-samd21-3d-model.zip",
        size=18_255_477,
        boards=("XIAO-SAMD21-DIP", "XIAO-SAMD21-SMD"),
    ),
    Model(
        chip="RP2040",
        url="https://files.seeedstudio.com/wiki/XIAO-RP2040/res/"
            "seeed-studio-xiao-rp2040-3d-model.zip",
        size=3_399_090,
        boards=("XIAO-RP2040-DIP", "XIAO-RP2040-SMD"),
    ),
    Model(
        chip="ESP32-S3",
        url="https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/"
            "seeed-studio-xiao-esp32s3-3d_model.zip",
        size=4_382_912,
        boards=("XIAO-ESP32-S3-DIP", "XIAO-ESP32-S3-SMD", "XIAO-ESP32-S3-SMD_PAD"),
    ),
    Model(
        chip="nRF52840",
        url="https://files.seeedstudio.com/wiki/XIAO-BLE/"
            "seeed-studio-xiao-nrf52840-3d-model.zip",
        size=8_849_412,
        boards=("XIAO-nRF52840-DIP", "XIAO-nRF52840-SMD"),
    ),
)


class Unavailable(Exception):
    """OCP is not installed. Exit 3 and say SKIPPED, never pass quietly."""


@dataclasses.dataclass
class Mesh:
    """Triangles grouped by the colour the vendor gave them.

    One list per colour rather than one list with a colour attribute, because
    that is the shape glTF wants -- a primitive per material -- and converting
    between the two would be work in both directions.
    """

    #: `"#rrggbb"` -> (positions, normals, indices), each already flat.
    groups: dict[str, tuple[list[float], list[float], list[int]]]

    def triangles(self) -> int:
        return sum(len(i) // 3 for _, _, i in self.groups.values())

    def vertices(self) -> int:
        return sum(len(p) // 3 for p, _, _ in self.groups.values())


@dataclasses.dataclass(frozen=True)
class Extent:
    """A bounding box in millimetres, in the source's own axes."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def thickness(self) -> float:
        return self.zmax - self.zmin


def model_for(chip: str) -> Model:
    """The model for `chip`, or an error naming every chip there is one for."""
    for candidate in MODELS:
        if candidate.chip == chip:
            return candidate
    known = ", ".join(m.chip for m in MODELS)
    raise SystemExit(f"no vendor model for {chip!r}. There is one for: {known}")


def fetch(model: Model) -> pathlib.Path:
    """Download the archive if it is not already here, and return its path.

    The size is checked against the one this file records. A vendor is free to
    replace a file, and a mesh built from a different revision than the one
    these numbers were measured on would be wrong in a way nothing else here
    would catch.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / f"{model.chip}.zip"
    if not archive.is_file():
        print(f"  fetch  {model.url}")
        with urllib.request.urlopen(model.url) as response:  # noqa: S310 - https, fixed
            archive.write_bytes(response.read())
    actual = archive.stat().st_size
    if actual != model.size:
        raise SystemExit(
            f"{archive} is {actual:,} bytes and this file records "
            f"{model.size:,}. The vendor's archive changed; re-measure the "
            f"model before trusting a mesh built from it."
        )
    return archive


def extract_step(archive: pathlib.Path) -> pathlib.Path:
    """Pull the one `.step` out of the archive, beside it."""
    with zipfile.ZipFile(archive) as bundle:
        members = [n for n in bundle.namelist() if n.lower().endswith((".step", ".stp"))]
        if len(members) != 1:
            raise SystemExit(
                f"{archive} holds {len(members)} STEP files, expected exactly "
                f"one: {members}"
            )
        step = archive.with_suffix(".step")
        if not step.is_file():
            step.write_bytes(bundle.read(members[0]))
        return step


def read(step: pathlib.Path):
    """Load the STEP with colours, and return `(shape, styles)`.

    `STEPCAFControl_Reader` rather than `STEPControl_Reader`: the plain reader
    gives geometry and drops every `STYLED_ITEM`, and a board rendered in one
    grey is not the board. This file carries 1,014 of them across 16 colours.
    """
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDF import TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.TopLoc import TopLoc_Location
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.XCAFPrs import XCAFPrs, XCAFPrs_IndexedDataMapOfShapeStyle
    except ImportError as exc:
        raise Unavailable(str(exc)) from exc

    document = TDocStd_Document(TCollection_ExtendedString("step"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.ReadFile(str(step))
    reader.Transfer(document)

    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    if roots.Length() != 1:
        raise SystemExit(f"{step} has {roots.Length()} root shapes, expected 1")
    top = roots.Value(1)

    styles = XCAFPrs_IndexedDataMapOfShapeStyle()
    XCAFPrs.CollectStyleSettings_s(top, TopLoc_Location(), styles)
    # **The document must outlive this call.** The shape holds labels into it,
    # and letting it be collected here produced an empty style map -- returned
    # so the caller keeps a reference.
    return tool.GetShape_s(top), styles, document


def box_of(shape) -> Extent:
    """A shape's bounding box, in the STEP's own millimetres and axes."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return Extent(xmin, xmax, ymin, ymax, zmin, zmax)


def spans(extent: Extent) -> tuple[float, float, float]:
    """A box's three extents, indexed 0, 1, 2 for x, y, z."""
    return (extent.width, extent.height, extent.thickness)


def up_axis(shape) -> int:
    """Which axis the board's thickness runs along: 0, 1 or 2.

    **These four files do not agree on it, and finding that out is the reason
    this function exists.** Seeed's SAMD21 and RP2040 models are Z-up, in the
    convention KiCad and most mechanical CAD use. The ESP32-S3 and nRF52840
    models are Y-up. Measured 2026-08-26 -- assembly extents in the file's own
    axes:

        SAMD21    22.601 x 17.901 x  4.511      thin in z
        RP2040    17.514 x 22.014 x  4.419      thin in z
        ESP32-S3  22.484 x  4.462 x 17.782      thin in y
        nRF52840  22.482 x  4.460 x 17.780      thin in y

    A board is flat, so the assembly's own smallest extent is the thickness --
    including the components standing on it, which are short compared with a
    20 mm board in both directions. Assuming z would have laid two of the four
    on their sides, and the tell would have been a picture rather than an
    error.
    """
    return min(range(3), key=lambda axis: spans(box_of(shape))[axis])


def pcb_solid(shape, up: int):
    """The solid that is the printed circuit board.

    **Chosen by shape rather than by name or by index**, because the file names
    nothing: it is the solid with the largest area in the plane the board lies
    in, which is the one every component stands on. Index would be a guess that
    happens to work on one file.

    This matters because **the assembly bounding box is not the board**. On the
    SAMD21 model the USB-C connector reaches x 11.950 while the PCB stops at
    10.650, so a model centred on the assembly sits 0.65 mm off its own pads --
    close enough to look almost right, which is the worst amount to be wrong by.
    """
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    plane = [axis for axis in range(3) if axis != up]
    best, best_area = None, -1.0
    walk = TopExp_Explorer(shape, TopAbs_SOLID)
    while walk.More():
        solid = TopoDS.Solid_s(walk.Current())
        size = spans(box_of(solid))
        area = size[plane[0]] * size[plane[1]]
        if area > best_area:
            best, best_area = solid, area
        walk.Next()
    if best is None:
        raise SystemExit("the model has no solids")
    return best


def colour_of(styles, shape) -> str:
    """`"#rrggbb"` for a shape, or `""` where the vendor set none."""
    if not styles.Contains(shape):
        return ""
    style = styles.FindFromKey(shape)
    if not style.IsSetColorSurf():
        return ""
    colour = style.GetColorSurf()
    return "#{:02x}{:02x}{:02x}".format(
        round(colour.Red() * 255), round(colour.Green() * 255),
        round(colour.Blue() * 255),
    )


#: What a face with no style of its own is painted.
#:
#: Named rather than inline because it is the one colour in this file that is
#: not the vendor's, and a reader should be able to find every such number by
#: searching. Mid grey reads as "unpainted" against every colour in the four
#: models rather than pretending to be a material.
UNSTYLED = "#808080"


@dataclasses.dataclass(frozen=True)
class Frame:
    """How to get from one file's axes to the one frame the page draws in.

    **The four models do not share a convention**, so this is computed per file
    rather than written down once: two are Z-up and two are Y-up, and the
    RP2040's board runs the short way across its own x. The canonical frame is
    the same for all of them -- the PCB's long side along glTF x, its thickness
    along glTF y with the underside at zero, its short side along glTF z, and
    the PCB centred on the origin in both horizontal axes.

    That is the frame `webui/static/board3d.js` expects, and having exactly one
    means the renderer contains no per-board correction and no board-shaped
    special case.
    """

    #: Which source axis becomes glTF x, y and z.
    long_axis: int
    up: int
    short_axis: int
    #: `+1` or `-1` on the short axis, whichever leaves the frame
    #: right-handed. **Getting this wrong mirrors the board**, which on a part
    #: whose two headers carry different pins is a wrong picture rather than an
    #: ugly one -- and a mirrored XIAO looks entirely plausible.
    handedness: float
    #: Subtracted from a point before the axes are permuted.
    origin: tuple[float, float, float]

    def place(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        moved = (x - self.origin[0], y - self.origin[1], z - self.origin[2])
        return (moved[self.long_axis],
                moved[self.up],
                self.handedness * moved[self.short_axis])


def handedness_of(order: tuple[int, int, int]) -> float:
    """`+1` or `-1`: what the short axis must be scaled by to stay a rotation.

    A signed permutation is a rotation only when its determinant is `+1`, and
    for a permutation with all-positive signs that determinant is the parity of
    the rearrangement. Counting inversions rather than writing a 3x3 keeps it
    to three comparisons instead of nine numbers of which six are zero.

    **A named function rather than six lines inside `frame_for`**, and the
    reason is a test rather than tidiness: `frame_for` needs a loaded shape and
    therefore needs OpenCASCADE, and this is the part that has to be right on a
    machine that has neither. A test that recomputed the parity to check the
    parity would be the defect `tests/cortexm0/test_samd21_arduino.py` records
    twice -- a right-hand side imported from the thing under test.
    """
    parity = 1.0
    for i in range(3):
        for j in range(i + 1, 3):
            if order[i] > order[j]:
                parity = -parity
    return parity


def frame_for(shape) -> tuple[Frame, Extent, float, float]:
    """The canonical frame for a model, and the PCB's size in it.

    Returns `(frame, pcb extent in the file's own axes, long, short)`.
    """
    up = up_axis(shape)
    pcb = box_of(pcb_solid(shape, up))
    size = spans(pcb)
    plane = [axis for axis in range(3) if axis != up]
    long_axis, short_axis = sorted(plane, key=lambda axis: -size[axis])

    parity = handedness_of((long_axis, up, short_axis))

    lows = (pcb.xmin, pcb.ymin, pcb.zmin)
    highs = (pcb.xmax, pcb.ymax, pcb.zmax)
    origin = [0.0, 0.0, 0.0]
    for axis in range(3):
        origin[axis] = lows[axis] if axis == up else (lows[axis] + highs[axis]) / 2

    frame = Frame(long_axis=long_axis, up=up, short_axis=short_axis,
                  handedness=parity, origin=(origin[0], origin[1], origin[2]))
    return frame, pcb, size[long_axis], size[short_axis]


def tessellate(shape, styles, deflection: float, frame: Frame) -> Mesh:
    """Mesh every face, grouped by colour, in glTF axes and millimetres."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection, False, ANGULAR, True)

    groups: dict[str, tuple[list[float], list[float], list[int]]] = {}
    walk = TopExp_Explorer(shape, TopAbs_FACE)
    while walk.More():
        face = TopoDS.Face_s(walk.Current())
        walk.Next()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            continue

        key = colour_of(styles, face) or UNSTYLED
        positions, normals, indices = groups.setdefault(key, ([], [], []))
        base = len(positions) // 3
        transform = location.Transformation()
        reversed_face = face.Orientation() == TopAbs_REVERSED

        for node in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(node).Transformed(transform)
            positions.extend(frame.place(point.X(), point.Y(), point.Z()))
            normals.extend((0.0, 0.0, 0.0))

        first = len(indices)
        # A reversed face's triangles wind the other way, and so does every
        # face if the frame had to mirror one axis. Either alone flips the
        # outside inward; both together cancel, which is why this is one
        # exclusive-or rather than two independent swaps.
        backwards = reversed_face != (frame.handedness < 0)
        for index in range(1, triangulation.NbTriangles() + 1):
            a, b, c = triangulation.Triangle(index).Get()
            if backwards:
                a, c = c, a
            indices.extend((base + a - 1, base + b - 1, base + c - 1))
        accumulate_normals(positions, normals, indices, first)

    for positions, normals, _ in groups.values():
        normalise(normals)
    return Mesh(groups=groups)


def accumulate_normals(positions: list[float], normals: list[float],
                       indices: list[int], first: int) -> None:
    """Add each triangle's own normal to the three vertices that carry it.

    **Computed here rather than read off the surface**, and the reason is a
    property of a B-rep rather than a shortcut. Every face is meshed on its own
    and shares no vertex with its neighbours, so averaging within a face gives
    a cylinder smooth shading and still leaves a crease where two faces meet --
    which is what the solid actually looks like. Asking OCC for a surface
    normal per node would produce the same answer at ten times the cost.

    Unnormalised on purpose: a triangle's cross product is twice its area, so
    summing them weights each face's contribution by how much of the vertex it
    is, which is the standard and the better average.
    """
    for corner in range(first, len(indices), 3):
        a, b, c = (indices[corner] * 3, indices[corner + 1] * 3,
                   indices[corner + 2] * 3)
        ux = positions[b] - positions[a]
        uy = positions[b + 1] - positions[a + 1]
        uz = positions[b + 2] - positions[a + 2]
        vx = positions[c] - positions[a]
        vy = positions[c + 1] - positions[a + 1]
        vz = positions[c + 2] - positions[a + 2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        for vertex in (a, b, c):
            normals[vertex] += nx
            normals[vertex + 1] += ny
            normals[vertex + 2] += nz


def normalise(normals: list[float]) -> None:
    """Scale every accumulated normal to unit length, in place.

    A zero-length one is left pointing up rather than producing a division by
    zero: it means a degenerate triangle, which the tessellator does emit at
    the poles of a revolved surface, and one lit-wrong vertex is a better
    outcome than a crash on import.
    """
    for start in range(0, len(normals), 3):
        x, y, z = normals[start], normals[start + 1], normals[start + 2]
        length = (x * x + y * y + z * z) ** 0.5
        if length == 0.0:
            normals[start + 1] = 1.0
            continue
        normals[start] = x / length
        normals[start + 1] = y / length
        normals[start + 2] = z / length


def write_glb(mesh: Mesh, path: pathlib.Path, chip: str, source: str,
              pcb: tuple[float, float, float]) -> int:
    """Write the mesh as glTF 2.0 binary. Returns the byte count.

    One primitive and one material per colour. Hand-written rather than through
    a library for the reason the module docstring gives about dependencies --
    and because what is emitted here is a deliberately narrow subset: triangles,
    positions, normals, a base colour. No scenes graph, no textures, no
    animation, nothing that would need a general writer.
    """
    buffer = bytearray()
    views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    primitives: list[dict[str, object]] = []

    def pad_to_four() -> None:
        while len(buffer) % 4:
            buffer.append(0)

    for colour, (positions, normals, indices) in sorted(mesh.groups.items()):
        if not indices:
            continue
        pad_to_four()
        offset = len(buffer)
        buffer.extend(struct.pack(f"<{len(positions)}f", *positions))
        views.append({"buffer": 0, "byteOffset": offset,
                      "byteLength": len(positions) * 4, "target": 34962})
        position_view = len(views) - 1

        pad_to_four()
        offset = len(buffer)
        buffer.extend(struct.pack(f"<{len(normals)}f", *normals))
        views.append({"buffer": 0, "byteOffset": offset,
                      "byteLength": len(normals) * 4, "target": 34962})
        normal_view = len(views) - 1

        pad_to_four()
        offset = len(buffer)
        buffer.extend(struct.pack(f"<{len(indices)}I", *indices))
        views.append({"buffer": 0, "byteOffset": offset,
                      "byteLength": len(indices) * 4, "target": 34963})
        index_view = len(views) - 1

        # glTF requires min and max on a POSITION accessor. Not decoration:
        # a viewer frames the model from them without reading the buffer.
        xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
        accessors.append({
            "bufferView": position_view, "componentType": 5126,
            "count": len(positions) // 3, "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        })
        accessors.append({"bufferView": normal_view, "componentType": 5126,
                          "count": len(normals) // 3, "type": "VEC3"})
        accessors.append({"bufferView": index_view, "componentType": 5125,
                          "count": len(indices), "type": "SCALAR"})

        red = int(colour[1:3], 16) / 255
        green = int(colour[3:5], 16) / 255
        blue = int(colour[5:7], 16) / 255
        materials.append({
            "name": colour,
            "pbrMetallicRoughness": {
                "baseColorFactor": [red, green, blue, 1.0],
                "metallicFactor": 0.1,
                "roughnessFactor": 0.6,
            },
            "doubleSided": True,
        })
        primitives.append({
            "attributes": {"POSITION": len(accessors) - 3,
                           "NORMAL": len(accessors) - 2},
            "indices": len(accessors) - 1,
            "material": len(materials) - 1,
        })

    document = {
        "asset": {
            "version": "2.0",
            "generator": "OpenHardware tools/import_3d_model.py",
            # **The spec's unit is the metre and this is millimetres.** Said
            # in the file rather than only in the docstring, because the file
            # is the thing that travels.
            "extras": {
                "units": "mm", "chip": chip, "source": source,
                # The PCB alone, in the frame above: long side, short
                # side, thickness. **The page needs the thickness and
                # cannot measure it**, because the mesh it loads includes
                # the components and its bounding box is the assembly.
                # It is what puts a pad post on the board rather than
                # sunk into it.
                "pcb": {"long": round(pcb[0], 4), "short": round(pcb[1], 4),
                        "thickness": round(pcb[2], 4)},
            },
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": chip}],
        "meshes": [{"name": chip, "primitives": primitives}],
        "accessors": accessors,
        "bufferViews": views,
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
    }

    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    bin_chunk = bytes(buffer) + b"\x00" * (-len(buffer) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        out.write(struct.pack("<III", 0x46546C67, 2, total))
        out.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
        out.write(json_chunk)
        out.write(struct.pack("<II", len(bin_chunk), 0x004E4942))
        out.write(bin_chunk)
    return total


def report_alignment(model: Model, long: float, short: float,
                     thickness: float) -> None:
    """Print how the model's PCB compares with the pad map, in millimetres.

    **Printed rather than asserted.** These are two independent measurements of
    the same object -- the vendor's KiCad footprint through
    `tools/import_kicad_board.py`, and the vendor's mechanical model -- and
    what they agree to is a finding, not a requirement. A test that demanded
    zero would either be lying or would have to be relaxed until it meant
    nothing.
    """
    sys.path.insert(0, str(REPO))
    from webui import pinmap

    for board in model.boards:
        layout = pinmap.load(board)
        if layout is None:
            print(f"    {board}: no pad map")
            continue
        placed = [pad for pad in layout.pads if pad.x is not None]
        if not placed:
            print(f"    {board}: pad map has no positions")
            continue
        # `webui/boards/*.json` records pixels at a stated pixels-per-mm; the
        # model is millimetres. One division, here, rather than at four sites.
        xs = [pad.x / PX_PER_MM for pad in placed]
        ys = [pad.y / PX_PER_MM for pad in placed]
        # The pad map's own long side, matched to the model's long side. Both
        # are sorted rather than assumed: `webui/boards/*.json` is landscape
        # for every board here and the models are not, which is the whole
        # reason `Frame` exists.
        span = sorted((max(xs) - min(xs), max(ys) - min(ys)), reverse=True)
        print(f"    {board}: {len(placed)} pads span "
              f"{span[0]:.3f} x {span[1]:.3f} mm; PCB is "
              f"{long:.3f} x {short:.3f} x {thickness:.3f} mm; margin "
              f"{(long - span[0]) / 2:.3f} x {(short - span[1]) / 2:.3f} mm each side")


#: Pixels per millimetre in `webui/boards/*.json`, stated in every one of their
#: `derivation` fields. Repeated here rather than parsed because it is a
#: property of how those files were generated, not of any one of them.
PX_PER_MM = 8.0


def convert(model: Model, deflection: float, check: bool) -> int:
    """Fetch, tessellate and write one model. Returns the glTF's byte count."""
    print(f"{model.chip}:")
    archive = fetch(model)
    step = extract_step(archive)
    print(f"  parse  {step.name}  {step.stat().st_size:,} bytes")

    shape, styles, _document = read(step)
    frame, pcb, long, short = frame_for(shape)
    whole = box_of(shape)
    print(f"  axes   file is {'xyz'[frame.up]}-up; "
          f"long side is its {'xyz'[frame.long_axis]}; "
          f"{'mirrored' if frame.handedness < 0 else 'right-handed'} as read")
    print(f"  pcb    {long:.3f} x {short:.3f} x {spans(pcb)[frame.up]:.3f} mm"
          f"   (assembly {whole.width:.3f} x {whole.height:.3f} x "
          f"{whole.thickness:.3f} mm in the file's own axes)")

    mesh = tessellate(shape, styles, deflection, frame)
    print(f"  mesh   {mesh.triangles():,} triangles, {mesh.vertices():,} vertices, "
          f"{len(mesh.groups)} colours at {deflection} mm deflection")
    report_alignment(model, long, short, spans(pcb)[frame.up])

    if check:
        print("  write  skipped (--check)")
        return 0
    out = OUT / f"{model.chip}.glb"
    size = write_glb(mesh, out, model.chip, model.url,
                     (long, short, spans(pcb)[frame.up]))
    print(f"  write  {out.relative_to(REPO)}  {size:,} bytes")
    return size


def read_extras(glb: pathlib.Path) -> dict[str, object]:
    """`asset.extras` out of a `.glb`, without loading its geometry.

    The JSON chunk is the first one and its length is in the header, so this
    reads a few hundred bytes of a file that may be a megabyte and a half.
    """
    with glb.open("rb") as handle:
        magic, _version, _total = struct.unpack("<III", handle.read(12))
        if magic != 0x46546C67:
            raise SystemExit(f"{glb} is not a glb")
        length, kind = struct.unpack("<II", handle.read(8))
        if kind != 0x4E4F534A:
            raise SystemExit(f"{glb}'s first chunk is not JSON")
        document = json.loads(handle.read(length).decode("utf-8"))
    return document.get("asset", {}).get("extras", {})


def write_index() -> pathlib.Path:
    """Write `models/index.json`: which board has a model, and from where.

    **Board name is the key, not chip**, because that is what the page has:
    `webui/api.py`'s `pin_view` reports the board it drew and knows nothing
    about chips, and teaching `board3d.js` a board-to-chip table would be a
    second copy of `webui/boards/catalogue.py` living in JavaScript.

    Written for every model in the table whether or not its `.glb` is present,
    so that a checkout which has not run the importer gets an index naming what
    is missing rather than an index that quietly says nothing exists.
    """
    boards: dict[str, dict[str, object]] = {}
    for model in MODELS:
        mesh = OUT / f"{model.chip}.glb"
        for board in model.boards:
            boards[board] = {
                "chip": model.chip,
                "file": f"/models/{model.chip}.glb" if mesh.is_file() else None,
                "bytes": mesh.stat().st_size if mesh.is_file() else 0,
                "source": model.url,
            }
            if mesh.is_file():
                boards[board]["pcb"] = read_extras(mesh).get("pcb")
    index = OUT / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({
        "units": "mm",
        "note": (
            "The vendor's own mechanical model, tessellated by "
            "tools/import_3d_model.py. A board absent here has no reachable "
            "vendor model and is drawn as an extruded footprint instead."
        ),
        "boards": boards,
    }, indent=2) + "\n", encoding="utf-8")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chip", help="one chip from the table")
    parser.add_argument("--all", action="store_true", help="every model there is")
    parser.add_argument("--check", action="store_true",
                        help="report and write nothing")
    parser.add_argument("--deflection", type=float, default=DEFLECTION,
                        help=f"chord error in mm (default {DEFLECTION})")
    args = parser.parse_args(argv)

    if not args.all and not args.chip:
        parser.error("one of --chip or --all")
    wanted = MODELS if args.all else (model_for(args.chip),)

    try:
        total = sum(convert(model, args.deflection, args.check) for model in wanted)
    except Unavailable as exc:
        # The shape `CLAUDE.md` states for a checker that cannot find its
        # source: exit 3, say SKIPPED, never pass quietly.
        print(f"SKIPPED: OpenCASCADE is not installed ({exc}).\n"
              f"  pip install cadquery-ocp", file=sys.stderr)
        return 3
    if not args.check:
        index = write_index()
        print(f"\n{total:,} bytes of glTF for {len(wanted)} model(s); "
              f"{index.relative_to(REPO)} rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
