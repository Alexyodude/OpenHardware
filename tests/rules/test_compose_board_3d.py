# OpenHardware — a board model composed from CAD, checked against the CAD.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What is worth asserting here, and what is not
#
# `tools/compose_board_3d.py` stands published component meshes on a published
# board outline. Almost none of the interesting content is in the tessellation
# -- that is OpenCASCADE's -- and almost all of it is in the *arithmetic that
# decides where a part goes*: chaining an outline into a ring, triangulating
# it, turning a KiCad model into EAGLE's frame, and anchoring it on the pads.
#
# So the geometry tests below need no OpenCASCADE and no network: they run the
# ring, the triangulation and the placement against shapes whose right answer
# is known by hand. The two that need the real Arduino file skip loudly
# without it, the same way every other vendor-tree test in this repository does.
#
# ## The three bugs these were written after
#
# Each of these was found by measuring the composed model and none of them by
# looking at it, which is the same lesson OH-73's rope recorded four times:
#
#   * EAGLE lays a `1X10` header along x and KiCad lays `PinHeader_1x10` along
#     y, so every header stood across the board. The assembly measured
#     68.58 x 91.44 mm on a board 53.34 mm deep.
#   * `confirm` compared *sorted* spans, so it could not see that -- 22.86 x
#     2.54 sorts the same as 2.54 x 22.86.
#   * The two libraries also disagree about a package's origin: KiCad puts it
#     on pin 1 and EAGLE in the middle of the pin field, which walked the
#     6-pin analog header 2.54 mm off the end of the board.

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools import compose_board_3d as compose  # noqa: E402
from tools import eagle  # noqa: E402

BRD = REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"


def _brd() -> pathlib.Path:
    if not BRD.is_file():
        pytest.skip(
            f"SKIPPED: {BRD.name} is not fetched. Run: "
            f"python tools/get_board_sources.py arduino-uno, which prints the "
            f"URL to download by hand -- it is an https-archive, like the Pico"
        )
    return BRD


def _segments(points):
    """A closed ring as EAGLE would write it: shuffled, and some reversed."""
    made = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        if index % 2:
            start, end = end, start
        made.append(eagle.Segment("20", start[0], start[1], end[0], end[1]))
    return tuple(made[::-1])


# --- the outline ------------------------------------------------------------------


def test_an_outline_chains_into_a_ring_whatever_order_it_is_written_in():
    """EAGLE writes the outline in no order and in no direction.

    The Arduino Uno's twelve segments arrive with the notch's two edges at
    opposite ends of the list and several drawn right-to-left, so a reader that
    assumed either would produce a shape rather than the shape.
    """
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
    ring = compose.loop(_segments(square))
    assert len(ring) == 4
    assert set(ring) == set(square)


def test_an_outline_with_a_segment_touching_nothing_is_refused():
    """A silently-closed polygon is a plausible wrong board.

    Joining the loose ends would extrude something -- and it would look like a
    board, because almost anything convex does.

    **Split from the test below**, and the split is the point. One test that
    accepted either message passed with either guard deleted: they are two
    different failures -- a segment that touches nothing, and a chain whose
    ends do not meet -- and a disjunction cannot tell which guard is gone.
    A mutation removing the first survived exactly that way.
    """
    adrift = (
        eagle.Segment("20", 0.0, 0.0, 10.0, 0.0),
        eagle.Segment("20", 10.0, 0.0, 10.0, 5.0),
        eagle.Segment("20", 0.0, 5.0, 0.0, 0.0),
    )
    with pytest.raises(ValueError, match="does not chain"):
        compose.loop(adrift)


def test_an_outline_that_chains_but_does_not_meet_itself_is_refused():
    """Every segment touches its neighbour and the shape is still open.

    Three points in a line join end to end perfectly well and enclose nothing.
    """
    open_path = (
        eagle.Segment("20", 0.0, 0.0, 10.0, 0.0),
        eagle.Segment("20", 10.0, 0.0, 10.0, 5.0),
    )
    with pytest.raises(ValueError, match="does not close"):
        compose.loop(open_path)


