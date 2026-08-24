# OpenHardware - tests for the schematic connectivity importer.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib

import pytest

from tools import eagle
from tools.import_schematic import (
    DESIGNATORS,
    SchematicError,
    Status,
    choose_mcu,
    connectivity,
    gpio_of,
    indicators,
    is_rail,
    pdf_only,
    role_of,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDOR_SCH = (
    REPO
    / "third_party"
    / "sparkfun-thing-plus-esp32-c6"
    / "Hardware"
    / "Thing_Plus_ESP32_C6.sch"
)
#: The same board's own board-support definition, from a different
#: organisation's repository. This is the second source the done-criterion
#: needs: SparkFun drew the schematic, Espressif ships the variant header.
VARIANT = (
    REPO
    / "third_party"
    / "bsp"
    / "arduino-esp32"
    / "variants"
    / "sparkfun_esp32c6_thing_plus"
    / "pins_arduino.h"
)


def _report():
    if not VENDOR_SCH.is_file():
        pytest.skip(
            f"SKIPPED: {VENDOR_SCH.name} is not fetched. Run: "
            f"python tools/get_board_sources.py sparkfun-thing-plus-esp32-c6"
        )
    return connectivity(VENDOR_SCH, header="J1")


def _variant_constants():
    if not VARIANT.is_file():
        pytest.skip(f"SKIPPED: {VARIANT} is not fetched (OH-26 populates third_party/bsp)")
    from tools.import_pindefs import read_c_pin_constants

    return read_c_pin_constants(VARIANT.read_text(encoding="utf-8"))


def _sch(tmp_path, parts, nets, name="probe.sch"):
    """A minimal EAGLE schematic, for the cases the vendor board does not have.

    Written as text so a reviewer can see it is the format it imitates.
    `parts` is (name, library, deviceset); `nets` maps a net name to
    (part, pin) pairs.
    """
    part_xml = "".join(
        f'<part name="{n}" library="{lib}" deviceset="{ds}" device=""/>'
        for n, lib, ds in parts
    )
    net_xml = "".join(
        f'<net name="{net}"><segment>'
        + "".join(f'<pinref part="{p}" gate="G$1" pin="{pin}"/>' for p, pin in refs)
        + "</segment></net>"
        for net, refs in nets.items()
    )
    path = tmp_path / name
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eagle version="9.6.2"><drawing><schematic>'
        f"<parts>{part_xml}</parts>"
        f"<sheets><sheet><nets>{net_xml}</nets></sheet></sheets>"
        "</schematic></drawing></eagle>",
        encoding="utf-8",
    )
    return path


# --- the done-criterion -----------------------------------------------------


def test_the_led_gpio_edge_comes_out_of_the_vendors_schematic():
    """One edge, from the netlist, with every hop named.

    Not "an LED is on GPIO 23" but: the WS2812 called D5 has its data input on
    net IO23/STAT, and the module pin on that net is SDIO_D3/IO23.
    """
    led = next(row for row in _report()["indicators"] if row["part"] == "D5")
    assert led["gpio"] == 23
    assert led["mcu_pin"] == "SDIO_D3/IO23"
    assert led["net"] == "IO23/STAT"
    assert led["led_pin"] == "DI"
    assert led["deviceset"] == "WS2812"


def test_the_led_edge_agrees_with_the_boards_own_board_support():
    """Two sources that share no author, on one edge.

    SparkFun drew the schematic; Espressif ships the arduino-esp32 variant
    header. Neither was derived from the other, so agreeing is evidence rather
    than a tautology. This is OH-28's done-criterion.
    """
    schematic_says = next(
        row["gpio"] for row in _report()["indicators"] if row["part"] == "D5"
    )
    board_support_says = _variant_constants()["PIN_RGB_LED"]
    assert schematic_says == board_support_says == 23, (
        f"schematic says GPIO{schematic_says}, board support says "
        f"GPIO{board_support_says}"
    )


def test_led_builtin_is_not_a_pin_number_on_this_board():
    """The trap the netlist exists to catch, and the reason it is worse here.

    `tools/import_firmware.py` records that XIAO ESP32-C3 defines no
    `LED_BUILTIN` at all, so a fixture blink had to be rewritten. This board
    defines one, and it is not a pin:

        static const uint8_t LED_BUILTIN = SOC_GPIO_PIN_COUNT + PIN_RGB_LED;

    Past the end of the GPIO range on purpose — arduino-esp32 uses the offset
    to send `digitalWrite` to an addressable-LED driver instead of to a port.
    Firmware compiles either way. A simulator taking it for a pin index runs
    off the end of its port model, and the netlist is what says the real
    answer is 23.
    """
    constants = _variant_constants()
    assert "LED_BUILTIN" not in constants, (
        "the C parser resolved LED_BUILTIN to a number; it is an expression "
        "over SOC_GPIO_PIN_COUNT and must not come out as a pin"
    )
    assert constants["PIN_RGB_LED"] == 23
    text = VARIANT.read_text(encoding="utf-8")
    assert "SOC_GPIO_PIN_COUNT + PIN_RGB_LED" in text, (
        "the sentinel this test is about is no longer in the file"
    )


