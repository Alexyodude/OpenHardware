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
import math
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

#: Radians of angular deviation, OCC's second tessellation control.
#:
#: **AND IT IS THE ONE THAT BINDS, WHICH `DEFLECTION` ABOVE DOES NOT SAY.**
#: That constant carries a measured paragraph and this one used to carry
#: "OCC's own default; named here so that both knobs are visible rather than
#: one" -- the reasoning was attached to the knob that was not deciding
#: anything. Measured 2026-08-28 on the 5 mm LED, re-reading the STEP for each
#: setting because `BRepMesh_IncrementalMesh` stores its triangulation ON the
#: shape and a second call against the same shape is a silent no-op:
#:
#:      defl 0.05  ang 0.5      461 triangles
#:      defl 0.01  ang 0.5    1,627          -- 5x finer chord, 3.5x the mesh
#:      defl 0.05  ang 0.2    1,509          -- 2.5x tighter angle, 3.3x
#:      defl 0.05  ang 0.1    4,959
#:
#: **Left at 0.5 anyway, and that is a decision rather than an omission.**
#: Rebuilding the whole corpus at 0.2 costs 4,170,400 -> 9,146,360 bytes and
#: changes 0.95% of the pixels in a close-up of the board. What looked like
#: faceting turned out to be `weld_seams` below: a hard shading line where a
#: periodic surface's parametrisation wraps, which costs nothing to remove and
#: is most of what 0.2 was buying. Revisit this when something is measured
#: that the weld does not fix.
ANGULAR = 0.5

