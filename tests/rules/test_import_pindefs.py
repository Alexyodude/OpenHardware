# OpenHardware - tests for label -> chip pin extraction from board-support packages.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Every fixture below is **written out in this file**, in the format of the
# real file it stands for, for the reason `tests/rules/test_kicad.py` gives
# about the vendor CAD: `third_party/bsp/` is fetched and git-ignored, and a
# suite that skips silently when a download is missing is the vacuous green
# this repository exists to prevent.
#
# What each fixture reproduces, read on 2026-08-25 at the revisions below:
#
#   arduino-pico   33201a6  variants/seeed_xiao_rp2040/pins_arduino.h
#   arduino-esp32  2787dab  variants/XIAO_ESP32C3/pins_arduino.h
#   seeed-nrf52    667f05f  variants/Seeed_XIAO_nRF52840/variant.{h,cpp}
#   seeed-samd     2e6b174  variants/XIAO_m0/variant.{h,cpp}
#   silabs-arduino 6128e93  variants/xiao_mg24/{pins_arduino.h,arduino_variant.cpp}
#   zephyr         0a2e408  boards/seeed/xiao_rp2040/seeed_xiao_connector.dtsi
#
# `test_the_real_packages_resolve_a_board` is the one exception and skips
# loudly by name when the fetch has not been run.
#
# There is deliberately no @pytest.mark.parametrize anywhere here:
# tools/inventory.py counts `def test_*` with ast, and
# test_ast_count_matches_pytest_collection fails on the divergence. Cases are
# looped inside one test instead.

import pytest

from tools.import_pindefs import (
    BOARDS,
    BOARDS_DIR,
    BSP_DIR,
    PACKAGES,
    ChipPin,
    Claim,
    PindefError,
    Resolved,
    agree,
    alternatives,
    board_report,
    flat_gpio,
    microchip_port_pin,
    nordic_flat_pin,
    nordic_port_pin,
    pad_report,
    read_c_pin_constants,
    read_flat_pins,
    read_indexed_pins,
    read_nrf_pin_map,
    read_samd_pin_description,
    read_silabs_pin_names,
    read_zephyr_connector,
    resolve,
    select_labels,
    silabs_port_pin,
)

# --- the two spellings an Arduino core uses for a pin constant -------------

PICO_PINS_ARDUINO_H = """\
#pragma once

// LEDs
#define PIN_LED        (17u)
#define LED_BUILTIN    PIN_LED

// Digital pins
static const uint8_t D0 = (26u);
static const uint8_t D1 = (27u);
static const uint8_t D6 = (0u);
static const uint8_t D10 = (3u);

// Analog pins
static const uint8_t A0  = (26u);

// Wire
#define PIN_WIRE0_SDA  (6u)
#define SDA            PIN_WIRE0_SDA
"""

MG24_PINS_ARDUINO_H = """\
#ifndef PINS_ARDUINO_H
#define PINS_ARDUINO_H

// LEDs
#define LED_BUILTIN   (20u)
#define PIN_LED     (LED_BUILTIN)

// Digital pins
#define D0  (0u)
#define D1  (1u)
#define D18 (18u)

#define PIN_SERIAL_RX (D11) // PA9
#endif
"""

# `PIN_VBAT` is the trap the module docstring argues about: it is P0.31, the
# GPIO that senses the battery pad, and it is not the pad labelled VBAT.
NRF52_VARIANT_H = """\
#define PINS_COUNT              (33)
#define PIN_LED                 (LED_RED)
#define LED_RED                 (11)

// Digital PINs
static const uint8_t D0  = 0 ;
static const uint8_t D6  = 6 ;
static const uint8_t D10 = 10;

#define PIN_A0                  (0)
static const uint8_t A0  = PIN_A0;

#define PIN_NFC1                (30)
#define PIN_NFC2                (31)
#define PIN_VBAT                (32)
"""

