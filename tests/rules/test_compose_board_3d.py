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

import dataclasses
import json
import math
import pathlib
import struct
import sys
from unittest import mock

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools import compose_board_3d as compose  # noqa: E402
from tools import eagle  # noqa: E402
from tools import kicad  # noqa: E402

BRD = REPO / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"


def _brd() -> pathlib.Path:
    if not BRD.is_file():
        pytest.skip(
            f"SKIPPED: {BRD.name} is not fetched. Run: "
            f"python tools/get_board_sources.py arduino-uno, which prints the "
            f"URL to download by hand -- it is an https-archive, like the Pico"
        )
    return BRD


def _uno():
    """The Arduino Uno's composition, BY NAME.

    These tests used `COMPOSITIONS[0]`, which was the Uno while it was the only
    composed board. OH-93 added the XIAO ESP32-C3, so a positional index is now
    one reordering away from pointing every Uno assertion at a different board
    -- and they would not fail, they would measure the wrong thing.
    """
    for spec in compose.COMPOSITIONS:
        if spec.board == "Arduino Uno":
            return spec
    raise AssertionError("the Arduino Uno is no longer a composed board")


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


def test_a_five_micron_gap_in_the_vendors_own_drawing_still_closes():
    """Seeed's XIAO RP2350 and nRF54L15 miss by 0.005 mm four times each.

    Where a routed slot's arc meets its line they write `66.6404` against
    `66.6354`. Five microns is a tenth of what any fab holds, so the board is
    made from that file exactly as drawn -- and a reader that demanded an
    exact meeting called it "the outline does not chain", which reads like a
    parse failure and is a correct parse of a drawing with a gap in it.
    """
    gapped = (
        eagle.Segment("20", 0.0, 0.0, 10.0, 0.0),
        eagle.Segment("20", 10.0, 0.005, 10.0, 5.0),
        eagle.Segment("20", 10.0, 5.0, 0.0, 5.0),
        eagle.Segment("20", 0.0, 5.0, 0.0, 0.0),
    )
    assert len(compose.loop(gapped)) == 4


def test_a_gap_the_size_of_a_real_feature_is_still_refused():
    """The tolerance has to sit between two measured things, and it does.

    Across the five boards this composes, the largest gap that MUST close is
    0.00559 mm and the closest endpoints that must NOT join are 0.19079 mm --
    two consecutive points along an arc some other entity was expanded into,
    at `ARC_CHORD_MM`. So the ceiling is this file's own chord length and not
    a vendor's, and a tolerance approaching it would weld a curve to its
    neighbour instead of reporting a hole in the drawing.
    """
    assert compose.CHAIN_TOLERANCE_MM < compose.ARC_CHORD_MM / 5, (
        "a chaining tolerance near the chord length joins points that are "
        "merely adjacent along a curve"
    )
    holed = (
        eagle.Segment("20", 0.0, 0.0, 10.0, 0.0),
        eagle.Segment("20", 10.0, 0.19, 10.0, 5.0),
        eagle.Segment("20", 10.0, 5.0, 0.0, 5.0),
        eagle.Segment("20", 0.0, 5.0, 0.0, 0.0),
    )
    with pytest.raises(ValueError, match="does not chain"):
        compose.loop(holed)


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

    **The USB socket used to be on this list and is not any more**, because it
    was modelled instead. What remains are parts with no honest source of any
    kind, and each entry has to carry the measurement that rules the obvious
    candidate out -- otherwise the next person re-runs the search.

    This asserted `set(ABSENT) == {"QS", "RESONATOR"}` while the Uno was the
    only board that left anything off. A pinned literal is a tripwire against
    a casual addition and nothing more, and OH-93's five boards turned it into
    a line to re-pin rather than a check -- so the invariants below replace it
    with things that stay true as boards are added.
    """
    assert "PN61729" not in compose.ABSENT, (
        "the USB socket is drawn now; ABSENT should no longer claim otherwise"
    )
    for package, why in compose.ABSENT.items():
        assert "mm" in why, f"{package} does not say what was measured"
        # **"We looked and it is not there" is only checkable if you say
        # where you looked.** Every entry names the library it searched, so
        # the claim can be re-run against that library rather than retaken on
        # trust -- which is the whole reason these paragraphs are long.
        assert "KiCad" in why, (
            f"{package} does not name the library that was searched"
        )


def test_nothing_is_declared_absent_that_no_board_actually_has():
    """An `ABSENT` key is a vendor's package name, typed out by hand.

    Get one letter wrong and the entry is dead: the board draws without the
    part and without the explanation, which is the exact state the dict exists
    to prevent, and nothing else fails. **This is not hypothetical** -- Seeed
    write the C3's load switch `PMOS_1.0_0.6_0.35MM` and the other three
    boards' `PMOS_1.0X0.6X0.35MM`, so the obvious single key silently covered
    three boards out of four.

    Skips per layout rather than in one lump, so a checkout holding some of
    the vendor files still checks those.
    """
    seen: set[str] = set()
    for spec in compose.COMPOSITIONS:
        if not spec.layout.is_file():
            continue
        seen |= {e.package for e in compose.read_layout(spec.layout).elements}
    if not seen:
        pytest.skip("SKIPPED: no vendor layout is fetched")
    unused = [p for p in compose.ABSENT if p not in seen]
    assert not unused, (
        f"{unused} appear in ABSENT and on no fetched board. Either the "
        f"package name is mistyped -- in which case the board draws without "
        f"the part AND without the reason -- or the entry outlived its board."
    )


#: Board -> the omissions its model is expected to explain to a reader.
#:
#: **Pinned per board, where the old global pin was not.** `set(ABSENT) ==
#: {"QS", "RESONATOR"}` had to be re-pinned every time a board was added and
#: said nothing about any particular model. This says something true of each:
#: *this* board's `.glb` carries *these* reasons. Adding a board makes it fail
#: until its omissions are stated, which is the point.
#:
#: It is not "every part not drawn". The Arduino Uno leaves its SMB diode, its
#: MSOP-8 and a dozen 0603s undrawn and always has; what has to be explained
#: is what a person would look for and miss.
EXPLAINS: dict[str, set[str]] = {
    "Arduino Uno": {"QS", "RESONATOR"},
    "XIAO-ESP32-C3-DIP": {"PMOS_1.0_0.6_0.35MM", "BUTTON_TD1183SA"},
    # Its antenna and buttons were here until OH-104 modelled them.
    "XIAO-ESP32-C6-DIP": {"PMOS_1.0X0.6X0.35MM"},
    # The C5's only stated omission: its buttons, which name no height.
    "XIAO-ESP32-C5-DIP": {"BUTTON_TD1183SA"},
    # The RP2350's own chip was here until OH-100 modelled it.
    "XIAO-RP2350-DIP": {"PMOS_1.0X0.6X0.35MM"},
    # Its own processor, its antenna and its coaxial socket were here until
    # OH-104 modelled all three; the buttons stay, having no stated height.
    "XIAO-nRF54l15-DIP": {"BUTTON_TD1183SA", "PMOS_1.0X0.6X0.35MM"},
}


def test_each_board_explains_the_parts_it_leaves_off():
    """A missing part with no reason beside it reads as a broken importer.

    **Seeed spell the same part differently from board to board**, and that is
    what this catches. Their load switch is `PMOS_1.0_0.6_0.35MM` on the
    ESP32-C3 and `PMOS_1.0X0.6X0.35MM` on the other three; their module
    footprint gains a `-PRO`; a `QFN32G` becomes a `QFN32`. So one obvious key
    silently covers three boards out of four, and the fourth loses its
    explanation without anything failing.
    """
    assert set(EXPLAINS) == {spec.board for spec in compose.COMPOSITIONS}, (
        "a composed board with no entry here has never had its omissions "
        "stated -- add it rather than deleting this assertion"
    )
    for spec in compose.COMPOSITIONS:
        if not spec.layout.is_file():
            continue
        packages = {e.package for e in compose.read_layout(spec.layout).elements}
        for missing in EXPLAINS[spec.board]:
            assert missing in packages, (
                f"{spec.board} has no {missing!r}, so this expectation is "
                f"stale or the package name is mistyped"
            )
            assert missing in compose.ABSENT, (
                f"{spec.board} leaves {missing!r} off and says nothing about "
                f"it. A reader sees a board with a part visibly gone and no "
                f"reason, which is the state ABSENT exists to prevent."
            )



def _glb_groups(path: pathlib.Path) -> dict[str, list[tuple[float, float, float]]]:
    """Vertices per colour out of a shipped `.glb`, in the scene's own frame.

    Reading the ARTEFACT rather than recomposing it, deliberately: what a
    person looked at and called broken is the file the page loads, and a test
    that rebuilt the mesh in memory would be checking a different object. The
    cost is that it skips in a checkout where nothing has been composed, which
    is the same trade every shipped-mesh test here makes.
    """
    raw = path.read_bytes()
    json_length = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20:20 + json_length])
    binary = raw[20 + json_length + 8:]
    out: dict[str, list[tuple[float, float, float]]] = {}
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            colour = doc["materials"][primitive["material"]]["name"]
            access = doc["accessors"][primitive["attributes"]["POSITION"]]
            view = doc["bufferViews"][access["bufferView"]]
            at = view.get("byteOffset", 0) + access.get("byteOffset", 0)
            flat = struct.unpack_from(f"<{access['count'] * 3}f", binary, at)
            out.setdefault(colour, []).extend(
                [(flat[i], flat[i + 1], flat[i + 2])
                 for i in range(0, len(flat), 3)])
    return out


#: The gold and brass a KiCad model gives a plated contact. Every one of these
#: was read off a shipped mesh rather than chosen: they are what the vendors'
#: own STEP files style their pins and shells with.
CONTACT_COLOURS = frozenset({"#b58136", "#ebbc51", "#edbe51", "#c6c4a0"})

#: How high above the board a plated contact still counts as touching it.
#:
#: **A USB-C's contacts do not all end on the board, and that is correct.**
#: The solder tails sit on the pads; the same contacts then run forward onto
#: the tongue, which is inside a shell that overhangs the edge. So gold past
#: the outline is normal a couple of millimetres up, and only gold at BOARD
#: LEVEL is a tail that has missed its pad.
#:
#: The first version of this test had no such band and passed only because
#: every receptacle was turned wrongly at the time.
TOUCHING_THE_BOARD_MM = 0.35

#: How far a contact that touches the board may lie outside the outline.
#:
#: **Zero, since OH-102 modelled the receptacle the vendor actually fitted.**
#: It was 0.05 while two boards carried a connector 3.15 mm longer than the
#: one Seeed name, and a hair of allowance is what a part of the wrong size
#: needs. Measured on the shipped meshes, negative being inside:
#:
#:     Arduino Uno         -2.093 mm
#:     XIAO-RP2350-DIP     -1.146
#:     XIAO-ESP32-C5-DIP   -0.881
#:     XIAO-ESP32-C3-DIP   -0.372
#:     XIAO-nRF54l15-DIP   -0.156
#:     XIAO-ESP32-C6-DIP   -0.152
#:
#: The last three are the U.FL socket's own shell rather than a receptacle
#: tail; every USB-C contact on every board is further in than that. The
#: number that made this a test is 0.42: that is how far the WRONG receptacle
#: put them, and it is what a person looking at the board saw as a connector
#: hanging in mid-air.
CONTACT_OVERHANG_MM = 0.0


def test_no_soldered_contact_hangs_off_the_board():
    """A pin is soldered to a pad, and a pad is on the board.

    **This is the check that would have caught OH-101 and did not exist.**
    Seeed use two USB-C land patterns and OH-93 gave both the same model, so
    matching a four-tab model to a two-lock land slid the connector forward
    and left its contact row 0.42 mm past the board edge, in mid-air.

    Every other check passed. `confirm` measures the model's footprint against
    the pad span and the wrong part was 2.46 mm short of a 10.240 mm land,
    inside a `SPAN_TOLERANCE_MM` of 3.0 that is deliberately generous because
    a body and its pads are legitimately different sizes. So the tolerance is
    not the thing to tighten -- this is.
    """
    models = REPO / "webui" / "static" / "models"
    boards = [slug for slug in
              (compose._slug(spec.board) for spec in compose.COMPOSITIONS)
              if (models / f"{slug}.glb").is_file()]
    if not boards:
        pytest.skip("no board composed; run tools/compose_board_3d.py")
    worst: list[str] = []
    for slug in boards:
        groups = _glb_groups(models / f"{slug}.glb")
        pcb = groups.get(compose.BOARD_MASK) or groups.get("#313d63")
        assert pcb, f"{slug} has no PCB group to measure against"
        left, right = min(p[0] for p in pcb), max(p[0] for p in pcb)
        near, far = min(p[2] for p in pcb), max(p[2] for p in pcb)
        top = max(p[1] for p in pcb)
        for colour in CONTACT_COLOURS & set(groups):
            for x, y, z in groups[colour]:
                if y - top > TOUCHING_THE_BOARD_MM:
                    continue
                out = max(left - x, x - right, near - z, z - far)
                if out > CONTACT_OVERHANG_MM:
                    worst.append(f"{slug}: {colour} at ({x:.3f}, {z:.3f}) is "
                                 f"{out:.3f} mm outside the PCB")
                    break
    assert not worst, "\n".join(worst)


def test_a_legged_model_is_anchored_on_the_holes_its_legs_go_into():
    """Like against like, which is what OH-101 half-fixed and OH-102 finished.

    `place` anchors a through-hole model on its legs, because a barrel jack's
    body is entirely to one side of its pins. The pads those legs go into are
    the through-hole ones -- and until this, they were compared against EVERY
    pad on the footprint, which is only the same answer when every pad is a
    hole.

    The USB-C is the part where they differ: its two board locks sit 4.75 mm
    from its contact row, so the two answers are 2.26 mm apart on the RP2350
    and the whole connector landed that far inboard of where it belongs.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    usb = next(e for e in board.elements
               if e.package == "USB2.0-TYPE-C_USB-31C-F-16P")

    locks = usb.pads_of("thru_hole")
    assert len(locks) == 2, "this land pattern has two board locks"
    legged = compose.anchor_of(usb, legged=True)
    assert legged[0] == pytest.approx(locks[0].x_mm, abs=0.001), (
        "both locks share one x, so the legged anchor is that x"
    )
    flat = compose.anchor_of(usb, legged=False)
    assert abs(legged[0] - flat[0]) == pytest.approx(2.263, abs=0.01), (
        "the two anchors are 2.26 mm apart, which is the whole bug"
    )