def test_a_concave_outline_is_triangulated_without_leaving_the_board():
    """The Uno's notch is why this is ear clipping and not a fan.

    A fan from one vertex of an L covers area outside it. The check is the
    total triangle area against the polygon's own: they agree for a correct
    triangulation of any simple polygon and disagree for a fan of a concave one.
    """
    ell = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0),
           (0.0, 10.0)]
    triangles = compose.ear_clip(ell)
    assert len(triangles) == len(ell) - 2

    covered = sum(
        abs(compose._cross(ell[a], ell[b], ell[c])) / 2 for a, b, c in triangles
    )
    assert covered == pytest.approx(abs(compose._area(ell)) / 2, rel=1e-9)


def test_the_slab_is_the_outline_and_not_its_bounding_box():
    """An Uno drawn as a rectangle has no notch, and the notch is its shape."""
    ell = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0),
           (0.0, 10.0)]
    mesh = compose.slab(ell, 1.6, "#313d63", (5.0, 5.0))
    positions = mesh.groups["#313d63"][0]
    corner = [(positions[at], -positions[at + 2])
              for at in range(0, len(positions), 3)]
    # (9, 9) is inside the bounding box and outside the L.
    assert not any(x > 4.5 and y > 4.5 for x, y in corner), (
        "the slab covers the notch, so it was extruded from a bounding box"
    )


# --- the correspondence -----------------------------------------------------------


def test_every_correspondence_says_what_was_measured():
    """A table of judgements is only as good as the evidence beside each one.

    `why` exists so the next reader can check the claim rather than trust it,
    and a line that merely restated the mapping would be worse than none.
    """
    for component in compose.CORRESPONDENCE:
        assert len(component.why) > 40, component
        assert "mm" in component.why or "x 2.54" in component.why, component


def test_a_model_too_small_for_its_pads_is_refused():
    """The mistake a name-based table actually makes.

    A `DIL28-3` given a DIP-8 draws a plausible little chip in exactly the
    right place. Only the numbers say otherwise, so the numbers are checked on
    every run rather than at the moment somebody wrote the table.
    """
    element = eagle.Element(
        "ZU4", "lib", "DIL28-3",
        pads=(eagle.Pad("1", "thru_hole", 0.0, 0.0, 1.0, 1.0, None),
              eagle.Pad("28", "thru_hole", 33.02, 7.62, 1.0, 1.0, None)),
        x_mm=0.0, y_mm=0.0, rotation=0.0, mirrored=False,
    )
    class Box:
        """Just the three spans `confirm` reads, so this needs no OpenCASCADE."""

        def __init__(self, width, height):
            self.width = width
            self.height = height

    assert compose.confirm(element, Box(9.0, 33.5), turn=90.0) is None
    complaint = compose.confirm(element, Box(9.0, 10.16), turn=90.0)
    assert complaint is not None and "too short" in complaint, complaint


def test_a_model_turned_the_wrong_way_is_refused():
    """The check that was blind, and is the reason it no longer sorts.

    A one-row header is 22.86 x 0.00 mm of pads and its model is 22.86 x 2.54.
    Turned a quarter, the model is 2.54 x 22.86 -- which sorts identically and
    is a header lying across the board instead of along it.
    """
    header = eagle.Element(
        "IOH", "lib", "1X10",
        pads=(eagle.Pad("1", "thru_hole", 0.0, 0.0, 1.0, 1.0, None),
              eagle.Pad("10", "thru_hole", 22.86, 0.0, 1.0, 1.0, None)),
        x_mm=0.0, y_mm=0.0, rotation=0.0, mirrored=False,
    )

    class Box:
        def __init__(self, width, height):
            self.width = width
            self.height = height

    # KiCad's model runs along y; a quarter turn puts it along x, where the
    # pads are.
    assert compose.confirm(header, Box(2.54, 25.4), turn=90.0) is None
    wrong = compose.confirm(header, Box(2.54, 25.4), turn=0.0)
    assert wrong is not None and "too short" in wrong, wrong


