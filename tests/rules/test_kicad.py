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
    assert smd[0] == Pad("1", "smd", 7.62, -8.455, 2.432, 1.524)


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
    pads = read_geometry(mod, select="XIAO-ESP32-C3-SMD").pads

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
