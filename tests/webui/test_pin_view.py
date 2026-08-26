# OpenHardware — what a board's pins are doing, and what nobody can say.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this exists
#
# OH-66 put an IDE on three boards and a browser session found there was
# nowhere on the page a pin appeared. Two of the three cannot print -- a XIAO's
# `Serial` is USB CDC and there is no host to enumerate to -- so the only
# feedback a person got from a running sketch was an instruction count.
#
# ## The distinction every test here is about
#
# `high`, `low` and `input` are claims about the *program*. `unknown` is a
# claim about *this repository*: a pad whose label the board module has no
# entry for, or a power pad with no MCU pin behind it at all.
#
# Collapsing the two would produce a board picture with every pad dark and no
# way to tell a quiet program from a thin model -- which is the failure this
# project ranks worst and the reason `webui/api.py` has a four-value vocabulary
# rather than a boolean.
#
# ## Two boards over two cores, on purpose
#
# The Uno reads a byte of AVR data space and the XIAO reads two 32-bit Arm
# registers, and both export one name. That is what keeps `webui/api.py` free
# of chip knowledge, so both are exercised here rather than whichever was
# convenient.

import pytest

from webui import api
from webui.boards import atmega328p, samd21

UNO = "Arduino Uno"
XIAO = "XIAO-SAMD21-DIP"

#: A sketch that drives one header pin and the on-board LED, so a test can tell
#: a pin that moved from a pin that was never configured. `D0` is a pad and
#: `LED_BUILTIN` is not, which is the whole difference this file cares about.
DRIVE = """
void setup() { pinMode(LED_BUILTIN, OUTPUT); pinMode(D0, OUTPUT); }
void loop() { digitalWrite(LED_BUILTIN, HIGH); digitalWrite(D0, HIGH); }
"""

UNO_DRIVE = """
void setup() { pinMode(13, OUTPUT); }
void loop() { digitalWrite(13, HIGH); }
"""