NRF52_VARIANT_CPP = """\
#include "variant.h"

const uint32_t g_ADigitalPinMap[] =
{
    // D0 .. D10
     2, // D0  is P0.02 (A0)
     3, // D1  is P0.03 (A1)
    28, // D2  is P0.28 (A2)
    29, // D3  is P0.29 (A3)
     4, // D4  is P0.04 (A4,SDA)
     5, // D5  is P0.05 (A5,SCL)
    43, // D6  is P1.11 (TX)
    44, // D7  is P1.12 (RX)
    45, // D8  is P1.13 (SCK)
    46, // D9  is P1.14 (MISO)
    47, // D10 is P1.15 (MOSI)
    26, // D11 is P0.26 (LED RED)
     6, // D12 is P0.06 (LED BLUE)
    30, // D13 is P0.30 (LED GREEN)
    14, // D14 is P0.14 (READ_BAT)
    40, 27, 7, 11, 42, 32, 16, 13, 17, 21, 25, 20, 24, 22, 23,
     9, // D30 is P0.09 (NFC1)
    10, // D31 is P0.10 (NFC2)
    31, // D32 is P0.31 (VBAT)
};

void initVariant() { }
"""

MG24_ARDUINO_VARIANT_CPP = """\
PinName gPinNames[] = {
  PC0, // D0 - SPI SS - WU
  PC1, // D1
  PA9, // D11 - Serial Rx - 11
  PD2, // D18 - WU - 18
  PD5  // IMU enable - WU - 19
};

unsigned int getPinCount()
{
  return sizeof(gPinNames) / sizeof(gPinNames[0]);
}
"""

# Note the `} ;` with a space: that is how this file really closes, and it is
# why the array terminator is matched rather than searched for as two bytes.
SAMD_VARIANT_CPP = """\
const PinDescription g_APinDescription[]=
{
  // 0..10 - Digital & Analog pins
  { PORTA,  2, PIO_ANALOG, PIN_ATTR_ANALOG, ADC_Channel0, NOT_ON_PWM, NOT_ON_TIMER, EXTERNAL_INT_2 }, // ADC/AIN[0]
  { PORTA,  4, PIO_ANALOG, (PIN_ATTR_PWM|PIN_ATTR_TIMER), ADC_Channel4, PWM0_CH0, TCC0_CH0, EXTERNAL_INT_4 },
  { PORTB,  8, PIO_SERCOM_ALT, (PIN_ATTR_PWM|PIN_ATTR_TIMER), ADC_Channel2, PWM4_CH0, TC4_CH0, EXTERNAL_INT_8 } // TX

} ;

const void* g_apTCInstances[TCC_INST_NUM+TC_INST_NUM]={ TCC0, TCC1, TCC2 } ;
"""

SAMD_VARIANT_H = """\
#define PIN_A0               (0ul)
#define D0  (0u)
#define D1  (1u)
#define D2  (2u)
"""

RP2040_CONNECTOR_DTSI = """\
/ {
	xiao_d: connector {
		compatible = "seeed,xiao-gpio";
		#gpio-cells = <2>;
		gpio-map-mask = <0xffffffff 0xffffffc0>;
		gpio-map-pass-thru = <0 0x3f>;
		gpio-map = <0 0 &gpio0 26 0>,		/* D0 */
			   <1 0 &gpio0 27 0>,		/* D1 */
			   <6 0 &gpio0 0 0>,		/* D6 */
			   <10 0 &gpio0 3 0>;		/* D10 */
	};
};

xiao_i2c: &i2c1 {};
"""

S3_CONNECTOR_DTSI = """\
/ {
	xiao_d: connector {
		compatible = "seeed,xiao-gpio";
		gpio-map = <0 0 &gpio0 1 0>,	/* D0 */
			   <6 0 &gpio1 11 0>,	/* D6 */
			   <7 0 &gpio1 12 0>;	/* D7 */
	};
};
"""

SAMD_CONNECTOR_DTSI = """\
/ {
	xiao_d: connector {
		gpio-map = <0 0 &porta 2 0>,		/* D0 */
			   <6 0 &portb 8 0>;		/* D6 */
	};
};
"""

MG24_CONNECTOR_DTSI = """\
/ {
	xiao_d: connector {
		gpio-map = <0 0 &gpioc 0 0>, /* D0 */
			   <8 0 &gpioa 3 0>; /* D8 */
	};
};
"""

