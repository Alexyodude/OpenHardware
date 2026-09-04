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

from webui import api, pinmap
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
