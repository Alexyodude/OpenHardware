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

import json
import pathlib
import struct
import types

import pytest

from webui import api, pinmap
from webui.boards import atmega328p, catalogue, samd21

UNO = "Arduino Uno"
XIAO = "XIAO-SAMD21-DIP"

MODELS = (pathlib.Path(__file__).resolve().parents[2]
          / "webui" / "static" / "models")


def board_solids(model: pathlib.Path) -> list[dict]:
    """Every component box a composed board model states, by name.

    A `.glb` is a length-prefixed JSON chunk followed by binary, and only the
    JSON is wanted -- so this reads the container by hand rather than adding a
    glTF dependency to the test suite for one lookup.
    """
    raw = model.read_bytes()
    at = 12
    doc = None
    while at < len(raw):
        size, kind = struct.unpack_from("<II", raw, at)
        at += 8
        if kind == 0x4E4F534A:                        # the ASCII "JSON"
            doc = json.loads(raw[at:at + size].decode("utf-8"))
            break
        at += size
    if doc is None:
        raise AssertionError(f"{model} has no JSON chunk")

    def find(node: object) -> list[dict] | None:
        if isinstance(node, dict):
            extras = node.get("extras")
            if isinstance(extras, dict) and isinstance(extras.get("solids"), list):
                return extras["solids"]
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value)
                if found is not None:
                    return found
        return None

    return find(doc) or []

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


def test_the_uno_maps_every_pad_with_an_mcu_pin_behind_it():
    """Twenty-two of thirty-two, and the ten it leaves out are the claim.

    OH-70 took this from six by adding PORTC and PORTD. What must stay absent
    is every pad with no MCU pin behind it -- `AREF`, `NC`, `IOREF`, `RESET`,
    the supplies and the grounds -- because a `low` for `GND` would be a
    sentence about the program when the truth is a sentence about the board.
    """
    assert len(atmega328p.HEADER) == 22
    assert set(atmega328p.HEADER) >= {"0", "7", "13", "A0", "A5"}
    # Spelled out rather than derived from the pad map, so that a pad map that
    # grew a `GND` entry could not quietly make this test agree with it.
    supplies = {"AREF", "NC", "IOREF", "RESET", "3V3", "5V", "VIN", "GND"}
    assert not supplies & set(atmega328p.HEADER)


def test_the_unos_two_i2c_labels_are_the_two_analog_pads_they_duplicate():
    """`SDA` and `SCL` are not extra pins. `pins_arduino.h:48-51` makes them
    digital 18 and 19, which is PC4 and PC5 -- the same silicon as `A4` and
    `A5`, brought out a second time on the R3 header.

    So a sketch driving `A4` must move both rows of the picture. Reporting one
    of them and not the other would be a board that does not exist.
    """
    assert atmega328p.HEADER["SDA"] == atmega328p.HEADER["A4"]
    assert atmega328p.HEADER["SCL"] == atmega328p.HEADER["A5"]
    assert atmega328p.PIN_NAMES["SDA"] == "PC4"
    assert atmega328p.PIN_NAMES["SCL"] == "PC5"


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
    """"22 of 32 answerable" is what tells a reader whether they are looking at
    a thin model or a quiet program."""
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
    assert view["unknown"] == sum(
        1 for pad in view["pads"] if pad["state"] == "unknown"
    )
    # Ten of the Uno's thirty-two, and every one of them is a pad with no MCU
    # pin behind it. **Named rather than counted**: a count alone would still
    # pass if PORTC went missing and five power pads appeared from somewhere.
    assert sorted(pad["label"] for pad in view["pads"]
                  if pad["state"] == "unknown") == [
        "3V3", "5V", "AREF", "GND", "GND", "GND", "IOREF", "NC", "RESET", "VIN"
    ]


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


def test_a_board_with_nothing_to_draw_and_nothing_to_report_says_so():
    """The same shape `uart_view` uses for a board with no UART, and for the
    same reason: an empty table reads as a program that has driven nothing,
    which is a claim about the sketch.

    **`present` narrowed under OH-94 and this test had to say which meaning it
    holds.** It used to mean "the description reports no pin states", which
    hid every board whose chip has no `pin_states` -- twenty-three of the
    twenty-six then and fourteen since OH-160 -- even though they have pad
    maps and could be drawn. (Both this docstring and `api.pad_view`'s said
    twenty-four until OH-160 measured it; `samd21.py` had a `pin_states` when
    the sentence was written, so its two boards were never among them.) It now
    means "there is nothing to draw AND nothing to report", and board `"X"`
    qualifies on both counts: no `webui/boards/X.json` and no levels.

    Without this rewrite the test would keep passing for a reason it does not
    state, which this repository has now been bitten by twice.
    """
    runtime = api.Runtime(
        board="X", chip="Nothing", core="none",
        description=_Silent(), abi=None, machine=None,
    )
    assert pinmap.load("X") is None, "the fixture board must have no pad map"
    view = api.pin_view(runtime, None, "X")
    assert view["present"] is False
    assert "webui.boards.nothing" in view["note"]
    assert "no pad map" in view["note"]
    assert "gap in the board description" in view["note"]
    assert api.pin_levels(runtime, None) is None


# --- a board that has been picked but not loaded (OH-94) --------------------


def test_a_board_with_pads_and_no_core_still_reports_where_they_are():
    """**The change OH-94 is for, and the board that proves it.**

    A `XIAO-MG24-DIP` has twenty-four pads in `webui/boards/`, no built core,
    and no `webui/boards/mg24.py` at all. Where its pads sit is not an
    execution and must not need one -- `runtime_for` would refuse it at three
    separate joins.
    """
    view = api.pad_view("XIAO-MG24-DIP", api.description_for("XIAO-MG24-DIP"),
                        None)
    assert view["present"] is True
    assert len(view["pads"]) == 24
    assert view["unknown"] == 24, "nothing is running, so nothing is answerable"
    assert all(pad["state"] == "unknown" for pad in view["pads"])
    assert view["width"] and view["height"], "the page needs a size to scale by"


def test_a_board_with_no_description_module_is_drawn_rather_than_refused():
    """`webui.boards.mg24` does not exist. That is a board without pin names,
    not a board that cannot be drawn, so `description_for` answers None."""
    assert api.description_for("XIAO-MG24-DIP") is None
    assert api.description_for("Arduino Uno") is not None
    # A board the catalogue has never heard of is also None rather than a
    # traceback out of the middle of a request.
    assert api.description_for("no such board") is None