def test_a_surface_mount_model_is_anchored_on_every_pad_it_covers():
    """The other half of the same rule, and it must not change.

    A model with no legs is anchored on its body, and a body sits over all of
    its pads -- so narrowing the anchor to the through-hole ones for everything
    would put every surface-mount part in the wrong place, or crash on the
    thousands that have no hole at all.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    chip = next(e for e in board.elements if e.package == "QFN60-0.4-7X7X0.9MM")

    assert not chip.pads_of("thru_hole"), "a QFN has no holes"
    x0, y0, x1, y1 = chip.pad_extent()
    assert compose.anchor_of(chip, legged=False) == pytest.approx(
        ((x0 + x1) / 2, (y0 + y1) / 2))


def test_a_legged_model_on_a_footprint_with_no_holes_is_refused():
    """The case that would silently divide by nothing, said out loud.

    `confirm` refuses this pairing before `place` sees it -- a model with legs
    on a footprint with no holes is a through-hole part on surface-mount pads.
    This is the belt behind that brace, and it exists because narrowing the
    anchor is what created the possibility of an empty list.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    chip = next(e for e in board.elements if e.package == "QFN60-0.4-7X7X0.9MM")

    with pytest.raises(SystemExit, match="no through-hole pad"):
        compose.anchor_of(chip, legged=True)


def test_the_legged_anchor_is_the_one_place_actually_uses():
    """`anchor_of` can be right while nothing consults it.

    A mutation replacing `place`'s call with `anchor_of(element, False)` --
    reverting the whole fix -- survived every test that called the function
    directly, and survived the composed boards too, because the only board
    `compose` is driven over in this suite is the ESP32-C3, whose receptacle
    draws no `F.Fab` and so has no body for `silk_miss` to check. This drives
    it through `place` on a board where the two anchors are 2.26 mm apart.

    It is the same lesson OH-103's `body_allowance` and OH-107's
    `contact_miss` each cost a round of: measure the guard, not only the
    measurement.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    made = compose.MODELLED / "USB2.0-TYPE-C_USB-31C-F-16P.obj"
    if not made.is_file():
        pytest.skip("SKIPPED: run python tools/model_from_datasheet.py")

    board = compose.read_layout(spec.layout)
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    usb = next(e for e in board.elements
               if e.package == "USB2.0-TYPE-C_USB-31C-F-16P")
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == usb.package)
    mesh, _box = compose.component_mesh(component, compose.DEFLECTION)

    put = compose.place(mesh, usb, component.turn, spec.thickness_mm, centre)
    legs = [(p[at], p[at + 2]) for _c, (p, _n, _i) in put.groups.items()
            for at in range(0, len(p), 3)
            if p[at + 1] < spec.thickness_mm - compose.LEAD_DEPTH_MM]
    assert legs, "the receptacle's board locks are not below the board"
    leg_x = (min(v[0] for v in legs) + max(v[0] for v in legs)) / 2
    leg_z = (min(v[1] for v in legs) + max(v[1] for v in legs)) / 2

    lock_x, lock_y = compose.anchor_of(usb, legged=True)
    assert leg_x == pytest.approx(lock_x - centre[0], abs=0.01), (
        f"the locks are drawn at x {leg_x:.3f} and the holes they go into are "
        f"at {lock_x - centre[0]:.3f}"
    )
    assert leg_z == pytest.approx(-(lock_y - centre[1]), abs=0.01)


def test_every_modelled_slab_agrees_with_the_outline_the_vendor_drew():
    """Reading a dimension out of a STRING is only safe if something checks it.

    A slab's height comes from the last field of the vendor's own footprint
    name, because a land pattern cannot express it. The name states the plan
    too -- and that is not redundant: comparing it against the `F.Fab`
    assembly outline is what proves the name was parsed correctly. A name read
    wrongly, a pitch taken for a length, misses by millimetres.

    Measured 2026-08-29, the eight agree to between 0.000 and 0.267 mm.
    """
    from tools import model_from_datasheet

    assert model_from_datasheet.SLABS, "nothing is modelled as a slab"
    for spec in model_from_datasheet.SLABS:
        if not spec.pcb.is_file():
            continue
        plan = model_from_datasheet.slab_geometry(spec)
        assert plan["apart"] <= model_from_datasheet.NAMED_BODY_TOLERANCE_MM, spec
        assert plan["height"] > 0.0, spec


def test_a_package_that_states_no_height_is_not_modelled_as_a_slab():
    """The one number no layer carries, so guessing it is the whole risk.

    **A button is why this matters.** `BUTTON_TD1183SA` has an `F.Fab`
    outline and no height anywhere -- and a button STANDS PROUD of the board,
    which is the point of it, so a slab of invented thickness would be exactly
    what this file exists not to draw. It stays in `ABSENT` while the C6's and
    RP2350's switches, whose names DO state 0.53 mm, are drawn.
    """
    from tools import model_from_datasheet

    spec = dataclasses.replace(model_from_datasheet.SLABS[0],
                               package="BUTTON_TD1183SA",
                               pcb=compose.PCB_CACHE / "nRF54L15.kicad_pcb")
    if not spec.pcb.is_file():
        pytest.skip("SKIPPED: nRF54L15.kicad_pcb is not fetched")
    with pytest.raises(SystemExit, match="states no length x width x height"):
        model_from_datasheet.slab_geometry(spec)
    assert "BUTTON_TD1183SA" in compose.ABSENT
    assert "no height" in compose.ABSENT["BUTTON_TD1183SA"], (
        "the entry has to say WHICH number is missing, or the next person "
        "models it from the F.Fab outline it does have"
    )


def test_a_name_that_disagrees_with_the_outline_is_refused():
    """The check that makes the parse safe, shown refusing.

    A package renamed to claim a body twice its drawn size is the shape of a
    misread name, and it must not draw either dimension.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SLABS
                if s.package.startswith("ANT2P"))
    if not spec.pcb.is_file():
        pytest.skip("SKIPPED: nRF54L15.kicad_pcb is not fetched")
    body = spec.pcb.read_text(encoding="utf-8", errors="replace")
    lying = body.replace("ANT2P-5.2x2x1.1MM", "ANT2P-11.0x4.0x1.1MM")
    assert lying != body, "the substitution did not take"
    scratch = spec.pcb.with_name("ANT-lying.kicad_pcb")
    scratch.write_text(lying, encoding="utf-8")
    try:
        wrong = dataclasses.replace(spec, package="ANT2P-11.0x4.0x1.1MM",
                                    pcb=scratch)
        with pytest.raises(SystemExit, match="mm apart"):
            model_from_datasheet.slab_geometry(wrong)
    finally:
        scratch.unlink()


def test_a_modelled_slab_is_declared_as_built_here():
    """The page has to say which parts were made rather than fetched.

    `modelled` is what carries that all the way to a reader, and a slab is the
    furthest from a measurement anything here gets -- so it is the last thing
    that should arrive looking like a vendor's own model.
    """
    from tools import model_from_datasheet

    by_package = {c.package: c for c in compose.CORRESPONDENCE}
    for spec in model_from_datasheet.SLABS:
        component = by_package.get(spec.package)
        assert component is not None, f"{spec.package} is modelled and not drawn"
        assert component.modelled is True, spec.package
        assert component.library == "modelled", spec.package
        assert component.model == spec.name, spec.package
        assert component.turn == 0.0, (
            "a modelled part is built in the vendor package's own frame"
        )
        assert spec.package not in compose.ABSENT, (
            f"{spec.package} is drawn now; ABSENT should not claim otherwise"
        )


def test_a_usb_socket_faces_off_the_board_a_cable_can_reach():
    """The user's report, three times over: "the usb plug is orientated in the
    wrong way".

    It was, and the turn was settled wrongly twice before this test existed --
    0, then 90, and only then 270. Two things have to hold:

      * a receptacle's 8.95 mm width -- fixed by the standard that lets any
        cable enter any socket, and drawn by Seeed on `F.Fab` as
        7.370 x 8.950 mm -- lies ALONG the board edge, which rules out the
        pair of turns that put its depth there;
      * its plated contacts land on the pads they solder to, which picks
        between the remaining two.

    **The second is the one that had to be measured rather than looked at.**
    OH-105 chose by finding which end had least triangle area in its plane,
    reasoning that a mouth is a rim and a back is a filled face. What that
    measured was the thin solder tails crossing the plane, so it named the
    back as the mouth and faced the socket into the board. The margin here is
    a factor of two to five and needs no interpretation.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    receptacles = {c.package: c for c in compose.CORRESPONDENCE
                   if c.package.startswith("USB2.0-TYPE-C")}
    assert receptacles, "no USB-C is drawn"
    meshes = {package: compose.component_mesh(component, 0.05)
              for package, component in receptacles.items()}

    checked = 0
    for spec in compose.COMPOSITIONS:
        if spec.pcb_chip is None or not spec.layout.is_file():
            continue
        board = compose.read_layout(spec.layout)
        pads = [pad for name in spec.headers
                for pad in board.element(name).pads]
        centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
                  (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
        for element in board.elements:
            if element.package not in receptacles:
                continue
            checked += 1
            component = receptacles[element.package]
            mesh, _box = meshes[element.package]
            put = compose.place(mesh, element, component.turn,
                                spec.thickness_mm, centre)
            xs = [p[at] for _c, (p, _n, _i) in put.groups.items()
                  for at in range(0, len(p), 3)]
            zs = [p[at + 2] for _c, (p, _n, _i) in put.groups.items()
                  for at in range(0, len(p), 3)]
            along, across = max(zs) - min(zs), max(xs) - min(xs)
            #: The vendor's own stated envelope, 8.94 x 7.35 mm, as the FLOOR
            #: rather than a window: the mesh reaches past the body at both
            #: ends -- shell tabs across the edge, solder tails inboard -- so
            #: it can only be larger. The window this used to be was measured
            #: off the published models, and a modelled part's tabs broke it
            #: while being more correct than what it was measuring.
            assert along > 8.9, (
                f"{spec.board} {element.name}: {along:.3f} mm lies along the "
                f"board edge and a USB-C receptacle is 8.94 mm wide"
            )
            assert across > 7.3, (
                f"{spec.board} {element.name}: only {across:.3f} mm points "
                f"off the edge, and Seeed's own Description says 7.35 mm deep"
            )
            assert along > across, (
                f"{spec.board} {element.name}: {across:.3f} mm points off the "
                f"edge against {along:.3f} along it, so the receptacle's DEPTH "
                f"is lying along the edge. It is turned a quarter out, and a "
                f"cable would go in sideways."
            )
            here = compose.contact_miss(element, put, centre)
            assert here is not None, f"{element.name} has no contacts to place"
            for other in (0.0, 90.0, 180.0, 270.0):
                if other == component.turn:
                    continue
                rival = compose.contact_miss(
                    element,
                    compose.place(mesh, element, other, spec.thickness_mm,
                                  centre),
                    centre)
                assert here < rival - compose.TURN_MARGIN_MM, (
                    f"{spec.board} {element.name} at {component.turn:.0f} puts "
                    f"its contacts {here:.3f} mm from their pads, and "
                    f"{other:.0f} puts them {rival:.3f}"
                )
    #: Derived rather than pinned: every composed XIAO carries exactly one
    #: USB-C, so this follows the board list instead of needing a new number
    #: each time one is added -- and it still catches a loop that quietly ran
    #: over nothing, which is what a bare count is for.
    xiaos = [s for s in compose.COMPOSITIONS
             if s.pcb_chip is not None and s.layout.is_file()]
    assert checked == len(xiaos), (
        f"{len(xiaos)} composed XIAOs are fetched and {checked} USB-C sockets "
        f"were checked"
    )


def test_composing_refuses_a_part_turned_the_wrong_way():
    """The guard, not the measurement it rests on.

    `contact_miss` can be right while nothing consults it -- a mutation
    replacing `compose`'s call with `None` survived every test that checked
    the numbers, because they all called the function directly. This drives
    the refusal through `compose` itself, which is where the three wrong turns
    actually got out.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "ESP32-C3")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    turned = tuple(
        dataclasses.replace(c, turn=(c.turn + 90.0) % 360.0)
        if c.package == "USB2.0-TYPE-C" else c
        for c in compose.CORRESPONDENCE)
    with mock.patch.object(compose, "CORRESPONDENCE", turned):
        with pytest.raises(SystemExit, match="from the pads they solder to"):
            compose.compose(spec, deflection=0.05, check=True)