# --- the real board ---------------------------------------------------------------


def test_the_unos_outline_is_the_size_arduino_publishes():
    """68.58 x 53.34 mm is 2.7 x 2.1 inches, to the micron."""
    board = eagle.read_board(_brd())
    ring = compose.loop(board.outline)
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    assert max(xs) - min(xs) == pytest.approx(68.58, abs=0.001)
    assert max(ys) - min(ys) == pytest.approx(53.34, abs=0.001)
    assert len(ring) == 12, "the Uno's silhouette has twelve corners"


def test_the_composed_model_records_what_it_could_not_draw():
    """A part left off the board must say why, not leave a person guessing.

    The XIAO ESP32-C3 sets the precedent: its model is on GrabCAD, that is
    recorded, and nobody re-searches for it.

    **The USB socket used to be on this list and is not any more**, because it
    was modelled instead. What remains are the two parts with no honest source
    of any kind, and each entry has to carry the measurement that rules the
    obvious candidate out -- otherwise the next person re-runs the search.
    """
    assert set(compose.ABSENT) == {"QS", "RESONATOR"}, sorted(compose.ABSENT)
    assert "PN61729" not in compose.ABSENT, (
        "the USB socket is drawn now; ABSENT should no longer claim otherwise"
    )
    for package, why in compose.ABSENT.items():
        assert "mm" in why, f"{package} does not say what was measured"


def test_the_uno_names_a_colour_it_actually_read_somewhere():
    """The one thing here that is neither Arduino's nor KiCad's.

    A PCB colour is in no CAD file this repository has. It is read out of
    PICSimLab's own artwork, and the composition says which file and which
    element -- because an unsourced colour beside two sourced geometries is
    exactly the kind of quiet invention that gets believed.
    """
    spec = compose.COMPOSITIONS[0]
    assert spec.colour.startswith("#") and len(spec.colour) == 7
    assert "board.svg" in spec.colour_source
    assert "path" in spec.colour_source


