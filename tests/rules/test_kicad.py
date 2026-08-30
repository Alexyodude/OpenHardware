# OpenHardware - tests for the KiCad reader and the board importer.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for tools/kicad.py, the parser both board importers used.

The fixtures here are written inline rather than read from
`third_party/seeed-xiao/`, because that tree is fetched and git-ignored. A
suite that silently skips when a download is missing is the vacuous green this
repository exists to prevent, so the parser is pinned against text held here.

`test_the_real_vendor_library_parses` is the one exception, and it skips
loudly by name when the fetch has not been run.
"""

import json
import pathlib

import pytest

from tools.kicad import (
    KicadError,
    Pad,
    parse_sexp,
    read_board,
    read_footprint,
    read_symbol_pins,
    symbol_roots,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDOR = REPO / "third_party" / "seeed-xiao" / "Seeed Studio XIAO Series Library"

# A footprint with the shapes that broke the first regex attempt: a pad whose
# `at` carries a rotation, one whose `at` does not, a multi-line rect, and an
# SMD/through-hole pair sharing pad number 1.
FOOTPRINT = """(footprint "TEST-BOARD"
\t(version 20260206)
\t(layer "F.Cu")
\t(pad "1" smd roundrect
\t\t(at 7.62 -8.455 90)
\t\t(size 2.432 1.524)
\t\t(layers "F.Cu" "F.Mask")
\t)
\t(pad "1" thru_hole circle
\t\t(at 7.62 -7.62 90)
\t\t(size 1.524 1.524)
\t\t(drill 0.889)
\t)
\t(pad "2" thru_hole circle
\t\t(at 5.08 -7.62)
\t\t(size 1.524 1.524)
\t)
\t(fp_line
\t\t(start -9 -9)
\t\t(end 9 -9)
\t\t(layer "F.SilkS")
\t)
\t(fp_rect
\t\t(start -10 -10)
\t\t(end 10 10)
\t\t(layer "F.CrtYd")
\t)
\t(fp_line
\t\t(start 0 0)
\t\t(end 1 1)
\t\t(layer "F.Fab")
\t)
)
"""

SYMBOL_LIB = """(kicad_symbol_lib
\t(version 20260101)
\t(symbol "TEST-BOARD-SMD"
\t\t(symbol "TEST-BOARD-SMD_1_1"
\t\t\t(pin passive line
\t\t\t\t(at -12.7 3.81 0)
\t\t\t\t(name "D0")
\t\t\t\t(number "1")
\t\t\t)
\t\t\t(pin passive line
\t\t\t\t(at -12.7 0 0)
\t\t\t\t(name "GND")
\t\t\t\t(number "2")
\t\t\t)
\t\t)
\t)
\t(symbol "OTHER-BOARD-SMD"
\t\t(symbol "OTHER-BOARD-SMD_1_1"
\t\t\t(pin passive line
\t\t\t\t(at 0 0 0)
\t\t\t\t(name "X")
\t\t\t\t(number "1")
\t\t\t)
\t\t)
\t)
)
"""


@pytest.fixture
def footprint(tmp_path):
    path = tmp_path / "TEST-BOARD.kicad_mod"
    path.write_text(FOOTPRINT, encoding="utf-8")
    return read_footprint(path)


@pytest.fixture
def symbols(tmp_path):
    path = tmp_path / "lib.kicad_sym"
    path.write_text(SYMBOL_LIB, encoding="utf-8")
    return path


# --- the s-expression parser --------------------------------------------------


def test_nested_lists_parse():
    assert parse_sexp("(a (b c) (d (e 1)))") == ["a", ["b", "c"], ["d", ["e", "1"]]]


def test_quoted_strings_keep_their_spaces():
    assert parse_sexp('(name "XIAO ESP32 C3")') == ["name", "XIAO ESP32 C3"]


def test_unbalanced_parens_raise():
    with pytest.raises(KicadError, match="unbalanced"):
        parse_sexp("(a (b c)")


def test_an_empty_file_raises():
    with pytest.raises(KicadError, match="empty"):
        parse_sexp("   \n  ")


# --- footprints ----------------------------------------------------------------


def test_pads_are_read_with_position_and_size(footprint):
    smd = footprint.pads_of("smd")
    assert len(smd) == 1
    assert smd[0] == Pad("1", "smd", 7.62, -8.455, 2.432, 1.524,
                         shape="roundrect", rotation_deg=90.0,
                         layers=("F.Cu", "F.Mask"))


def test_a_pad_without_rotation_still_parses(footprint):
    """`(at x y)` is as valid as `(at x y rot)`; the first regex assumed three."""
    two = [p for p in footprint.pads if p.number == "2"]
    assert len(two) == 1 and two[0].x_mm == 5.08


def test_a_rect_becomes_four_segments(footprint):
    crtyd = [s for s in footprint.segments if s.layer == "F.CrtYd"]
    assert len(crtyd) == 4


def test_every_layer_is_kept_for_the_caller_to_filter(footprint):
    assert {s.layer for s in footprint.segments} == {"F.SilkS", "F.CrtYd", "F.Fab"}


def test_a_footprint_with_no_pads_raises(tmp_path):
    """An empty read must not look like a board with no pins."""
    path = tmp_path / "empty.kicad_mod"
    path.write_text('(footprint "EMPTY"\n\t(layer "F.Cu")\n)\n', encoding="utf-8")
    with pytest.raises(KicadError, match="no pads"):
        read_footprint(path)


def test_a_non_footprint_file_is_rejected(tmp_path):
    path = tmp_path / "wrong.kicad_mod"
    path.write_text('(kicad_symbol_lib\n\t(version 1)\n)\n', encoding="utf-8")
    with pytest.raises(KicadError, match="not a footprint"):
        read_footprint(path)


# --- symbols --------------------------------------------------------------------


def test_pins_are_read_from_the_unit_sub_symbol(symbols):
    """KiCad puts pins in `<root>_1_1`, not in the root symbol."""
    assert read_symbol_pins(symbols, "TEST-BOARD-SMD") == {"1": "D0", "2": "GND"}


def test_symbol_roots_are_deduplicated(symbols):
    assert symbol_roots(symbols) == ["OTHER-BOARD-SMD", "TEST-BOARD-SMD"]


def test_an_unknown_symbol_names_what_is_available(symbols):
    with pytest.raises(KicadError, match="OTHER-BOARD-SMD"):
        read_symbol_pins(symbols, "NOT-THERE")


# --- the importer, which is tools/import_board.py -----------------------------
#
# The six tests that were here exercised `tools/import_kicad_board.py`'s
# `build` and `header_pads`, and went with it when OH-41 retired that file.
# **Their coverage did not go with them**: `tests/rules/test_import_board.py`
# has 27 tests over the replacement, including the one that made the
# retirement possible -- it reproduces the committed
# `webui/boards/XIAO-RP2040-DIP.json` exactly, from a different tool than the
# one that produced it, every coordinate identical to 0.0 px.
#
# What remains in this file is `tools/kicad.py`: the parser, which both
# importers used and only one of them is gone.

# --- boards -------------------------------------------------------------------------
#
# A `.kicad_pcb` is what OH-93 composes the six unmodelled XIAO chips from,
# the same way the Uno is composed from Arduino's EAGLE `.brd`. The fixture
# below carries the shapes that would each fail differently and silently:
#
#   * an `Edge.Cuts` line AND a `F.SilkS` line, so layer filtering is tested
#     rather than assumed -- taking every `gr_line` gives an outline with the
#     silkscreen in it, which still draws
#   * a `gr_arc`, whose `mid` is a point ON the curve and not its centre
#   * a `gr_rect`, which is one node and four edges
#   * a footprint whose `at` has NO rotation, which is legal and means zero
#   * one on `B.Cu`, which is mounted on the underside
#   * a reference in the KiCad 7 `(property "Reference" ...)` form and one in
#     the older `(fp_text reference ...)` form, because Seeed's six projects
#     span generator versions and reading only one gives "" for every part

BOARD = """(kicad_pcb
\t(version 20241229)
\t(generator "pcbnew")
\t(gr_line
\t\t(start 10 20)
\t\t(end 30 20)
\t\t(stroke (width 0.05) (type solid))
\t\t(layer "Edge.Cuts")
\t)
\t(gr_line
\t\t(start 0 0)
\t\t(end 99 99)
\t\t(stroke (width 0.12) (type solid))
\t\t(layer "F.SilkS")
\t)
\t(gr_arc
\t\t(start 30 20)
\t\t(mid 31.4142 21.4142)
\t\t(end 32 23)
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
\t\t\t(layers "F.Cu" "F.Paste" "F.Mask")
\t\t)
\t\t(pad "33" smd rect
\t\t\t(at 0 0)
\t\t\t(size 3.7 3.7)
\t\t\t(layers "F.Cu" "F.Paste" "F.Mask")
\t\t)
\t)
\t(footprint "XIAO TEST:C0201"
\t\t(layer "B.Cu")
\t\t(at 15 25)
\t\t(fp_text reference "C13"
\t\t\t(at 0 -0.7 0)
\t\t\t(layer "B.SilkS")
\t\t)
\t\t(pad "1" smd roundrect
\t\t\t(at -0.28 0)
\t\t\t(size 0.3 0.35)
\t\t\t(layers "B.Cu" "B.Paste" "B.Mask")
\t\t)
\t)
)
"""


@pytest.fixture
def board(tmp_path):
    path = tmp_path / "TEST.kicad_pcb"
    path.write_text(BOARD, encoding="utf-8")
    return path


def test_a_board_reports_every_placement_with_its_footprint(board):
    got = read_board(board)
    assert len(got.placements) == 2
    by_reference = {p.reference: p for p in got.placements}
    assert set(by_reference) == {"U4", "C13"}
    # The library id is kept whole and `name` is the part after the colon,
    # because the composer keys its correspondence table on the name and the
    # report has to be able to say which library it came from.
    assert by_reference["U4"].library == "XIAO TEST:QFN32G-0.5-5X5MM"
    assert by_reference["U4"].name == "QFN32G-0.5-5X5MM"


def test_a_reference_is_read_from_either_place_kicad_puts_it(tmp_path):
    """**KiCad 7 moved it and both vintages are in the wild.**

    Reading only `(property "Reference" ...)` returns "" for every part of an
    older board. Nothing raises: the composer just reports its alignment
    against a column of empty strings, which is unreadable rather than wrong,
    and is exactly the kind of failure that gets diagnosed as "the parser is
    fine, the data must be bad".

    So this drives a board where EVERY reference is in the old form. The mixed
    fixture cannot catch a reader that handles only `property`, because the
    part that would fail is the one it already reads.
    """
    old = BOARD.replace('(property "Reference" "U4"\n\t\t\t(at -1.5 1.9 0)\n'
                        '\t\t\t(layer "F.SilkS")\n\t\t)',
                        '(fp_text reference "U4"\n\t\t\t(at -1.5 1.9 0)\n'
                        '\t\t\t(layer "F.SilkS")\n\t\t)')
    assert "property" not in old, "the substitution did not take"
    path = tmp_path / "old.kicad_pcb"
    path.write_text(old, encoding="utf-8")
    assert {p.reference for p in read_board(path).placements} == {"U4", "C13"}


def test_a_placement_without_a_rotation_is_not_rotated(board):
    """`(at x y)` is legal and means zero. Indexing coords[2] and hoping is
    an IndexError on roughly half the parts of any real board."""
    got = {p.reference: p for p in read_board(board).placements}
    assert got["U4"].rotation_deg == -90.0
    assert got["C13"].rotation_deg == 0.0


def test_the_side_a_part_is_mounted_on_is_reported(board):
    got = {p.reference: p for p in read_board(board).placements}
    assert got["U4"].back is False
    assert got["C13"].back is True, (
        "a part on B.Cu is on the underside and its footprint is mirrored; "
        "drawing it on top puts it in the right place on the wrong face"
    )


def test_a_placement_carries_its_own_pads(board):
    """The pads are what `confirm` measures a candidate mesh against, so a
    placement that does not carry them cannot be checked at all."""
    got = {p.reference: p for p in read_board(board).placements}
    assert len(got["U4"].pads) == 2
    assert got["U4"].pads[1] == Pad("33", "smd", 0.0, 0.0, 3.7, 3.7,
                                    shape="rect", rotation_deg=0.0,
                                    layers=("F.Cu", "F.Paste", "F.Mask"))


def test_only_the_outline_layer_is_taken_for_the_outline(board):
    """A `gr_line` on `F.SilkS` is not the edge of the board.

    The fixture's silkscreen line runs to (99, 99); an outline that included
    it would measure 99 mm across and still draw.
    """
    got = read_board(board)
    assert all(s.layer == "Edge.Cuts" for s in got.outline)
    left, bottom, right, top = got.extent_mm()
    assert (right, top) == (32.0, 37.0)
    assert (left, bottom) == (10.0, 20.0)


def test_a_rect_on_the_outline_becomes_four_edges(board):
    """One node, four sides -- the same expansion `fp_rect` already gets, so
    every consumer works in one primitive."""
    got = read_board(board)
    # one gr_line + four from the gr_rect
    assert len(got.outline) == 5
    assert len(got.arcs) == 1


def test_an_arcs_mid_point_is_on_the_curve_and_not_its_centre(board):
    """**Reading `mid` as a centre puts every rounded corner one radius out.**

    The result is a board with corners of the right size in the wrong places,
    which looks like a board. The fixture's arc runs (30,20) -> (32,23) with a
    mid at (31.41, 21.41); its centre is nowhere near that point.
    """
    arc = read_board(board).arcs[0]
    assert (arc.x1_mm, arc.y1_mm) == (30.0, 20.0)
    assert (arc.xm_mm, arc.ym_mm) == pytest.approx((31.4142, 21.4142))
    assert (arc.x2_mm, arc.y2_mm) == (32.0, 23.0)


def test_an_arc_that_bulges_past_the_straight_edges_is_inside_the_extent(tmp_path):
    """**A rounded rectangle cannot catch this and neither can the real board.**

    Where every arc is a corner, its endpoints ARE the tangent points and the
    straight edges already reach every extreme -- so dropping arcs from the
    bounding box changes nothing, and a mutation that does exactly that
    survived the whole suite until this test existed.

    A board with a curved END is a different shape: the arc's own middle is
    the widest point and nothing else in the file knows about it. Here the
    edges stop at x = 32 and the arc reaches 35.
    """
    bulge = BOARD.replace("(mid 31.4142 21.4142)", "(mid 35 21.5)")
    assert bulge != BOARD, "the substitution did not take"
    path = tmp_path / "bulge.kicad_pcb"
    path.write_text(bulge, encoding="utf-8")

    got = read_board(path)
    assert max(s.x2_mm for s in got.outline) == 32.0, "the edges stop at 32"
    assert got.extent_mm()[2] == 35.0, (
        "the arc reaches 35 and the outline does not, so an extent that omits "
        "arcs crops the widest part of the board off it"
    )


# --- an outline drawn inside a footprint --------------------------------------------
#
# **Four of Seeed's six projects draw the board's own silhouette inside their
# `MOUDLE14P-XIAO-HALF-HOLE` footprint** and leave only the routed slots at
# the top level. Reading `gr_*` alone measured the XIAO ESP32-C6 as
# 1.270 x 12.954 mm -- its two slots -- which is a plausible small board
# rather than an error, and the ESP32-C3 (the first one read) draws everything
# at the top level and so could not show the difference.

INSIDE = """(kicad_pcb
\t(version 20241229)
\t(footprint "Module:MOUDLE14P"
\t\t(layer "F.Cu")
\t\t(at 100 50 90)
\t\t(property "Reference" "U2"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(fp_line
\t\t\t(start 2 0)
\t\t\t(end 2 4)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "Edge.Cuts")
\t\t)
\t\t(fp_line
\t\t\t(start -9 -9)
\t\t\t(end 9 9)
\t\t\t(stroke (width 0.12) (type solid))
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(fp_arc
\t\t\t(start 2 4)
\t\t\t(mid 3 5)
\t\t\t(end 4 4)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "Edge.Cuts")
\t\t)
\t\t(fp_rect
\t\t\t(start 0 0)
\t\t\t(end 1 1)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "Edge.Cuts")
\t\t)
\t\t(pad "1" smd rect
\t\t\t(at 0 0)
\t\t\t(size 1 1)
\t\t\t(layers "F.Cu")
\t\t)
\t)
)
"""


@pytest.fixture
def inside(tmp_path):
    path = tmp_path / "INSIDE.kicad_pcb"
    path.write_text(INSIDE, encoding="utf-8")
    return path


def test_a_footprints_edge_cuts_line_is_part_of_the_boards_outline(inside):
    """Where a vendor drew it is the incidental detail this module hides.

    KiCad mills a footprint's `Edge.Cuts` exactly as it mills the board's own,
    so "the outline" is both. Without this the C6, the RP2350 and the
    nRF54L15 have no silhouette at all.
    """
    got = read_board(inside)
    #: The `F.SilkS` line is a diagonal across the whole part -- it would
    #: double the outline's extent if the layer filter were dropped.
    assert len(got.outline) == 1 + 4, "one fp_line and the fp_rect's four edges"
    lines = [s for s in got.outline if (s.x1_mm, s.y1_mm) != (s.x2_mm, s.y2_mm)]
    assert all(s.layer == "Edge.Cuts" for s in lines)


def test_a_footprints_outline_is_turned_by_the_footprints_own_rotation(inside):
    """Placed at (100, 50) and turned 90 degrees, by hand.

    In KiCad's stored frame y runs DOWN the page, so a rotation that is
    counter-clockwise as drawn takes `(lx, ly)` to
    `(px + lx cos + ly sin, py - lx sin + ly cos)`. At 90 degrees that is
    `(px + ly, py - lx)`, which turns the local vertical `(2,0)-(2,4)` into a
    board horizontal at y = 48 running from x = 100 to x = 104.

    **Getting this wrong still draws a board**, rotated or mirrored, with
    every part in the right place on it -- which is why it is measured here
    rather than looked at.
    """
    got = read_board(inside)
    line = next(s for s in got.outline
                if {(s.x1_mm, s.y1_mm), (s.x2_mm, s.y2_mm)} == {(100.0, 48.0),
                                                                (104.0, 48.0)})
    assert line.layer == "Edge.Cuts"

    arc = got.arcs[0]
    assert (arc.x1_mm, arc.y1_mm) == (104.0, 48.0), "the arc starts where the line ends"
    assert (arc.xm_mm, arc.ym_mm) == (105.0, 47.0)
    assert (arc.x2_mm, arc.y2_mm) == (104.0, 46.0)


def test_a_footprint_on_the_back_has_its_outline_mirrored(tmp_path):
    """The same rule its pads follow: a part on the underside is seen through
    the board, so its x is negated before it is turned.

    At rotation zero the local `(2,0)-(2,4)` lands at x = 98, not x = 102.
    """
    path = tmp_path / "back.kicad_pcb"
    path.write_text(INSIDE.replace('(layer "F.Cu")', '(layer "B.Cu")')
                          .replace("(at 100 50 90)", "(at 100 50)"),
                    encoding="utf-8")
    got = read_board(path)
    assert got.placements[0].back is True
    line = next(s for s in got.outline
                if {(s.x1_mm, s.y1_mm), (s.x2_mm, s.y2_mm)} == {(98.0, 50.0),
                                                                (98.0, 54.0)})
    assert line.layer == "Edge.Cuts"


def test_a_footprint_carrying_the_whole_outline_is_enough_of_one(tmp_path):
    """`INSIDE` has no `gr_*` at all, and is not the empty board the "nothing
    on Edge.Cuts" guard refuses. That guard runs after the footprints are
    read for exactly this reason."""
    path = tmp_path / "only-fp.kicad_pcb"
    path.write_text(INSIDE, encoding="utf-8")
    got = read_board(path)
    #: By hand, at 90 degrees, where the transform is `(100 + ly, 50 - lx)`:
    #: the rect's corners land on x 100..101 and y 49..50, the line on
    #: (100,48)-(104,48), and the arc reaches x 105 and y 46. So x spans
    #: 100..105 and y spans 46..50.
    assert got.extent_mm() == (100.0, 46.0, 105.0, 50.0)


# --- the body, which is not the silkscreen -------------------------------------------

BODIES = """(kicad_pcb
\t(version 20241229)
\t(gr_line
\t\t(start 0 0)
\t\t(end 40 0)
\t\t(stroke (width 0.05) (type solid))
\t\t(layer "Edge.Cuts")
\t)
\t(gr_rect
\t\t(start 0 0)
\t\t(end 40 30)
\t\t(stroke (width 0.05) (type solid))
\t\t(layer "Edge.Cuts")
\t)
\t(footprint "Lib:SOT-25"
\t\t(layer "F.Cu")
\t\t(at 10 10)
\t\t(property "Reference" "U1"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(fp_rect
\t\t\t(start -1.45 -0.95)
\t\t\t(end 1.45 0.95)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "F.Fab")
\t\t)
\t\t(fp_line
\t\t\t(start -8 -8)
\t\t\t(end 8 8)
\t\t\t(stroke (width 0.12) (type solid))
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(fp_text user "U1"
\t\t\t(at 0 -9 0)
\t\t\t(layer "F.Fab")
\t\t)
\t\t(pad "1" smd rect
\t\t\t(at -1.1 -0.95)
\t\t\t(size 0.6 0.7)
\t\t\t(layers "F.Cu")
\t\t)
\t)
\t(footprint "Lib:NOBODY"
\t\t(layer "F.Cu")
\t\t(at 20 20)
\t\t(property "Reference" "TP1"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t)
\t\t(pad "1" smd circle
\t\t\t(at 0 0)
\t\t\t(size 0.9 0.9)
\t\t\t(layers "F.Cu")
\t\t)
\t)
)
"""


@pytest.fixture
def bodies(tmp_path):
    path = tmp_path / "BODIES.kicad_pcb"
    path.write_text(BODIES, encoding="utf-8")
    return path


def test_a_footprints_body_is_read_from_the_fab_layer(bodies):
    """`F.Fab` is where KiCad draws the part; `F.SilkS` is ink near it.

    EAGLE has no such separation, so `tools/eagle.py` takes layers 21 and 51
    and gets the body among other things. Here the right layer is named, and
    taking the silkscreen instead would measure this 2.9 x 1.9 mm part as
    16 x 16 -- the diagonal stroke in the fixture is there to make that
    failure loud rather than plausible.
    """
    got = read_board(bodies)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["U1"].body == (-1.45, -0.95, 1.45, 0.95)


def test_a_reference_designator_is_not_part_of_the_body(bodies):
    """`fp_text` on F.Fab is a label, placed wherever it is legible.

    The fixture puts one 9 mm above a part 0.95 mm tall, for the reason
    `eagle._silk_extent` records: including it would make a 1 mm capacitor
    measure five.
    """
    got = read_board(bodies)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["U1"].body[1] == -0.95, "the label at y -9 is not the body"


def test_a_closed_outline_beats_loose_lines_on_the_same_layer(tmp_path):
    """Seeed draw a cable keep-out on `F.Fab` beside the body, and it is not
    the part.

    Their `USB2.0-TYPE-C` has an `fp_rect` of 7.341 x 8.992 mm -- the
    receptacle -- and four `fp_line`s forming a 1.651 x 12.5 mm box behind it,
    which is the room a plug needs. Unioning the two reported a 12.5 mm body,
    and **every comparison against it was meaningless**: it is what let a
    connector sit a quarter turn out with `silk_miss` agreeing (OH-105). The
    RP2350 draws only the rectangle, and the disagreement between two boards
    sharing a footprint is what gave it away.
    """
    path = tmp_path / "keepout.kicad_pcb"
    path.write_text(BODIES.replace('''\t\t(fp_line
\t\t\t(start -8 -8)
\t\t\t(end 8 8)
\t\t\t(stroke (width 0.12) (type solid))
\t\t\t(layer "F.SilkS")
\t\t)''', '''\t\t(fp_line
\t\t\t(start -6 -6)
\t\t\t(end 6 -6)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "F.Fab")
\t\t)'''), encoding="utf-8")
    got = read_board(path)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["U1"].body == (-1.45, -0.95, 1.45, 0.95), (
        "the keep-out line at y -6 was unioned into the body, which makes a "
        "2.9 mm part measure 12"
    )


def test_loose_lines_are_read_where_there_is_no_closed_outline(tmp_path):
    """A chamfered body is drawn edge by edge and is still a body.

    Preferring a rectangle must not mean ignoring a footprint that draws its
    outline as lines, which is why this is a preference and not a filter.
    """
    path = tmp_path / "chamfered.kicad_pcb"
    path.write_text(BODIES.replace('''\t\t(fp_rect
\t\t\t(start -1.45 -0.95)
\t\t\t(end 1.45 0.95)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "F.Fab")
\t\t)''', '''\t\t(fp_line
\t\t\t(start -1.45 -0.95)
\t\t\t(end 1.45 0.95)
\t\t\t(stroke (width 0.05) (type solid))
\t\t\t(layer "F.Fab")
\t\t)'''), encoding="utf-8")
    got = read_board(path)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["U1"].body == (-1.45, -0.95, 1.45, 0.95)


def test_a_polygon_body_is_read_like_a_rectangle(tmp_path):
    """KiCad draws a chamfered body as an `fp_poly`, and it is still closed.

    Which matters because a polygon has to beat loose lines the same way a
    rectangle does: a footprint with a polygon body AND a keep-out line would
    otherwise take both.
    """
    path = tmp_path / "poly.kicad_pcb"
    path.write_text(BODIES.replace('''		(fp_rect
			(start -1.45 -0.95)
			(end 1.45 0.95)
			(stroke (width 0.05) (type solid))
			(layer "F.Fab")
		)''', '''		(fp_poly
			(pts
				(xy -1.45 -0.95) (xy 1.45 -0.95) (xy 1.45 0.6)
				(xy 1.1 0.95) (xy -1.45 0.95)
			)
			(stroke (width 0.05) (type solid))
			(layer "F.Fab")
		)'''), encoding="utf-8")
    got = read_board(path)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["U1"].body == (-1.45, -0.95, 1.45, 0.95)


def test_a_footprint_that_draws_no_body_reports_none(bodies):
    """A test point has pads and no assembly drawing.

    `None` rather than an empty box, because `silk_miss` has to tell "the
    vendor did not say" from "the vendor said zero" -- the first is nothing to
    compare against and the second would fail every part that had one.
    """
    got = read_board(bodies)
    by_reference = {p.reference: p for p in got.placements}
    assert by_reference["TP1"].body is None


def test_a_board_with_no_outline_is_refused(tmp_path):
    """A board drawn without `Edge.Cuts` would be a bounding box around its
    parts, which is not its shape and would be reported as though it were."""
    path = tmp_path / "no-edge.kicad_pcb"
    path.write_text(BOARD.replace('"Edge.Cuts"', '"F.SilkS"'), encoding="utf-8")
    with pytest.raises(KicadError, match="no outline"):
        read_board(path)


def test_a_board_with_no_footprints_is_refused(tmp_path):
    path = tmp_path / "bare.kicad_pcb"
    path.write_text("(kicad_pcb (version 20241229))", encoding="utf-8")
    with pytest.raises(KicadError, match="no footprints"):
        read_board(path)


def test_a_footprint_file_is_not_a_board(tmp_path):
    """Both are s-expressions and both hold `(pad ...)`, so the wrong one
    parses cleanly and yields a board with no outline and one part."""
    path = tmp_path / "TEST-BOARD.kicad_mod"
    path.write_text(FOOTPRINT, encoding="utf-8")
    with pytest.raises(KicadError, match="not a board"):
        read_board(path)


# --- against the real vendor library ------------------------------------------------


def test_the_real_vendor_library_parses():
    """Skips by name when the vendor CAD has not been fetched."""
    if not VENDOR.is_dir():
        pytest.skip("vendor library absent; run python tools/get_board_sources.py seeed-xiao")
    mod = VENDOR / "XIAO-ESP32-C3-DIP.kicad_mod"
    if not mod.is_file():
        pytest.skip(f"{mod.name} absent from the fetched tree")

    from tools.import_board import read_geometry

    # `read_footprint` is what this file is about and is exercised whole; the
    # geometry comes from the surviving importer, because pad SELECTION -- a
    # DIP footprint carries both a through-hole and an SMD pad for one pin --
    # is that tool's rule and not the parser's.
    assert read_footprint(mod), "the footprint parses"
    pins = read_symbol_pins(VENDOR / "Seeed_Studio_XIAO_Series.kicad_sym", "XIAO-ESP32-C3-SMD")
    # `--select` is needed because the symbol library names only the SMD
    # variant of this part: a DIP and an SMD XIAO share one symbol and differ
    # only in their footprints. The retired tool took the footprint's own name
    # and would have failed here too -- the difference is that this one says
    # which names it does have.
    pads = read_geometry(mod, select=("XIAO-ESP32-C3-SMD",)).pads

    assert len(pads) == 14, "the XIAO is a 14-pin board"
    # 2.54 mm is the 0.1 inch header pitch; pinmap.py treats that pitch as what
    # identifies a header run, so it is worth pinning rather than assuming.
    #
    # Grouped by Y rather than by sign: `PadSpec` measures from the top-left
    # with Y increasing DOWN, where the retired tool measured from the
    # footprint origin and put the top row at a negative Y. Same board, two
    # conventions, and reading the old one here would silently select nothing.
    rows: dict[float, list[float]] = {}
    for pad in pads:
        rows.setdefault(round(pad.y_mm, 2), []).append(pad.x_mm)
    longest = sorted(rows.values(), key=len)[-1]
    gaps = {round(b - a, 2) for a, b in zip(sorted(longest), sorted(longest)[1:])}
    assert gaps == {2.54}
    assert pins["1"] == "D0"


def test_the_real_vendor_pcb_parses_and_agrees_with_the_vendors_own_footprint():
    """**Two independent vendor files, and they are made to disagree out loud.**

    Seeed publishes a KiCad PROJECT for the ESP32-C3 (OH-93's survey; the
    meshes it has no equivalent of) and, separately, a FOOTPRINT of the whole
    XIAO for people placing one on a carrier board. Neither was made from the
    other. The board's `Edge.Cuts` and the footprint's `F.Fab` are therefore
    two measurements of one rectangle, and this asserts they agree.

    Measured 2026-08-28: 20.955 x 17.780 from the PCB against 20.975 x 17.800
    from the footprint -- 0.020 mm apart in both axes, which is one line width.

    **And 21 x 17.5 mm, which is what Seeed's own marketing says the XIAO
    measures, is wrong by 0.28 mm.** The real board is 0.825 x 0.700 INCH,
    laid out in imperial. A test written against the published figure would
    have failed here and been read as a parser bug.

    Skips by name when the fetch has not been run: `third_party/` is
    git-ignored and these archives state no licence, so they are never
    committed.
    """
    pcb = REPO / "third_party" / "seeed-pcb" / "ESP32-C3.kicad_pcb"
    if not pcb.is_file():
        pytest.skip(f"{pcb} absent; see docs/research/board-models/README.md")

    got = read_board(pcb)
    assert len(got.placements) == 68
    width, height = got.size_mm()

    mod = VENDOR / "XIAO-ESP32-C3-DIP.kicad_mod"
    if not mod.is_file():
        pytest.skip("the vendor footprint library has not been fetched")
    fab = [s for s in read_footprint(mod).segments if s.layer == "F.Fab"]
    assert fab, "the footprint has no F.Fab body outline to compare against"
    xs = [v for s in fab for v in (s.x1_mm, s.x2_mm)]
    ys = [v for s in fab for v in (s.y1_mm, s.y2_mm)]

    assert width == pytest.approx(max(xs) - min(xs), abs=0.05)
    assert height == pytest.approx(max(ys) - min(ys), abs=0.05)
    # Imperial, which is the fact the marketing figure rounds away.
    assert width == pytest.approx(0.825 * 25.4, abs=0.05)
    assert height == pytest.approx(0.700 * 25.4, abs=0.05)


def test_the_committed_xiao_boards_load(request):
    """Every generated board must survive a round trip through pinmap."""
    from webui import pinmap

    names = [n for n in pinmap.available() if n.startswith("XIAO")]
    if not names:
        pytest.skip("no XIAO boards generated yet")
    for name in names:
        board = pinmap.load(name)
        assert board.pads, f"{name} has no pads"
        assert all(p.pin is None for p in board.pads), f"{name} has a non-null pin"


# --- the models a vendor states, and why reading them changes little (OH-98) -


def _kicad_boards():
    """Every composed board whose layout is a `.kicad_pcb` and is on disk.

    **One spec per LAYOUT**, not per board: OH-118 split each XIAO's DIP and
    SMD variants into their own compositions of the same PCB file, and a test
    counting statements per spec counted every one of them twice -- the C6's
    single vendor disagreement "became" two the day the variants split.
    """
    from tools import compose_board_3d as compose

    seen: set = set()
    out = []
    for spec in compose.COMPOSITIONS:
        if spec.layout.suffix != ".kicad_pcb" or not spec.layout.is_file():
            continue
        if spec.layout in seen:
            continue
        seen.add(spec.layout)
        out.append(spec)
    return out


def test_the_model_blocks_are_read_and_four_boards_of_five_carry_them():
    """**The claim this module made and OH-98 corrected.**

    The header said `(model ...)` blocks were absent because "Seeed strips
    them". That is true of the ESP32-C3 -- and the C3 is the only board of the
    five it is true of, and it is the one the pipeline was built on. The other
    four carry 59, 57, 91 and 83.
    """
    from tools import kicad

    boards = _kicad_boards()
    if not boards:
        pytest.skip("no KiCad layouts on disk; run tools/get_board_sources.py")
    carrying = 0
    for spec in boards:
        board = kicad.read_board(spec.layout)
        stated = sum(len(placed.models) for placed in board.placements)
        if stated:
            carrying += 1
    assert carrying >= 4, (
        f"only {carrying} of {len(boards)} boards state any model at all, so "
        f"the header's corrected claim is wrong in the other direction now"
    )


def test_a_whole_xiao_board_is_never_a_usable_model_for_a_part_on_one():
    """**The catastrophe OH-98 describes, as a test rather than a paragraph.**

    `MOUDLE14P-XIAO-HALF-HOLE` carries five alternates and every one of them
    is a COMPLETE XIAO BOARD. Four are `(hide yes)`. `Seeeduino XIAO SAMD21
    v4.step` is not -- so a reader that trusted the hide flag alone would
    stand a whole SAMD21 on top of an RP2350, which looks like a rendering bug
    rather than a data bug.

    **What actually stops it is the path**, not the flag: all five are under
    `${AMZPATH}`, Seeed's own library, which they do not publish. So the guard
    that matters is "only `${KICAD7_3DMODEL_DIR}` can be fetched" -- and this
    asserts both halves, because a future file could hide the SAMD21 and leave
    a different whole board visible.
    """
    from tools import kicad

    boards = _kicad_boards()
    if not boards:
        pytest.skip("no KiCad layouts on disk; run tools/get_board_sources.py")
    seen = 0
    for spec in boards:
        board = kicad.read_board(spec.layout)
        for placed in board.placements:
            for model in placed.models:
                if "XIAO" not in model.path or ".3dshapes" not in model.path:
                    continue
                seen += 1
                assert model.variable != "KICAD7_3DMODEL_DIR", (
                    f"{spec.board}: {placed.name} names {model.path!r} from "
                    f"KiCad's own library, so it could be fetched and stood "
                    f"on the board -- and it is a whole XIAO"
                )
    assert seen, "no whole-board alternate found at all; has the footprint changed?"


def test_the_visible_alternate_on_the_half_hole_footprint_is_the_wrong_board():
    """The specific fact, pinned so it cannot quietly stop being true.

    Not because it must stay wrong, but because the guard above is only
    interesting while it is: if Seeed ever hide the SAMD21, a test that
    silently started passing for a different reason would take the teeth out
    of the one above without anybody noticing.
    """
    from tools import kicad

    boards = [spec for spec in _kicad_boards() if spec.pcb_chip == "RP2350"]
    if not boards:
        pytest.skip("no RP2350 layout on disk")
    board = kicad.read_board(boards[0].layout)
    placed = next(p for p in board.placements if "MOUDLE14P" in p.name)
    visible = [m for m in placed.models if not m.hidden]
    assert len(visible) == 1, [m.path for m in visible]
    assert "SAMD21" in visible[0].path, (
        f"the visible alternate is now {visible[0].path!r}. If Seeed have "
        f"fixed this, say so here -- the guard in the test above is what "
        f"matters and it is unaffected"
    )
    assert visible[0].variable == "AMZPATH", (
        "the SAMD21 alternate moved to a library that CAN be fetched, which "
        "is the one change that would make it dangerous"
    )


def test_a_stated_model_never_silently_replaces_the_measured_correspondence():
    """**Why CORRESPONDENCE does not shrink, which is OH-98's real answer.**

    That ticket expected reading these blocks to "turn most of CORRESPONDENCE
    from a judgement into a reading". Counted across all five boards by
    (board, package) pair, it does not: 17 name a model that can be fetched
    and every one of those 17 already AGREES with what the table measured, 43
    state nothing usable, and the single disagreement is one where the vendor
    is wrong -- the C6's `USB2.0-TYPE-C`, stated as
    `USB_C_Receptacle_GCT_USB4105-xx-A_16P`, which is 7.78 mm deep where the
    same footprint's own Description says 7.3.

    So reading the statements would change nothing except in the one place it
    would make the picture worse. This asserts the shape of that count rather
    than the exact numbers, which a new board would move.
    """
    from tools import compose_board_3d as compose
    from tools import kicad

    boards = _kicad_boards()
    if not boards:
        pytest.skip("no KiCad layouts on disk; run tools/get_board_sources.py")
    table = {c.package: c for c in compose.CORRESPONDENCE}
    agrees = disagrees = 0
    for spec in boards:
        board = kicad.read_board(spec.layout)
        seen = set()
        for placed in board.placements:
            if placed.name in seen or placed.name not in table:
                continue
            seen.add(placed.name)
            usable = [m for m in placed.models
                      if not m.hidden and m.variable == "KICAD7_3DMODEL_DIR"]
            if len(usable) != 1:
                continue
            parts = usable[0].path.split("/")
            stated = (parts[-2].removesuffix(".3dshapes"),
                      parts[-1].removesuffix(".step"))
            component = table[placed.name]
            if stated == (component.library, component.model):
                agrees += 1
            else:
                disagrees += 1
    assert agrees >= 15, (
        f"only {agrees} stated models agree with CORRESPONDENCE; it was 17, "
        f"and the argument for not reading them is that they add nothing"
    )
    assert disagrees <= 1, (
        f"{disagrees} stated models now disagree with CORRESPONDENCE. It was "
        f"one, and the vendor was wrong about it. More than one means the "
        f"question of which source to believe is worth re-opening"
    )