NRF54L15_CONNECTOR_DTSI = """\
/ {
	xiao_d: connector {
		gpio-map = <0 0 &gpio1 4 0>,	/* D0 */
			   <6 0 &gpio2 8 0>;	/* D6 */
	};
};
"""


# --- the readers -----------------------------------------------------------


def test_both_c_spellings_of_a_pin_constant_are_read():
    """`#define D0 (0u)` and `static const uint8_t D0 = (26u);` both count.

    A constant defined in terms of another -- `#define PIN_LED (LED_RED)` --
    is not resolved, and must not silently appear as some number.
    """
    pico = read_c_pin_constants(PICO_PINS_ARDUINO_H)
    assert pico["D0"] == 26
    assert pico["D6"] == 0
    assert pico["PIN_LED"] == 17
    assert "LED_BUILTIN" not in pico, "PIN_LED is not an integer literal"

    mg24 = read_c_pin_constants(MG24_PINS_ARDUINO_H)
    assert mg24["D0"] == 0
    assert mg24["D18"] == 18
    assert "PIN_LED" not in mg24, "(LED_BUILTIN) is not an integer literal"

    nrf = read_c_pin_constants(NRF52_VARIANT_H)
    assert nrf["D6"] == 6
    assert nrf["PIN_NFC1"] == 30
    assert "A0" not in nrf, "A0 = PIN_A0 is not an integer literal"


def test_only_d_labels_and_named_extras_are_selected():
    """A sweep would put PIN_VBAT -- an ADC input -- on a battery terminal.

    So `select_labels` keeps `D<n>` and nothing else unless a board's registry
    entry asks for it by name, and `PIN_NFC1` is reachable as `NFC1`.
    """
    constants = read_c_pin_constants(NRF52_VARIANT_H)
    assert set(select_labels(constants, ())) == {"D0", "D6", "D10"}

    with_extras = select_labels(constants, ("NFC1", "NFC2"))
    assert with_extras["NFC1"] == 30
    assert with_extras["NFC2"] == 31
    assert "VBAT" not in with_extras
    assert "SDA" not in select_labels(read_c_pin_constants(PICO_PINS_ARDUINO_H), ())


def test_a_flat_core_pin_number_is_the_gpio():
    """arduino-pico and arduino-esp32: `D6 = (0u)` means GPIO0, and stops there."""
    pins = read_flat_pins((PICO_PINS_ARDUINO_H,))
    assert pins["D6"] == ChipPin("GPIO0", 0)
    assert pins["D0"] == ChipPin("GPIO26", 26)
    assert set(pins) == {"D0", "D1", "D6", "D10"}


def test_an_indexed_core_pin_number_is_not_the_gpio():
    """The trap the whole module is shaped around.

    On the XIAO nRF52840 `D6 = 6`, and 6 is an index into `g_ADigitalPinMap`,
    where it reads 43 -- P1.11. Reading that file with the flat reader would
    answer GPIO6 and look entirely successful doing it.
    """
    indexed = read_indexed_pins(
        (NRF52_VARIANT_H, NRF52_VARIANT_CPP), read_table=read_nrf_pin_map, extras=("NFC1", "NFC2")
    )
    assert indexed["D6"] == ChipPin("P1.11", 43)
    assert indexed["D0"] == ChipPin("P0.02", 2)
    assert indexed["NFC1"] == ChipPin("P0.09", 9)
    assert indexed["NFC2"] == ChipPin("P0.10", 10)

    wrong = read_flat_pins((NRF52_VARIANT_H,))
    assert wrong["D6"] == ChipPin("GPIO6", 6), "the wrong reader is plausible, which is the point"
    assert wrong["D6"] != indexed["D6"]