def test_the_wider_pin_table_agrees_with_the_netlist():
    """The same cross-check over every constant the variant states.

    Stronger than the single edge and it costs nothing, since both sides are
    already parsed. One row disagrees and is named rather than filtered: the
    variant sets `SS = 5` while the schematic puts the SD card's chip select
    on IO18. `SS` in Arduino is the *default* SPI select, which a board may
    point anywhere, so this is a difference of meaning rather than a mistake --
    but it is exactly the kind of thing that must not be averaged away.
    """
    report = _report()
    constants = _variant_constants()
    by_gpio = {row["gpio"]: row["pad"] for row in report["gpio_to_pad"]}

    expected = {
        "SDA": 6,
        "SCL": 7,
        "TX": 16,
        "RX": 17,
        "SCK": 19,
        "MOSI": 20,
        "MISO": 21,
        "A0": 0,
        "A1": 1,
        "A2": 2,
        "A3": 3,
        "A4": 4,
        "A5": 5,
    }
    for name, gpio in expected.items():
        assert constants[name] == gpio, f"the variant moved {name}"
        assert gpio in by_gpio, f"the netlist has no header pad on GPIO{gpio} for {name}"

    assert constants["SS"] == 5, "the variant changed its default SPI select"
    assert by_gpio.get(18) == "GPIO0", (
        "IO18 is where the schematic puts the SD card chip select; if that "
        "moved, the note in this test needs rewriting rather than deleting"
    )


# --- the silkscreen trap ----------------------------------------------------


def test_no_header_pad_naming_a_gpio_names_the_right_one():
    """Seven pads say GPIO0 to GPIO6. None is on the GPIO it names.

    They are Adafruit Feather positional labels, kept for pin compatibility.
    `tools/import_board.py` can only see them, because a footprint has pad
    names and no connectivity — so this is the concrete thing a netlist adds.
    """
    rows = _report()["gpio_to_pad"]
    claiming = [row for row in rows if row["pad_label_agrees"] is not None]
    assert len(claiming) == 7, f"expected 7 pads naming a GPIO, got {len(claiming)}"
    assert all(row["pad_label_agrees"] is False for row in claiming), (
        "a pad label agrees with its GPIO; that would be new"
    )
    by_pad = {row["pad"]: row["gpio"] for row in claiming}
    assert by_pad == {
        "GPIO0": 18,
        "GPIO1": 22,
        "GPIO2": 11,
        "GPIO3": 10,
        "GPIO4": 8,
        "GPIO5": 23,
        "GPIO6": 15,
    }


def test_a_pad_naming_a_function_claims_nothing():
    """`SDA` is not wrong about a number; it makes no claim about one.

    Three values, not two: collapsing "states no GPIO" into "disagrees" made
    an early run of this tool report 21 of 21 pads mislabelled, which is
    alarming and false.
    """
    rows = _report()["gpio_to_pad"]
    silent = [row for row in rows if row["pad_label_agrees"] is None]
    assert len(silent) == 14
    assert {"SDA", "SCL", "TX", "RX", "SCK"} <= {row["pad"] for row in silent}


def test_the_mcu_is_chosen_by_a_margin_the_report_states():
    """The header's own pins are named GPIOn too, so the rule needs its margin.

    23 against 7. A rule that took the header for the MCU would invert
    every row of gpio_to_pad, so the count and the runner-up are in the
    output rather than in a comment.
    """
    mcu = _report()["mcu"]
    assert mcu["part"] == "U1"
    assert mcu["gpio_pins"] == 23
    assert mcu["runner_up"] == "J1"
    assert mcu["runner_up_gpio_pins"] == 7


# --- the other three views --------------------------------------------------


def test_usb_lands_on_the_two_module_pins_that_name_it():
    nets = {row["net"]: row["pins"] for row in _report()["usb"]}
    assert nets["USB_N"] == ["J2.D-", "U1.USB_D-/IO12"]
    assert nets["USB_P"] == ["J2.D+", "U1.USB_D+/IO13"]


def test_the_crystal_is_the_thirty_two_kilohertz_pair():
    """And it doubles as A0/A1 on the header, which is worth seeing."""
    nets = {row["net"] for row in _report()["crystal"]}
    assert nets == {"IO0", "IO1"}


def test_the_regulator_output_feeds_the_three_volt_three_rail():
    rails = {row["net"] for row in _report()["regulator"]}
    assert "3.3V" in rails