def test_the_margin_is_a_margin():
    """A turn has to WIN, not merely tie.

    Negating `TURN_MARGIN_MM` makes every comparison vacuously true, and that
    mutation survived until this existed. The bound above it is the smallest
    winning margin on any composed board, so a margin larger than that would
    start refusing the right answer.

    **It was 0.94 mm while the receptacle was a published model of a different
    part.** Modelling the one the vendor names widened it to 2.61 -- the
    ESP32-C3, where turn 0 puts the contacts 0.996 mm from their pads and the
    next best turn puts them 3.606 -- because a model built from the same
    footprint as the pads agrees with them the way a substitute cannot.
    """
    assert 0.0 < compose.TURN_MARGIN_MM < 2.61


def test_a_part_with_too_few_pads_has_no_facing_to_check():
    """Two pads cannot say which way round a part is.

    A chip capacitor is the same part rotated, and four pads in a square are
    no better. `contact_miss` answers `None` there rather than a number that
    would be noise -- and a number would be worse than none, because
    `compose` would then refuse a turn on the strength of it.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "ESP32-C3")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    small = next(e for e in board.elements if e.package == "C0201")
    assert len(small.pads) < compose.TURN_FROM_CONTACTS_PADS
    assert compose.contact_miss(small, compose.slab(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 1.0, "#b58136", (0.0, 0.0)),
        (0.0, 0.0)) is None


def test_the_two_usb_c_land_patterns_are_given_different_receptacles():
    """They differ in the count of holes, which is what picks the part.

    Both are 16-pin USB-C, so the PIN count says nothing. `USB2.0-TYPE-C` has
    four through-hole shell tabs and `USB2.0-TYPE-C_USB-31C-F-16P` has two
    board locks. Giving them one entry is what OH-101 was: a four-tab model on
    a two-lock land left the contact row 0.42 mm past the board edge.

    Both are modelled now rather than matched, and the property survives the
    change unaltered -- each land pattern is built from its own footprint, so
    they cannot collapse into one mesh by accident.
    """
    usb = {c.package: c.model for c in compose.CORRESPONDENCE
           if c.package.startswith("USB2.0-TYPE-C")}
    assert len(usb) == 2, usb
    assert len(set(usb.values())) == 2, (
        f"both land patterns share {usb} -- they are two different parts, and "
        f"the one with two board locks is not the one with four shell tabs"
    )


def test_a_composition_that_can_be_fetched_says_which_chip_fetches_it():
    """`fetch_with` prints the command that gets a missing layout.

    For the XIAOs that command is this tool itself, so it is only true if the
    tool actually fetches -- and until `pcb_chip` existed it did not:
    `fetch_pcb` had no caller anywhere in the repository, and the C3's
    instruction was the command that had just printed it. The C3's file
    happened to be on the disk already, unzipped by hand, so nothing noticed.
    """
    for spec in compose.COMPOSITIONS:
        under_cache = spec.layout.parent == compose.PCB_CACHE
        assert (spec.pcb_chip is not None) == under_cache, (
            f"{spec.board}: a layout under {compose.PCB_CACHE.name} is one "
            f"this tool downloads, and one elsewhere is not"
        )
        if spec.pcb_chip is not None:
            assert spec.pcb_chip in compose.PCB_SOURCES, spec.board
            assert spec.layout.name == f"{spec.pcb_chip}.kicad_pcb", (
                f"{spec.board}: fetch_pcb writes <chip>.kicad_pcb, so a "
                f"layout named anything else can never be the file it fetches"
            )


def test_a_missing_layout_is_fetched_rather_than_only_talked_about(monkeypatch,
                                                                   tmp_path):
    """The field is worth nothing unless `compose` calls it.

    `fetch_pcb` sat in this module with **no caller anywhere in the
    repository**: a missing XIAO layout printed "Run: python
    tools/compose_board_3d.py --board XIAO-ESP32-C3-DIP", which is the command
    that had just printed it. Nothing noticed because the C3's file was
    already on the disk, unzipped by hand.

    So the assertion is that the fetch is ATTEMPTED, not that it succeeds --
    no network, and the mutation that removes the call is what this kills.
    """
    asked: list[str] = []
    monkeypatch.setattr(compose, "fetch_pcb", lambda chip: asked.append(chip))
    absent = dataclasses.replace(
        _uno(),
        board="Test board",
        layout=tmp_path / "NOT-FETCHED.kicad_pcb",
        pcb_chip="ESP32-C3",
    )
    assert compose.compose(absent, deflection=0.05, check=True) == 3
    assert asked == ["ESP32-C3"], (
        "compose printed the instruction to fetch and did not fetch"
    )


def test_a_layout_nobody_can_fetch_is_only_talked_about(monkeypatch, tmp_path):
    """The Arduino Uno's board file is an `https-archive` a person has to
    accept terms for, so `pcb_chip` is None and the message is all there is.

    Split from the test above because one test accepting either behaviour
    would pass with the `is not None` guard deleted -- and that guard is what
    stops a missing Uno from raising `KeyError: None` out of `PCB_SOURCES`.
    """
    asked: list[str] = []
    monkeypatch.setattr(compose, "fetch_pcb", lambda chip: asked.append(chip))
    absent = dataclasses.replace(_uno(), layout=tmp_path / "no.brd")
    assert compose.compose(absent, deflection=0.05, check=True) == 3
    assert asked == []


def test_the_uno_names_a_colour_it_actually_read_somewhere():
    """The one thing here that is neither Arduino's nor KiCad's.

    A PCB colour is in no CAD file this repository has. It is read out of
    PICSimLab's own artwork, and the composition says which file and which
    element -- because an unsourced colour beside two sourced geometries is
    exactly the kind of quiet invention that gets believed.
    """
    spec = _uno()
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
    spec = _uno()
    _brd()
    board = compose.read_layout(spec.layout)
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

    every = (*model_from_datasheet.SPECS, *model_from_datasheet.PACKS,
             *model_from_datasheet.SOCKETS)
    assert every, "nothing is modelled, so this is vacuous"
    for spec in every:
        assert spec.why_not_fetched.strip(), spec.name
        assert spec.cited, f"{spec.name} cites nothing, so it invented nothing?"
        for field, (value, why) in spec.cited.items():
            assert isinstance(value, float), f"{spec.name}.{field}"
            assert len(why) > 40, f"{spec.name}.{field} has no real citation"


def test_listing_the_modelled_parts_does_not_die_on_the_ones_that_cite_nothing():
    """`--list` is the first command the handoff tells a reader to run.

    A slab carries no `cited` field at all, because every number it draws is in
    the vendor's file -- and the loop that prints citations went straight at
    the attribute, so the command died with an `AttributeError` on the first
    slab from the moment OH-104 added one. It printed two parts and then a
    traceback for a day.
    """
    from tools import model_from_datasheet

    assert model_from_datasheet.SLABS, "nothing cites nothing, so this is vacuous"
    assert not hasattr(model_from_datasheet.SLABS[0], "cited")
    assert model_from_datasheet.main(["--list"]) == 0


def _rp2350() -> pathlib.Path:
    path = compose.PCB_CACHE / "RP2350.kicad_pcb"
    if not path.is_file():
        pytest.skip(
            f"SKIPPED: {path.name} is not fetched. Run: "
            f"python tools/compose_board_3d.py --board XIAO-RP2350-DIP"
        )
    return path


def test_a_body_drawn_as_lines_is_read_like_one_drawn_as_a_rectangle():
    """`pack_geometry` had its own F.Fab reader and it looked for a rectangle.

    The ESP32-C5 draws its QFN's body as four `fp_line`s, so a part whose
    outline was perfectly present was refused as absent -- "0 rectangles on
    F.Fab". Two readers of one layer meant only one of them learned what
    OH-105 taught about closed outlines and keep-out lines, so this now goes
    through `kicad._body_of` like everything else.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.PACKS
                if s.package.startswith("QFN48"))
    if not spec.pcb.is_file():
        pytest.skip(f"SKIPPED: {spec.pcb.name} is not fetched")
    plan = model_from_datasheet.pack_geometry(spec)
    body = plan["body"]
    assert body["x"][1] - body["x"][0] == pytest.approx(6.0, abs=0.001)
    assert body["y"][1] - body["y"][0] == pytest.approx(6.0, abs=0.001)
    assert len(plan["leads"]) == 48, "a QFN-48 has forty-eight leads"


def test_the_modelled_qfn_is_built_from_the_vendors_own_footprint():
    """Every number in plan is Seeed's, which is why it cannot drift.

    The RP2350 is the only part on any XIAO that is modelled rather than
    matched, and the reason is that **nobody publishes a QFN-60**. What makes
    that safe is that only its HEIGHT is not in the vendor's file.
    """
    from tools import model_from_datasheet

    _rp2350()
    spec = next(s for s in model_from_datasheet.PACKS
                if s.package == "QFN60-0.4-7X7X0.9MM")
    plan = model_from_datasheet.pack_geometry(spec)

    body = plan["body"]
    assert body["x"][1] - body["x"][0] == pytest.approx(7.0, abs=0.001)
    assert body["y"][1] - body["y"][0] == pytest.approx(7.0, abs=0.001)
    assert len(plan["leads"]) == 60, "a QFN-60 has sixty leads"
    assert plan["flag"]["w"] == pytest.approx(3.45, abs=0.001)
    assert plan["flag"]["h"] == pytest.approx(3.45, abs=0.001)
    # Fifteen a side on 0.4 mm pitch, the ring at +-3.4 mm. All Seeed's.
    assert sorted({round(p["x"], 3) for p in plan["leads"]})[0] == -3.4
    assert len({round(p["y"], 3) for p in plan["leads"] if p["x"] == -3.4}) == 15