def test_the_three_core_pin_tables_parse():
    """`g_ADigitalPinMap[]`, `gPinNames[]` and `g_APinDescription[]`.

    The SAMD array closes with `} ;`, a space between the brace and the
    semicolon, and the one after it -- `g_apTCInstances` -- must not be read
    as more pins.
    """
    nrf = read_nrf_pin_map(NRF52_VARIANT_CPP)
    assert nrf[0] == ChipPin("P0.02", 2)
    assert nrf[6] == ChipPin("P1.11", 43)
    assert len(nrf) == 33

    silabs = read_silabs_pin_names(MG24_ARDUINO_VARIANT_CPP)
    assert silabs[0] == ChipPin("PC0")
    assert silabs[3] == ChipPin("PD2")
    assert len(silabs) == 5

    samd = read_samd_pin_description(SAMD_VARIANT_CPP)
    assert samd == (ChipPin("PA02"), ChipPin("PA04"), ChipPin("PB08"))


def test_an_indexed_label_past_the_table_is_refused():
    """A short table would otherwise wrap or throw an unhelpful IndexError."""
    with pytest.raises(PindefError) as caught:
        read_indexed_pins(
            (NRF52_VARIANT_H, MG24_ARDUINO_VARIANT_CPP), read_table=read_silabs_pin_names
        )
    assert "D6 = 6" in str(caught.value)
    assert "5-entry" in str(caught.value)


def test_a_zephyr_connector_reads_under_each_chip_naming():
    """One file format, five ways a chip names the pin it lands on.

    The controller label alone does not say: `&gpio1 11` is GPIO43 on an
    ESP32-S3 and P1.11 on an nRF52840, so the naming is a property of the
    board, not of the file.
    """
    cases = (
        (RP2040_CONNECTOR_DTSI, flat_gpio, "D6", ChipPin("GPIO0", 0)),
        (S3_CONNECTOR_DTSI, flat_gpio, "D6", ChipPin("GPIO43", 43)),
        (SAMD_CONNECTOR_DTSI, microchip_port_pin, "D6", ChipPin("PB08")),
        (MG24_CONNECTOR_DTSI, silabs_port_pin, "D8", ChipPin("PA3")),
        (NRF54L15_CONNECTOR_DTSI, nordic_port_pin, "D6", ChipPin("P2.08")),
    )
    for text, naming, label, expected in cases:
        pins = read_zephyr_connector((text,), naming=naming)
        assert pins[label] == expected, f"{label} under {naming.__name__}"

    # gpio-map-mask and gpio-map-pass-thru sit above the nexus in the real
    # files and must not be read as entries.
    assert set(read_zephyr_connector((RP2040_CONNECTOR_DTSI,), naming=flat_gpio)) == {
        "D0",
        "D1",
        "D6",
        "D10",
    }


def test_the_same_zephyr_row_names_two_different_pins():
    """`&gpio1 11` is GPIO43 on an ESP32-S3 and P1.11 on an nRF52840.

    Both are the same 32-per-bank arithmetic; only the spelling differs, and
    on the nRF52840 that spelling is what the datasheet uses.
    """
    assert flat_gpio("gpio1", 11) == ChipPin("GPIO43", 43)
    assert nordic_flat_pin("gpio1", 11) == ChipPin("P1.11", 43)
    # nRF54L ports are not 32 wide, so no flat index is invented for them.
    assert nordic_port_pin("gpio2", 8) == ChipPin("P2.08", None)


def test_a_connector_that_contradicts_its_own_comment_is_refused():
    """Cell 0 is the D number by binding; the comment is a cross-check."""
    wrong = RP2040_CONNECTOR_DTSI.replace("<1 0 &gpio0 27 0>,		/* D1 */", "<1 0 &gpio0 27 0>,		/* D9 */")
    with pytest.raises(PindefError) as caught:
        read_zephyr_connector((wrong,), naming=flat_gpio)
    assert "'D9'" in str(caught.value)
    assert "cell 1" in str(caught.value)


def test_a_mismatched_controller_shape_is_refused():
    """`&gpioc` under a numbered-bank naming would otherwise be a silent zero."""
    for naming in (flat_gpio, nordic_flat_pin, nordic_port_pin):
        with pytest.raises(PindefError) as caught:
            naming("gpioc", 0)
        assert "'gpioc'" in str(caught.value)
    with pytest.raises(PindefError) as caught:
        microchip_port_pin("gpio0", 2)
    assert "'gpio0'" in str(caught.value)


