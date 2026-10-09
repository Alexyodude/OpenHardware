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
import itertools
import json
import math
import pathlib
import re
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


def _uno_whole():
    """The Uno's composition, skipping by name what of it is not fetched: its
    board file, or the schematic beside it that `compose` now reads too
    (OH-191) -- a checkout can hold the one without the other."""
    spec = _uno()
    for path in (spec.layout, spec.schematic):
        if not path.is_file():
            pytest.skip(f"SKIPPED: {path.name} is not fetched. Run: {spec.fetch_with}")
    return spec


def _fetched(spec) -> bool:
    """Its board file is on disk, and its schematic too where it reads one."""
    return spec.layout.is_file() and (spec.schematic is None
                                      or spec.schematic.is_file())


def _drawn(spec, board):
    """`(element, row)` for every placement `compose` draws from a row, found
    the way `compose` finds it (OH-187): through the board's schematic, which
    refuses some parts and says which kind of passive the rest are."""
    statements = compose.statements_for(spec)
    for element in board.elements:
        row, _refused = compose.drawn_from(element, statements)
        if row is not None:
            yield element, row


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


def _fills_exactly(ring, triangles, probes) -> list:
    """What is wrong with `triangles` as a fill of `ring`, or [] if nothing.

    Held two ways, neither borrowed from the triangulator: every triangle
    winds forward and their areas sum to the ring's own by the shoelace
    formula; and each probe point is under a triangle exactly where an
    even-odd ray from it crosses the ring an odd number of times -- which,
    for a keyhole, leaves the counter open, because the bridge into it is
    crossed twice. A probe on a triangle's own edge counts as under it.

    The shoelace sum is taken about the ring's first point: a glyph of a few
    hundred square microns placed 100 mm from the origin loses its area to
    rounding in the plain formula's products."""
    wrong = []
    areas = [compose._cross(ring[a], ring[b], ring[c]) / 2 for a, b, c in triangles]
    if not areas or min(areas) <= 0:
        wrong.append(("a triangle of no area or wound backwards", min(areas, default=None)))
    shoelace = abs(sum(compose._cross(ring[0], a, b)
                       for a, b in itertools.pairwise(ring[1:]))) / 2
    if sum(areas) != pytest.approx(shoelace, rel=1e-9, abs=1e-12):
        wrong.append(("area", sum(areas), shoelace))

    def under(point) -> bool:
        return any(min(compose._cross(ring[a], ring[b], point), compose._cross(ring[b], ring[c], point),
                       compose._cross(ring[c], ring[a], point)) >= 0 for a, b, c in triangles)

    for point in probes:
        if under(point) != compose.point_in(ring, point):
            wrong.append(("probe", point, under(point)))
    return wrong


def _grid(width: float, height: float) -> list[tuple[float, float]]:
    """Probe points over a shape drawn on whole millimetres, each off every
    line through two of its corners, so none sits on an edge."""
    return [(x + 0.37, y + 0.61) for x in range(-1, int(width) + 1)
            for y in range(-1, int(height) + 1)]


#: An "O": a 10 mm square with a 4 mm counter, walked as KiCad writes a glyph
#: with a hole -- out along a bridge from (10, 5), round the counter the other
#: way, and back along the same bridge.
_O = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (7.0, 5.0), (7.0, 3.0), (3.0, 3.0),
      (3.0, 7.0), (7.0, 7.0), (7.0, 5.0), (10.0, 5.0), (10.0, 10.0), (0.0, 10.0)]


def test_a_keyhole_glyph_is_filled_with_its_counter_left_open():
    """**A glyph with a hole is one outline that walks into its counter and
    back** (OH-163): KiCad and EAGLE both write an "o" so, two points
    repeated and the bridge between them walked once each way. `ear_clip`
    raised on it -- no ear, it said, the polygon not simple -- so Seeed's
    logo and every PCBCUPID and SparkFun label went undrawn. It fills the
    84 mm^2 the "O" encloses and not the counter's 16, whichever way round
    the ring runs and from whichever vertex, the bridge first or last."""
    for ring in (_O, _O[::-1], _O[3:] + _O[:3], (_O[8:] + _O[:8])[::-1]):
        triangles = compose.ear_clip(ring)
        assert not _fills_exactly(ring, triangles, _grid(10, 10)), (
            ring[0], _fills_exactly(ring, triangles, _grid(10, 10)))
        assert sum(compose._cross(ring[a], ring[b], ring[c]) for a, b, c in triangles) / 2 == (
            pytest.approx(84.0))


def test_a_ring_with_two_holes_is_filled_around_both():
    """Two counters, each bridged from the bottom edge -- a "B", or a pair
    of SparkFun's letters joined as one polygon. 200 mm^2 less two of 16."""
    ring = [(0.0, 0.0), (5.0, 0.0), (5.0, 3.0), (3.0, 3.0), (3.0, 7.0), (7.0, 7.0),
            (7.0, 3.0), (5.0, 3.0), (5.0, 0.0), (15.0, 0.0), (15.0, 3.0), (13.0, 3.0),
            (13.0, 7.0), (17.0, 7.0), (17.0, 3.0), (15.0, 3.0), (15.0, 0.0), (20.0, 0.0),
            (20.0, 10.0), (0.0, 10.0)]
    for walked in (ring, ring[::-1]):
        triangles = compose.ear_clip(walked)
        assert not _fills_exactly(walked, triangles, _grid(20, 10)), _fills_exactly(
            walked, triangles, _grid(20, 10))
        assert sum(compose._cross(walked[a], walked[b], walked[c])
                   for a, b, c in triangles) / 2 == pytest.approx(168.0)


def test_a_pinch_and_a_spike_cover_only_what_they_enclose():
    """**The two other ways a vendor's outline touches itself**, both on
    PCBCUPID's labels: two squares meeting at one corner, walked as one
    ring through it twice; and a spike, out to a point and straight back.
    A pinch's two visits each turn the long way round, so a triangle across
    it can look like an ear at either and is outside both squares; a spike
    encloses nothing and must add nothing."""
    pinch = [(4.0, 4.0), (4.0, 2.0), (2.0, 2.0), (2.0, 0.0), (0.0, 0.0), (0.0, 2.0),
             (2.0, 2.0), (2.0, 4.0)]
    triangles = compose.ear_clip(pinch)
    assert not _fills_exactly(pinch, triangles, _grid(4, 4)), _fills_exactly(
        pinch, triangles, _grid(4, 4))
    spike = [(0.0, 0.0), (6.0, 0.0), (6.0, 3.0), (9.0, 3.0), (6.0, 3.0), (6.0, 6.0), (0.0, 6.0)]
    triangles = compose.ear_clip(spike)
    assert not _fills_exactly(spike, triangles, _grid(9, 6)), _fills_exactly(
        spike, triangles, _grid(9, 6))
    assert sum(compose._cross(spike[a], spike[b], spike[c]) for a, b, c in triangles) / 2 == (
        pytest.approx(36.0))


def test_a_ring_that_crosses_itself_is_refused_naming_where():
    """**A ring two of whose edges cross is no outline at all**: what it
    fills depends on a rule -- even-odd or non-zero -- that the drawing does
    not state, so it is refused and the two edges named, never filled by
    one rule or the other. Six of SparkFun's letter polygons are this, each
    an edge back from a counter that misses its own bridge by 0.01 mm."""
    bow = [(0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)]
    with pytest.raises(ValueError, match=r"cross.*\(0\.0, 0\.0\)-\(4\.0, 4\.0\)"):
        compose.ear_clip(bow)


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
    # **The XIAOs hold one refusal between them.** These sets held the
    # antennas and the coaxial socket until OH-104, the RP2350's own
    # processor until OH-100, the buttons until OH-153 and the load switch
    # until OH-154. What is left is the buck converter whose own name is
    # wrong, on the two boards that place it under that name (OH-189 made
    # this test ask the other direction, which is what found it listed
    # nowhere). An empty set fails the moment a new absence appears.
    #
    # The Arduino Uno above has two, and they are the honest kind: a
    # crystal can and a resonator that KiCad publishes no model of.
    "XIAO-ESP32-C3-DIP": set(),
    "XIAO-ESP32-C6-DIP": {"BGA6-0.35-0.745X10.95X0.4MM"},
    "XIAO-ESP32-C5-DIP": set(),
    "XIAO-RP2350-DIP": {"BGA6-0.35-0.745X10.95X0.4MM"},
    "XIAO-nRF54l15-DIP": set(),
    # **The manifest boards (OH-180) leave off what nobody publishes**, and
    # a person looking at one would look first for its USB socket and its
    # battery lead. Solder jumpers, fiducials and test pads are copper and
    # are drawn as copper, so they are not here.
    "SparkFun Thing Plus ESP32-C6": {
        "THING_PLUS", "USB-C-16P_4LAYER-PADS", "JST-2-SMD", "MICROSD_TINY",
        "WS2812-2020",
    },
    "Adafruit QT Py ESP32-C3": {"USB_C_CUSB31-CFM2AX-01-X", "SK6805_1515"},
    "Adafruit Feather ESP32-C6": {
        "1X16_ROUND", "1X12_ROUND", "USB_C_CUSB31-CFM2AX-01-X",
        "JSTPH2_BATT", "JST_SH4_RA", "LONGAN-IC_SNR6-1.0-3X3X1MM",
    },
    # The QT Py's two and its own flash (OH-186). Its castellated edge is
    # copper, as the QT Py's is, and so is not here.
    "Adafruit KB2040": {"USB_C_CUSB31-CFM2AX-01-X", "SK6805_1515", "USON8_4X4"},
    # SparkFun's USB-C socket on both (OH-189), and the Pocket's battery
    # socket. The Pro Micro's castellated edge is copper, as the QT Py's is;
    # the Pocket's header holes are refused by its own schematic, whose
    # device says NO_POP (`REFUSED_BY_SCHEMATIC`).
    "SparkFun Pro Micro ESP32-C3": {"USB-C-16P_4LAYER-PADS"},
    "SparkFun Qwiic Pocket ESP32-C6": {"USB-C-16P_4LAYER-PADS", "JST-2-SMD"},
    # The header PCBCUPID's footprints hang under the castellated rows, which
    # a person would look for (OH-195; `compose.GLYPH_HEADER`).
    "PCBCUPID Glyph Mini RP2040": {"PinHeader_1x05_P2.54mm_Vertical",
                                   "PinHeader_1x09_P2.54mm_Vertical"},
    # The buttons, whose land and model name two parts (OH-195). Their USB
    # socket is refused too, by the model their own file places
    # (`REFUSED_BY_SCHEMATIC`), and so is not here.
    "PCBCUPID Glyph C3": {"SW_SPST_PTS810"},
    "PCBCUPID Glyph C6": {"SW_SPST_PTS810"},
    # Olimex's own parts that nobody but Olimex publishes a model of.
    "Olimex ESP32-C3-DevKit-Lipo": {
        "CD32", "YTS-A016-X", "GBH-254-SMT-10", "LIPO_BAT_VERTICAL_DW02S",
        "USB2.0_TYPE-C(A40-00119-A52-12)"},
    # The C6-EVB's share of those, and its own (OH-198): its module, whose
    # value and model name two modules; its relays, terminals, jack and
    # optocouplers; two cans whose land and value state two bodies; and its
    # inductor and regulator, whose packages KiCad holds no model of.
    "Olimex ESP32-C6-EVB": {
        "CD32", "YTS-A016-X", "GBH-254-SMT-10", "USB2.0_TYPE-C(A40-00119-A52-12)",
        "ESP32-C6-WROOM-1-xx-UNIVERSAL_MODULE", "Relay_RAS-05-15",
        "TB2-DG306-5.0_2P", "TB3-DG306-5.0_3P", "PWRJ-2mm(YDJ-1136)",
        "H11A817C_SMD(PC817X3NIP06)_FP", "CPOL-RM5mm_10.0x16.0mm_PTH",
        "CPOL-RM2.5mm_6.3x11mm_PTH", "DBS135", "ESOIC-8"},
    # What its EAGLE sibling, the Thing Plus C6, leaves off, and its buttons.
    "SparkFun Thing Plus ESP32-C5": {
        "JST_1x02_P2.0mm_Horizontal_SMD", "USB-C_16",
        "microSD_Friction_Fit_Common", "WS2812_2020",
        "Push_SMD_4.6x2.8mm_h2.5mm"},
}
# **An SMD variant leaves off exactly what its DIP sibling does** -- same PCB,
# same placements, same absences -- so the entries are derived the same way
# `compose.COMPOSITIONS` derives the variants themselves (OH-118). Written as
# a loop rather than five lines so the two derivations cannot disagree.
for _dip in [name for name in EXPLAINS if name.endswith("-DIP")]:
    EXPLAINS[_dip.replace("-DIP", "-SMD")] = EXPLAINS[_dip]


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
        if not _fetched(spec):
            continue
        board = compose.read_layout(spec.layout)
        packages = {e.package for e in board.elements}
        # **And the other direction** (OH-189): every part the board refuses
        # for want of a model is in its entry. Copper, ink and holes are
        # not -- a person does not look for them -- and a part the board's
        # own schematic refuses is explained there.
        statements = compose.statements_for(spec)
        refused = {e.package for e in board.elements
                   if e.package in compose.ABSENT
                   and compose.NO_BODY not in compose.ABSENT[e.package]
                   and not (statements and e.name in statements
                            and statements[e.name].refused)}
        assert refused <= EXPLAINS[spec.board], (
            f"{spec.board} refuses {sorted(refused - EXPLAINS[spec.board])} "
            f"and its entry here does not say so")
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



def _mask_of(slug: str) -> str:
    """The colour a composed board's PCB slab is drawn in, by file stem.

    Read off the composition rather than listed here: this was
    `BOARD_MASK or "#313d63"`, which held while every board was a XIAO or
    the Uno and found no PCB at all on the first red one (OH-180).
    """
    return next(spec.colour for spec in compose.COMPOSITIONS
                if compose._slug(spec.board) == slug)


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
CONTACT_COLOURS = frozenset({"#dbbc7e", "#f6df99", "#f7e099", "#e4e3cf"})

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
        pcb = groups.get(_mask_of(slug))
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

    **A test point is the subject, because nothing else is left.** OH-154
    drew the last component body that had been refused, so the packages
    still in `ABSENT` with an `F.Fab` outline are copper and ink:
    `TP-80X40MIL` is twelve of them, a bare 80 x 40 mil pad on all five
    XIAOs, and no field of it states a height because a pad has none to
    state. The mechanism is what is under test -- a package whose height no
    readable field gives must REFUSE rather than be drawn to a guess -- and
    it holds whether the thing refused is a pad or a moulded body.

    **This test made the same point with `BUTTON_TD1183SA` until OH-153, and
    its premise was false.** It asserted the button had no height "anywhere"
    while reading the nRF54L15 -- the very board file whose Description says
    `2P-L3.0*W2.5*H1.5mm`. It passed because `_STATED_ENVELOPE` could not
    parse letters between the numbers, which is a fact about a regex and not
    about the vendor. A test can be green for years on a premise the data
    contradicts; this one was.
    """
    from tools import model_from_datasheet

    spec = dataclasses.replace(model_from_datasheet.SLABS[0],
                               package="TP-80X40MIL",
                               pcb=compose.PCB_CACHE / "ESP32-C3.kicad_pcb")
    if not spec.pcb.is_file():
        pytest.skip("SKIPPED: ESP32-C3.kicad_pcb is not fetched")
    with pytest.raises(SystemExit, match="states no length x width x height"):
        model_from_datasheet.slab_geometry(spec)
    assert "TP-80X40MIL" in compose.ABSENT, (
        "a package left off must still carry a reason, or a reader sees it "
        "missing and nothing said about it"
    )


def test_nothing_refused_is_a_part_this_file_could_have_drawn():
    """**The general form of the bug OH-153 and OH-154 each fixed one of.**

    A false absence is a part refused for want of a dimension the vendor
    states -- and both instances of it survived review because everybody,
    including three reviewers, read the REASON beside the part and found it
    persuasive. The reason was persuasive. It was also contradicted by the
    board file it sat next to.

    So this asks the question of the data instead: for every package in
    `ABSENT` that a board actually places, building a slab from it must
    FAIL. A success means the vendor states the envelope and it is being
    refused anyway.

    It sweeps every (package, board) pair rather than one board per package,
    because that is exactly where the button hid: the ESP32-C3's two copies
    carry an empty `Description` while the ESP32-C5's and nRF54L15's state
    `2P-L3.0*W2.5*H1.5mm`. A sweep that stopped at the first board would
    have agreed with the refusal.

    **What this half cannot see, measured rather than assumed.** Putting
    `BUTTON_TD1183SA` or `PMOS_1.0X0.6X0.35MM` back into `ABSENT` fails it,
    but putting `PMOS_1.0_0.6_0.35MM` back does NOT -- and that survival is
    correct rather than a hole. The C3's spelling of the load switch is one
    `slab_geometry` genuinely cannot read, underscores where `_NAMED_BODY`
    wants an `x`; it is drawn by borrowing the other spelling's model, which
    is a fact about `CORRESPONDENCE` and not about the parser. The first
    assertion below is what covers it, and it is the cheaper question
    anyway: a package cannot be both refused and drawn.
    """
    from tools import model_from_datasheet

    both = set(compose.ABSENT) & {c.package for c in compose.CORRESPONDENCE}
    assert not both, (
        f"{sorted(both)} are in ABSENT and in CORRESPONDENCE at once, so the "
        f"board draws a part while the page says it was left off. Whichever "
        f"is stale, a reader is being told two different things."
    )

    template = model_from_datasheet.SLABS[0]
    checked = 0
    for spec in compose.COMPOSITIONS:
        if not spec.layout.is_file():
            continue
        placed = {e.package for e in compose.read_layout(spec.layout).elements}
        kicad5 = spec.layout.suffix == ".kicad_pcb" and kicad.board_version(
            kicad.parse_sexp(spec.layout.read_text(encoding="utf-8"))) == kicad.KICAD5_VERSION
        if spec.layout.suffix != ".kicad_pcb" or kicad5:
            # **An EAGLE layout, which the slab reader cannot open** (OH-180),
            # **or a KiCad 5 one**, whose `(module ...)` it does not read
            # (OH-198): it walks a board's `(footprint ...)` nodes itself.
            # The question is the same one asked of the name alone: a
            # refused package whose own name states length x width x height
            # is the OH-153 kind of absence, and its reason must say that the
            # gap is the reader and not the part -- or it is a false one.
            for package in sorted(placed & set(compose.ABSENT)):
                if model_from_datasheet._NAMED_BODY.search(package) is None:
                    continue
                why = compose.ABSENT[package]
                assert ("tools/model_from_datasheet.py" in why
                        and ("EAGLE package" in why or "KiCad 5" in why)), (
                    f"{package} on {spec.board} states its own body in its "
                    f"name and is refused without saying the reader is the "
                    f"gap: {why}"
                )
                checked += 1
            continue
        for package in sorted(placed & set(compose.ABSENT)):
            trial = dataclasses.replace(template, package=package,
                                        pcb=spec.layout)
            with pytest.raises(SystemExit) as raised:
                model_from_datasheet.slab_geometry(trial)
            assert "draws no *.Fab outline" in str(raised.value) or \
                   "states no length x width x height" in str(raised.value) or \
                   "mm apart" in str(raised.value), (
                f"{package} on {spec.board} refused for an unexpected "
                f"reason: {raised.value}"
            )
            checked += 1
    if not checked:
        pytest.skip("SKIPPED: no board layouts are fetched")


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
    absent = _inputs_missing(spec, compose.read_layout(spec.layout))
    if absent:
        pytest.skip(f"SKIPPED: {spec.board} reads what is not fetched: {absent}")
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
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 1.0, "#dbbc7e", (0.0, 0.0)),
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
    # **Not "no row is a QFN-56"**, which is what this asserted until the
    # KB2040's RP2040 arrived (OH-186): a 56-lead chip whose model IS one.
    # The near miss is a model naming a different number of leads from the
    # land it stands on, so that is what is checked, on every fetched board.
    named = re.compile(r"(?:QFN|DFN|SON)-(\d+)-1EP")
    checked = 0
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            continue
        for element, component in _drawn(spec, compose.read_layout(spec.layout)):
            leads = named.search(component.model)
            if not leads:
                continue
            checked += 1
            # A pad on no copper layer is a paste aperture KiCad lays over
            # an exposed pad, as the Glyph's RP2040 has, and not a lead
            # (OH-195). An EAGLE pad is on copper by construction.
            copper = [pad for pad in element.pads if pad.front or pad.back]
            assert len(copper) == int(leads.group(1)) + 1, (
                f"{spec.board}: {element.name} ({element.package}) puts down "
                f"{len(copper)} pads and was given {component.model}. "
                f"A {leads.group(1)}-lead part and its exposed pad is not "
                f"that land, however well it measures."
            )
    if not checked:
        pytest.skip("SKIPPED: no board layouts are fetched")


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

    Its footprint carries no `F.Fab` outline and no `Description` either.
    Before OH-124 the refusal fired at the missing Fab outline; the widened
    body reader now takes the silkscreen outline where Fab is silent, so
    the file DOES say how large the part is -- and still not how TALL,
    which no layer of a land pattern carries. The refusal moved one check
    downstream, to the empty Description, and the boundary it guards is
    unchanged: a body of invented thickness is what
    `tools/model_from_datasheet.py` exists not to draw.
    """
    from tools import model_from_datasheet

    spec = next(s for s in model_from_datasheet.SOCKETS
                if s.package == "USB2.0-TYPE-C")
    c3 = compose.PCB_CACHE / "ESP32-C3.kicad_pcb"
    if not c3.is_file():
        pytest.skip("SKIPPED: ESP32-C3.kicad_pcb is not fetched")
    with pytest.raises(SystemExit, match=r"states no length\*width\*height"):
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

    # 15 until OH-119 mapped the Uno's small parts; 47 until OH-191 deleted
    # the L1812 and CT/CN0603 rows, which drew F1, Z1 and Z2 in borrowed
    # bodies that the Uno's own schematic now refuses. Counted by row.
    assert checked == 44, (
        f"only {checked} components were checked against silk")
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
    _uno_whole()
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
    # 15 until OH-119 mapped the Uno's small parts; 47 until OH-191 deleted
    # the L1812 and CT/CN0603 rows. Counted by row.
    assert checked == 44, (
        f"only {checked} components were boxed")


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

    **A manifest row's entry is derived on both sides now** (OH-186): the
    importer reads `tools/board_manifest.py` for itself, with its own slug
    and its own rule for which rows compose, so this still fails when the
    two derivations disagree -- a slug spelled differently, or a row one
    side composes and the other refuses -- rather than when a row is added.
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


def test_the_importers_boards_are_real_and_each_named_once():
    """**On the values the importer holds, not on its source text** (OH-186).

    `tools/check_facts.py` asks the same two questions of `COMPOSED` by
    reading its literal, and the manifest rows are appended to it rather
    than written in it -- so there the rows go unasked. A board both
    fetched and composed would have two answers in `index.json`, and a board
    named here that `webui/boards/` does not hold is a model for nothing.
    """
    from tools.import_3d_model import COMPOSED, MODELS

    held = {json.loads(path.read_text(encoding="utf-8"))["board"]
            for path in (REPO / "webui" / "boards").glob("*.json")}
    fetched = {board for model in MODELS for board in model.boards}
    composed = {board for board, _chip, _slug in COMPOSED}
    assert not fetched & composed, (
        f"{sorted(fetched & composed)} are both fetched (MODELS) and composed")
    assert composed | fetched <= held, (
        f"{sorted((composed | fetched) - held)} have a model and no board "
        f"file in webui/boards/")


def test_a_manifest_row_the_composer_refuses_is_not_in_the_importers_list(
        monkeypatch):
    """The importer's filter, pinned: a row in a format the composer refuses
    (`manifest_composition`) must not reach `COMPOSED` either, and an EAGLE
    and a KiCad row beside it must -- KiCad's since OH-195. The importer is
    loaded afresh over the patched rows, because it reads them as it loads."""
    import importlib.util

    from tools import board_manifest

    kicad_row = dataclasses.replace(board_manifest.ROWS[0], board="A KiCad Board",
                                    cad="board.kicad_pcb")
    eagle_row = dataclasses.replace(board_manifest.ROWS[0], board="An EAGLE Board",
                                    cad="board.brd")
    altium_row = dataclasses.replace(board_manifest.ROWS[0],
                                     board="An Altium Board", cad="board.PcbDoc")
    monkeypatch.setattr(board_manifest, "ROWS", (kicad_row, eagle_row, altium_row))
    spec = importlib.util.spec_from_file_location(
        "import_3d_model_over_patched_rows", REPO / "tools" / "import_3d_model.py")
    fresh = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, fresh)
    spec.loader.exec_module(fresh)
    named = {board for board, _chip, _slug in fresh.COMPOSED}
    assert "An EAGLE Board" in named, "the importer no longer reads the rows"
    assert "A KiCad Board" in named, (
        "a KiCad row is composed and the importer does not list it")
    assert "An Altium Board" not in named, (
        "an Altium row reached COMPOSED, and the composer refuses it")
    _made, refused = compose.manifest_compositions((kicad_row, altium_row))
    assert set(refused) == {"An Altium Board"}


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
        pcb = groups.get(_mask_of(slug))
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
    """A caption hiding what it left out would be worse than one that names
    it. Text was unread until OH-163, an arc until its step 3, and a filled
    polygon until the slice after; all are read now, for the composer to
    letter, to flatten and to fill, and what stays unread is named: the text
    the file hides, and the circles, each counted by kind."""
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    board = compose.read_layout(spec.layout)
    unread = dict(board.silk_unread)
    assert "text" not in unread and unread.get("hidden text", 0) > 0, unread
    assert len(board.kicad_text) >= 40, len(board.kicad_text)
    assert board.silk, "the strokes it CAN draw are drawn"


def _fill_layouts():
    """Each fetched composed board file once, by its first composition."""
    specs = {}
    for spec in compose.COMPOSITIONS:
        if spec.layout.is_file():
            specs.setdefault(spec.layout, spec)
    if not specs:
        pytest.skip("SKIPPED: no composed board file is fetched; run "
                    "python tools/compose_board_3d.py")
    return list(specs.values())


def _crosses(ring) -> bool:
    """Whether two edges of `ring` cross, held pair by pair -- slower than
    the composer's sweep, and not borrowed from it."""
    for i, j in itertools.combinations(range(len(ring)), 2):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        c, d = ring[j], ring[(j + 1) % len(ring)]
        sides = (compose._cross(c, d, a), compose._cross(c, d, b),
                 compose._cross(a, b, c), compose._cross(a, b, d))
        if 0 not in sides and (sides[0] > 0) != (sides[1] > 0) and (sides[2] > 0) != (sides[3] > 0):
            return True
    return False


def test_every_filled_polygon_of_ink_is_filled_to_its_own_area():
    """**Every filled polygon on a composed board's silkscreen is filled as
    its vendor's plot fills it, or refused because it crosses itself**
    (OH-163). None was drawn before: Seeed's logo on the RP2350 and the C5,
    PCBCUPID's labels, Olimex's logo and open-hardware mark, the Thing Plus
    C5's labels, SparkFun's EAGLE letters. Each `ear_clip` fills sums to its
    own shoelace area, every triangle wound forward; on each that touches
    itself -- a keyhole, a pinch, a spike -- seeded probes are under a
    triangle exactly where the even-odd rule puts them inside; and each it
    refuses has two edges that cross, found here pair by pair. The keyholes
    step 3 measured are counted among those filled, board by board."""
    import random

    probe = random.Random(163)
    tally: dict[str, dict[str, int]] = {}
    for spec in _fill_layouts():
        counts = tally.setdefault(spec.board, {})
        for fill in compose.read_layout(spec.layout).silk_fills:
            ring = list(fill.points)
            try:
                triangles = compose.ear_clip(ring)
            except ValueError:
                assert _crosses(ring), (spec.board, ring[:4])
                counts["crossing"] = counts.get("crossing", 0) + 1
                continue
            touching = len(set(ring)) < len(ring)
            xs, ys = [x for x, _y in ring], [y for _x, y in ring]
            probes = [(probe.uniform(min(xs), max(xs)), probe.uniform(min(ys), max(ys)))
                      for _ in range(25 if touching else 0)]
            wrong = _fills_exactly(ring, triangles, probes)
            assert not wrong, (spec.board, len(ring), wrong[:3])
            kind = "touching" if touching else "simple"
            counts[kind] = counts.get(kind, 0) + 1
    measured = {"XIAO-RP2350-DIP": 6, "XIAO-ESP32-C5-DIP": 6, "PCBCUPID Glyph Mini RP2040": 3,
                "PCBCUPID Glyph C3": 78, "PCBCUPID Glyph C6": 78,
                "Olimex ESP32-C3-DevKit-Lipo": 6, "SparkFun Thing Plus ESP32-C5": 192}
    seen = {board: tally[board].get("touching", 0) for board in measured if board in tally}
    assert seen and seen == {board: measured[board] for board in seen}, tally


def test_an_eagle_silkscreen_polygon_is_read_as_a_fill_where_its_element_puts_it(tmp_path):
    """**SparkFun letter their EAGLE labels as `<polygon>`s on tPlace, a
    keyhole for every letter with a counter** (OH-163), and the reader
    counted them and dropped them. Read now as fills, every vertex placed as
    a wire's ends are -- turned with its element, mirrored with one at MR
    and moved to the other face -- with the polygon's width as its pen; a
    board-level polygon as drawn. A polygon with a curved edge, or poured
    other than solid, stays counted; one on tDocu is no ink at all."""
    path = tmp_path / "inked.brd"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><board>'
        '<plain><wire x1="0" y1="0" x2="20" y2="0" width="0.2" layer="20"/>'
        '<polygon width="0" layer="22"><vertex x="1" y="1"/><vertex x="2" y="1"/>'
        '<vertex x="2" y="2"/></polygon></plain>'
        '<libraries><library name="L"><packages><package name="P">'
        '<pad name="1" x="0" y="0" drill="1.016" diameter="1.8796"/>'
        '<polygon width="0.01" layer="21"><vertex x="1" y="0"/><vertex x="3" y="0"/>'
        '<vertex x="3" y="1"/></polygon>'
        '<polygon width="0.15" layer="21"><vertex x="0" y="0" curve="90"/>'
        '<vertex x="1" y="0"/><vertex x="1" y="1"/></polygon>'
        '<polygon width="0" layer="21" pour="hatch"><vertex x="0" y="0"/>'
        '<vertex x="1" y="0"/><vertex x="1" y="1"/></polygon>'
        '<polygon width="0" layer="51"><vertex x="0" y="0"/><vertex x="1" y="0"/>'
        '<vertex x="1" y="1"/></polygon>'
        "</package></packages></library></libraries>"
        "<elements>"
        '<element name="A" library="L" package="P" x="10" y="5" rot="R90"/>'
        '<element name="B" library="L" package="P" x="10" y="5" rot="MR0"/>'
        "</elements><signals/>"
        "</board></drawing></eagle>",
        encoding="utf-8",
    )
    board = eagle.read_board(path)
    got = [(fill.layer, tuple((round(x, 9), round(y, 9)) for x, y in fill.points),
            fill.width_mm) for fill in board.silk_fills]
    # (1, 0) turned a quarter about (10, 5) is (10, 6); mirrored, (9, 5).
    assert got == [
        ("B.SilkS", ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)), 0.0),
        ("F.SilkS", ((10.0, 6.0), (10.0, 8.0), (9.0, 8.0)), 0.01),
        ("B.SilkS", ((9.0, 5.0), (7.0, 5.0), (7.0, 6.0)), 0.01),
    ], got
    assert dict(board.silk_unread) == {"polygon": 4}, board.silk_unread