def built(board: str, source: str):
    """Compile and load, or skip with the reason nothing can build."""
    compiler = pytest.importorskip("webui.compile")
    recipe = compiler.recipe_for(board)
    try:
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
        compiler.variant_root(recipe)
        compiler.include_roots(recipe)
        compiler.linker_script(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    image = compiler.build(board, source)
    assert image.ok, image.diagnostics
    return api.load_firmware(board, image.image, base=recipe.base)


# --- the board modules, which need no compiler ------------------------------


def test_both_boards_export_the_name_the_api_looks_for():
    """`getattr(description, "pin_states")`, the same shape `uart_view` uses.

    Two chips over two cores exporting one name is what keeps `webui/api.py`
    from knowing what a PORT is.
    """
    assert callable(atmega328p.pin_states)
    assert callable(samd21.pin_states)


def test_the_pin_names_are_derived_from_the_same_table_the_levels_come_from():
    """A second hand-written table would be a second thing to get wrong, and
    it would be wrong in a caption rather than in a register read -- which is
    exactly the kind of error nobody notices."""
    assert set(samd21.PIN_NAMES) == set(samd21.HEADER)
    assert set(atmega328p.PIN_NAMES) == set(atmega328p.HEADER)
    assert samd21.PIN_NAMES["LED"] == f"PA{samd21.LED_PIN}"
    assert atmega328p.PIN_NAMES["13"] == f"PB{atmega328p.LED_PIN}"


def test_the_xiaos_led_is_a_pin_and_not_a_pad():
    """`LED_BUILTIN` on a XIAO is on the board, not on the header, so it has a
    state and no coordinate. It is also the pin a stock Blink drives, which is
    why leaving it out would hide the commonest sketch there is."""
    assert "LED" in samd21.HEADER
    assert samd21.HEADER["LED"] == (samd21.PORTA, samd21.LED_PIN)


def test_the_uno_maps_only_the_port_its_board_models():
    """Six of thirty-two pads. Pins 0-7 are PORTD and A0-A5 are PORTC, and
    `webui/boards/atmega328p.py` models neither -- so they must be absent from
    `HEADER` rather than present and answering zero."""
    assert set(atmega328p.HEADER) == {"8", "9", "10", "11", "12", "13"}


# --- the join, with a real image --------------------------------------------


def test_a_driven_pad_reads_high_and_an_untouched_one_reads_input():
    """**The headline.** A pin the sketch drove and a pin it did not, told
    apart -- which is the entire point of the panel this feeds."""
    with built(XIAO, DRIVE) as session:
        for _ in range(60_000):
            session.step()
        view = api.pin_view(session.runtime, session.cpu, XIAO)
        states = {pad["pin"]: pad["state"] for pad in view["pads"]}
    assert states["D0"] == "high"
    assert states["LED"] == "high"
    assert states["D1"] == "input"


def test_a_power_pad_is_unknown_and_not_low():
    """`GND` has no MCU pin behind it and never will. Reporting it `low` would
    be a sentence about the program when the truth is a sentence about the
    board."""
    with built(XIAO, DRIVE) as session:
        session.step(1000)
        view = api.pin_view(session.runtime, session.cpu, XIAO)
        states = {pad["pin"]: pad["state"] for pad in view["pads"]}
    for pad in ("GND", "3V3_OUT", "VBUS"):
        assert states[pad] == "unknown"


def test_the_unknown_count_is_reported_rather_than_left_to_be_counted():
    """"6 of 32 answerable" is what tells a reader they are looking at a thin
    model rather than a quiet program."""
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
    assert view["unknown"] == sum(
        1 for pad in view["pads"] if pad["state"] == "unknown"
    )
    # Twenty-six of the Uno's thirty-two, because only PORTB is modelled.
    assert view["unknown"] == 26


def test_the_silkscreens_pwm_tilde_does_not_stop_a_pin_being_found():
    """The Uno's pad map spells pin 11 `~11`, because that is what is printed
    on the board. The board module calls it `11`, because that is its name.
    One character, and without it five of the six answerable pads would read
    `unknown`."""
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
        pads = {pad["label"]: pad for pad in view["pads"]}
    assert pads["~11"]["pin"] == "11"
    assert pads["~11"]["state"] != "unknown"
    assert pads["~11"]["chip_pin"] == "PB3"


def test_a_pad_carries_the_chip_pin_it_reaches():
    """The connection the view is named for: `D6` is `PB08` and `13` is `PB5`.
    A pad with no MCU pin carries `None`, which is a missing caption rather
    than a missing state."""
    with built(XIAO, DRIVE) as session:
        session.step(1000)
        view = api.pin_view(session.runtime, session.cpu, XIAO)
        pads = {pad["pin"]: pad for pad in view["pads"]}
    assert pads["D6"]["chip_pin"] == "PB08"
    assert pads["LED"]["chip_pin"] == "PA17"
    assert pads["GND"]["chip_pin"] is None


def test_a_pad_carries_the_position_the_vendors_footprint_gave_it():
    """Position comes from `webui/pinmap.py` and therefore from the board
    JSON, whose own `derivation` says the centres are exact to three decimals
    in millimetres. Nothing here rounds or lays out."""
    from webui import pinmap

    layout = pinmap.load(XIAO)
    expected = {pad.label: (pad.x, pad.y) for pad in layout.pads}
    with built(XIAO, DRIVE) as session:
        session.step(1000)
        view = api.pin_view(session.runtime, session.cpu, XIAO)
    assert view["width"] == layout.width
    assert view["height"] == layout.height
    for pad in view["pads"]:
        if pad["x"] is not None:
            assert (pad["x"], pad["y"]) == expected[pad["label"]]


def test_a_pin_with_no_pad_is_reported_with_no_position():
    """Not dropped. The XIAO's LED would otherwise be invisible, and it is the
    pin most sketches move."""
    with built(XIAO, DRIVE) as session:
        session.step(1000)
        view = api.pin_view(session.runtime, session.cpu, XIAO)
        led = next(pad for pad in view["pads"] if pad["pin"] == "LED")
    assert led["x"] is None and led["y"] is None
    assert led["group"] == "on-board"


def test_the_state_poll_carries_levels_without_the_geometry():
    """Where a pad is never changes and what it is doing changes constantly,
    so `state()` carries only the second. Sending thirty-two coordinates
    twenty times a second to redraw the same board is the whole difference."""
    with built(XIAO, DRIVE) as session:
        session.step(60_000)
        state = session.state()
    assert state["pins"]["D0"] == "high"
    assert "x" not in str(state["pins"]), "geometry leaked into the poll"


def test_every_reported_state_is_one_of_the_four_the_api_names():
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
    for pad in view["pads"]:
        assert pad["state"] in api.PIN_STATES


# --- a board that cannot answer ---------------------------------------------


class _Silent:
    """A board description with no `pin_states`, which is every board but two.

    A stub rather than a real module because the point is the *absence*, and
    every module that has the attribute today would have to have it removed to
    test this -- which is a worse test and a temporarily broken board.
    """

    __name__ = "webui.boards.nothing"


def test_a_board_that_maps_no_pins_says_so_rather_than_reporting_none():
    """The same shape `uart_view` uses for a board with no UART, and for the
    same reason: an empty table reads as a program that has driven nothing,
    which is a claim about the sketch."""
    runtime = api.Runtime(
        board="X", chip="Nothing", core="none",
        description=_Silent(), abi=None, machine=None,
    )
    view = api.pin_view(runtime, None, "X")
    assert view["present"] is False
    assert "webui.boards.nothing" in view["note"]
    assert "gap in the board description" in view["note"]
    assert api.pin_levels(runtime, None) is None
