# OpenHardware — tests for board pin maps.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Where a board's header pins sit on its image.

This is the one piece of board data nobody upstream has: `board.map` declares
controls and displays, never headers, and no `src/boards/*.cc` carries a
coordinate. So it is authored here, and these tests hold the authoring honest.
"""

from __future__ import annotations

import json

import pytest

from webui.pinmap import PinMapError, available, load, parse, synthesise

GOOD = {
    "board": "Example",
    "image": {"width": 100, "height": 50},
    "pads": [
        {"label": "13", "pin": 19, "x": 10, "y": 5, "group": "digital"},
        {"label": "GND", "pin": 22, "x": 20, "y": 5, "group": "digital"},
        {"label": "VIN", "pin": None, "x": 30, "y": 45, "group": "power"},
    ],
}


# --- the shipped map ---------------------------------------------------------


def test_the_arduino_uno_map_is_authored():
    assert "Arduino Uno" in available()


def test_the_uno_map_matches_its_art():
    """402x304 is what board.svg declares and what board.map reports."""
    pinmap = load("Arduino Uno")
    assert (pinmap.width, pinmap.height) == (402, 304)
    assert len(pinmap.pads) == 32
    assert len(pinmap.wireable) == 28


def test_the_uno_exposes_the_pads_that_have_no_mcu_pin():
    """NC, IOREF, 3V3 and VIN are real header pads with nothing behind them.

    Dropping them would make the header look wrong and would let a drag land
    on empty space with no explanation.
    """
    unwired = {pad.label for pad in load("Arduino Uno").pads if not pad.wireable}
    assert unwired == {"NC", "IOREF", "3V3", "VIN"}


def test_the_uno_pads_are_all_inside_the_image():
    pinmap = load("Arduino Uno")
    for pad in pinmap.pads:
        assert 0 <= pad.x <= pinmap.width
        assert 0 <= pad.y <= pinmap.height


def test_duplicate_pins_are_allowed_because_the_hardware_has_them():
    """On an Uno, SCL is A5 and SDA is A4; GND appears twice."""
    pinmap = load("Arduino Uno")
    assert pinmap.by_pin(28).label in ("SCL", "A5")
    gnds = [pad for pad in pinmap.pads if pad.label == "GND"]
    assert len(gnds) == 3, [p.group for p in gnds]


def test_an_unauthored_board_returns_none_rather_than_raising():
    """Coverage is partial by design; those boards fall back to the rail."""
    assert load("Blue Pill") is None


# --- refusals ----------------------------------------------------------------


def test_a_map_with_no_pads_raises():
    bad = {**GOOD, "pads": []}
    with pytest.raises(PinMapError, match="declares no pads"):
        parse(bad, "sample")


def test_a_pad_outside_the_image_raises():
    bad = {**GOOD, "pads": [{"label": "X", "pin": 1, "x": 500, "y": 5}]}
    with pytest.raises(PinMapError, match="outside the"):
        parse(bad, "sample")


def test_a_pin_above_the_protocol_ceiling_raises():
    """rcontrol reads an index as exactly two characters, so 100 is unreachable."""
    bad = {**GOOD, "pads": [{"label": "X", "pin": 100, "x": 5, "y": 5}]}
    with pytest.raises(PinMapError, match="must be 1..99"):
        parse(bad, "sample")


def test_a_pad_without_a_label_raises():
    bad = {**GOOD, "pads": [{"pin": 1, "x": 5, "y": 5}]}
    with pytest.raises(PinMapError, match="has no label"):
        parse(bad, "sample")


def test_a_pad_without_coordinates_raises():
    bad = {**GOOD, "pads": [{"label": "X", "pin": 1}]}
    with pytest.raises(PinMapError, match="no usable x/y"):
        parse(bad, "sample")


def test_malformed_json_raises(tmp_path):
    (tmp_path / "Broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PinMapError, match="not valid JSON"):
        load("Broken", tmp_path)


def test_a_good_map_round_trips_through_as_dict():
    pinmap = parse(GOOD, "sample")
    assert json.loads(json.dumps(pinmap.as_dict()))["pads"][0]["label"] == "13"


# --- synthesised headers, added 2026-08-12 ----------------------------------
#
# Only the Uno's pads are authored. The other twenty boards get a header laid
# out from the simulator's own pin list so they are wireable immediately.


def _pins(count: int):
    from webui.api import Pin

    return [
        Pin(index=i, type="D", direction="I", value=0, oavalue_raw=0,
            avalue=0.0, name=f"P{i}")
        for i in range(1, count + 1)
    ]


def test_a_synthesised_header_uses_the_simulators_own_pins():
    pinmap = synthesise("Test", _pins(28), 400, 300)
    assert len(pinmap.pads) == 28
    assert pinmap.pads[0].label == "P1"
    assert pinmap.pads[0].pin == 1
    assert all(pad.wireable for pad in pinmap.pads)


def test_a_synthesised_header_says_it_is_approximate():
    """The wiring is exact; only the picture is schematic. Do not imply more."""
    assert synthesise("Test", _pins(28), 400, 300).derived is True
    assert load("Arduino Uno").derived is False


def test_a_synthesised_header_stays_inside_the_board_image():
    for count in (4, 16, 17, 40, 64):
        pinmap = synthesise("Test", _pins(count), 376, 149)
        for pad in pinmap.pads:
            assert 0 <= pad.x <= pinmap.width, (count, pad.label, pad.x)
            assert 0 <= pad.y <= pinmap.height, (count, pad.label, pad.y)


def test_many_pins_wrap_onto_a_second_row():
    """A single row of forty on a small board is unusable."""
    assert len({p.group for p in synthesise("T", _pins(40), 400, 300).pads}) == 2
    assert len({p.group for p in synthesise("T", _pins(14), 400, 300).pads}) == 1


def test_a_board_with_no_pins_raises_rather_than_making_an_empty_header():
    with pytest.raises(PinMapError, match="reports no pins"):
        synthesise("Test", [], 400, 300)


def test_every_shipped_board_can_be_given_a_header():
    """The 3D view must work for all 21 boards, not only the authored one."""
    from webui.assets import available_boards, load_board

    for board in available_boards():
        art = load_board(board)
        pinmap = load(board) or synthesise(board, _pins(28), art.width, art.height)
        assert pinmap.wireable, board
        for pad in pinmap.wireable:
            assert 0 <= pad.x <= art.width and 0 <= pad.y <= art.height, board