def test_every_led_gets_a_row_including_the_ones_firmware_cannot_touch():
    """A report of only the drivable LEDs would look complete and not be."""
    rows = {row["part"]: row for row in _report()["indicators"]}
    assert set(rows) == {"D1", "D4", "D5"}
    assert rows["D1"]["gpio"] is None
    assert rows["D4"]["gpio"] is None
    assert rows["D5"]["gpio"] == 23


def test_a_status_led_names_its_driver_rather_than_a_gpio():
    """`no GPIO` and `driven by the charger` are different answers."""
    charge = next(row for row in _report()["indicators"] if row["part"] == "D4")
    assert charge["driver"] == "U3.STAT"
    assert charge["gpio"] is None
    assert "U3.STAT drives it" in charge["note"]


def test_the_derivation_says_what_it_read_and_measured_nothing():
    derivation = _report()["derivation"]
    assert "Nothing here was measured off an image." in derivation
    assert "EAGLE 9.6.2" in derivation
    assert "one hop on a shared net" in derivation


# --- PDF only is an answer --------------------------------------------------


def test_a_pdf_is_recorded_as_pdf_only_rather_than_refused(tmp_path):
    """The other half of this ticket, and it is not an error path.

    `tools/import_board.py` raises on a PDF because geometry cannot come out
    of one and geometry is what its caller asked for. Here the question is
    what the vendor publishes, and "a picture" answers it. An unknown that is
    written down is usable; one that is inferred is not.
    """
    paper = tmp_path / "RPI-PICO-R3-PUBLIC-SCHEMATIC.pdf"
    paper.write_bytes(b"%PDF-1.4\n")

    report = pdf_only(paper)
    assert report["status"] == Status.PDF_ONLY.label
    assert report["source"]["format"] == "pdf"
    assert "no parsing turns one into the other" in report["derivation"]


def test_pdf_only_reports_the_questions_it_cannot_answer(tmp_path):
    """Named, not omitted. An absent key reads as an oversight."""
    paper = tmp_path / "schematic.pdf"
    paper.write_bytes(b"%PDF-1.4\n")
    report = pdf_only(paper)

    assert set(report["unknown"]) == {
        "gpio_to_pad",
        "indicators",
        "usb",
        "crystal",
        "regulator",
    }
    for answered in ("gpio_to_pad", "indicators", "usb", "crystal", "regulator"):
        assert answered not in report, (
            f"{answered} is present on a pdf-only report, so an empty list from a "
            f"picture would be indistinguishable from a board with none"
        )


def test_the_two_statuses_never_share_a_column():
    """A netlist and a picture are different claims and are labelled so."""
    assert Status.NETLIST.label != Status.PDF_ONLY.label
    assert {s.label for s in Status} == {"netlist", "pdf-only"}
    for status in Status:
        assert status.gloss.strip()


# --- roles, spellings, rails ------------------------------------------------


def test_roles_come_from_reference_designators():
    assert role_of(eagle.Part("R12", "any", "1KOHM", "", None)) == "resistor"
    assert role_of(eagle.Part("U1", "any", "ESP32-C6-WROOM-1", "", None)) == "ic"
    assert role_of(eagle.Part("J1", "any", "THING_PLUS_LOGICAL", "", None)) == "connector"
    assert role_of(eagle.Part("Y1", "any", "CRYSTAL", "", None)) == "crystal"
    assert role_of(eagle.Part("SUPPLY13", "any", "3.3V", "", None)) == "supply"


def test_an_led_is_a_diode_the_file_itself_calls_an_led():
    """The one refinement, and it reads text the file states."""
    assert role_of(eagle.Part("D5", "SparkFun-LED", "WS2812", "", None)) == "led"
    assert role_of(eagle.Part("D3", "SparkFun-Diode", "SCHOTTKY", "", None)) == "diode"


def test_a_designator_outside_the_table_is_unknown_not_guessed():
    """This board has SHLD, MEAS, CHG and BOOT. None is inferred from position."""
    assert role_of(eagle.Part("SHLD", "any", "JUMPER", "", None)) == "unknown"
    assert role_of(eagle.Part("BOOT", "any", "SWITCH", "", None)) == "unknown"
    assert "SHLD" not in DESIGNATORS


def test_a_gpio_number_is_read_only_from_the_spellings_named():
    assert gpio_of("IO23") == 23
    assert gpio_of("SDIO_D3/IO23") == 23
    assert gpio_of("GPIO5") == 5
    assert gpio_of("MTDO/LP_SCL/IO7") == 7
    assert gpio_of("3V3") is None
    assert gpio_of("USB_D-/IO12") == 12
    assert gpio_of("PA13") is None, (
        "an STM32 spelling must read as no GPIO rather than be matched loosely"
    )


