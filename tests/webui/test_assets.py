# OpenHardware — tests for the board art loader.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parse the art PICSimLab actually ships, not fixtures invented here.

A hand-written sample map would only prove the parser matches my idea of the
format -- the same defect that let three protocol bugs through a stub. So the
load-bearing test here runs every shipped board through the parser.
"""

from __future__ import annotations

import pytest

from webui.assets import (
    AssetError,
    available_boards,
    load_board,
    parse_map,
    resolve_board_name,
    sanitise,
    share_root,
)

HEADER = '<img src="x" width="402" height="304" border="0" usemap="#map" />'


def one(area: str) -> str:
    return f'{HEADER}\n<map name="map">\n{area}\n</map>'


# --- against the real shipped files ------------------------------------------


def test_every_shipped_board_parses():
    """The whole point. 21 boards, and a new one must not break silently."""
    boards = available_boards()
    assert len(boards) >= 20, boards
    for name in boards:
        art = load_board(name)
        assert art.regions, f"{name} parsed to no regions"
        assert art.width > 0 and art.height > 0
        assert art.svg.startswith(b"<") or b"svg" in art.svg[:200].lower()


def test_the_arduino_uno_has_the_regions_its_map_declares():
    """Pinned exactly, because these ids are what live values bind to."""
    art = load_board("Arduino Uno")
    assert {r.id for r in art.regions} == {
        "B_PB_RST",
        "I_SW_PWR",
        "I_PG_ICSP",
        "O_LD_L",
        "O_LD_TX",
        "O_LD_RX",
        "O_LD_ON",
    }
    led = next(r for r in art.regions if r.id == "O_LD_L")
    assert led.role == "output"
    # The name is what pairs with `board.out[01] LD_L` in an info dump.
    assert led.name == "LD_L"
    assert (led.left, led.top, led.right, led.bottom) == (158, 53, 169, 63)


def test_board_art_groups_by_role():
    art = load_board("Arduino Uno")
    assert len(art.by_role("output")) == 4
    assert len(art.by_role("button")) == 1
    assert len(art.by_role("input")) == 2


def test_share_root_finds_the_boards_directory():
    assert (share_root() / "boards").is_dir()


# --- shapes ------------------------------------------------------------------


def test_a_rect_keeps_its_corners():
    _, _, regions = parse_map(one('<area shape="rect" coords="1,2,3,4" href="O_A" />'))
    r = regions[0]
    assert (r.left, r.top, r.right, r.bottom) == (1, 2, 3, 4)
    assert r.radius is None


def test_a_circle_becomes_a_bounding_box_and_keeps_its_radius():
    """So a caller needing a hit area never has to branch on shape."""
    _, _, regions = parse_map(one('<area shape="circle" coords="10,20,5" href="O_A" />'))
    r = regions[0]
    assert (r.left, r.top, r.right, r.bottom) == (5, 15, 15, 25)
    assert r.radius == 5
    assert r.centre == (10, 20)


# --- refusals ----------------------------------------------------------------


def test_an_unknown_role_prefix_raises():
    with pytest.raises(AssetError, match="unknown role prefix"):
        parse_map(one('<area shape="rect" coords="1,2,3,4" href="Z_MYSTERY" />'))


def test_an_unsupported_shape_raises_rather_than_being_skipped():
    """Skipping would lose an element the UI then never draws, silently."""
    with pytest.raises(AssetError, match="unsupported shape"):
        parse_map(one('<area shape="poly" coords="1,2,3,4,5,6" href="O_A" />'))


def test_a_map_with_no_regions_raises():
    with pytest.raises(AssetError, match="no <area> regions"):
        parse_map(f'{HEADER}\n<map name="map">\n</map>')


def test_a_map_with_no_size_raises():
    with pytest.raises(AssetError, match="no width/height"):
        parse_map('<map name="map">\n<area shape="rect" coords="1,2,3,4" href="O_A" />')


def test_wrong_coordinate_count_raises():
    with pytest.raises(AssetError, match="rect needs 4"):
        parse_map(one('<area shape="rect" coords="1,2,3" href="O_A" />'))
    with pytest.raises(AssetError, match="circle needs 3"):
        parse_map(one('<area shape="circle" coords="1,2" href="O_A" />'))


# --- the two names every board has ------------------------------------------


def test_sanitise_matches_the_simulators_own_rule():
    """board.cc:585-590 turns both space and hyphen into underscore."""
    assert sanitise("Arduino Uno") == "Arduino_Uno"
    assert sanitise("ESP32-DevKitC") == "ESP32_DevKitC"
    assert sanitise("ESP32-C3-DevKitC-02") == "ESP32_C3_DevKitC_02"


def test_every_board_resolves_from_the_name_blist_reports():
    """`blist` gives `name_`, `info` gives `name`, art uses `name`.

    Ten of the twenty-one shipped boards contain a space or hyphen, so a UI
    that fed `blist` names to the art loader would fail on half the catalogue.
    """
    for art_name in available_boards():
        assert resolve_board_name(sanitise(art_name)) == art_name


def test_the_lossy_direction_is_never_guessed():
    """`ESP32_C3_DevKitC_02` must resolve to the hyphenated art directory.

    Un-sanitising is impossible -- an underscore could have been either
    character -- so resolution sanitises the candidates instead. This is the
    case that proves it, since a space-substituting inverse would produce
    "ESP32 C3 DevKitC 02", which does not exist.
    """
    assert resolve_board_name("ESP32_C3_DevKitC_02") == "ESP32-C3-DevKitC-02"
    assert resolve_board_name("ESP32-C3-DevKitC-02") == "ESP32-C3-DevKitC-02"


def test_load_board_accepts_either_name_form():
    assert load_board("Blue_Pill").name == "Blue Pill"
    assert load_board("Blue Pill").name == "Blue Pill"


def test_an_unknown_board_name_lists_what_is_known():
    with pytest.raises(AssetError, match="no board art matches"):
        resolve_board_name("Raspberry Pi Pico")


def test_a_missing_board_raises():
    with pytest.raises(AssetError, match="missing board.svg|no board"):
        load_board("No Such Board")