def test_picking_a_board_and_loading_one_give_the_same_geometry():
    """**One implementation, and this is what says so.**

    The view of a board you picked and the view of a board you loaded are the
    same view with and without states. Two functions answering that question
    is how `readPalette` and the glTF writer disagreed about sRGB for as long
    as both existed, so `pin_view` is a caller of `pad_view` and the pads must
    match position for position.
    """
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        loaded = api.pin_view(session.runtime, session.cpu, UNO)
    picked = api.pad_view(UNO, api.description_for(UNO), None)

    assert picked["present"] == loaded["present"] is True
    assert [(p["label"], p["x"], p["y"]) for p in picked["pads"]] == \
           [(p["label"], p["x"], p["y"]) for p in loaded["pads"]]
    # The supply rides the geometry, so it survives without a session too.
    assert picked["supply"] == loaded["supply"]
    # And the ONE thing that differs is the states.
    assert picked["unknown"] == len(picked["pads"])
    assert loaded["unknown"] < len(loaded["pads"])


# --- what a pin can drive, for the circuit the 3D view solves ---------------


def test_the_pin_view_carries_what_a_pin_of_this_board_can_drive():
    """**The join OH-79 added**, and it rides the geometry rather than the poll.

    `webui/static/circuit.js` cannot solve anything without a supply voltage
    and an output resistance, and neither is derivable from a pin level. They
    come with the pad map, once, because an output resistance is a property of
    silicon and does not change while a sketch runs.
    """
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
    supply = view["supply"]
    assert supply is not None
    assert supply["chip"] == "ATmega328P"
    assert supply["volts"] == 5.0
    # Every number carries where it came from. A supply whose provenance had
    # been dropped in transit would let the page print a current nobody could
    # trace back to a datasheet, which is the failure `Electrical` and `SPECS`
    # are both shaped to prevent.
    for name in ("volts", "source_ohms", "sink_ohms", "rated_amps",
                 "absolute_amps"):
        assert supply["cited"][name]


def test_a_supply_is_json_and_not_a_python_object():
    """It crosses to the browser, so every value in it has to survive the trip.

    A dataclass or a tuple here would be a 500 from `/api/board/pins` on the
    one board a reader is most likely to be looking at, and nothing else in
    this file would have caught it.
    """
    import json

    with built(XIAO, DRIVE) as session:
        session.step(1000)
        view = api.pin_view(session.runtime, session.cpu, XIAO)
    back = json.loads(json.dumps(view))
    assert back["supply"]["volts"] == 3.3
    # **Null rather than a number, and it is a real absence.** The SAM D21
    # states no per-pin absolute maximum at all -- its limit is per cluster.
    assert back["supply"]["absolute_amps"] is None
    assert "cluster" in back["supply"]["cited"]["absolute_amps"]


def test_a_board_with_no_supply_model_says_null_rather_than_guessing():
    """Nine of the ten boards with a 3D model publish no `SUPPLY`.

    The page then solves no circuit and says why. A default of five volts here
    would light a part on a 3.3 V board at half again the current it draws.
    """
    runtime = api.Runtime(
        board="X", chip="Nothing", core="none",
        description=_Silent(), abi=None, machine=None,
    )
    assert getattr(runtime.description, "SUPPLY", None) is None


# --- a pad the timer took, at the register level (OH-71) ---------------------


class _Registers:
    """A data space that answers `read_data` and nothing else.

    **`pin_states` needs exactly one call**, which is what its own `Cpu`
    protocol says, so a dict behind that call reaches states a compiled sketch
    cannot easily be made to produce -- specifically `COM` bits set while the
    direction register still says input. Driving a real core there would mean
    a sketch that enables a compare output without calling `pinMode`, which
    `analogWrite` never does.
    """

    def __init__(self, values: dict[int, int]):
        self._values = values

    def read_data(self, address: int) -> int:
        return self._values.get(address, 0)


def _all_outputs() -> dict[int, int]:
    """Every pad an output and nothing driven high, so the baseline is `low`."""
    return {atmega328p.DDRB: 0xFF, atmega328p.DDRC: 0xFF, atmega328p.DDRD: 0xFF}


def test_a_timer_pad_is_unknown_only_when_its_own_com_bits_are_set():
    """One channel enabled leaves the other five pads alone.

    A `TIMER_PINS` row pointing at the wrong register or the wrong COM pair
    would show up here. **Pin 11 is the assertion that matters**: it is the
    OTHER channel of the SAME register as pin 3, so a mask that read the whole
    of `TCCR2A` rather than one channel's two bits would take it too, and a
    test that only looked at other timers would not notice.
    """
    quiet = atmega328p.pin_states(_Registers(_all_outputs()))
    assert quiet["3"] == "low" and quiet["11"] == "low", (
        "with no COM bits set every tilde pad is its port's"
    )

    taken = _all_outputs()
    taken[atmega328p.TCCR2A] = atmega328p.COM_B_MASK
    states = atmega328p.pin_states(_Registers(taken))
    assert states["3"] == "unknown", "OC2B has taken PD3"
    assert states["11"] == "low", (
        "OC2A shares TCCR2A with OC2B and was NOT enabled, so pin 11 is still "
        "PORTB's -- a mask over the whole register would break this"
    )
    for label in ("5", "6", "9", "10"):
        assert states[label] == "low", f"pad {label} is on another timer"


def test_each_timer_pad_answers_to_its_own_register_and_no_other():
    """Every one of the six, one at a time. Three registers and two channels
    each, so a row that named timer 1 where it meant timer 2 -- or channel A
    where it meant B -- moves the wrong pad and only a sweep sees it."""
    for label, (register, mask) in atmega328p.TIMER_PINS.items():
        values = _all_outputs()
        values[register] = mask
        states = atmega328p.pin_states(_Registers(values))
        assert states[label] == "unknown", (
            f"enabling {mask:#04x} in {register:#04x} did not take pad {label}"
        )
        others = [other for other in atmega328p.TIMER_PINS if other != label]
        assert all(states[other] == "low" for other in others), (
            f"enabling pad {label}'s compare output also took "
            f"{[o for o in others if states[o] != 'low']}"
        )


