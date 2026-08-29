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
    "XIAO-ESP32-C6-DIP": {"ANT2P-5.2x2x1.1MM", "PMOS_1.0X0.6X0.35MM",
                          "SW4-SMD-2.8-2.6X1.6X0.53MM"},
    # The RP2350's own chip was here until OH-100 modelled it.
    "XIAO-RP2350-DIP": {"PMOS_1.0X0.6X0.35MM",
                        "SW4-SMD-2.8-2.6X1.6X0.53MM"},
    "XIAO-nRF54l15-DIP": {"WLCSP47-0.3-2.451X2.245X0.42MM",
                          "ANT2P-5.2x2x1.1MM", "BUTTON_TD1183SA",
                          "IPEX-GEN4-SMD-1.7X1.7X1.0MM",
                          "PMOS_1.0X0.6X0.35MM"},
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

#: How far a soldered contact may lie outside the board's own outline.
#:
#: **It should be zero and on three of the five boards it is exactly zero.**
#: The Arduino Uno, the ESP32-C3 and the ESP32-C6 have no gold whatever beyond
#: their PCB. What buys the rest is that the RP2350's and nRF54L15's USB-C is
#: a part nobody publishes -- Seeed name their own `USB-31C-F-16P-L7.35`,
#: 7.35 mm long -- so the nearest published receptacle is a fraction large and
#: its front contacts reach 0.099 and 0.206 mm past the edge.
#:
#: The number that made this a test is 0.42: that is how far the WRONG
#: receptacle put them, and it is what a person looking at the board saw as a
#: connector hanging off the end of it.
CONTACT_OVERHANG_MM = 0.25


def test_no_soldered_contact_hangs_off_the_board():
    """A pin is soldered to a pad, and a pad is on the board.

    **This is the check that would have caught OH-101 and did not exist.**
    Seeed use two USB-C land patterns -- one with four through-hole shell tabs
    and one with two -- and OH-93 gave both the same KiCad model. `place`
    anchors a through-hole part on its legs against the pad extent, so
    matching a four-tab model to a two-lock land slid the connector half a
    millimetre forward and left its contact row 0.42 mm past the board edge,
    in mid-air.

    Every other check passed. `confirm` measures the model's footprint against
    the pad span and the wrong part was 2.46 mm short of a 10.240 mm land,
    inside a `SPAN_TOLERANCE_MM` of 3.0 that is deliberately generous because
    a body and its pads are legitimately different sizes. So the tolerance is
    not the thing to tighten -- this is.
    """
    models = REPO / "webui" / "static" / "models"
    boards = [_slug for _slug in
              (compose._slug(spec.board) for spec in compose.COMPOSITIONS)
              if (models / f"{_slug}.glb").is_file()]
    if not boards:
        pytest.skip("no board composed; run tools/compose_board_3d.py")
    worst: list[str] = []
    for slug in boards:
        groups = _glb_groups(models / f"{slug}.glb")
        pcb = groups.get(compose.BOARD_MASK) or groups.get("#313d63")
        assert pcb, f"{slug} has no PCB group to measure against"
        left, right = min(p[0] for p in pcb), max(p[0] for p in pcb)
        near, far = min(p[2] for p in pcb), max(p[2] for p in pcb)
        for colour in CONTACT_COLOURS & set(groups):
            for x, _y, z in groups[colour]:
                out = max(left - x, x - right, near - z, z - far)
                if out > CONTACT_OVERHANG_MM:
                    worst.append(f"{slug}: {colour} at ({x:.3f}, {z:.3f}) is "
                                 f"{out:.3f} mm outside the PCB")
                    break
    assert not worst, "\n".join(worst)


def test_the_two_usb_c_land_patterns_are_given_different_receptacles():
    """They differ in the count of holes, which is what picks the part.

    Both are 16-pin USB-C, so the PIN count says nothing. `USB2.0-TYPE-C` has
    four through-hole shell tabs and `USB2.0-TYPE-C_USB-31C-F-16P` has two
    board locks, and KiCad's `Connector_USB` happens to hold exactly one
    published receptacle of each kind. Giving them one entry is what OH-101
    was.
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

    every = (*model_from_datasheet.SPECS, *model_from_datasheet.PACKS)
    assert every, "nothing is modelled, so this is vacuous"
    for spec in every:
        assert spec.why_not_fetched.strip(), spec.name
        assert spec.cited, f"{spec.name} cites nothing, so it invented nothing?"
        for field, (value, why) in spec.cited.items():
            assert isinstance(value, float), f"{spec.name}.{field}"
            assert len(why) > 40, f"{spec.name}.{field} has no real citation"


def _rp2350() -> pathlib.Path:
    path = compose.PCB_CACHE / "RP2350.kicad_pcb"
    if not path.is_file():
        pytest.skip(
            f"SKIPPED: {path.name} is not fetched. Run: "
            f"python tools/compose_board_3d.py --board XIAO-RP2350-DIP"
        )
    return path


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