def test_every_lead_is_brought_into_the_composers_frame():
    """**The lead RING cannot show this and the individual leads can.**

    A QFN's ring is symmetric about y, so negating it or not gives the same
    SET of positions and an identical mesh -- which means no assertion about
    the ring as a whole can tell a mirrored reader from a correct one. Pad by
    pad it is plain: the vendor's pad 16 sits at y +3.400 in a file that
    measures y downward, and belongs at -3.400 in a frame that measures it up.
    """
    from tools import model_from_datasheet

    path = _rp2350()
    spec = next(s for s in model_from_datasheet.PACKS
                if s.package == "QFN60-0.4-7X7X0.9MM")
    plan = model_from_datasheet.pack_geometry(spec)

    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    node = next(n for n in kicad.children(tree, "footprint")
                if str(n[1]).endswith("QFN60-0.4-7X7X0.9MM"))
    vendor = [p for p in kicad._pads_of(node)
              if p.width_mm * p.height_mm < 1.0]
    assert len(vendor) == len(plan["leads"]), "read in the vendor's own order"
    off = [(v.number, v.y_mm, got["y"])
           for v, got in zip(vendor, plan["leads"])
           if round(got["y"], 4) != round(-v.y_mm, 4)]
    assert not off, (
        f"{len(off)} lead(s) keep the file's own y instead of the composer's, "
        f"first {off[:2]} -- a mirrored part, which draws perfectly"
    )


def test_the_modelled_qfns_height_is_the_one_the_vendor_named():
    """The only number here that is not geometry, tied to where it came from.

    A QFN is a moulded slab whose height is the one dimension a land pattern
    cannot express, so Seeed state it in the footprint NAME --
    `QFN60-0.4-7X7X0.9MM` -- or nowhere. Reading it out of that name is what
    keeps `cited` from drifting into a number somebody liked the look of.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.PACKS
                if s.package == "QFN60-0.4-7X7X0.9MM")
    named = spec.package.rsplit("X", 1)[-1].removesuffix("MM")
    assert spec.cited["height"][0] == pytest.approx(float(named), abs=0.0001), (
        f"the vendor's footprint is named {spec.package}, whose last field is "
        f"{named} mm, and this draws it {spec.cited['height'][0]} mm tall"
    )


def test_the_qfn_body_is_the_fab_outline_and_not_the_courtyard():
    """They differ by 0.01 mm on this part, so the wrong one is invisible.

    `F.Fab` is KiCad's own convention for where the plastic actually is;
    `F.CrtYd` is the keep-out around it and is what a placement tool avoids.
    Here they are 7.000 x 7.000 and 7.000 x 7.000 -- the courtyard is offset
    rather than larger -- so nothing about the SIZE would give away a reader
    that took the wrong rectangle, and the body would sit 0.01 mm off centre
    for ever.
    """
    from tools import model_from_datasheet

    path = _rp2350()
    spec = next(s for s in model_from_datasheet.PACKS
                if s.package == "QFN60-0.4-7X7X0.9MM")
    plan = model_from_datasheet.pack_geometry(spec)

    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    node = next(n for n in kicad.children(tree, "footprint")
                if str(n[1]).endswith("QFN60-0.4-7X7X0.9MM"))
    on = {}
    for rect in kicad.children(node, "fp_rect"):
        layer = kicad.first(rect, "layer")
        on[layer[1]] = (kicad._floats(kicad.first(rect, "start"))
                        + kicad._floats(kicad.first(rect, "end")))
    assert {"F.Fab", "F.CrtYd"} <= set(on), on
    # **They differ in y ONLY** -- -3.51..3.49 against -3.50..3.50, the same
    # 7.000 mm span shifted by a hundredth. So an assertion about x, or about
    # either span, passes on both, and this has to compare the corner it
    # actually took. The first version of this test asserted x and let the
    # mutation through.
    assert on["F.Fab"][1::2] != on["F.CrtYd"][1::2], (
        "this test is only meaningful while the two rectangles differ in y"
    )
    assert plan["body"]["x"] == sorted([on["F.Fab"][0], on["F.Fab"][2]])
    assert plan["body"]["y"] == sorted([-on["F.Fab"][1], -on["F.Fab"][3]])


def test_the_modelled_qfn_is_not_mirrored():
    """The one feature on a QFN that says which way round it is.

    KiCad measures y DOWN the page and the composer works in a frame whose y
    runs up, so a model built in the file's own frame is mirrored against the
    placement that positions it. **The body is four-fold symmetric, so that
    draws perfectly** -- and moves the pin-1 dot to the opposite corner.

    Checked against pad 1 rather than against a remembered sign. **Not by
    which lead is nearest**: a corner dot sits between the last lead of one
    side and the first of the next, and here it is 0.438 mm from lead 1 and
    0.434 mm from lead 60 -- four microns apart, so "nearest" is noise and a
    test built on it would pass or fail on rounding. What mirroring actually
    changes is the SIGN of y, so the quadrant is what to assert.
    """
    from tools import model_from_datasheet

    path = _rp2350()
    spec = next(s for s in model_from_datasheet.PACKS
                if s.package == "QFN60-0.4-7X7X0.9MM")
    mark = model_from_datasheet.pack_geometry(spec)["mark"]
    assert mark is not None, "the vendor draws a pin-1 circle on F.Fab"

    tree = kicad.parse_sexp(path.read_text(encoding="utf-8", errors="replace"))
    node = next(n for n in kicad.children(tree, "footprint")
                if str(n[1]).endswith("QFN60-0.4-7X7X0.9MM"))
    pads = {p.number: p for p in kicad._pads_of(node)}
    one = pads["1"]
    corner = (math.copysign(1, one.x_mm), math.copysign(1, -one.y_mm))
    assert (math.copysign(1, mark["x"]), math.copysign(1, mark["y"])) == corner, (
        f"the pin-1 mark is at ({mark['x']:.3f}, {mark['y']:.3f}) and pad 1 is "
        f"at ({one.x_mm:.3f}, {-one.y_mm:.3f}) -- different corners, so the "
        f"model is mirrored. It draws a correct-looking part with the one "
        f"feature that says which way round it is diagonally misplaced."
    )
    # And it really is a CORNER mark: the two leads that meet there are the
    # ends of the numbering, which is what a pin-1 dot points between.
    nearest = sorted(
        (math.dist((mark["x"], mark["y"]), (pad.x_mm, -pad.y_mm)), number)
        for number, pad in pads.items() if number != "61")[:2]
    assert {n for _d, n in nearest} == {"1", "60"}, nearest


def test_the_rp2350_is_drawn_and_the_near_miss_is_still_refused():
    """A QFN-56 is right in body and pitch and wrong in lead count.

    It would draw a handsome part in the right place and put
    `U4 (QFN-56-1EP_7x7mm_P0.4mm...)` in this model's own list of what is on
    the board, which is a false statement rather than an approximation. That
    is the whole reason the part is modelled instead.
    """
    qfn = [c for c in compose.CORRESPONDENCE
           if c.package == "QFN60-0.4-7X7X0.9MM"]
    assert qfn, "the RP2350's own chip is not in the correspondence"
    assert qfn[0].modelled is True
    assert qfn[0].turn == 0.0, (
        "a modelled part is built in the vendor package's own frame"
    )
    assert "QFN60-0.4-7X7X0.9MM" not in compose.ABSENT, (
        "it is drawn now; ABSENT should no longer claim otherwise"
    )
    for component in compose.CORRESPONDENCE:
        assert "QFN-56" not in component.model, (
            f"{component.package} was given {component.model}. A 56-lead part "
            f"is not a 60-lead part, however well it measures."
        )


# --- the receptacle the vendor names and does not ship (OH-102) ---------------


def test_the_modelled_receptacle_is_the_length_the_vendor_states():
    """The whole of OH-102, in one number per land pattern.

    Both published 16-pin receptacles are longer than the part Seeed fitted --
    the GCT by 0.43 mm and Amphenol's by 3.15 -- and there is no third in
    KiCad's `Connector_USB` to try. What settles it is that the vendor states
    the envelope twice in their own file: in the footprint's `Description`
    property, and as the `F.Fab` rectangle they drew.
    """
    from tools import model_from_datasheet

    assert model_from_datasheet.SOCKETS, "no receptacle is modelled"
    for spec in model_from_datasheet.SOCKETS:
        if not spec.pcb.is_file():
            continue
        plan = model_from_datasheet.socket_geometry(spec)
        length, width, height = plan["stated"]
        assert sorted((length, width)) == pytest.approx([7.3, 8.9], abs=0.06), (
            f"{spec.package}: its Description states {length} x {width} mm, "
            f"and a 16-pin USB-C receptacle is about 7.35 x 8.94"
        )
        assert 3.0 < height < 3.5, (
            f"{spec.package}: {height} mm tall. Both published models measure "
            f"3.28 and 3.31 mm over the shell, so this is the same part."
        )
        assert plan["apart"] <= model_from_datasheet.NAMED_BODY_TOLERANCE_MM


def test_the_receptacles_contacts_are_named_by_the_standard():
    """Sixteen contacts on twelve pads, and the pad names say which four join.

    **This is how a contact is told from a shell tab**, and it is the vendor
    writing the specification's own vocabulary rather than a rule invented
    here: `A1_B12`, `A4_B9`, `B4_A9` and `B1_A12` are the four pairs a USB 2.0
    receptacle joins inside itself, which is why a 16-pin part arrives on
    twelve pads. Reading them by position instead would need a threshold.
    """
    from tools import model_from_datasheet

    for spec in model_from_datasheet.SOCKETS:
        if not spec.pcb.is_file():
            continue
        plan = model_from_datasheet.socket_geometry(spec)
        assert len(plan["designations"]) == model_from_datasheet.SPEC_CONTACTS
        assert len(plan["contacts"]) == 12, (
            f"{spec.package}: {len(plan['contacts'])} contact pads, and a "
            f"USB 2.0 Type-C receptacle lands its sixteen contacts on twelve"
        )
        assert plan["posts"], "a receptacle with no hole has nothing to anchor on"


def test_a_footprint_that_draws_no_body_is_refused_rather_than_guessed():
    """The ESP32-C3's own receptacle, which is why the C6 is read instead.

    Its footprint carries no `F.Fab` outline and no `Description` either, so
    nothing in that file says how large or how tall the part is. Two boards
    share this package and only one of them drew it; naming the wrong one
    would have to invent a body, which is what
    `tools/model_from_datasheet.py` exists not to do.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SOCKETS
                if s.package == "USB2.0-TYPE-C")
    c3 = compose.PCB_CACHE / "ESP32-C3.kicad_pcb"
    if not c3.is_file():
        pytest.skip("SKIPPED: ESP32-C3.kicad_pcb is not fetched")
    with pytest.raises(SystemExit, match=r"draws no \*\.Fab outline"):
        model_from_datasheet.socket_geometry(dataclasses.replace(spec, pcb=c3))


def test_a_package_whose_description_states_no_envelope_is_refused():
    """The height is the one dimension no layer of a land pattern carries.

    Most of Seeed's own descriptions state two numbers rather than three --
    `SMD IC Memory;16Mbit-SPI-USON-8-2*3mm` is a plan and no height -- so the
    receptacles' three are a property of those footprints and not of the
    field. A part whose description reads like that gets no height from it,
    and a slab of invented thickness is the defect this whole file exists to
    refuse.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SOCKETS
                if s.package == "USB2.0-TYPE-C_USB-31C-F-16P")
    if not spec.pcb.is_file():
        pytest.skip(f"SKIPPED: {spec.pcb.name} is not fetched")
    with pytest.raises(SystemExit, match="states no length"):
        model_from_datasheet.socket_geometry(
            dataclasses.replace(spec, package="DFN6-0.5-1.45X1X0.6"))


def test_a_description_that_disagrees_with_the_outline_is_refused():
    """The comparison is what proves the string was read, and it must refuse.

    Both real footprints agree to 0.020 and 0.092 mm, so the check never fires
    on anything shipped -- and a mutation deleting it survived the whole suite
    until this existed. A Description claiming twice the length its `F.Fab`
    rectangle draws is the shape of a misread string, and it must not draw
    either the plan it states or the height beside it.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SOCKETS
                if s.package == "USB2.0-TYPE-C_USB-31C-F-16P")
    if not spec.pcb.is_file():
        pytest.skip(f"SKIPPED: {spec.pcb.name} is not fetched")
    board = spec.pcb.read_text(encoding="utf-8", errors="replace")
    assert board.count("7.35*8.94*3.25mm") == 1, "the envelope is not unique"
    scratch = spec.pcb.with_name("USB-lying.kicad_pcb")
    scratch.write_text(board.replace("7.35*8.94*3.25mm", "14.7*8.94*3.25mm"),
                       encoding="utf-8")
    try:
        with pytest.raises(SystemExit, match="mm apart"):
            model_from_datasheet.socket_geometry(
                dataclasses.replace(spec, pcb=scratch))
    finally:
        scratch.unlink()


