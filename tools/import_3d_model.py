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
              pcb: tuple[float, float, float],
              extras: dict[str, object] | None = None) -> int:
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
                **(extras or {}),
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


# --- the parts a wire connects to -------------------------------------------


@dataclasses.dataclass(frozen=True)
class Part:
    """One component model from KiCad's own 3D library."""

    #: The library folder it lives in, which is also the folder the page shows
    #: it under. **KiCad's own tree, not a taxonomy invented here**: a reader
    #: who knows `LED_THT` can find the same file, and a category this
    #: repository made up would be one more thing to keep true.
    library: str
    name: str
    label: str
    #: The colour, in the file, of the surface that shows what the pin is
    #: doing. **Stated per part rather than guessed**: "the least grey group"
    #: works on an LED and not on a black buzzer, and a rule that works on one
    #: file is a rule that will be wrong on the next one somebody adds.
    lens: str
    #: What the two leads are called, in the order this file's own geometry
    #: puts them -- see `lead_tips`, which sorts them by x.
    terminals: tuple[str, str]

    @property
    def slug(self) -> str:
        """What the page and the mesh file call it."""
        return self.name.replace(".", "_")

    @property
    def url(self) -> str:
        return f"{KICAD_3D}/{self.library}.3dshapes/{self.name}.step"


#: Where KiCad's 3D library actually lives.
#:
#: **GitLab, and not the GitHub mirror**, which is what this fetched until
#: 2026-08-27. `KiCad/kicad-packages3D` on GitHub is a mirror and it is not the
#: same tree: counted that day, `Connector_USB` had 5 entries there against 13
#: here, `Connector_BarrelJack` 4 against 5, and `Button_Switch_THT` 127
#: against 82 -- so it diverges in both directions and is not simply older.
#:
#: Nothing already imported was wrong: every model this repository had fetched
#: was byte-for-byte identical in the two. What the mirror cost was COVERAGE,
#: and a conclusion drawn from it -- "there is no model for this part" -- was
#: a claim about the mirror wearing the library's name. That is the same defect
#: as OH-29's census of Seeed's repository, which closed a question for a day
#: by stating its conclusion without its scope.
KICAD_3D = "https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/master"

#: **KiCad's `kicad-packages3D`, not a vendor's.** Seeed publishes no 3D model
#: for the Grove modules -- checked 2026-08-27, the Grove Red LED wiki lists a
#: schematic PDF and a Codecraft zip and nothing else -- and the only LEDs in
#: the trees this repository already fetches are 0603 chips 1.6 mm long, which
#: are real LEDs and not things anybody wires a jumper to.
#:
#: KiCad's library is the standard source for exactly this and these are real
#: parts at real sizes, measured 2026-08-27 by tessellating each one: the LEDs
#: are 3.4, 5.4 and 10.5 mm across on 2.540 mm leads, and the buzzer is 13 mm
#: across on 7.600 mm leads. **Licence: CC-BY-SA-4.0 with the library
#: exception**, which is why these are fetched and not vendored, the same as
#: the vendors' board models and for the reason `rules/licence-hygiene.md`
#: section 4 gives.
#:
#: **Only parts that can honestly show a pin state are here.** A tactile
#: switch is in the same library and is not: it is an *input*, it would drive
#: a pin, and OH-73 records at length that driving a pin needs the `PIN`
#: registers this repository has already written down as unmodelled. A switch
#: on this bench would be a part that does nothing, which is worse than no
#: switch at all.
PARTS: tuple[Part, ...] = (
    Part(library="LED_THT", name="LED_D3.0mm", label="3 mm LED",
         lens="#720301", terminals=("cathode", "anode")),
    Part(library="LED_THT", name="LED_D5.0mm", label="5 mm LED",
         lens="#720301", terminals=("cathode", "anode")),
    Part(library="LED_THT", name="LED_D10.0mm", label="10 mm LED",
         lens="#720301", terminals=("cathode", "anode")),
    #: **The red mark on its case, and it means driven rather than sounding.**
    #: A buzzer makes a noise and this page has no audio, so nothing here can
    #: show what it is actually doing. Lighting its polarity mark says the one
    #: thing that is true -- the pin wired to it is high -- and the panel says
    #: the same in words. Inventing a sound would be the failure this
    #: repository ranks worst; leaving a part on the bench that shows nothing
    #: at all would be the one it ranks second.
    Part(library="Buzzer_Beeper", name="Buzzer_12x9.5RM7.6", label="12 mm buzzer",
         lens="#9e2705", terminals=("negative", "positive")),
)