def test_a_compare_output_does_not_reach_a_pad_the_direction_register_calls_an_input():
    """**The datasheet is explicit and the order of the checks encodes it.**

    "The Data Direction Register bit for the OCnx pin must be set as output
    before the OCnx value is visible on the pin." So COM bits set with DDR
    clear is a pad that is still an input, and answering `unknown` about it
    would be this function's own confident wrong answer -- the very class
    OH-71 was filed about, reintroduced by its own fix.
    """
    states = atmega328p.pin_states(
        _Registers({atmega328p.TCCR2A: atmega328p.COM_B_MASK}))
    assert states["3"] == "input", (
        "DDRD bit 3 is clear, so the compare output does not reach the pad and "
        "the honest answer is that nobody is driving it"
    )


def test_every_timer_pad_is_one_the_header_knows_and_they_are_the_six_tilde_pins():
    """The table cannot name a pad the board does not have, and it is exactly
    the six an Uno's silkscreen marks with a tilde -- 3, 5, 6, 9, 10 and 11,
    from the vendor's own `digital_pin_to_timer_PGM`."""
    assert set(atmega328p.TIMER_PINS) == {"3", "5", "6", "9", "10", "11"}
    for label in atmega328p.TIMER_PINS:
        assert label in atmega328p.HEADER, f"{label} is not a header pin"
    assert not set(atmega328p.TIMER_PINS) & set(atmega328p.USART_PINS), (
        "a pad cannot be taken by both peripherals in this model"
    )


def test_the_timer_control_registers_are_the_addresses_the_vendor_header_gives():
    """**Restated here rather than derived, and that is the point.**

    `test_each_timer_pad_answers_to_its_own_register_and_no_other` writes to
    whatever address `TIMER_PINS` names and then reads it back, so it agrees
    with itself however wrong the table is -- a right-hand side imported from
    the thing under test, which is the defect this repository has been caught
    by before. A mutation moving `TCCR1A` to 0xA0 survived it.

    So the addresses are asserted against `iom328p.h` directly:

        #define TCCR0A _SFR_IO8(0x24)     line 221  -> 0x24 + 0x20 = 0x44
        #define TCCR1A _SFR_MEM8(0x80)    line 516  -> 0x80
        #define TCCR2A _SFR_MEM8(0xB0)    line 625  -> 0xB0

    **`_SFR_IO8` adds 0x20 and `_SFR_MEM8` does not**, which is the same trap
    `TIFR0` records beside its own definition -- and it is why timer 0's
    register is not simply the number in its macro.
    """
    assert atmega328p.TCCR0A == 0x44, "_SFR_IO8(0x24) is 0x44 in the data space"
    assert atmega328p.TCCR1A == 0x80, "_SFR_MEM8(0x80) is 0x80 unchanged"
    assert atmega328p.TCCR2A == 0xB0, "_SFR_MEM8(0xB0) is 0xB0 unchanged"
    assert len({atmega328p.TCCR0A, atmega328p.TCCR1A, atmega328p.TCCR2A}) == 3
    # And the two masks are two bits each and do not overlap: COMnx1:COMnx0 is
    # one channel's pair, and the two channels share the byte.
    assert bin(atmega328p.COM_A_MASK).count("1") == 2
    assert bin(atmega328p.COM_B_MASK).count("1") == 2
    assert not atmega328p.COM_A_MASK & atmega328p.COM_B_MASK


# --- the four generated tables, and the join a compound label needs (OH-160) --


def test_a_pad_label_with_two_names_joins_on_the_one_the_module_defines():
    """`D9/BOOT` is one pad silkscreened twice, and the packages define `D9`.

    `header_key` is the one place a pad's spelling meets the module's, and it
    must be exact in both directions: a compound label lands on the half the
    module knows whichever order the silkscreen wrote it in, and a label the
    module knows nothing about comes back whole rather than as a fragment.
    """
    from webui.boards import esp32c3

    names = esp32c3.PIN_NAMES
    assert api.header_key("D9/BOOT", names) == "D9"
    assert api.header_key("BOOT/D9", names) == "D9"
    assert api.header_key("D3/MTDI", names) == "D3"
    assert api.header_key("GND", names) == "GND"
    assert api.header_key("MTMS/MTDI", names) == "MTMS/MTDI"
    assert api.header_key("~11", atmega328p.PIN_NAMES) == "11"
    # KiCad's overbar, not the PWM mark: the SparkFun Thing Plus ESP32-C5's reset.
    assert api.header_key("~{RST}", atmega328p.PIN_NAMES) == "~{RST}"

    dip = api.pad_view("XIAO-ESP32-C3-DIP", api.description_for("XIAO-ESP32-C3-DIP"), None)
    boot = next(pad for pad in dip["pads"] if pad["label"] == "D9/BOOT")
    assert (boot["pin"], boot["chip_pin"]) == ("D9", "GPIO9")
    gnd = next(pad for pad in dip["pads"] if pad["label"] == "GND")
    assert (gnd["pin"], gnd["chip_pin"]) == ("GND", None)

    smd = api.pad_view("XIAO-ESP32-C3-SMD", api.description_for("XIAO-ESP32-C3-SMD"), None)
    d3 = [pad for pad in smd["pads"] if pad["pin"] == "D3"]
    assert {pad["label"] for pad in d3} == {"D3", "D3/MTDI"}, (
        "the castellation and the underside pad are one GPIO, and share a name"
    )
    assert {pad["chip_pin"] for pad in d3} == {"GPIO5"}