def test_the_receptacle_faces_the_way_its_own_tails_say():
    """Which end the plug goes into is READ, not judged.

    A receptacle's contacts leave at its back and solder to pads, so the end
    the tails are at is the back and the mouth is the other one. OH-105 got
    this backwards by measuring triangle area in each end plane -- reasoning
    that a mouth is a rim and a back is a filled face, and measuring the thin
    solder tails crossing the plane instead -- and faced the socket into the
    board on four boards.

    Stated as a distance rather than a direction, so it holds for a footprint
    drawn either way round: every tail is FURTHER from the mouth than the back
    of the shell is.
    """
    from tools import model_from_datasheet

    for spec in model_from_datasheet.SOCKETS:
        if not spec.pcb.is_file():
            continue
        plan = model_from_datasheet.socket_geometry(spec)
        front, back = plan["front_face"], plan["back_face"]
        assert front in plan["body"]["x"], "the mouth is a face of the body"
        assert back in plan["body"]["x"], "and so is the back"
        assert front != back
        nearest = min(min(abs(edge - front) for edge in tail["x"])
                      for tail in plan["contacts"])
        assert nearest >= abs(back - front) - 1e-9, (
            f"{spec.package}: a tail comes within {nearest:.3f} mm of the "
            f"mouth, which is {abs(back - front):.3f} mm from the back face "
            f"they were clipped to. The socket is facing into the board."
        )


def test_the_modelled_receptacles_are_drawn_and_marked_as_modelled():
    """Two land patterns, two meshes, both built here rather than fetched."""
    usb = [c for c in compose.CORRESPONDENCE
           if c.package.startswith("USB2.0-TYPE-C")]
    assert len(usb) == 2, usb
    for component in usb:
        assert component.modelled is True, component.package
        assert component.library == "modelled", component.package
        assert component.turn == 0.0, (
            "a modelled part is built in the vendor footprint's own frame, so "
            "it needs no turn -- and this one was given 0, then 90, then 270 "
            "while it was a published model of a different part"
        )


def test_an_exposed_pad_that_is_not_alone_is_refused():
    """The flag is told apart from a lead by AREA, not by pad number.

    3.45 mm square against 0.6 x 0.18 is a factor of a hundred, so the split
    is wide -- but a part with two large pads is a different animal and this
    would silently pick whichever came first in the file.
    """
    from tools import model_from_datasheet

    path = _rp2350()
    body = path.read_text(encoding="utf-8", errors="replace")
    # Turn one lead into a second flag by growing it, in a copy.
    broken = body.replace('(size 0.6 0.18)', '(size 3.45 3.45)', 1)
    assert broken != body, "the substitution did not take"
    scratch = path.with_name("QFN-two-flags.kicad_pcb")
    scratch.write_text(broken, encoding="utf-8")
    try:
        spec = dataclasses.replace(
            next(s for s in model_from_datasheet.PACKS
                 if s.package == "QFN60-0.4-7X7X0.9MM"),
            pcb=scratch)
        with pytest.raises(SystemExit, match="exactly one exposed pad"):
            model_from_datasheet.pack_geometry(spec)
    finally:
        scratch.unlink()


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
    spec = _uno()
    _brd()
    board = compose.read_layout(spec.layout)
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


# --- which way a part faces (OH-77) ------------------------------------------------


def test_the_silkscreen_is_read_off_the_package():
    """The body outline, which is a different fact from the pads.

    `eagle.Element.pad_extent` says where the pins are; this says where the
    part is. Nothing before OH-77 read it, and that is why a barrel jack could
    point the wrong way and measure perfectly.
    """
    board = eagle.read_board(_brd())
    jack = board.element("X1")
    assert jack.silk is not None
    x0, y0, x1, y1 = jack.silk
    assert (x0, y0, x1, y1) == pytest.approx((-5.08, -6.35, 3.9116, 7.1374),
                                             abs=0.001)
    # The USB socket's body runs a long way to one side of its pins, which is
    # exactly the asymmetry that makes this worth reading.
    usb = board.element("X2")
    assert usb.silk == pytest.approx((-5.9, -10.15, 5.9, 5.6), abs=0.001)


def test_every_component_lands_where_the_vendor_drew_its_body():
    """The check the user asked for, against the file the parts came from.

    Fourteen of fifteen already agreed to 0.40 mm. The fifteenth, the barrel
    jack, was 7.50 mm out with its barrel pointing into the board -- and no
    measurement taken from the pads could see it, because a pin field is
    symmetric about its own centre whichever way the body faces.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = _uno()
    _brd()
    board = compose.read_layout(spec.layout)
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)

    by_package = {c.package: c for c in compose.CORRESPONDENCE}
    cache: dict[str, tuple[object, object]] = {}
    worst, worst_name, checked = 0.0, "", 0
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
        miss = compose.silk_miss(element, put, centre)
        if miss is None:
            continue
        checked += 1
        if miss > worst:
            worst, worst_name = miss, element.name

    assert checked == 15, f"only {checked} components were checked against silk"
    assert worst < compose.SILK_TOLERANCE_MM, (
        f"{worst_name} lands {worst:.2f} mm from the body the vendor drew"
    )


def test_the_barrel_jack_faces_out_over_the_board_edge():
    """The specific wrong picture, pinned so it cannot come back.

    A DC jack is mounted at the edge so a plug can reach it. Turned 180
    degrees it sits inside the board, which looks tidy and is not an Arduino.
    """
    jack = [c for c in compose.CORRESPONDENCE
            if c.package == "POWERSUPPLY_DC-21MM"]
    assert jack, "the barrel jack is not in the correspondence"
    assert jack[0].turn == 270.0, (
        "270 is the only turn within 5 mm of the vendor's silkscreen; the "
        "other three miss by 5.36, 7.50 and 5.35"
    )


def test_a_component_turned_the_wrong_way_is_refused_by_the_silk_check():
    """The check has to fail on the thing it was written for.

    Built rather than fetched: a 20 x 4 mm body sitting on pins at the origin,
    offset so that turning it moves it. Needs no OpenCASCADE and no network.
    """
    element = eagle.Element(
        "X1", "lib", "JACK",
        pads=(eagle.Pad("1", "thru_hole", 0.0, 0.0, 1.0, 1.0, None),
              eagle.Pad("2", "thru_hole", 2.0, 0.0, 1.0, 1.0, None)),
        x_mm=10.0, y_mm=10.0, rotation=0.0, mirrored=False,
        # The body is all to one side of the pins, like a barrel.
        silk=(-1.0, -1.0, 11.0, 1.0),
    )
    def slab_at(x0, x1):
        """A body spanning `x0..x1` and board y 9..11, in the SCENE's frame.

        Scene positions are `(x, height, -y)` -- the same flip `place` applies
        -- so a fixture that puts board y straight into z measures 10.5 mm out
        and looks like a broken check rather than a broken fixture. It did.
        """
        positions = []
        for x in (x0, x1):
            for board_y in (9.0, 11.0):
                positions.extend((x, 0.5, -board_y))
        return compose.Mesh({"#888888": (positions, [0.0] * len(positions),
                                         [0, 1, 2, 1, 2, 3])})

    centre = (0.0, 0.0)
    facing = slab_at(9.0, 21.0)      # centred at x=15, where the silk is
    reversed_ = slab_at(-1.0, 11.0)  # centred at x=5, a 10 mm flip

    assert compose.silk_miss(element, facing, centre) == pytest.approx(0.0,
                                                                      abs=0.01)
    wrong = compose.silk_miss(element, reversed_, centre)
    assert wrong > compose.SILK_TOLERANCE_MM, wrong


def test_a_package_with_no_silkscreen_is_not_checked_rather_than_failed():
    """Absent evidence is not evidence of a wrong placement.

    Every package on this board draws a body, so this path is not exercised by
    the Uno -- which is exactly why it is worth pinning before the next board.
    """
    element = eagle.Element(
        "R1", "lib", "0603",
        pads=(eagle.Pad("1", "smd", 0.0, 0.0, 1.0, 1.0, None),),
        x_mm=0.0, y_mm=0.0, rotation=0.0, mirrored=False, silk=None,
    )
    mesh = compose.Mesh({"#888888": ([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0])})
    assert compose.silk_miss(element, mesh, (0.0, 0.0)) is None


def test_compose_refuses_a_board_whose_part_faces_the_wrong_way(monkeypatch):
    """The guard, not just the measurement.

    `silk_miss` returning a large number is worthless if nothing acts on it,
    and a mutation removing the `raise` from `compose` survived every other
    test here: they all call `silk_miss` themselves and assert on what it
    returns. This drives the real thing, with the barrel jack put back to the
    turn it had when it pointed into the board.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    _brd()
    wrong = tuple(
        dataclasses.replace(component, turn=90.0)
        if component.package == "POWERSUPPLY_DC-21MM" else component
        for component in compose.CORRESPONDENCE
    )
    monkeypatch.setattr(compose, "CORRESPONDENCE", wrong)
    with pytest.raises(SystemExit, match="X1"):
        compose.compose(_uno(), compose.DEFLECTION, check=True)


# --- what a wire may not pass through (OH-78) --------------------------------------


def test_the_model_states_a_box_around_every_component_it_draws():
    """A wire's physics knows about boxes, not about meshes.

    `webui/static/board3d.js` collides a rope against the PCB slab and the
    parts on the bench. The fifteen components OH-75 and OH-76 put ON the board
    were geometry in the mesh and nothing else, so a wire went straight through
    the DIP-28 and all six headers -- invisible until there were components to
    pass through, and not a line of the collider code was wrong.

    Measured rather than asserted by eye: a fresh wire laid straight from pad
    12 to an LED sits 2.248 mm inside the DIP-28, and 0.000 mm once it settles.
    """
    glb = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not glb.is_file():
        pytest.skip("SKIPPED: run python tools/compose_board_3d.py first")
    from tools.import_3d_model import read_extras

    extras = read_extras(glb)
    solids = extras["solids"]
    drawn = extras["drawn"]
    assert len(solids) == len(drawn), (
        f"{len(drawn)} components drawn and {len(solids)} boxes emitted"
    )
    named = {solid["name"] for solid in solids}
    assert {"ZU4", "IOH", "IOL", "POWER", "AD", "X1", "X2"} <= named, named

    for solid in solids:
        low, high = solid["min"], solid["max"]
        assert all(a < b for a, b in zip(low, high)), solid
        # Nothing on this board is a metre across or a micron thick.
        for axis in range(3):
            span = high[axis] - low[axis]
            assert 0.05 < span < 80.0, f"{solid['name']} spans {span} on {axis}"