def test_an_eagle_silkscreen_rectangle_is_read_as_a_filled_quad(tmp_path):
    """**Adafruit's Feather logo is 5,783 `<rectangle>`s on tPlace**, a
    bitmap turned into runs a pixel tall, and the Uno marks its LEDs and
    passives with 16 more (OH-163). Each is read as a filled quad: turned by
    its own `rot` about its own centre -- (0, 0)-(2, 1) at R90 stands on
    (1, 0.5) -- then placed with its element, and moved to the other face,
    mirrored, by one at MR; a board-level one as drawn. One on tDocu is no
    ink. On the Feather every one is read, and none is left counted."""
    path = tmp_path / "boxed.brd"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><board>'
        '<plain><wire x1="0" y1="0" x2="20" y2="0" width="0.2" layer="20"/>'
        '<rectangle x1="1" y1="1" x2="3" y2="2" layer="21"/></plain>'
        '<libraries><library name="L"><packages><package name="P">'
        '<pad name="1" x="0" y="0" drill="1.016" diameter="1.8796"/>'
        '<rectangle x1="0" y1="0" x2="2" y2="1" layer="21"/>'
        '<rectangle x1="0" y1="0" x2="2" y2="1" layer="21" rot="R90"/>'
        '<rectangle x1="0" y1="0" x2="2" y2="1" layer="51"/>'
        "</package></packages></library></libraries>"
        "<elements>"
        '<element name="A" library="L" package="P" x="10" y="5"/>'
        '<element name="B" library="L" package="P" x="10" y="5" rot="MR0"/>'
        "</elements><signals/>"
        "</board></drawing></eagle>",
        encoding="utf-8",
    )
    board = eagle.read_board(path)
    got = [(fill.layer, tuple((round(x, 9) + 0.0, round(y, 9) + 0.0) for x, y in fill.points),
            fill.width_mm) for fill in board.silk_fills]
    assert got == [
        ("F.SilkS", ((1.0, 1.0), (3.0, 1.0), (3.0, 2.0), (1.0, 2.0)), 0.0),
        ("F.SilkS", ((10.0, 5.0), (12.0, 5.0), (12.0, 6.0), (10.0, 6.0)), 0.0),
        ("F.SilkS", ((11.5, 4.5), (11.5, 6.5), (10.5, 6.5), (10.5, 4.5)), 0.0),
        ("B.SilkS", ((10.0, 5.0), (8.0, 5.0), (8.0, 6.0), (10.0, 6.0)), 0.0),
        ("B.SilkS", ((8.5, 4.5), (8.5, 6.5), (9.5, 6.5), (9.5, 4.5)), 0.0),
    ], got
    assert "rectangle" not in dict(board.silk_unread), board.silk_unread

    spec = next(s for s in compose.COMPOSITIONS if s.board == "Adafruit Feather ESP32-C6")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    feather = compose.read_layout(spec.layout)
    quads = [fill for fill in feather.silk_fills if len(fill.points) == 4 and fill.width_mm == 0]
    assert (len(quads), "rectangle" in dict(feather.silk_unread)) == (5783, False), (
        len(quads), feather.silk_unread)


def _faces(mesh, colour) -> list[tuple[tuple[float, float], ...]]:
    """Each triangle of `colour` in `mesh`, as board points: the scene's x,
    and its z negated back to the board's y."""
    positions, _normals, indices = mesh.groups[colour]
    point = [(positions[at], -positions[at + 2]) for at in range(0, len(positions), 3)]
    return [tuple(point[index] for index in indices[at:at + 3])
            for at in range(0, len(indices), 3)]


def test_a_fill_is_drawn_as_ink_with_its_counter_open_and_its_pen_traced():
    """**The artwork pass draws each fill as `ear_clip` fills it** (OH-163),
    on its own face, cut to the board like all ink: the "O"'s ink covers its
    84 mm^2 and leaves the counter bare; a back-side square drawn with a
    0.5 mm pen is traced a quarter millimetre outside its edge, as the
    vendor's plot traces a polygon's outline, and -- every stroke here being
    the rectangle its width sweeps -- not round its corners. A fill that
    crosses itself is counted under `FILL_REFUSED`, and one wholly beside
    the board is counted too, neither drawn."""
    board = eagle.Board("inked", "test", (), (), silk_fills=(
        eagle.Fill("F.SilkS", tuple(_O), 0.0),
        eagle.Fill("B.SilkS", ((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)), 0.5),
        eagle.Fill("F.SilkS", ((0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)), 0.0),
        eagle.Fill("F.SilkS", ((30.0, 30.0), (31.0, 30.0), (31.0, 31.0)), 0.0),
    ))
    ring = [(-1.0, -1.0), (12.0, -1.0), (12.0, 12.0), (-1.0, 12.0)]
    meshes, tally, _undrawn = compose.artwork(board, ring, 1.6, (0.0, 0.0), "#313d63", [])
    assert (tally["fill front"], tally["fill back"], tally[compose.FILL_REFUSED],
            tally["fill off the board"]) == (1, 1, 1, 1), tally
    front, back = _faces(meshes[2], compose.SILKSCREEN), _faces(meshes[5], compose.SILKSCREEN)
    assert sum(compose._cross(*face) for face in front) / 2 == pytest.approx(84.0)

    def under(faces, point) -> bool:
        """On or inside a face, whichever way it is wound: a back face is
        wound to face down."""
        return any(min(sides) >= 0 or max(sides) <= 0 for sides in (
            (compose._cross(a, b, point), compose._cross(b, c, point),
             compose._cross(c, a, point)) for a, b, c in faces))

    for point in _grid(10, 10):
        assert under(front, point) == compose.point_in(_O, point), point
    # Inside; in the pen's band outside the edge; beyond it; off the corner.
    assert [under(back, point) for point in ((3.0, 3.0), (1.9, 3.0), (1.7, 3.0),
                                             (1.85, 1.85))] == [True, True, False, False]


def test_a_fill_the_triangulator_refuses_is_counted_as_ink_not_drawn(capsys):
    """**What `ear_clip` refuses is ink the file carries and the model
    lacks**, so `compose` prints it on the `not ink` line under
    `FILL_REFUSED` and not on the artwork line (OH-163): on SparkFun's Thing
    Plus ESP32-C6, the letters whose bridge back from a counter misses itself
    and crosses, each counted as many times as it is placed."""
    spec = next(s for s in compose.COMPOSITIONS if s.board == "SparkFun Thing Plus ESP32-C6")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    refused = 0
    for fill in compose.read_layout(spec.layout).silk_fills:
        try:
            compose.ear_clip(list(fill.points))
        except ValueError:
            refused += 1
    lines = _accounting(spec, capsys).splitlines()
    unread = next(line for line in lines if line.startswith("  not ink "))
    drawn = next(line for line in lines if line.startswith("  artwork "))
    assert refused and f"{compose.FILL_REFUSED} {refused}" in unread, (refused, unread)
    assert compose.FILL_REFUSED not in drawn, drawn


def test_the_composed_fills_land_on_seeeds_plotted_regions():
    """**A filled mark reaches the composed board as Seeed plotted it**
    (OH-163): on the XIAO ESP32-C6, each filled polygon `from_kicad` gives
    the composer -- in its own frame, y up, which from Seeed's zero origin
    IS the Gerber's -- is filled by triangles whose areas sum to its plotted
    region's, every one of them inside that region. The C6's three U.FL
    marks are the only filled silkscreen any fetched vendor Gerber plots."""
    import zipfile

    from tests.rules.test_kicad import (
        SEEED_C6_ROOT,
        SEEED_PCB,
        _gerber_draws,
        _same_ring,
    )

    zipped, path = SEEED_PCB / "ESP32-C6.zip", SEEED_PCB / "ESP32-C6.kicad_pcb"
    if not (zipped.is_file() and path.is_file()):
        pytest.skip(f"SKIPPED: {zipped.name} or {path.name} absent under {SEEED_PCB}; "
                    f"python tools/compose_board_3d.py --board XIAO-ESP32-C6-DIP")
    regions: list = []
    with zipfile.ZipFile(zipped) as bundle:
        assert path.read_bytes() == bundle.read(SEEED_C6_ROOT + "XIAO ESP32 C6.kicad_pcb")
        _gerber_draws(bundle.read(f"{SEEED_C6_ROOT}XIAO ESP32 C6_gerber/"
                                  f"XIAO ESP32 C6-F_Silkscreen.gbr").decode("ascii"),
                      path.name, regions=regions)
    fills = compose.from_kicad(path).silk_fills
    assert len(fills) == len(regions) == 3, (len(fills), len(regions))
    for fill in fills:
        ring = list(fill.points)
        region = next((contour[:-1] for contour in regions if _same_ring(ring, contour[:-1])), None)
        assert region is not None, ring
        faces = [[ring[index] for index in triangle] for triangle in compose.ear_clip(ring)]
        assert sum(compose._cross(*face) for face in faces) / 2 == pytest.approx(
            abs(compose._area(region)) / 2, rel=1e-6)
        assert all(compose.point_in(region, (sum(x for x, _y in face) / 3,
                                             sum(y for _x, y in face) / 3)) for face in faces)


def test_text_beside_the_board_is_not_drawn_on_it():
    """**Seeed draw a stackup table beside the RP2350, on its silkscreen
    layer**, and a fab prints nothing off the board. So a text stroke is cut
    to the outline as every other piece of ink is, and one wholly beside the
    board is counted rather than drawn in the air."""
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched")
    _newstroke()
    board = compose.read_layout(spec.layout)
    ring, _cut = compose.outer(board.outline)
    letters, _refused, _drawn = compose.lettering(board.kicad_text)
    meshes, tally, _undrawn = compose.artwork(board, ring, spec.thickness_mm,
                                              (0.0, 0.0), spec.colour, letters)
    ink = [(p[at], -p[at + 2]) for mesh in meshes
           for colour, (p, _n, _i) in mesh.groups.items() if colour == compose.SILKSCREEN
           for at in range(0, len(p), 3)]
    left, right = min(x for x, _y in ring), max(x for x, _y in ring)
    near, far = min(y for _x, y in ring), max(y for _x, y in ring)
    out = max(max(left - x, x - right, near - y, y - far) for x, y in ink)
    assert out <= 0.001, f"ink {out:.3f} mm outside the board"
    assert tally.get("text stroke off the board", 0) > 0, tally
    assert tally["text front"] > 0 and tally["text back"] > 0, tally


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
    meshes, tally, _undrawn = compose.artwork(board, ring, spec.thickness_mm,
                                              (0.0, 0.0), spec.colour, [])
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
    meshes, tally, _undrawn = compose.artwork(board, ring, spec.thickness_mm,
                                              (0.0, 0.0), spec.colour, [])
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
    #: The sRGB of the linear (0.72, 0.60, 0.30) first typed for them (OH-214).
    brass = "#" + "".join(f"{round(v * 255):02x}" for v in (0.865, 0.798, 0.584))
    assert brass in mesh.groups, "the pins are still drawn"
    positions = mesh.groups[brass][0]
    highest = max(positions[at + 2] for at in range(0, len(positions), 3))
    assert highest < floor, (
        f"brass reaches {highest:.3f} mm, which is inside an opening whose "
        f"floor is {floor:.3f}: the paddle is an insulator, and the four "
        f"contacts on it are half a millimetre wide and are not drawn"
    )
    assert compose.leads_of(mesh), "the through-hole pins are still there"


# --- the shape of a Type-C (OH-114) --------------------------------------------


def test_the_usb_c_shell_is_an_obround_and_not_a_box():
    """**A reader called this part blocky, and a square-cornered box is.**

    A Type-C connector's cross-section is an obround -- a rectangle with a
    SEMICIRCLE at each end, radius half its height. That pill is the most
    recognisable thing about the connector: it is why the plug is reversible,
    and it is why nobody mistakes one for anything else.

    Measured as the ABSENCE of corners, which is what tells the two shapes
    apart. On Seeed's 8.94 x 3.25 mm envelope the end radius is 1.625, so the
    nearest the profile comes to a corner of its own bounding box is
    1.625 x (root 2 - 1) = 0.673 mm. A box has a vertex sitting on it.
    """
    from tools import model_from_datasheet

    checked = 0
    for spec in model_from_datasheet.SOCKETS:
        made = compose.MODELLED / f"{spec.name}.obj"
        if not made.is_file():
            continue
        if not spec.pcb.is_file():
            continue
        checked += 1
        plan = model_from_datasheet.socket_geometry(spec)
        length, across, height = plan["stated"]
        # The Description's first two numbers are in no fixed order -- the 16P
        # land says `7.35*8.94*3.25` and the four-tab one `8.9*7.3*3.2` -- so
        # the across-the-edge width is simply the larger of the two.
        width = max(length, across)
        mid = sum(plan["body"]["y"]) / 2

        mesh, _extent = compose.read_obj(made)
        steel = model_from_datasheet.SOCKET_COLOURS["shell"][0]
        assert steel in mesh.groups, f"{spec.name} draws no shell"
        positions = mesh.groups[steel][0]
        # **The tube, without what lies on the board.** The shell feet and the
        # board locks are the same metal and are pads rather than part of the
        # section; every one of them is under 0.35 mm tall, and the first
        # version of this test measured a foot's inner corner and called the
        # connector square.
        section = [(positions[at + 1], positions[at + 2])
                   for at in range(0, len(positions), 3)
                   if positions[at + 2] > 0.4]
        assert section, f"{spec.name} has no shell above its own feet"
        for corner in ((mid - width / 2, 0.0), (mid - width / 2, height),
                       (mid + width / 2, 0.0), (mid + width / 2, height)):
            nearest = min(math.dist(corner, point) for point in section)
            assert nearest > 0.5, (
                f"{spec.name} has metal {nearest:.3f} mm from the corner "
                f"{corner} of the envelope its vendor states, so its ends are "
                f"square and it is not a Type-C"
            )
    assert checked == 2, f"{checked} sockets are built, and there are two"


def test_rounding_the_shell_did_not_move_the_part():
    """The bounding box is what every other check measures.

    `confirm` compares spans, `silk_miss` compares body centres and the
    overhang test compares vertices against the outline. Rounding the ends
    changes the CROSS-SECTION and must leave all three alone -- so the shell
    still measures the envelope Seeed state, to the millimetre they state it.
    """
    from tools import model_from_datasheet

    for spec in model_from_datasheet.SOCKETS:
        made = compose.MODELLED / f"{spec.name}.obj"
        if not (made.is_file() and spec.pcb.is_file()):
            continue
        plan = model_from_datasheet.socket_geometry(spec)
        # **The Description's first two numbers are in no fixed order**: the
        # 16P land says `7.35*8.94*3.25` and the four-tab one `8.9*7.3*3.2`,
        # so the depth comes first on one and second on the other. That is
        # why `socket_geometry` SORTS them before comparing with `F.Fab`, and
        # the across-the-edge width is simply the larger of the two.
        length, across, height = plan["stated"]
        width = max(length, across)
        mesh, extent = compose.read_obj(made)
        assert extent.zmax == pytest.approx(height, abs=0.001), (
            f"{spec.name} stands {extent.zmax:.3f} mm and its vendor says "
            f"{height}"
        )
        steel = model_from_datasheet.SOCKET_COLOURS["shell"][0]
        positions = mesh.groups[steel][0]
        # Above the feet and the locks, which lie on the board rather than
        # being part of the section -- the same 0.4 mm the test above uses.
        across = [positions[at + 1] for at in range(0, len(positions), 3)
                  if positions[at + 2] > 0.4]
        drawn = max(across) - min(across)
        # **Against the F.Fab rectangle, which is what the tube is built
        # from**, and not against the Description: those two disagree by
        # 0.020 and 0.092 mm on the two land patterns, which is a fact about
        # the vendor's file that `socket_geometry` already checks and this
        # test would otherwise re-measure as if it were an error here.
        by0, by1 = plan["body"]["y"]
        assert drawn == pytest.approx(by1 - by0, abs=0.001), (
            f"{spec.name}'s shell is {drawn:.3f} mm wide and the F.Fab "
            f"rectangle it is built from is {by1 - by0:.3f}"
        )
        assert drawn == pytest.approx(width, abs=0.1), (
            f"{spec.name}'s shell is {drawn:.3f} mm wide and its vendor's "
            f"Description says {width}"
        )


# --- a half turn, and the parts nothing could see one on (OH-106) ------------


def test_a_curved_wire_on_the_silkscreen_is_read_as_a_pin_one_marker():
    """Arduino's own `DIL28-3` draws the DIP notch as a wire with a `curve`,
    and it is the only curved thing on that package's silkscreen. The chord's
    midpoint is at x -18.542, which is the end pad 1 is at."""
    board = eagle.read_board(_uno().layout)
    element = board.element("ZU4")
    assert element.mark is not None, "the notch is no longer read"
    assert element.mark[0] == pytest.approx(-18.542, abs=0.001)
    assert element.mark[1] == pytest.approx(0.0, abs=0.001)
    # **And it is at the end their own pad 1 is at**, which is the two vendor
    # statements agreeing. Compared on the BOARD, through `mark_of`: ZU4 is
    # placed at 180 degrees, so the package-frame -18.542 lands at +x and
    # comparing the raw coordinate against a board offset gets the answer
    # exactly backwards. That is what the first version of this test did.
    on_board = compose.mark_of(element)
    assert on_board is not None, "the notch is 0.500 of the package off centre"
    one = next(pad for pad in element.pads if pad.number == "1")
    assert math.copysign(1, on_board[0] - element.x_mm) == math.copysign(
        1, one.x_mm - element.x_mm), (
        f"the vendor's notch lands at x {on_board[0]:.3f} and their own pad 1 "
        f"at {one.x_mm:.3f}, on opposite sides of the element origin "
        f"{element.x_mm:.3f} -- so one of the two readings is wrong"
    )


def test_a_circle_on_the_silkscreen_is_read_as_a_pin_one_marker():
    """The other spelling, on the same board: Arduino's `MLF32` marks pin 1
    with a `<circle>` at (-1.600, 1.600) rather than a notch."""
    board = eagle.read_board(_uno().layout)
    element = board.element("U3")
    assert element.mark is not None, "the corner dot is no longer read"
    assert compose.mark_of(element) is not None, (
        "the dot is 0.453 of the package's own size off its centre, which is "
        "well past MARK_OFFSET_FRACTION"
    )


def test_a_curved_outline_is_not_a_pin_one_marker():
    """**Curvature alone does not mean pin 1**, and both counter-examples are
    on the Arduino Uno. `PANASONIC_D` draws an electrolytic can as two arcs
    whose centroid is the package origin to 0.000 mm, and `TS42` draws a
    button as two concentric circles at 0.021 of its size. Read as markers
    they would point at nothing in particular and refuse a correct turn."""
    board = eagle.read_board(_uno().layout)
    for name in ("PC1", "RESET"):
        element = board.element(name)
        assert element.mark is not None, f"{name} draws curved silkscreen"
        assert compose.mark_of(element) is None, (
            f"{name} ({element.package}) is a round OUTLINE and is now being "
            f"read as a pin-1 marker"
        )


def test_kicad_reads_the_fab_circle_as_a_pin_one_marker():
    """The same fact in the other CAD. Seeed mark pin 1 with an `fp_circle` on
    `F.Fab`, which `tools/model_from_datasheet.py` already reads for the
    RP2350's QFN -- this makes the same reading available to every placement
    rather than to one part."""
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "RP2350")
    if not spec.layout.is_file():
        pytest.skip(f"no layout; run {spec.fetch_with}")
    board = kicad.read_board(spec.layout)
    marked = [p for p in board.placements if p.mark is not None]
    assert marked, "no footprint on the RP2350 marks pin 1 any more"
    qfn = next(p for p in board.placements if p.name.startswith("QFN60"))
    assert qfn.mark is not None, "the QFN-60's pin-1 circle is no longer read"


def test_a_pin_header_is_the_same_part_turned_round():
    """**A half turn that moves nothing is not a claim that can be wrong.**
    Every pin header on the Uno is symmetric about its own anchor, so its
    `turn` is a free choice and no check needs to have an opinion. Measured
    rather than assumed, because this is what keeps the count of unpinned
    parts honest: a part that comes out at exactly zero is not counted."""
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = _uno()
    if not spec.layout.is_file():
        pytest.skip(f"no layout; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    element = board.element("IOH")
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == element.package)
    mesh, _box = compose.component_mesh(component, 0.05)
    moved = compose.half_turn_moves(mesh, element, component.turn,
                                    spec.thickness_mm, centre)
    assert moved == 0.0, (
        f"a 1x10 header now moves {moved:.4f} of its own mesh under a half "
        f"turn, so its turn has become a claim that something has to check"
    )
    # **And therefore it is not counted as an unseen turn either.** Both
    # halves matter: a symmetric part needs no check, and counting one as a
    # gap would inflate the number this ticket exists to make honest -- 23 of
    # the 43 packages placed are symmetric, so the count would nearly treble.
    put = compose.place(mesh, element, component.turn, spec.thickness_mm, centre)
    assert not compose.turn_unseen(element, mesh, put, component.turn,
                                   spec.thickness_mm, centre)