def test_the_four_generated_tables_derive_their_names_and_fit_one_register():
    """`PIN_NAMES` is `HEADER` read the other way, every value is a bit of one
    32-bit `OUT` register (`esp32c3.pin_states` says why that matters), and
    the ticket's own example holds: one label, four different pins."""
    from webui.boards import esp32c3, esp32c5, esp32c6, rp2040

    # The bound is each part's OWN, cited where its module's `pin_states`
    # cites it, because `< 32` would pass a table this silicon cannot hold:
    # the C3's `GPIO_OUT_DATA` is `bitpos:[25:0]` (gpio_reg.h:59), the C5's
    # and C6's `GPIO_OUT_DATA_ORIG` is `[31:0]` (:39 and :30), and the
    # RP2040's `GPIO_OUT` is "bits 29-0" (rp2040_v2/rp2040_sio.json).
    for module, led, width in (
        (esp32c3, None, 26), (esp32c5, 27, 32), (esp32c6, 15, 32), (rp2040, 17, 30)
    ):
        assert set(module.PIN_NAMES) == set(module.HEADER), module.__name__
        for label, gpio in module.HEADER.items():
            assert 0 <= gpio < width, (
                f"{module.__name__} {label} = {gpio}, outside this part's "
                f"{width}-bit register"
            )
            assert module.PIN_NAMES[label] == f"GPIO{gpio}", f"{module.__name__} {label}"
        assert {f"D{n}" for n in range(11)} <= set(module.HEADER), module.__name__
        assert module.HEADER.get("LED") == led, module.__name__
        assert "GND" not in module.HEADER and "3V3_OUT" not in module.HEADER
    assert (esp32c3.HEADER["D10"], esp32c5.HEADER["D10"], esp32c6.HEADER["D10"],
            rp2040.HEADER["D10"]) == (10, 10, 18, 3)
    assert (esp32c3.HEADER["D6"], rp2040.HEADER["D6"]) == (21, 0), "OH-26's example"


class _Words:
    """A bus that answers `read_word` from a dict and nothing else, so each
    module's `pin_states` can be shown a driven-but-disabled pin -- which a
    sketch reaches only by writing `OUT` without ever calling `pinMode`."""

    def __init__(self, values: dict[int, int]):
        self._values = values

    def read_word(self, address: int) -> int:
        return self._values.get(address, 0)


def test_the_esp32_and_rp2040_pin_states_read_the_enable_before_the_out():
    """`input` beats whatever `OUT` holds, `low` is an enabled pin at zero,
    and one bit moves exactly one label: the other rows of the table stay
    `input` when only `D10`'s bits are set."""
    from webui.boards import esp32c3, esp32c5, esp32c6, rp2040

    cases = (
        (esp32c3, esp32c3.GPIO + esp32c3.GPIO_ENABLE, esp32c3.GPIO + esp32c3.GPIO_OUT),
        (esp32c5, esp32c5.GPIO + esp32c5.GPIO_ENABLE, esp32c5.GPIO + esp32c5.GPIO_OUT),
        (esp32c6, esp32c6.GPIO + esp32c6.GPIO_ENABLE, esp32c6.GPIO + esp32c6.GPIO_OUT),
        (rp2040, rp2040.SIO + rp2040.SIO_GPIO_OE, rp2040.SIO + rp2040.SIO_GPIO_OUT),
    )
    for module, enable, out in cases:
        bit = 1 << module.HEADER["D10"]
        assert module.pin_states(_Words({}))["D10"] == "input", module.__name__
        assert module.pin_states(_Words({out: bit}))["D10"] == "input", (
            f"{module.__name__}: a driven pin whose output is not enabled has no level"
        )
        assert module.pin_states(_Words({enable: bit}))["D10"] == "low", module.__name__
        states = module.pin_states(_Words({enable: bit, out: bit}))
        assert states["D10"] == "high", module.__name__
        assert set(states) == set(module.HEADER), module.__name__
        assert {state for label, state in states.items() if label != "D10"} == {"input"}, (
            f"{module.__name__}: one bit moved more than one label"
        )


def test_a_running_c5_or_c6_dip_lists_the_smd_jtag_and_boot_pads_as_on_board_rows():
    """**A running DIP board shows five rows it has no pad for** (OH-200).

    `pad_view` lists every `pin_states` key that no pad carries as an
    on-board row, the way it lists `LED`. The C5's and C6's modules each
    serve a DIP and an SMD board file, and their `HEADER` now carries `MTMS`,
    `MTDI`, `MTDO`, `MTCK` and `BOOT`, which only the SMD file has pads for.
    So on the DIP those five are padless rows beside `LED`, each with its
    GPIO; on the SMD they are pads, and `LED` is the only padless row.

    That is true of the board, and OH-200's review ruled it so: Seeed's one
    board CAD per chip carries the five as underside test points, and the DIP
    and SMD footprints are two ways of mounting that one module.

    `pin_states` over a bus that reads zero stands in for a running board, as
    in the test above, so no core is built. Each GPIO is read from the
    module's own `HEADER`, which `tests/rules/test_import_pindefs.py` holds to
    Seeed's board file.
    """
    from webui.boards import esp32c5, esp32c6

    five = ("MTMS", "MTDI", "MTDO", "MTCK", "BOOT")
    for chip, module in (("C5", esp32c5), ("C6", esp32c6)):
        for footprint, padless in (("DIP", ("LED",) + five), ("SMD", ("LED",))):
            board = f"XIAO-ESP32-{chip}-{footprint}"
            assert api.description_for(board) is module, board
            view = api.pad_view(board, module, module.pin_states(_Words({})))
            rows = {pad["pin"]: (pad["group"], pad["chip_pin"])
                    for pad in view["pads"] if pad["x"] is None}
            assert rows == {label: ("on-board", f"GPIO{module.HEADER[label]}")
                            for label in padless}, (board, rows)