def test_each_component_box_actually_contains_its_component():
    """A box that does not enclose the mesh it names would stop nothing.

    The boxes are emitted from the same placed vertices everything else here
    measures, so this is a check that the right mesh was measured -- not a
    check of arithmetic.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = _uno()
    _brd()
    board = compose.read_layout(spec.layout)
    header_pads = [pad for name in spec.headers
                   for pad in board.element(name).pads]
    hx = [pad.x_mm for pad in header_pads]
    hy = [pad.y_mm for pad in header_pads]
    centre = ((min(hx) + max(hx)) / 2, (min(hy) + max(hy)) / 2)

    by_package = {c.package: c for c in compose.CORRESPONDENCE}
    cache: dict[str, tuple[object, object]] = {}
    checked = 0
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
        solid = compose.box_around(element.name, put)
        for _colour, (positions, _n, _i) in put.groups.items():
            for at in range(0, len(positions), 3):
                for axis in range(3):
                    value = positions[at + axis]
                    assert solid["min"][axis] - 1e-3 <= value, element.name
                    assert value <= solid["max"][axis] + 1e-3, element.name
        checked += 1
    assert checked == 15, f"only {checked} components were boxed"


# --- a KiCad board, presented as the one this already composes ----------------
#
# OH-93. Six of the eight unmodelled chips publish a vendor KiCad PCB and no
# mesh, so `from_kicad` presents one as the `eagle.Board` `compose` already
# consumes -- an adapter rather than a mode, so nothing below the reader knows
# which vendor's CAD it came from.

#: A board with one part at a known place, an outline, and a rotation. Written
#: out per test rather than shared with `tests/rules/test_kicad.py`: that file
#: pins the PARSER and this one pins the ADAPTER, and a fixture serving both
#: would make a change to either a change to the other.
KICAD_BOARD = """(kicad_pcb
\t(version 20241229)
\t(gr_line
\t\t(start 10 20)
\t\t(end 30 20)
\t\t(stroke (width 0.05) (type solid))
\t\t(layer "Edge.Cuts")
\t)
\t(gr_rect
\t\t(start 10 20)
\t\t(end 32 37)
\t\t(stroke (width 0.05) (type solid))
\t\t(layer "Edge.Cuts")
\t)
\t(footprint "XIAO TEST:QFN32G-0.5-5X5MM"
\t\t(layer "F.Cu")
\t\t(at 20.5 28.25 -90)
\t\t(property "Reference" "U4"
\t\t\t(at -1.5 1.9 0)
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(pad "1" smd roundrect
\t\t\t(at -2.5 -1.75 90)
\t\t\t(size 0.8 0.28)
\t\t\t(layers "F.Cu")
\t\t)
\t\t(pad "33" smd rect
\t\t\t(at 0 0)
\t\t\t(size 3.7 3.7)
\t\t\t(layers "F.Cu")
\t\t)
\t)
)
"""


def _kicad_board_file():
    """The fixture above, on disk, because the reader takes a path."""
    import tempfile

    path = pathlib.Path(tempfile.mkdtemp()) / "TEST.kicad_pcb"
    path.write_text(KICAD_BOARD, encoding="utf-8")
    return path


def test_an_arc_is_flattened_onto_its_own_circle():
    """**KiCad stores three points on the curve, not a centre.**

    A quarter circle of radius 5 about (10, 10): every point produced must lie
    on it, and the ends must be the ends. This is the assertion that would
    have caught the sign error described below in one line.
    """
    arc = kicad.Arc("Edge.Cuts", 15.0, 10.0, 13.5355, 13.5355, 10.0, 15.0)
    points = compose.arc_points(arc, chord=0.2)

    assert points[0] == pytest.approx((15.0, 10.0))
    assert points[-1] == pytest.approx((10.0, 15.0))
    for x, y in points:
        assert math.hypot(x - 10.0, y - 10.0) == pytest.approx(5.0, abs=1e-3)
    # A quarter of a 5 mm circle is 7.85 mm of arc; at 0.2 mm of chord that is
    # forty segments, so this is "enough points to be smooth" and not a
    # transcription of the implementation.
    assert 30 < len(points) < 60


def test_the_real_boards_outline_is_the_size_two_vendor_files_agree_on():
    """**The end-to-end check on the adapter, against a second source.**

    Seeed's KiCad PCB and Seeed's XIAO footprint are two files neither made
    from the other. `Edge.Cuts` here and `F.Fab` there are two measurements of
    one rectangle: 20.955 x 17.780 against 20.975 x 17.800, 0.020 mm apart.

    This also pins the shape, not just its size. The C3's outline is not one
    ring -- it is the silhouette plus two 1.270 x 0.508 mm slots -- and the
    silhouette must come back smaller than its own bounding box, because a
    rounded rectangle does. The sign error described in `arc_points` produced
    a "silhouette" of 67,569 segments spanning 746 mm, which is what this
    would have caught in one line.
    """
    pcb = REPO / "third_party" / "seeed-pcb" / "ESP32-C3.kicad_pcb"
    if not pcb.is_file():
        pytest.skip(f"{pcb} absent; see docs/research/board-models/README.md")

    board = compose.from_kicad(pcb)
    left, bottom, right, top = board.extent_mm()
    assert (right - left) == pytest.approx(20.955, abs=0.01)
    assert (top - bottom) == pytest.approx(17.780, abs=0.01)

    ring, cuts = compose.outer(board.outline)
    assert len(cuts) == 2, "the C3 has two routed slots inside its edge"
    area = abs(compose._area(ring)) / 2  # `_area` is TWICE the signed area
    box = (right - left) * (top - bottom)
    assert 0.97 * box < area < box, (
        f"the silhouette is {area:.2f} mm^2 against a {box:.2f} mm^2 box; a "
        f"rounded rectangle is a little under its box and nothing else is"
    )


def test_an_arc_goes_the_way_its_middle_point_says():
    """A rounded corner taken the other way round is a three-quarter circle
    bitten out of the board, and it still draws."""
    short = compose.arc_points(
        kicad.Arc("Edge.Cuts", 15.0, 10.0, 13.5355, 13.5355, 10.0, 15.0))
    # Same ends, middle on the far side: the long way round the same circle.
    long = compose.arc_points(
        kicad.Arc("Edge.Cuts", 15.0, 10.0, 6.4645, 6.4645, 10.0, 15.0))
    assert len(long) > 2 * len(short), (
        "the reflex arc is not being taken the long way round"
    )


def test_three_collinear_points_are_a_straight_line_and_not_an_error():
    """A zero-bulge arc is legal in an outline; refusing it refuses the board."""
    assert compose.arc_points(
        kicad.Arc("Edge.Cuts", 0.0, 0.0, 1.0, 0.0, 2.0, 0.0)
    ) == [(0.0, 0.0), (2.0, 0.0)]


def _square(x, y, side, layer="Dimension"):
    corners = [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]
    return [eagle.Segment(layer, *corners[i], *corners[(i + 1) % 4])
            for i in range(4)]


def test_an_outline_with_a_cutout_chains_into_two_rings():
    """**More than one ring is normal, and was not until OH-93.**

    The Uno draws a single silhouette. The XIAO ESP32-C3 draws its edge and
    two 0.76 x 0.51 mm slots inside it, which `loop` reported as "the outline
    does not chain: 74 segment(s) left" -- a correct parse of a shape it could
    not hold, reading exactly like a parse failure.
    """
    segments = tuple(_square(0, 0, 10) + _square(3, 3, 1))
    rings = compose.contours(segments)
    assert len(rings) == 2
    assert sorted(len(r) for r in rings) == [4, 4]


def test_the_silhouette_is_the_largest_ring_and_the_rest_are_returned():
    """The cutouts come back rather than being dropped, so a caller can say
    what it is not drawing. Extruding the outer ring alone fills the slots in;
    saying nothing about them is the part that would be wrong."""
    ring, cuts = compose.outer(tuple(_square(0, 0, 10) + _square(3, 3, 1)))
    assert abs(compose._area(ring)) == pytest.approx(200.0)  # twice 10 x 10
    assert len(cuts) == 1
    assert abs(compose._area(cuts[0])) == pytest.approx(2.0)


def test_loop_still_refuses_a_shape_it_cannot_hold():
    """`loop` is kept strict so a single-silhouette board cannot quietly
    become several; `outer` is what a caller uses when cutouts are expected."""
    with pytest.raises(ValueError, match="2 closed rings"):
        compose.loop(tuple(_square(0, 0, 10) + _square(3, 3, 1)))


def test_kicad_measures_down_the_page_and_the_composer_measures_up():
    """**The one thing in the adapter that is not bookkeeping.**

    Getting this wrong mirrors the whole board: right outline, right parts,
    right sizes, and pin 1 in the opposite corner. It draws perfectly.
    """
    board = _kicad_board_file()
    got = compose.from_kicad(board)
    placed = {e.name: e for e in got.elements}
    # The fixture puts U4 at y = 28.25 in KiCad's frame.
    assert placed["U4"].y_mm == pytest.approx(-28.25)
    assert placed["U4"].x_mm == pytest.approx(20.5)
    # And every outline point is negated with it, so the two still agree.
    assert max(s.y1_mm for s in got.outline) == pytest.approx(-20.0)


def test_a_placements_pads_arrive_in_board_space():
    """`confirm` measures a candidate mesh against these, so a pad still in
    the footprint's own frame would compare a part against the origin."""
    got = compose.from_kicad(_kicad_board_file())
    u4 = {e.name: e for e in got.elements}["U4"]
    # Pad 33 sits at the footprint's own origin, so it lands on the placement.
    centre = [p for p in u4.pads if p.number == "33"][0]
    assert (centre.x_mm, centre.y_mm) == pytest.approx((20.5, -28.25))


def test_a_pad_off_the_footprints_origin_is_flipped_and_then_rotated():
    """**Pad 33 cannot catch either mistake and pad 1 catches both.**

    A pad at the footprint's own origin is invariant under a Y-flip AND under
    a rotation, so asserting on it tests the translation and nothing else --
    which let two mutations through: dropping the rotation, and leaving a
    pad's local Y measuring down the page.

    Worked by hand, for U4 at (20.5, 28.25) turned -90 degrees:

        pad 1 is at (-2.5, -1.75) in the footprint, KiCad's Y down
        into the composer's Y-up frame:   (-2.5, +1.75)
        turned -90 (cos 0, sin -1):       x = -2.5*0 - 1.75*-1 = +1.75
                                          y = -2.5*-1 + 1.75*0 = +2.50
        placed at (20.5, -28.25):         (22.25, -25.75)
    """
    got = compose.from_kicad(_kicad_board_file())
    u4 = {e.name: e for e in got.elements}["U4"]
    assert u4.rotation == -90.0
    first = [p for p in u4.pads if p.number == "1"][0]
    assert (first.x_mm, first.y_mm) == pytest.approx((22.25, -25.75))


def test_the_two_lists_of_composed_boards_agree():
    """**`COMPOSED` in the importer is a copy and this is what stops it
    drifting.**

    `tools/compose_board_3d.py` owns the real list -- a `Composition` per
    board, with its layout file, its headers and the boards it serves -- and
    passes it to `write_index`. The importer keeps a copy for
    `import_3d_model.py --all`, which writes the index without the composer
    having run. Two lists of the same fact is how this repository has been
    bitten twice; the answer here is one test rather than one list, because
    the importer cannot import the composer without a cycle.
    """
    from tools.import_3d_model import COMPOSED
    from webui.boards.catalogue import chip_for

    expected = {
        (name, chip_for(spec.board), compose._slug(spec.board))
        for spec in compose.COMPOSITIONS
        for name in (spec.board, *spec.serves)
    }
    assert set(COMPOSED) == expected, (
        "the importer's copy of the composed-board list disagrees with the "
        "composer's own; whichever is wrong, the index will name the wrong "
        "file for a board"
    )


def test_every_composed_board_says_how_to_fetch_its_layout():
    """A layout that is not fetched prints the command that gets it. Two
    vendors are fetched two different ways -- Arduino's `.brd` by hand through
    `get_board_sources.py`, Seeed's `.kicad_pcb` by this tool itself -- so a
    single hard-coded sentence would send half of them to the wrong place."""
    for spec in compose.COMPOSITIONS:
        assert spec.fetch_with, spec.board
        assert spec.geometry and len(spec.geometry) > 40, spec.board
        assert spec.layout.suffix in (".brd", ".kicad_pcb"), spec.layout


# --- the copper and the ink the vendor drew (OH-110) ---------------------------


def test_a_pad_is_drawn_at_the_angle_its_own_footprint_gives_it():
    """A chip land's two pads face each other, and that is what rotation is for.

    **The invariant is the part's, not this code's**: on every two-terminal
    chip land ever made, each pad's long axis is square to the line joining
    the two. So a pad drawn without its own rotation -- or with somebody
    else's -- fails this on any component that is not axis-aligned, and the
    RP2350 places 224 of its 316 pads at an angle.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    turned = [e for e in board.elements
              if e.package == "C0201" and len(e.pads) == 2
              and round(e.pads[0].rotation_deg) % 180 != 0]
    assert turned, "no 0201 on this board is placed at an angle, so this is vacuous"

    element = turned[0]
    one, two = element.pads
    joining = math.atan2(two.y_mm - one.y_mm, two.x_mm - one.x_mm)
    ring = compose.pad_outline(one)
    assert ring is not None and len(ring) == 4
    # The long axis of the drawn quad, taken from its own longest edge.
    edges = [(ring[i], ring[(i + 1) % 4]) for i in range(4)]
    long_edge = max(edges, key=lambda e: math.dist(e[0], e[1]))
    across = math.atan2(long_edge[1][1] - long_edge[0][1],
                        long_edge[1][0] - long_edge[0][0])
    apart = math.degrees(joining - across) % 180.0
    assert abs(apart - 90.0) < 1.0, (
        f"{element.name}'s pads are joined along {math.degrees(joining):.1f} "
        f"degrees and its pad is drawn along {math.degrees(across):.1f}, which "
        f"is {apart:.1f} apart. A chip land's pads face each other."
    )


def test_a_pad_shape_nothing_can_draw_is_counted_rather_than_guessed():
    """`custom` is a list of primitives, not a size, and there are 60 of them.

    Each is the surface tab beside a castellated half-hole whose drilled
    barrel is drawn anyway, so nothing is lost by leaving them -- and a
    rectangle of their bounding size would be a shape the vendor did not draw.
    The count travels to the caption, which is the difference between leaving
    something out and hiding it.
    """
    custom = eagle.Pad("1", "smd", 0.0, 0.0, 1.6, 1.3, None, shape="custom")
    assert compose.pad_outline(custom) is None
    plain = dataclasses.replace(custom, shape="roundrect")
    assert len(compose.pad_outline(plain)) == 4
    round_pad = dataclasses.replace(custom, shape="circle")
    assert len(compose.pad_outline(round_pad)) == compose.ROUND_PAD_SIDES


def test_a_xiao_outline_is_convex_and_the_unos_is_not():
    """Which decides whether copper can be cut to the board edge exactly.

    Clipping a pad against a convex region is one half-plane per edge and is
    exact. Against a concave one the same procedure removes area that is
    inside the board, so a shape crossing a concave outline is dropped and
    counted instead of being drawn wrongly.
    """
    xiao = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    uno = next(s for s in compose.COMPOSITIONS if s.pcb_chip is None)
    if not (xiao.layout.is_file() and uno.layout.is_file()):
        pytest.skip("SKIPPED: a layout is not fetched")
    ring, _cut = compose.outer(compose.read_layout(xiao.layout).outline)
    assert compose.convex(ring), "a XIAO is a rounded rectangle"
    ring, _cut = compose.outer(compose.read_layout(uno.layout).outline)
    assert not compose.convex(ring), "the Uno has a notch in its outline"


def test_a_castellated_half_hole_is_cut_off_at_the_board_edge():
    """Half a hole is half a pad, and the other half is not there.

    42 of the RP2350's 316 pads cross its outline and every one is a
    castellation on the edge. Drawn whole they hang in the air beside the
    board, which is what the wrong USB receptacle looked like in OH-101 and is
    just as wrong here.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    ring, _cut = compose.outer(board.outline)
    edge = max(point[1] for point in ring)
    castellation = next(pad for pad in board.element("U2").pads
                        if pad.shape == "circle" and abs(pad.y_mm - edge) < 0.001)

    whole = compose.pad_outline(castellation)
    assert max(p[1] for p in whole) > edge, "this pad does cross the edge"
    cut = compose.clipped_to(ring, whole)
    assert cut, "the half that is on the board is still copper"
    assert max(p[1] for p in cut) == pytest.approx(edge, abs=0.001), (
        "and the half that is off the board is not"
    )


def test_no_copper_is_drawn_outside_the_board():
    """The shipped meshes, which is what a person actually looks at.

    Reading the artefact rather than recomposing it, for the reason
    `test_no_soldered_contact_hangs_off_the_board` gives: what somebody called
    broken is the file the page loads.
    """
    models = REPO / "webui" / "static" / "models"
    boards = [slug for slug in
              (compose._slug(spec.board) for spec in compose.COMPOSITIONS)
              if (models / f"{slug}.glb").is_file()]
    if not boards:
        pytest.skip("no board composed; run tools/compose_board_3d.py")
    worst: list[str] = []
    for slug in boards:
        groups = _glb_groups(models / f"{slug}.glb")
        pcb = groups.get(compose.BOARD_MASK) or groups.get("#313d63")
        copper = groups.get(compose.COPPER)
        assert copper, f"{slug} draws no copper at all, so it is a bare slab"
        left, right = min(p[0] for p in pcb), max(p[0] for p in pcb)
        near, far = min(p[2] for p in pcb), max(p[2] for p in pcb)
        out = max(max(left - x, x - right, near - z, z - far)
                  for x, _y, z in copper)
        if out > 0.001:
            worst.append(f"{slug}: copper reaches {out:.3f} mm past the outline")
    assert not worst, "\n".join(worst)


def test_the_copper_colour_is_not_one_a_contact_check_looks_for():
    """Not aesthetics: a castellated half-hole is copper AT the board's edge.

    `test_no_soldered_contact_hangs_off_the_board` finds a receptacle's solder
    tails by colour and requires them inside the outline. Copper sharing one of
    those values would make every XIAO fail a check about its USB socket, on
    the strength of a feature that is supposed to reach the edge.
    """
    assert compose.COPPER not in compose.CONTACT_COLOURS
    assert compose.COPPER not in CONTACT_COLOURS
    assert compose.SILKSCREEN not in compose.CONTACT_COLOURS
    assert compose.SILKSCREEN not in CONTACT_COLOURS


def test_artwork_faces_one_way_whichever_way_its_ring_was_wound():
    """Two builders, two windings, and half a mesh facing backwards.

    `pad_outline` walks counter-clockwise and `stroke_outline` walks
    clockwise, because the offset that turns a line into a rectangle goes left
    and then right. Emitted as they came, the ink was back-facing while the
    copper was not -- artwork present from one side of the board and absent
    from the other, and only on whichever side the author did not look at.
    """
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert compose.signed_area(square) > 0
    assert compose.signed_area(square[::-1]) < 0
    forward = compose.flat([square], 1.0, "#c8a253", (0.0, 0.0), True)
    backward = compose.flat([square[::-1]], 1.0, "#c8a253", (0.0, 0.0), True)
    assert (forward.groups["#c8a253"][0]
            == backward.groups["#c8a253"][0]), "the same four corners in order"
    assert forward.groups["#c8a253"][2] == backward.groups["#c8a253"][2]


def test_a_stroke_with_no_length_or_no_width_is_not_ink():
    """A dot is a zero-area quad and a normal of nothing."""
    assert compose.stroke_outline(
        eagle.Stroke("F.SilkS", 1.0, 1.0, 1.0, 1.0, 0.15)) is None
    assert compose.stroke_outline(
        eagle.Stroke("F.SilkS", 1.0, 1.0, 2.0, 1.0, 0.0)) is None
    drawn = compose.stroke_outline(
        eagle.Stroke("F.SilkS", 1.0, 1.0, 2.0, 1.0, 0.2))
    assert len(drawn) == 4
    assert max(p[1] for p in drawn) - min(p[1] for p in drawn) == pytest.approx(0.2)


def test_the_silkscreen_says_what_it_could_not_draw():
    """Text is 47 to 99 pieces per board, and a caption hiding it would be
    worse than one that names it. Text needs a font; the arcs, circles and
    polygons are a handful per board and are named for the same reason."""
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    unread = dict(board.silk_unread)
    assert unread.get("text", 0) >= 40, unread
    assert board.silk, "the strokes it CAN draw are drawn"


def test_the_uno_draws_copper_too():
    """A second vendor and a second reader, and only one of them had shapes.

    `tools/eagle.py` read `<pad>` and `<smd>` for their centres, because a pad
    map is all this project wanted of them for a year. Drawing the copper
    wants the shape and the angle as well, so an Uno composed without them was
    a bare blue slab beside five XIAOs covered in gold.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip is None)
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    pads = [pad for element in board.elements for pad in element.pads]
    assert pads, "the Uno places pads"
    drawn = [pad for pad in pads if compose.pad_outline(pad) is not None]
    assert len(drawn) == len(pads), (
        f"{len(pads) - len(drawn)} of the Uno's pads have no shape this can "
        f"draw: {sorted({p.shape for p in pads if compose.pad_outline(p) is None})}"
    )
    # A drilled pad is copper on both faces; EAGLE has no per-pad layer for it.
    holes = [pad for pad in pads if pad.kind == "thru_hole"]
    assert holes and all(pad.front and pad.back for pad in holes)


# --- what a pad carries beyond its centre (OH-110) -----------------------------


def test_a_pads_stored_rotation_is_the_boards_and_not_the_footprints():
    """The fact the whole drawing of copper rests on, measured rather than read.

    KiCad could reasonably store a pad's angle either way round. On Seeed's
    RP2350 it is ABSOLUTE: of the 20 pads in footprints placed at 90 degrees
    every one says 90, and of the 79 in footprints at 180 every one says 180.
    So `compose_board_3d.from_kicad` must NOT add the placement's rotation to
    it -- doing so turns every pad on a rotated part by twice the angle, which
    on a chip land is a rectangle lying across its own pair.
    """
    path = compose.PCB_CACHE / "RP2350.kicad_pcb"
    if not path.is_file():
        pytest.skip("SKIPPED: RP2350.kicad_pcb is not fetched")
    board = kicad.read_board(path)
    turned = [p for p in board.placements if round(p.rotation_deg) % 360 == 90]
    assert turned, "no footprint on this board is placed at 90 degrees"
    agree = [pad for placed in turned for pad in placed.pads
             if round(pad.rotation_deg) % 360 == 90]
    every = [pad for placed in turned for pad in placed.pads]
    assert len(agree) == len(every), (
        f"{len(every) - len(agree)} of the pads in 90-degree footprints do not "
        f"themselves say 90, so the stored angle is not absolute after all"
    )


def test_a_pad_says_which_side_its_copper_is_on():
    """The pad's own statement, not its footprint's.

    The RP2350 has 16 pads on `B.Cu` inside front-side footprints and 24 on
    `*.Cu`, which is both faces. Deciding by the footprint's own layer would
    put a via's copper on one side and a surface pad's on the wrong one.
    """
    path = compose.PCB_CACHE / "RP2350.kicad_pcb"
    if not path.is_file():
        pytest.skip("SKIPPED: RP2350.kicad_pcb is not fetched")
    board = kicad.read_board(path)
    pads = [pad for placed in board.placements for pad in placed.pads]
    both = [pad for pad in pads if pad.front and pad.back]
    assert both, "a through-hole pad is copper on both faces"
    assert all("*.Cu" in pad.layers or "F&B.Cu" in pad.layers for pad in both)
    front_only = [pad for pad in pads if pad.front and not pad.back]
    assert front_only and all("F.Cu" in pad.layers for pad in front_only)


def test_the_silkscreen_is_read_with_the_width_it_was_drawn_at():
    """Ink covers area, and the width is most of what makes it visible.

    Seeed draw their board-level silkscreen at 0.152 mm and some of their
    footprint silkscreen at 0.010 -- a hairline nobody can see. A reader that
    dropped the width would draw both at the same weight, which is a picture
    of a board nobody printed.
    """
    path = compose.PCB_CACHE / "RP2350.kicad_pcb"
    if not path.is_file():
        pytest.skip("SKIPPED: RP2350.kicad_pcb is not fetched")
    board = kicad.read_board(path)
    assert board.silk, "this board draws silkscreen"
    assert all(stroke.width_mm > 0 for stroke in board.silk)
    assert {round(stroke.width_mm, 3) for stroke in board.silk} != {0.0}
    assert any(stroke.layer.startswith("F.") for stroke in board.silk)
    assert any(stroke.layer.startswith("B.") for stroke in board.silk), (
        "a XIAO prints its pin names on the underside"
    )


def test_a_width_written_either_way_is_read():
    """Modern KiCad nests it and older files do not, and both are in the tree."""
    nested = kicad.parse_sexp(
        '(fp_line (start 0 0) (end 1 0) (stroke (width 0.15) (type solid))'
        ' (layer "F.SilkS"))')
    assert kicad._stroke_width(nested) == pytest.approx(0.15)
    plain = kicad.parse_sexp(
        '(fp_line (start 0 0) (end 1 0) (width 0.2) (layer "F.SilkS"))')
    assert kicad._stroke_width(plain) == pytest.approx(0.2)
    silent = kicad.parse_sexp('(fp_line (start 0 0) (end 1 0) (layer "F.SilkS"))')
    assert kicad._stroke_width(silent) == 0.0


def test_clipping_does_not_care_which_way_the_outline_was_wound():
    """`contours` chains segments in whatever order the vendor wrote them.

    Nothing upstream promises a direction, so which side of an edge is
    "inside" has to be measured off the ring rather than assumed. Assuming it
    survives on every board here -- all five happen to come out
    counter-clockwise -- and would clip every pad away on the first one that
    does not, a failure that looks exactly like "the vendor drew no copper".
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    ring, _cut = compose.outer(board.outline)
    edge = max(point[1] for point in ring)
    castellation = next(pad for pad in board.element("U2").pads
                        if pad.shape == "circle" and abs(pad.y_mm - edge) < 0.001)
    shape = compose.pad_outline(castellation)

    forward = compose.clipped_to(ring, shape)
    reversed_ring = compose.clipped_to(ring[::-1], shape)
    assert forward, "the half on the board survives"
    assert len(reversed_ring) == len(forward)
    assert (max(p[1] for p in reversed_ring)
            == pytest.approx(max(p[1] for p in forward), abs=1e-9))


def test_the_artwork_pass_is_the_thing_that_cuts_copper_to_the_board():
    """`clipped_to` can be right while nothing calls it.

    A mutation handing `artwork` the raw pad instead of the cut one survived
    every test here, because the one that measures copper against the outline
    reads the SHIPPED mesh -- and a source mutation does not regenerate it.
    That is the same gap `body_allowance` and `anchor_of` each cost a round
    of: measure the guard, not only the measurement it rests on.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    ring, _cut = compose.outer(board.outline)
    meshes, tally = compose.artwork(board, ring, spec.thickness_mm, (0.0, 0.0),
                                    spec.colour)
    assert tally["pads front"] > 200, tally
    assert tally["track front"] > 200, tally

    copper = [(p[at], -p[at + 2])
              for mesh in meshes for _c, (p, _n, _i) in mesh.groups.items()
              for at in range(0, len(p), 3)]
    assert copper, "the artwork pass drew nothing"
    left, right = min(x for x, _y in ring), max(x for x, _y in ring)
    near, far = min(y for _x, y in ring), max(y for _x, y in ring)
    out = max(max(left - x, x - right, near - y, y - far) for x, y in copper)
    assert out <= 0.001, (
        f"artwork put a vertex {out:.3f} mm outside the board. A castellated "
        f"half-hole is half a hole; drawn whole it hangs in the air."
    )


# --- the routing (OH-112) ------------------------------------------------------


def test_a_trace_keeps_its_boards_own_hue():
    """**The bug this replaced showed up as silver tracery on a blue board.**

    A trace is not exposed metal, it is the mask with something brighter
    behind it: soldermask is translucent, so light goes through, reflects off
    the copper, and comes back through. What changes is lightness, not hue.

    The first version blended the mask toward `COPPER` by 0.30. Copper's blue
    channel is 83 and the Arduino Uno's navy mask's is 99, so the blend pulled
    blue DOWN while pushing red and green up, and rgb(49,61,99) came out
    rgb(94,91,94) -- a neutral grey.
    """
    navy = compose.mask_over_copper("#313d63")
    red, green, blue = (int(navy[at:at + 2], 16) for at in (1, 3, 5))
    assert blue > green > red, (
        f"#313d63 is a navy and its routing came out {navy}, which is not"
    )
    assert blue > 0x63, "and it is lighter than the mask, not darker"
    # Black stays black and gets lighter, which is what a black board's
    # routing looks like -- barely, and that is the honest answer.
    assert compose.mask_over_copper("#1b1b1b") == "#2a2a2a"


def test_a_trace_is_drawn_under_the_pads_it_runs_into():
    """A pad is what a reader is looking for, so nothing may occlude one.

    Physically the mask over a trace stands slightly PROUD of a bare pad --
    copper plus the ink over it, against copper with the ink opened away. Drawn
    that way a trace would cut the edge of every pad it reaches.
    """
    assert 0 < compose.TRACE_PROUD_MM < compose.COPPER_THICKNESS_MM


def test_only_the_two_layers_anything_can_see_are_drawn():
    """A four- and a six-layer board route inside the laminate.

    The RP2350 lays 149 segments on In2 through In4 and the nRF54L15 381.
    Nothing can see them from either side, so they are counted rather than
    drawn -- and counted rather than dropped, because "544 traces" while
    silently discarding 149 is a different claim from "544, and 149 inside".
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    assert board.traces, "this board is routed"
    assert {t.layer for t in board.traces} <= set(kicad.OUTER_COPPER)
    unread = dict(board.traces_unread)
    assert any(name.startswith("In") for name in unread), unread
    assert unread.get("zone", 0) > 0, (
        "a zone's fill is a keyhole polygon and is not attempted; the count "
        "is what says so"
    )


def test_an_airwire_is_not_a_trace():
    """EAGLE layer 19 is `Unrouted`, and the Uno carries two.

    An airwire is a connection the router has NOT made -- a straight line from
    one pad to another through whatever is in the way. Drawn as copper it would
    be a trace crossing the board that is not on it, and it would look
    exactly like one.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip is None)
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    assert {t.layer for t in board.traces} == {"F.Cu", "B.Cu"}
    assert dict(board.traces_unread).get("layer 19") == 2, board.traces_unread


def test_a_curved_trace_is_flattened_rather_than_dropped():
    """The ESP32-C6 routes 43 of its 597 lengths of track as arcs.

    Dropped, they would be 43 gaps in the routing -- and a gap in a trace is
    what a broken render looks like. `arc_points` already solves an arc's
    centre from the three points KiCad stores, for the board outline, so the
    reader keeps them as arcs and the composer flattens them with it.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "ESP32-C6")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    raw = kicad.read_board(spec.layout)
    assert raw.trace_arcs, "this board routes curves"
    assert all(arc.width_mm > 0 for arc in raw.trace_arcs), (
        "a length of track has a width; an outline arc does not and says 0"
    )
    assert all(arc.width_mm == 0 for arc in raw.arcs), (
        "an Edge.Cuts arc is a boundary, and its width means nothing"
    )
    # And they arrive as straight strokes on the way through `from_kicad`.
    board = compose.read_layout(spec.layout)
    assert len(board.traces) > len(raw.traces)