def test_a_rail_is_a_net_carrying_a_power_symbol(tmp_path):
    """Exact, and not a threshold on how many pins a net has."""
    roles = {"SUPPLY1": "supply", "U1": "ic", "D5": "led"}
    rail = eagle.Net("3.3V", (eagle.PinRef("SUPPLY1", "G$1", "3.3V"), eagle.PinRef("U1", "G$1", "3V3")))
    signal = eagle.Net("IO23/STAT", (eagle.PinRef("U1", "G$1", "IO23"), eagle.PinRef("D5", "G$1", "DI")))
    assert is_rail(rail, roles)
    assert not is_rail(signal, roles)


# --- the topology the vendor board does not have ----------------------------


def test_an_led_one_resistor_from_a_gpio_is_found(tmp_path):
    """The classic GPIO-resistor-LED-ground blink, which this board lacks.

    Every LED on the SparkFun board is either addressable, driven by the
    charger, or between rails. Without this fixture the resistor hop would be
    written and never executed, which is the same as not written.
    """
    path = _sch(
        tmp_path,
        [
            ("U1", "mcu", "MCU"),
            ("R1", "res", "330OHM"),
            ("D1", "SparkFun-LED", "LED-GREEN"),
            ("GND1", "power", "GND"),
        ],
        {
            "LED_DRIVE": [("U1", "IO7"), ("R1", "1")],
            "N$1": [("R1", "2"), ("D1", "A")],
            "GND": [("D1", "C"), ("GND1", "GND")],
        },
    )
    schematic = eagle.read_schematic(path)
    led = indicators(schematic, "U1")[0]

    assert led.part == "D1"
    assert led.gpio == 7
    assert led.mcu_pin == "IO7"
    assert led.series_resistors == ("R1",)
    assert "through R1" in led.note


def test_the_resistor_hop_is_one_hop_and_stops(tmp_path):
    """Two resistors deep is a different question, left unanswered.

    An unbounded search would eventually reach a GPIO through the ground net
    of every LED on the board and report all of them as drivable.
    """
    path = _sch(
        tmp_path,
        [
            ("U1", "mcu", "MCU"),
            ("R1", "res", "330OHM"),
            ("R2", "res", "330OHM"),
            ("D1", "SparkFun-LED", "LED-GREEN"),
        ],
        {
            "FAR": [("U1", "IO7"), ("R1", "1")],
            "MID": [("R1", "2"), ("R2", "1")],
            "NEAR": [("R2", "2"), ("D1", "A")],
        },
    )
    led = indicators(eagle.read_schematic(path), "U1")[0]
    assert led.gpio is None, "a two-resistor path was followed"
    assert "a longer path would not have been followed" in led.note


def test_a_rail_is_never_taken_for_a_drive_net(tmp_path):
    """An anode on 3.3V says nothing about what switches the LED."""
    path = _sch(
        tmp_path,
        [
            ("U1", "mcu", "MCU"),
            ("D1", "SparkFun-LED", "LED-RED"),
            ("SUPPLY1", "power", "3.3V"),
        ],
        {"3.3V": [("SUPPLY1", "3.3V"), ("D1", "A"), ("U1", "IO9")]},
    )
    led = indicators(eagle.read_schematic(path), "U1")[0]
    assert led.gpio is None, "a GPIO sharing a power rail was read as driving the LED"


def test_a_schematic_with_no_gpio_named_pins_says_so(tmp_path):
    """Silence would be indistinguishable from a board with nothing wired."""
    path = _sch(
        tmp_path,
        [("U1", "mcu", "MCU"), ("R1", "res", "1K")],
        {"N$1": [("U1", "PA13"), ("R1", "1")]},
    )
    with pytest.raises(SchematicError, match="no part has a pin named like a GPIO"):
        choose_mcu(eagle.read_schematic(path))


def test_a_board_file_is_refused_as_not_a_schematic(tmp_path):
    """`.sch` and `.brd` are the same dialect with different payloads."""
    path = tmp_path / "board.sch"
    path.write_text(
        '<eagle version="9.6.2"><drawing><board><elements/></board></drawing></eagle>',
        encoding="utf-8",
    )
    with pytest.raises(eagle.EagleError, match="holds no <schematic>"):
        eagle.read_schematic(path)


def test_a_schematic_with_parts_and_no_nets_is_refused(tmp_path):
    path = _sch(tmp_path, [("U1", "mcu", "MCU")], {})
    with pytest.raises(eagle.EagleError, match="not one net"):
        eagle.read_schematic(path)


def test_an_unknown_header_names_the_parts_that_exist(tmp_path):
    path = _sch(
        tmp_path,
        [("U1", "mcu", "MCU"), ("J9", "conn", "HEADER")],
        {"IO7": [("U1", "IO7"), ("J9", "1")]},
    )
    with pytest.raises(eagle.EagleError) as caught:
        connectivity(path, header="J1")
    assert "J9" in str(caught.value)