def test_a_view_says_whether_any_levels_were_read_at_all():
    """**OH-164: a board you picked told you its pins were in use elsewhere.**

    A pad with no state is one of three things, and only two of them are
    about the pin: no module models it, or a running program has taken it
    somewhere the direction register cannot show. The third is that nobody
    has loaded anything, and every pad of every modelled board is in it.

    The page could not tell the third from the second, so it said the second.
    Measured over `catalogue.board_names()`, counting pads that are `unknown`
    with a `chip_pin` -- which is exactly the input the panel's `unknownWords`
    reads -- for a board picked and not loaded.

    **It was twelve boards, OH-167 made it twenty-five and OH-170 made it all
    twenty-six.** A chip pin used to come only from the board module's
    `PIN_NAMES`, and fourteen boards have no module; it now falls back to the
    `chip_pin` the board file has carried since OH-26. The last exclusion was
    `XIAO-XIAO STM32C5-SMD`, whose file stated no chip pin for any of its 35
    pads because no board-support package covers it -- and that stayed true
    while Seeed's own schematic symbol library named two of them `SWDIO/PA13`
    and `SWCLK/PA14`. Reading those left no board in the catalogue whose file
    names no pin at all, so the exclusion is asserted empty rather than
    deleted: a board that loses its chip pins has to show up here.

    Before OH-167 the twelve were the number OH-160 made it: TWO modules
    answered before that -- `atmega328p` and `samd21`, over three board files,
    since the SAMD21 has a DIP and an SMD -- and it gave the ESP32-C3, C5, C6
    and RP2040 a generated `HEADER` between them.

    So the fact is stated. `read_levels` is false exactly when `pad_view` was
    given no levels to read, which is `live is None` and nothing else --
    `pin_view` always passes `pin_levels(...)`, so an empty dict is a program
    that drove nothing and not the absence of one. The page cannot work this
    out: `unknown == len(pads)` is equally true of a loaded sketch that has
    driven nothing, and re-deriving what the file could state is what OH-121
    paid for once already.

    **Four mutations die here, 2026-09-05, two of them only here**: the field
    always true, and the field read AFTER the coalesce that loses the
    distinction -- which is the mistake the code comment is placed to
    prevent. The other two are the field never reported and an empty poll
    counted as no program, which would make a sketch that drives nothing
    indistinguishable from one that was never loaded.
    """
    boards = catalogue.board_names()
    # 26 until OH-176 added the SparkFun Thing Plus ESP32-C6, whose file names
    # five chip pins from its arduino-esp32 variant; 27 until OH-177 added
    # the Adafruit QT Py ESP32-C3, whose file names 11; 28 until the
    # Adafruit Feather ESP32-C6, whose file names 15; 29 until OH-181 added
    # the Adafruit KB2040, whose file names 18; 30 until OH-188 added the
    # SparkFun Pro Micro ESP32-C3, whose file names 12; 31 until the SparkFun
    # Qwiic Pocket ESP32-C6, whose file names 8; 32 until OH-192 added the
    # PCBCUPID Glyph Mini RP2040, whose file names 20; 33 until OH-194 added
    # the PCBCUPID Glyph C3, whose file names 19; 34 until the PCBCUPID Glyph
    # C6, whose file names 20; 35 until the Olimex ESP32-C3-DevKit-Lipo,
    # whose file names 13; 36 until the SparkFun Thing Plus ESP32-C5, whose
    # file names 19.
    assert len(boards) == 37, boards
    # Every board, picked and not loaded: nothing was read.
    picked = {board: api.pad_view(board, api.description_for(board), None)
              for board in boards}
    assert all(view["read_levels"] is False
               for view in picked.values() if view.get("present")), [
        board for board, view in picked.items()
        if view.get("present") and view["read_levels"] is not False
    ]
    # And the boards that would otherwise have lied, named rather than counted
    # so that a board losing its chip pins shows up as a change here. All of
    # them, since OH-170 -- still written as the exclusion, because an empty
    # list is what says the last board with no chip pin at all has gone, and
    # a board losing its pins again would refill it.
    would_have_lied = sorted(
        board for board, view in picked.items()
        if view.get("present") and any(
            pad["state"] == "unknown" and pad["chip_pin"] is not None
            for pad in view["pads"])
    )
    silent = sorted(set(boards) - set(would_have_lied))
    assert silent == [], silent
    assert len(would_have_lied) == 37, would_have_lied
    assert "Arduino Uno" in would_have_lied
    assert "XIAO-MG24-SMD" in would_have_lied, (
        "the MG24 has no board module at all, so its 19 chip pins can only "
        "have come from its board file -- which is what OH-167 changed"
    )
    # A dict, even an empty one, is a program that was asked.
    asked = api.pad_view(UNO, api.description_for(UNO), {})
    assert asked["read_levels"] is True
    driven = api.pad_view(UNO, api.description_for(UNO), {"13": "high"})
    assert driven["read_levels"] is True


def test_a_running_board_still_reports_the_pins_its_timers_took():
    """**The clear-air case, and it is the one the third sentence must not
    eat.** OH-71: an Uno running a sketch has pads that are genuinely
    unanswerable, because a peripheral has taken the pin and the direction
    register carries no trace of it. Those keep "in use elsewhere"; only a
    board with no program at all gets the new words.

    So this asserts the opposite of the test above on the same board: levels
    WERE read, and pads that are still unknown with a chip pin behind them
    are the real thing rather than the absence of a program.
    """
    with built(UNO, UNO_DRIVE) as session:
        session.step(5000)
        view = api.pin_view(session.runtime, session.cpu, UNO)
    assert view["read_levels"] is True
    # The sketch drives pin 13, so at least one pad is answerable and the
    # view is not the empty one the picked case gives.
    assert view["unknown"] < len(view["pads"])
    assert any(pad["state"] == "high" for pad in view["pads"])


def test_a_running_board_whose_module_reads_no_pins_still_says_one_is_running():
    """**The invariant `read_levels` needs, kept where it can be kept.**

    `pad_view` decides on `live is None`, and `pin_view` is what guarantees
    that means "picked and not loaded". It did not: `pin_levels` answers
    `None` for a description with no `pin_states`, so a board that was RUNNING
    could arrive as `None` and report that nothing was running -- every
    modelled pad reading "no program running" while a program ran.

    Nothing has that shape today. Every module with `PIN_NAMES` also has
    `pin_states`, so this was a comment claiming a property of the type where
    only a property of today's board modules held. **OH-160 is precisely the
    shape that produces one without the other**: it generates `PIN_NAMES` from
    a `HEADER` and leaves `pin_states` hand-written, so the next module to get
    a generated header and no reader would have hit it.

    So `pin_view` coalesces, and this is the fixture that says so: a
    description with names and no reader, which is the combination no shipped
    module has and the generator can make. A stub rather than a real session,
    because the thing under test is one `or {}` and a real board would need a
    toolchain to prove less.

    **Three mutations die here, 2026-09-05, one of them only here**: the
    coalesce removed. The other two are the field never reported and an empty
    poll counted as no program.
    """
    named_but_silent = types.SimpleNamespace(
        __name__="stub_with_names_and_no_reader",
        PIN_NAMES={"D0": "PA02", "D1": "PA04"},
    )
    assert not hasattr(named_but_silent, "pin_states")
    # `board` because `pin_levels` asks whether it is a manifest row (OH-179).
    runtime = types.SimpleNamespace(board=XIAO, description=named_but_silent)
    assert api.pin_levels(runtime, None) is None, (
        "the stub answers levels after all, so it is not the case this test "
        "is for"
    )
    view = api.pin_view(runtime, None, XIAO)
    assert view["read_levels"] is True, (
        "a board with a session reported that no levels were read, so every "
        "modelled pad would say no program is running while one does"
    )
    # And the pads are all unknown, which is the honest half: there really
    # are no levels. The difference is what the page says about WHY.
    assert view["unknown"] == len(view["pads"])
    # The coupling that makes this unreachable today, stated so that a module
    # gaining a generated header and no reader is a change here rather than a
    # silent one.
    from webui.boards import catalogue

    with_names = sorted(
        module.__name__.rsplit(".", 1)[-1]
        for module in {
            api.description_for(board) for board in catalogue.board_names()
        }
        if module is not None and getattr(module, "PIN_NAMES", None)
    )
    assert with_names == ["atmega328p", "esp32c3", "esp32c5", "esp32c6",
                          "rp2040", "rp2350", "samd21"], with_names
    assert all(
        hasattr(api.description_for(board), "pin_states")
        for board in catalogue.board_names()
        if getattr(api.description_for(board), "PIN_NAMES", None)
    ), "a module publishes names it cannot read levels for"