def test_the_dip_is_turned_the_way_arduino_draw_their_own_notch():
    """**The mutation this ticket was filed for.**

    Turning `DIL28-3` from 90 to 270 survived the whole suite: `confirm`
    compares spans and a half turn preserves one, `silk_miss` compares body
    centres and a half turn preserves one of those too, and `contact_miss`
    needs a pin field of plated metal that a DIP has not got.

    What sees it is the notch. Arduino draw one at the end their pad 1 is at,
    KiCad's model cuts one into the top of the body -- 1.5 x 0.8 mm of
    `#262525` -- and at the stated turn the two land 1.542 mm apart against
    25.15 for the nearest rival.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = _uno()
    if not spec.layout.is_file():
        pytest.skip(f"no layout; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    element = board.element("ZU4")
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == "DIL28-3")
    mesh, _box = compose.component_mesh(component, 0.05)
    misses = compose.mark_turns(element, mesh, spec.thickness_mm, centre)
    assert misses is not None, "the DIP's notch no longer decides its turn"
    best = min((miss, turn) for turn, miss in misses.items())
    assert best[1] == component.turn, (
        f"CORRESPONDENCE turns the DIP-28 {component.turn:.0f} and its own "
        f"notch lands nearest Arduino's at {best[1]:.0f} -- "
        f"{ {t: round(m, 3) for t, m in misses.items()} }"
    )
    rival = min(miss for turn, miss in misses.items() if turn != component.turn)
    assert rival - misses[component.turn] > compose.TURN_MARGIN_MM, (
        f"the stated turn beats its nearest rival by only "
        f"{rival - misses[component.turn]:.3f} mm, which is inside "
        f"TURN_MARGIN_MM and therefore a coin toss"
    )


def test_every_part_whose_vendor_marks_pin_one_agrees_with_its_model():
    """**The general rule, on every composed board.** Where the vendor draws
    a pin-1 marker and the model has a feature a half turn moves, no RIVAL
    turn may beat the stated one by the margin.

    Not "the stated turn must win by the margin", which is what this
    asserted until OH-124 -- the widened marker reader gave the C3's U.FL
    a mark, and its nearly four-fold-symmetric mesh puts every turn within
    0.006 mm of every other: nobody wins, the comparison carries no
    information, and the composer counts the part unseen. What stays fatal
    here is what was always fatal: a rival turn decisively closer to the
    vendor's own dot than the turn the table states -- the exact shape in
    which the same reader caught the C3's processor a quarter turn wrong
    the day it landed.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    cache: dict = {}
    checked = 0
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            continue
        board = compose.read_layout(spec.layout)
        pads = [pad for name in spec.headers for pad in board.element(name).pads]
        centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
                  (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
        # The composer's own lookup: SparkFun's `0603` is two rows, told
        # apart by library, and Adafruit's by what their schematic states.
        for element, component in _drawn(spec, board):
            if compose.mark_of(element) is None:
                continue
            if component.slug not in cache:
                cache[component.slug] = compose.component_mesh(component, 0.05)
            mesh, _box = cache[component.slug]
            misses = compose.mark_turns(element, mesh, spec.thickness_mm, centre)
            if misses is None or component.turn not in misses:
                continue
            checked += 1
            rival = min((miss for turn, miss in misses.items()
                         if turn != component.turn), default=None)
            assert rival is None or misses[component.turn] < rival + compose.TURN_MARGIN_MM, (
                f"{spec.board}: {element.name} ({element.package}) is turned "
                f"{component.turn:.0f} and a rival turn puts the model's "
                f"feature decisively closer to the vendor's own marker -- "
                f"{ {t: round(m, 3) for t, m in misses.items()} }"
            )
    if not checked:
        pytest.skip("no layouts on disk; run tools/get_board_sources.py")
    assert checked >= 6, (
        f"only {checked} placement(s) had both a vendor marker and a model "
        f"feature to compare it with; six did when this was written, so a "
        f"reader has been lost"
    )


#: How far the band's area-weighted centroid must sit off the model's centre
#: against the next colour's before it is taken for the band: twice. Every
#: diode model drawn here clears it by four times that or more -- a
#: MiniMELF's thin blue stripe included, once weighted by area.
BAND_MARGIN = 2.0

#: The least share of a model's surface a colour must cover to be read as a
#: band at all: a painted stripe is a face, and a stray triangle far out at
#: the anode end is not one, however far out it sits.
MIN_BAND_SHARE = 0.01

#: The least a band's offset may be, as a share of the model's half-length:
#: a floor under the margin, which cannot fire when the next colour sits
#: exactly on the centre -- end caps at 0.000 make any ratio infinite, and a
#: tessellation's 0.02 mm of noise would then be read as a band. Every
#: diode model drawn here sits a third of its half-length out or more.
BAND_FLOOR = 0.2


def _read_band(mesh) -> tuple[str, float]:
    """A diode model's band and how far off its centre it sits, in the
    model's own plan -- or an AssertionError saying there is no band to
    read, which is what a model with one colour, or with its stripe painted
    over, has."""
    everything = [value for positions, _n, _i in mesh.groups.values()
                  for value in positions]
    spans = [max(everything[axis::3]) - min(everything[axis::3]) for axis in (0, 1)]
    middle = [(max(everything[axis::3]) + min(everything[axis::3])) / 2
              for axis in (0, 1)]
    read = _area_centroids(mesh.groups)
    surface = sum(area for _u, _v, area in read.values())
    offsets = sorted(((math.dist(middle, (u, v)), colour)
                      for colour, (u, v, area) in read.items()
                      if area >= MIN_BAND_SHARE * surface), reverse=True)
    assert len(offsets) > 1, (
        f"no band to read: {len(offsets)} colour(s) cover "
        f"{MIN_BAND_SHARE:.0%} of the surface")
    (off, band), (runner_up, _next) = offsets[0], offsets[1]
    assert off >= BAND_MARGIN * runner_up, (
        f"no band to read: the most off-centre colour sits {off:.3f} mm out "
        f"and the next {runner_up:.3f}")
    assert off >= BAND_FLOOR * max(spans) / 2, (
        f"no band to read: the most off-centre colour sits {off:.3f} mm out, "
        f"under {BAND_FLOOR:.0%} of the model's half-length, {max(spans) / 2:.3f}")
    return band, off


def test_a_model_with_no_band_says_so():
    """The floor and the count, on models built to have no band: one colour
    alone, and a cylinder whose end caps sit exactly on the centre with its
    body 0.02 mm off it -- a ratio of infinity, and noise."""
    with pytest.raises(AssertionError, match="no band to read"):
        _read_band(_model_box(3.6, 1.4, 1.4, "#d2d1c7"))
    caps = [_model_box(0.4, 1.4, 1.4, "#d2d1c7", at=(x, 0.0)) for x in (-1.6, 1.6)]
    positions, normals, indices = [], [], []
    for cap in caps:
        (p, n, i), = cap.groups.values()
        indices += [index + len(positions) // 3 for index in i]
        positions += p
        normals += n
    body = _model_box(2.8, 1.4, 1.4, "#b2190d", at=(0.02, 0.0))
    cylinder = compose.Mesh({"#d2d1c7": (positions, normals, indices),
                             **body.groups})
    with pytest.raises(AssertionError, match="half-length"):
        _read_band(cylinder)
    # And a real stripe, a fifth of the length in from one end, reads.
    stripe = _model_box(0.3, 1.41, 1.41, "#0000ff", at=(-0.9, 0.0))
    band, _off = _read_band(compose.Mesh({**cylinder.groups, **stripe.groups}))
    assert band == "#0000ff"


def _area_centroids(groups, plan=(0, 1)) -> dict[str, tuple[float, float, float]]:
    """Each colour group's centroid in plan, weighted by its triangles' area,
    so a sliver with many vertices cannot outweigh a face with few -- and
    the group's area, third."""
    out = {}
    for colour, (positions, _normals, indices) in groups.items():
        sum_a = sum_u = sum_v = 0.0
        for at in range(0, len(indices), 3):
            corners = [positions[i * 3:i * 3 + 3] for i in indices[at:at + 3]]
            edge1 = [corners[1][k] - corners[0][k] for k in range(3)]
            edge2 = [corners[2][k] - corners[0][k] for k in range(3)]
            area = math.dist((0, 0, 0), (
                edge1[1] * edge2[2] - edge1[2] * edge2[1],
                edge1[2] * edge2[0] - edge1[0] * edge2[2],
                edge1[0] * edge2[1] - edge1[1] * edge2[0])) / 2
            sum_a += area
            sum_u += area * sum(c[plan[0]] for c in corners) / 3
            sum_v += area * sum(c[plan[1]] for c in corners) / 3
        if sum_a:
            out[colour] = (sum_u / sum_a, sum_v / sum_a, sum_a)
    return out


def test_a_diodes_band_lies_along_its_land_at_the_pad_its_vendor_names_the_cathode():
    """**A diode's turn, checked by its own band** (OH-186 review, OH-190).

    A KiCad diode model marks its cathode with a band: the colour whose
    area-weighted centroid sits furthest off the model's centre, by
    `BAND_MARGIN` over the next -- or there is no band to read and the test
    says so rather than guess. Placed, the band must lie ALONG the land:
    nearer one pad than the other by at least its own offset, where a diode
    drawn across its pads puts it the same distance from both (the Uno's
    MiniMELFs did, at turn 90). And where the vendor names the pads A and C,
    the nearer is C. On every composed board, each skipped by name when its
    files are not fetched.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    cache: dict = {}
    checked, unfetched = [], []
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            unfetched.append(spec.board)
            continue
        board = compose.read_layout(spec.layout)
        pads = [pad for name in spec.headers for pad in board.element(name).pads]
        centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
                  (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
        for element, component in _drawn(spec, board):
            if component.library != "Diode_SMD" or len(element.pads) != 2:
                continue
            if component.slug not in cache:
                cache[component.slug] = compose.component_mesh(component, 0.05)
            mesh, _box = cache[component.slug]
            try:
                band, off = _read_band(mesh)
            except AssertionError as exc:
                raise AssertionError(
                    f"{spec.board}: {element.name} ({component.model}) has "
                    f"{exc}") from None
            put = compose.place(mesh, element, component.turn, spec.thickness_mm,
                                centre, component.flip)
            # The scene: x is the board's, z its y negated.
            got = _area_centroids({band: put.groups[band]}, plan=(0, 2))[band][:2]
            near = {pad.number: math.dist(got, (pad.x_mm - centre[0],
                                                -(pad.y_mm - centre[1])))
                    for pad in element.pads}
            (d_near, nearer), (d_far, _farther) = sorted(
                (d, number) for number, d in near.items())
            assert d_far - d_near >= off, (
                f"{spec.board}: {element.name} ({element.package}) turned "
                f"{component.turn:.0f} puts its band {d_near:.3f} and "
                f"{d_far:.3f} mm from its two pads: it lies across its land")
            if set(near) == {"A", "C"}:
                assert nearer == "C", (
                    f"{spec.board}: {element.name} ({element.package}) turned "
                    f"{component.turn:.0f} puts its band at pad A")
            checked.append((spec.board, element.name))
    if not checked:
        pytest.skip(f"SKIPPED: no diode on a fetched board; not fetched: {unfetched}")
    if unfetched:
        pytest.skip(f"checked {len(checked)} diodes; not fetched: {unfetched}")


def test_the_turn_nothing_can_see_is_counted_rather_than_passed_over():
    """**A gap that is measured is one somebody can close.**

    Eighteen placements move under a half turn with nothing here able to tell,
    and the composer prints them per board rather than staying quiet -- the
    same reason `Board.silk_unread` is counted. An 0402 LED is the clearest
    case: it is not symmetric, its two pads are, its model carries no plated
    pin field and Seeed draw it no marker.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "ESP32-C3")
    if not spec.layout.is_file():
        pytest.skip(f"no layout; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    element = board.element("CHG0")
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == element.package)
    mesh, _box = compose.component_mesh(component, 0.05)
    put = compose.place(mesh, element, component.turn, spec.thickness_mm, centre)
    assert compose.turn_unseen(element, mesh, put, component.turn,
                               spec.thickness_mm, centre), (
        "the 0402 LED's turn is now checkable by something, which is good -- "
        "update the count in the composer's own note and here"
    )
    assert compose.half_turn_moves(mesh, element, component.turn,
                                   spec.thickness_mm, centre) > 0.0, (
        "the LED is now symmetric under a half turn, so it should not be "
        "counted as an unseen turn at all"
    )


def test_the_barrel_jack_is_not_counted_because_silk_already_refuses_it():
    """The count asks whether an existing check would REJECT the half turn,
    not whether some number changes. Arduino's barrel jack moves its silk miss
    from 0.013 to 7.496 mm -- five times `SILK_TOLERANCE_MM` -- so it is seen,
    and counting it would overstate the gap by the one part this whole family
    of checks was originally written for."""
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = _uno()
    if not spec.layout.is_file():
        pytest.skip(f"no layout; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    element = board.element("X1")
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == element.package)
    mesh, _box = compose.component_mesh(component, 0.05)
    put = compose.place(mesh, element, component.turn, spec.thickness_mm, centre)
    assert not compose.turn_unseen(element, mesh, put, component.turn,
                                   spec.thickness_mm, centre)
    other = compose.place(mesh, element, (component.turn + 180.0) % 360.0,
                          spec.thickness_mm, centre)
    assert compose.silk_miss(element, other, centre) > compose.SILK_TOLERANCE_MM


def test_compose_refuses_a_part_turned_away_from_the_pin_one_marker(monkeypatch):
    """The guard for the marker, not just the measurement.

    The same lesson `test_compose_refuses_a_board_whose_part_faces_the_wrong_way`
    records, one check later: a mutation that stops the `raise` firing survives
    every test that calls `mark_turns` itself and asserts on what it returns.
    This drives the real thing with the DIP-28 half a turn out, which is the
    mutation OH-106 was filed for.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    _uno_whole()
    wrong = tuple(
        dataclasses.replace(component, turn=270.0)
        if component.package == "DIL28-3" else component
        for component in compose.CORRESPONDENCE
    )
    monkeypatch.setattr(compose, "CORRESPONDENCE", wrong)
    with pytest.raises(SystemExit, match="ZU4") as refused:
        compose.compose(_uno(), compose.DEFLECTION, check=True)
    assert "pin-1 marker" in str(refused.value), (
        f"the DIP was refused, but not by the marker: {refused.value}"
    )


# --- the DIP variant's headers, hung below the board (OH-118) ----------------


def test_a_flipped_part_hangs_below_the_board_with_its_tails_proud_of_the_top():
    """**The one new degree of freedom `flip` adds, measured on one vertex.**

    A body point above the raw mesh's zero comes out BELOW the board -- the
    body rests against the underside -- and a solder tail below the raw zero
    comes out above the top face, which is what `carvePins` needs to find on
    the pads. And x is negated along with z: one negated axis alone would be a
    MIRROR, which is the defect class OH-115 was, so the pair is asserted
    together.
    """
    mesh = compose.Mesh(groups={
        "#dbbc7e": ([1.0, 0.0, 2.0,    # a body corner, above the raw zero
                     0.0, 0.0, -3.0],  # a tail tip, below it
                    [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
                    [0, 1, 1]),
    })
    element = eagle.Element(
        "DIP1", "composed", "XIAO-DIP-1X07",
        pads=(eagle.Pad("1", "thru_hole", 10.0, 20.0, 1.7, 1.7, None),),
        x_mm=10.0, y_mm=20.0)
    flat = compose.place(mesh, element, 0.0, 1.6, (0.0, 0.0))
    flipped = compose.place(mesh, element, 0.0, 1.6, (0.0, 0.0), flip=True)
    fx, fy, fz = flat.groups["#dbbc7e"][0][0:3]
    px, py, pz = flipped.groups["#dbbc7e"][0][0:3]
    assert fy == pytest.approx(1.6 + 2.0), "unflipped, the body stands on top"
    assert py == pytest.approx(-2.0), "flipped, the body hangs below the board"
    tail_y = flipped.groups["#dbbc7e"][0][4]
    assert tail_y == pytest.approx(3.0), (
        "the tail should come out proud of the top face, where the pad is"
    )
    assert px - 10.0 == pytest.approx(-(fx - 10.0)), (
        "x is not negated with z, so the flip is a MIRROR rather than the "
        "half turn about a horizontal axis it claims to be"
    )


def test_the_dip_rows_sit_at_the_vendors_own_offset_from_the_module_centre():
    """`dip_header_elements` from a synthetic castellation field: two rows of
    seven through-hole pads, 7.62 mm either side of the field's centre along
    its shorter axis, spanning 6 x 2.54 along the longer -- every number the
    vendor's own `XIAO-*-DIP.kicad_mod`, measured across all twelve."""
    field = [eagle.Pad(str(n), "thru_hole",
                       100.0 + x, -50.0 + y, 0.8, 0.8, None)
             for n, (x, y) in enumerate(
                 [(dx, dy) for dx in (-7.62, 7.62) for dy in (-8.89, 8.89)])]
    made = compose.dip_header_elements(field)
    assert len(made) == 2
    for element in made:
        assert element.package == "XIAO-DIP-1X07"
        assert len(element.pads) == compose.DIP_ROW_PINS
        assert all(pad.kind == "thru_hole" for pad in element.pads)
        xs = sorted(pad.x_mm for pad in element.pads)
        assert xs[-1] - xs[0] == pytest.approx(6 * 2.54)
        assert xs[1] - xs[0] == pytest.approx(compose.DIP_PITCH_MM)
    rows = sorted(element.pads[0].y_mm for element in made)
    # **7.62 as a literal, not `compose.DIP_ROW_OFFSET_MM`** -- a right-hand
    # side imported from the module under test agrees with itself however
    # wrong the constant is, and a mutation moving the rows out to the
    # castellations survived this test while it read the constant back.
    assert rows[0] == pytest.approx(-50.0 - 7.62)
    assert rows[1] == pytest.approx(-50.0 + 7.62)
    # And the synthetic package is in CORRESPONDENCE, flipped: the headers
    # hang BELOW a XIAO so it can stand in a breadboard.
    component = next(c for c in compose.CORRESPONDENCE
                     if c.package == "XIAO-DIP-1X07")
    assert component.flip, "the headers would stand on top of the board"


def test_an_smd_variant_is_its_dip_siblings_pcb_without_the_headers():
    """**The variants stopped sharing one file, and this is the shape of the
    split.** Every -SMD composition shares its layout, thickness and colour
    with its -DIP sibling and composes no headers; no composition serves an
    -SMD board any more, because a model with headers is wrong for a board
    without them and vice versa."""
    by_board = {spec.board: spec for spec in compose.COMPOSITIONS}
    smd = [spec for spec in compose.COMPOSITIONS if spec.board.endswith("-SMD")]
    assert len(smd) >= 5, "the derived SMD variants are gone"
    for spec in smd:
        sibling = by_board[spec.board.replace("-SMD", "-DIP")]
        assert spec.layout == sibling.layout
        assert spec.thickness_mm == sibling.thickness_mm
        assert spec.colour == sibling.colour
        assert not spec.dip_headers
        assert sibling.dip_headers, f"{sibling.board} lost its headers"
    for spec in compose.COMPOSITIONS:
        # `-DIP-SMD` is a HEADER variant despite the suffix -- its pad map is
        # identical to the DIP's, measured pad for pad -- so serving it the
        # DIP file is right and only a bare -SMD board may not be served one.
        assert not any(name.endswith("-SMD") and "-DIP-" not in name
                       for name in spec.serves), (
            f"{spec.board} serves {spec.serves}: an SMD board is being handed "
            f"a model with DIP headers on it"
        )


def test_the_composed_dip_board_has_pin_metal_at_both_header_rows():
    """The whole point, measured on the mesh that ships: metal above the top
    face AND below the board at both rows, z = +/-7.62 in the model's frame.
    The below-board half is what makes the module read as a breadboard part;
    the above-top half is what `carvePins` finds on the pads."""
    from tools.import_3d_model import read_extras

    glb = REPO / "webui" / "static" / "models" / "XIAO-RP2350-DIP.glb"
    if not glb.is_file():
        pytest.skip("no composed RP2350; run tools/compose_board_3d.py")
    extras = read_extras(glb)
    thickness = extras["pcb"]["thickness"]
    assert extras["pad_span"] == [15.24, 15.24], (
        "a DIP board's pad_span is its DIP field, or scaleFromPads divides "
        "pixels of one field by millimetres of another and the model draws "
        "14% too small"
    )
    brass = _glb_groups(glb).get("#dbbc7e", [])
    for row in (-7.62, 7.62):
        near = [p for p in brass if abs(p[2] - row) < 0.6]
        assert any(p[1] > thickness for p in near), (
            f"no header metal above the top face at row z={row}: the tails "
            f"are gone and no pad on that row can find a pin"
        )
        assert any(p[1] < -3.0 for p in near), (
            f"no legs below the board at row z={row}: the header does not "
            f"hang, so the module cannot stand in a breadboard"
        )


def test_the_smd_variants_mesh_is_the_old_bare_board():
    """The SMD board is the same PCB with nothing hung below it: no geometry
    anywhere near a breadboard leg's depth, which is what the bare composed
    board always was."""
    glb = REPO / "webui" / "static" / "models" / "XIAO-RP2350-SMD.glb"
    if not glb.is_file():
        pytest.skip("no composed RP2350-SMD; run tools/compose_board_3d.py")
    lows = [p[1] for group in _glb_groups(glb).values() for p in group]
    assert min(lows) > -3.0, (
        f"the SMD variant reaches {min(lows):.2f} mm below the board, so the "
        f"DIP headers leaked into the sibling that must not have them"
    )


def test_compose_injects_the_dip_headers_for_a_dip_spec():
    """**The measurement was tested and its USE was not**, which is this
    repository's most repeated failure: `dip_header_elements` was covered and
    a mutation deleting its one call site survived, because the shipped-mesh
    tests read a `.glb` no mutation recomposes. Asserted at the source with
    comment lines stripped -- the OH-117 lesson, where a docstring quoting the
    expression satisfied a source assertion after the code was gutted."""
    source = pathlib.Path(compose.__file__).read_text(encoding="utf-8")
    body = source.split("def compose(", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "dip_header_elements(header_pads) if spec.dip_headers" in code, (
        "compose no longer injects the DIP headers, so every XIAO DIP board "
        "goes back to a bare SMD model under pads that expect pins"
    )


# --- every part is drawn or its absence is stated (OH-119) -------------------


def test_every_uno_package_is_drawn_or_its_absence_is_explained():
    """**The composer dropped 99 of the Uno's 116 elements in silence** --
    among them the pin-13 LED every Blink drives, on a project whose stated
    purpose is watching one. `compose` skips any package in neither
    `CORRESPONDENCE` nor `ABSENT` with no model and no line of output, so
    the only thing that keeps the board honest is this closed-world check:
    a package must be one or the other, by name.

    This is deliberately the DONE-WHEN of OH-119 rather than a count: a count
    survives a swapped part, and a new element in a vendor revision fails
    loudly here instead of vanishing.
    """
    spec = _uno_whole()
    board = compose.read_layout(spec.layout)
    mapped = {c.package for c in compose.CORRESPONDENCE}
    # A package every placement of which its own schematic refuses is
    # explained there, with the reason printed per part (OH-191).
    statements = compose.statements_for(spec)
    stated_off = {e.package for e in board.elements
                  if compose.drawn_from(e, statements)[1] is not None}
    explained = set(compose.ABSENT) | stated_off
    # A placement that puts down no pad -- the Uno's schematic frame -- is no
    # part, and `compose` counts it apart (OH-163).
    orphans = sorted({e.package for e in board.elements if e.pads}
                     - mapped - explained)
    assert not orphans, (
        f"{orphans} are neither drawn nor explained. Add a CORRESPONDENCE "
        f"row with a measured why, or an ABSENT row with the reason -- "
        f"silence is the defect OH-119 was filed about"
    )


def test_every_composed_boards_placements_are_drawn_or_explained():
    """**The same closed world, on every composed board** (OH-186).

    A manifest row is composed by construction, so a board arrives with no
    table edit at all -- and the KB2040 did, with eleven of its placements
    drawn as nothing and one line of output saying so. The lookup is the
    composer's own, `correspondence_for`, because SparkFun's `0603` is two
    rows told apart by library. A padless element that states no mesh is
    ink and is counted apart by `compose`, and so is one whose own Edge.Cuts
    is the board's outer ring (OH-163) -- not one that only cuts a slot or a
    notch, which is a part like any other -- so only a placement with a pad
    or a mesh that is not the board must be one or the other.
    """
    orphans: dict[str, list[str]] = {}
    checked = 0
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            continue
        checked += 1
        statements = compose.statements_for(spec)
        for element in compose.read_layout(spec.layout).elements:
            # A part its own schematic refuses is explained there (OH-187).
            row, refused = compose.drawn_from(element, statements)
            if ((element.pads or element.models) and not element.edge
                    and element.package not in compose.ABSENT
                    and row is None and refused is None):
                orphans.setdefault(spec.board, []).append(
                    f"{element.name} ({element.package})")
    if not checked:
        pytest.skip("SKIPPED: no board layouts are fetched")
    assert not orphans, (
        f"placements neither drawn nor explained: {orphans}. Add a "
        f"CORRESPONDENCE row with a measured why, or an ABSENT row with the "
        f"reason"
    )


def test_the_pin_13_led_is_one_of_the_drawn_parts():
    """The single part the project exists to show. Pinned by name on the
    shipped mesh, so a table edit that quietly re-orphaned the LEDs would
    fail here even without a recompose of the world."""
    led = next((c for c in compose.CORRESPONDENCE
                if c.package == "CHIP-LED0805"), None)
    assert led is not None, "the Uno's indicator LEDs lost their row"
    assert led.model == "LED_0805_2012Metric"
    glb = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not glb.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    from tools.import_3d_model import read_extras

    drawn = read_extras(glb)["drawn"]
    for name in ("L (LED_0805_2012Metric)", "ON (LED_0805_2012Metric)",
                 "RX (LED_0805_2012Metric)", "TX (LED_0805_2012Metric)"):
        assert name in drawn, f"{name} is not in the shipped mesh's own list"
    assert len(drawn) >= 44, (
        f"the Uno draws {len(drawn)} parts; it drew 47 when OH-119 closed and "
        f"44 once OH-191 read its schematic, which refuses F1, Z1 and Z2 "
        f"out loud -- fewer means something was silently lost"
    )


# --- the tallies reach a reader (OH-125) -------------------------------------


def test_what_is_not_drawn_rides_in_extras():
    """**The measurement stopped at stdout** (OH-125): `compose` printed
    artwork tallies, unread ink and copper, cutouts and unchecked turns,
    and the extras dict carried none of it -- the mechanism that let
    OH-119 and OH-122 sit unnoticed. The page's claim about what is not
    drawn is now the composer's own measurement, and this reads it back
    out of a shipped board."""
    glb = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not glb.is_file():
        pytest.skip("SKIPPED: run python tools/compose_board_3d.py first")
    from tools.import_3d_model import read_extras

    extras = read_extras(glb)
    assert "artwork" in extras and extras["artwork"].get("ink front", 0) > 0
    gaps = extras.get("not_drawn")
    assert gaps is not None, "the composer's gaps still stop at stdout"
    for key in ("ink", "copper", "cutouts", "turn_unseen", "unmodelled", "text"):
        assert key in gaps, f"not_drawn is missing {key}"
    # The Uno prints text in EAGLE's own vector font, which no licence lets
    # this repository carry -- so its text is counted in the ink tally and
    # refused, every piece of it, under that reason (OH-163).
    assert gaps["ink"].get("text", 0) > 0
    assert gaps["text"] == {compose.EAGLE_TEXT: gaps["ink"]["text"]}, gaps["text"]
    # **Text the file hides is not a gap** (OH-163 step 1's review): KiCad
    # plots none of it either, so it rides under its own key and `not_drawn`
    # lists only what a vendor's plot has and this model lacks. SparkFun's
    # KiCad file for the Thing Plus C5 hides every text it carries.
    assert extras.get("hidden") == {"text": 0}, extras.get("hidden")
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Thing Plus ESP32-C5")
    glb = REPO / "webui" / "static" / "models" / f"{compose._slug(spec.board)}.glb"
    if not (glb.is_file() and spec.layout.is_file()):
        pytest.skip(f"SKIPPED: {glb.name} or {spec.layout.name} is absent; "
                    f"{spec.fetch_with}, then python tools/compose_board_3d.py")
    hidden = dict(compose.read_layout(spec.layout).silk_unread).get("hidden text", 0)
    extras = read_extras(glb)
    assert hidden > 0 and extras.get("hidden") == {"text": hidden}, (hidden, extras.get("hidden"))
    assert "hidden text" not in extras["not_drawn"]["ink"], extras["not_drawn"]["ink"]


def test_an_unmodelled_placement_is_counted_not_skipped():
    """The bare `continue` was the silence itself: a placement with no
    model and no ABSENT entry fell through without becoming a number.
    Pinned at the source with comments stripped, because the counting
    happens inside `compose` where no unit can reach it cheaply."""
    source = (REPO / "tools" / "compose_board_3d.py").read_text(encoding="utf-8")
    body = source.split("def compose(", 1)[1]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "unmodelled.append" in code, (
        "an unmapped placement falls through a bare continue again"
    )
    assert "absent_why(element) is None" in code, (
        "ABSENT packages are counted as unmodelled, double-reporting what "
        "the absent list already explains"
    )
    assert '"not_drawn"' in code, "the gaps do not ride in extras"


def test_a_composed_board_lists_every_colour_it_draws_in_no_named_material():
    """OH-163: a colour `FINISHES` cannot name stays at the default, and the
    page's own inventory says which colours those are rather than letting them
    pass as grey with nothing to say why.

    On the artefact where one exists: `default_finish` in each composed
    board's extras must be exactly the file's materials that have no
    `FINISHES` entry, with the triangles each covers -- not a superset, not a
    stale copy from before an entry was added. And pinned at the source, with
    comments stripped, so a checkout with nothing composed still fails if the
    list stops being written.
    """
    from tools.import_3d_model import FINISHES, read_extras

    source = (REPO / "tools" / "compose_board_3d.py").read_text(encoding="utf-8")
    body = source.split("def compose(", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "default_finish = report_finishes(whole)" in code, (
        "the composer no longer keeps what its own audit could not name")
    assert '"default_finish": default_finish' in code, (
        "the unnamed colours do not ride in extras")

    seen = 0
    for spec in compose.COMPOSITIONS:
        glb = REPO / "webui" / "static" / "models" / f"{compose._slug(spec.board)}.glb"
        if not glb.is_file():
            continue
        raw = glb.read_bytes()
        length = struct.unpack("<I", raw[12:16])[0]
        doc = json.loads(raw[20:20 + length])
        unnamed: dict[str, int] = {}
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                name = doc["materials"][primitive["material"]]["name"]
                if name not in FINISHES:
                    unnamed[name] = unnamed.get(name, 0) + (
                        doc["accessors"][primitive["indices"]]["count"] // 3)
        listed = read_extras(glb).get("default_finish")
        assert listed == unnamed, (
            f"{glb.name}: extras list {listed} as drawn in no named material, "
            f"and the file's own materials with no FINISHES entry are {unnamed}")
        seen += 1
    if not seen:
        pytest.skip("no composed board on disk; run tools/compose_board_3d.py")


def test_the_ceramic_parts_reach_the_shipped_boards_as_dielectrics():
    """OH-155 on the artefact: the material in the file, not the row in the table.

    A slab is one box, so its colour group is exactly twelve triangles, and
    that count is what says the group IS the ceramic part rather than some
    vendor face that happens to share the hex. Metalness 0 and the table's
    own roughness are what a reader's renderer will shade it with.

    Skips where nothing has been composed, the same trade every shipped-mesh
    test in this file makes.
    """
    from tools.import_3d_model import CERAMIC, FINISHES

    for board in ("XIAO-ESP32-C5-DIP", "XIAO-nRF54l15-DIP"):
        path = REPO / "webui" / "static" / "models" / f"{board}.glb"
        if not path.is_file():
            pytest.skip(f"no composed {board}; run tools/compose_board_3d.py")
        raw = path.read_bytes()
        json_length = struct.unpack("<I", raw[12:16])[0]
        doc = json.loads(raw[20:20 + json_length])
        finishes = {}
        triangles: dict[str, int] = {}
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                material = doc["materials"][primitive["material"]]
                pbr = material["pbrMetallicRoughness"]
                finishes[material["name"]] = (pbr["metallicFactor"],
                                              pbr["roughnessFactor"])
                count = doc["accessors"][primitive["indices"]]["count"] // 3
                triangles[material["name"]] = (
                    triangles.get(material["name"], 0) + count)
        assert CERAMIC in finishes, f"{board}: no ceramic material in the file"
        assert finishes[CERAMIC] == (0.0, FINISHES[CERAMIC].roughness), board
        assert triangles[CERAMIC] == 12, (
            f"{board}: {triangles[CERAMIC]} triangles of {CERAMIC}, "
            "not the one box a slab is"
        )
        # The colour it used to borrow is a dielectric wherever it remains:
        # KiCad's PLASTIC-WHITE-01, a body on every model carrying it
        # (OH-163's review), and no longer the 'steel cover' it was taken for.
        if "#e4e3cf" in finishes:
            assert finishes["#e4e3cf"][0] == 0.0, (
                f"{board}: #e4e3cf ships at metalness {finishes['#e4e3cf'][0]}")


# --- the manifest boards, composed from their rows (OH-180) --------------------


def _manifest_specs():
    """Each `tools/board_manifest.py` row's composition, row first."""
    from tools import board_manifest

    by_board = {spec.board: spec for spec in compose.COMPOSITIONS}
    return [(row, by_board.get(row.board)) for row in board_manifest.ROWS]


def _preview(path: pathlib.Path, name: str) -> str:
    """One `<mfgpreviewcolor>` of an EAGLE board file, as EAGLE writes it."""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    found = root.findall(f".//mfgpreviewcolors/mfgpreviewcolor[@name='{name}']")
    assert len(found) == 1, f"{path.name} states {name} {len(found)} times"
    return found[0].get("color")


def _plain_notes(path: pathlib.Path) -> list[str]:
    """The words on the board file's own documentation layer, 51 (tDocu)."""
    import xml.etree.ElementTree as ET

    board = ET.parse(path).getroot().find("drawing/board")
    return [text.text or "" for text in board.findall("plain/text")
            if text.get("layer") == "51"]


def test_every_manifest_row_is_composed_from_that_row():
    """**A row already names the board file and the pads**, so the
    composition is derived from it rather than written out a second time --
    and the model is centred on the very elements the row builds the pad map
    from, so the two cannot disagree about where the middle of the board is.
    """
    from tools import board_manifest

    for row, spec in _manifest_specs():
        if row.board in compose.MANIFEST_REFUSED:
            assert spec is None, f"{row.board} is refused and composed at once"
            continue
        assert spec is not None, (
            f"{row.board} is a row in tools/board_manifest.py and is neither "
            f"composed nor refused, so the page draws its footprint silently"
        )
        assert spec.layout == board_manifest.cad_path(row), row.board
        assert spec.headers == row.select, (
            f"{row.board}: the model is centred on {spec.headers} and the pad "
            f"map is built from {row.select}"
        )
        assert spec.fetch_with.endswith(f"get_board_sources.py {row.source}"), (
            row.board)


def test_a_package_two_libraries_share_is_told_apart_by_the_library():
    """SparkFun's `0603` is a resistor from one library and a capacitor from
    another, under one package name. A table keyed by package alone draws
    all twenty-three as one of them; the library is the vendor saying which.
    """
    def placed(library: str, package: str) -> eagle.Element:
        return eagle.Element(
            "X1", library, package,
            pads=(eagle.Pad("1", "smd", -0.85, 0.0, 1.1, 1.0, None),
                  eagle.Pad("2", "smd", 0.85, 0.0, 1.1, 1.0, None)))

    resistor = compose.correspondence_for(placed("SparkFun-Resistors", "0603"))
    capacitor = compose.correspondence_for(placed("SparkFun-Capacitors", "0603"))
    assert resistor is not None and resistor.model == "R_0603_1608Metric"
    assert capacitor is not None and capacitor.model == "C_0603_1608Metric"
    assert compose.correspondence_for(placed("somebody-else", "0603")) is None, (
        "no row for 0603 names no library, so a third library's 0603 is a "
        "part nobody has matched yet"
    )
    # A row that names no library answers for every library's copy.
    for library in ("SparkFun-IC-Power", "adafruit_power", "microbuilder"):
        row = compose.correspondence_for(placed(library, "SOT23-5"))
        assert row is not None and row.model == "SOT-23-5", library


def test_a_manufacturers_model_sits_where_its_own_footprint_puts_its_pads(
        monkeypatch, tmp_path):
    """`pads_origin` is the one new number in placing a module, so it is
    checked against a footprint whose answer is known by hand: pads centred
    on (0, -2) in KiCad's down-the-page frame, and the model offset by
    (-3, -4), put the middle of the pads at (3, 6) in the model's own frame.
    """
    monkeypatch.setattr(compose, "CACHE", tmp_path)
    part = compose.Component(
        "PKG", "maker", "PART", "a test part, two 1 mm pads 2 mm apart",
        step="https://example.invalid/PART.STEP",
        footprint="https://example.invalid/PART.kicad_mod")
    local = compose.cached(part, part.footprint, ".kicad_mod")

    def footprint(rotate: str) -> str:
        return (
            '(footprint "PART"\n'
            '  (pad "1" smd rect (at -1 -2) (size 1 1) (layers "F.Cu"))\n'
            '  (pad "2" smd rect (at 1 -2) (size 1 1) (layers "F.Cu"))\n'
            '  (model "${X}/maker.3dshapes/PART.STEP"\n'
            '    (offset (xyz -3 -4 0)) (scale (xyz 1 1 1))\n'
            f'    (rotate (xyz {rotate}))))\n')

    local.write_text(footprint("0 0 0"), encoding="utf-8")
    assert compose.pads_origin(part) == pytest.approx((3.0, 6.0))

    # A block that also TURNS the model is refused, not read as an offset.
    local.write_text(footprint("0 0 90"), encoding="utf-8")
    with pytest.raises(SystemExit, match="turns or scales"):
        compose.pads_origin(part)

    # And a part from KiCad's own library keeps the anchor it always had.
    kicad_part = dataclasses.replace(part, step=None, footprint=None)
    assert compose.pads_origin(kicad_part) is None


def test_the_module_lands_on_the_body_its_vendor_drew():
    """**The guard, on the real module**: SparkFun draw the WROOM-1's body
    three millimetres off the middle of its pads, towards the antenna, and
    Espressif's own footprint puts its model there too. Anchored the old
    way -- the body's middle on the pads' -- it misses SparkFun's drawing by
    that much, which `silk_miss` refuses; anchored by `pads_origin` it lands.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Thing Plus ESP32-C6")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    module = board.element("U1")
    component = compose.correspondence_for(module)
    step = compose.cached(component, component.url, ".step")
    if not step.is_file():
        pytest.skip("SKIPPED: the module's STEP is not fetched; run "
                    "tools/compose_board_3d.py")
    pads = [pad for name in spec.headers for pad in board.element(name).pads]
    centre = ((min(p.x_mm for p in pads) + max(p.x_mm for p in pads)) / 2,
              (min(p.y_mm for p in pads) + max(p.y_mm for p in pads)) / 2)
    mesh, _box = compose.component_mesh(component, compose.DEFLECTION)
    assert isinstance(mesh, compose.OverPads), (
        "the module arrives without where its own pads are"
    )

    placed = compose.place(mesh, module, component.turn, spec.thickness_mm,
                           centre)
    assert compose.silk_miss(module, placed, centre) < 0.5
    # The same triangles as a plain mesh: anchored the old way.
    centred = compose.place(compose.Mesh(mesh.groups), module, component.turn,
                            spec.thickness_mm, centre)
    assert compose.silk_miss(module, centred, centre) > compose.SILK_TOLERANCE_MM, (
        "centred on its pads the module should miss SparkFun's drawing of it; "
        "if it does not, `pads_origin` is doing nothing this test can see"
    )


def test_a_manifest_boards_colour_is_read_where_its_file_states_one():
    """**The colour is the vendor's where their file states one, and a
    judgement where it does not -- and which is which is read, not
    remembered.** EAGLE writes a manufacturing-preview solder mask into
    every board file whether anybody chose one or not. The Arduino Uno's
    file carries one under a board this table draws navy from PICSimLab's
    own artwork, so that value is what nobody choosing looks like; a board
    drawn in `BOARD_MASK` must carry it, and a board drawn in anything else
    must not, and must be drawn in what its file states.
    """
    uno = _brd()
    unset = _preview(uno, "soldermaskcolor")
    checked = 0
    for row, spec in _manifest_specs():
        if spec is None or not spec.layout.is_file():
            continue
        checked += 1
        if spec.layout.suffix == ".kicad_pcb":
            # KiCad's stackup names the top mask and the dielectric under it
            # (OH-195), read here by pattern rather than through the
            # composer's own reader, and drawn as KiCad's 3D view lays one
            # over the other.
            text = spec.layout.read_text(encoding="utf-8")
            named = re.search(r'\(layer "F\.Mask"\s*\(type "[^"]*"\)'
                              r'(?:\s*\([^()]*\))*?\s*\(color "([^"]+)"\)', text)
            if named is None:
                assert spec.colour == compose.BOARD_MASK, row.board
                continue
            cores = re.findall(r'\(layer "dielectric \d+"\s*\(type "[^"]*"\)'
                               r'(?:\s*\([^()]*\))*?\s*\(color "([^"]+)"\)', text)
            under = compose.KICAD_BOARD_COLOURS[
                cores[0] if len(set(cores)) == 1 else "FR4 natural"]
            stated = named.group(1)
            if stated in compose.KICAD_MASK_COLOURS:
                rgb, alpha = compose.KICAD_MASK_COLOURS[stated]
            else:
                rgb = tuple(int(stated[at:at + 2], 16) for at in (1, 3, 5))
                alpha = int(stated[7:9], 16) / 255 if len(stated) == 9 else 1.0
            assert spec.colour == _over(rgb, alpha, under), (row.board, spec.colour)
            assert stated in spec.colour_source, row.board
            assert "A JUDGEMENT" in spec.colour_source, row.board
            continue
        stated = _preview(spec.layout, "soldermaskcolor")
        if spec.colour == compose.BOARD_MASK:
            assert stated == unset, (
                f"{row.board} is drawn in BOARD_MASK and its file states a "
                f"mask of {stated}; read it"
            )
            assert stated in spec.colour_source, row.board
            continue
        assert stated != unset, (
            f"{row.board} is drawn in {spec.colour} and its file states only "
            f"EAGLE's unset {unset}"
        )
        # ARGB, drawn as EAGLE's preview draws it: over the file's own
        # substrate at the stated alpha.
        substrate = _preview(spec.layout, "substratecolor")
        alpha = int(stated[2:4], 16) / 255
        drawn = "#" + "".join(
            f"{round(int(stated[at:at + 2], 16) * alpha + int(substrate[at:at + 2], 16) * (1 - alpha)):02x}"
            for at in (4, 6, 8))
        assert spec.colour == drawn, (
            f"{row.board}: its file states {stated} over {substrate}, which "
            f"draws {drawn}, and the composition says {spec.colour}"
        )
        # Every figure the source quotes is the file's, read here.
        for quoted in (stated, unset, f"0x{stated[4:]}", f"0x{substrate[4:]}",
                       f"alpha {int(stated[2:4], 16)}/255"):
            assert quoted in spec.colour_source, (
                f"{row.board}: the colour source does not say {quoted}, which "
                f"is what the files read"
            )
        # And the words the source quotes are on the board's own note.
        said = [line.strip() for note in _plain_notes(spec.layout)
                for line in note.splitlines() if line.startswith("Soldermask:")]
        assert said and all(f"'{line}'" in spec.colour_source for line in said), (
            f"{row.board}: the note reads {said}, and the colour source "
            f"quotes something else"
        )
    if not checked:
        pytest.skip("SKIPPED: no manifest board is fetched")


def test_a_manifest_boards_thickness_is_its_own_note_or_the_unos_stack():
    """1.6 mm is the Uno's reused assumption, and it is only honest where the
    board file states nothing better. An EAGLE file's design rules carry a
    layer stack, and where it is the stack the Uno's own file carries it is
    EAGLE's and nobody's statement; where a board's note states a
    thickness, that is the number drawn.
    """
    import xml.etree.ElementTree as ET

    def stack(path: pathlib.Path) -> dict[str, str]:
        rules = ET.parse(path).getroot().find("drawing/board/designrules")
        return {param.get("name"): param.get("value")
                for param in rules.findall("param")
                if param.get("name") in ("mtCopper", "mtIsolate")}

    uno = stack(_brd())
    checked = 0
    for row, spec in _manifest_specs():
        if spec is None or not spec.layout.is_file():
            continue
        checked += 1
        if spec.layout.suffix == ".kicad_pcb":
            # Its stackup and `(general (thickness))`, two statements that
            # decide only where they agree (OH-195).
            _mask, layers, general, _core = compose.kicad_stackup(spec.layout)
            agree = (layers is not None and general is not None
                     and abs(layers - general) < 5e-4)
            assert spec.thickness_mm == (
                general if agree else compose.MANIFEST_THICKNESS_MM), row.board
            continue
        stated = "thickness_mm" in compose.MANIFEST_STATED.get(row.board, {})
        if not stated:
            assert spec.thickness_mm == _uno().thickness_mm, (
                f"{row.board} states no thickness and is not drawn at the "
                f"Uno's, which is the assumption it claims to reuse"
            )
            assert stack(spec.layout) == uno, (
                f"{row.board}'s design rules carry a stack of their own; "
                f"read its thickness rather than assuming the Uno's"
            )
            continue
        notes = " ".join(_plain_notes(spec.layout))
        assert f"Board thickness: {spec.thickness_mm:g}mm" in notes, (
            f"{row.board} is drawn {spec.thickness_mm} mm thick and its "
            f"note does not say so"
        )
    if not checked:
        pytest.skip("SKIPPED: no manifest board is fetched")


def test_every_placement_is_drawn_refused_or_padless_and_counted(capsys):
    """Every element of a board is accounted for exactly once, and the
    refusals are counted in the output, not only listed.

    Run with nothing matched, so no model is fetched or tessellated: every
    element with a pad is then either refused by `ABSENT` or unmodelled, and
    one with no pad at all -- a logo, a pin label -- is neither, because
    nothing is soldered there for a part to stand on. SparkFun's file places
    63 pin labels, each its own package, which is why that is a count and
    not an `ABSENT` entry apiece.
    """
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "Adafruit QT Py ESP32-C3")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    # A part its own schematic refuses is refused whatever the table holds
    # (OH-187), and counted there alone.
    statements = compose.statements_for(spec)
    off = [e for e in board.elements
           if e.name in statements and statements[e.name].refused]
    padless = [e for e in board.elements if not e.pads and e not in off]
    absent = [e for e in board.elements
              if e.package in compose.ABSENT and e not in off]
    rest = [e for e in board.elements if e.pads and e.package not in compose.ABSENT
            and e not in off]
    assert padless and absent and rest, "the board no longer shows all three"
    # **A refused part and a bodyless pad are counted apart**, and which is
    # which on this board is written here rather than derived, so a reason
    # that loses its "no body" words -- or gains them -- is caught.
    parts = {"USB_C_CUSB31-CFM2AX-01-X", "SK6805_1515"}
    refused = [e for e in absent if e.package in parts]
    bodyless = [e for e in absent if e.package not in parts]
    assert {e.package for e in bodyless} == {
        "1X07_CASTEL", "B1,27", "FIDUCIAL_1MM", "TESTPOINT_MINUS_1X3MM",
        "TESTPOINT_PLUS_1X3MM"}

    with mock.patch.object(compose, "CORRESPONDENCE", ()):
        compose.compose(spec, deflection=0.05, check=True)
    out = capsys.readouterr().out
    assert f"no pads {len(padless)} placement(s)" in out, out
    assert f"no model {len(rest)} placement(s)" in out, out
    assert (f"refused {len(refused) + len(off)} placement(s): {len(refused)} of "
            f"{len(parts)} package(s) with no published model, and {len(off)} "
            f"by what their own schematic states") in out, out
    # Every pad of every one of them is drawn, so each is counted drawn, as
    # its copper, and none of them as absent (OH-163).
    assert (f"copper  {len(bodyless)} placement(s) of "
            f"{len({e.package for e in bodyless})} package(s)") in out, out
    assert "bodyless" not in out, out
    assert (len(padless) + len(absent) + len(rest) + len(off)
            == len(board.elements))


# --- what was reported absent and is not a part (OH-163 step 3) -------------


def _xiao_layouts():
    """The five KiCad XIAOs, one composition per board file -- an SMD
    variant composes its DIP sibling's PCB (OH-118) -- skipping the run by
    name where none is fetched, and needing the font a XIAO's text is
    lettered in."""
    _newstroke()
    specs = [spec for spec in compose.COMPOSITIONS
             if spec.board.startswith("XIAO-") and spec.dip_headers
             and spec.layout.is_file()]
    if not specs:
        pytest.skip("SKIPPED: no XIAO board file is fetched; run "
                    "python tools/compose_board_3d.py")
    return specs


def _accounting(spec, capsys) -> str:
    """What `compose --check` prints of one board with no model matched: its
    placements counted, with no mesh fetched or tessellated."""
    with mock.patch.object(compose, "CORRESPONDENCE", ()):
        compose.compose(spec, deflection=0.05, check=True)
    return capsys.readouterr().out


#: Seeed's test points on the KiCad XIAOs, by package: a bare pad each on the
#: underside, and no body.
XIAO_TEST_POINTS = frozenset({"TP-D45MIL", "TP-80X40MIL", "TP-1.6MM-ROUND"})


def test_a_test_point_is_drawn_as_its_pad_and_not_also_reported_absent(capsys):
    """**A test point is its pad, and the copper pass draws the pad** (OH-110),
    so naming it among the absent as well was a double report (OH-163): its
    copper on the board, and the test point listed as missing beside it.

    Held on the copper first -- every corner of every test point's pad is a
    vertex of the copper drawn on that pad's own face -- then on the count,
    which names each package as drawn copper and none on an `absent` line;
    and on the composed `.glb`, whose `absent` no longer lists them."""
    from tools.import_3d_model import read_extras

    for spec in _xiao_layouts():
        board = compose.read_layout(spec.layout)
        points = [e for e in board.elements if e.package in XIAO_TEST_POINTS]
        assert points, f"{spec.board} places none of {sorted(XIAO_TEST_POINTS)}"
        ring, _cut = compose.outer(board.outline)
        meshes, *_ = compose.artwork(board, ring, spec.thickness_mm, (0.0, 0.0),
                                     spec.colour, [])
        copper: dict[float, set[tuple[float, float]]] = {}
        for mesh in meshes:
            for colour, (p, _n, _i) in mesh.groups.items():
                if colour != compose.COPPER:
                    continue
                for at in range(0, len(p), 3):
                    copper.setdefault(round(p[at + 1], 4), set()).add(
                        (round(p[at], 4), round(-p[at + 2], 4)))
        for element in points:
            for pad in element.pads:
                face = round(-compose.COPPER_THICKNESS_MM if pad.back else
                             spec.thickness_mm + compose.COPPER_THICKNESS_MM, 4)
                corners = {(round(x, 4), round(y, 4))
                           for x, y in compose.pad_outline(pad)}
                assert corners <= copper.get(face, set()), (
                    f"{spec.board}: {element.name}'s pad is not drawn as copper")

        packages = {e.package for e in points}
        lines = _accounting(spec, capsys).splitlines()
        named = [line for line in lines if line.startswith("  absent  ")
                 and any(f"({package})" in line for package in packages)]
        assert not named, (spec.board, named)
        drawn = next((line for line in lines if line.startswith("  copper  ")), "")
        assert packages <= set(drawn.partition(": ")[2].split(", ")), (
            spec.board, drawn)

        glb = REPO / "webui" / "static" / "models" / f"{compose._slug(spec.board)}.glb"
        if glb.is_file():
            extras = read_extras(glb)
            assert not packages & {entry["package"] for entry in extras["absent"]}, (
                f"{glb.name} still lists its test points absent; recompose")
            assert packages <= {entry["package"] for entry in extras.get("copper", [])}


def test_a_placement_with_an_unplated_hole_is_not_counted_drawn(capsys):
    """**Its copper is not all of it** (OH-163): an unplated hole is a hole,
    which the copper pass does not cut -- it reaches `artwork` as a surface
    pad, see `eagle.Pad.hole` -- so a placement with no body that puts one
    down stays among the absent, saying that its hole is not drawn, and is
    not counted drawn as its copper. Olimex's mounting holes and SparkFun's
    standoffs are that."""
    _newstroke()
    checked = []
    for spec in compose.COMPOSITIONS:
        if spec.layout.suffix != ".kicad_pcb" or not _fetched(spec):
            continue
        holed = {e.package for e in compose.read_layout(spec.layout).elements
                 if any(pad.hole for pad in e.pads)
                 and compose.NO_BODY in (compose.absent_why(e) or "")}
        if not holed:
            continue
        lines = _accounting(spec, capsys).splitlines()
        drawn = next((line for line in lines if line.startswith("  copper  ")), "")
        assert not holed & set(drawn.partition(": ")[2].split(", ")), (spec.board, drawn)
        for package in holed:
            assert any(line.startswith("  absent  ") and f"({package}): " in line
                       and " not drawn: an unplated hole, and no hole is cut" in line
                       for line in lines), (spec.board, package, lines)
        checked.append(spec.board)
    if not checked:
        pytest.skip("SKIPPED: no fetched board places a bodyless unplated hole")


def test_a_logo_is_ink_and_not_a_part_left_off(capsys):
    """**A footprint that puts down no pad has nothing soldered to it**, so
    it is no part, whatever `ABSENT` holds (OH-163): Seeed's logos are that,
    and each was reported absent beside its own ink. The board file is what
    says so -- no pad -- and each is counted on the no-pads line, its ink
    stroke by stroke on the artwork and `not ink` lines.

    And where the file carries a logo's ink as strokes, it is drawn: the CE
    mark's outline is a run of arcs, which the silkscreen reader counted
    and dropped and now reads, so no arc of any XIAO's silkscreen is left
    unread and each is drawn as the strokes `arc_points` flattens it to.
    Last, no `ABSENT` reason is for a package any fetched board places with
    no pad: `compose` could never print one."""
    for spec in _xiao_layouts():
        board = compose.read_layout(spec.layout)
        padless = [e for e in board.elements if not e.pads]
        assert padless, f"{spec.board} places no logo"
        out = _accounting(spec, capsys)
        assert f"  no pads {len(padless)} placement(s)" in out, out
        absent = [line for line in out.splitlines() if line.startswith("  absent  ")]
        for element in padless:
            assert not any(f"({element.package})" in line for line in absent), (
                spec.board, element.package)

        read = kicad.read_board(spec.layout)
        assert "arc" not in dict(read.silk_unread), (spec.board, read.silk_unread)
        flattened = sum(len(compose.arc_points(arc)) - 1 for arc in read.silk_arcs)
        assert len(board.silk) == len(read.silk) + flattened, spec.board
        if spec.pcb_chip == "nRF54L15":
            assert any(arc.layer == "B.SilkS" for arc in read.silk_arcs), (
                "the CE mark's arcs, on the underside, are not read")

    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            continue
        dead = {e.package for e in compose.read_layout(spec.layout).elements
                if not e.pads and not e.models and compose.absent_why(e) is not None}
        assert not dead, (spec.board, dead)


def test_the_composed_silkscreen_arcs_land_on_seeeds_own_gerber():
    """**The arcs of ink reach the composed board where Seeed plotted them**
    (OH-163, from step 3's review). Each silkscreen arc `from_kicad`
    flattens is a run of strokes in the composer's own frame, y up -- which,
    Seeed plotting from a zero origin, IS the Gerber's frame -- and each run
    goes from one end of a circular draw of its own layer's Gerber, through
    its sweep, to the other, on the XIAO ESP32-C6. Only a count of those
    strokes held them before, and a flattening that left y as KiCad stores
    it, down the page, drew every arc of ink mirrored off the board and
    passed."""
    import zipfile

    from tests.rules.test_kicad import (
        SEEED_C6_ROOT,
        SEEED_PCB,
        _arc_lands,
        _gerber_draws,
    )

    zipped, path = SEEED_PCB / "ESP32-C6.zip", SEEED_PCB / "ESP32-C6.kicad_pcb"
    if not (zipped.is_file() and path.is_file()):
        pytest.skip(f"SKIPPED: {zipped.name} or {path.name} absent under {SEEED_PCB}; "
                    f"python tools/compose_board_3d.py --board XIAO-ESP32-C6-DIP")
    plotted: dict[str, list] = {}
    with zipfile.ZipFile(zipped) as bundle:
        assert path.read_bytes() == bundle.read(SEEED_C6_ROOT + "XIAO ESP32 C6.kicad_pcb"), (
            "not the board Seeed plotted these from")
        for layer, name in (("F.SilkS", "F_Silkscreen"), ("B.SilkS", "B_Silkscreen")):
            plotted[layer] = []
            _gerber_draws(bundle.read(f"{SEEED_C6_ROOT}XIAO ESP32 C6_gerber/"
                                      f"XIAO ESP32 C6-{name}.gbr").decode("ascii"),
                          f"{path.name} {layer}", plotted[layer])
    read = kicad.read_board(path)
    rest = compose.from_kicad(path).silk[len(read.silk):]
    missed = []
    for arc in read.silk_arcs:
        steps = len(compose.arc_points(arc)) - 1
        run, rest = rest[:steps], rest[steps:]
        middle = run[steps // 2]
        if not (all(stroke.layer == arc.layer for stroke in run)
                and _arc_lands(plotted[arc.layer], (run[0].x1_mm, run[0].y1_mm),
                               (middle.x1_mm, middle.y1_mm), (run[-1].x2_mm, run[-1].y2_mm))):
            missed.append((arc, run[0], run[-1]))
    assert read.silk_arcs and not rest and not missed, (len(rest), missed[:3])


def test_a_test_point_beyond_the_outline_stays_absent_and_says_why(capsys):
    """**A placement is drawn as its copper only where every pad of it is
    drawn** (OH-163, from step 3's review). The Uno's ORIGIN is a test point
    whose pad reaches outside the board's concave outline, which the copper
    pass cuts nothing to, so the pad is not drawn and ORIGIN stays among the
    absent -- saying that, and not its package's reason, which is about the
    test points whose pads are drawn. Those are counted drawn, as copper."""
    spec = next(s for s in compose.COMPOSITIONS if s.board == "Arduino Uno")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    points = [e for e in compose.read_layout(spec.layout).elements if e.package == "TP-SP"]
    origin = next(e for e in points if e.name == "ORIGIN")
    assert len(points) > 1 and len(origin.pads) == 1, (len(points), origin.pads)
    lines = _accounting(spec, capsys).splitlines()
    assert (f"  absent  ORIGIN (TP-SP): pad {origin.pads[0].number} not drawn: "
            f"reaching outside the board's concave outline, which nothing is cut "
            f"to") in lines, lines
    drawn = next((line for line in lines if line.startswith("  copper  ")), "")
    assert "TP-SP" in drawn.partition(": ")[2].split(", "), drawn


def test_an_unplated_hole_is_not_drawn_as_copper():
    """**A hole with no copper in it is drawn as no copper** (OH-163, from
    step 3's review). A KiCad `np_thru_hole` reaches `artwork` as a surface
    pad -- see `eagle.Pad.hole` -- and was drawn on both faces as a disc of
    copper its drill's size: the locating pegs of the USB-C sockets, buttons
    and switches, Olimex's mounting holes, SparkFun's standoffs. Now no
    corner of any such hole is a vertex of the copper, and each is counted
    under `np_thru_hole`."""
    checked = []
    for spec in compose.COMPOSITIONS:
        if (spec.layout.suffix != ".kicad_pcb" or not spec.layout.is_file()
                or spec.layout in {seen for seen, _board in checked}):
            continue
        board = compose.read_layout(spec.layout)
        holes = [pad for e in board.elements for pad in e.pads if pad.hole]
        if not holes:
            continue
        ring, _cut = compose.outer(board.outline)
        meshes, tally, _undrawn = compose.artwork(board, ring, spec.thickness_mm,
                                                  (0.0, 0.0), spec.colour, [])
        copper = {(round(p[at], 4), round(-p[at + 2], 4))
                  for mesh in meshes for colour, (p, _n, _i) in mesh.groups.items()
                  if colour == compose.COPPER for at in range(0, len(p), 3)}
        drawn = [pad for pad in holes
                 if {(round(x, 4), round(y, 4)) for x, y in compose.pad_outline(pad)} & copper]
        assert not drawn, (spec.board, drawn[:3])
        assert tally.get("np_thru_hole") == len(holes), (spec.board, tally)
        checked.append((spec.layout, spec.board))
    if not checked:
        pytest.skip("SKIPPED: no fetched KiCad board places an unplated hole")


def test_a_flattened_arc_stands_off_its_circle_by_no_more_than_its_chord_allows():
    """**The price of `ARC_CHORD_MM`, as its comment states it** (OH-163,
    from step 3's review, now that the silkscreen's arcs are flattened too):
    no chord `arc_points` draws stands off its circle by more than
    r(1 - cos(min(chord / 2r, pi / 2))). Swept over radii from below
    chord / pi, where two steps round a circle are its diameter, to well
    above a XIAO's corner, and over sweeps either way round.

    Each step's angle t is measured from its chord, 2 asin(c / 2r), which
    cannot exceed a half turn -- so the angles summing to the whole sweep is
    what shows no step is more than one -- and the step stands off its arc
    by r(1 - cos(t/2))."""
    worst = 0.0
    for radius in (0.03, 0.0637, 0.1, 0.254, 0.5, 1.5, 10.0):
        for sweep in (5.0, 45.0, 90.0, 180.0, 270.0, 359.0, -90.0, -300.0):
            half = math.radians(sweep) / 2
            arc = kicad.Arc("F.SilkS", radius, 0.0,
                            radius * math.cos(half), radius * math.sin(half),
                            radius * math.cos(2 * half), radius * math.sin(2 * half))
            points = compose.arc_points(arc)
            steps = [2 * math.asin(min(1.0, math.dist(a, b) / (2 * radius)))
                     for a, b in itertools.pairwise(points)]
            assert sum(steps) == pytest.approx(abs(2 * half), abs=1e-9), (radius, sweep, steps)
            bound = radius * (1 - math.cos(min(compose.ARC_CHORD_MM / (2 * radius),
                                                math.pi / 2)))
            for step in steps:
                gap = radius * (1 - math.cos(step / 2))
                assert gap <= bound + 1e-12, (radius, sweep, gap, bound)
                worst = max(worst, gap / bound)
    assert worst > 0.9, f"the bound is never approached ({worst:.3f}), so it holds nothing"


def _edge_footprint(reference: str, at: str, cuts: str) -> str:
    """One footprint with one pad, drawing `cuts` on Edge.Cuts."""
    return (f'\t(footprint "Test:{reference}"\n\t\t(layer "F.Cu")\n\t\t(at {at})\n'
            f'\t\t(property "Reference" "{reference}" (at 0 0 0) (layer "F.SilkS"))\n'
            f'{cuts}\t\t(pad "1" smd rect (at 0 3) (size 1 1) (layers "F.Cu"))\n\t)\n')


def _cut(kind: str, x1: float, y1: float, x2: float, y2: float) -> str:
    """One straight piece of Edge.Cuts: a `*_line`, or a `*_rect`'s corners."""
    return (f'\t\t({kind} (start {x1} {y1}) (end {x2} {y2}) '
            f'(stroke (width 0.05) (type solid)) (layer "Edge.Cuts"))\n')


#: Three 20 x 10 mm boards, which differ in which footprint draws what on
#: Edge.Cuts (OH-163). `RING`: U2 draws the whole rectangle, and J1 beside it
#: cuts a 2 x 0.6 mm slot. `NOTCHED`: the rectangle is drawn at the top level
#: but for 4 mm of its top edge, which J2 closes with a 1 mm deep notch.
#: `RING_AND_SLOT`: U3 draws the rectangle and a slot inside it, both.
RING = ("(kicad_pcb\n\t(version 20241229)\n"
        + _edge_footprint("U2", "0 0", _cut("fp_rect", 0, 0, 20, 10))
        + _edge_footprint("J1", "10 5", _cut("fp_rect", -1, -0.3, 1, 0.3)) + ")\n")
NOTCHED = ("(kicad_pcb\n\t(version 20241229)\n"
           + "".join(_cut("gr_line", *ends) for ends in (
               (0, 0, 8, 0), (12, 0, 20, 0), (20, 0, 20, 10), (20, 10, 0, 10),
               (0, 10, 0, 0)))
           + _edge_footprint("J2", "10 0", _cut("fp_line", -2, 0, -2, 1)
                             + _cut("fp_line", -2, 1, 2, 1) + _cut("fp_line", 2, 1, 2, 0))
           + ")\n")
RING_AND_SLOT = ("(kicad_pcb\n\t(version 20241229)\n"
                 + _edge_footprint("U3", "0 0", _cut("fp_rect", 0, 0, 20, 10)
                                   + _cut("fp_rect", 9, 4.7, 11, 5.3)) + ")\n")


def test_only_a_footprint_whose_edge_cuts_is_the_outer_ring_is_the_board(tmp_path):
    """**A footprint's Edge.Cuts is the board only where it IS the board's
    outer ring** (OH-163, from step 3's review). Every footprint that drew
    anything there was taken for the board, so a connector cutting a slot
    for itself, with no model, was printed as the board's edge and counted
    nowhere else. By hand, on the three boards above:

      * U2 draws the whole rectangle, and is the board. J1, a part with a
        pad, cuts a slot inside it: still a part, its slot a cutout.
      * J2 closes the top-level outline with a notch, so every one of its
        segments is a side of the outer ring -- and it is still a part. A
        part of the ring is not the ring.
      * U3 draws the ring and a slot: not the ring alone, so not taken for
        the board. It is then a placement with pads like any other, which
        is counted and seen rather than passed over as the board.
    """
    got = {}
    for name, text in (("ring", RING), ("notched", NOTCHED),
                       ("ring-and-slot", RING_AND_SLOT)):
        path = tmp_path / f"{name}.kicad_pcb"
        path.write_text(text, encoding="utf-8")
        got.update({e.name: e.edge for e in compose.from_kicad(path).elements})
    assert got == {"U2": True, "J1": False, "J2": False, "U3": False}


def test_a_part_that_cuts_a_slot_for_itself_is_still_a_part(tmp_path, capsys):
    """**Step 3's review, kept as a test** (OH-163): a closed 0.6 mm square
    slot on Edge.Cuts added inside the XIAO ESP32-C3's USB-C footprint, in
    a copy of Seeed's file, put the socket on the `edge` line -- the board,
    counted nowhere else -- when no model is matched for it. Now it stays a
    placement with no model, counted as one, and its slot is one more cutout.
    """
    spec, shipped = _the_c3s_accounting(capsys)
    slotted = _accounting(_c3_with(spec, tmp_path, "USB2.0-TYPE-C", "\n" + _cut(
        "fp_rect", -0.3, -0.3, 0.3, 0.3)), capsys).splitlines()
    assert not [line for line in slotted if line.startswith("  edge")], slotted
    assert _counted(slotted, "  no model") == _counted(shipped, "  no model") != "", (
        _counted(slotted, "  no model"), _counted(shipped, "  no model"))
    assert _counted(shipped, "  cutouts").startswith("  cutouts 2 ")
    assert _counted(slotted, "  cutouts").startswith("  cutouts 3 "), slotted


def test_a_placement_with_no_pad_that_states_a_mesh_is_a_part(tmp_path, capsys):
    """**No pad is not enough to make a placement ink** (OH-163, from step
    3's review): one that states a mesh claims a body, so it is counted as a
    part -- here, with no model matched, on the `no model` line -- and not
    on the `no pads` line a logo is counted on. Shown on copies of the XIAO
    ESP32-C3's file, whose one padless placement, Seeed's logo, is given a
    `(model ...)`; and given a hidden one, KiCad's own "an alternate, not
    this part", it is ink again. With an `ABSENT` reason for its package, it
    is counted absent by that reason, as any part with no published model."""
    spec, shipped = _the_c3s_accounting(capsys)
    assert _counted(shipped, "  no pads") == "  no pads 1", shipped
    model = '\n\t\t(model "${KICAD9_3DMODEL_DIR}/Test.3dshapes/Test.step"%s)\n'
    logo = "LOGO-SEEED-NEW-1X9.6MM"
    stated = _accounting(_c3_with(spec, tmp_path, logo, model % ""), capsys).splitlines()
    hidden = _accounting(_c3_with(spec, tmp_path, logo, model % " (hide yes)"),
                         capsys).splitlines()
    unmodelled = int(_counted(shipped, "  no model").split()[-1])
    assert _counted(stated, "  no pads") == "", stated
    assert _counted(stated, "  no model") == f"  no model {unmodelled + 1}", stated
    assert _counted(hidden, "  no pads") == "  no pads 1", hidden
    assert _counted(hidden, "  no model") == f"  no model {unmodelled}", hidden
    with mock.patch.dict(compose.ABSENT, {logo: "a part nobody publishes a model of"}):
        reasoned = _accounting(_c3_with(spec, tmp_path, logo, model % ""), capsys)
    assert f"  absent  U$2 ({logo}): a part nobody publishes a model of..." in reasoned, (
        reasoned)
    # And a reason saying there is no body contradicts the mesh the file
    # states: refused with both, never printed as copper whose every pad --
    # of none -- is drawn.
    with mock.patch.dict(compose.ABSENT, {logo: f"a mark: {compose.NO_BODY}"}):
        with pytest.raises(ValueError, match=r"U\$2 .*has no pad and states a mesh"):
            _accounting(_c3_with(spec, tmp_path, logo, model % ""), capsys)


def _the_c3s_accounting(capsys):
    """The XIAO ESP32-C3's composition and what `_accounting` prints of it,
    skipping where its file or the font its text is lettered in is absent."""
    _newstroke()
    spec = next(s for s in compose.COMPOSITIONS if s.board == "XIAO-ESP32-C3-DIP")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched; {spec.fetch_with}")
    return spec, _accounting(spec, capsys).splitlines()


def _c3_with(spec, tmp_path, package: str, inserted: str):
    """`spec` composing a copy of the C3's file with `inserted` written into
    the one footprint of `package`, just after its name."""
    text = spec.layout.read_text(encoding="utf-8")
    marker = f'(footprint "XIAO ESP32C3_v1.3:{package}"'
    assert text.count(marker) == 1, f"{spec.layout.name} places {text.count(marker)} {marker}"
    at = text.index(marker) + len(marker)
    copy = tmp_path / package / spec.layout.name
    copy.parent.mkdir(exist_ok=True)
    copy.write_text(text[:at] + inserted + text[at:], encoding="utf-8")
    return dataclasses.replace(spec, layout=copy)


def _counted(lines: list[str], start: str) -> str:
    """The first line beginning `start`, up to its count, or `""`."""
    return next((line for line in lines if line.startswith(start)), "").split(" placement")[0]


def test_the_footprint_drawing_the_boards_edge_is_the_board_and_not_a_placement(capsys):
    """**KiCad mills a footprint's `Edge.Cuts` as it mills the board's own**,
    so a footprint whose Edge.Cuts is the board's whole silhouette is the
    board (OH-163): Seeed's module outline is a XIAO's, its pads the
    castellations, and it was reported absent as though a part were missing
    from it.

    Which footprints draw the edge is read out of the file here, not named,
    and by a different measure from `from_kicad`'s: the outline a footprint
    carries reaches the board's own extent on all four sides. The kinds are
    the reader's -- a line, a rectangle, an arc -- and no footprint on a
    XIAO draws any other kind there, which is checked rather than assumed.
    Each is printed as the board's edge and counted nowhere else, and each
    is still the header element the page lands a board file's pads on. The
    ESP32-C3 draws its silhouette at the top level, so on it none is."""
    seen = []
    flagged = []
    for spec in _xiao_layouts():
        tree = kicad.board_tree(spec.layout)
        kinds = {kicad.head(child) for node in kicad.children(tree, "footprint")
                 for child in node if isinstance(child, list)
                 and kicad.first(child, "layer") == ["layer", "Edge.Cuts"]}
        assert kinds <= {"fp_line", "fp_rect", "fp_arc"}, (spec.board, kinds)
        read = kicad.read_board(spec.layout)
        extent = read.extent_mm()
        carrying = set()
        for placed in read.placements:
            xs = ([v for s in placed.outline for v in (s.x1_mm, s.x2_mm)]
                  + [v for a in placed.arcs for v in (a.x1_mm, a.xm_mm, a.x2_mm)])
            ys = ([v for s in placed.outline for v in (s.y1_mm, s.y2_mm)]
                  + [v for a in placed.arcs for v in (a.y1_mm, a.ym_mm, a.y2_mm)])
            if xs and all(abs(mine - whole) < compose.CHAIN_TOLERANCE_MM for mine, whole
                          in zip((min(xs), min(ys), max(xs), max(ys)), extent)):
                carrying.add(placed.reference)
        out = _accounting(spec, capsys)
        lines = out.splitlines()
        board = compose.read_layout(spec.layout)
        for element in board.elements:
            if element.name not in carrying:
                continue
            assert (f"  edge    {element.name} ({element.package}) draws the "
                    f"board's own outline") in out, out
            assert not [line for line in lines
                        if line.startswith(("  absent  ", "  copper  ", "  no model"))
                        and element.package in line], (spec.board, element.name)
            assert element.name in spec.headers, (spec.board, element.name)
            seen.append(f"{spec.board}: {element.name}")
        flagged.append((spec.board, board, carrying))
        # And the composed model records it, as it records every other
        # placement it does not draw as a part.
        glb = REPO / "webui" / "static" / "models" / f"{compose._slug(spec.board)}.glb"
        if glb.is_file():
            from tools.import_3d_model import read_extras

            assert read_extras(glb).get("edge") == [
                f"{e.name} ({e.package})" for e in board.elements if e.name in carrying], (
                f"{glb.name} does not record its edge placement; recompose")
    # And the flag the composer counts by is the file's own, board by board.
    for name, board, carrying in flagged:
        assert {e.name for e in board.elements if e.edge} == carrying, name
    if not seen:
        pytest.skip("SKIPPED: no fetched XIAO draws its edge inside a footprint")


def test_a_mirrored_elements_copper_is_on_the_other_face(tmp_path):
    """EAGLE's `M` turns the whole package over onto the bottom face, and
    `eagle._ink` already moved its silkscreen there while its surface pads
    stayed on the top. The Uno's GROUND solder jumper is mirrored and its two
    pads were drawn on the top face from OH-110 until this; the QT Py's
    ESP32-C3 is mirrored too, and it was 33 pads on the top face of a board
    whose file puts them underneath (OH-180). Lives here because the
    composer's artwork is the one reader of a pad's face.
    """
    path = tmp_path / "mirrored.brd"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><board>'
        '<plain><wire x1="0" y1="0" x2="10" y2="0" width="0.2" layer="20"/></plain>'
        '<libraries><library name="L"><packages><package name="P">'
        '<smd name="1" x="-1" y="0" dx="0.5" dy="0.5" layer="1"/>'
        '<smd name="2" x="1" y="0" dx="0.5" dy="0.5" layer="16"/>'
        "</package></packages></library></libraries>"
        '<elements>'
        '<element name="TOP" library="L" package="P" x="2" y="2"/>'
        '<element name="BOT" library="L" package="P" x="8" y="8" rot="MR0"/>'
        "</elements><signals/>"
        "</board></drawing></eagle>",
        encoding="utf-8",
    )
    board = eagle.read_board(path)
    sides = {(e.name, p.number): (p.front, p.back)
             for e in board.elements for p in e.pads}
    assert sides[("TOP", "1")] == (True, False)
    assert sides[("TOP", "2")] == (False, True)
    assert sides[("BOT", "1")] == (False, True), (
        "a mirrored element's top-layer pad is on the bottom of the board"
    )
    assert sides[("BOT", "2")] == (True, False)


def test_a_mirrored_element_hangs_under_the_board():
    """**A part on the bottom face is turned over, not reflected.** EAGLE's
    `M` negates x, and a model moved by that alone is a mirror image standing
    on the TOP of the board, inside out -- which is how the QT Py's
    ESP32-C3 first came out. Negating z with it is the half turn that puts
    the part underneath, and the pair is a rotation.
    """
    model = _model_box(2.0, 1.0, 1.0, "#262525")
    pads = (eagle.Pad("1", "smd", -0.85, 0.0, 0.5, 0.5, None),
            eagle.Pad("2", "smd", 0.85, 0.0, 0.5, 0.5, None))
    thickness = 1.6
    for mirrored in (False, True):
        element = eagle.Element("C1", "L", "P", pads=pads, mirrored=mirrored)
        put = compose.place(model, element, 0.0, thickness, (0.0, 0.0))
        heights = [p[at + 1] for _c, (p, _n, _i) in put.groups.items()
                   for at in range(0, len(p), 3)]
        if mirrored:
            assert max(heights) <= 0.0 + 1e-9, (
                f"a bottom-side part reaches {max(heights):.3f} mm, above the "
                f"board's underside at 0"
            )
        else:
            assert min(heights) >= thickness - 1e-9


def _model_box(length: float, width: float, height: float, colour: str,
               at: tuple[float, float] = (0.0, 0.0)) -> compose.Mesh:
    """A box in a model's own z-up frame, centred on `at`, for placing parts
    without OpenCASCADE. `slab` builds in the scene's axes, so it is swapped
    back: scene (x, up, -y) is model (x, y, up)."""
    x, y = at
    box = compose.slab([(x - length / 2, y - width / 2), (x + length / 2, y - width / 2),
                        (x + length / 2, y + width / 2), (x - length / 2, y + width / 2)],
                       height, colour, (0.0, 0.0))
    groups = {}
    for name, (p, n, i) in box.groups.items():
        groups[name] = (
            [v for k in range(0, len(p), 3) for v in (p[k], -p[k + 2], p[k + 1])],
            [v for k in range(0, len(n), 3) for v in (n[k], -n[k + 2], n[k + 1])],
            list(i))
    return compose.Mesh(groups)


def test_compose_draws_each_0603_from_its_own_library(monkeypatch, capsys):
    """**The lookup `compose` actually uses**, end to end: the Thing Plus's
    fourteen resistors come out as resistors and its nine capacitors as
    capacitors. `correspondence_for` can be right while `compose` keys its own
    table by package and draws all twenty-three as whichever row came last --
    that mutant survived until this drove `compose` itself.

    No OpenCASCADE: only the two 0603 rows are kept, and each is given a
    1.6 x 0.8 mm box, so nothing is fetched or tessellated.
    """
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Thing Plus ESP32-C6")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    rows = tuple(c for c in compose.CORRESPONDENCE if c.package == "0603")
    assert {c.vendor_library for c in rows} == {"SparkFun-Resistors",
                                                "SparkFun-Capacitors"}
    monkeypatch.setattr(compose, "CORRESPONDENCE", rows)
    monkeypatch.setattr(
        compose, "component_mesh",
        lambda component, deflection: (
            _model_box(1.6, 0.8, 0.5, "#101010"),
            compose.Extent(-0.8, 0.8, -0.4, 0.4, 0.0, 0.5)))
    compose.compose(spec, deflection=0.05, check=True)
    out = capsys.readouterr().out
    drawn_line = next(line for line in out.splitlines()
                      if line.startswith("  drawn "))
    drawn = dict(part.rsplit(" (", 1) for part in
                 drawn_line.split(": ", 1)[1].split(", "))
    want = {"SparkFun-Resistors": "R_0603_1608Metric)",
            "SparkFun-Capacitors": "C_0603_1608Metric)"}
    board = compose.read_layout(spec.layout)
    # C6 is valued DNP, and a part its schematic says is not fitted is not
    # drawn (OH-187).
    refused = {name for name, said in compose.statements_for(spec).items()
               if said.refused}
    placed = [e for e in board.elements
              if e.package == "0603" and e.name not in refused]
    assert len(placed) == len(drawn), (drawn_line, len(placed))
    for element in placed:
        assert drawn[element.name] == want[element.library], (
            f"{element.name} is from {element.library} and was drawn as "
            f"{drawn[element.name]}"
        )


# --- a passive is drawn as the kind its vendor states (OH-187) -----------------


def test_a_value_states_a_kind_only_in_ohms_farads_or_a_word_it_knows():
    """Every value these four boards carry, and the answer each one gives.

    A bare number states no unit, so `27` and `0` decide nothing; `2nH` is
    henries, which is not read; and a word is read only if `KIND_WORDS` holds
    it -- which is closed, and pinned here, so that `TBD`, `DNP` and `NC` are
    not swallowed by it.
    """
    for value in ("10K", "5.1K", "100k", "1k", "4.7k", "0 ohm", "4K7", "4R7",
                  "10Ω", "1M"):
        assert compose.value_kind(value) == "resistor", value
    for value in ("0.1uF", "22pF", "10µF", "10μF", "2.2uF", "0.01uF", "1uF"):
        assert compose.value_kind(value) == "capacitor", value
    assert compose.value_kind("FUSE") == "fuse"
    for value in ("27", "0", "2nH", "TBD", "DNP", "NC", "", "10m", "100n"):
        assert compose.value_kind(value) is None, value
    assert compose.KIND_WORDS == {"FUSE": "fuse"}
    assert compose.NOT_FITTED == {"DNP", "NC", "NF", "DNF", "DNI"}
    assert compose.UNDECIDED == {"TBD"}


def _schematic(tmp_path, parts: str, variantdefs: str = "") -> pathlib.Path:
    """A written EAGLE schematic: two libraries under one name told apart by
    urn, one of each kind of deviceset prefix these rules meet, and the
    variant definitions EAGLE writes after the libraries."""
    path = tmp_path / "board.sch"
    path.write_text(
        '<eagle version="9.6.2"><drawing><schematic><libraries>'
        '<library name="lib"><devicesets>'
        '<deviceset name="RESISTOR" prefix="R"/>'
        '<deviceset name="CAP" prefix="C"/>'
        '<deviceset name="INDUCTOR" prefix="L"/>'
        '<deviceset name="FUSE" prefix="F"/>'
        '<deviceset name="DIODE" prefix="D"/>'
        '<deviceset name="CHIP" prefix="U"/>'
        '<deviceset name="LED" prefix="LED"/>'
        '<deviceset name="CONN" prefix="CONN"/>'
        '<deviceset name="FERRITE" prefix="FB"/>'
        '<deviceset name="JUMPER" prefix="JP"/>'
        '<deviceset name="SWITCH" prefix="SW"/>'
        '<deviceset name="LOGO" prefix=""/>'
        '<deviceset name="NETWORK" prefix="RN"/>'
        '<deviceset name="VARISTOR" prefix="R"/>'
        '</devicesets></library>'
        '<library name="twin" urn="urn:one"><devicesets>'
        '<deviceset name="PART" prefix="R"/></devicesets></library>'
        '<library name="twin" urn="urn:two"><devicesets>'
        '<deviceset name="PART" prefix="C"/></devicesets></library>'
        f'</libraries>{variantdefs}<parts>{parts}</parts></schematic></drawing></eagle>',
        encoding="utf-8")
    return path


def test_the_schematic_decides_a_passives_kind_and_which_statement_did(tmp_path):
    """The prefix alone, the value alone, both agreeing, and neither, and a
    prefix naming a kind that is none of R, C, L and F -- which is only
    silent when it is EMPTY. What spoke is recorded as fields, not words:
    `compose` counts them."""
    stated = compose.stated_kinds(_schematic(tmp_path, (
        '<part name="R1" library="lib" deviceset="RESISTOR" value="10K"/>'
        '<part name="R3" library="lib" deviceset="RESISTOR" value="27"/>'
        '<part name="F1" library="lib" deviceset="FUSE" value="FUSE"/>'
        '<part name="X1" library="lib" deviceset="LOGO" value="0.1uF"/>'
        '<part name="U1" library="lib" deviceset="CHIP" value="RP2040"/>'
        '<part name="LED1" library="lib" deviceset="LED" value="RED"/>'
        '<part name="CONN1" library="lib" deviceset="CONN" value=""/>'
        '<part name="G1" library="lib" deviceset="LOGO" value="ADAFRUIT"/>'
        '<part name="R12" library="twin" library_urn="urn:one" deviceset="PART"/>'
        '<part name="C12" library="twin" library_urn="urn:two" deviceset="PART"/>')))
    assert stated["R1"] == compose.Statement("resistor", "R", "10K")
    assert stated["R3"] == compose.Statement("resistor", "R", None)
    # Only an F prefix agrees with a value reading FUSE.
    assert stated["F1"] == compose.Statement("fuse", "F", "FUSE", word="FUSE")
    assert stated["X1"] == compose.Statement("capacitor", None, "0.1uF")
    # **A prefix that is none of R, C, L and F still speaks**: LED is not an
    # inductor and CONN is not a capacitor, whatever letter they start with.
    assert stated["U1"] == compose.Statement(compose.OTHER, "U", None)
    assert stated["LED1"] == compose.Statement(compose.OTHER, "LED", None)
    assert stated["CONN1"] == compose.Statement(compose.OTHER, "CONN", None)
    assert stated["G1"] == compose.Statement(None, None, None)
    # One library name, two urns, two prefixes.
    assert stated["R12"].kind == "resistor" and stated["C12"].kind == "capacitor"
    assert compose.PREFIX_KINDS == {"R": "resistor", "C": "capacitor",
                                    "L": "inductor", "F": "fuse",
                                    "RN": "resistor"}


def test_a_passive_renamed_away_from_its_prefix_is_refused(tmp_path):
    """**The designer's name against the library's prefix** (OH-191): the
    Uno's F1 is placed from an inductor's deviceset. A name whose letter
    stem `DESIGNATOR_STEMS` pairs with the prefix keeps the kind -- the
    Uno's PC1 is a polarised C, FB1 a ferrite on an L -- and any other is
    refused with both statements, a varistor's RV1, a diode's CR1 and a
    0R jumper's JP1 alike. A deviceset's own name is a third statement: a
    VARISTOR is not a resistor whatever its prefix and its part's name say.
    And a part whose prefix is not a passive's is not asked: an LED named
    TX, a chip named ZU4."""
    stated = compose.stated_kinds(_schematic(tmp_path, (
        '<part name="F1" library="lib" deviceset="INDUCTOR" value="MF-MSMF050-2"/>'
        '<part name="Z1" library="lib" deviceset="RESISTOR" value="CG0603MLC-05E"/>'
        '<part name="RV1" library="lib" deviceset="RESISTOR" value="10K"/>'
        '<part name="CR1" library="lib" deviceset="RESISTOR" value=""/>'
        '<part name="JP1" library="lib" deviceset="RESISTOR" value="0R"/>'
        '<part name="R5" library="lib" deviceset="VARISTOR" value=""/>'
        '<part name="FB1" library="lib" deviceset="INDUCTOR" value="BLM21"/>'
        '<part name="PTC2" library="lib" deviceset="FUSE" value=""/>'
        '<part name="R7" library="lib" deviceset="NETWORK" value="10K"/>'
        '<part name="PC1" library="lib" deviceset="CAP" value="47u"/>'
        '<part name="RN1" library="lib" deviceset="NETWORK" value="10K"/>'
        '<part name="TX" library="lib" deviceset="LED" value="YELLOW"/>'
        '<part name="ZU4" library="lib" deviceset="CHIP" value="ATMEGA328P"/>')))
    for name, prefix in (("F1", "L"), ("Z1", "R"), ("RV1", "R"), ("CR1", "R"),
                         ("JP1", "R")):
        assert stated[name].kind is None, stated[name]
        assert f"named it {name}" in stated[name].refused
        assert f"prefix {prefix} says" in stated[name].refused
    assert stated["R5"].kind is None and "VARISTOR" in stated["R5"].refused
    assert stated["FB1"] == compose.Statement("inductor", "L", None)
    assert stated["PTC2"] == compose.Statement("fuse", "F", None, word="FUSE")
    assert stated["R7"] == compose.Statement("resistor", "RN", "10K")
    assert stated["PC1"] == compose.Statement("capacitor", "C", None)
    assert stated["RN1"] == compose.Statement("resistor", "RN", "10K")
    assert stated["TX"] == compose.Statement(compose.OTHER, "LED", None)
    assert stated["ZU4"] == compose.Statement(compose.OTHER, "U", None)
    assert compose.DESIGNATOR_STEMS == {
        "R": {"R", "RN"}, "C": {"C", "PC"}, "L": {"L", "FB"},
        "F": {"F", "PTC"}, "RN": {"RN", "R"}}
    assert compose.DEVICESET_WORDS == {
        "VARISTOR": "varistor", "FUSE": "fuse", "PTC": "fuse",
        "THERMISTOR": "thermistor", "FERRITE": "inductor"}


def test_two_statements_of_a_kind_that_disagree_refuse_the_part(tmp_path):
    """**A swapped kind is refused, not drawn as either**: the QT Py's own
    L2, an inductor valued in ohms; a capacitor valued in ohms; a chip, a
    ferrite and an LED valued in farads or ohms; a diode and an LED valued
    FUSE; and the KB2040's own R8, a resistor valued FUSE -- whose model KiCad
    does publish, which is why the reason is the disagreement and never that
    nothing could draw it."""
    stated = compose.stated_kinds(_schematic(tmp_path, (
        '<part name="L2" library="lib" deviceset="INDUCTOR" value="0 ohm"/>'
        '<part name="C9" library="lib" deviceset="CAP" value="10K"/>'
        '<part name="U2" library="lib" deviceset="CHIP" value="0.1uF"/>'
        '<part name="FB1" library="lib" deviceset="FERRITE" value="600R"/>'
        '<part name="LED2" library="lib" deviceset="LED" value="10K"/>'
        '<part name="D5" library="lib" deviceset="DIODE" value="FUSE"/>'
        '<part name="LED3" library="lib" deviceset="LED" value="FUSE"/>'
        '<part name="R8" library="lib" deviceset="RESISTOR" value="FUSE"/>')))
    for name in ("L2", "C9", "U2", "FB1", "LED2", "D5", "LED3", "R8"):
        said = stated[name]
        assert said.kind is None and "disagree" in said.refused, (name, said)
    assert "says resistor" in stated["R8"].refused
    assert "says fuse" in stated["R8"].refused


def test_a_part_its_files_say_is_not_fitted_is_not_drawn(tmp_path):
    """**`populate` where EAGLE writes it**: on the `<variant>` a part is
    placed in, read for the schematic's CURRENT variant only, and on a board
    file's `<element>` -- never on `<part>`, which EAGLE does not write. And
    DNP and its spellings, and TBD -- which says nobody has decided, so
    drawing the part would say somebody had -- of a passive only: a jumper
    or a switch valued NC is normally closed, not missing."""
    schematic = _schematic(tmp_path, (
        '<part name="R4" library="lib" deviceset="RESISTOR" value="10K">'
        '<variant name="full" populate="no"/></part>'
        '<part name="R5" library="lib" deviceset="RESISTOR" value="10K">'
        '<variant name="lite" populate="no"/></part>'
        '<part name="R6" library="lib" deviceset="RESISTOR" value="10K" populate="no"/>'
        '<part name="C6" library="lib" deviceset="CAP" value="DNP"/>'
        '<part name="R2" library="lib" deviceset="RESISTOR" value="nc"/>'
        '<part name="C7" library="lib" deviceset="CAP" value="TBD"/>'
        '<part name="JP1" library="lib" deviceset="JUMPER" value="NC"/>'
        '<part name="SW1" library="lib" deviceset="SWITCH" value="NC"/>'
        '<part name="R9" library="lib" deviceset="RESISTOR" value="10K"/>'
        '<part name="R10" library="lib" deviceset="RESISTOR" value="10K"/>'
        '<part name="J2" library="lib" deviceset="CONN" device="NO_SILK_NO_POP"/>'
        '<part name="J4" library="lib" deviceset="CONN" device="NO_SILK_FEMALE_PTH"/>'
        '<part name="J6" library="lib" deviceset="CONN" device="PIANO_POP"/>'),
        variantdefs=('<variantdefs><variantdef name="lite"/>'
                     '<variantdef name="full" current="yes"/></variantdefs>'))
    stated = compose.stated_kinds(schematic)
    assert "populate" in stated["R4"].refused and "'full'" in stated["R4"].refused
    assert stated["R5"].refused is None, "a variant that is not current"
    assert stated["R6"].refused is None, "<part populate> is not EAGLE's shape"
    assert "not fitted" in stated["C6"].refused
    assert "not fitted" in stated["R2"].refused
    assert "whether it is fitted is not stated" in stated["C7"].refused
    assert stated["JP1"] == compose.Statement(compose.OTHER, "JP", None)
    assert stated["SW1"] == compose.Statement(compose.OTHER, "SW", None)
    # **The device's own name, where the vendor says it there** (OH-189):
    # SparkFun's CONN_06 places NO_SILK_NO_POP and NO_SILK_FEMALE_PTH on one
    # land, so the land cannot say which is fitted and the device does. Read
    # as a whole run of the name, so PIANO_POP says nothing.
    assert "'NO_SILK_NO_POP'" in stated["J2"].refused
    assert stated["J4"].refused is None and stated["J6"].refused is None
    assert compose.NOT_FITTED_DEVICE == ("NO", "POP")

    board = tmp_path / "board.brd"
    board.write_text(
        '<eagle version="9.6.2"><drawing><board><variantdefs>'
        '<variantdef name="full" current="yes"/></variantdefs><elements>'
        '<element name="R9" library="lib" package="0603" value="10K" x="0" y="0"'
        ' populate="no"/>'
        '<element name="R10" library="lib" package="0603" value="10K" x="0" y="0">'
        '<variant name="full" populate="no"/></element>'
        '<element name="R1" library="lib" package="0603" value="10K" x="0" y="0"/>'
        '</elements></board></drawing></eagle>', encoding="utf-8")
    import types
    statements = compose.statements_for(
        types.SimpleNamespace(schematic=schematic, layout=board))
    assert 'board.brd places R9 with populate="no"' in statements["R9"].refused
    assert 'board.brd places R10 with populate="no"' in statements["R10"].refused
    assert statements["R9"].kind is None


def test_another_kind_on_a_passives_land_is_refused(tmp_path):
    """**A row does not get to decide what a part is** (OH-187 confirm
    review). On a land every row of which draws a resistor, capacitor,
    inductor or fuse, a part its schematic states to be something else is
    refused, as a part nothing states is: the QT Py's L1 land restated a
    ferrite, R7's restated an LED, an ESD diode on a resistor's land. Only a
    board with no schematic -- the XIAOs -- draws its ESD diodes from a
    resistor's row, as it always has. And without a kind, a package two
    unlibraried rows answer is answered with None rather than whichever row
    comes first."""
    def placed(name, package, library="lib"):
        return eagle.Element(
            name, library, package,
            pads=(eagle.Pad("1", "smd", -0.46, 0.0, 0.5, 0.5, None),
                  eagle.Pad("2", "smd", 0.46, 0.0, 0.5, 0.5, None)))

    statements = {"L1": compose.Statement(compose.OTHER, "FB", None),
                  "R7": compose.Statement(compose.OTHER, "LED", None),
                  "D2": compose.Statement(compose.OTHER, "D", None),
                  "C1": compose.Statement(None, None, None)}
    for name, land in (("L1", "_0402"), ("R7", "_0603MP_TWO6MIL"),
                       ("D2", "ESD-0402")):
        row, refused = compose.drawn_from(placed(name, land), statements)
        assert row is None and f"prefix {statements[name].prefix}" in refused, (
            name, row, refused)
    row, refused = compose.drawn_from(placed("C1", "_0402NO"), statements)
    assert row is None and "nothing in" in refused
    row, refused = compose.drawn_from(placed("D2", "ESD-0402"), None)
    assert refused is None and row.model == "R_0402_1005Metric"
    assert compose.correspondence_for(placed("C1", "_0402NO")) is None
    assert compose.correspondence_for(
        placed("C1", "_0402NO"), "capacitor").model == "C_0402_1005Metric"
    # **The kind is asked before the vendor's library is**: a part from
    # SparkFun's resistor library that its schematic calls a capacitor is
    # not drawn as the resistor its library's row would draw.
    stray = placed("R99", "0603", library="SparkFun-Resistors")
    assert compose.correspondence_for(stray, "capacitor") is None
    assert compose.drawn_from(
        stray, {"R99": compose.Statement("capacitor", "C", None)}) == (None, None)


#: What each manifest board's own schematic refuses, by name. Written down
#: rather than derived, so a reader that loses a statement -- or gains a
#: false one -- is caught on the board it happens to.
REFUSED_BY_SCHEMATIC = {
    "SparkFun Thing Plus ESP32-C6": {"C6"},
    "Adafruit QT Py ESP32-C3": {"C7", "C9", "L2"},
    "Adafruit Feather ESP32-C6": set(),
    "Adafruit KB2040": {"R8"},
    "SparkFun Pro Micro ESP32-C3": set(),
    "SparkFun Qwiic Pocket ESP32-C6": {"C6", "J2", "J3"},
    # Arduino named its fuse F1 and its varistors Z1 and Z2, and placed them
    # from an inductor's deviceset and a varistor's whose prefix is R.
    "Arduino Uno": {"F1", "Z1", "Z2"},
    # A KiCad board file is its own schematic here (OH-195), and PCBCUPID's
    # states every passive's kind three ways that agree.
    "PCBCUPID Glyph Mini RP2040": set(),
    # Both Glyphs mark their sockets, test pads and jumper `dnp`, and place
    # HRO's USB socket from their own disk on a land a row draws as GCT's.
    "PCBCUPID Glyph C3": {"J1", "J2", "J3", "J4", "JP1"},
    "PCBCUPID Glyph C6": {"J1", "J2", "J3", "J4", "JP1", "F1"},
    "Olimex ESP32-C3-DevKit-Lipo": set(),
    "SparkFun Thing Plus ESP32-C5": set(),
    # KiCad 5, read through kicad.board_tree (OH-198): the parts Olimex value
    # NA, not assembled (`compose.NOT_ASSEMBLED`) -- five resistors, the EXT1
    # and ESP-PROG1 headers and the PWR2 terminal.
    "Olimex ESP32-C6-EVB": {"R9", "R10", "R18", "R33", "R34", "EXT1", "ESP-PROG1",
                            "PWR2"},
}


#: What each manifest board draws as copper, ink or a hole -- an ABSENT reason
#: carrying `NO_BODY` -- by package. Written down, because the words are the
#: only thing that sorts a reason into the bodyless count rather than the
#: refused one, and a reason that loses them would move silently.
BODYLESS = {
    "SparkFun Thing Plus ESP32-C6": {
        "COMBO-JUMPER_2_NC_TRACE", "FIDUCIAL-MICRO", "SMT-JUMPER_2_NC_TRACE_SILK",
        "SMT-JUMPER_2_NO_SILK", "SMT-JUMPER_3_1-NC_TRACE_SILK",
        "SMT-JUMPER_3_2-NC_TRACE_SILK", "THING_PLUS"},
    "Adafruit QT Py ESP32-C3": {
        "1X07_CASTEL", "B1,27", "FIDUCIAL_1MM", "TESTPOINT_MINUS_1X3MM",
        "TESTPOINT_PLUS_1X3MM"},
    "Adafruit Feather ESP32-C6": {
        "1X12_ROUND", "1X16_ROUND", "FIDUCIAL_1MM", "MOUNTINGHOLE_2.5_PLATED",
        "SOLDERJUMPER_CLOSEDWIRE"},
    "Adafruit KB2040": {
        "1X13_CASTEL", "FIDUCIAL_1MM", "SOLDERJUMPER_ARROW_NOPASTE",
        "TESTPOINT_ROUND_1.5MM_NO"},
    "SparkFun Pro Micro ESP32-C3": {
        "1X09_CASTELLATED", "FIDUCIAL-MICRO", "PAD.03X.05",
        "SMT-JUMPER_2_NC_TRACE_SILK", "SMT-JUMPER_3_2-NC_TRACE_SILK",
        "USB-SOLDER-PADS"},
    "SparkFun Qwiic Pocket ESP32-C6": {
        "FIDUCIAL-MICRO", "PAD.03X.03", "SMT-JUMPER_2_NC_TRACE_SILK",
        "SMT-JUMPER_3_2-NC_TRACE_SILK"},
    # Its three logos put down no pad and are counted as ink instead.
    "PCBCUPID Glyph Mini RP2040": set(),
    # Their copper is refused by `dnp` instead, and their logos are ink.
    "PCBCUPID Glyph C3": set(),
    "PCBCUPID Glyph C6": set(),
    "Olimex ESP32-C3-DevKit-Lipo": {
        "Fiducial1x3", "Fiducial1x3_Paste",
        "Mounting_Hole_Drill-3.3mm_Clerance-7mm", "SJ_1_SMALLER"},
    "Olimex ESP32-C6-EVB": {
        "Fiducial1x3", "Mounting_Hole_Drill-3.3mm_Clerance-7mm", "SJ_1_SMALLER",
        "TEST_PAD40x70_SQUARE"},
    "SparkFun Thing Plus ESP32-C5": {
        "Fiducial_0.5mm_Mask1mm", "Jumper_2_NC_Trace", "Jumper_2_NO",
        "Jumper_2_PTH_SMD_Combo-NC", "Jumper_3_NC-1_Trace",
        "Jumper_3_NC-2_Trace", "Standoff", "ThingPlus_With_Connectors"},
}


def test_each_manifest_board_counts_the_same_things_bodyless():
    """Per fetched manifest board, the packages drawn as copper, ink or a
    hole are the ones written above, and every other ABSENT package it
    places is a refused part its `EXPLAINS` names -- so header holes whose
    reason lost its no-body words would move from one count to the other
    and fail here, on the board they moved on."""
    unfetched = []
    for _row, spec in _manifest_specs():
        if spec is None:
            continue   # refused by name; test_every_manifest_row_is_composed_from_that_row
        if not _fetched(spec):
            unfetched.append(_row.board)
            continue
        statements = compose.statements_for(spec)
        absent = {e.package for e in compose.read_layout(spec.layout).elements
                  if e.package in compose.ABSENT
                  and not (e.name in statements and statements[e.name].refused)}
        bodyless = {p for p in absent if compose.NO_BODY in compose.ABSENT[p]}
        assert bodyless == BODYLESS[spec.board], (spec.board, bodyless)
        assert absent - bodyless <= EXPLAINS[spec.board], (
            spec.board, absent - bodyless)
    if unfetched:
        pytest.skip(f"checked the rest; not fetched: {unfetched}")


#: The passives a board's own file states the kind of and nobody publishes a
#: model for, by board and reference: each refused by its package's `ABSENT`
#: reason rather than drawn (OH-195).
PASSIVES_NOBODY_MODELS = {("Olimex ESP32-C3-DevKit-Lipo", "L1"),
                          # Its CD32 sibling, its other inductor, and its two
                          # cans, whose land and value state two bodies (OH-198).
                          ("Olimex ESP32-C6-EVB", "L2"), ("Olimex ESP32-C6-EVB", "L1"),
                          ("Olimex ESP32-C6-EVB", "C1"), ("Olimex ESP32-C6-EVB", "C6")}


def test_every_manifest_passive_is_drawn_as_the_kind_its_vendor_states():
    """**The rows, held to the schematics**, per fetched board that reads
    one -- the manifest boards and the Uno: each part a schematic calls a
    resistor, capacitor, inductor or fuse is drawn from a row of that kind,
    and the parts refused are the ones written above -- so a row whose kind
    is swapped, a package that loses its row for one kind, or a part whose
    kind is restated, fails by name."""
    unfetched = []
    for spec in compose.COMPOSITIONS:
        if spec.schematic is None:
            continue
        if not _fetched(spec):
            unfetched.append(spec.board)
            continue
        assert spec.board in REFUSED_BY_SCHEMATIC, (
            f"{spec.board} is composed and its schematic's refusals are not "
            f"written down")
        statements = compose.statements_for(spec)
        refused = set()
        for element in compose.read_layout(spec.layout).elements:
            row, why = compose.drawn_from(element, statements)
            if why is not None:
                refused.add(element.name)
                continue
            said = statements.get(element.name)
            if said is None or said.kind not in compose.PASSIVE_KINDS.values():
                continue
            # A passive nobody publishes a model of is refused by its
            # package's ABSENT reason, named here part by part: the
            # Olimex's inductor L1 (OH-195). Nowhere else may a stated
            # passive go undrawn.
            assert row is not None or (
                (spec.board, element.name) in PASSIVES_NOBODY_MODELS
                and compose.absent_why(element) is not None), (
                f"{spec.board}: {element.name} ({element.package}) is stated "
                f"{said.kind}, and no row draws that kind on that package")
            if row is None:
                continue
            assert compose.PASSIVE_KINDS[row.library] == said.kind, (
                f"{spec.board}: {element.name} is stated {said.kind} and is "
                f"drawn as {row.model}")
        assert refused == REFUSED_BY_SCHEMATIC[spec.board], (spec.board, refused)
    if unfetched:
        pytest.skip(f"checked the rest; not fetched: {unfetched}")


def _passive_rows_only(monkeypatch):
    """Only the passive rows, each a 1.6 x 0.8 mm box, so `compose` runs
    without OpenCASCADE and fetches nothing."""
    rows = tuple(c for c in compose.CORRESPONDENCE
                 if c.library in compose.PASSIVE_KINDS
                 and not c.model.startswith("R_Array"))
    monkeypatch.setattr(compose, "CORRESPONDENCE", rows)
    monkeypatch.setattr(
        compose, "component_mesh",
        lambda component, deflection: (
            _model_box(1.6, 0.8, 0.5, "#101010"),
            compose.Extent(-0.8, 0.8, -0.4, 0.4, 0.0, 0.5)))


def test_compose_draws_each_passive_as_the_kind_its_schematic_states(
        monkeypatch, capsys):
    """**The lookup `compose` actually uses**, on the two boards OH-187 was
    filed from: the QT Py's R1-R6 were C_0402 and the Feather's C4 and C10
    were R_0603."""
    _passive_rows_only(monkeypatch)
    want = {
        "Adafruit QT Py ESP32-C3": {
            **{f"R{n}": "R_0402_1005Metric" for n in range(1, 7)},
            "C2": "C_0402_1005Metric", "L1": "L_0402_1005Metric"},
        "Adafruit Feather ESP32-C6": {
            "C4": "C_0603_1608Metric", "C10": "C_0603_1608Metric",
            "R1": "R_0603_1608Metric"},
    }
    for board, expected in want.items():
        spec = next(s for s in compose.COMPOSITIONS if s.board == board)
        if not _fetched(spec):
            pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
        compose.compose(spec, deflection=0.05, check=True)
        out = capsys.readouterr().out
        drawn_line = next(line for line in out.splitlines()
                          if line.startswith("  drawn "))
        drawn = dict(part[:-1].rsplit(" (", 1) for part in
                     drawn_line.split(": ", 1)[1].split(", "))
        for name, model in expected.items():
            assert drawn.get(name) == model, (board, name, drawn.get(name))


def test_what_decided_each_passive_is_recorded_in_the_model(
        monkeypatch, capsys, tmp_path):
    """**The recording, read back** (OH-187 review): the console line counts
    which statements spoke, from the statements' own fields, and the written
    model carries each passive's kind with what said so and each refusal
    with its reason."""
    from tools.import_3d_model import read_extras

    _passive_rows_only(monkeypatch)
    monkeypatch.setattr(compose, "OUT", tmp_path)
    monkeypatch.setattr(compose, "REPO", tmp_path)
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "Adafruit QT Py ESP32-C3")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    compose.compose(spec, deflection=0.05, check=False)
    out = capsys.readouterr().out
    assert ("  kinds   21 passive(s) drawn as the kind Adafruit QT Py "
            "ESP32-C3.sch states: 19 by the deviceset's prefix and the value, "
            "2 by the prefix alone, 0 by the value alone") in out, out
    assert "  refused 5 placement(s): 2 of 2 package(s) with no published " \
           "model, and 3 by what their own schematic states" in out, out
    extras = read_extras(tmp_path / f"{compose._slug(spec.board)}.glb")
    assert extras["kinds"]["R1"] == {"kind": "resistor", "prefix": "R",
                                     "value": "10K"}
    assert extras["kinds"]["R3"] == {"kind": "resistor", "prefix": "R"}
    refused = {name: entry["why"] for entry in extras["absent"]
               for name in entry["elements"]}
    assert "'0 ohm'" in refused["L2"] and "disagree" in refused["L2"]
    assert "TBD" in refused["C7"]


def test_every_row_draws_something_somewhere():
    """A row no composed board draws from is a claim about a part nobody
    places -- as the KB2040's R8 row became when its schematic's two
    statements were found to disagree. Asked only with every board file
    fetched, because an unfetched board's rows would look unused."""
    used: set[int] = set()
    unfetched = []
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            unfetched.append(spec.board)
            continue
        board = compose.read_layout(spec.layout)
        extra = (compose.dip_header_elements(
            [pad for name in spec.headers for pad in board.element(name).pads])
            if spec.dip_headers else [])
        statements = compose.statements_for(spec)
        for element in [*board.elements, *extra]:
            row, _why = compose.drawn_from(element, statements)
            if row is not None:
                used.add(id(row))
    if unfetched:
        pytest.skip(f"SKIPPED: not every board is fetched: {unfetched}")
    unused = [f"{row.package} -> {row.model}" for row in compose.CORRESPONDENCE
              if id(row) not in used]
    assert not unused, unused


# --- a row held to the vendor's own words (OH-193) ------------------------------


def test_every_row_agrees_with_its_vendors_words():
    """On every fetched composed board, no drawn placement's row names a
    model its vendor's own package or value words contradict -- the check
    `compose` makes, asked here without OpenCASCADE."""
    checked, unfetched = 0, []
    for spec in compose.COMPOSITIONS:
        if not _fetched(spec):
            unfetched.append(spec.board)
            continue
        board = compose.read_layout(spec.layout)
        pads = [pad for name in spec.headers for pad in board.element(name).pads]
        extra = compose.dip_header_elements(pads) if spec.dip_headers else []
        statements = compose.statements_for(spec)
        for element in [*board.elements, *extra]:
            row, _why = compose.drawn_from(element, statements)
            if row is None:
                continue
            checked += 1
            said = compose.contradiction(element, row)
            assert said is None, f"{spec.board}: {element.name}: {said}"
    if not checked:
        pytest.skip("SKIPPED: no board layouts are fetched")
    if unfetched:
        pytest.skip(f"checked {checked} placements; not fetched: {unfetched}")


def test_a_row_its_vendors_words_contradict_is_refused():
    """The three words the vocabularies read, each agreeing and each
    contradicted: an orientation, a chip, a lead count. The vocabularies are
    closed and pinned, so a word is read only once it is added here too."""
    def placed(package, value=""):
        return eagle.Element("U1", "lib", package, pads=(), value=value)

    vertical = compose.Component(
        "JST04_1MM_VERT", "Connector_JST",
        "JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical", "a test row")
    horizontal = dataclasses.replace(
        vertical, model="JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal")
    assert compose.contradiction(placed("JST04_1MM_VERT"), vertical) is None
    assert "vertical" in compose.contradiction(placed("JST04_1MM_VERT"), horizontal)
    assert "horizontal" in compose.contradiction(placed("JST04_1MM_RA"), vertical)

    c3 = compose.Component(
        "ESP32-C3-MINI-1", "espressif", "ESP32-C3-MINI-1", "a test row",
        step="https://example.invalid/ESP32-C3-MINI-1.STEP",
        footprint="https://example.invalid/ESP32-C3-MINI-1.kicad_mod")
    assert compose.contradiction(placed("ESP32-C3-MINI-1", "ESP32-C3_MINI-1"), c3) is None
    # The model's name left alone and only its files pointed elsewhere.
    c6_files = dataclasses.replace(
        c3, step="https://example.invalid/ESP32-C6-MINI-1.STEP",
        footprint="https://example.invalid/ESP32-C6-MINI-1.kicad_mod")
    assert "ESP32-C6" in compose.contradiction(placed("ESP32-C3-MINI-1"), c6_files)
    # A value that names the chip where the package does not: the Feather's.
    assert "ESP32-C3" in compose.contradiction(
        placed("ESP32-PICO-MINI", "ESP32-C3-MINI"),
        dataclasses.replace(c3, model="ESP32-C6-MINI-1", step=None, footprint=None))

    qfn = compose.Component("QFN56_7MM", "Package_DFN_QFN",
                            "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", "a test row")
    assert compose.contradiction(placed("QFN56_7MM"), qfn) is None
    assert "56 leads" in compose.contradiction(
        placed("QFN56_7MM"), dataclasses.replace(qfn, model="QFN-60-1EP_7x7mm"))
    assert "6 leads" in compose.contradiction(
        placed("2X03"), dataclasses.replace(qfn, model="PinHeader_2x04_P2.54mm"))
    # A body's size is not a header's count.
    assert compose.contradiction(
        placed("TDFN8_2X2MM"), dataclasses.replace(qfn, model="DFN-8-1EP_2x2mm")) is None

    assert compose.ORIENTATION_WORDS == {"VERT": "Vertical", "VERTICAL": "Vertical",
                                         "RA": "Horizontal", "HORIZONTAL": "Horizontal"}
    assert compose.CHIP_NAMES == ("ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-H2",
                                  "ESP32-S2", "ESP32-S3", "RP2040", "RP2350")


def test_compose_refuses_a_row_its_vendors_words_contradict(monkeypatch):
    """The exit itself, not only `contradiction`: the Pro Micro's vertical
    Qwiic land on KiCad's horizontal SM04B stops `compose` before any model
    is read, so no OpenCASCADE is needed."""
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Pro Micro ESP32-C3")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    row = next(c for c in compose.CORRESPONDENCE if c.package == "JST04_1MM_VERT")
    monkeypatch.setattr(compose, "CORRESPONDENCE", (dataclasses.replace(
        row, model="JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal"),))
    with pytest.raises(SystemExit, match="Fix the table rather than the words"):
        compose.compose(spec, deflection=0.05, check=True)


def test_compose_refuses_a_flip_on_a_mirrored_element(monkeypatch):
    """The side guard, driven: the Pocket's module is mirrored under the
    board by its file, and a row that also flips it would turn it back on
    top. A box the module's size stands in for its mesh, centred on its pads
    rather than where Espressif's footprint puts it, so the silkscreen check
    -- which is not the one asked about here -- is set aside."""
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Qwiic Pocket ESP32-C6")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    row = next(c for c in compose.CORRESPONDENCE if c.package == "ESP32-C6-MINI-1")
    monkeypatch.setattr(compose, "silk_miss", lambda *args: None)
    for flip, refused in ((False, False), (True, True)):
        monkeypatch.setattr(compose, "CORRESPONDENCE",
                            (dataclasses.replace(row, flip=flip),))
        monkeypatch.setattr(compose, "component_mesh", lambda component, d: (
            _model_box(13.2, 16.6, 2.4, "#101010"),
            compose.Extent(-6.6, 6.6, -8.3, 8.3, 0.0, 2.4)))
        if refused:
            with pytest.raises(SystemExit, match="flip on a mirrored element"):
                compose.compose(spec, deflection=0.05, check=True)
        else:
            compose.compose(spec, deflection=0.05, check=True)


def test_a_body_code_is_not_a_lead_count():
    """A DFN1006 is a 1.0 x 0.6 mm body and a QFN-3X3 a 3 x 3 mm one: neither
    number counts leads, and a count is what the words check compares."""
    for text in ("DFN1006-2L", "QFN-3X3", "QFN-3.0X3.0"):
        assert compose._leads(text, compose._VENDOR_LEADS) is None, text
    for text in ("QFN-16-1EP_3x3mm", "DFN-8-1EP_2x2mm"):
        assert compose._leads(text, compose._MODEL_LEADS) is not None, text
    assert compose._leads("QFN_3x3", compose._MODEL_LEADS) is None
    assert compose._leads("QFN56_7MM", compose._VENDOR_LEADS) == 56
    assert compose._leads("QFN32G-0.5-5X5MM", compose._VENDOR_LEADS) == 32


def _inputs_missing(spec, board) -> list[str]:
    """The fetched files `compose` would read for this board and cannot find:
    a model it would otherwise download, one tools/model_from_datasheet.py
    has not built, or the font a KiCad board's text is lettered in."""
    missing = []
    if board.kicad_text and compose.newstroke_font() is None:
        missing.append(f"the newstroke font ({compose.FETCH_FONT})")
    statements = compose.statements_for(spec)
    for element in board.elements:
        row, _why = compose.drawn_from(element, statements)
        if row is None:
            continue
        if row.modelled:
            wanted = [compose.MODELLED / f"{row.model}.obj"]
        else:
            wanted = [compose.cached(row, row.url, ".step")]
            if row.footprint is not None:
                wanted.append(compose.cached(row, row.footprint, ".kicad_mod"))
        missing += [path.name for path in wanted if not path.is_file()]
    return sorted(set(missing))


def test_the_manifest_boards_compose_under_test(capsys):
    """**The composer's own refusals, in the suite's view** (OH-193): its
    turn, silkscreen, side and word checks exit the composer, and until this
    nothing ran it under pytest. Each manifest board composes, writing
    nothing, wherever its files and every model it draws are on disk and
    OpenCASCADE is installed; what is missing is named. A row the composer
    refuses by name is not missing anything: its reason is reported beside
    what composed, and `test_every_manifest_row_is_composed_from_that_row`
    holds that it is refused rather than drawn."""
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    composed, missing, refused = [], {}, {}
    for _row, spec in _manifest_specs():
        if spec is None:
            refused[_row.board] = compose.MANIFEST_REFUSED[_row.board]
            continue
        if not _fetched(spec):
            missing[_row.board] = ["its board or schematic file"]
            continue
        board = compose.read_layout(spec.layout)
        absent = _inputs_missing(spec, board)
        if absent:
            missing[spec.board] = absent
            continue
        try:
            compose.compose(spec, deflection=compose.DEFLECTION, check=True)
        except SystemExit as exc:
            pytest.fail(f"the composer refuses {spec.board}: {exc}")
        composed.append(spec.board)
    capsys.readouterr()
    if not composed:
        pytest.skip(f"SKIPPED: nothing to compose; missing {missing}; "
                    f"refused by name {refused}")
    if missing:
        pytest.skip(f"composed {composed}; missing {missing}; "
                    f"refused by name {refused}")


def test_a_board_not_fetched_is_skipped_and_the_rest_still_compose(monkeypatch,
                                                                   capsys):
    """`main` used to stop at the first board whose files were not fetched,
    so a checkout holding the Uno's board file and not its schematic
    composed nothing (OH-191). It reports each such board, composes the
    rest, and ends 3."""
    first, second = compose.COMPOSITIONS[0], compose.COMPOSITIONS[1]
    reached = []

    def fake(spec, deflection, check):
        reached.append(spec.board)
        return 3 if spec is first else 0

    monkeypatch.setattr(compose, "COMPOSITIONS", (first, second))
    monkeypatch.setattr(compose, "MANIFEST_REFUSED", {})
    monkeypatch.setattr(compose, "compose", fake)
    assert compose.main(["--check"]) == 3
    assert reached == [first.board, second.board]
    assert f"SKIPPED 1 board(s), their files not fetched: {first.board}" in (
        capsys.readouterr().out)


def test_a_manifest_row_in_neither_format_is_refused_by_name(capsys):
    """Every reading `manifest_composition` makes beyond the row is EAGLE's or
    KiCad's own field -- a preview colour and a design-rule stack, or a
    `(stackup ...)` and `(general (thickness ...))` (OH-195) -- so a row in
    any other format would be composed with a sentence about a file it is
    not. Such a row is refused by name, and the refusal is printed; a KiCad
    row beside it is composed.
    """
    from tools import board_manifest

    altium_row = dataclasses.replace(board_manifest.ROWS[0],
                                     board="An Altium row",
                                     cad="Hardware/board.PcbDoc")
    kicad_row = dataclasses.replace(board_manifest.ROWS[0],
                                    board="A KiCad row",
                                    cad="Hardware/board.kicad_pcb")
    made, refused = compose.manifest_compositions(
        (board_manifest.ROWS[0], altium_row, kicad_row))
    assert [spec.board for spec in made] == [board_manifest.ROWS[0].board,
                                             "A KiCad row"]
    assert "composition from a .pcbdoc manifest row is not supported" in (
        refused["An Altium row"])
    with mock.patch.object(compose, "MANIFEST_REFUSED", refused):
        assert compose.main(["--board", "An Altium row", "--check"]) == 2
    out = capsys.readouterr().out
    assert "An Altium row:" in out and "REFUSED" in out and "not supported" in out


def test_a_manufacturers_model_sits_on_the_board_whatever_its_z():
    """`pads_origin` reads an offset's x and y and ignores its z, a
    judgement with numbers under it: Espressif's MINI-1 footprint lifts its
    model half a millimetre, and the STEP's own lowest point is already on
    the board plane -- honoured, the module would float over the board it is
    soldered to. So what is checked is the premise: every manufacturer's
    model here bottoms out at its own z = 0, and at least one footprint
    states a z that would have lifted it.
    """
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    from tools import kicad as kicad_reader

    makers = [c for c in compose.CORRESPONDENCE if c.footprint is not None]
    assert makers, "no manufacturer's model is drawn"
    lifted = 0
    for component in makers:
        step = compose.cached(component, component.url, ".step")
        footprint = compose.cached(component, component.footprint, ".kicad_mod")
        if not step.is_file() or not footprint.is_file():
            pytest.skip("SKIPPED: run tools/compose_board_3d.py to fetch them")
        tree = kicad_reader.parse_sexp(footprint.read_text(encoding="utf-8"))
        z = [m.offset[2] for m in kicad_reader._models_of(tree)
             if pathlib.PurePosixPath(m.path).stem == component.model]
        lifted += any(value != 0.0 for value in z)
        _mesh, box = compose.component_mesh(component, compose.DEFLECTION)
        assert abs(box.zmin) < 0.05, (
            f"{component.model}'s lowest point is {box.zmin:.3f} mm from its "
            f"own z = 0, so resting that on the board is not right either"
        )
    assert lifted, "no footprint states a z, so ignoring one decides nothing"


def test_a_part_flipped_and_mirrored_is_the_right_way_up():
    """`under` is `flip != mirrored`, and the case nothing on a board has yet
    is both at once: a part hung under the board by its table row AND on the
    bottom face by its element is turned over twice -- the right way up, and
    in the same place as a part that is neither."""
    model = _model_box(2.0, 1.0, 1.0, "#262525", at=(0.7, 0.0))
    pads = (eagle.Pad("1", "smd", -0.85, 0.0, 0.5, 0.5, None),
            eagle.Pad("2", "smd", 0.85, 0.0, 0.5, 0.5, None))
    plain = compose.place(model, eagle.Element("C1", "L", "P", pads=pads),
                          0.0, 1.6, (0.0, 0.0))
    both = compose.place(model, eagle.Element("C1", "L", "P", pads=pads,
                                              mirrored=True),
                         0.0, 1.6, (0.0, 0.0), flip=True)
    for colour, (positions, _n, _i) in plain.groups.items():
        assert both.groups[colour][0] == pytest.approx(positions), colour


def test_a_mirrored_eagle_parts_model_lands_where_eagle_place_puts_its_pads():
    """**`place` moves a mesh the way `eagle.place` moves a pad** (OH-211).
    EAGLE's MRd turns a package by d and then mirrors it in x, and a model
    drawn over that package's pads has to go the same way, or at MR90 and
    MR270 -- where the two orders are half a turn apart -- the part stands
    half a turn round on its own copper. A vertex over each of an asymmetric
    package's two pads, in the package's own frame, lands on that pad as
    `eagle.place` puts it, at every quarter turn, mirrored or not."""
    local = {"1": (-1.0, 0.5), "2": (1.5, -0.3)}
    model = compose.Mesh({
        "#000001": ([-1.0, 0.5, 0.5], [0.0, 0.0, 1.0], [0]),
        "#000002": ([1.5, -0.3, 0.5], [0.0, 0.0, 1.0], [0]),
    })
    for rot in ("R0", "R90", "R180", "R270", "MR0", "MR90", "MR180", "MR270"):
        pads = {number: eagle.place(x, y, (8.0, 6.0), rot)
                for number, (x, y) in local.items()}
        element = eagle.Element(
            "U1", "L", "P",
            pads=tuple(eagle.Pad(number, "smd", x, y, 0.5, 0.5, None)
                       for number, (x, y) in pads.items()),
            x_mm=8.0, y_mm=6.0, rotation=float(rot.lstrip("MR")),
            mirrored=rot.startswith("M"))
        put = compose.place(model, element, 0.0, 1.6, (0.0, 0.0))
        for colour, number in (("#000001", "1"), ("#000002", "2")):
            p = put.groups[colour][0]
            assert (p[0], -p[2]) == pytest.approx(pads[number]), (rot, number)


def test_a_modules_pads_land_on_the_pads_at_every_turn():
    """`place` turns an `OverPads` origin with the model, so the point under
    the middle of the module's pads lands on the middle of the element's
    pads whatever the table's turn, the element's rotation or its mirror --
    a module is not always drawn at turn 0."""
    origin = (0.4, -1.1)
    body = _model_box(3.0, 5.0, 1.0, "#808080", at=(0.0, 0.0))
    marker = _model_box(0.001, 0.001, 0.001, "#ff00ff", at=origin)
    groups = {**body.groups, **marker.groups}
    module = compose.OverPads(groups, origin)
    pads = (eagle.Pad("1", "smd", 10.0, 20.0, 0.5, 0.5, None),
            eagle.Pad("2", "smd", 12.0, 21.0, 0.5, 0.5, None))
    anchor = (11.0, 20.5)
    for turn in (0.0, 90.0, 180.0, 270.0):
        for rotation in (0.0, 30.0):
            for mirrored in (False, True):
                element = eagle.Element("U1", "L", "P", pads=pads,
                                        rotation=rotation, mirrored=mirrored)
                put = compose.place(module, element, turn, 1.6, (0.0, 0.0))
                p = put.groups["#ff00ff"][0]
                x = sum(p[0::3]) / (len(p) // 3)
                y = -sum(p[2::3]) / (len(p) // 3)
                assert (x, y) == pytest.approx(anchor, abs=1e-6), (
                    f"turn {turn}, rotation {rotation}, mirrored {mirrored}: "
                    f"the module's pad origin lands at ({x:.3f}, {y:.3f})"
                )


def test_a_manufacturers_file_is_cached_by_the_commit_it_came_from():
    """Re-pinning `ESPRESSIF_KICAD` must fetch the new commit's files. Keyed
    by name alone, the old commit's STEP would be read under the new pin and
    nothing would say so; a KiCad model keeps its old name, so nothing
    already fetched is fetched again."""
    module = next(c for c in compose.CORRESPONDENCE if c.step is not None)
    repinned = dataclasses.replace(
        module, step=module.step.replace(compose.ESPRESSIF_KICAD.rsplit("/", 1)[1],
                                         "0" * 40))
    assert repinned.step != module.step
    assert (compose.cached(module, module.url, ".step")
            != compose.cached(repinned, repinned.url, ".step"))
    kicad_part = next(c for c in compose.CORRESPONDENCE
                      if c.step is None and not c.modelled)
    assert compose.cached(kicad_part, kicad_part.url, ".step") == (
        compose.CACHE / f"component-{kicad_part.slug}.step")


# --- a KiCad manifest row, read from what its own file states (OH-195) ---------


def _kicad_parts_file(*parts) -> pathlib.Path:
    """A KiCad board placing each `(library:name, reference, value, attr,
    has_pads)` at the same spot, two 0402 pads apiece where it has pads -- on
    disk, because the readers take a path."""
    import tempfile

    placed = []
    for lib_id, reference, value, attr, has_pads in parts:
        pads = "".join(
            f'\t\t(pad "{number}" smd rect (at {x} 0) (size 0.5 0.5) '
            f'(layers "F.Cu"))\n'
            for number, x in (("1", -0.48), ("2", 0.48))) if has_pads else ""
        placed.append(
            f'\t(footprint "{lib_id}"\n\t\t(layer "F.Cu")\n\t\t(at 10 10)\n'
            f'\t\t(property "Reference" "{reference}")\n'
            f'\t\t(property "Value" "{value}")\n'
            + (f"\t\t(attr {attr})\n" if attr else "") + pads + "\t)\n")
    path = pathlib.Path(tempfile.mkdtemp()) / "PARTS.kicad_pcb"
    path.write_text("(kicad_pcb\n\t(version 20241229)\n"
                    '\t(gr_rect (start 0 0) (end 20 20) (layer "Edge.Cuts"))\n'
                    + "".join(placed) + ")\n", encoding="utf-8")
    return path


def test_a_kicad_part_whose_file_states_nothing_of_its_kind_is_refused():
    """**OH-187's rule, on a board file that is its own schematic.** A KiCad
    footprint carries three statements of kind: KiCad's own passive library
    it came from, its reference's letters, and its value. Those that speak
    decide where they agree; where they disagree, or where none speaks, a
    part on a land that only passives are drawn on is refused -- a row does
    not get to decide what a part is."""
    path = _kicad_parts_file(
        ("Resistor_SMD:R_0402_1005Metric", "R1", "10k", "smd", True),
        ("Capacitor_SMD:C_0402_1005Metric", "7", "", "smd", True),
        ("MyParts:R_0402_1005Metric", "12", "", "smd", True),
        ("MyParts:R_0402_1005Metric", "X3", "", "smd", True),
        ("Resistor_SMD:R_0402_1005Metric", "C4", "100nF", "smd", True),
    )
    statements = compose.kicad_statements(path)
    elements = {e.name: e for e in compose.read_layout(path).elements}

    def drawn(name):
        return compose.drawn_from(elements[name], statements, path.name)

    # All three speak and agree.
    assert statements["R1"] == compose.Statement(
        "resistor", "R", "10k", word="Resistor_SMD")
    assert drawn("R1")[0].model == "R_0402_1005Metric"
    # KiCad's own library alone is a statement, and it decides.
    assert statements["7"] == compose.Statement(
        "capacitor", None, None, word="Capacitor_SMD")
    assert drawn("7")[0].model == "C_0402_1005Metric"
    # **Nothing speaks**: a library of the vendor's own, a reference with no
    # letters and a value with no unit. This is the ticket's DONE-WHEN.
    row, why = drawn("12")
    assert row is None and why.startswith(
        "nothing in PARTS.kicad_pcb states what kind of part 12 is"), why
    # The letters name some other kind.
    row, why = drawn("X3")
    assert row is None and "under the prefix X" in why, why
    # The library says resistor, the letters and the value capacitor.
    row, why = drawn("C4")
    assert row is None and "disagree" in why, why
    for said in ("Resistor_SMD saying resistor", "letters C saying capacitor",
                 "'100nF', which says capacitor"):
        assert said in why, (said, why)


def test_a_kicad_part_its_own_file_says_is_not_fitted_is_refused():
    """**What KiCad records for a part nobody fits** (OH-195): the `dnp` and
    `exclude_from_bom` attributes its footprint carries, and OH-187's closed
    vocabulary in the value of a passive. A footprint with no pad is ink --
    a logo -- and is counted as ink rather than refused, however it is
    marked; a chip valued NC is not a passive left off."""
    path = _kicad_parts_file(
        ("Resistor_SMD:R_0402_1005Metric", "R2", "10k", "smd dnp", True),
        ("Resistor_SMD:R_0402_1005Metric", "R3", "10k", "smd exclude_from_bom", True),
        ("Resistor_SMD:R_0402_1005Metric", "R4", "DNP", "smd", True),
        ("Capacitor_SMD:C_0402_1005Metric", "C5", "TBD", "smd", True),
        ("Package_TO_SOT_SMD:SOT-23-5", "U5", "NC", "smd", True),
        ("Graphics:LOGO", "G1", "LOGO",
         "board_only exclude_from_pos_files exclude_from_bom", False),
    )
    statements = compose.kicad_statements(path)
    assert statements["R2"].refused == "PARTS.kicad_pcb marks R2 dnp: not fitted"
    assert statements["R3"].refused == (
        "PARTS.kicad_pcb marks R3 exclude_from_bom: not fitted")
    assert statements["R4"].refused == "PARTS.kicad_pcb values R4 'DNP': not fitted"
    assert "whether it is fitted is not stated" in statements["C5"].refused
    assert statements["U5"].refused is None
    assert statements["G1"].refused is None
    for name in ("R2", "R3", "R4", "C5"):
        assert statements[name].kind is None, name


def test_a_kicad_reference_two_footprints_with_pads_share_is_refused():
    """**Two parts under one reference cannot both be read** (OH-195): the
    statements are keyed by reference, and the second silently replaced the
    first. Two footprints with pads under one name are refused, naming both;
    a footprint with no pad is ink, and under a name already read -- a logo's
    `G***`, a sign's `REF*` -- it is passed over, before a part or after it,
    without touching that part's statement."""
    path = _kicad_parts_file(
        ("Resistor_SMD:R_0402_1005Metric", "R1", "10k", "smd", True),
        ("Capacitor_SMD:C_0402_1005Metric", "R1", "100nF", "smd", True))
    with pytest.raises(ValueError) as caught:
        compose.kicad_statements(path)
    for said in ("PARTS.kicad_pcb", "'R1'", "Resistor_SMD:R_0402_1005Metric at (10 10)",
                 "Capacitor_SMD:C_0402_1005Metric at (10 10)"):
        assert said in str(caught.value), (said, str(caught.value))
    path = _kicad_parts_file(
        ("Graphics:LOGO", "G***", "LOGO", "board_only", False),
        ("Graphics:LOGO", "R3", "LOGO", "board_only", False),
        ("Resistor_SMD:R_0402_1005Metric", "R2", "10k", "smd", True),
        ("Resistor_SMD:R_0402_1005Metric", "R3", "4k7", "smd", True),
        ("Graphics:LOGO", "G***", "LOGO", "board_only", False),
        ("Graphics:LOGO", "R2", "LOGO", "board_only", False))
    statements = compose.kicad_statements(path)
    assert statements["R2"].value == "10k" and statements["R2"].kind == "resistor"
    assert statements["R3"].value == "4k7" and statements["R3"].kind == "resistor"
    assert "G***" in statements


def _kicad_stackup_file(stackup: str | None, general: str | None) -> pathlib.Path:
    """A KiCad board stating only its stackup and its general thickness."""
    import tempfile

    text = "(kicad_pcb\n\t(version 20241229)\n"
    if general is not None:
        text += f"\t(general\n\t\t(thickness {general})\n\t)\n"
    if stackup is not None:
        text += f"\t(setup\n\t\t(stackup\n{stackup}\t\t)\n\t)\n"
    path = pathlib.Path(tempfile.mkdtemp()) / "STACK.kicad_pcb"
    path.write_text(text + ")\n", encoding="utf-8")
    return path


def _two_layer_stack(mask: str | None, core: str, under: str | None = None) -> str:
    colour = f' (color "{mask}")' if mask is not None else ""
    named = f' (color "{under}")' if under is not None else ""
    return (f'\t\t\t(layer "F.Mask" (type "Top Solder Mask"){colour} (thickness 0.01))\n'
            f'\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n'
            f'\t\t\t(layer "dielectric 1" (type "core"){named} (thickness {core}) (material "FR4"))\n'
            f'\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))\n'
            f'\t\t\t(layer "B.Mask" (type "Bottom Solder Mask"){colour} (thickness 0.01))\n')


def _over(rgb, alpha: float, under) -> str:
    """`rgb` laid at `alpha` over an opaque `under`, as `#rrggbb`: the blend
    an EAGLE preview and KiCad's 3D view both draw, written out again here
    so the composer's own arithmetic is not what checks it."""
    return "#" + "".join(f"{round(a * alpha + b * (1 - alpha)):02x}"
                         for a, b in zip(rgb, under))


def test_kicads_mask_and_board_colours_are_its_own_3d_views():
    """**The colours a KiCad row is drawn in are the ones KiCad's own 3D view
    draws** (OH-195): `g_MaskColors` and `g_BoardColors` in
    3d-viewer/3d_canvas/board_adapter.cpp, lines 169-184 and 195-203 at
    commit 3ff0b3cc57dd043ac6b159611d85a01374df7a88, copied a second time
    here so that changing either copy fails. The table was `gbrjobColors`
    first, whose "Green" is 60, 150, 80 -- a Gerber job file writes the
    NAME -- and a mutant changing an entry survived every test."""
    assert compose.KICAD_MASK_COLOURS == {
        "Green": ((20, 51, 36), 0.83),
        "Light Green": ((91, 168, 12), 0.83),
        "Saturated Green": ((13, 104, 11), 0.83),
        "Red": ((181, 19, 21), 0.83),
        "Light Red": ((210, 40, 14), 0.83),
        "Red/Orange": ((239, 53, 41), 0.83),
        "Blue": ((2, 59, 162), 0.83),
        "Light Blue 1": ((54, 79, 116), 0.83),
        "Light Blue 2": ((61, 85, 130), 0.83),
        "Green/Blue": ((21, 70, 80), 0.83),
        "Black": ((11, 11, 11), 0.83),
        "White": ((245, 245, 245), 0.83),
        "Purple": ((32, 2, 53), 0.83),
        "Light Purple": ((119, 31, 91), 0.83),
        "Yellow": ((194, 195, 0), 0.83),
    }
    assert compose.KICAD_BOARD_COLOURS == {
        "FR4 natural, dark": (51, 43, 22),
        "FR4 natural": (109, 116, 75),
        "PTFE natural": (252, 252, 250),
        "Polyimide": (205, 130, 0),
        "Phenolic natural": (92, 17, 6),
        "Brown 1": (146, 99, 47),
        "Brown 2": (160, 123, 54),
        "Brown 3": (146, 99, 47),
        "Aluminum": (213, 213, 213),
    }


def test_a_kicad_rows_colour_and_thickness_are_what_its_stackup_states():
    """**A KiCad board file states its colour and thickness in its
    `(stackup ...)`** (OH-195), where an EAGLE one states them in a preview
    and a note. A mask is drawn as KiCad's own 3D view draws it -- a named
    one in that view's colour for the name and at its alpha, a `#rrggbbaa`
    at the alpha it states -- laid over the dielectric's own colour where
    the stackup names one, and KiCad's FR4 where it does not, as an EAGLE
    row's mask is laid over its substrate; each a judgement, and said to
    be. The stackup's layers must add up to `(general (thickness))` for
    either number to be believed: KiCad writes the general thickness on
    every board whether anybody set it or not."""
    from tools import board_manifest, board_sources

    row = next(r for r in board_manifest.ROWS
               if r.cad.endswith(".kicad_pcb"))
    source = board_sources.source(row.source)

    def composed(stackup, general):
        return compose._kicad_manifest_composition(
            row, source, _kicad_stackup_file(stackup, general))

    # Black, 11, 11, 11 at 0.83, over KiCad's FR4 natural, 109, 116, 75:
    # the stackup names no colour for its core.
    black = composed(_two_layer_stack("Black", "1.51"), "1.6")
    assert black.colour == "#1c1d16" == _over((11, 11, 11), 0.83, (109, 116, 75))
    for said in ("'Black'", "A JUDGEMENT", "no colour for its dielectric"):
        assert said in black.colour_source, (said, black.colour_source)
    assert black.thickness_mm == 1.6
    # A dielectric the stackup names is what the mask is laid over.
    flex = composed(_two_layer_stack("Black", "1.51", "Polyimide"), "1.6")
    assert flex.colour == "#2c1f09" == _over((11, 11, 11), 0.83, (205, 130, 0))
    assert "'Polyimide'" in flex.colour_source, flex.colour_source
    # **A colour's own alpha is drawn, not dropped**: 0xD4 is 212/255.
    custom = composed(_two_layer_stack("#1B1B1BD4", "0.71"), "0.8")
    assert custom.colour == "#292a23" == _over((27, 27, 27), 212 / 255, (109, 116, 75))
    for said in ("#1B1B1BD4", "212/255", "A JUDGEMENT"):
        assert said in custom.colour_source, (said, custom.colour_source)
    assert custom.thickness_mm == 0.8
    # And one stating none is opaque, as KiCad reads it.
    assert composed(_two_layer_stack("#1B1B1B", "0.71"), "0.8").colour == "#1b1b1b"
    # Layers that do not add up to the general thickness decide nothing.
    assert composed(_two_layer_stack("Black", "1.51"), "1.2").thickness_mm == (
        compose.MANIFEST_THICKNESS_MM)
    # No stackup: a general thickness alone is KiCad's default as often as
    # anybody's statement, and there is no mask to read.
    bare = composed(None, "1.6")
    assert bare.colour == compose.BOARD_MASK and "A JUDGEMENT" in bare.colour_source
    assert bare.thickness_mm == compose.MANIFEST_THICKNESS_MM
    unnamed = composed(_two_layer_stack(None, "1.51"), "1.6")
    assert unnamed.colour == compose.BOARD_MASK
    assert "names no colour" in unnamed.colour_source, unnamed.colour_source
    # **A name KiCad's view does not draw is said to be one**, not passed
    # off as no name at all.
    matte = composed(_two_layer_stack("Matte Black", "1.51"), "1.6")
    assert matte.colour == compose.BOARD_MASK
    assert "'Matte Black'" in matte.colour_source, matte.colour_source
    assert "names no colour" not in matte.colour_source, matte.colour_source


def test_a_kicad_stackup_thickness_that_is_not_a_number_is_named():
    """A stackup thickness that is not a number fails naming the file, the
    layer and the words it found (OH-195), not as a bare ValueError."""
    path = _kicad_stackup_file(_two_layer_stack("Green", "1.5x"), "1.6")
    with pytest.raises(ValueError) as caught:
        compose.kicad_stackup(path)
    for said in (str(path), "'dielectric 1'", "'1.5x'"):
        assert said in str(caught.value), (said, str(caught.value))


# --- a KiCad 5 row (OH-198) ------------------------------------------------------

#: The hand-written twin boards of tests/rules/test_kicad.py: one board,
#: written once as KiCad 5 writes it and once as KiCad 7 does.
KICAD5_TWINS = pathlib.Path(__file__).resolve().parent / "kicad5"
C6_EVB_SHA = "7b66d23cabba3c573a1e63d83363675b5fb74f06"


def _c6_evb_file(name: str) -> pathlib.Path:
    """One of the ESP32-C6-EVB's two board files, found by name below
    `OH_KICAD5_BOARDS` or the registry's checkout, or a skip saying how to
    get it: the registry row fetches both the KiCad 5 board and its KiCad 7
    copy in HARDWARE/Dimensions/."""
    import os

    for root in (os.environ.get("OH_KICAD5_BOARDS"),
                 REPO / "third_party" / "olimex-esp32-c6-evb"):
        found = sorted(pathlib.Path(root).rglob(name)) if root and pathlib.Path(
            root).is_dir() else []
        if found:
            return found[0]
    pytest.skip(f"SKIPPED: no {name}; python tools/get_board_sources.py "
                f"olimex-esp32-c6-evb fetches it, as of {C6_EVB_SHA}, or set "
                f"OH_KICAD5_BOARDS to a directory holding it")


def test_a_kicad_5_boards_parts_state_what_its_kicad_7_twin_states():
    """**A KiCad 5 board stated nothing** (OH-198): `kicad_statements`
    walked the `(footprint ...)` a KiCad 5 file never writes -- it places
    every part as `(module ...)` -- and refused every passive on it as a
    part whose kind nothing states. Read through `kicad.board_tree`, the
    KiCad 5 twin states what the KiCad 7 one does, part by part."""
    old = compose.kicad_statements(KICAD5_TWINS / "twin-kicad5.kicad_pcb")
    new = compose.kicad_statements(KICAD5_TWINS / "twin-kicad7.kicad_pcb")
    assert old == new
    assert (old["R1"].kind, old["R1"].value, old["R1"].models) == (
        "resistor", "10k", ("R_0603_1608Metric",))


def test_the_c6_evbs_kicad_5_board_states_a_part_for_every_reference():
    """On Olimex's own KiCad 5 board: walked as written it holds no
    `(footprint ...)` at all, and read through `kicad.board_tree` every
    reference it places is stated -- the padless signs once each, as
    `kicad_statements` keys them."""
    path = _c6_evb_file("ESP32-C6-EVB_Rev_A.kicad_pcb")
    assert not kicad.children(kicad.parse_sexp(path.read_text(encoding="utf-8")),
                              "footprint")
    stated = compose.kicad_statements(path)
    assert set(stated) == {placed.reference for placed in kicad.read_board(path).placements}
    assert stated["R11"].kind == "resistor" and stated["C10"].kind == "capacitor"


def test_the_c6_evbs_kicad_5_board_states_each_part_as_its_kicad_7_copy_does():
    """The KiCad 5 board against the KiCad 7 copy of it Olimex keep in
    HARDWARE/Dimensions/: the same parts stated the same way, every one, but
    for the file each refusal names. The copy names every model in KiCad's
    own directory and the board in its own, and a model is held to by its
    file's stem, which is alike."""
    old_path = _c6_evb_file("ESP32-C6-EVB_Rev_A.kicad_pcb")
    new_path = _c6_evb_file("ESP32-C6-EVB_DIMM_Rev_A.kicad_pcb")

    def stated(path):
        return {name: dataclasses.replace(said, refused=said.refused.replace(
                    path.name, "BOARD") if said.refused else None)
                for name, said in compose.kicad_statements(path).items()}

    old, new = stated(old_path), stated(new_path)
    assert old == new
    assert len(old) == len({placed.reference
                            for placed in kicad.read_board(new_path).placements})


def test_the_c6_evbs_module_refusal_quotes_what_its_own_footprint_says():
    """U3's refusal (`compose.ABSENT`) is that its footprint names one module
    and places a model of another, and it quotes the footprint for both: its
    own `descr`, the datasheet its `tags` give, and the model it places, each
    as Olimex's KiCad 5 board writes it (OH-198)."""
    path = _c6_evb_file("ESP32-C6-EVB_Rev_A.kicad_pcb")
    (u3,) = [node for node in kicad.children(kicad.board_tree(path), "footprint")
             if kicad._reference_of(node) == "U3"]
    why = compose.ABSENT[u3[1].split(":", 1)[1]]
    descr, tags = kicad.first(u3, "descr")[1].strip(), kicad.first(u3, "tags")[1]
    assert tags.startswith("https://www.espressif.com/"), tags
    models = [pathlib.PurePosixPath(model.path).name for model in kicad._models_of(u3)]
    assert models == ["ESP32-WROOM-32D-56544.STEP"], models
    for said in (descr, pathlib.PurePosixPath(tags).name, *models):
        assert said in why, (said, why)


def test_a_part_olimex_values_na_is_not_fitted(tmp_path):
    """**NA is Olimex's not assembled** (OH-198, `compose.NOT_ASSEMBLED`):
    read as the whole value or before a slash or a parenthesis, of any
    part -- a header as well as a resistor, since NA names nothing a
    connector could otherwise be -- in a KiCad board file and an EAGLE
    schematic alike; in capitals only, since `nA` is a current; and not as
    the start of a longer word."""
    path = _kicad_parts_file(
        ("OLIMEX_RLC-FP:R_0402_5MIL_DWS", "R9", "NA/R0402", "smd", True),
        ("OLIMEX_RLC-FP:R_0402_5MIL_DWS", "R33", "NA(2.2k/R0402)", "smd", True),
        ("OLIMEX_RLC-FP:R_0402_5MIL_DWS", "R5", "NA", "smd", True),
        ("OLIMEX_Connectors-FP:HN1x10", "EXT1", "NA(HN1x10)", "", True),
        ("OLIMEX_RLC-FP:R_0402_5MIL_DWS", "R6", "2.2k/R0402", "smd", True),
        ("Package_SO:SOIC-8", "U1", "nA(typ)", "smd", True),
        ("Package_SO:SOIC-8", "U2", "NAND", "smd", True),
        ("Package_SO:SOIC-8", "U3", "NA1", "smd", True),
    )
    statements = compose.kicad_statements(path)
    for name, value in (("R9", "NA/R0402"), ("R33", "NA(2.2k/R0402)"), ("R5", "NA"),
                        ("EXT1", "NA(HN1x10)")):
        assert statements[name].refused == (
            f"PARTS.kicad_pcb values {name} {value!r}, whose first word, NA, is not "
            f"assembled as Olimex write it (NOT_ASSEMBLED): not fitted"), name
    for name in ("R6", "U1", "U2", "U3"):
        assert statements[name].refused is None, (name, statements[name])
    stated = compose.stated_kinds(_schematic(tmp_path, (
        '<part name="R9" library="lib" deviceset="RESISTOR" value="NA/R0402"/>'
        '<part name="CONN1" library="lib" deviceset="CONN" value="NA(WU06S)"/>'
        '<part name="U1" library="lib" deviceset="CHIP" value="nA(typ)"/>')))
    assert "NOT_ASSEMBLED" in stated["R9"].refused and "NOT_ASSEMBLED" in stated[
        "CONN1"].refused
    assert stated["U1"].refused is None


def test_a_kicad_5_part_marked_virtual_is_not_read_as_not_fitted(tmp_path):
    """**KiCad 5's `(attr virtual)` says a part is not placed by machine**,
    not that it is not there (OH-198): KiCad 5.1 leaves the part out of the
    position file, and its own 3D viewer draws the part's model by default.
    So a footprint with pads that KiCad 5 marks virtual is stated as any
    other, where KiCad 7's `exclude_from_bom` on the same part refuses it
    (`test_a_kicad_part_its_own_file_says_is_not_fitted_is_refused`).
    Olimex's ESP32-PoE is why it matters: its KiCad 5 revisions mark
    LAN_CON1, the RJ45 jack, virtual."""
    path = tmp_path / "VIRTUAL.kicad_pcb"
    path.write_text(
        "(kicad_pcb (version 20171130) (host pcbnew 5.1.6)\n"
        "  (layers (0 F.Cu signal) (31 B.Cu signal))\n"
        "  (module Conn:RJ45 (layer F.Cu) (at 10 10)\n"
        "    (attr virtual)\n"
        "    (fp_text reference LAN_CON1 (at 0 0) (layer F.SilkS))\n"
        "    (fp_text value RJ45 (at 0 0) (layer F.Fab))\n"
        "    (pad 1 thru_hole circle (at 0 0) (size 1.5 1.5) (drill 0.9) (layers *.Cu *.Mask)))\n"
        "  (module Resistor_SMD:R_0402_1005Metric (layer F.Cu) (at 20 10)\n"
        "    (attr virtual)\n"
        "    (fp_text reference R7 (at 0 0) (layer F.SilkS))\n"
        "    (fp_text value 10k (at 0 0) (layer F.Fab))\n"
        "    (pad 1 smd rect (at -0.48 0) (size 0.56 0.62) (layers F.Cu))\n"
        "    (pad 2 smd rect (at 0.48 0) (size 0.56 0.62) (layers F.Cu))))\n",
        encoding="utf-8")
    statements = compose.kicad_statements(path)
    assert statements["LAN_CON1"].refused is None
    assert statements["R7"] == compose.Statement(
        "resistor", "R", "10k", word="Resistor_SMD")
    poe = REPO / "third_party" / "olimex-esp32-poe" / "HARDWARE" / (
        "ESP32-PoE-hardware-revision-D") / "ESP32-PoE_Rev_D.kicad_pcb"
    if not poe.is_file():
        pytest.skip(f"SKIPPED after the written board: no {poe}; python "
                    f"tools/get_board_sources.py olimex-esp32-poe")
    (lan,) = [node for node in kicad.children(kicad.board_tree(poe), "footprint")
              if kicad._reference_of(node) == "LAN_CON1"]
    assert kicad.first(lan, "attr")[1:] == ["virtual"]
    assert compose.kicad_statements(poe)["LAN_CON1"].refused is None


def test_a_kicad_5_rows_colour_says_its_format_states_none(tmp_path):
    """**A KiCad 5 file has no stackup** (OH-198): KiCad 5.1 writes a board's
    thickness in `(general ...)` and no colour for any layer. Its mask is
    BOARD_MASK, a judgement, and the colour source says why in those words
    rather than that a stackup it never had names none."""
    from tools import board_manifest, board_sources

    row = next(r for r in board_manifest.ROWS if r.board == "Olimex ESP32-C6-EVB")
    path = tmp_path / "OLD.kicad_pcb"
    path.write_text("(kicad_pcb (version 20171130) (host pcbnew 5.1.0)\n"
                    "  (general (thickness 1.6)))\n", encoding="utf-8")
    spec = compose._kicad_manifest_composition(
        row, board_sources.source(row.source), path)
    assert spec.colour == compose.BOARD_MASK
    for said in ("A JUDGEMENT", "KiCad 5's, version 20171130", "has no stackup",
                 "(general (thickness ...))"):
        assert said in spec.colour_source, (said, spec.colour_source)
    assert "names no colour for its top solder mask" not in spec.colour_source
    assert spec.thickness_mm == compose.MANIFEST_THICKNESS_MM
    # Told by the version the file states, as `kicad.board_tree` tells it,
    # and not by its first line's spelling: one that KiCad 5 would never
    # write but reads alike is the same KiCad 5 board.
    spaced = tmp_path / "SPACED.kicad_pcb"
    spaced.write_text("(kicad_pcb\n  (version 20171130)\n  (host pcbnew 5.1.0)\n"
                      "  (general (thickness 1.6)))\n", encoding="utf-8")
    assert kicad.board_version(kicad.board_tree(spaced)) == kicad.KICAD5_VERSION
    assert compose._kicad_manifest_composition(
        row, board_sources.source(row.source), spaced).colour_source == spec.colour_source


def test_the_glyph_mini_is_drawn_in_what_its_own_stackup_states():
    """PCBCUPID's file states a green top mask over 'FR4 natural' and a
    stackup adding up to its general 1.6 mm, so both numbers are the
    file's, and the model's parts are read out of that same file. The
    colour is KiCad's 3D view's Green, 20, 51, 36 at 0.83, over its FR4
    natural, 109, 116, 75."""
    spec = next((s for s in compose.COMPOSITIONS
                 if s.board == "PCBCUPID Glyph Mini RP2040"), None)
    assert spec is not None, "the Glyph Mini is a KiCad row and is composed"
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    assert spec.colour == "#233e2b"
    assert "'Green'" in spec.colour_source and "'FR4 natural'" in spec.colour_source
    assert spec.thickness_mm == 1.6
    assert spec.schematic == spec.layout


def test_the_thing_plus_c5_is_drawn_at_the_alpha_its_stackup_states():
    """SparkFun's stackup states its mask as #E0311DD4 -- red at alpha
    212/255 -- and names no colour for its dielectric (OH-195). Its alpha
    was dropped and the board drawn #e0311d; it is laid over KiCad's FR4,
    as a named mask is."""
    spec = next((s for s in compose.COMPOSITIONS
                 if s.board == "SparkFun Thing Plus ESP32-C5"), None)
    assert spec is not None, "the Thing Plus C5 is a KiCad row and is composed"
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    assert spec.colour == "#cd3c25" == _over((224, 49, 29), 212 / 255, (109, 116, 75))
    assert "#E0311DD4" in spec.colour_source and "212/255" in spec.colour_source


#: A KiCad footprint on the underside, placed the way KiCad stores one: its
#: pads, its F.Fab-become-B.Fab body, its pin-1 dot and its silkscreen line
#: all flipped top to bottom already, from a library footprint whose pad 1 is
#: at (-1.0, -0.5), pad 2 at (1.0, 0.5), body (-1.3, -0.8)-(1.3, 0.6), dot at
#: (-1.6, -0.9) and silkscreen line (-1.3, -1.0)-(0.5, -1.0). The same
#: footprint on the top face is stored as the library has it.
_SIDED = """(kicad_pcb
\t(version 20241229)
\t(gr_rect (start 10 20) (end 30 40) (layer "Edge.Cuts"))
\t(footprint "Lib:PART"
\t\t(layer "{copper}")
\t\t(at 20 30 {rotation})
\t\t(property "Reference" "U1")
\t\t(fp_rect (start -1.3 {top}) (end 1.3 {bottom}) (layer "{fab}"))
\t\t(fp_circle (center -1.6 {dot}) (end -1.5 {dot}) (layer "{fab}"))
\t\t(fp_line (start -1.3 {line}) (end 0.5 {line}) (stroke (width 0.12) (type solid)) (layer "{silk}"))
\t\t(pad "1" smd rect (at -1.0 {one} {rotation}) (size 0.6 0.4) (layers "{copper}"))
\t\t(pad "2" smd rect (at 1.0 {two} {rotation}) (size 0.6 0.4) (layers "{copper}"))
\t)
)
"""


def test_an_underside_kicad_part_lands_where_its_own_file_puts_it():
    """**KiCad stores an underside footprint already flipped, so it is not
    flipped again** (OH-195, after OH-182). Its pads, its body outline, its
    pin-1 dot and its silkscreen (OH-184) all land where the file puts them
    -- through the one transform the pads have always used, which the copper
    checks and the vendors' Gerbers check for the ink -- and a model built on
    the library footprint lands with its pad 1 on pad 1. The top face is held
    to the same, so the two sides cannot drift apart.
    """
    import tempfile

    rotation = 30.0
    turn = math.radians(rotation)

    def on_board(x, y):
        # The pads' own transform (`kicad.pad_on_board`), read into this
        # module's y-up frame.
        return (20 + x * math.cos(turn) + y * math.sin(turn),
                -30 + x * math.sin(turn) - y * math.cos(turn))

    # The model: a vertex over each of the library's pads, in a model's
    # y-up frame, where the library's y is negated.
    model = compose.Mesh({
        "#000001": ([-1.0, 0.5, 0.5], [0.0, 0.0, 1.0], [0]),
        "#000002": ([1.0, -0.5, 0.5], [0.0, 0.0, 1.0], [0]),
    })
    for side, flip in (("F", 1.0), ("B", -1.0)):
        stored = {"one": -0.5 * flip, "two": 0.5 * flip, "dot": -0.9 * flip,
                  "top": min(-0.8 * flip, 0.6 * flip),
                  "bottom": max(-0.8 * flip, 0.6 * flip), "line": -1.0 * flip}
        path = pathlib.Path(tempfile.mkdtemp()) / "SIDED.kicad_pcb"
        path.write_text(_SIDED.format(copper=f"{side}.Cu", fab=f"{side}.Fab",
                                      silk=f"{side}.SilkS", rotation=rotation,
                                      **stored),
                        encoding="utf-8")
        board = compose.read_layout(path)
        element = board.element("U1")
        assert element.mirrored == (side == "B")
        (ink,) = board.silk
        assert ink.layer == f"{side}.SilkS"
        assert ((ink.x1_mm, ink.y1_mm), (ink.x2_mm, ink.y2_mm)) == (
            pytest.approx(on_board(-1.3, stored["line"])),
            pytest.approx(on_board(0.5, stored["line"]))), side
        pads = {pad.number: (pad.x_mm, pad.y_mm) for pad in element.pads}
        assert pads["1"] == pytest.approx(on_board(-1.0, stored["one"]))
        assert pads["2"] == pytest.approx(on_board(1.0, stored["two"]))
        assert compose.mark_of(element) == pytest.approx(
            on_board(-1.6, stored["dot"])), side
        spelling = ("MR" if element.mirrored else "R") + str(int(element.rotation))
        x0, y0, x1, y1 = element.silk
        drawn = sorted(eagle.place(x, y, (element.x_mm, element.y_mm), spelling)
                       for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
        filed = sorted(on_board(x, y) for x, y in (
            (-1.3, stored["top"]), (1.3, stored["top"]),
            (1.3, stored["bottom"]), (-1.3, stored["bottom"])))
        for got, want in zip(drawn, filed):
            assert got == pytest.approx(want), (side, drawn, filed)
        put = compose.place(model, element, 0.0, 1.6, (0.0, 0.0))
        for colour, number in (("#000001", "1"), ("#000002", "2")):
            p = put.groups[colour][0]
            assert (p[0], -p[2]) == pytest.approx(pads[number]), (side, number)
        assert (put.groups["#000001"][0][1] < 0) == (side == "B"), (
            "an underside part hangs under the board")


def test_the_glyph_headers_are_refused_for_the_pair_of_holes_under_each_pin():
    """`GLYPH_HEADER` says why J3, J4 and J5 are not drawn, and each thing it
    says is read here out of PCBCUPID's own file: every pin is two plated
    holes 1.5 mm apart, and their footprint hangs KiCad's PinHeader under
    the row, turned half round and dropped 1.5 mm. It is a refusal and not
    copper, because a body is placed there."""
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "PCBCUPID Glyph Mini RP2040")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    tree = kicad.parse_sexp(spec.layout.read_text(encoding="utf-8"))
    footprints = {kicad._reference_of(node): node
                  for node in kicad.children(tree, "footprint")}
    for name in ("J3", "J4", "J5"):
        element = board.element(name)
        assert compose.absent_why(element) == compose.GLYPH_HEADER
        assert compose.NO_BODY not in compose.GLYPH_HEADER
        pairs: dict[str, list] = {}
        for pad in element.pads_of("thru_hole"):
            pairs.setdefault(pad.number, []).append((pad.x_mm, pad.y_mm))
        assert pairs and all(len(pair) == 2 for pair in pairs.values()), name
        for number, (one, two) in pairs.items():
            assert math.dist(one, two) == pytest.approx(1.5, abs=1e-6), (name, number)
        (model,) = kicad._models_of(footprints[name])
        assert "Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x" in model.path
        assert tuple(abs(a) for a in model.rotate) == (0.0, 180.0, 0.0), name
        assert model.offset == (0.0, 0.0, -1.5), name


def test_a_plain_kicad_header_is_not_refused_for_the_glyphs_castellated_rows(capsys):
    """**The Glyph's reason is keyed to the Glyph's library** (OH-195).
    PCBCUPID keep their castellated rows in `Conn_Castellated_Holes_2.54mm`
    under the names of KiCad's own plain headers, so a board placing KiCad's
    `PinHeader_1x05_P2.54mm_Vertical` from KiCad's library places another
    part: it is not refused with the Glyph's pair-of-holes reason, and with
    no row to draw it is counted unmodelled, as any land nothing explains."""
    path = _kicad_parts_file(
        ("Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
         "J1", "Conn_01x05", "", True),
        ("Conn_Castellated_Holes_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
         "J3", "Conn_01x05", "", True))
    assert set(compose.ABSENT_ONLY_FROM) <= set(compose.ABSENT), (
        "an ABSENT_ONLY_FROM key that is no ABSENT key restricts nothing")
    elements = {e.name: e for e in compose.read_layout(path).elements}
    assert compose.absent_why(elements["J1"]) is None
    assert compose.absent_why(elements["J3"]) == compose.GLYPH_HEADER
    spec = compose.Composition(
        board="HEADERS", layout=path, fetch_with="", pcb_chip=None,
        geometry="", headers=("J1",), thickness_mm=1.6,
        colour=compose.BOARD_MASK, colour_source="", schematic=path)
    with mock.patch.object(compose, "CORRESPONDENCE", ()):
        compose.compose(spec, deflection=0.05, check=True)
    out = capsys.readouterr().out
    assert "no model 1 placement(s)" in out and (
        "J1 (PinHeader_1x05_P2.54mm_Vertical)" in out), out
    assert "absent  J3 (PinHeader_1x05_P2.54mm_Vertical): J3, J4 and J5" in out, out
    assert "absent  J1" not in out and "J1/J3" not in out and "J3/J1" not in out, out


def test_the_glyph_usb_socket_lands_where_its_own_footprint_puts_it():
    """**J2 is drawn from the model PCBCUPID's footprint places, and where
    that footprint places it.** Their land is Palconn's and the model GCT's,
    moved by an `(offset ...)`; `place` anchors the model on its shell tabs
    and knows nothing of the offset. The model's own origin must still land
    where the vendor's offset puts it -- which it does to a few hundredths
    of a millimetre, against the 1.25 mm the offset moves it."""
    pytest.importorskip("OCP", reason="OpenCASCADE is needed to tessellate")
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "PCBCUPID Glyph Mini RP2040")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    board = compose.read_layout(spec.layout)
    element = board.element("J2")
    row, _why = compose.drawn_from(element, compose.statements_for(spec))
    if not compose.cached(row, row.url, ".step").is_file():
        pytest.skip(f"SKIPPED: {row.model}.step is not fetched")
    tree = kicad.parse_sexp(spec.layout.read_text(encoding="utf-8"))
    (footprint,) = [node for node in kicad.children(tree, "footprint")
                    if kicad._reference_of(node) == "J2"]
    (stated,) = kicad._models_of(footprint)
    assert pathlib.PurePosixPath(stated.path).stem == row.model
    mesh, _box = compose.component_mesh(row, 0.05)
    marked = compose.Mesh({**mesh.groups,
                           "#000001": ([0.0, 0.0, 5.0], [0.0, 0.0, 1.0], [0])})
    put = compose.place(marked, element, row.turn, spec.thickness_mm, (0.0, 0.0))
    origin = put.groups["#000001"][0]
    # A model's offset is in its own y-up frame, turned with the footprint.
    turn = math.radians(element.rotation)
    ox, oy = stated.offset[0], stated.offset[1]
    want = (element.x_mm + ox * math.cos(turn) - oy * math.sin(turn),
            element.y_mm + ox * math.sin(turn) + oy * math.cos(turn))
    assert math.dist((origin[0], -origin[2]), want) < 0.05, (origin, want)
    assert math.hypot(ox, oy) > 1.0, "the offset no longer moves the model"


def test_a_kicad_row_draws_only_the_model_its_own_footprint_places(
        monkeypatch, tmp_path):
    """**A KiCad footprint states the model it places** (OH-195), and one
    land can carry two parts on two boards: PCBCUPID put GCT's USB4105 on
    the Glyph Mini's Palconn land and HRO's TYPE-C-31-M-12 on the Glyph C3's
    and C6's. So on a KiCad board a row draws only the model the footprint
    places, or one the row says stands for it, and anything else is refused
    with both names. A hidden alternate is no statement, and a footprint
    that names no model leaves the row to say. A footprint with no
    reference is keyed as `from_kicad` names it, by its library id."""
    def footprint(reference, models):
        blocks = "".join(f'\t\t(model "{path}"{" (hide yes)" if hidden else ""})\n'
                         for path, hidden in models)
        named = f'\t\t(property "Reference" "{reference}")\n' if reference else ""
        return ('\t(footprint "Lib:LAND"\n\t\t(layer "F.Cu")\n\t\t(at 10 10)\n'
                + named + '\t\t(property "Value" "X")\n\t\t(attr smd)\n'
                '\t\t(pad "1" smd rect (at -1 0) (size 0.5 0.5) (layers "F.Cu"))\n'
                '\t\t(pad "2" smd rect (at 1 0) (size 0.5 0.5) (layers "F.Cu"))\n'
                + blocks + "\t)\n")

    path = tmp_path / "MODELS.kicad_pcb"
    path.write_text(
        "(kicad_pcb\n\t(version 20241229)\n"
        '\t(gr_rect (start 0 0) (end 20 20) (layer "Edge.Cuts"))\n'
        + footprint("U1", [("${KICAD9_3DMODEL_DIR}/Lib.3dshapes/MODEL_A.step", False)])
        + footprint("U2", [("F:/their disk/MODEL_B.step", False)])
        + footprint("U3", [("${KIPRJMOD}/packages3D/MODEL_C.stp", False)])
        + footprint("U4", [("F:/their disk/MODEL_B.step", True)])
        + footprint("U5", [])
        + footprint("", [("F:/their disk/MODEL_B.step", False)])
        + ")\n", encoding="utf-8")
    row = compose.Component("LAND", "Lib", "MODEL_A",
                            "a two-pad land, its pads 2.00 mm apart")
    monkeypatch.setattr(compose, "CORRESPONDENCE", (row,))
    statements = compose.kicad_statements(path)
    elements = {e.name: e for e in compose.read_layout(path).elements}

    def drawn(name):
        return compose.drawn_from(elements[name], statements, path.name)

    assert statements["U1"].models == ("MODEL_A",)
    assert drawn("U1") == (row, None)
    assert drawn("U2") == (None, (
        "MODELS.kicad_pcb's footprint for U2 places MODEL_B, and the row for "
        "its land, LAND, draws MODEL_A, which is not that and does not say it "
        "stands for it: drawing it would put a part on the board that its own "
        "file does not"))
    assert drawn("U3")[0] is None
    assert drawn("U4") == (row, None), "a hidden alternate is not a statement"
    assert drawn("U5") == (row, None)
    assert drawn("Lib:LAND")[0] is None, "the unreferenced footprint's model unread"
    # A row that says what it stands for is drawn there, and still where
    # the footprint names its own model.
    stand_in = dataclasses.replace(row, stands_for=("MODEL_C",))
    monkeypatch.setattr(compose, "CORRESPONDENCE", (stand_in,))
    assert drawn("U3") == (stand_in, None)
    assert drawn("U1") == (stand_in, None)
    assert drawn("U2")[0] is None


def test_a_kicad_parts_value_is_held_to_its_row_as_an_eagle_parts_is():
    """PCBCUPID place the Glyph C3's module on a land named for the
    ESP32-H2-MINI-1 and value it ESP32-C3-MINI-1-N4 (OH-195). Espressif's own
    footprints for the H2-, C3- and C6-MINI-1 put down one land, so the value
    is the word that names the chip, and `contradiction` reads a KiCad
    part's value as it reads an EAGLE element's: the C3 module is drawn
    there, and a C6 module on that land would be refused."""
    path = _kicad_parts_file(
        ("ESP32C3:ESP32-H2-MINI-1_EXP", "U4", "ESP32-C3-MINI-1-N4", "smd", True))
    element = compose.read_layout(path).element("U4")
    assert element.value == "ESP32-C3-MINI-1-N4"
    c3 = next(row for row in compose.CORRESPONDENCE
              if row.package == "ESP32-H2-MINI-1_EXP")
    assert compose.contradiction(element, c3) is None
    c6 = next(row for row in compose.CORRESPONDENCE
              if row.package == "ESP32-C6-MINI-1_EXP")
    said = compose.contradiction(element, c6)
    assert said is not None and "ESP32-C6" in said, said


def test_a_plated_hole_in_a_surface_mount_pad_is_not_a_hole_for_a_leg():
    """Olimex drill a hole through the middle of the ESP32-C3-MINI-1's ground
    pad, laid as nine 1.45 mm squares on 1.975 mm under one number, the
    middle one plated (OH-195). `confirm` reads a through-hole pad as where a
    legged part's legs go, and a via in a pad is not one: the module is
    surface-mount and is drawn. **"In a pad" is geometry, not a shared
    number**: same-numbered surface-mount copper on all four sides of the
    hole's centre, the pad's own rotation honoured. A plated slot BESIDE
    pads of its number -- the Olimex USB-C's shell, four slots each next to
    a surface-mount tab numbered 0 as they are -- is a leg's hole, and so is
    one whose number no surface-mount pad shares."""
    class Box:
        width, height = 4.0, 4.0

    flat = _model_box(4.0, 4.0, 0.5, "#101010")

    def complaint(*pads):
        return compose.confirm(eagle.Element("U3", "lib", "LAND", pads=pads),
                               Box(), 0.0, flat)

    def pad(number, kind, x, y, width, height, turn=0.0):
        return eagle.Pad(number, kind, x, y, width, height, None,
                         shape="rect", rotation_deg=turn)

    # Olimex's field: eight squares round a plated ninth, which lies in none.
    field = [pad("49", "smd", x * 1.975, y * 1.975, 1.45, 1.45, 90.0)
             for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)]
    middle = pad("49", "thru_hole", 0.0, 0.0, 1.45, 1.45, 90.0)
    assert complaint(*field, middle) is None
    # Take away the row above it and copper is on three sides: a leg's hole.
    open_top = [square for square in field if square.y_mm <= 0]
    said = complaint(*open_top, middle)
    assert said is not None and "through-hole pads" in said, said
    # Inside one pad, its rotation honoured: 3.0 x 0.6 turned 90 runs along
    # y and holds (0, 1.2); unturned it runs along x and does not.
    hole = pad("1", "thru_hole", 0.0, 1.2, 0.5, 0.5)
    assert complaint(pad("1", "smd", 0.0, 0.0, 3.0, 0.6, 90.0), hole) is None
    said = complaint(pad("1", "smd", 0.0, 0.0, 3.0, 0.6), hole)
    assert said is not None and "through-hole pads" in said, said
    # The USB-C's shell, read off the Olimex's file: each slot 0.61 mm
    # inboard of a 1.1 mm tab under the same number, outside it.
    shell = [pad("0", kind, sign * x, y, width, height)
             for sign in (-1, 1)
             for y, slot, tab in ((0.0, (1.2, 2.2), (1.1, 2.2)),
                                  (-4.18, (1.3, 2.0), (1.1, 2.0)))
             for kind, x, (width, height) in (("thru_hole", 4.320, slot),
                                              ("smd", 4.928, tab))]
    said = complaint(*shell)
    assert said is not None and "through-hole pads" in said, said
    # A number no surface-mount pad shares is a leg's, as before.
    said = complaint(*field, pad("50", "thru_hole", 0.0, 0.0, 1.45, 1.45))
    assert said is not None and "through-hole pads" in said, said


def test_a_sot_on_a_kicad_row_is_turned_so_its_pin_one_is_kicads():
    """**A five-lead SOT-23 drawn a quarter or a half turn out passes every
    check `compose` makes** -- its span is nearly square and nothing marks
    its pin 1 -- and two did (OH-195): SparkFun's KiCad land took the EAGLE
    row's quarter turn under the same package name, and Olimex's, laid out
    half round from KiCad's, took none. KiCad's own SOT-23, SOT-23-5 and
    SOT-23-6 footprints put pad 1 at -x and -y down the page, read
    2026-10-08; turned back by its row, each land's pad 1 must sit there."""
    checked, unfetched = 0, []
    for row, spec in _manifest_specs():
        if spec is None or not row.cad.endswith(".kicad_pcb"):
            continue
        if not _fetched(spec):
            unfetched.append(row.board)
            continue
        statements = compose.statements_for(spec)
        placed = kicad.read_board(spec.layout).placements
        for footprint, element in zip(placed, compose.read_layout(spec.layout).elements):
            drawn, _why = compose.drawn_from(element, statements)
            if drawn is None or drawn.model not in ("SOT-23", "SOT-23-5", "SOT-23-6"):
                continue
            checked += 1
            one = next(pad for pad in footprint.pads if pad.number == "1")
            # The land's own frame, y up: an underside footprint's stored
            # pads are its library's with y negated (OH-182).
            x, y = one.x_mm, (one.y_mm if footprint.back else -one.y_mm)
            back = math.radians(-drawn.turn)
            mx = x * math.cos(back) - y * math.sin(back)
            my = x * math.sin(back) + y * math.cos(back)
            assert mx < 0 < my, (
                f"{spec.board}: {element.name} ({element.package}, "
                f"{element.library}) turned {drawn.turn:.0f} puts its pad 1 "
                f"at ({mx:.2f}, {my:.2f}) in {drawn.model}'s frame, where "
                f"KiCad's footprint puts it at -x, +y")
    if unfetched:
        pytest.skip(f"checked {checked}; not fetched: {unfetched}")
    assert checked, "no SOT on any KiCad row"


def test_sparkfuns_kicad_lands_take_their_rows_only_from_sparkfuns_kicad_library():
    """**A row written for one library's land holds for that library only**
    (OH-195). SparkFun's KiCad SOT-23-5, SOT-23-6, SOT-583-8 and 2 x 2 mm
    DFN-8 are laid out as KiCad's own and drawn unturned; the same names in
    another library -- SparkFun's EAGLE SOT23-5 is one -- are other copper,
    and a land of that name from anywhere else must not silently take this
    row and its turn."""
    library = "SparkFun-Semiconductor-Standard"
    for package in ("SOT23-5", "SOT23-6", "SOT-583-8",
                    "DFN-8_2x2mm_P0.5mm_EP1.2x0.8mm"):
        rows = [c for c in compose.CORRESPONDENCE
                if c.package == package and c.vendor_library == library]
        assert len(rows) == 1, (package, rows)
        here = eagle.Element("U1", library, package, pads=())
        assert compose.correspondence_for(here) == rows[0], package
        elsewhere = dataclasses.replace(here, library="SparkFun-IC-Power")
        assert compose.correspondence_for(elsewhere) != rows[0], (
            f"a {package} land from another library takes the row written "
            f"for {library}'s")


def test_the_thing_plus_c5s_qwiic_and_microsd_quote_what_their_footprints_state():
    """**A row's words about what a footprint says are read back out of it**
    (OH-195). SparkFun's file never names SM04B-SRSS-TB: J1's footprint
    says '4 pin JST 1mm polarized connector for I2C' and links JST's SH
    catalogue, so KiCad's SM04B standing for it is a judgement and its row
    quotes both and says so. J4's footprint links Molex's own document for
    the microSD socket, which its ABSENT reason was written as naming no
    maker."""
    spec = next(s for s in compose.COMPOSITIONS
                if s.board == "SparkFun Thing Plus ESP32-C5")
    if not _fetched(spec):
        pytest.skip(f"SKIPPED: not fetched; run {spec.fetch_with}")
    tree = kicad.parse_sexp(spec.layout.read_text(encoding="utf-8"))
    stated = {kicad._reference_of(node): {p[1]: p[2] for p in kicad.children(node, "property")}
              for node in kicad.children(tree, "footprint")}
    board = compose.read_layout(spec.layout)
    row = compose.correspondence_for(board.element("J1"))
    for said in (f"'{stated['J1']['Description']}'",
                 pathlib.PurePosixPath(stated["J1"]["Datasheet"]).name,
                 "A JUDGEMENT"):
        assert said in row.why, (said, row.why)
    why = compose.ABSENT[board.element("J4").package]
    document = pathlib.PurePosixPath(stated["J4"]["Datasheet"]).name
    assert document in why and "naming no maker" not in why, why


# --- the silkscreen's text (OH-163) ---------------------------------------------
#
# The oracle for the font is its author's own table, and the oracle for the
# layout is what each vendor plotted: a silkscreen Gerber is the ink as it was
# sent to be printed, written by KiCad from the very board file read here, and
# a text in it is a run of straight draws at the text's pen. So every stroke
# `letter` makes is looked for there, with the reader tests/rules/test_kicad.py
# holds the silkscreen's lines to, at the same micron.


def _newstroke() -> pathlib.Path:
    """The fetched font, or a skip naming what fetches it."""
    font = compose.newstroke_font()
    if font is None:
        pytest.skip(f"SKIPPED: newstroke is not fetched under {compose.FONT_CACHE}; "
                    f"{compose.FETCH_FONT} fetches it")
    return font


def _letters_on_gerbers(path: pathlib.Path, text: str, gerbers: dict[str, str],
                        origin: tuple[float, float]):
    """`(tally, missed)`: each text `letter` draws or refuses, by outcome, and
    every stroke it draws that lands on no draw of its own layer's Gerber.
    The Gerber's frame is the board's with y negated, from `origin`."""
    from tests.rules.test_kicad import _gerber_draws, _gerber_ends, _lands

    cells = {layer: _gerber_ends(_gerber_draws(plotted, f"{path.name} {layer}"))
             for layer, plotted in gerbers.items()}
    table = compose.newstroke(_newstroke())
    tally: dict[str, int] = {}
    missed = []
    for item in kicad.read_board(path, text=text).text:
        try:
            strokes = compose.letter(item, table)
        except compose.Unlettered as why:
            tally[str(why)] = tally.get(str(why), 0) + 1
            continue
        tally["lettered"] = tally.get("lettered", 0) + 1
        tally["strokes"] = tally.get("strokes", 0) + len(strokes)
        missed += [(item.text, stroke) for stroke in strokes
                   if not _lands(cells[stroke.layer],
                                 (stroke.x1_mm - origin[0], origin[1] - stroke.y1_mm),
                                 (stroke.x2_mm - origin[0], origin[1] - stroke.y2_mm))]
    return tally, missed


def test_newstroke_reads_as_its_authors_own_table():
    """**The glyphs are read out of the author's libraries and are the very
    table the author generated from them**: every character from U+0020 to
    U+007E, built from `font.lib` and `symbol.lib` through `charlist.txt`,
    is the string the archive's own `newstroke_font.cpp` holds for it, bearings,
    accents and the converter's dropped repeat points included. That table is
    the one KiCad plots from, which the Gerber tests below hold."""
    import tarfile

    font = _newstroke()
    with tarfile.open(font / "newstroke-font.tgz") as bundle:
        generated = bundle.extractfile("newstroke_font.cpp").read().decode("latin-1")
    rows = [re.sub(r"\\(.)", r"\1", row) for row in re.findall(
        r'^\s*"((?:[^"\\]|\\.)*)",', generated[generated.index("newstroke_font[]"):],
        re.MULTILINE)]
    table = compose.newstroke(font)
    assert sorted(table) == list(range(0x20, 0x7F))
    assert {code: rows[code - 0x20] for code in table} == table


def test_the_xiao_esp32_c6s_text_lands_on_seeeds_own_gerber():
    """**Every stroke of every text on the XIAO ESP32-C6 lands on a draw of
    Seeed's own silkscreen Gerbers**, plotted by KiCad 8.0.0 from the board
    file read here: its pin labels mirrored on the back, the stackup table
    beside the board, both justifications and every angle it uses -- and its
    "3V3" followed by a line break, which KiCad draws as one line."""
    from tests.rules.test_kicad import SEEED_C6_ROOT, SEEED_PCB
    import zipfile

    zipped, path = SEEED_PCB / "ESP32-C6.zip", SEEED_PCB / "ESP32-C6.kicad_pcb"
    if not (zipped.is_file() and path.is_file()):
        pytest.skip(f"SKIPPED: {zipped.name} or {path.name} absent under {SEEED_PCB}; "
                    f"python tools/compose_board_3d.py --board XIAO-ESP32-C6-DIP")
    with zipfile.ZipFile(zipped) as bundle:
        shipped = bundle.read(SEEED_C6_ROOT + "XIAO ESP32 C6.kicad_pcb")
        gerbers = {layer: bundle.read(f"{SEEED_C6_ROOT}XIAO ESP32 C6_gerber/"
                                      f"XIAO ESP32 C6-{name}.gbr").decode("ascii")
                   for layer, name in (("F.SilkS", "F_Silkscreen"),
                                       ("B.SilkS", "B_Silkscreen"))}
    assert path.read_bytes() == shipped, "not the board Seeed plotted these from"
    tally, missed = _letters_on_gerbers(path, shipped.decode("utf-8"), gerbers, (0.0, 0.0))
    assert (tally, missed) == ({"lettered": 73, "strokes": 4178}, [])


def test_the_esp32_poes_text_lands_on_olimexs_own_gerber():
    """**The same on a second vendor and a second KiCad**: Olimex's
    ESP32-PoE revision M, plotted by KiCad 7.0.9 from an auxiliary origin,
    with footprint text kept upright at every quarter turn. Its four knockout
    texts are refused by name, not drawn wrong."""
    from tests.rules.test_kicad import POE_REV_M

    path = POE_REV_M / "ESP32-PoE_Rev_M.kicad_pcb"
    files = {layer: POE_REV_M / "Gerbers" / f"ESP32-PoE_Rev_M-{name}.gbr"
             for layer, name in (("F.SilkS", "F_Silkscreen"), ("B.SilkS", "B_Silkscreen"))}
    if not (path.is_file() and all(file.is_file() for file in files.values())):
        pytest.skip(f"SKIPPED: revision M's board or Gerbers absent under {POE_REV_M}; "
                    f"python tools/get_board_sources.py olimex-esp32-poe")
    text = path.read_text(encoding="utf-8")
    setup = kicad.first(kicad.parse_sexp(text), "setup")
    origin = tuple(float(v) for v in kicad.first(setup, "aux_axis_origin")[1:3])
    gerbers = {layer: file.read_text(encoding="ascii") for layer, file in files.items()}
    tally, missed = _letters_on_gerbers(path, text, gerbers, origin)
    knockout = next(why for why in tally if why.startswith("knockout"))
    assert (tally, missed) == ({"lettered": 188, "strokes": 5956, knockout: 4}, [])


def test_a_text_newstroke_would_draw_unlike_kicad_is_refused_by_name():
    """**Refused, and said why, rather than drawn wrong**: a TrueType face
    KiCad draws from its own outlines, a knockout, a stated line spacing,
    KiCad's markup, a character KiCad has redrawn since the author's release,
    and one the table does not hold. Each reason names the thing, so a board's
    count of refusals says what is missing from it."""
    table = {ord(c): "PTRFR[" for c in "D0~"}
    plain = kicad.Text(layer="F.SilkS", text="D0", x_mm=0.0, y_mm=0.0, angle_deg=0.0,
                       height_mm=1.0, width_mm=1.0, thickness_mm=0.15, halign="left",
                       valign="bottom", mirrored=False, upright=False, bold=False,
                       italic=False)
    assert len(compose.letter(plain, table)) == 2
    for change, reason in (({"face": "Lexend"}, "a TrueType face, 'Lexend'"),
                           ({"knockout": True}, "knockout text"),
                           ({"line_spacing": 1.2}, "a stated line spacing"),
                           ({"text": "~{RST}"}, "KiCad markup"),
                           ({"text": "D0~"}, "does: U+007E"),
                           ({"text": "Dé"}, "does: U+00E9")):
        with pytest.raises(compose.Unlettered, match=re.escape(reason)):
            compose.letter(dataclasses.replace(plain, **change), table)


# The layout's branches no vendor's Gerber exercises, each held to a stroke
# derived BY HAND from KiCad 8.0.0's arithmetic, the derivation in the
# docstring. Read at that tag: `getLinePositions` in common/font/font.cpp for
# where a line starts, `STROKE_FONT::GetTextAsGlyphs` and the glyph loader in
# common/font/stroke_font.cpp for the advance and a glyph's units,
# `STROKE_GLYPH::Transform` in common/font/glyph.cpp for the lean,
# `EDA_TEXT::GetEffectiveTextPenWidth` in common/eda_text.cpp and the pen
# sizes in common/gr_text.cpp for the pen.
#
# One glyph does for all of them: "PTRFR[" -- bearings P and T, two units
# either side of R, so a 4-unit cell; then one stroke from (R, F) to (R, [),
# x = 0 - (-2) = 2 units into the cell, y from F - R - 8 = -20 units to
# [ - R - 8 = +1, y down. A unit is 1/21 of the size, so at 2.1 mm it is
# 0.1 mm. KiCad truncates the lead (pen / 1.52) and the drop (pen x 0.052) to
# whole nanometres where the composer keeps the fraction, under 1 nm each, so
# every coordinate is held to 2 nm.
_I_GLYPH = {ord("I"): "PTRFR["}
_NM2 = 2e-6


def _plain(**changes) -> kicad.Text:
    """'I' at (10, 20), 2.1 mm square, pen 0.152 mm, left and bottom."""
    text = kicad.Text(layer="F.SilkS", text="I", x_mm=10.0, y_mm=20.0, angle_deg=0.0,
                      height_mm=2.1, width_mm=2.1, thickness_mm=0.152, halign="left",
                      valign="bottom", mirrored=False, upright=False, bold=False,
                      italic=False)
    return dataclasses.replace(text, **changes)


def _strokes_of(text: kicad.Text) -> list[tuple[float, ...]]:
    return [(s.x1_mm, s.y1_mm, s.x2_mm, s.y2_mm, s.width_mm)
            for s in compose.letter(text, _I_GLYPH)]


def test_right_justified_text_ends_a_pen_lead_short_of_its_position():
    """The text "II", right-justified, bottom-aligned, pen 0.152 mm.

    The line spans two 4-unit cells, 0.8 mm. A right-justified line starts at
    -(span + pen / 1.52) = -(0.8 + 0.1) = -0.9 from the text's x, so at 9.1;
    each stroke is 2 units, 0.2 mm, into its cell: x = 9.3 and 9.7.

    Bottom: the line's y is the text's y plus the size, less the drop
    pen x 0.052 = 0.007904, less the block's height 1.17 x size = 2.457:
    20 + 2.1 - 0.007904 - 2.457 = 19.635096. The stroke runs from 20 units
    above it to 1 below: 17.635096 to 19.735096."""
    assert _strokes_of(_plain(text="II", halign="right")) == [
        pytest.approx((9.3, 17.635096, 9.3, 19.735096, 0.152), abs=_NM2),
        pytest.approx((9.7, 17.635096, 9.7, 19.735096, 0.152), abs=_NM2)]


def test_top_aligned_text_hangs_below_its_position():
    """The text "I", left-justified, top-aligned, pen 0.152 mm.

    Left: the line starts a lead of pen / 1.52 = 0.1 past the text's x, so
    the stroke is at 10 + 0.1 + 0.2 = 10.3. Top: nothing is taken off for
    the block, so the line's y is 20 + 2.1 - 0.007904 = 22.092096 and the
    stroke runs from 20.092096 to 22.192096 -- the glyph's top a pen's drop
    below the text's own y."""
    assert _strokes_of(_plain(valign="top")) == [
        pytest.approx((10.3, 20.092096, 10.3, 22.192096, 0.152), abs=_NM2)]


def test_text_with_no_thickness_is_drawn_at_an_eighth_of_its_width():
    """The text "I", 2.1 mm high and 1.6 mm wide, no thickness stated.

    A pen of one nanometre or less takes the default, 1/8 of the WIDTH (not
    of the smaller side): 1.6 / 8 = 0.2, under the clamp of 1.6 / 4 = 0.4.
    x: 10 + 0.2 / 1.52 + 2/21 x 1.6 = 10 + 0.131579 + 0.152381 = 10.283960.
    y: 20 + 2.1 - 0.2 x 0.052 - 2.457 = 19.6326, so the stroke runs from
    17.6326 to 19.7326."""
    assert _strokes_of(_plain(width_mm=1.6, thickness_mm=0.0)) == [
        pytest.approx((10.283960, 17.6326, 10.283960, 19.7326, 0.2), abs=_NM2)]


def test_bold_text_with_no_thickness_is_drawn_at_a_fifth_of_its_width():
    """As the default pen, bold: 1/5 of the width, 1.6 / 5 = 0.32, under the
    clamp of 0.4. x: 10 + 0.32 / 1.52 + 0.152381 = 10 + 0.210526 + 0.152381
    = 10.362907. y: 20 + 2.1 - 0.32 x 0.052 - 2.457 = 19.62636, the stroke
    from 17.62636 to 19.72636."""
    assert _strokes_of(_plain(width_mm=1.6, thickness_mm=0.0, bold=True)) == [
        pytest.approx((10.362907, 17.62636, 10.362907, 19.72636, 0.32), abs=_NM2)]


def test_a_pen_is_held_to_a_quarter_of_the_texts_smaller_side():
    """The text "I", 2.1 mm high and 1.6 mm wide, a stated pen of 0.6 mm.

    Any pen is held to 1/4 of the smaller of the two sizes: 1.6 / 4 = 0.4,
    not 2.1 / 4. x: 10 + 0.4 / 1.52 + 0.152381 = 10 + 0.263158 + 0.152381
    = 10.415539. y: 20 + 2.1 - 0.4 x 0.052 - 2.457 = 19.6222, the stroke
    from 17.6222 to 19.7222."""
    assert _strokes_of(_plain(width_mm=1.6, thickness_mm=0.6)) == [
        pytest.approx((10.415539, 17.6222, 10.415539, 19.7222, 0.4), abs=_NM2)]


def test_italic_text_leans_an_eighth_of_its_height():
    """The text "I", left-justified, bottom-aligned, pen 0.152 mm, italic.

    Each point is scaled first and then moved left by 1/8 of its scaled y,
    which is negative above the baseline: the top point, 2.0 mm above, moves
    right by 0.25 to 10.55; the bottom point, 0.1 mm below, left by 0.0125
    to 10.2875. Nothing else moves -- the advance is the unleaned glyph's --
    so y is the right-justified case's: 17.635096 to 19.735096."""
    assert _strokes_of(_plain(italic=True)) == [
        pytest.approx((10.55, 17.635096, 10.2875, 19.735096, 0.152), abs=_NM2)]


def test_every_composed_boards_text_is_lettered_or_refused_by_name():
    """**Done for OH-163's first step**: on every composed KiCad board each
    text is lettered or refused under a named reason, and on Seeed's XIAOs
    none is refused. What is refused is PCBCUPID's TrueType faces -- Lexend,
    and the Noto Sans of the "Antenna Here!" each Glyph ESP32 leads an arrow
    to, a dimension's text -- and Olimex's knockouts; an EAGLE board's text
    is counted, and refused for EAGLE's font, in
    `test_what_is_not_drawn_rides_in_extras`."""
    _newstroke()
    named = ("a TrueType face, 'Lexend'", "knockout text", "a TrueType face, 'Noto Sans'")
    refusals: dict[str, dict[str, int]] = {}
    for spec in compose.COMPOSITIONS:
        if spec.layout.suffix != ".kicad_pcb" or not _fetched(spec):
            continue
        texts = compose.read_layout(spec.layout).kicad_text
        _letters, refused, drawn = compose.lettering(texts)
        assert drawn + sum(refused.values()) == len(texts), spec.board
        # Each reason by the name it starts with, or whole where it is new.
        refusals[spec.board] = {
            next((name for name in named if why.startswith(name)), why): count
            for why, count in refused.items()}
    if not refusals:
        pytest.skip("SKIPPED: no composed KiCad board is fetched")
    xiaos = [spec.board for spec in compose.COMPOSITIONS
             if spec.pcb_chip is not None and spec.board in refusals]
    assert xiaos and all(refusals[board] == {} for board in xiaos), refusals
    expected = {"PCBCUPID Glyph Mini RP2040": {named[0]: 49},
                "PCBCUPID Glyph C3": {named[0]: 48, named[2]: 1},
                "PCBCUPID Glyph C6": {named[0]: 48, named[2]: 1},
                "Olimex ESP32-C3-DevKit-Lipo": {named[1]: 33}}
    assert {board: said for board, said in refusals.items() if said} == {
        board: said for board, said in expected.items() if board in refusals}


def test_a_font_archive_that_is_not_the_one_measured_is_refused(tmp_path, monkeypatch):
    """**The font is checked by its digest as well as its size**, because it
    lives on its author's wiki: an archive of the right length and other
    bytes is another font, and every board's text would be drawn in it."""
    monkeypatch.setattr(compose, "FONT_CACHE", tmp_path)
    (tmp_path / "newstroke-font.tgz").write_bytes(b"x" * compose.NEWSTROKE[1])
    with pytest.raises(SystemExit, match=r"records 210,057 bytes and dba1c334"):
        compose.fetch_newstroke()


def test_a_download_that_is_not_the_font_is_deleted(tmp_path, monkeypatch):
    """**A failed fetch leaves nothing behind and names where it was**
    (OH-163 step 1's review): the download is bounded by `FETCH_TIMEOUT_S`
    rather than waiting on the author's wiki for ever, and one that is not
    the archive measured is deleted, its path in the message, so the next
    run does not find it and trip over it."""
    import io

    monkeypatch.setattr(compose, "FONT_CACHE", tmp_path)
    asked = {}

    def answer(url, timeout=None):
        asked[url] = timeout
        return io.BytesIO(b"not the font")

    monkeypatch.setattr(compose.urllib.request, "urlopen", answer)
    archive = tmp_path / "newstroke-font.tgz"
    with pytest.raises(SystemExit) as said:
        compose.fetch_newstroke()
    assert f"{archive} is 12 bytes" in str(said.value), said.value
    assert "Deleted it" in str(said.value) and not archive.exists(), said.value
    assert asked == {compose.NEWSTROKE[0]: compose.FETCH_TIMEOUT_S}


def test_a_font_file_changed_since_it_was_unpacked_is_refused(tmp_path, monkeypatch):
    """**The font is checked every time it is read, not only when fetched**,
    as `import_3d_model.fetch` checks its archive every time: an unpacked
    file that differs from the archive's own copy is another font, and the
    composer says which file and how to put it right rather than drawing
    every board's text in it."""
    import shutil

    real = _newstroke()
    monkeypatch.setattr(compose, "FONT_CACHE", tmp_path)
    shutil.copy(real / "newstroke-font.tgz", tmp_path / "newstroke-font.tgz")
    assert compose.fetch_newstroke() == tmp_path
    assert compose.newstroke_font() == tmp_path
    glyphs = tmp_path / "font.lib"
    glyphs.write_bytes(glyphs.read_bytes() + b"\n")
    with pytest.raises(SystemExit, match=re.escape(f"{glyphs} is not the font.lib in")):
        compose.newstroke_font()


def test_a_board_whose_font_is_not_fetched_is_skipped_naming_it(tmp_path, monkeypatch,
                                                               capsys):
    """**Composing reads the font and never fetches it**, as it reads a
    manifest board's own files (OH-163 step 1's review). `compose` used to
    download the font in the middle of whatever called it, a test included,
    and offline that ended in a URLError rather than a reason. A KiCad board
    whose font is not fetched is SKIPPED, naming the font and the one command
    that fetches it; and `_inputs_missing`, which every test that composes a
    board consults first, names it too, so those tests skip and fetch
    nothing."""
    spec = next(s for s in compose.COMPOSITIONS if s.pcb_chip == "ESP32-C3")
    if not spec.layout.is_file():
        pytest.skip(f"SKIPPED: {spec.layout.name} is not fetched; run {spec.fetch_with}")
    nowhere = tmp_path / "newstroke"
    monkeypatch.setattr(compose, "FONT_CACHE", nowhere)

    def offline(url, *args, **kwargs):
        raise AssertionError(f"composing fetched {url}")

    monkeypatch.setattr(compose.urllib.request, "urlopen", offline)
    fetch = "python tools/compose_board_3d.py --fetch-font"
    assert compose.compose(spec, deflection=compose.DEFLECTION, check=True) == 3
    out = capsys.readouterr().out
    assert f"SKIPPED: the newstroke font is not fetched under {nowhere}" in out, out
    assert f"Run: {fetch}" in out, out
    assert not nowhere.exists(), sorted(nowhere.iterdir())
    missing = _inputs_missing(spec, compose.read_layout(spec.layout))
    assert any("newstroke" in name and fetch in name for name in missing), missing


def test_a_run_of_the_tool_fetches_the_font_before_it_composes(monkeypatch):
    """**The command line fetches the font as a run fetches KiCad's models**,
    so a fresh checkout's `python tools/compose_board_3d.py` letters its
    boards rather than skipping every KiCad one; `compose`, which tests call,
    still only reads it. Neither the font nor OpenCASCADE is needed here:
    the fetch and the composition are both stood in for, and what is held is
    that the fetch happens once, first."""
    calls = []
    monkeypatch.setattr(compose, "newstroke_font", lambda: None)
    monkeypatch.setattr(compose, "fetch_newstroke",
                        lambda: calls.append("fetch") or compose.FONT_CACHE)
    monkeypatch.setattr(compose, "compose",
                        lambda spec, deflection, check: calls.append(spec.board) or 0)
    board = compose.COMPOSITIONS[0].board
    assert compose.main(["--check", "--board", board]) == 0
    assert calls == ["fetch", board], calls


# --- OH-216: the header pads a model is set by --------------------------------


#: A KiCad header whose first pin is a whole hole and a castellated half-hole
#: beside it, as PCBCUPID draws the Glyph Mini's, and whose second is a whole
#: hole on no net.
CASTELLATED_HEADER = """(kicad_pcb
\t(version 20241229)
\t(gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))
\t(footprint "L:HEADER"
\t\t(layer "F.Cu")
\t\t(at 5 5)
\t\t(property "Reference" "J1")
\t\t(pad "1" thru_hole circle (at -1.27 0) (size 1.7 1.7) (drill 1)
\t\t\t(layers "*.Cu") (net 1 "/A"))
\t\t(pad "1" thru_hole circle (at -1.27 1.5) (size 2 1.7) (drill 1)
\t\t\t(layers "*.Cu") (net 1 "/A") (property pad_prop_castellated))
\t\t(pad "2" thru_hole circle (at 1.27 0) (size 1.7 1.7) (drill 1)
\t\t\t(layers "*.Cu"))
\t)
)
"""


def test_a_model_states_its_header_pads_as_the_board_file_names_them(tmp_path):
    """**OH-216: the composer says where its header pads are, by name, so
    the page can set the model by them.** Each is `[x, z, width, height,
    name]` in the model's own millimetres -- x along the file's x, z down
    the page from the centre the model is built about -- named by its net, or
    its number on no net, as `tools/import_board.py` names a board file's.

    A castellated half-hole beside its pin's whole hole is not one: the
    importer keeps the whole hole as the pin's only pad, so a board file has
    nothing there to land, and stated it moved the middle of the PCBCUPID
    Glyph Mini's pads 0.73 mm off the middle of its board file's.

    Seen red (2026-10-09): with the half-hole kept, three pads were stated;
    with `from_kicad` dropping nets as it did, pin 1 was named "1".
    """
    path = tmp_path / "HEADER.kicad_pcb"
    path.write_text(CASTELLATED_HEADER, encoding="utf-8")
    spec = dataclasses.replace(compose.COMPOSITIONS[0], layout=path,
                               headers=("J1",), dip_headers=False)
    board = compose.read_layout(path)
    stated = compose.stated_header_pads(spec, board, [], (5.0, -5.0))
    assert stated == [[-1.27, 0.0, 1.7, 1.7, "/A"], [1.27, 0.0, 1.7, 1.7, "2"]], stated


def test_a_dip_pin_is_named_by_the_castellation_it_stands_in(tmp_path):
    """A XIAO DIP's header rows are not in the vendor's file -- the composer
    hangs them from the castellation field (`dip_header_elements`) -- so
    each pin is named by the castellation it stands in, which is the pin it
    is soldered to. That is what lets the page tell a XIAO DIP from itself
    turned half way round: its GND and VBUS lie on no namesake there.

    Seen red (2026-10-09): with the DIP pins named by their own numbers, no
    pin was named for its castellation.
    """
    # A half-hole on the edge and a whole hole inside it, one net, per pin --
    # as Seeed's MOUDLE14P-XIAO-HALF-HOLE draws each of its fourteen.
    castellations = tuple(
        eagle.Pad(number=str(index + 1), kind="thru_hole",
                  x_mm=(index - 3) * 2.54, y_mm=side * across, width_mm=1.5,
                  height_mm=1.5, net=f"{'TOP' if side > 0 else 'BOT'}{index}")
        for side in (1, -1) for index in range(7) for across in (8.89, 7.62))
    board = eagle.Board(name="module", version="test",
                        elements=(eagle.Element(name="U2", library="L",
                                                package="CASTEL",
                                                pads=castellations),),
                        outline=())
    spec = dataclasses.replace(compose.COMPOSITIONS[0], layout=tmp_path / "m.brd",
                               headers=("U2",), dip_headers=True)
    dip = compose.dip_header_elements(list(castellations))
    stated = compose.stated_header_pads(spec, board, dip, (0.0, 0.0))
    named = {(round(x, 2), round(z, 2)): name for x, z, _, _, name in stated}
    assert named == {(round((index - 3) * 2.54, 2), round(-side * 7.62, 2)):
                     f"{'TOP' if side > 0 else 'BOT'}{index}"
                     for side in (1, -1) for index in range(7)}, named


def test_every_composed_model_states_the_header_pads_it_is_set_by():
    """Every composed model built here carries `header_pads`, each row
    `[x, z, width, height, name]` with a name, so the page sets it by its
    pads and not by its outline. Skips where nothing is composed.

    Seen red (2026-10-09): on the models composed before OH-216, every one
    stated none. A board the index says is composed whose model is not
    built here is left out and named in a skip, after the rest are held: in
    review (2026-10-09), with XIAO-ESP32-C3-DIP.glb moved away, this passed
    quietly; now it skips in part, naming the two boards drawn from it.
    """
    index = REPO / "webui" / "static" / "models" / "index.json"
    if not index.is_file():
        pytest.skip(f"no {index}; run tools/compose_board_3d.py")
    from tools.import_3d_model import read_extras

    wrong, left_out = [], []
    seen = 0
    for board, entry in json.loads(index.read_text(encoding="utf-8"))["boards"].items():
        model = REPO / "webui" / "static" / (entry.get("file") or "/").lstrip("/")
        if not model.is_file():
            if entry.get("composed"):
                left_out.append(f"{board}: no {model.name}")
            continue
        extras = read_extras(model)
        if not extras.get("composed"):
            continue
        seen += 1
        rows = extras.get("header_pads") or []
        if not rows or any(len(row) != 5 or not row[4] for row in rows):
            wrong.append(f"{board}: header_pads {rows[:2]!r}")
    if not seen:
        pytest.skip(f"no composed model is built here; run tools/compose_board_3d.py. "
                    f"Left out: {left_out}")
    assert not wrong, "\n".join(wrong)
    if left_out:
        pytest.skip(f"SKIPPED in part: the {seen} boards whose composed model is "
                    f"built here held; "
                    f"left out, with no model built here (recompose: python "
                    f"tools/compose_board_3d.py): {left_out}")


def test_a_boards_thickness_is_its_top_face_and_not_its_solids_box():
    """**OH-216: Seeed's SAMD21 STEP gives its PCB solid a small feature 0.39
    mm proud of the board**, so the solid's box said the board was 1.61 mm
    thick where its top face -- 309.66 of the solid's top area, and what
    every component stands on -- is at 1.21. The page stood its pad markers
    in the air and found none of its castellation copper "above the board".
    `board_top` takes the plane across the board holding the most area
    above the solid's middle.

    A 20 x 17 x 1.2 mm board fused to a 1 x 1 x 0.4 mm boss on its top: one
    solid, whose box is 1.6 mm and whose top face is at 1.2. Built here
    because the vendor's file is fetched and this must run without it.

    Here rather than beside the importer's other tests, whose file is not
    this ticket's: the importer writes the fetched meshes the composed ones
    are drawn beside, and both state `pcb.thickness` for the page.

    Seen red (2026-10-09): with `board_top` answering the solid's box, 1.6.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt
    except ImportError:
        pytest.skip("OpenCASCADE is not installed")

    from tools.import_3d_model import board_top, pcb_solid

    board = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 20.0, 17.0, 1.2).Shape()
    boss = BRepPrimAPI_MakeBox(gp_Pnt(5.0, 5.0, 1.2), 1.0, 1.0, 0.4).Shape()
    fused = BRepAlgoAPI_Fuse(board, boss).Shape()
    solid = pcb_solid(fused, 2)
    assert board_top(solid, 2) == 1.2, board_top(solid, 2)