#: KiCad's 3D library has one convention and every file in it keeps it: the
#: part sits with the board's surface at z = 0, its body in +z and its leads
#: in -z, in millimetres.
#:
#: **So a part needs none of `frame_for`'s heuristics and must not use them.**
#: That function exists because four vendors disagreed about which axis was
#: up; it decides from the assembly's thinnest extent, which is a fact about a
#: flat board and nonsense about a 5 mm LED. Run on this file it answers x-up,
#: because an LED on its leads is 14.1 mm tall and 5.4 mm across.
PART_UP = 2

#: Millimetres above the lowest vertex of a lead that still counts as its tip.
#: A tessellated cylinder's end cap is flat, so its ring is all at one height
#: and any small number does; 0.05 is the tessellation's own chord tolerance,
#: which is the largest a vertex can be off by.
LEAD_RING = 0.05


def part_frame(shape) -> Frame:
    """KiCad's convention, as a `Frame`: z up, and the board plane at zero.

    The origin is the body's centre in x and y and **z = 0 exactly**, not the
    model's own minimum: zero is where the part meets the board, and the leads
    hang below it. Centring on the bounding box instead would bury a part by
    half the length of its legs.
    """
    box = box_of(shape)
    return Frame(
        long_axis=0, up=PART_UP, short_axis=1,
        handedness=handedness_of((0, PART_UP, 1)),
        origin=((box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2, 0.0),
    )


def lead_tips(mesh: Mesh, lens: str) -> list[list[float]]:
    """Where a wire attaches, taken from the model rather than from a datasheet.

    Every group that is not the lens is metal, so the leads are the lowest
    points in it -- and there are two of them, one either side of the body.
    Splitting on the sign of x and taking the lowest vertex of each gives the
    two tips.

    **Derived and not written down**, because a lead spacing typed in from a
    datasheet is a second source that can disagree with the mesh, and it would
    disagree silently: a wire would meet nothing, an inch from the leg.
    """
    tips: list[list[float]] = []
    for side in (-1, 1):
        here: list[tuple[float, float, float]] = []
        for colour, (positions, _normals, _indices) in mesh.groups.items():
            if colour == lens:
                continue
            for at in range(0, len(positions), 3):
                x = positions[at]
                if (x < 0) != (side < 0):
                    continue
                here.append((x, positions[at + 1], positions[at + 2]))
        if not here:
            continue
        # **The whole ring at the tip, averaged, and not the single lowest
        # vertex.** A lead is a cylinder, so its lowest vertices are a circle
        # of them and which one comes first is an artefact of the
        # tessellation: the first version of this took one each side and got
        # -1.270 and +0.870 for a part whose leads are 2.54 mm apart -- one
        # answer on the lead's axis and one on its rim, and no way to tell
        # which from the number alone.
        floor = min(point[1] for point in here)
        ring = [point for point in here if point[1] <= floor + LEAD_RING]
        tips.append([sum(point[axis] for point in ring) / len(ring)
                     for axis in range(3)])
    return tips


def convert_part(part: Part, deflection: float, check: bool) -> int:
    """Fetch, tessellate and write one part. Returns the glTF's byte count."""
    print(f"{part.library}/{part.name}:")
    CACHE.mkdir(parents=True, exist_ok=True)
    step = CACHE / f"part-{part.slug}.step"
    if not step.is_file():
        print(f"  fetch  {part.url}")
        with urllib.request.urlopen(part.url) as response:  # noqa: S310 - https
            step.write_bytes(response.read())
    print(f"  parse  {step.name}  {step.stat().st_size:,} bytes")

    shape, styles, _document = read(step)
    whole = box_of(shape)
    frame = part_frame(shape)
    mesh = tessellate(shape, styles, deflection, frame)
    print(f"  size   {whole.width:.3f} x {whole.height:.3f} x "
          f"{whole.thickness:.3f} mm, z-up by KiCad's convention")
    print(f"  mesh   {mesh.triangles():,} triangles, {len(mesh.groups)} colours: "
          f"{sorted(mesh.groups)}")
    if part.lens not in mesh.groups:
        raise SystemExit(
            f"{part.name} names {part.lens} as its lens and the model has "
            f"{sorted(mesh.groups)}. The file changed; re-read it before "
            f"trusting a part that cannot light up."
        )
    tips = lead_tips(mesh, part.lens)
    if len(tips) != 2:
        raise SystemExit(
            f"{part.name} has {len(tips)} lead tips and a wire needs two. "
            f"Either the model is not a two-lead part or its leads do not "
            f"straddle the origin."
        )
    print(f"  leads  {part.terminals[0]} at "
          f"({tips[0][0]:.3f}, {tips[0][1]:.3f}, {tips[0][2]:.3f}), "
          f"{part.terminals[1]} at "
          f"({tips[1][0]:.3f}, {tips[1][1]:.3f}, {tips[1][2]:.3f})")

    if check:
        print("  write  skipped (--check)")
        return 0
    out = OUT / "parts" / f"{part.slug}.glb"
    size = write_glb(mesh, out, part.slug, part.url, (whole.width, whole.height,
                                                     whole.thickness),
                     extras={"label": part.label, "lens": part.lens,
                             "library": part.library,
                             "terminals": [
                                 {"name": part.terminals[i],
                                  "at": [round(v, 4) for v in tips[i]]}
                                 for i in range(2)],
                             "licence": "CC-BY-SA-4.0 with the KiCad library "
                                        "exception; fetched, not vendored"})
    print(f"  write  {out.relative_to(REPO)}  {size:,} bytes")
    return size


#: `(board, chip, file stem)` for every board whose model is COMPOSED by
#: `tools/compose_board_3d.py` out of CAD, because no vendor publishes a mesh
#: for it. Named here rather than in that module because `write_index` is the
#: one writer of `index.json` and the composer already imports this file's
#: tessellator -- naming them there and importing them here would be a cycle.
#:
#: The chip is repeated rather than looked up: `webui/boards/catalogue.py`
#: knows it, and importing the board catalogue into a mesh tool to learn one
#: string is the layering `tools/check_layering.py` exists to prevent.
COMPOSED: tuple[tuple[str, str, str], ...] = (
    ("Arduino Uno", "ATmega328P", "Arduino-Uno"),
)


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
    for board, chip, slug in COMPOSED:
        mesh = OUT / f"{slug}.glb"
        extras = read_extras(mesh) if mesh.is_file() else {}
        boards[board] = {
            "chip": chip,
            "file": f"/models/{slug}.glb" if mesh.is_file() else None,
            "bytes": mesh.stat().st_size if mesh.is_file() else 0,
            "source": extras.get("geometry", ""),
            # **The page must be able to tell these apart.** A composed model
            # is not the vendor's mesh and the caption may not claim it is:
            # its outline is the vendor's CAD, its components are KiCad's
            # published models, and its colour is somebody's artwork. Three
            # sources, and the panel says so.
            "composed": True,
            "pcb": extras.get("pcb"),
            "pcb_offset": extras.get("pcb_offset"),
            "drawn": extras.get("drawn", []),
            "modelled": extras.get("modelled", []),
            "absent": extras.get("absent", []),
            "components": extras.get("components", ""),
            "pcb_colour_source": extras.get("pcb_colour_source", ""),
        }
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
    # Grouped by KiCad's own library folder, which is what the page shows as
    # a folder. Written whether or not each mesh is present, so a checkout
    # that has not run the importer gets a menu that says what is missing
    # rather than an empty one that says nothing exists.
    libraries: dict[str, list[dict[str, object]]] = {}
    for part in PARTS:
        mesh = OUT / "parts" / f"{part.slug}.glb"
        libraries.setdefault(part.library, []).append({
            "slug": part.slug,
            "name": part.name,
            "label": part.label,
            "file": f"/models/parts/{part.slug}.glb" if mesh.is_file() else None,
            "bytes": mesh.stat().st_size if mesh.is_file() else 0,
            "source": part.url,
        })

    index = OUT / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({
        "units": "mm",
        "parts": {
            "source": "KiCad kicad-packages3D, CC-BY-SA-4.0 with the library "
                      "exception; fetched, not vendored",
            "libraries": libraries,
        },
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
    parser.add_argument("--parts", action="store_true",
                        help="the component models a wire connects to")
    parser.add_argument("--check", action="store_true",
                        help="report and write nothing")
    parser.add_argument("--deflection", type=float, default=DEFLECTION,
                        help=f"chord error in mm (default {DEFLECTION})")
    args = parser.parse_args(argv)

    if not args.all and not args.chip and not args.parts:
        parser.error("one of --chip, --all or --parts")
    wanted = MODELS if args.all else () if args.parts else (model_for(args.chip),)

    try:
        total = sum(convert(model, args.deflection, args.check) for model in wanted)
        if args.parts or args.all:
            total += sum(convert_part(part, args.deflection, args.check)
                         for part in PARTS)
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