def test_a_pad_names_its_chip_pin_on_a_board_with_no_module_at_all():
    """**OH-167: the answer was on disk and the page said "not modelled".**

    A chip pin had one source, the board module's `PIN_NAMES`. Fourteen of the
    twenty-six boards have no module -- `webui/boards/mg24.py` does not exist
    -- so every pad of those boards reported `chip_pin` null, which the panel
    renders as the sentence OH-164 defined to mean "nothing models this pin".

    The board files have carried the answer since OH-26, which read it out of
    six board-support packages and named the vendor file and revision for
    every value. `webui/pinmap.py` dropped it while parsing. Measured
    2026-09-05 across all 26 boards, comparing each board FILE against what
    `pad_view` reported:

        196   the file states a chip pin and the page showed none
        125   both state it and they agree
          0   they disagree, on any pad of any board

    The MG24 is the sharpest case because it has no module at all: 19 of its
    24 pads name a chip pin in the file, and every one of them read null.

    **Zero disagreements is what makes the fallback safe and it is also why
    this went unseen.** Nothing showed a WRONG pin; it showed a missing one,
    and a missing chip pin on a board with no module is indistinguishable from
    the honest answer until you open the JSON beside it.
    """
    # `D1` on each, spelled out rather than derived, so that a board file
    # re-imported from a different source shows up here as a change. The MG24
    # names by port and bit because Silicon Labs publishes no flat numbering,
    # which is why `chip_pin` is the string and `chip_index` the extra.
    #
    # The second witness was `XIAO-RP2350-DIP` until OH-157 gave the RP2350 a
    # module; the ESP32-S3 has none and numbers its GPIOs flat, as it did.
    for board, expect in (("XIAO-MG24-SMD", "PC1"), ("XIAO-ESP32-S3-DIP", "GPIO2")):
        layout = pinmap.load(board)
        assert layout is not None, board
        # The loader keeps it.
        stated = {pad.label: pad.chip_pin for pad in layout.pads}
        assert any(v is not None for v in stated.values()), board
        # And the view reports it, with no module in sight.
        assert api.description_for(board) is None, (
            f"{board} has a module now, so it is the wrong witness for this"
        )
        view = api.pad_view(board, None, None)
        shown = {pad["label"]: pad["chip_pin"] for pad in view["pads"]}
        assert shown == stated, board
        assert expect in shown.values(), (board, expect, sorted(
            v for v in shown.values() if v))
    # And the flat index, which is the half that is NOT always there. Silicon
    # Labs numbers the MG24 by port and bit and publishes nothing flat, so
    # every one of its pads carries a chip pin and no index; the ESP32-S3 has
    # both. A reader who treats `chip_index` as the answer gets nulls on four
    # families, which is why `chip_pin` is the string the page shows.
    mg24 = {pad.label: pad.chip_index for pad in pinmap.load("XIAO-MG24-SMD").pads}
    assert set(mg24.values()) == {None}, mg24
    s3 = {pad.label: pad.chip_index for pad in pinmap.load("XIAO-ESP32-S3-DIP").pads}
    assert s3["D1"] == 2, s3


def test_the_board_module_wins_where_it_names_a_pin_and_the_file_fills_the_rest():
    """**Two sources, a fixed order, and no merge.**

    `PIN_NAMES` wins wherever it has an entry because it is the same table
    `pin_states` reads levels through, so a label cannot carry one pin in the
    caption and another in the state. The file fills only the holes.

    Asserted against a stub whose table deliberately contradicts the file, so
    the direction is pinned rather than inferred from real data that agrees:
    across all 26 boards there are 125 agreements and no disagreement, which
    means live data can never show which source won.
    """
    board = "XIAO-MG24-SMD"
    layout = pinmap.load(board)
    stated = {pad.label: pad.chip_pin for pad in layout.pads}
    named = next(label for label, pin in stated.items() if pin is not None)

    module = types.SimpleNamespace(PIN_NAMES={named: "CONTRADICTION"})
    view = api.pad_view(board, module, None)
    shown = {pad["label"]: pad["chip_pin"] for pad in view["pads"]}
    assert shown[named] == "CONTRADICTION", (
        "the board module has to win where it names a pin, or a caption can "
        "disagree with the level read through the same table"
    )
    # And every other pad still gets the file's answer.
    others = {k: v for k, v in stated.items() if k != named and v is not None}
    assert others, "the fixture needs a pad the module does not name"
    for label, pin in others.items():
        assert shown[label] == pin, (label, pin, shown[label])