def test_every_composed_board_draws_its_routing():
    """The regression guard: a board with pads and no traces is half a board."""
    drawn = 0
    for spec in compose.COMPOSITIONS:
        if not spec.layout.is_file():
            continue
        board = compose.read_layout(spec.layout)
        assert board.traces, f"{spec.board} draws no routing"
        assert board.vias, f"{spec.board} draws no vias"
        assert any(t.layer == "F.Cu" for t in board.traces), spec.board
        assert any(t.layer == "B.Cu" for t in board.traces), spec.board
        drawn += 1
    assert drawn >= 2, f"only {drawn} layouts are fetched, so this is thin"


def test_a_via_joins_both_faces_and_is_drawn_on_each():
    """It is a plated hole through the board, so it shows from either side.

    Tented -- covered by mask -- which is why it takes a trace's colour and
    not the bare copper of an exposed pad.
    """
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    ring, _cut = compose.outer(board.outline)
    meshes, tally = compose.artwork(board, ring, spec.thickness_mm, (0.0, 0.0),
                                    spec.colour)
    assert tally["vias"] > 100, tally
    routed = compose.mask_over_copper(spec.colour)
    faces: dict[float, set[tuple[float, float]]] = {}
    for mesh in meshes:
        for colour, (p, _n, _i) in mesh.groups.items():
            if colour != routed:
                continue
            for at in range(0, len(p), 3):
                faces.setdefault(round(p[at + 1], 4), set()).add(
                    (round(p[at], 4), round(-p[at + 2], 4)))
    assert len(faces) == 2, f"routing is drawn at {sorted(faces)}, not two faces"
    assert max(faces) > 0 > min(faces)

    # **Looked for by position, because counting cannot tell a via from a
    # trace.** A mutation dropping the vias from the front group survived a
    # test that only counted heights: the back traces kept that face alive.
    # Every via is a ring of `VIA_SIDES` points at exactly its own radius, and
    # the one at angle zero is `(x + d/2, y)`.
    inside_only = [via for via in board.vias
                   if all(compose.point_in(ring, corner) for corner in (
                       (via.x_mm + via.diameter_mm / 2, via.y_mm),
                       (via.x_mm - via.diameter_mm / 2, via.y_mm),
                       (via.x_mm, via.y_mm + via.diameter_mm / 2),
                       (via.x_mm, via.y_mm - via.diameter_mm / 2)))]
    assert len(inside_only) > 100, "most vias are well inside the outline"
    for face, corners in faces.items():
        missing = [via for via in inside_only[:40]
                   if (round(via.x_mm + via.diameter_mm / 2, 4),
                       round(via.y_mm, 4)) not in corners]
        assert not missing, (
            f"{len(missing)} of 40 vias are not drawn on the face at {face}; "
            f"a via goes through the board and shows from either side"
        )


