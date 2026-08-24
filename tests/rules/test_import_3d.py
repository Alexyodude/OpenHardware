# OpenHardware — a board outline from a layout, and the mesh it extrudes to.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Exercises `tools/import_3d.py`.

Two kinds of test here, deliberately separated.

The **synthetic** ones build a small `.kicad_pcb` in `tmp_path` and always run.
They are where a refusal can be provoked on purpose: an open outline, two
loops, a layout with no Edge.Cuts at all.

The **real-board** ones read OLIMEX ESP32-PoE, fetched into `third_party/` and
git-ignored, so they **skip when it is absent** -- never pass. Same contract the
rule checkers keep without a PICSimLab checkout: a check that quietly became a
no-op is worse than one that says it did not run. They are what makes this more
than a test of its own fixtures, because the vendor's file is the thing this
has to survive.

No `@pytest.mark.parametrize`: `tools/inventory.py` counts `def test_*` with
`ast` and `test_ast_count_matches_pytest_collection` fails on the divergence.
"""

from __future__ import annotations

import base64
import json
import pathlib
import struct
import subprocess
import sys

import pytest

from tools import board_sources, import_3d

REPO = pathlib.Path(__file__).resolve().parents[2]
OLIMEX = REPO / "third_party" / "olimex-esp32-poe" / "HARDWARE"

#: The revision every dimension in this file is quoted from.
REV_C = OLIMEX / "ESP32-PoE-hardware-revision-C1" / "ESP32-PoE_Rev_C.kicad_pcb"
#: The newest generation of the file format, in the same repository.
REV_M2 = OLIMEX / "ESP32-PoE-hardware-revision-M2" / "ESP32-PoE_Rev_M2.kicad_pcb"
#: The revision with an unplaced part, which is why the pad check earns its keep.
REV_B2 = OLIMEX / "ESP32-PoE-hardware-revision-B2" / "ESP32-PoE_Rev_B2.kicad_pcb"


def layout(tmp_path: pathlib.Path, body: str, *, quoted: bool = False,
           thickness: str = "(thickness 1.6)", name: str = "board.kicad_pcb") -> pathlib.Path:
    """A minimal `.kicad_pcb` carrying `body`.

    `quoted` writes layer names the way KiCad 7 does. Both generations sit in
    the OLIMEX repository, and `kicad.parse_sexp` strips the quotes, so the two
    must arrive identical -- which is the point of being able to write either.
    """
    layer = '"Edge.Cuts"' if quoted else "Edge.Cuts"
    path = tmp_path / name
    path.write_text(
        f"(kicad_pcb (version 20171130) (host pcbnew test)\n"
        f"  (general {thickness})\n"
        f"{body.replace('EDGE', layer)}\n"
        f")\n",
        encoding="utf-8",
    )
    return path


def square(side: float = 10.0, x0: float = 0.0, y0: float = 0.0,
           reverse: bool = False) -> str:
    """Four Edge.Cuts segments forming a closed square."""
    corners = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    if reverse:
        corners.reverse()
    out = []
    for index, start in enumerate(corners):
        end = corners[(index + 1) % len(corners)]
        out.append(f"  (gr_line (start {start[0]} {start[1]}) "
                   f"(end {end[0]} {end[1]}) (layer EDGE) (width 0.1))")
    return "\n".join(out)


def mesh_of(document: dict):
    """Vertices and triangles decoded back out of the glTF buffer."""
    blob = base64.b64decode(document["buffers"][0]["uri"].split(",", 1)[1])
    vertices_view, indices_view = document["bufferViews"]
    vertices = [
        struct.unpack_from("<3f", blob, vertices_view["byteOffset"] + 12 * i)
        for i in range(document["accessors"][0]["count"])
    ]
    flat = struct.unpack_from(
        f"<{document['accessors'][1]['count']}I", blob, indices_view["byteOffset"]
    )
    return vertices, [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]


def volume_mm3(vertices, triangles) -> float:
    """Signed volume by the divergence theorem. Positive means outward faces."""
    total = 0.0
    for a, b, c in triangles:
        ax, ay, az = vertices[a]
        bx, by, bz = vertices[b]
        cx, cy, cz = vertices[c]
        total += (ax * (by * cz - bz * cy)
                  - ay * (bx * cz - bz * cx)
                  + az * (bx * cy - by * cx))
    return total / 6.0


@pytest.fixture(scope="session")
def olimex() -> pathlib.Path:
    """The fetched OLIMEX tree, or skip.

    Absence is a skip and never a pass. `third_party/` is git-ignored, so a
    fresh clone has no vendor tree at all.
    """
    if not REV_C.is_file():
        pytest.skip(
            f"no OLIMEX checkout at {OLIMEX}. Fetch it:\n"
            f"  python tools/get_board_sources.py olimex-esp32-poe"
        )
    return OLIMEX


# --- the mesh, on outlines this file writes ---------------------------------


def test_a_square_outline_extrudes_to_a_watertight_mesh(tmp_path):
    """Every directed edge must have its opposite. A mesh with a hole in it
    renders as a board right up until something tries to compute a volume or
    cast a shadow through it."""
    path = layout(tmp_path, square())
    document = import_3d.to_gltf(
        import_3d.read_outline(path), import_3d.read_thickness_mm(path), "square"
    )
    _, triangles = mesh_of(document)

    directed = set()
    for a, b, c in triangles:
        directed |= {(a, b), (b, c), (c, a)}
    unmatched = [(a, b) for a, b in directed if (b, a) not in directed]
    assert not unmatched, f"{len(unmatched)} edge(s) with no opposite: {unmatched[:4]}"


def test_the_mesh_volume_is_the_polygon_area_times_the_thickness(tmp_path):
    """**The invariant that checks three things at once.** A volume this exact
    can only come from a mesh that is closed, wound outward, and extruded by
    the right amount -- and any of the three being wrong changes it."""
    path = layout(tmp_path, square(side=10.0))
    outline = import_3d.read_outline(path)
    thickness = import_3d.read_thickness_mm(path)
    vertices, triangles = mesh_of(import_3d.to_gltf(outline, thickness, "square"))

    expected = abs(outline.signed_area_mm2()) * thickness
    assert expected == pytest.approx(100.0 * 1.6)
    assert volume_mm3(vertices, triangles) == pytest.approx(expected, abs=1e-4)


def test_a_mesh_wound_inside_out_would_have_been_caught(tmp_path):
    """The check above is only worth having if the wrong winding fails it.
    Reversing every triangle is exactly the mistake it is watching for, and it
    flips the sign of the volume rather than changing its size."""
    path = layout(tmp_path, square())
    vertices, triangles = mesh_of(import_3d.to_gltf(
        import_3d.read_outline(path), 1.6, "square"))
    flipped = [(c, b, a) for a, b, c in triangles]
    assert volume_mm3(vertices, flipped) == pytest.approx(
        -volume_mm3(vertices, triangles), abs=1e-4)


def test_the_source_outline_winding_does_not_change_the_mesh(tmp_path):
    """A layout stores outline segments in whichever order they were drawn.
    Two boards identical but for drawing order must produce the same solid."""
    forward = layout(tmp_path, square(), name="a.kicad_pcb")
    backward = layout(tmp_path, square(reverse=True), name="b.kicad_pcb")
    volumes = []
    for path in (forward, backward):
        vertices, triangles = mesh_of(import_3d.to_gltf(
            import_3d.read_outline(path), 1.6, path.stem))
        volumes.append(volume_mm3(vertices, triangles))
    assert volumes[0] == pytest.approx(volumes[1], abs=1e-4)
    assert volumes[0] > 0


def test_the_mesh_sits_at_the_origin_and_records_the_corner_it_moved_from(tmp_path):
    """A layout places a board wherever the page put it -- ESP32-PoE at x=90.15
    -- and a mesh 90 mm off origin renders off-screen. Nothing may be lost by
    moving it."""
    path = layout(tmp_path, square(side=10.0, x0=90.15, y0=95.15))
    outline = import_3d.read_outline(path)
    document = import_3d.to_gltf(outline, 1.6, "offset")

    assert document["accessors"][0]["min"] == [0.0, 0.0, 0.0]
    assert document["accessors"][0]["max"] == pytest.approx([10.0, 1.6, 10.0])
    assert document["extras"]["openhardware"]["origin_mm"] == [90.15, 95.15]


def test_a_pad_maps_into_mesh_space_by_subtracting_the_origin(tmp_path):
    """The alignment contract, as arithmetic rather than as a paragraph.

    This is what OH-30 needs: a pad at `(px, py)` in the layout is at
    `(px - origin_x, py - origin_y)` on the mesh's x and z axes.
    """
    body = square(side=10.0, x0=90.15, y0=95.15) + """
  (module TEST (layer F.Cu) (at 93.15 98.15 0)
    (fp_text reference R1 (at 0 0) (layer F.SilkS))
    (pad "1" smd rect (at 0 0) (size 1 1))
  )"""
    path = layout(tmp_path, body)
    outline = import_3d.read_outline(path)
    (reference, px, py), = import_3d.pad_positions(path)

    assert reference == "R1"
    origin_x, origin_y = import_3d.extent(outline, 1.6, "t")["origin_mm"]
    assert (px - origin_x, py - origin_y) == pytest.approx((3.0, 3.0))


# --- refusals, each a shape this cannot honestly extrude ---------------------


def test_an_open_outline_is_refused_and_names_a_loose_point(tmp_path):
    """An open outline has no inside. Extruding one anyway would produce a
    plausible silhouette of a board nobody made, and nothing downstream could
    tell -- which is the whole reason this refuses rather than closes the gap
    with a straight line."""
    three_sides = "\n".join(square().splitlines()[:3])
    path = layout(tmp_path, three_sides)
    with pytest.raises(import_3d.Import3dError, match="not closed"):
        import_3d.read_outline(path)


def test_two_separate_loops_are_refused_rather_than_joined(tmp_path):
    """A board with a cutout, or two boards panelised on one sheet. Every point
    joins exactly two segments, so closure alone does not catch it -- the walk
    returning early is what does."""
    path = layout(tmp_path, square(side=10.0) + "\n" + square(side=4.0, x0=20.0, y0=20.0))
    with pytest.raises(import_3d.Import3dError, match="more than one loop"):
        import_3d.read_outline(path)


def test_a_layout_with_no_edge_cuts_says_what_is_missing(tmp_path):
    """Silence here would be the worst outcome: an empty outline, not an error.
    A line-oriented regex does exactly that on KiCad 7 files."""
    path = layout(tmp_path, "  (gr_line (start 0 0) (end 1 0) (layer F.Cu) (width 0.1))")
    with pytest.raises(import_3d.Import3dError, match="no Edge.Cuts segments"):
        import_3d.read_outline(path)


def test_thickness_is_read_from_the_layout_and_never_defaulted(tmp_path):
    """1.6 mm is the common answer and would have been right for all fifteen
    OLIMEX boards, which is exactly why defaulting is wrong: it would be
    silently wrong on the first 0.8 mm board and nothing would say so."""
    thin = layout(tmp_path, square(), thickness="(thickness 0.8)", name="thin.kicad_pcb")
    assert import_3d.read_thickness_mm(thin) == 0.8

    silent = layout(tmp_path, square(), thickness="(drawings 1)", name="silent.kicad_pcb")
    with pytest.raises(import_3d.Import3dError, match="thickness"):
        import_3d.read_thickness_mm(silent)


def test_both_kicad_generations_read_identically(tmp_path):
    """KiCad 5 writes `(layer Edge.Cuts)` and KiCad 7 writes `(layer
    "Edge.Cuts")`. OLIMEX ships both in one repository, so this is not a
    hypothetical portability concern -- it decides whether three of the fifteen
    boards produce a mesh or an empty one."""
    bare = layout(tmp_path, square(), quoted=False, name="five.kicad_pcb")
    quoted = layout(tmp_path, square(), quoted=True, name="seven.kicad_pcb")
    assert import_3d.read_outline(bare).points == import_3d.read_outline(quoted).points


def test_a_point_inside_and_a_point_outside(tmp_path):
    path = layout(tmp_path, square(side=10.0))
    outline = import_3d.read_outline(path)
    assert outline.contains(5.0, 5.0)
    assert not outline.contains(15.0, 5.0)
    assert not outline.contains(5.0, -1.0)


def test_an_outline_of_fewer_than_three_points_is_refused():
    with pytest.raises(import_3d.Import3dError, match="needs 3 points"):
        import_3d.Outline(((0.0, 0.0), (1.0, 1.0)))


# --- the glTF document -------------------------------------------------------


def test_the_gltf_is_self_contained_and_declares_its_units(tmp_path):
    """One file. The alternative is a `.gltf` beside a `.bin` that has to
    travel with it, and units left to the reader to guess."""
    path = layout(tmp_path, square())
    document = import_3d.to_gltf(import_3d.read_outline(path), 1.6, "square")

    assert document["asset"]["version"] == "2.0"
    assert document["buffers"][0]["uri"].startswith("data:application/octet-stream;base64,")
    assert "uri" not in document["bufferViews"][0]

    summary = document["extras"]["openhardware"]
    assert summary["units"] == "mm"
    assert summary["extent_mm"] == [10.0, 10.0]
    assert summary["thickness_mm"] == 1.6
    assert "gltf y = thickness" in summary["axes"]
    json.dumps(document)  # a document that will not serialise is not a document


def test_the_accessor_bounds_are_the_extent_the_extras_claim(tmp_path):
    """Two independent statements of the same size, in one file. A viewer reads
    the accessor bounds and a person reads the extras, so they must agree."""
    path = layout(tmp_path, square(side=7.5, x0=3.0, y0=4.0))
    document = import_3d.to_gltf(import_3d.read_outline(path), 1.6, "square")
    summary = document["extras"]["openhardware"]
    high = document["accessors"][0]["max"]
    assert high[0] == pytest.approx(summary["extent_mm"][0])
    assert high[2] == pytest.approx(summary["extent_mm"][1])
    assert high[1] == pytest.approx(summary["thickness_mm"])


# --- the vendor's own board, and the vendor's own prose ----------------------


def test_the_outline_agrees_with_the_vendors_written_dimensions(olimex):
    """**The check that is not this parser marking its own homework.**

    `HARDWARE/Revision-changes.txt` is prose, written by OLIMEX, and it says of
    revision J: *"The board PCB extended with 5mm from 28x75mm to 28x80mm"*.
    That is an independent statement of the same fact the geometry carries, in
    a different file, in a different notation, by a different author.

    So this asserts the parser reproduces both numbers **and the revision the
    change lands on**. A mis-scaled or mis-parsed outline would have to be
    wrong in exactly the way the changelog is wrong to pass.
    """
    changes = (olimex / "Revision-changes.txt").read_text(
        encoding="utf-8", errors="replace")
    assert "from 28x75mm to 28x80mm" in changes, "the changelog no longer says this"

    before = import_3d.read_outline(OLIMEX / "ESP32-PoE-hardware-revision-I"
                                   / "ESP32-PoE_Rev_I.kicad_pcb")
    after = import_3d.read_outline(OLIMEX / "ESP32-PoE-hardware-revision-J"
                                  / "ESP32-PoE_Rev_J.kicad_pcb")

    assert (before.width_mm, before.height_mm) == pytest.approx((28.0, 75.0))
    assert (after.width_mm, after.height_mm) == pytest.approx((28.0, 80.0))
    assert after.height_mm - before.height_mm == pytest.approx(5.0)


def test_every_pad_on_the_reference_board_is_inside_its_own_outline(olimex):
    """467 pads and an outline, from different nodes of one document.

    A mirrored, mis-scaled, or wrong-layer outline puts most of a board
    outside itself, so this is the check that the geometry is *right* and not
    merely parseable.
    """
    outline = import_3d.read_outline(REV_C)
    pads = import_3d.pad_positions(REV_C)
    assert len(pads) == 467
    assert import_3d.pads_outside(REV_C, outline) == ()


def test_the_pad_check_finds_the_part_the_vendor_left_unplaced(olimex):
    """The check would be worth nothing if it could never fire, and on this
    repository it does: revision B2 has C12 sitting 13.7 mm past the right
    edge, both pads, still in the layout.

    Two pads out of 475 on one reference is an unplaced component. A broken
    outline would put hundreds outside, on every reference at once -- which is
    why the report names the part rather than only counting."""
    outline = import_3d.read_outline(REV_B2)
    stray = import_3d.pads_outside(REV_B2, outline)

    assert {reference for reference, _, _ in stray} == {"C12"}
    assert len(stray) == 2
    assert len(stray) < len(import_3d.pad_positions(REV_B2)) / 100


def test_the_newest_file_generation_in_the_same_repository_also_reads(olimex):
    """Revisions M, M1 and M2 are KiCad `version 20221018`; everything older is
    `20171130`. One repository, two formats, and the newer three are the ones a
    line-oriented reader silently returns nothing for."""
    outline = import_3d.read_outline(REV_M2)
    assert (outline.width_mm, outline.height_mm) == pytest.approx((28.0, 80.0))
    assert len(outline.points) == 8
    assert import_3d.read_thickness_mm(REV_M2) == 1.6


def test_every_layout_in_the_repository_extrudes_to_a_solid(olimex):
    """Fifteen boards across two file formats and thirteen years of KiCad. A
    parser that handles the one board it was written against is not a parser
    yet."""
    layouts = sorted(olimex.glob("*/*.kicad_pcb"))
    assert len(layouts) == 15, f"expected 15 layouts, found {len(layouts)}"

    for path in layouts:
        outline = import_3d.read_outline(path)
        thickness = import_3d.read_thickness_mm(path)
        vertices, triangles = mesh_of(import_3d.to_gltf(outline, thickness, path.stem))
        expected = abs(outline.signed_area_mm2()) * thickness
        assert volume_mm3(vertices, triangles) == pytest.approx(expected, abs=1e-3), (
            f"{path.name}: mesh volume disagrees with area x thickness"
        )
        assert outline.width_mm == pytest.approx(28.0), path.name
        assert outline.height_mm in (pytest.approx(75.0), pytest.approx(80.0)), path.name


# --- the command line, and the registry row that feeds it --------------------


def test_the_command_line_writes_a_document_and_reports_the_extent(olimex, tmp_path):
    """What a person actually runs. The extent goes to stderr so the glTF can
    go to stdout without the summary landing inside it."""
    out = tmp_path / "board.gltf"
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "import_3d.py"), str(REV_C),
         "--out", str(out), "--check-pads"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "28.0 x 75.0 x 1.6 mm" in result.stderr
    assert "8 outline points" in result.stderr

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["extras"]["openhardware"]["extent_mm"] == [28.0, 75.0]


def test_the_pad_check_fails_the_run_and_names_the_part(olimex, tmp_path):
    """Exit 1, and a message a reader can act on without opening the file."""
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "import_3d.py"), str(REV_B2),
         "--out", str(tmp_path / "b2.gltf"), "--check-pads"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "C12" in result.stderr
    assert "2 of 475" in result.stderr


def test_a_layout_that_is_not_there_is_an_error_not_an_empty_board(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "import_3d.py"),
         str(tmp_path / "absent.kicad_pcb")],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_olimex_is_in_the_registry_and_fetchable_through_the_generic_path():
    """The source this ticket needed, reachable by the tool that already
    exists. Adding a vendor must not add a code path -- see
    `test_the_fetcher_names_no_vendor` in test_board_sources.py."""
    source = board_sources.source("olimex-esp32-poe")
    assert source in board_sources.fetchable()
    assert source.fetch.transport is board_sources.Transport.GIT_SPARSE
    assert source.artefacts.pcb_layout.published is board_sources.Published.YES
    assert source.licence.sampled, "one repository per board; the sibling has no LICENCE"