def test_the_uno_names_the_component_its_led_pin_lights_and_no_other_board_does():
    """**OH-169: the board's own LED never lit, however hard a sketch blinked.**

    The levels were always live -- a compiled blink toggles pin `13` -- and
    `setLevels` recoloured every pad on every poll. What nothing did was light
    the lamp printed on the board, because a user LED is a pin and not a pad,
    so it has a state and no coordinate and appeared only in the table.

    The component is named here rather than in the renderer, by the same
    `getattr` that finds `SUPPLY` and `PIN_NAMES`, so `webui/api.py` still does
    not know what an LED is.

    **An Uno carries four and three of them are not the user's**: `ON` is
    power, `RX` and `TX` are the serial bridge. Which one to light was traced
    through Arduino's own `UNO-TH_Rev3e.brd` in five hops, and two of the net
    names on the way -- `L13` and the test point `TP_13` -- state the pin
    number in the vendor's file. The trace is written out beside `LED_PARTS`.

    Every other board names none, and that is the honest answer rather than a
    gap: measured 2026-09-05, the SAMD21 and RP2040 have a user LED in their
    module and no LED component in their 3D model at all, the C5 and C6 have
    LED components nobody has traced to a pin, and `esp32c3.py` records that
    its board has no user LED whatsoever.
    """
    assert atmega328p.LED_PARTS == {"L": "13"}
    # The label it is keyed to has to be a pin the board actually reports, or
    # the renderer would look up a level that never arrives.
    assert set(atmega328p.LED_PARTS.values()) <= set(atmega328p.HEADER)
    # And it is the pin the module already calls the LED, not a second opinion.
    assert atmega328p.HEADER["13"] == ("B", atmega328p.LED_PIN)

    named = {board: api.pad_view(board, api.description_for(board), None)["led_parts"]
             for board in catalogue.board_names()}
    assert named["Arduino Uno"] == {"L": "13"}
    assert [b for b, v in named.items() if v] == ["Arduino Uno"], named


def test_the_named_led_component_is_one_the_shipped_board_model_actually_draws():
    """A component named here and absent from the mesh would light nothing and
    say nothing, which is survivable -- the renderer skips it. Naming one that
    is *misspelled* is the same silence for a worse reason, so the join is
    checked rather than assumed.

    The model is gitignored, so this skips rather than fails where nobody has
    run `tools/compose_board_3d.py`: a fresh checkout draws the extruded
    footprint, which has no components at all.
    """
    model = MODELS / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip(f"no {model}; run tools/compose_board_3d.py")
    solids = {solid["name"] for solid in board_solids(model)}
    assert solids, "the model states no component boxes at all"
    for component in atmega328p.LED_PARTS:
        assert component in solids, (
            f"{component!r} is named as an LED and the model does not draw it; "
            f"the four it does draw are "
            f"{sorted(s for s in solids if s in {'L', 'ON', 'RX', 'TX'})}"
        )


# --- a board from tools/board_manifest.py (OH-179) ----------------------------
#
# Its chip module's `HEADER` is keyed by a XIAO's labels. Before OH-179 a
# running Thing Plus listed the XIAO's D0..D10 and LED as its own on-board
# pins; its levels now come from its own file.

#: A chip's own blink fixture per row chip: any image that runs will do, since
#: what is asserted is which pads the view lists, not what the image drives.
CHIP_BLINKS = {"ESP32-C3": "riscv32/c3blink", "ESP32-C5": "riscv32/c5blink",
               "ESP32-C6": "riscv32/c6blink", "RP2040": "cortexm0/blink"}


def test_a_running_manifest_board_lists_its_own_pads_and_no_xiao_label():
    """The ticket's condition, on each row: the view lists the board file's
    pads in its order and nothing else -- the pilot's 28 -- each with its
    own file's `chip_pin`, so a label of the chip module's table is never
    captioned as that table's; a pad with a `chip_index` has a level and
    one without is unknown. The KB2040's `D0`..`D10` are keys of the RP2040
    module's table in fact, so the caption is what holds it; its pads, and
    the Glyph Mini's, read levels since OH-196."""
    pytest.importorskip("core.riscv32.abi")
    pytest.importorskip("core.cortexm0.abi")
    from tools import board_manifest

    tests = pathlib.Path(__file__).resolve().parents[1]
    counts = {}
    assert {row.chip for row in board_manifest.ROWS} <= set(CHIP_BLINKS), CHIP_BLINKS
    for row in board_manifest.ROWS:
        module = api.description_for(row.board)
        own = json.loads((pinmap.BOARDS_DIR / f"{row.board}.json").read_text(encoding="utf-8"))
        image = (tests / CHIP_BLINKS[row.chip] / "blink.bin").read_bytes()
        # A raw image carries no address: an ESP32's loads at its IROM, the
        # RP2040's past boot2, where the chip blink's `blink.ld` links it.
        base = module.IROM if row.chip != "RP2040" else module.FLASH + module.BOOT2_BYTES
        with api.load_firmware(row.board, image, base=base) as session:
            session.step(2000)
            view = api.pin_view(session.runtime, session.cpu, row.board)
        pins = [pad["pin"] for pad in view["pads"]]
        assert [(pad["pin"], pad["chip_pin"]) for pad in view["pads"]] == [
            (pad["label"], pad["chip_pin"]) for pad in own["pads"]], row.board
        if row.chip != "RP2040":
            assert not set(pins) & set(module.HEADER), (row.board, set(pins) & set(module.HEADER))
        assert [pad["state"] != "unknown" for pad in view["pads"]] == [
            pad["chip_index"] is not None for pad in own["pads"]], row.board
        counts[row.board] = len(pins)
    assert counts["SparkFun Thing Plus ESP32-C6"] == 28, counts
    assert {"Adafruit KB2040", "PCBCUPID Glyph Mini RP2040"} <= set(counts), counts