# --- the Series-B key (OH-113) -------------------------------------------------


def test_the_usb_b_opening_has_the_two_corners_the_standard_cuts():
    """**A reader called this connector an ethernet port.**

    Which is what a plain rectangular metal socket is. The two upper corners
    of a Series-B opening are cut off at 45 degrees, and the bevel is not
    decoration: it is the KEY. A Series-B plug's shell has the same two
    corners cut, so the pair mate one way up, and a socket without them is one
    that would take the plug upside down.

    Read off the built mesh rather than the payload, because the payload can
    carry a chamfer that the Blender script never draws -- which is exactly
    what the first attempt did on one side, where the cavity was coplanar with
    the front face and won the depth test.
    """
    from tools import model_from_datasheet

    made = compose.MODELLED / "USB_B_PN61729.obj"
    if not made.is_file():
        pytest.skip("SKIPPED: run python tools/model_from_datasheet.py")
    spec = next(s for s in model_from_datasheet.SPECS if s.package == "PN61729")
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    half = cited["mouth_width"] / 2
    tall = cited["mouth_height"]
    cut = cited["mouth_chamfer"]
    low = (cited["height"] - tall) / 2

    mesh, extent = compose.read_obj(made)
    front = {(round(p[at], 3), round(p[at + 2], 3))
             for _c, (p, _n, _i) in mesh.groups.items()
             for at in range(0, len(p), 3)
             if abs(p[at + 1] - extent.ymin) < 1e-6}
    assert front, "the model has no front face at all"
    for corner in ((-half + cut, low + tall), (half - cut, low + tall),
                   (-half, low + tall - cut), (half, low + tall - cut)):
        assert (round(corner[0], 3), round(corner[1], 3)) in front, (
            f"the opening has no bevel at {corner}: this is a rectangular "
            f"hole, which is an RJ45 and not a USB-B"
        )


def test_the_chamfer_is_a_bevel_and_not_a_hole_of_its_own():
    """Big enough to see, small enough to leave an opening.

    A chamfer of half the width would meet in the middle and the aperture
    would be a triangle; one of nothing would be the rectangle this replaced.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SPECS if s.package == "PN61729")
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    assert 0 < cited["mouth_chamfer"] < cited["mouth_width"] / 2
    assert cited["mouth_chamfer"] < cited["mouth_height"]


def test_the_usb_b_paddle_is_not_made_of_metal():
    """It is an insulator, and the four contacts on it are not drawn.

    Given the pin colour it rendered as a gold wedge filling the socket, which
    is a statement about a material rather than a shape -- and a wrong one.
    The value used is the moulding colour GCT put in their own USB-C STEP, so
    the two connectors on these boards say the same thing with the same
    number.
    """
    from tools import model_from_datasheet

    made = compose.MODELLED / "USB_B_PN61729.obj"
    if not made.is_file():
        pytest.skip("SKIPPED: run python tools/model_from_datasheet.py")
    spec = next(s for s in model_from_datasheet.SPECS if s.package == "PN61729")
    cited = {key: value for key, (value, _why) in spec.cited.items()}
    floor = (cited["height"] - cited["mouth_height"]) / 2

    mesh, _extent = compose.read_obj(made)
    #: The pins are the only brass in this part and they are the group that
    #: reaches UNDER the board. Nothing of that colour may stand in the
    #: aperture -- which is where the paddle is, and where it rendered as a
    #: gold wedge for as long as it was given this material.
    brass = "#" + "".join(f"{round(v * 255):02x}" for v in (0.72, 0.60, 0.30))
    assert brass in mesh.groups, "the pins are still drawn"
    positions = mesh.groups[brass][0]
    highest = max(positions[at + 2] for at in range(0, len(positions), 3))
    assert highest < floor, (
        f"brass reaches {highest:.3f} mm, which is inside an opening whose "
        f"floor is {floor:.3f}: the paddle is an insulator, and the four "
        f"contacts on it are half a millimetre wide and are not drawn"
    )
    assert compose.leads_of(mesh), "the through-hole pins are still there"