def test_a_samd_row_that_is_not_a_port_is_refused():
    """Skipping a `NOT_A_PORT` row would shift every pin after it by one."""
    broken = SAMD_VARIANT_CPP.replace("{ PORTA,  4,", "{ NOT_A_PORT,  0,")
    with pytest.raises(PindefError) as caught:
        read_samd_pin_description(broken)
    assert "entry 1" in str(caught.value)
    assert "NOT_A_PORT" in str(caught.value)


# --- agreement, disagreement, and silence ----------------------------------

ZEPHYR_CITED = "zephyr boards/seeed/xiao_rp2040/seeed_xiao_connector.dtsi @ 0a2e408"
PICO_CITED = "arduino-pico variants/seeed_xiao_rp2040/pins_arduino.h @ 33201a6"


def test_two_packages_naming_the_same_pin_agree():
    claims = (Claim(ChipPin("GPIO0", 0), ZEPHYR_CITED), Claim(ChipPin("GPIO0", 0), PICO_CITED))
    assert agree(claims) == ChipPin("GPIO0", 0)


def test_an_unnumbered_claim_does_not_contradict_a_numbered_one():
    """Zephyr says P1.11 and stops; the Arduino core says P1.11 and calls it 43.

    That is one answer told twice at different resolutions, not a conflict, so
    the number survives.
    """
    claims = (Claim(ChipPin("P1.11"), ZEPHYR_CITED), Claim(ChipPin("P1.11", 43), PICO_CITED))
    assert agree(claims) == ChipPin("P1.11", 43)


def test_packages_that_disagree_produce_no_answer():
    """Two different names, and two different numbers under one name."""
    different_names = (
        Claim(ChipPin("GPIO5", 5), ZEPHYR_CITED),
        Claim(ChipPin("GPIO29", 29), PICO_CITED),
    )
    assert agree(different_names) is None

    same_name_different_number = (
        Claim(ChipPin("P1.11", 43), ZEPHYR_CITED),
        Claim(ChipPin("P1.11", 11), PICO_CITED),
    )
    assert agree(same_name_different_number) is None
    assert agree(()) is None


# --- what the report says --------------------------------------------------


def test_a_resolved_pad_names_the_file_that_resolved_it():
    """The `derivation` field names a footprint; a pad names its pin's source."""
    entry = Resolved(
        pad="7",
        label="D6",
        matched="D6",
        claims=(Claim(ChipPin("GPIO0", 0), ZEPHYR_CITED), Claim(ChipPin("GPIO0", 0), PICO_CITED)),
    )
    report = pad_report(entry)
    assert report["chip_pin"] == "GPIO0"
    assert report["index"] == 0
    assert report["sources"] == [ZEPHYR_CITED, PICO_CITED]
    assert "reason" not in report


def test_a_disagreement_is_recorded_rather_than_averaged():
    """Neither 5 nor 29 nor 17 comes out; both claims are kept with their files."""
    entry = Resolved(
        pad="4",
        label="D3",
        matched="D3",
        claims=(
            Claim(ChipPin("GPIO5", 5), ZEPHYR_CITED),
            Claim(ChipPin("GPIO29", 29), PICO_CITED),
        ),
    )
    report = pad_report(entry)
    assert report["chip_pin"] is None, "a disputed pad stays null"
    assert report["index"] is None
    assert "disagree" in report["reason"]
    assert report["disputed"] == [
        {"chip_pin": "GPIO29", "sources": [PICO_CITED]},
        {"chip_pin": "GPIO5", "sources": [ZEPHYR_CITED]},
    ]


def test_a_pad_no_package_covers_stays_null_and_says_so():
    """GND is not a GPIO. The existing null is correct; this keeps it."""
    report = pad_report(Resolved(pad="13", label="GND", matched=None, claims=()))
    assert report["chip_pin"] is None
    assert report["sources"] == []
    assert "no board-support package" in report["reason"]


def test_a_compound_label_resolves_on_whichever_half_is_published():
    """`D9/BOOT` and `D3/MTDI` are one pad silkscreened twice."""
    assert alternatives("D9/BOOT") == ("D9", "BOOT")
    assert alternatives("SWDIO/PA13") == ("SWDIO", "PA13")
    assert alternatives("3V3_OUT") == ("3V3_OUT",)


