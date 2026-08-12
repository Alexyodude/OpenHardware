# OpenHardware — tests for the draw-list model.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""The decision layer, tested where the decisions are.

There is no browser test runner in this repository, so this is the only place
the UI's logic can be checked at all. That is the reason it lives in Python:
`.claude/rules/conformance-fixtures.md` §3 will not let a cell reach `done`
without a fixture, and a fixture that cannot see the logic proves nothing.

The `info` text below is a **verbatim capture** from a live PICSimLab 0.9.3 on
2026-08-12, not a format invented to match the parser.
"""

from __future__ import annotations

import pytest

from webui.assets import load_board, load_part
from webui.render_model import StateError, build, parse_info

LIVE_INFO = """Board:     Arduino Uno
Processor: atmega328p
Frequency:   16000000 Hz
Use Spare: 1
    board.out[01] LD_L= 200
  part[00]: Push Buttons
    part[00].in[00] PB_1= 0
    part[00].in[01] PB_2= 0
    part[00].in[02] PB_3= 1
    part[00].in[03] PB_4= 0
    part[00].in[04] PB_5= 0
    part[00].in[05] PB_6= 0
    part[00].in[06] PB_7= 0
    part[00].in[07] PB_8= 0"""


# --- parsing -----------------------------------------------------------------


def test_a_live_info_dump_parses():
    state = parse_info(LIVE_INFO)
    assert state.board == "Arduino Uno"
    assert state.processor == "atmega328p"
    assert state.frequency == "16000000 Hz"
    assert state.use_spare is True


def test_board_outputs_keep_index_name_and_value():
    state = parse_info(LIVE_INFO)
    assert len(state.board_outputs) == 1
    led = state.board_outputs[0]
    # index 1, not 01 -- the two-digit form is a wire detail, not a model one.
    assert (led.index, led.name, led.value) == (1, "LD_L", 200.0)


def test_parts_carry_their_named_inputs():
    state = parse_info(LIVE_INFO)
    assert len(state.parts) == 1
    part = state.parts[0]
    assert (part.index, part.name) == (0, "Push Buttons")
    assert len(part.inputs) == 8
    assert part.inputs[2].name == "PB_3"
    assert part.inputs[2].value == 1.0


def test_lookup_by_name_is_how_art_binds_to_state():
    state = parse_info(LIVE_INFO)
    assert state.output_named("LD_L").index == 1
    assert state.output_named("LD_TX") is None


def test_a_reply_without_a_board_line_raises():
    """A blank state must never be mistaken for an empty board."""
    with pytest.raises(StateError, match="not an info reply"):
        parse_info("Processor: atmega328p\nUse Spare: 0")


def test_part_io_before_its_header_raises():
    with pytest.raises(StateError, match="before any part header"):
        parse_info("Board: X\n    part[00].in[00] PB_1= 0")


def test_use_spare_zero_is_false():
    assert parse_info("Board: X\nUse Spare: 0").use_spare is False


# --- the draw list -----------------------------------------------------------


def model():
    state = parse_info(LIVE_INFO)
    return build(state, load_board("Arduino Uno"))


def test_the_draw_list_covers_every_region_the_art_declares():
    m = model()
    assert len(m["regions"]) == 7
    assert m["board"] == "Arduino Uno"
    assert (m["width"], m["height"]) == (402, 304)


def test_a_region_the_simulator_reports_is_bound_and_lit():
    led = next(r for r in model()["regions"] if r["id"] == "O_LD_L")
    assert led["value"] == 200.0
    assert led["active"] is True
    assert led["index"] == 1
    assert led["intensity"] == pytest.approx(200 / 255)


def test_regions_the_board_does_not_report_are_kept_and_counted():
    """Dropping them would make a firmware/art mismatch invisible."""
    m = model()
    assert m["unbound"] == 6
    dark = next(r for r in m["regions"] if r["id"] == "O_LD_TX")
    assert dark["value"] is None
    assert dark["active"] is False
    assert dark["index"] is None


def test_an_unbound_control_is_not_clickable():
    """Clicking it would send an index the model does not have."""
    reset = next(r for r in model()["regions"] if r["id"] == "B_PB_RST")
    assert reset["value"] is None
    assert reset["clickable"] is False


def test_an_output_is_never_clickable_even_when_bound():
    led = next(r for r in model()["regions"] if r["id"] == "O_LD_L")
    assert led["clickable"] is False


def test_a_bound_input_is_clickable():
    """The Uno reports no board inputs, so this uses a synthetic dump.

    Written as a state whose input name matches the Uno's own `I_SW_PWR`
    region, so the binding path is exercised against real art.
    """
    state = parse_info("Board: Arduino Uno\n    board.in[00] SW_PWR= 0")
    m = build(state, load_board("Arduino Uno"))
    switch = next(r for r in m["regions"] if r["id"] == "I_SW_PWR")
    assert switch["value"] == 0.0
    assert switch["index"] == 0
    assert switch["clickable"] is True


def test_intensity_is_clamped_to_one():
    state = parse_info("Board: Arduino Uno\n    board.out[01] LD_L= 4000")
    led = next(
        r for r in build(state, load_board("Arduino Uno"))["regions"]
        if r["id"] == "O_LD_L"
    )
    assert led["intensity"] == 1.0


def test_parts_reach_the_draw_list_with_their_inputs():
    part = model()["parts"][0]
    assert part["name"] == "Push Buttons"
    assert len(part["inputs"]) == 8
    assert part["inputs"][2]["value"] == 1.0


# --- pin anchors, added 2026-08-12 ------------------------------------------
#
# A part's pins are drawn at `O_PN_<n>` regions and named by its schema. The
# correspondence is positional and nothing states it, so `_anchors` checks the
# counts agree and returns nothing at all when they do not.


def test_anchors_land_on_the_parts_own_pin_label_regions():
    state = parse_info(LIVE_INFO)
    detail = lambda index, name: {  # noqa: E731 - a stub, not a design
        "labels": [f"B{i}" for i in range(1, 9)],
        "wiring": {"B1": 9},
    }
    m = build(state, load_board("Arduino Uno"), part_art=load_part,
              part_detail=detail)
    anchors = m["parts"][0]["anchors"]
    assert len(anchors) == 8
    assert anchors[0]["label"] == "B1"
    assert anchors[0]["wired_to"] == 9
    assert anchors[1]["wired_to"] is None
    # Position comes from the art, not from anything invented here.
    art = load_part("Push Buttons")
    first = next(r for r in art.regions if r.id == "O_PN_1")
    assert anchors[0]["x"] == first.centre[0]


def test_a_count_disagreement_yields_no_anchors_rather_than_wrong_ones():
    """Nine labels against eight drawn pins: draw nothing.

    A wire from the wrong dot would make the picture lie about which pin is
    connected, which is worse than making the user wire from the form.
    """
    state = parse_info(LIVE_INFO)
    detail = lambda index, name: {  # noqa: E731
        "labels": [f"B{i}" for i in range(1, 10)],
        "wiring": {},
    }
    m = build(state, load_board("Arduino Uno"), part_art=load_part,
              part_detail=detail)
    assert m["parts"][0]["anchors"] == []


def test_a_part_with_no_schema_gets_no_anchors():
    state = parse_info(LIVE_INFO)
    m = build(state, load_board("Arduino Uno"), part_art=load_part,
              part_detail=lambda index, name: None)
    assert m["parts"][0]["anchors"] == []


def test_anchors_are_absent_when_no_detail_source_is_given():
    state = parse_info(LIVE_INFO)
    m = build(state, load_board("Arduino Uno"), part_art=load_part)
    assert m["parts"][0]["anchors"] == []