def test_a_manifest_boards_levels_agree_with_its_chip_module_on_every_gpio_both_name():
    """`api.row_levels` reads the registers the chip module's `pin_states`
    reads, so on every GPIO a row's pad and the module's table both name,
    for each register state, the two say the same thing. Every row's chip
    module names the words, the RP2040's since OH-196, whose rows read them
    only where `FUNCSEL` selects SIO, so it is selected on every GPIO here:
    `test_an_rp2040_rows_pad_reads_sio_only_where_its_funcsel_selects_sio`
    is the rest."""
    from tools import board_manifest

    shared = {}
    assert [row.board for row in board_manifest.ROWS
            if not hasattr(api.description_for(row.board), "GPIO")] == []
    for row in board_manifest.ROWS:
        module = api.description_for(row.board)
        runtime = api.Runtime(board=row.board, chip=row.chip,
                              core=api.catalogue.CHIPS[row.chip][1],
                              description=module, abi=None, machine=None)
        label_of = {gpio: label for label, gpio in module.HEADER.items()}
        own = [pad for pad in pinmap.load(row.board).pads if pad.chip_index in label_of]
        enable, out = module.GPIO + module.GPIO_ENABLE, module.GPIO + module.GPIO_OUT
        sio = ({module.gpio_ctrl(gpio): module.FUNCSEL_SIO
                for gpio in range(module.IO_BANK0_GPIOS)}
               if hasattr(module, "unrouted_level") else {})
        for words in ({}, {enable: 0xFFFFFFFF}, {enable: 0xFFFFFFFF, out: 0xFFFFFFFF},
                      {enable: 0xAAAAAAAA, out: 0x66666666}):
            ours = api.row_levels(runtime, _Words({**sio, **words}))
            theirs = module.pin_states(_Words(words))
            assert [ours[pad.label] for pad in own] == [
                theirs[label_of[pad.chip_index]] for pad in own], (row.board, words)
        shared[row.board] = len(own)
    assert all(shared.values()), f"a row shares no GPIO with its chip's table: {shared}"


def test_an_rp2040_rows_pad_reads_sio_only_where_its_funcsel_selects_sio():
    """OH-196: SIO drives a pad only where its `FUNCSEL` selects SIO, as
    silicon requires. At reset every `FUNCSEL` is NULL, and every pad reads
    `input` however SIO's words stand; SIO on one GPIO gives that pad alone
    SIO's level; any other function is a peripheral nothing here models,
    and its pad is `unknown`. The XIAO's `pin_states` does not ask, and
    reads SIO's level throughout: the gap this ticket leaves open."""
    from webui.boards import rp2040

    driven = {rp2040.SIO + rp2040.SIO_GPIO_OE: 0xFFFFFFFF,
              rp2040.SIO + rp2040.SIO_GPIO_OUT: 0xFFFFFFFF}
    at_reset = {rp2040.gpio_ctrl(gpio): rp2040.GPIO_CTRL_AT_RESET
                for gpio in range(rp2040.IO_BANK0_GPIOS)}
    for board in ("Adafruit KB2040", "PCBCUPID Glyph Mini RP2040"):
        runtime = api.Runtime(board=board, chip="RP2040", core="cortexm0",
                              description=rp2040, abi=None, machine=None)
        (first, *_) = [pad for pad in pinmap.load(board).pads if pad.chip_index is not None]
        assert set(api.row_levels(runtime, _Words({**driven, **at_reset})).values()) == {
            "input"}, board
        for funcsel, level in ((rp2040.FUNCSEL_SIO, "high"),
                               (rp2040.FUNCSEL_SIO + 1, "unknown")):
            words = {**driven, **at_reset, rp2040.gpio_ctrl(first.chip_index): funcsel}
            levels = api.row_levels(runtime, _Words(words))
            assert {label: state for label, state in levels.items() if state != "input"} == {
                first.label: level}, (board, funcsel)
    assert set(rp2040.pin_states(_Words({**driven, **at_reset})).values()) == {"high"}


def test_an_rp2040_rows_pad_past_gpio29_is_not_modelled_rather_than_an_error(monkeypatch):
    """IO_BANK0 has no `CTRL` past GPIO29, and no board here puts a pad there;
    a file that did gets that pad reported `unknown`, and every other pad
    its level, rather than the whole view failing on the one address."""
    import dataclasses

    from webui.boards import rp2040

    board = "PCBCUPID Glyph Mini RP2040"
    real = pinmap.load(board)
    (first, *_) = [pad for pad in real.pads if pad.chip_index is not None]
    far = dataclasses.replace(first, label="/GPIO-30", chip_index=30)
    monkeypatch.setattr(api.pinmap, "load",
                        lambda name: dataclasses.replace(real, pads=(*real.pads, far)))
    runtime = api.Runtime(board=board, chip="RP2040", core="cortexm0",
                          description=rp2040, abi=None, machine=None)
    sio = {rp2040.gpio_ctrl(gpio): rp2040.FUNCSEL_SIO for gpio in range(rp2040.IO_BANK0_GPIOS)}
    levels = api.row_levels(runtime, _Words({**sio, rp2040.SIO + rp2040.SIO_GPIO_OE: 0}))
    assert levels.pop("/GPIO-30") == "unknown", levels
    assert set(levels.values()) == {"input"}, levels


def test_a_row_whose_chip_module_names_no_gpio_words_reports_no_levels():
    """A chip module naming no `GPIO`, `GPIO_ENABLE` or `GPIO_OUT` gives a
    row no level at all, and its view lists its own pads, in its file's
    order, each with its own `chip_pin` and no state. `rp2040.py` was that
    module until OH-196 named them, so a stand-in without them plays it
    here, on the KB2040 (OH-181) and the Glyph Mini (OH-192)."""
    bare = types.SimpleNamespace(__name__="webui.boards.rp2040")
    for board in ("Adafruit KB2040", "PCBCUPID Glyph Mini RP2040"):
        runtime = api.Runtime(board=board, chip="RP2040", core="cortexm0",
                              description=bare, abi=None, machine=None)
        assert api.row_levels(runtime, _Words({})) is None
        own = json.loads((pinmap.BOARDS_DIR / f"{board}.json").read_text(encoding="utf-8"))
        view = api.pad_view(board, api.description_for(board),
                            api.row_levels(runtime, _Words({})))
        assert [(pad["pin"], pad["chip_pin"], pad["state"]) for pad in view["pads"]] == [
            (pad["label"], pad["chip_pin"], "unknown") for pad in own["pads"]], board


def test_a_manifest_pad_is_never_captioned_by_its_chip_modules_table():
    """A module table keyed by a row's own label: the pad keeps its own
    name and its own file's `chip_pin`, and the module's GPIO99 appears
    nowhere. The KB2040's `D0`..`D10` are keys of the RP2040 module's table
    in fact (OH-181)."""
    module = types.SimpleNamespace(__name__="webui.boards.fake", PIN_NAMES={"IO6": "GPIO99"})
    view = api.pad_view("SparkFun Thing Plus ESP32-C6", module, None)
    pad = next(pad for pad in view["pads"] if pad["label"] == "IO6/SDA")
    assert (pad["pin"], pad["chip_pin"]) == ("IO6/SDA", "GPIO6")