def test_every_components_legs_land_on_the_board():
    """A pin goes through a hole, so a leg that misses the board is misplaced.

    The analog header ran 2.54 mm past the right-hand edge, because KiCad
    anchors a header on pin 1 and EAGLE anchors it in the middle.

    **This asserted the whole BODY was on the board until the USB socket was
    drawn**, and that was the wrong invariant wearing the right answer's
    clothes: it held only while every part happened to be an interior one. A
    connector is mounted at the edge precisely so that it can overhang -- the
    Uno's USB shell stands 5.94 mm out over the edge and its barrel jack 0.07,
    both correctly. What may never leave the outline is the geometry BELOW the
    board, because that is the pins, and the pins are what the placement is
    anchored on. Measured after the fix: 0.00 mm for all fifteen.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = compose.COMPOSITIONS[0]
    _brd()
    board = eagle.read_board(spec.brd)
    ring = compose.loop(board.outline)
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)
    limits = (min(xs) - centre[0], max(xs) - centre[0],
              -(max(ys) - centre[1]), -(min(ys) - centre[1]))

    by_package = {c.package: c for c in compose.CORRESPONDENCE}
    cache: dict[str, tuple[object, object]] = {}
    worst = 0.0
    for element in board.elements:
        component = by_package.get(element.package)
        if component is None:
            continue
        if component.slug not in cache:
            cache[component.slug] = compose.component_mesh(
                component, compose.DEFLECTION)
        mesh, _box = cache[component.slug]
        put = compose.place(mesh, element, component.turn,
                            spec.thickness_mm, centre)
        below = [(p[at], p[at + 2])
                 for _c, (p, _n, _i) in put.groups.items()
                 for at in range(0, len(p), 3)
                 if p[at + 1] < spec.thickness_mm - 0.5]
        if not below:
            continue  # surface-mount: it has no legs to land anywhere
        px = [point[0] for point in below]
        pz = [point[1] for point in below]
        worst = max(worst, limits[0] - min(px), max(px) - limits[1],
                    limits[2] - min(pz), max(pz) - limits[3])
    assert worst < 0.5, f"a component's legs miss the board by {worst:.2f} mm"


def test_the_written_model_carries_the_scale_the_page_cannot_assume():
    """`board3d.js` scales a model at 8 px/mm, and this board is not 8.

    Every generated board JSON is 8 px/mm because `tools/import_board.py`
    writes them that way. The Arduino Uno's pad map was traced off PICSimLab's
    artwork instead, which is 5.66 -- so the model came out 41% too large and
    stood its headers outside their own markers. `pad_span` is how the page
    works the scale out from the two descriptions of the same pads.
    """
    glb = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not glb.is_file():
        pytest.skip("SKIPPED: run python tools/compose_board_3d.py first")
    from tools.import_3d_model import read_extras

    extras = read_extras(glb)
    assert extras.get("composed") is True
    span = extras["pad_span"]
    assert span[0] == pytest.approx(44.704, abs=0.01)
    assert span[1] == pytest.approx(48.26, abs=0.01)

    landed = json.loads(
        (REPO / "webui" / "boards" / "Arduino Uno.json").read_text(encoding="utf-8")
    )
    pixels = max(p["x"] for p in landed["pads"]) - min(p["x"] for p in landed["pads"])
    assert pixels / span[0] == pytest.approx(5.66, abs=0.02), (
        "the artwork's scale is no longer what the model was composed against"
    )

    # And the markers must ride the pin tips, not the board: an Uno's pads are
    # inside a header shroud and a marker at board level is buried by it.
    assert extras["pad_top"] > extras["pcb"]["thickness"] + 5, extras["pad_top"]


# --- the parts this project had to make itself (OH-76) -----------------------------


def test_a_through_hole_model_on_surface_mount_pads_is_refused():
    """The check the size tolerance could not do, and the part that needed it.

    `Y2` on the Uno is a 3.20 x 1.60 mm surface-mount resonator, by the
    vendor's own silkscreen. KiCad's only three-pin resonators are 7 mm
    through-hole cans standing 12.5 mm tall, and the size check *passed* one --
    7 mm against 2 mm of pads is inside a tolerance that has to allow a body
    wider than its pins. What tells them apart is that one has legs.
    """
    surface = eagle.Element(
        "Y2", "lib", "RESONATOR",
        pads=(eagle.Pad("1", "smd", 0.0, 0.0, 1.0, 1.0, None),
              eagle.Pad("2", "smd", 2.0, 0.0, 1.0, 1.0, None)),
        x_mm=0.0, y_mm=0.0, rotation=0.0, mirrored=False,
    )

    class Box:
        def __init__(self, width, height):
            self.width = width
            self.height = height

    legged = compose.Mesh({"#888888": ([0.0, 0.0, -2.0, 1.0, 0.0, -2.0,
                                        0.5, 1.0, -2.0], [0.0] * 9, [0, 1, 2])})
    flat = compose.Mesh({"#888888": ([0.0, 0.0, 0.5, 1.0, 0.0, 0.5,
                                      0.5, 1.0, 0.5], [0.0] * 9, [0, 1, 2])})

    assert compose.confirm(surface, Box(7.0, 2.5), 0.0) is None, (
        "without the mesh the size check alone still accepts it, which is the "
        "whole reason the mounting check exists"
    )
    complaint = compose.confirm(surface, Box(7.0, 2.5), 0.0, legged)
    assert complaint is not None and "through-hole part" in complaint, complaint
    assert compose.confirm(surface, Box(7.0, 2.5), 0.0, flat) is None


def test_a_surface_mount_model_on_through_hole_pads_is_refused():
    """The other direction, which is just as wrong and much easier to miss."""
    through = eagle.Element(
        "ZU4", "lib", "DIL28-3",
        pads=(eagle.Pad("1", "thru_hole", 0.0, 0.0, 1.0, 1.0, None),
              eagle.Pad("28", "thru_hole", 33.02, 7.62, 1.0, 1.0, None)),
        x_mm=0.0, y_mm=0.0, rotation=0.0, mirrored=False,
    )

    class Box:
        def __init__(self, width, height):
            self.width = width
            self.height = height

    flat = compose.Mesh({"#888888": ([0.0, 0.0, 0.5, 1.0, 0.0, 0.5,
                                      0.5, 1.0, 0.5], [0.0] * 9, [0, 1, 2])})
    complaint = compose.confirm(through, Box(9.0, 34.0), 90.0, flat)
    assert complaint is not None and "surface-mount part" in complaint, complaint


def test_the_obj_reader_keeps_one_colour_group_per_material(tmp_path):
    """Blender cannot write STEP, so a modelled part arrives as OBJ.

    The material groups are the point: a shell, a cavity and a pin are three
    colours in one file, and losing them would make the socket one grey lump.
    """
    (tmp_path / "part.mtl").write_text(
        "newmtl shell\nKd 0.500000 0.500000 0.500000\n"
        "newmtl pin\nKd 1.000000 0.000000 0.000000\n", encoding="utf-8")
    (tmp_path / "part.obj").write_text(
        "mtllib part.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
        "vn 0 0 1\n"
        "usemtl shell\nf 1//1 2//1 3//1\n"
        "usemtl pin\nf 1//1 2//1 4//1\n", encoding="utf-8")

    mesh, extent = compose.read_obj(tmp_path / "part.obj")
    # 0.5 is 127.5 of 255 and Python rounds a half to even, so it is 0x80 --
    # which is also `UNSTYLED`, the colour an OBJ with no material gets. That
    # collision is harmless because the key is only ever a colour, but it is
    # the sort of thing worth having written down before somebody chases it.
    assert sorted(mesh.groups) == ["#808080", "#ff0000"]
    assert mesh.triangles() == 2
    assert (extent.width, extent.height, extent.thickness) == (1.0, 1.0, 1.0)


def test_the_obj_reader_triangulates_a_quad(tmp_path):
    """Blender exports box faces as quads, and a fan is right for a convex one.

    Not a general polygon triangulation -- `ear_clip` is, and the board outline
    is why it has to be.
    """
    (tmp_path / "q.obj").write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvn 0 0 1\n"
        "f 1//1 2//1 3//1 4//1\n", encoding="utf-8")
    mesh, _extent = compose.read_obj(tmp_path / "q.obj")
    assert mesh.triangles() == 2


def test_the_obj_reader_refuses_a_face_that_is_not_a_polygon(tmp_path):
    """Skipping it would draw most of a part, which is worse than refusing."""
    (tmp_path / "bad.obj").write_text(
        "v 0 0 0\nv 1 0 0\nvn 0 0 1\nf 1//1 2//1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a polygon"):
        compose.read_obj(tmp_path / "bad.obj")


def test_every_modelled_dimension_cites_where_it_came_from():
    """The rule that makes a hand-built part safe to have in here at all.

    A modelled mesh is the fourth and worst source of geometry in this project.
    What keeps it honest is that each number it uses which is NOT in the
    vendor's file carries its source -- so the diff shows a citation changing
    whenever a number does.
    """
    from tools import model_from_datasheet

    assert model_from_datasheet.SPECS, "nothing is modelled, so this is vacuous"
    for spec in model_from_datasheet.SPECS:
        assert spec.why_not_fetched.strip(), spec.name
        assert spec.cited, f"{spec.name} cites nothing, so it invented nothing?"
        for field, (value, why) in spec.cited.items():
            assert isinstance(value, float), f"{spec.name}.{field}"
            assert len(why) > 40, f"{spec.name}.{field} has no real citation"


def test_the_modelled_usb_socket_is_built_from_the_vendors_own_footprint():
    """Every number in plan is Arduino's, which is why it cannot drift.

    A pad table retyped into the model would be a second source that can
    disagree with the first, and it would disagree silently -- the same defect
    `lead_tips` records in `tools/import_3d_model.py`.
    """
    from tools import model_from_datasheet

    _brd()
    spec = next(s for s in model_from_datasheet.SPECS
                if s.package == "PN61729")
    plan = model_from_datasheet.plan_geometry(spec)

    assert len(plan["pins"]) == 4, plan["pins"]
    assert len(plan["posts"]) == 2, plan["posts"]
    assert plan["x"][1] - plan["x"][0] == pytest.approx(11.80, abs=0.001)
    assert plan["y"][1] - plan["y"][0] == pytest.approx(15.75, abs=0.001)
    # The four signal pins are a 2.5 x 2.0 mm rectangle; the shell posts are
    # 12 mm apart. Both straight out of the vendor's package.
    assert sorted({round(x, 3) for x, _y in plan["pins"]}) == [-1.25, 1.25]
    assert sorted({round(x, 3) for x, _y in plan["posts"]}) == [-6.0, 6.0]


def test_the_usb_socket_is_drawn_and_marked_as_modelled():
    """It is on the board now, and the page has to say it was made here."""
    usb = [c for c in compose.CORRESPONDENCE if c.package == "PN61729"]
    assert usb, "the USB socket is not in the correspondence"
    assert usb[0].modelled is True
    assert usb[0].turn == 0.0, (
        "a modelled part is built in the vendor package's own frame, so it "
        "needs no turn -- that is the advantage of building rather than matching"
    )


def test_a_through_hole_components_legs_land_on_its_own_pads():
    """The tight version of the test above, and the one the anchor needs.

    "Legs somewhere on the board" is loose enough that reverting the anchor to
    the body centre survived it: the barrel jack moved by millimetres and
    stayed inside the outline. What `place` actually guarantees is stronger --
    a part's legs sit on the pads that part is soldered to -- and that is only
    true because a through-hole model is anchored on its legs rather than on
    its body.

    It matters for exactly the parts whose body is not centred on their pins.
    A DIP or a header would pass either way; a barrel jack, whose barrel is all
    to one side, and a USB socket, whose shell overhangs the board, would not.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = compose.COMPOSITIONS[0]
    _brd()
    board = eagle.read_board(spec.brd)
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)

    by_package = {c.package: c for c in compose.CORRESPONDENCE}
    cache: dict[str, tuple[object, object]] = {}
    worst, worst_name = 0.0, ""
    checked = 0
    for element in board.elements:
        component = by_package.get(element.package)
        if component is None or not element.pads_of("thru_hole"):
            continue
        if component.slug not in cache:
            cache[component.slug] = compose.component_mesh(
                component, compose.DEFLECTION)
        mesh, _box = cache[component.slug]
        put = compose.place(mesh, element, component.turn,
                            spec.thickness_mm, centre)
        legs = [(p[at], p[at + 2])
                for _c, (p, _n, _i) in put.groups.items()
                for at in range(0, len(p), 3)
                if p[at + 1] < spec.thickness_mm - 0.5]
        assert legs, f"{element.name} is through-hole and has no legs"
        leg_x = (min(v[0] for v in legs) + max(v[0] for v in legs)) / 2
        leg_z = (min(v[1] for v in legs) + max(v[1] for v in legs)) / 2

        x0, y0, x1, y1 = element.pad_extent()
        pad_x = (x0 + x1) / 2 - centre[0]
        pad_z = -((y0 + y1) / 2 - centre[1])
        miss = max(abs(leg_x - pad_x), abs(leg_z - pad_z))
        checked += 1
        if miss > worst:
            worst, worst_name = miss, element.name

    assert checked >= 8, f"only {checked} through-hole components were checked"
    assert worst < 0.5, (
        f"{worst_name}'s legs sit {worst:.2f} mm from the pads it is soldered to"
    )