# --- the registry ----------------------------------------------------------


def test_every_board_file_is_either_registered_or_named():
    """A board dropped from the registry would vanish from the totals.

    The Arduino Uno is the only one outside it: its pins come from
    `webui/pinmap.py`, measured out of PICSimLab's own board.svg, and no
    board-support package is involved.
    """
    on_disk = {path.stem for path in BOARDS_DIR.glob("*.json")}
    assert on_disk, f"no board files under {BOARDS_DIR}"
    assert set(BOARDS) <= on_disk, f"registry names boards with no file: {set(BOARDS) - on_disk}"
    assert on_disk - set(BOARDS) == {"Arduino Uno"}


def test_every_registry_source_belongs_to_a_known_package():
    """A typo in a package name would surface as a missing directory instead."""
    for name, board in BOARDS.items():
        assert board.chip, f"{name} has no chip"
        for source in board.sources:
            assert source.package in PACKAGES, f"{name} cites unknown package {source.package}"
            assert source.paths, f"{name} cites {source.package} with no path"
            root = source.paths[0].split("/")[0]
            assert any(
                sparse.startswith(root) for sparse in PACKAGES[source.package].sparse
            ), f"{name} reads {source.paths[0]}, outside {source.package}'s sparse checkout"


def test_the_boards_with_no_source_are_deliberate():
    """One board has no package at all, and that is a finding, not an omission."""
    unsourced = {name for name, board in BOARDS.items() if not board.sources}
    assert unsourced == {"XIAO-XIAO STM32C5-SMD"}


# --- the real fetched tree -------------------------------------------------


def test_the_real_packages_resolve_a_board():
    """Skips by name when `python tools/import_pindefs.py --fetch` has not run.

    Pins the ticket's own example end to end: the same silkscreen `D6`, on two
    boards, reaching two different pins.
    """
    if not BSP_DIR.is_dir():
        pytest.skip(f"{BSP_DIR} absent; run python tools/import_pindefs.py --fetch")
    for package in ("zephyr", "arduino-pico", "arduino-esp32"):
        if not (BSP_DIR / package).is_dir():
            pytest.skip(f"{package} absent from {BSP_DIR}")

    def pin_of(board, label):
        pads = board_report(board)["pads"]
        return next(pad["chip_pin"] for pad in pads if pad["label"] == label)

    assert pin_of("XIAO-RP2040-DIP", "D6") == "GPIO0"
    assert pin_of("XIAO-ESP32-C3-DIP", "D6") == "GPIO21"

    report = board_report("XIAO-RP2040-DIP")
    assert report["resolved"] == 11, "D0..D10"
    assert report["unresolved"] == 3, "3V3_OUT, GND, VBUS are not GPIOs"
    assert report["disputed"] == 0
    for pad in report["pads"]:
        if pad["chip_pin"] is None:
            assert pad["sources"] == []
        else:
            assert pad["sources"], f"{pad['label']} resolved with no source named"
            assert all(" @ " in source for source in pad["sources"])


def test_the_real_tree_never_resolves_a_pad_from_nothing():
    """Across every registered board: a number implies a named file, always."""
    if not BSP_DIR.is_dir():
        pytest.skip(f"{BSP_DIR} absent; run python tools/import_pindefs.py --fetch")
    missing = sorted(
        package for package in PACKAGES if not (BSP_DIR / package).is_dir()
    )
    if missing:
        pytest.skip(f"{missing} absent from {BSP_DIR}")

    for name in sorted(BOARDS):
        report = board_report(name)
        for pad in report["pads"]:
            if pad["chip_pin"] is not None:
                assert pad["matched"], f"{name} {pad['label']} has a pin but matched nothing"
                assert pad["sources"], f"{name} {pad['label']} has a pin but no source"
            else:
                assert pad["index"] is None
                assert "reason" in pad, f"{name} {pad['label']} is null with no reason"


def test_a_board_the_registry_does_not_know_is_an_error():
    with pytest.raises(PindefError) as caught:
        resolve("Arduino Uno")
    assert "Arduino Uno" in str(caught.value)