#: Degrees a vertex's normal may sit from the mean of every normal at that
#: exact point before the two count as different surfaces.
#:
#: **What this is for is a seam, not an edge.** Every B-rep face is meshed on
#: its own and shares no vertex with its neighbours, so a cylinder or a sphere
#: -- which OCC meshes as ONE periodic face -- comes back with its wrap line
#: duplicated: two vertices at one point, each holding the average of only the
#: triangles on its own side. The surface is smooth there and the shading is
#: not, so a polished lid gets a dead-straight line across it. Measured on the
#: Arduino Uno: 509 such pairs in the `#a5a392` group alone, the worst 22.1
#: degrees apart, which is one facet's worth of normal concentrated onto a
#: single edge.
#:
#: 20 degrees from the mean, so 40 across a pair. That keeps a real edge: a
#: cube corner puts each of its three normals 54.7 degrees from their mean and
#: a 45-degree chamfer puts each 22.5, so both stay sharp, while a seam at
#: `ANGULAR`'s own 28.6 degrees puts each at 14.3 and welds. **Free in bytes:**
#: no vertex is added or removed, only normals are averaged.
SMOOTH_DEGREES = 20.0


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
    # --- OH-93 5.1: two meshes that were filed as not existing --------------
    #
    # **These two archives are the PCB downloads, and the mesh is INSIDE
    # them.** `docs/research/board-models/sources.json` records `"mesh": null`
    # for both, and that survey was careful -- it ran a positive control that
    # found all four models above at the exact URLs this table already held.
    # What it could not see is that Seeed ship a KiCad assembly export beside
    # the board file, under a link whose text says PCB.
    #
    # So the survey measured what it looked at, correctly, and looked at the
    # wrong thing: **it classified the LINKS on each wiki page and never
    # opened an archive.** That is the third shape of this same miss -- OH-29
    # read GitHub when the files were on the wiki, OH-93 read a GitHub census
    # that said Seeed publish no PCB, and this one read the wiki but only its
    # surface. Both were found by unzipping the five PCB archives for a
    # different reason entirely and reading the file list.
    #
    # Each holds exactly one `.step`, so `extract_step` takes them unchanged.
    Model(
        chip="MG24",
        url="https://files.seeedstudio.com/wiki/XIAO_MG24/Getting_Start/"
            "XIAO_MG24_v1.0_KiCad_260114.zip",
        size=1_583_091,
        boards=("XIAO-MG24-DIP", "XIAO-MG24-SMD"),
    ),
    # **This one's STEP header names the WRONG BOARD and the mesh is still
    # right.** `FILE_NAME('XIAO nRF54l15.step', ...)`, and the assembly root
    # is `XIAO nRF54l15 1` -- Seeed exported it from a project carrying the
    # sibling's name. A header is not evidence, so it was settled by content:
    #
    #   * The STEP holds `RGB4P-0.65-1X1X0.85MM` and `USON8-0.5-3X2MM`. Both
    #     boards' `.kicad_pcb` files were read and both packages are on the
    #     nRF54LM20A and on NEITHER the nRF54L15 -- the L15 has no RGB LED and
    #     no USON-8 flash at all.
    #   * Its four board solids are named `XIAO nRF54LM20A_PCB`, `_pad`,
    #     `_silkscreen` and `_soldermask`.
    #
    # Recorded because the cheap check -- read the header -- says the
    # opposite of the true answer, and somebody will run it again.
    Model(
        chip="nRF54LM20A",
        url="https://files.seeedstudio.com/wiki/XIAO_nRF54LM20A/getting_start/"
            "RES/XIAO_nRF54LM20A_V1.0_SCH&PCB_260508.zip",
        size=4_307_651,
        boards=("XIAO-nRF54LM20A-DIP", "XIAO-nRF54LM20A-SMD"),
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
#:
#: **It is deliberately absent from `FINISHES` below**, and it is the largest
#: colour group in the whole corpus -- 48,301 triangles across four vendor
#: models, counted 2026-08-27. A face the vendor did not style is a face whose
#: material nobody here knows, so giving it one would be exactly the pretending
#: this constant exists to avoid. `test_the_unstyled_colour_is_given_no_material`
#: is what keeps that true.
UNSTYLED = "#808080"

#: What an unstyled PRINTED CIRCUIT BOARD is painted, where the constant above
#: would otherwise leave it grey.
#:
#: **THIS IS A JUDGEMENT, AND `CERAMIC` BELOW IS THE ONLY OTHER ONE IN THIS
#: FILE.** Every other colour here is the vendor's, read out of their own STEP.
#: Nobody publishes this one. Searched on 2026-08-29 so that nobody repeats it:
#:
#:   * Seeed's STEP files give the PCB `#808080` -- `UNSTYLED`. On the RP2040
#:     that is 16,682 of 18,723 vertices.
#:   * **The `(stackup ...)` is where KiCad records a solder-mask colour, and
#:     six of the seven Seeed board files have one that states none.** Each
#:     carries six copper layers with thicknesses, five FR4 dielectrics with
#:     their `epsilon_r` and loss tangent, `(copper_finish "None")`, and both
#:     mask layers with `(thickness 0.01)` and no `(color ...)`. A vendor who
#:     filled in that table and left one field of it empty did not state a
#:     colour, and that is a stronger absence than an unopened file.
#:   * **`XIAO ESP32C3_v1.3.kicad_pcb` has no stackup at all**, which is what
#:     OH-97 measured and read as "the `.kicad_pcb` has no stackup". It is the
#:     one board of the seven that has none. Corrected 2026-08-30 by OH-99,
#:     which needed the six that do.
#:   * **The `pcb_color` this search used to cite is a NET CLASS field and not
#:     the board's.** It sits at `net_settings.classes[0]` in the `.kicad_pro`,
#:     beside `clearance`, `track_width`, `via_drill` and a `schematic_color`,
#:     and it is how nets of that class are highlighted in the two editors --
#:     which is why it has a schematic half at all. **Alpha zero is KiCad's
#:     UNSET**, so it states nothing; but it was never about the board, and all
#:     nine Seeed `.kicad_pro` files carry the identical default. Recorded
#:     because OH-97 and OH-99 both cited it as the board's colour.
#:   * Seeed's wiki says nothing: `XIAO_ESP32C3_Getting_Started` and
#:     `SeeedStudio_XIAO_Series_Introduction` fetched and searched for "black",
#:     "colour", "color", "matte", "glossy" -- zero mentions.
#:
#: So the value is chosen, and what is chosen is a DARK GREY rather than a
#: black: a solder mask is a thin translucent film over copper and glass-epoxy,
#: and it never reaches the 0.2% reflectance `FINISHES` gives moulded black
#: epoxy at `#050505`. Sitting it above that keeps the board readably a
#: different material from the chips standing on it, which is a thing anybody
#: can check against a real board.
#:
#: **What would retire this judgement**: Seeed stating a colour, or somebody
#: measuring a board. Recorded so it can be replaced rather than inherited.
BOARD_MASK = "#1b1b1b"

#: The colour a fired ceramic block draws in: the ESP32-C5's LTCC diplexer and
#: the nRF54L15's chip antenna, both built by `tools/model_from_datasheet.py`
#: because nobody publishes a mesh of either.
#:
#: **THE SECOND JUDGEMENT IN THIS FILE, AND THE SAME KIND AS THE FIRST.** Every
#: entry in `FINISHES` is a reading off a vendor mesh, and a part with no mesh
#: has nothing to read. Until OH-155 the two ceramic parts borrowed `#c6c4a0`,
#: the tactile switch's steel cover, and drew at metalness 1.0 -- a dielectric
#: shaded as a conductor, which under the PBR model is a different reflectance
#: law and not a nearby value on a slider. And the borrowed key could not
#: simply be re-declared for them: `FINISHES` is keyed by colour, and tallied
#: 2026-09-04 across the shipped boards `#c6c4a0` is on 13 of the 17, including
#: both ESP32-C3s at 604 triangles each, which carry neither a TS42 nor a
#: ceramic part -- so vendor models style faces with it too. One hex meaning
#: two materials is the shape of the defect OH-99 fixed on the nRF54LM20A's
#: mask film, and the cure is the same: the ceramic gets its own.
#:
#: Searched 2026-09-04 so that nobody repeats it: the three Murata LFD-series
#: diplexer datasheets fetched for OH-150 (LFD152G45MT1D824, LFD182G45MJFE023,
#: LFD182G45DCHD277) mention no colour, appearance or material anywhere in
#: their text, and Seeed's `ANT_KH5220-A36` antenna has no datasheet in the
#: tree at all. So the value is chosen: a pale warm ivory, which is what LTCC
#: and alumina fire to, set LIGHTER than the switch cover it replaces so that
#: the two are never read as one, in this table or on a board.
#:
#: **What would retire this judgement**: a vendor STEP that styles either
#: block, or a photographed board measured. Recorded so it can be replaced
#: rather than inherited, exactly as `BOARD_MASK` is.
CERAMIC = "#d9d3c0"

# --- the solder-mask film, and the one colour this file overrides (OH-99) ----
#
# **The nRF54LM20A drew green while its own board drew `BOARD_MASK`, and that
# incoherence is the defect** -- one missing fact answered two different ways
# inside one mesh. Its STEP is the only one of the six that exports the mask as
# its own body, and what it exports is not a solid but TWO LOOSE FACES:
#
#     the PCB solid   x -10.4775..10.4775  y -8.8900..8.8900  z 0.0000..1.5100
#     film, above     the same x and y to 0.0000 mm            z 1.5600
#     film, below     the same x and y to 0.0000 mm            z -0.0500
#
# So the identification is geometric and does not touch the colour, which is
# what makes overriding the colour safe: **a face with the board's own
# footprint, lying a film's thickness off one of its two outer planes, is the
# mask on that board.** Nothing else in six vendor board STEPs comes within
# 0.25 mm of the PCB's footprint -- the silkscreen, the nearest miss, is 0.505
# mm inside it and asymmetric, because lettering is not drawn to the edge.
#
# **Why this does not reverse "a face the vendor DID colour is untouched".**
# The vendor did not colour it. Their stackup states this mask's THICKNESS and
# no colour, as recorded above; `#143324` is the exporter's default, and it
# reads as one -- it is (0.08, 0.20, 0.14) in floats to two decimals, a
# constant somebody typed into a program rather than anything measured off a
# board. The rule that replaces the old one is therefore narrower, not weaker:
# *a face the vendor coloured is untouched unless it is the solder-mask film on
# the board this module has already identified by shape* -- because that face's
# colour comes from exactly where the board's does, which is nowhere, and
# `BOARD_MASK` is the answer this module already gave to that question.

#: How far a face's own edges may sit from the PCB solid's and still be the
#: same rectangle. Measured 0.0000 mm on both films; the sweep that set it ran
#: over all six vendor board STEPs and at this value returns those two faces
#: and nothing else.
MASK_FOOTPRINT_MM = 0.25

#: How far off one of the board's two outer planes a mask film may lie. The
#: exporter drew it 0.05 mm proud where the stackup states 0.01 mm thick, so
#: this admits either convention with room to spare, and it is what makes the
#: rule say "a film ON the board" rather than "anything board-shaped above it".
MASK_FILM_MM = 0.2


@dataclasses.dataclass(frozen=True)
class Finish:
    """How one colour group behaves in light, and where that came from.

    **Two numbers of very different kinds, and keeping them apart is the point.**

    `metalness` is DERIVED. Whether a material is an electrical conductor is a
    fact about what the thing is, and 0 or 1 are the only physically meaningful
    values -- a surface is a metal or it is not, and the in-between is a texture
    blend for surfaces that are partly both. Gold plating is 1. Epoxy is 0.

    `roughness` is a STATED CHOICE inside a band. Nobody publishes the RMS
    slope of an Arduino's header pins. It is the same register as the USB-B's
    `wall` in `tools/model_from_datasheet.py`, whose citation says outright
    "not a measurement -- it is a drawing thickness"; the values here are the
    conventional ones for plated metal, moulded plastic and solder mask, and
    each entry says which kind of number it is claiming to be.

    `why` carries the evidence for the ASSIGNMENT -- which thing in which model
    is this colour. That is the part that could be wrong, so it is the part
    written down.
    """

    metalness: float
    roughness: float
    why: str
    #: How much of a clear coat sits over the colour, and how smooth it is.
    #:
    #: **A third number because two could not say what a PCB is.** Solder mask
    #: is pigmented epoxy under a cured, near-transparent surface -- two layers
    #: with different behaviour, and `metalness`/`roughness` describe one. A
    #: single roughness has to be either the pigment's diffuse scatter or the
    #: coat's specular, and it was set to the first, which is why the board had
    #: no sheen and nothing to reflect however good the environment got.
    #:
    #: `KHR_materials_clearcoat` in the glTF, `MeshPhysicalMaterial` in
    #: three.js. **Zero by default, so every entry written before this keeps
    #: exactly the material it had**: a coat is a claim about a specific
    #: substance and not a way of making things shiny.
    coat: float = 0.0
    coat_roughness: float = 0.0


#: What a colour with no entry gets: exactly what every material got before
#: this table existed, so a model whose colours are not named here draws today's
#: picture rather than a worse one.
#:
#: **Not neutral by accident.** 0.1 metalness is "very slightly not a
#: dielectric", which is wrong for everything and offensive to nothing; it is
#: the value four models shipped with. Anything in this file that cannot say
#: what a surface is made of falls back here and the importer prints that it
#: did.
DEFAULT_FINISH = Finish(
    metalness=0.1, roughness=0.6,
    why="no entry in FINISHES: nothing here can say what this surface is",
)

#: Colour -> what that surface actually is, for the colours whose identity is
#: evidenced rather than guessed.
#:
#: **Keyed by colour because a colour group IS a material group here.** The
#: importer groups faces by the colour the vendor's CAD styles them with, so a
#: colour is already the finest division the file offers. The alternative --
#: keying on the component -- does not survive `tools/compose_board_3d.py`,
#: which merges fifteen components into one mesh by colour.
#:
#: ## How each assignment was arrived at, 2026-08-27
#:
#: The precedent for stating this rather than deriving it from the colour is
#: `Part.lens` a hundred lines below, whose own comment settled the same
#: argument: a rule that works on one file is a rule that will be wrong on the
#: next one somebody adds. Three kinds of evidence were available and every
#: entry says which one it rests on:
#:
#: 1. **This repository's own source names it.**
#:    `tools/blender/usb_b_receptacle.py` builds the Arduino Uno's USB socket
#:    out of materials it calls `shell`, `cavity` and `pin`.
#: 2. **Which package contributes the colour**, from loading every model in
#:    `compose_board_3d.CORRESPONDENCE` and tallying its groups. `#b58136` on
#:    the five pin-header packages and on nothing else is the strongest result
#:    of the lot: that colour is contact geometry by construction.
#: 3. **A record already in the tree.** `webui/static/board3d.js` names two of
#:    them in prose.
#:
#: A colour with none of the three is not in this table. `#6f6651` is the
#: worked example: a hundred triangles shared by a QFN-32 and a SOT-223, very
#: probably an exposed thermal pad and not evidenced enough to say so.
#:
#: **Four entries were written and then deleted**, and the thing that deleted
#: them was `test_every_finish_says_what_the_evidence_was` refusing a citation
#: too short to be a sentence. Made to write the evidence out, there was none:
#: `#10178b`, `#000ca4` and `#ebebe5` are 16, 4 and 2 triangles -- far too
#: small to be the board faces they had been called -- and `#ffffff` was 3,085
#: triangles on the SAMD21 that nothing here can identify at all. They take the
#: default now. A test that asks for the reason is how a plausible table stops
#: being a confident one.
FINISHES: dict[str, Finish] = {
    # -- metals. `metalness` 1.0 throughout, because a plated contact is a
    #    conductor and there is no honest fraction between the two.
    "#b58136": Finish(1.0, 0.30, (
        "gold-plated header contact. Tallied 2026-08-27 across every KiCad "
        "model the Uno is composed from: 1,224 triangles, all of them on "
        "1X10, 1X08, 1X06, 2X03 and 2X02, and NOT ONE anywhere else. A colour "
        "that appears only on pin-header packages is those packages' pins"
    )),
    "#b8994c": Finish(1.0, 0.30, (
        "the USB-B's contacts. Named in this repository's own source: "
        "`tools/blender/usb_b_receptacle.py` calls the material `pin`"
    )),
    "#9ea1a8": Finish(1.0, 0.25, (
        "the USB-B's shell, likewise named `shell` in "
        "`tools/blender/usb_b_receptacle.py`. A Series-B receptacle shell is "
        "folded nickel-plated steel, which is smoother than a plated contact"
    )),
    "#a5a392": Finish(1.0, 0.35, (
        "every component's LEG. 8,497 triangles across the DIP-28, the "
        "QFN-32, both electrolytics, the barrel jack, the SOT-223 and the "
        "tactile switch -- and it is also the colour `lead_tips` already "
        "treats as metal BY RULE on the LEDs and the buzzer: 'every group "
        "that is not the lens is metal'. Two independent readings agreeing"
    )),
    "#c6c4a0": Finish(1.0, 0.30, (
        "the tactile switch's metal cover. **The weakest entry here**: 440 "
        "triangles on TS42 and nothing else, and which of its two colours is "
        "the steel cover and which the moulded actuator is read off their "
        "values rather than off anything named. A B3S-1000 is a black body "
        "under a bright cover, and this is the bright one. **And it is not "
        "only on TS42**: tallied 2026-09-04, the shipped ESP32-C3 boards "
        "carry 604 triangles of it with no switch on them, so vendor models "
        "of small passives style faces with it too -- which is why the two "
        "ceramic parts that borrowed this hex until OH-155 could not have it "
        "re-declared for them, and draw in `CERAMIC` instead"
    )),
    "#ff9f37": Finish(1.0, 0.30, (
        "the XIAO's gold castellated pads. Already recorded in the tree: "
        "`webui/static/board3d.js`'s `refreshTheme` names it in prose, beside "
        "#116517 below"
    )),
    "#ff9d36": Finish(1.0, 0.30, (
        "the same gold, one value off, on the same board. Two nearly equal "
        "colours are two styles in the vendor's CAD rather than two materials"
    )),
    "#c8a253": Finish(1.0, 0.35, (
        "the composed boards' own exposed copper -- `compose_board_3d.COPPER`, "
        "this repository's one constant for every pad, castellation and via "
        "it draws (OH-110). A pad is plated metal and was shipping at "
        "DEFAULT_FINISH, metalness 0.1: 203-400 pads a board rendered matte "
        "tan while the header pins beside them shone, and `carvePins`'s "
        "metalness > 0.5 gate could not claim a castellation at all (OH-120)"
    )),
    "#e7c863": Finish(1.0, 0.30, (
        "gold plating on the ESP32-S3 and nRF52840 models. **By ANALOGY with "
        "#ff9f37 rather than from a record**: it is the same warm yellow, on "
        "the same vendor's boards, on 9,084 triangles, and Seeed plates every "
        "XIAO's pads. Analogy is weaker than the entries above and this says so"
    )),
    "#edbe51": Finish(1.0, 0.30, (
        "the same, on the RP2040 model. The same analogy and the same caveat"
    )),

    # -- dielectrics. `metalness` 0.0, and the roughness is what separates a
    #    moulded body from a solder mask from a lens.
    "#e9e9e4": Finish(0.0, 0.55, (
        "the composed boards' silkscreen -- `compose_board_3d.SILKSCREEN`. "
        "Screen-printed epoxy ink: an insulator, so metalness 0, and matte "
        "enough that lettering reads at any angle -- 0.55 sits between the "
        "solder mask's 0.35 and moulded epoxy's 0.70, which is what a cured "
        "ink over a gloss mask looks like (OH-120)"
    )),
    # **The near-blacks are one derivation, not four assertions.** A metal's
    # base colour IS its reflectance, and no metal used in electronics reflects
    # under about 50% -- gold, silver, nickel, tin and copper are all bright.
    # A surface the vendor styled at two percent grey is therefore not a metal,
    # whatever else it is, and moulded plastic and epoxy are what near-black
    # things on a board are made of. That argument covers every entry below and
    # is why they are here while other guesses were dropped.
    "#050505": Finish(0.0, 0.70, (
        "moulded black plastic and epoxy: 3,598 triangles across the bodies "
        "of the same six packages whose legs are #a5a392 above -- the QFN's "
        "encapsulant, the barrel jack's housing, the electrolytics' sleeves, "
        "the header shrouds, the DIP's body"
    )),
    "#0d0d0f": Finish(0.0, 0.70, (
        "the USB-B's insulator, named `cavity` in "
        "`tools/blender/usb_b_receptacle.py`"
    )),
    "#030303": Finish(0.0, 0.70, (
        "near-black moulding on the SAMD21 model, 13,822 triangles. Not a "
        "metal for the reflectance reason above; the specific plastic is not "
        "claimed and does not need to be"
    )),
    "#020202": Finish(0.0, 0.70, (
        "the same near-black, on the ESP32-S3, RP2040 and nRF52840 models"
    )),
    "#000000": Finish(0.0, 0.70, (
        "the same near-black, on the ESP32-S3 model. Pure zero rather than "
        "nearly zero, which is a vendor writing an ideal black rather than a "
        "different material"
    )),
    "#383838": Finish(0.0, 0.65, (
        "the tactile switch's moulded actuator, the other half of the TS42 "
        "pair. Carries the same caveat as #c6c4a0"
    )),
    CERAMIC: Finish(0.0, 0.60, (
        "the two ceramic blocks `tools/model_from_datasheet.py` builds -- the "
        "ESP32-C5's LTCC diplexer and the nRF54L15's chip antenna -- in the "
        "judged colour `CERAMIC` above, whose comment says what was searched "
        "before it was chosen. Metalness 0 is not a judgement: a fired "
        "ceramic is a dielectric and the parameter has no other honest value "
        "for one. The roughness IS a judgement, in the same register as "
        "BOARD_MASK's colour: an unglazed LTCC or alumina block is matte, so "
        "0.60 sits between the silkscreen ink's 0.55 and moulded epoxy's "
        "0.70, and a vendor mesh of either part would retire it"
    )),
    # -- the two solder masks, and the only two surfaces here with a COAT.
    # **Because a PCB is two layers and everything else here is one.** The
    # pigment scatters and the cured surface over it reflects, which is why a
    # board brightens as you tilt it and a moulded body does not. `roughness`
    # stays where it was -- it describes the pigment, and nothing about the
    # pigment changed -- and `coat` is the layer that was missing.
    #
    # `coat_roughness` 0.08 rather than 0: a cured mask is not glass, it has
    # the faint orange-peel of a screened coating, and a mirror-flat coat
    # reflects the softbox as a hard disc instead of a sheen.
    #
    # **WHERE THE COAT SHOWS IS NOT WHERE IT WAS EXPECTED TO, AND THE
    # EXPECTATION WAS WRONG RATHER THAN THE COAT.** OH-90 was filed predicting
    # that a coat brightens a board at a GRAZING angle, which is what Fresnel
    # does in the open air. Measured on the Uno's mask, switching the coat off
    # and on and changing nothing else:
    #
    #     camera      board's brightest tenth, off -> on
    #     top-down        148.0 -> 172.2     +16.3%
    #     default         132.9 -> 132.7      nothing
    #     oblique         132.3 -> 128.2      -3.1%
    #
    # A coat returns whatever lies in the MIRROR direction, and in this room
    # the bright thing is overhead. So a flat board shows its coat when the
    # camera is above it and loses a little when the camera drops, because the
    # mirror direction then points at a wall dimmer than the ceiling. That is
    # the same physics the prediction came from, applied to a room that has a
    # ceiling -- and the number that matters is the 16%, because the top-down
    # view is the one a reader lands on.
    "#313d63": Finish(0.0, 0.35, (
        "the Arduino Uno's solder mask. `tools/compose_board_3d.py` reads it "
        "out of PICSimLab's own artwork and says why in its header. Solder "
        "mask is a cured semi-gloss coating: far smoother than a moulded body "
        "and not a mirror"
    ), coat=0.85, coat_roughness=0.08),
    "#1b1b1b": Finish(0.0, 0.35, (
        "the XIAO family's solder mask, which is BOARD_MASK -- a judged "
        "colour, because no Seeed file states one (CERAMIC is the other). It "
        "gets the same finish as the two masks below it because it is the "
        "same kind of surface: a cured semi-gloss coating, smoother than a "
        "moulded body and not a mirror. The COLOUR is a judgement; that a "
        "solder mask is semi-gloss is not"
    ), coat=0.85, coat_roughness=0.08),
    "#116517": Finish(0.0, 0.35, (
        "the SAMD21 board's solder mask, named in `board3d.js`'s "
        "`refreshTheme` in the same sentence as #ff9f37"
    ), coat=0.85, coat_roughness=0.08),
    "#c07635": Finish(0.0, 0.55, (
        "the axial resistor's lacquered body. **Named by geometry, which is "
        "the strongest reading available on a two-colour part**: measured "
        "2026-08-28, `R_Axial_DIN0207_L6.3mm_D2.5mm` tessellates to exactly "
        "two colour groups, and this one spans x +-3.150 and z +-1.250 -- the "
        "6.3 by 2.5 mm body the filename itself states -- while #a5a392, "
        "already the LEG colour above, runs the full 8.2 mm out to the lead "
        "tips. A resistor's coat is a cured lacquer over a ceramic core: not a "
        "metal, and its gloss sits between a moulded body's 0.70 and a solder "
        "mask's 0.35"
    )),
    "#720301": Finish(0.0, 0.20, (
        "the LEDs' lens, which `Part.lens` already names on all three sizes. "
        "A moulded epoxy lens is the glossiest thing on this bench, which is "
        "why it is the lowest roughness in the table -- and `setPartState` "
        "replaces its colour and emissive at runtime without touching this"
    )),
}


def finish_for(colour: str) -> Finish:
    """The finish for a colour group, or the stated default."""
    return FINISHES.get(colour, DEFAULT_FINISH)


def report_finishes(mesh: Mesh) -> None:
    """Print what each colour group was taken to be made of.

    **So that the assignment can be audited against the picture**, which is the
    only way to check it. A table of thirty colours nobody ever sees applied is
    a table that rots; printing it per model, with the triangle counts, puts
    the claim in front of whoever runs the importer.
    """
    for colour, (_positions, _normals, indices) in sorted(
            mesh.groups.items(), key=lambda kv: -len(kv[1][2])):
        finish = finish_for(colour)
        named = "" if colour in FINISHES else "  DEFAULT, nothing says what this is"
        print(f"  finish {colour} {len(indices) // 3:>7,} tri  "
              f"metal {finish.metalness:.1f} rough {finish.roughness:.2f}{named}")


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


def colour_key(styled: str | None, is_board: bool, is_film: bool) -> str:
    """Which colour group a face belongs to.

    **Lifted out of `tessellate` so that it can be tested at all.** That
    function needs OpenCASCADE and a 34 MB vendor download to run, so the one
    decision inside it that has been wrong could only be checked by reading a
    `.glb` that a mutation does not regenerate -- the gap this repository has
    now been caught by twice.

    And it HAS been wrong. `colour_of` answers `""` for a face the file styles
    with nothing, as well as `None` for one it does not mention. A check for
    `None` alone let the empty string through as a colour key, which reached
    `int("", 16)` in the writer and stopped the import outright.

    **`is_film` is the one case where a stated colour loses, and the order of
    these three lines is the whole rule.** It is the solder mask lying on a
    board this module has already identified by shape, and the vendor stated
    no colour for it anywhere -- see the note beside `MASK_FOOTPRINT_MM`. It
    is deliberately not a default: every caller says which of the three cases
    a face is, because the case that was silently wrong is what OH-99 fixed.
    """
    if is_film:
        return BOARD_MASK
    if styled:
        return styled
    return BOARD_MASK if is_board else UNSTYLED


def board_faces_of(shape) -> frozenset:
    """The faces of the PCB solid, by identity, for `tessellate` to recolour.

    Identity rather than index: `TShape()` is the same object for a face
    however it is explored, and a positional index would depend on the order
    two different explorations happen to walk in.
    """
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    faces = set()
    walk = TopExp_Explorer(pcb_solid(shape, up_axis(shape)), TopAbs_FACE)
    while walk.More():
        faces.add(TopoDS.Face_s(walk.Current()).TShape())
        walk.Next()
    return frozenset(faces)


Corners = tuple[float, float, float]


def is_mask_film(low: Corners, high: Corners, board_low: Corners,
                 board_high: Corners, up: int) -> bool:
    """Whether one face's bounding box is solder-mask film lying on the PCB.

    **Lifted out of `mask_film_faces_of` for the reason `colour_key` was
    lifted out of `tessellate`**: that function needs OpenCASCADE and a 17 MB
    vendor download to reach, and this repository has twice been caught by a
    decision that could only be checked by reading a `.glb` no mutation
    regenerates. Boxes in, a verdict out, and the numbers measured off the
    nRF54LM20A go straight into a test.

    Two conditions, and each earns its place. The footprint must be the PCB
    solid's on both in-plane axes -- that is what does the identifying, and
    nothing else in six vendor board STEPs comes within `MASK_FOOTPRINT_MM` of
    it. And the whole face must lie within `MASK_FILM_MM` of ONE of the
    board's two outer planes: both ends against the same plane, so that a face
    reaching from the bottom to the top is the board's own edge and not a film
    on it.
    """
    for axis in range(3):
        if axis == up:
            continue
        if (abs(low[axis] - board_low[axis]) > MASK_FOOTPRINT_MM
                or abs(high[axis] - board_high[axis]) > MASK_FOOTPRINT_MM):
            return False
    return any(abs(low[up] - face) <= MASK_FILM_MM
               and abs(high[up] - face) <= MASK_FILM_MM
               for face in (board_low[up], board_high[up]))


def mask_film_faces_of(shape, board_faces: frozenset) -> frozenset:
    """The faces of the solder-mask film lying on the PCB, by identity.

    `is_mask_film` is the rule; this walks the shape and applies it. The
    argument for repainting what it finds, and the measurement behind both
    tolerances, is beside `MASK_FOOTPRINT_MM`.

    **`board_faces` is excluded rather than recomputed**, and it is the
    difference between the film and the board: the PCB solid's own top face
    passes every test here, being its own footprint at its own plane. Taking
    it out is what keeps this rule about a film ON the board -- and keeps a
    vendor who DID style the board's own faces safe from it.
    """
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    up = up_axis(shape)
    board = box_of(pcb_solid(shape, up))
    lows = (board.xmin, board.ymin, board.zmin)
    highs = (board.xmax, board.ymax, board.zmax)

    faces = set()
    walk = TopExp_Explorer(shape, TopAbs_FACE)
    while walk.More():
        face = TopoDS.Face_s(walk.Current())
        walk.Next()
        if face.TShape() in board_faces:
            continue
        box = box_of(face)
        if is_mask_film((box.xmin, box.ymin, box.zmin),
                        (box.xmax, box.ymax, box.zmax), lows, highs, up):
            faces.add(face.TShape())
    return frozenset(faces)


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


def tessellate(shape, styles, deflection: float, frame: Frame,
               board_faces: frozenset | None = None,
               film_faces: frozenset | None = None) -> Mesh:
    """Mesh every face, grouped by colour, in glTF axes and millimetres.

    `board_faces` names the faces of the PCB solid, and they take `BOARD_MASK`
    where the vendor styled them nothing. **Only those faces, and only when
    unstyled** -- `UNSTYLED` still means "nobody here knows what this is" for
    every other face, which is the position that constant exists to hold and
    `test_the_unstyled_colour_is_given_no_material` still enforces.

    A PCB is the one unstyled solid whose material is not a mystery: this
    module already had to IDENTIFY it, by shape, because the model's origin is
    the board's centre rather than the assembly's. See `BOARD_MASK`.

    `film_faces` names the solder mask lying ON that board, which one of the
    six vendor STEPs exports as its own pair of faces, and those take
    `BOARD_MASK` whatever the file styles them -- the single place this module
    overrides a stated colour, argued beside `MASK_FOOTPRINT_MM`.
    """
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

        key = colour_key(
            colour_of(styles, face),
            board_faces is not None and face.TShape() in board_faces,
            film_faces is not None and face.TShape() in film_faces,
        )
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

    welded = 0
    for positions, normals, _ in groups.values():
        welded += weld_seams(positions, normals)
        normalise(normals)
    if welded:
        print(f"  weld   {welded:,} vertices on a seam given one normal")
    return Mesh(groups=groups)


def linear(channel: int) -> float:
    """One sRGB byte as the linear value glTF's `baseColorFactor` is defined in.

    **This was `channel / 255` and that is a different colour.** The glTF
    specification says `baseColorFactor` is linear, three.js reads it as
    linear, and a CAD file's colours are sRGB -- so every albedo in every model
    this repository has ever written was too bright, and DIFFERENTLY too bright
    per channel because the transfer function is a curve. That flattens a
    colour toward grey, which is what was reported: "the board is still matte
    and greyish".

    Measured on the corpus, written against what it should have been:

        Uno solder mask #313d63   6.3x 5.1x 3.1x too bright, saturation .51 -> .75
        SAMD21 mask     #116517  11.9x 3.0x 10.5x           saturation .83 -> .96
        gold contact    #b58136   1.5x 2.3x  5.7x           saturation .70 -> .92
        black epoxy     #050505  12.9x each                 (grey, not black)

    **And the repository already had the right answer twenty lines away.**
    `readPalette` in `webui/static/board3d.js` builds its colours from strings
    with `new THREE.Color("#313d63")`, and `setStyle` applies this same
    function -- so the extruded slab has been correct since it was written
    while the composed board beside it was six times too bright. Two answers to
    one question, disagreeing quietly.

    The constants are the sRGB standard's own: the 0.0031308 knee lives in the
    other direction, so the threshold here is 0.04045.
    """
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def weld_seams(positions: list[float], normals: list[float]) -> int:
    """Give coincident vertices facing the same way one shared normal.

    Returns how many vertices were changed, so the caller can print it and a
    reader can see the seams being closed rather than take it on trust.

    **Clustered rather than simply averaged**, because a point where three
    faces meet at right angles is also a point with coincident vertices, and
    averaging there would round off a corner that is genuinely sharp. Each
    group is split into runs whose directions agree to within
    `SMOOTH_DEGREES`, and only a run with more than one member is merged -- so
    a cube corner produces three clusters of one and is left exactly as it was.

    The accumulated normals are summed rather than averaged, which keeps the
    area weighting `accumulate_normals` established: a seam vertex carrying
    half a cylinder's triangles on each side ends up with the sum of both,
    which is what it would have had if the face had never been cut.
    """
    at_point: dict[tuple[float, float, float], list[int]] = {}
    for vertex in range(0, len(positions), 3):
        # 0.1 um, which is three orders below `DEFLECTION` -- fine enough that
        # two vertices in one bucket are the same point, coarse enough that a
        # seam's two copies land together.
        at_point.setdefault((round(positions[vertex], 4),
                             round(positions[vertex + 1], 4),
                             round(positions[vertex + 2], 4)), []).append(vertex)

    limit = math.cos(math.radians(SMOOTH_DEGREES))
    changed = 0
    for group in at_point.values():
        if len(group) < 2:
            continue
        clusters: list[tuple[list[float], list[int]]] = []
        for vertex in group:
            here = normals[vertex:vertex + 3]
            length = math.sqrt(sum(v * v for v in here))
            if length == 0.0:
                continue                       # a degenerate triangle's vertex
            for total, members in clusters:
                scale = math.sqrt(sum(v * v for v in total))
                if scale == 0.0:
                    continue
                agreement = sum(a * b for a, b in zip(total, here)) / (scale * length)
                if agreement >= limit:
                    for axis in range(3):
                        total[axis] += here[axis]
                    members.append(vertex)
                    break
            else:
                clusters.append(([*here], [vertex]))
        for total, members in clusters:
            if len(members) < 2:
                continue
            changed += len(members)
            for vertex in members:
                normals[vertex:vertex + 3] = total
    return changed


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
    # **Here rather than in each caller**, so that the composed Arduino Uno
    # reports its assignment too without `tools/compose_board_3d.py` having to
    # know this table exists -- it already shares this writer.
    report_finishes(mesh)
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

        red = linear(int(colour[1:3], 16))
        green = linear(int(colour[3:5], 16))
        blue = linear(int(colour[5:7], 16))
        # **Per colour, not one constant for everything.** Until OH-82 these
        # two were literals here, so the gold header contacts, the nickel USB
        # shell, the tin legs, the black epoxy and the solder mask were all the
        # same substance and nothing in the scene had a material identity.
        # `FINISHES` says which is which, and says what the evidence was.
        finish = finish_for(colour)
        material: dict[str, object] = {
            "name": colour,
            "pbrMetallicRoughness": {
                "baseColorFactor": [red, green, blue, 1.0],
                "metallicFactor": finish.metalness,
                "roughnessFactor": finish.roughness,
            },
            "doubleSided": True,
        }
        # The coat, and only for a surface that has one. Written as the
        # registered `KHR_materials_clearcoat` rather than as a private key,
        # so this file stays a glTF anything can read -- and absent entirely
        # from a material with no coat, which is what "every other surface is
        # byte-for-byte what it was" means mechanically.
        if finish.coat:
            material["extensions"] = {
                "KHR_materials_clearcoat": {
                    "clearcoatFactor": finish.coat,
                    "clearcoatRoughnessFactor": finish.coat_roughness,
                }
            }
        materials.append(material)
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
        # Declared only when something in this file uses it. `extensionsUsed`
        # is a promise about the document, and a file listing an extension no
        # material carries is a file that lies about itself in a way every
        # validator will believe.
        **({"extensionsUsed": ["KHR_materials_clearcoat"]}
           if any("extensions" in material for material in materials) else {}),
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

    # **The PCB's own faces, so an unstyled BOARD is a board rather than a
    # mystery.** Every other unstyled face stays grey; see `BOARD_MASK`.
    # **And the mask film lying on it**, where the vendor exported one as its
    # own body -- one of the six does, and it drew green over its own dark
    # board until OH-99. Printed, because a rule that repaints a vendor's
    # stated colour should say out loud when it fired.
    board_faces = board_faces_of(shape)
    film_faces = mask_film_faces_of(shape, board_faces)
    if film_faces:
        print(f"  mask   {len(film_faces)} face(s) of solder-mask film on the"
              " PCB take BOARD_MASK; see MASK_FOOTPRINT_MM")
    mesh = tessellate(shape, styles, deflection, frame, board_faces, film_faces)
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
class Electrical:
    """How a part behaves in a circuit, and where each of its numbers came from.

    **The pattern is `tools/model_from_datasheet.py`'s `SPECS` and it is copied
    here deliberately**: a value and its provenance live in one mapping, so
    neither can be edited without the other showing up in the diff. That file's
    docstring gives the reason at length -- a plausible invented number that
    renders nicely is the defect this area of the project keeps re-learning.

    `webui/static/circuit.js` is the consumer. Everything here reaches it
    through the glTF's `asset.extras`, so a part carries its own physics the
    same way it already carries its own lead positions.
    """

    #: What kind of element this is in the netlist. `diode` is the only one so
    #: far, and a part with no `Electrical` at all is honestly modelled as a
    #: conductor of unknown value -- see `analyse`, which then refuses to report
    #: a current for anything on that bench.
    kind: str
    #: name -> (value in SI units, where the value came from).
    cited: dict[str, tuple[float, str]]
    note: str
    #: Which terminal current enters by and which it leaves by, in the names
    #: `lead_tips` gives them -- or `None` for a part that has no such
    #: direction.
    #:
    #: **A resistor is that case and it is an absence rather than a gap.** It
    #: conducts equally either way, so naming one lead as the one current
    #: enters by would state a polarity the part does not have -- and a reader
    #: who believed it would wire an LED round the right way and a resistor
    #: round the "wrong" one. `analyse` takes the magnitude of a non-diode's
    #: current for the same reason, so nothing downstream needs the direction.
    forward: tuple[str, str] | None = None

    def extras(self) -> dict[str, object]:
        """The shape `circuit.js` reads, values and citations side by side."""
        out: dict[str, object] = {
            "kind": self.kind,
            "note": self.note,
            "cited": {name: why for name, (_value, why) in self.cited.items()},
        }
        # Absent rather than null, for the reason `convert_part` gives about
        # `electrical` itself: a missing key is what a part with no forward
        # direction has, and `from: null` invites a reader to look for one.
        if self.forward is not None:
            out["from"], out["to"] = self.forward
        for name, (value, _why) in self.cited.items():
            out[name] = value
        return out


#: A 5 mm through-hole red indicator LED, electrically.
#:
#: **AND HERE IS THE HONEST PROBLEM, STATED RATHER THAN PAPERED OVER.** The two
#: chips this bench can drive publish datasheets that were read to the page --
#: see `SUPPLY` in `webui/boards/atmega328p.py` and `webui/boards/samd21.py`.
#: KiCad's mesh is a **generic** part. `LED_D5.0mm.step` carries no
#: manufacturer and no order code, so there is no datasheet to read and no
#: honest way to pretend otherwise.
#:
#: So these are **class values for a red indicator LED**, and each is taken at
#: the end of its range that makes the computed current a LOWER bound rather
#: than an upper one. That choice is what lets `circuit.js` say "at least
#: 40 mA, past the 20 mA this board rates a pin for" and be right about it: the
#: real current is larger still. It is also why nothing may ever say a circuit
#: is safe -- a lower bound under a rating establishes nothing.
#:
#: A specific part number would be strictly better than every line of this and
#: should replace it. The obvious candidates -- Kingbright's WP7113 series,
#: Vishay's TLHR5400 -- publish PDFs behind site searches that
#: `tools/get_board_sources.py`'s `https-archive` note already describes, and
#: none of them is the part KiCad drew.
LED_ELECTRICAL = Electrical(
    kind="diode",
    forward=("anode", "cathode"),
    cited={
        "forward_volts": (2.2, (
            "the top of the 1.8-2.2 V a red indicator LED drops at its rated "
            "current. A class value and not a measurement: an LED's forward "
            "voltage is set by the band gap of the semiconductor, which is why "
            "every red one in the world sits in that band and why a generic "
            "part can be given one at all. Taken at the TOP of the band "
            "deliberately, because a larger drop leaves less across the "
            "resistance and so computes less current"
        )),
        "series_ohms": (30.0, (
            "the top of the 10-30 ohm a 5 mm LED's bulk and lead resistance "
            "adds above its knee. Also a class value, also taken at the end "
            "that reduces the computed current. Between them these two make "
            "every number this part contributes a lower bound"
        )),
        "rated_amps": (0.020, (
            "the continuous forward current a 5 mm indicator LED is sold "
            "against. A WARNING and not a death sentence -- see "
            "`absolute_amps`, which is the one that licenses the page to say a "
            "part is destroyed"
        )),
        #: **This one is taken at the GENEROUS end of its band, and the
        #: inversion is the point.** The two numbers above are each chosen to
        #: make the computed CURRENT a lower bound; this is chosen to make the
        #: LIMIT an upper bound. So "a lower-bound current exceeds an
        #: upper-bound limit" holds under every reading of both, which is what
        #: makes a destruction claim safe to print. Choosing 20 mA here instead
        #: would condemn parts that a more generous datasheet allows.
        "absolute_amps": (0.030, (
            "the top of the 20-30 mA DC absolute maximum a 5 mm through-hole "
            "indicator LED is built to. A class value like the two above, and "
            "the ONLY one taken at the generous end of its range -- because it "
            "is a limit rather than a term in the current, so an upper bound "
            "here is what makes 'past this' true under any reading. An "
            "absolute maximum is a stress rating: DS40002061B's own wording "
            "over the equivalent table is that stresses beyond it 'may cause "
            "permanent damage to the device'"
        )),
    },
    note=(
        "Class values for a red indicator LED, not one part's datasheet: "
        "KiCad's mesh is generic and names no manufacturer. Each is chosen at "
        "the end of its range that makes the current a lower bound."
    ),
)


#: A 220 ohm axial resistor, and it is the part that makes the warning above
#: mean something.
#:
#: **WHY IT IS LOAD-BEARING RATHER THAN A NICETY.** With only LEDs on the
#: bench there was no way to light one on an Arduino Uno without destroying it:
#: an LED straight across a pin draws at least 40 mA against the 20 mA the
#: board rates a pin for, which `circuit.js` reported correctly and
#: unhelpfully. Every circuit a reader could build was one the page warned
#: about, and a warning that fires on everything is noise. Two LEDs in series
#: at 6 mA was the only intact circuit available.
#:
#: **THE MODELLED VALUE IS 231 AND NOT 220, AND THAT IS THE ONE INVARIANT THIS
#: AREA HAS.** Every resistance the solver is handed is a worst corner, so
#: every current it computes is a LOWER bound -- which is exactly what lets the
#: page say "at least 40 mA, past the 20 mA this board rates a pin for" and be
#: right about it under any reading. A resistor entered at its nominal value
#: would break that with the very part added to make the page usable: a real
#: 220 ohm +-5% part may be 209 ohm, 209 passes MORE current than 220, and
#: "at least 9.7 mA" would then have been false. 231 is the top of the band, so
#: the current through it is the least this part can pass.
#:
#: **The label says 220 ohm and the mesh says nothing at all**, which is the
#: question OH-80 was filed with open and it is settled by measurement rather
#: than by argument. The fear was that a part called 220 ohm would carry
#: painted colour bands reading something else -- a picture contradicting a
#: label, which is the defect this area keeps re-learning. Measured 2026-08-28
#: by tessellating it: `R_Axial_DIN0207` has exactly TWO styled colours,
#: `#a5a392` on the leads and `#c07635` on the body, and NO BANDS. There is no
#: claim in the picture for the label to contradict.
#:
#: **No current rating, and that is a measured absence rather than an
#: oversight.** A resistor's limit is power, not current, and on this bench it
#: cannot be reached: 5 V is the largest any rail offers, so the most this part
#: can dissipate is 5^2 / 231 = 108 mW, and the smallest axial part sold in a
#: 6.3 x 2.5 mm body is a quarter watt. `circuit.js` models no power at all,
#: and adding a limit no circuit here can approach would be the config option
#: with one call site that `.claude/CLAUDE.md` rule 6 refuses.
RESISTOR_ELECTRICAL = Electrical(
    kind="resistor",
    cited={
        "ohms": (231.0, (
            "220 ohm +-5%, taken at the TOP of its tolerance band. 220 is the "
            "classic Arduino series resistor for an indicator LED and +-5% is "
            "what a carbon-film part in a hobby kit is sold to. Taken at the "
            "top for the same reason every other resistance reaching this "
            "solver is taken at its worst corner: a larger resistance computes "
            "a smaller current, so the number the page prints stays a lower "
            "bound on the real one. 220 nominal would not -- a part at the "
            "bottom of the same band passes more than the page would claim"
        )),
    },
    note=(
        "220 ohm +-5%, modelled at 231 ohm -- the top of the band, so the "
        "computed current stays a lower bound. No power rating: on a 5 V "
        "bench this part cannot dissipate more than 108 mW, and the smallest "
        "one sold in this body is 250 mW."
    ),
)


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
    #:
    #: **`None` for a part that shows nothing**, which is the resistor. A
    #: resistor has no surface whose appearance says what is going through it,
    #: and nominating one would invent a display the part does not have --
    #: which is the same failure as lighting an ungrounded LED, one step
    #: earlier. `lead_tips` needs no lens to find the leads (measured: the same
    #: two tips with and without) and `dressPart` already copes with a part
    #: that has none.
    lens: str | None
    #: What the leads are called, in the order this file's own geometry puts
    #: them -- see `lead_tips`, which sorts tips by x. **A tuple of N, not a
    #: pair** (OH-126): the hard 2-tuple was the single line that made a
    #: potentiometer inexpressible, and every reader downstream -- the
    #: extras, `dressPart`'s terminal loop, `circuit.terminalsOf` -- was
    #: already generic.
    terminals: tuple[str, ...]
    #: What it does in a circuit, or `None` for a part nobody has published one
    #: for. **`None` is a real answer and not a gap**: `circuit.js` treats such
    #: a part as a conductor of unknown value, which still needs a complete
    #: circuit to do anything and produces no current claim for the bench it is
    #: on. Inventing a resistance to fill this in would decide every other
    #: part's current by it.
    electrical: Electrical | None = None

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
#: **The first three-terminal part, and why its one number is 5,500 and not
#: 5,000.** Bourns' 3266 series sells the '502' code at 5 kOhm with a +/-10%
#: element tolerance, and the TOP of that band computes the LEAST current --
#: the 220 Ohm resistor's own 231 argument, kept so that every number this
#: part contributes stays a lower bound. No rated or absolute current is
#: cited, because the 3266's limit is a wattage (0.25 W at 70 C) and no 5 V
#: bench can push a quarter watt through 5.5 kOhm; `destroys` therefore can
#: never claim this part, which is the same honesty as the resistor's.
#:
#: **The wiper has no knob yet.** `circuit.js` stands the wiper at the middle
#: of its travel and says so in its own constant -- turning it is page UI for
#: a ticket of its own, and a stated constant beats an invented interaction.
POT_ELECTRICAL = Electrical(
    kind="potentiometer",
    note=(
        "class values for a 3266-series 5 kOhm trimmer; the wiper stands at "
        "half its travel by circuit.js's POT_TRAVEL, a stated constant, "
        "because this bench has no knob to turn yet"
    ),
    cited={
        "ohms": (5500.0, (
            "the top of a 5 kOhm +/-10% element -- the 3266 series' '502' "
            "code -- because a smaller real resistance passes more current, "
            "so the top of the band keeps every computed current a lower "
            "bound, the 220 Ohm resistor's own argument"
        )),
    },
)

PARTS: tuple[Part, ...] = (
    #: All three carry the same electrical model, because all three are the
    #: same die behind a different lens: a 10 mm LED is a 5 mm LED you can see
    #: from further away, and neither KiCad's mesh nor the class values in
    #: `LED_ELECTRICAL` distinguish them. Saying so once beats three copies
    #: that could drift apart while all three parts stayed identical.
    Part(library="LED_THT", name="LED_D3.0mm", label="3 mm LED",
         lens="#720301", terminals=("cathode", "anode"),
         electrical=LED_ELECTRICAL),
    Part(library="LED_THT", name="LED_D5.0mm", label="5 mm LED",
         lens="#720301", terminals=("cathode", "anode"),
         electrical=LED_ELECTRICAL),
    Part(library="LED_THT", name="LED_D10.0mm", label="10 mm LED",
         lens="#720301", terminals=("cathode", "anode"),
         electrical=LED_ELECTRICAL),
    #: **The red mark on its case, and it means driven rather than sounding.**
    #: A buzzer makes a noise and this page has no audio, so nothing here can
    #: show what it is actually doing. Lighting its polarity mark says the one
    #: thing that is true -- the pin wired to it is high -- and the panel says
    #: the same in words. Inventing a sound would be the failure this
    #: repository ranks worst; leaving a part on the bench that shows nothing
    #: at all would be the one it ranks second.
    #:
    #: **And it gets no electrical model, which is the honest answer rather
    #: than a missing one.** A 12 mm buzzer is either a magnetic coil of a few
    #: tens of ohms or a piezo element that is very nearly an open circuit at
    #: DC, and those two draw currents three orders of magnitude apart. KiCad's
    #: mesh does not say which it drew, and the two are not distinguishable
    #: from the outside of a plastic can. So it is a conductor of unknown
    #: value: it still needs a complete circuit before it shows anything, and
    #: `circuit.js` reports no current for any bench it stands on rather than
    #: letting a number invented here decide an LED's.
    Part(library="Buzzer_Beeper", name="Buzzer_12x9.5RM7.6", label="12 mm buzzer",
         lens="#9e2705", terminals=("negative", "positive")),
    #: **The part that makes every other one usable**, and `RESISTOR_ELECTRICAL`
    #: above carries the argument. A 5 mm LED from D13 through this to GND
    #: carries at least 9.3 mA on an Uno -- inside the 20 mA a pin is rated for
    #: and inside the LED's own -- so the page reports a current and says
    #: nothing else. It is the first circuit this bench can build that raises
    #: no warning at all.
    #:
    #: **DIN0207 at 7.62 mm pitch, which is the one in a person's drawer.** Its
    #: body is 6.3 x 2.5 mm, the standard quarter-watt axial, and 7.62 mm is
    #: the breadboard-friendly footprint among the five pitches KiCad publishes
    #: for that body. Measured 2026-08-28 by tessellating it: 8.418 mm overall
    #: on lead tips 7.608 mm apart, against the 7.62 the name claims -- 0.012 mm
    #: out, which is the tessellation's own chord tolerance and not a
    #: disagreement.
    #:
    #: **Terminals `lead A` and `lead B` rather than a polarity.** `lead_tips`
    #: orders them by the sign of x and nothing else distinguishes them,
    #: because nothing about the part does: naming one of them positive would
    #: be a claim, and this part has none to make.
    Part(library="Resistor_THT",
         name="R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
         label="220 Ω resistor", lens=None, terminals=("lead A", "lead B"),
         electrical=RESISTOR_ELECTRICAL),
    #: The 3266W measures 6.7 x 4.5 x 13.1 mm with its three pins in the
    #: vendor's zig-zag -- x at -2.54, 0, +2.54, z alternating, measured off
    #: the mesh -- and the wiper is the MIDDLE pin, which is Bourns' own
    #: pinout for the W style. The first part on this bench with three
    #: terminals, which is the whole reason it is here (OH-126).
    Part("Potentiometer_THT", "Potentiometer_Bourns_3266W_Vertical",
         label="5 kΩ trimmer", lens=None,
         terminals=("lead A", "wiper", "lead B"),
         electrical=POT_ELECTRICAL),
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

#: How far above the lowest lead tip another lead's tip may sit and still be
#: a lead. The five two-lead parts' legs are equal to the micron; 2 mm is
#: slack for a moulding that is not.
LEAD_SLACK_MM = 2.0

#: One 0.1-inch pitch. Half of it separates lead clusters, because no two
#: through-hole leads sit closer than a pitch.
LEAD_APART_MM = 2.54


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
    # **Clustered on (x, z), not split on the sign of x** (OH-126). Two-lead
    # parts straddle the origin, but the 3266W trimmer's three pins zig-zag
    # -- x at -2.54, 0, +2.54 with z alternating -1.27, +1.27, -1.27,
    # measured off the vendor's own mesh -- and its middle pin has no side.
    # Metal points within LEAD_SLACK_MM of the lowest vertex are grouped by
    # xz proximity at half a 0.1-inch pitch; each cluster keeps its own
    # floor ring, which is the same ring the per-side version took, so the
    # five two-lead parts' tips do not move (verified by regenerating them).
    metal = [(positions[at], positions[at + 1], positions[at + 2])
             for colour, (positions, _normals, _indices) in mesh.groups.items()
             if colour != lens
             for at in range(0, len(positions), 3)]
    if not metal:
        return []
    floor = min(point[1] for point in metal)
    low = [point for point in metal if point[1] <= floor + LEAD_SLACK_MM]
    clusters: list[list[tuple[float, float, float]]] = []
    for point in low:
        for cluster in clusters:
            middle_x = sum(q[0] for q in cluster) / len(cluster)
            middle_z = sum(q[2] for q in cluster) / len(cluster)
            if math.hypot(point[0] - middle_x,
                          point[2] - middle_z) < LEAD_APART_MM / 2:
                cluster.append(point)
                break
        else:
            clusters.append([point])
    tips: list[list[float]] = []
    for cluster in clusters:
        # **The whole ring at the tip, averaged, and not the single lowest
        # vertex.** A lead is a cylinder, so its lowest vertices are a circle
        # of them and which one comes first is an artefact of the
        # tessellation: the first version of this took one each side and got
        # -1.270 and +0.870 for a part whose leads are 2.54 mm apart -- one
        # answer on the lead's axis and one on its rim, and no way to tell
        # which from the number alone.
        here = min(point[1] for point in cluster)
        ring = [point for point in cluster if point[1] <= here + LEAD_RING]
        tips.append([sum(point[axis] for point in ring) / len(ring)
                     for axis in range(3)])
    tips.sort(key=lambda tip: tip[0])
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
    # A part that names no lens is not checked for one -- but a part that names
    # one and has lost it still fails loudly, which is the case this guard was
    # written for.
    if part.lens is not None and part.lens not in mesh.groups:
        raise SystemExit(
            f"{part.name} names {part.lens} as its lens and the model has "
            f"{sorted(mesh.groups)}. The file changed; re-read it before "
            f"trusting a part that cannot light up."
        )
    tips = lead_tips(mesh, part.lens)
    if len(tips) != len(part.terminals):
        raise SystemExit(
            f"{part.name} has {len(tips)} lead tips and its terminals name "
            f"{len(part.terminals)}. Either the model is a different part or "
            f"the lead clustering mis-grouped; re-measure before trusting a "
            f"wire to land."
        )
    print("  leads  " + ", ".join(
        f"{part.terminals[i]} at "
        f"({tips[i][0]:.3f}, {tips[i][1]:.3f}, {tips[i][2]:.3f})"
        for i in range(len(part.terminals))))
    if part.electrical is None:
        print("  circuit  none published -- a conductor of unknown value")
    else:
        values = ", ".join(f"{name} {value:g}"
                           for name, (value, _why) in part.electrical.cited.items())
        forward = "" if part.electrical.forward is None else (
            f", {part.electrical.forward[0]} to {part.electrical.forward[1]}")
        print(f"  circuit  {part.electrical.kind}{forward}: {values}")

    if check:
        print("  write  skipped (--check)")
        return 0
    out = OUT / "parts" / f"{part.slug}.glb"
    extras: dict[str, object] = {
        "label": part.label, "lens": part.lens, "library": part.library,
        "terminals": [{"name": part.terminals[i],
                       "at": [round(v, 4) for v in tips[i]]}
                      for i in range(len(part.terminals))],
        "licence": "CC-BY-SA-4.0 with the KiCad library exception; fetched, "
                   "not vendored",
    }
    # Absent rather than null for a part with no published behaviour, so that
    # `dressPart` reads the same "nobody has said" from a missing key as from
    # an older file written before this existed.
    if part.electrical is not None:
        extras["electrical"] = part.electrical.extras()
    size = write_glb(mesh, out, part.slug, part.url, (whole.width, whole.height,
                                                     whole.thickness),
                     extras=extras)
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
#: **The FALLBACK list, and `tools/compose_board_3d.py` owns the real one.**
#: That module holds a `Composition` per composed board -- its layout file, its
#: headers, its colour and the boards it serves -- and passing that list in is
#: what keeps one answer to "which boards are composed". This copy exists only
#: for `import_3d_model.py --all`, which writes the index without the composer
#: having run, and `test_the_two_lists_of_composed_boards_agree` is what stops
#: the two drifting apart.
#: **An -SMD board gets its own file now** (OH-118): a DIP variant hangs two
#: header rows below the board and an SMD one does not, so the one file that
#: served both was right for neither. `-DIP-SMD` is the exception that proves
#: the rule -- its pad map is identical to the DIP's, measured pad for pad, so
#: it is a header variant under a different name and keeps the DIP file.
COMPOSED: tuple[tuple[str, str, str], ...] = (
    ("Arduino Uno", "ATmega328P", "Arduino-Uno"),
    ("XIAO-ESP32-C3-DIP", "ESP32-C3", "XIAO-ESP32-C3-DIP"),
    ("XIAO-ESP32-C3-DIP-SMD", "ESP32-C3", "XIAO-ESP32-C3-DIP"),
    ("XIAO-ESP32-C3-SMD", "ESP32-C3", "XIAO-ESP32-C3-SMD"),
    ("XIAO-ESP32-C6-DIP", "ESP32-C6", "XIAO-ESP32-C6-DIP"),
    ("XIAO-ESP32-C6-SMD", "ESP32-C6", "XIAO-ESP32-C6-SMD"),
    ("XIAO-RP2350-DIP", "RP2350", "XIAO-RP2350-DIP"),
    ("XIAO-RP2350-SMD", "RP2350", "XIAO-RP2350-SMD"),
    ("XIAO-nRF54l15-DIP", "nRF54l15", "XIAO-nRF54l15-DIP"),
    ("XIAO-nRF54l15-SMD", "nRF54l15", "XIAO-nRF54l15-SMD"),
    ("XIAO-ESP32-C5-DIP", "ESP32-C5", "XIAO-ESP32-C5-DIP"),
    ("XIAO-ESP32-C5-SMD", "ESP32-C5", "XIAO-ESP32-C5-SMD"),
)


def write_index(composed: tuple[tuple[str, str, str], ...] | None = None
                ) -> pathlib.Path:
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
    for board, chip, slug in (composed if composed is not None else COMPOSED):
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
