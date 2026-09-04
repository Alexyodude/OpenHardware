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
# Four tests are the exception and skip loudly by name when the fetch has not
# been run: `test_the_real_packages_resolve_a_board`,
# `test_the_real_tree_never_resolves_a_pad_from_nothing`, and the two OH-160
# added -- `test_the_committed_modules_match_the_generator` and
# `test_the_committed_board_files_match_the_generator`.
#
# **Those last two are the only check that the committed `HEADER` blocks and
# board files are what the packages say**, so a run where they skip proves
# nothing about the generated artefacts. That is why OH-160 added a fetch step
# to `.github/workflows/rules.yml`: before it, they would have skipped in every
# CI run there has ever been. What still holds with no network is the pair
# below them -- every file carries the join, and every file agrees with its
# module -- which catches the two drifting apart but not both drifting
# together away from upstream.
#
# There is deliberately no @pytest.mark.parametrize anywhere here:
# tools/inventory.py counts `def test_*` with ast, and
# test_ast_count_matches_pytest_collection fails on the divergence. Cases are
# looped inside one test instead.

import json
import pathlib
import re

import pytest

from tools import import_pindefs as pindefs
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


def _needs_the_fetched_packages(*packages: str) -> None:
    """Skip, by name, where `--fetch` has not been run.

    Takes the packages the caller actually opens, defaulting to all of them:
    a test that reads three and skipped because a fourth was missing would
    name a package it never wanted.
    """
    wanted = packages or tuple(PACKAGES)
    if not BSP_DIR.is_dir():
        pytest.skip(f"{BSP_DIR} absent; run python tools/import_pindefs.py --fetch")
    missing = sorted(package for package in wanted if not (BSP_DIR / package).is_dir())
    if missing:
        pytest.skip(f"{missing} absent from {BSP_DIR}; run python tools/import_pindefs.py --fetch")


def test_the_real_packages_resolve_a_board():
    """Skips by name when `python tools/import_pindefs.py --fetch` has not run.

    Pins the ticket's own example end to end: the same silkscreen `D6`, on two
    boards, reaching two different pins.
    """
    _needs_the_fetched_packages("zephyr", "arduino-pico", "arduino-esp32")

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
    _needs_the_fetched_packages()

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


# --- the answer reaching the modules and the files (OH-160) -----------------
#
# One fake chip, `FAKE`, with two board files -- a DIP and an SMD, the way
# every XIAO ships -- under a fake `third_party/bsp` holding the RP2040
# fixtures above, so nothing here needs the fetch. `revision` is the one call
# that reaches for git, and it is replaced: a fixture checkout has no history
# and the revision is a string the block must carry, not a fact under test.


def _board_file(boards: pathlib.Path, name: str, pads: list[tuple[str, str]]) -> None:
    document = {
        "board": name,
        "px_per_mm": 8.0,
        "image": {"width": 200, "height": 160, "file": f"webui/boards/{name}.svg"},
        "derivation": "a footprint",
        "assumption": "Every `pin` is null. A pad with pin null draws and refuses a wire.",
        "source": {"vendor": "fixture"},
        "pads": [
            {"label": label, "pin": None, "x": 10.0 * n, "y": 20.0, "group": "header", "pad": pad}
            for n, (label, pad) in enumerate(pads, start=1)
        ],
    }
    (boards / f"{name}.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _fake_tree(tmp_path, monkeypatch, connector: str = RP2040_CONNECTOR_DTSI):
    """A bsp dir, a boards dir, and `BOARDS` swapped for two boards of one chip."""
    bsp = tmp_path / "bsp"
    (bsp / "zephyr" / "boards" / "seeed" / "fake").mkdir(parents=True)
    (bsp / "zephyr" / "boards" / "seeed" / "fake" / "seeed_xiao_connector.dtsi").write_text(
        connector, encoding="utf-8"
    )
    (bsp / "arduino-pico" / "variants" / "fake").mkdir(parents=True)
    (bsp / "arduino-pico" / "variants" / "fake" / "pins_arduino.h").write_text(
        PICO_PINS_ARDUINO_H, encoding="utf-8"
    )
    boards = tmp_path / "boards"
    boards.mkdir()
    _board_file(boards, "FAKE-DIP", [("D0", "1"), ("D6", "7"), ("GND", "12")])
    _board_file(
        boards, "FAKE-SMD",
        [("D0", "1"), ("D6/MTDI", "7"), ("D10", "11"), ("GND", "12"), ("GND", "12")],
    )
    sources = (
        pindefs.zephyr_connector("fake", flat_gpio),
        pindefs.arduino_flat("arduino-pico", "fake", extras=("LED",)),
    )
    monkeypatch.setattr(pindefs, "BOARDS", {
        "FAKE-DIP": pindefs.Board("FAKE", sources, on_board=("LED",)),
        "FAKE-SMD": pindefs.Board("FAKE", sources, on_board=("LED",)),
    })
    monkeypatch.setattr(pindefs, "revision", lambda checkout: "fa4e000")
    return bsp, boards


def test_the_board_led_is_read_from_whichever_spelling_the_core_uses():
    """arduino-pico numbers `PIN_LED`; arduino-esp32 numbers `LED_BUILTIN` and
    has no `PIN_LED`; both are the same thing, and a board that defines
    neither with a number is refused rather than given a pin."""
    assert select_labels({"PIN_LED": 17, "D0": 26}, ("LED",))["LED"] == 17
    assert select_labels({"LED_BUILTIN": 27, "D0": 1}, ("LED",))["LED"] == 27
    with pytest.raises(PindefError) as caught:
        select_labels({"D0": 1}, ("LED",))
    message = str(caught.value)
    # All three spellings, because a refusal that names two of the three it
    # tried sends a reader looking for a bug in the file it just read.
    assert "'LED'" in message
    assert "'PIN_LED'" in message and "'LED_BUILTIN'" in message


def test_an_on_board_pin_is_reported_beside_the_pads_and_counted_with_neither(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    report = board_report("FAKE-DIP", bsp, boards)
    assert report["resolved"] == 2 and report["unresolved"] == 1, "D0, D6 and GND"
    assert [pad["label"] for pad in report["pads"]] == ["D0", "D6", "GND"]
    (led,) = report["on_board"]
    assert led["pad"] is None
    assert (led["label"], led["chip_pin"], led["index"]) == ("LED", "GPIO17", 17)
    assert led["sources"] == ["arduino-pico variants/fake/pins_arduino.h @ fa4e000"]


def test_a_header_table_is_the_union_over_a_chips_files_keyed_by_the_packages_label(tmp_path, monkeypatch):
    """The DIP has no `D10` pad and the SMD spells `D6` as `D6/MTDI`; the
    table has both, under the names the packages define, and `D1` -- which
    the packages define and no pad carries -- is not in it."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    table = pindefs.header_table("FAKE", bsp, boards)
    assert table.chip == "FAKE"
    assert table.boards == ("FAKE-DIP", "FAKE-SMD")
    assert list(table.pins) == ["D0", "D6", "D10", "LED"], "D<n> ascending, then on-board"
    assert table.pins["D6"] == ChipPin("GPIO0", 0)
    assert table.pins["D10"] == ChipPin("GPIO3", 3)
    assert table.pins["LED"] == ChipPin("GPIO17", 17)
    assert "D1" not in table.pins
    assert table.on_board == ("LED",)
    assert table.citations == (
        "zephyr boards/seeed/fake/seeed_xiao_connector.dtsi @ fa4e000",
        "arduino-pico variants/fake/pins_arduino.h @ fa4e000",
    )


def test_a_label_two_of_a_chips_files_send_to_two_pins_is_refused(tmp_path, monkeypatch):
    """One chip, one table. Two files of one chip cannot disagree about a
    label without one of them being wrong, and the generator says which two."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    other = bsp / "zephyr" / "boards" / "seeed" / "other"
    other.mkdir()
    (other / "seeed_xiao_connector.dtsi").write_text(
        RP2040_CONNECTOR_DTSI.replace("<6 0 &gpio0 0 0>", "<6 0 &gpio0 5 0>"), encoding="utf-8"
    )
    monkeypatch.setattr(pindefs, "BOARDS", {
        "FAKE-DIP": pindefs.Board("FAKE", (pindefs.zephyr_connector("fake", flat_gpio),)),
        "FAKE-SMD": pindefs.Board("FAKE", (pindefs.zephyr_connector("other", flat_gpio),)),
    })
    with pytest.raises(PindefError) as caught:
        pindefs.header_table("FAKE", bsp, boards)
    message = str(caught.value)
    assert "D6" in message and "GPIO0" in message and "GPIO5" in message
    assert "FAKE-DIP" in message and "FAKE-SMD" in message


def test_a_chip_the_registry_does_not_know_has_no_table(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    with pytest.raises(PindefError) as caught:
        pindefs.header_table("NOPE", bsp, boards)
    assert "NOPE" in str(caught.value) and "FAKE" in str(caught.value)


def test_a_chip_with_no_flat_number_gets_no_block():
    """SAMD21's `PA02` is a name and not a number. `samd21.py` keys its own
    table as `(group, bit)`, and a generated `"D0": None` would parse and
    answer nothing -- so the generator refuses, naming the pin and the file."""
    table = pindefs.HeaderTable(
        "SAMD21", ("XIAO-SAMD21-DIP",), {"D0": ChipPin("PA02"), "D1": ChipPin("PA04")},
        ("seeed-samd variants/XIAO_m0/variant.h, variants/XIAO_m0/variant.cpp @ 2e6b174",),
        (),
    )
    with pytest.raises(PindefError) as caught:
        pindefs.render_header(table)
    message = str(caught.value)
    assert "PA02" in message and "samd21.py" in message and "D0" in message


def test_the_rendered_block_is_python_that_defines_the_table_and_names_its_sources(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    block = pindefs.render_header(pindefs.header_table("FAKE", bsp, boards))
    lines = block.split("\n")
    assert lines[0] == pindefs.HEADER_BEGIN and lines[-1] == pindefs.HEADER_END
    assert all(len(line) <= 100 for line in lines[1:-1]), [line for line in lines if len(line) > 100]
    assert "#:     zephyr boards/seeed/fake/seeed_xiao_connector.dtsi @ fa4e000" in lines
    assert "#:     arduino-pico variants/fake/pins_arduino.h @ fa4e000" in lines
    assert any("FAKE-DIP, FAKE-SMD" in line for line in lines), "the files it came from"
    assert any("`LED` has no pad" in line for line in lines), "the on-board row is explained"
    namespace: dict = {}
    exec(block, namespace)  # noqa: S102 -- the block is this repository's own output
    assert namespace["HEADER"] == {"D0": 26, "D6": 0, "D10": 3, "LED": 17}


def test_write_header_replaces_only_what_lies_between_the_markers(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    module = boards / "fake.py"
    before = '"""A fake board."""\n\nLED_PIN = 17\n\n'
    after = '\n\nPIN_NAMES = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}\n'
    module.write_text(
        before + pindefs.HEADER_BEGIN + "\n" + pindefs.HEADER_END + after, encoding="utf-8"
    )
    assert pindefs.write_header("FAKE", bsp, boards) is True
    text = module.read_text(encoding="utf-8")
    assert text.startswith(before) and text.endswith(after)
    assert '    "D6": 0,' in text and '    "LED": 17,' in text
    namespace: dict = {}
    exec(text, namespace)  # noqa: S102 -- see above
    assert namespace["PIN_NAMES"]["D6"] == "GPIO0"
    assert pindefs.write_header("FAKE", bsp, boards) is False, "a second write changes nothing"
    assert module.read_text(encoding="utf-8") == text


def test_a_module_without_both_markers_is_refused():
    begin, end = pindefs.HEADER_BEGIN, pindefs.HEADER_END
    for text, word in (
        ("HEADER = {}\n", "neither"),
        (f"{begin}\nHEADER = {{}}\n", "the first"),
        (f"HEADER = {{}}\n{end}\n", "the second"),
    ):
        with pytest.raises(PindefError) as caught:
            pindefs.splice_header(text, "BLOCK", "fake.py")
        assert word in str(caught.value), text
    with pytest.raises(PindefError) as caught:
        pindefs.splice_header(f"{end}\n{begin}\n", "BLOCK", "fake.py")
    assert "before" in str(caught.value)
    with pytest.raises(PindefError) as caught:
        pindefs.splice_header(f"{begin}\n{end}\n{begin}\n{end}\n", "BLOCK", "fake.py")
    assert "more than one" in str(caught.value)


def test_a_module_with_no_file_is_refused(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    with pytest.raises(PindefError) as caught:
        pindefs.write_header("FAKE", bsp, boards)
    assert "fake.py" in str(caught.value)


def test_the_chips_that_take_a_block_are_read_off_the_modules(tmp_path, monkeypatch):
    """Opting in is carrying the markers. A marked module no registered chip
    maps to is an error, not a module quietly never regenerated."""
    _, boards = _fake_tree(tmp_path, monkeypatch)
    assert pindefs.chips_with_header_markers(boards) == []
    (boards / "fake.py").write_text(
        f"{pindefs.HEADER_BEGIN}\n{pindefs.HEADER_END}\n", encoding="utf-8"
    )
    (boards / "samd21.py").write_text("HEADER = {}\n", encoding="utf-8")
    assert pindefs.chips_with_header_markers(boards) == ["FAKE"]
    (boards / "stray.py").write_text(
        f"{pindefs.HEADER_BEGIN}\n{pindefs.HEADER_END}\n", encoding="utf-8"
    )
    with pytest.raises(PindefError) as caught:
        pindefs.chips_with_header_markers(boards)
    assert "stray.py" in str(caught.value)


def test_write_board_fills_chip_pin_and_keeps_pin_null_with_a_reason(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    assert pindefs.write_board("FAKE-SMD", bsp, boards) is True
    document = json.loads((boards / "FAKE-SMD.json").read_text(encoding="utf-8"))
    keys = list(document)
    assert keys.index("pindefs") == keys.index("assumption") + 1
    assert document["derivation"] == "a footprint", "everything else is left alone"
    assert document["source"] == {"vendor": "fixture"}
    by_label = {pad["label"]: pad for pad in document["pads"]}
    assert by_label["D0"]["pin"] is None, "`pin` is the PICSimLab index and stays null"
    assert (by_label["D0"]["chip_pin"], by_label["D0"]["chip_index"]) == ("GPIO26", 26)
    assert (by_label["D6/MTDI"]["chip_pin"], by_label["D6/MTDI"]["chip_index"]) == ("GPIO0", 0)
    assert "why_null" not in by_label["D0"]
    assert by_label["GND"]["chip_pin"] is None and by_label["GND"]["chip_index"] is None
    assert by_label["GND"]["why_null"] == pindefs.NOT_PUBLISHED
    assert list(by_label["D0"]) == ["label", "pin", "chip_pin", "chip_index", "x", "y", "group", "pad"]
    assert [pad["pad"] for pad in document["pads"]] == ["1", "7", "11", "12", "12"], (
        "two pads numbered alike, as the nRF54LM20A SMD's GNDs are, and both kept"
    )
    pindefs_ = document["pindefs"]
    assert pindefs_["generated_by"] == "tools/import_pindefs.py"
    assert pindefs_["derivation"] == pindefs.BOARD_DERIVATION
    assert [package["revision"] for package in pindefs_["packages"]] == ["fa4e000", "fa4e000"]
    assert (pindefs_["resolved"], pindefs_["unresolved"], pindefs_["disputed"]) == (3, 2, 0)
    assert [pin["label"] for pin in pindefs_["on_board"]] == ["LED"]
    assert pindefs.write_board("FAKE-SMD", bsp, boards) is False, "a second write changes nothing"


def test_the_assumption_says_whether_a_module_reads_the_table(tmp_path, monkeypatch):
    """Two sentences for two truths: with `fake.py` beside the file the pin
    view answers for a pad; without it every pad is not modelled, and the
    number is recorded so the join is ready rather than made."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    without = pindefs.filled_board("FAKE-DIP", bsp, boards)["assumption"]
    (boards / "fake.py").write_text("HEADER = {}\n", encoding="utf-8")
    with_module = pindefs.filled_board("FAKE-DIP", bsp, boards)["assumption"]
    for text in (without, with_module):
        assert text.startswith("Every `pin` is null:")
        assert "webui/pinmap.py" in text and "`why_null`" in text
    assert "No board module describes FAKE" in without and "not made" in without
    assert "webui/boards/fake.py reads a level through the same table" in with_module
    assert "not modelled" in with_module


def test_a_board_file_with_no_assumption_field_is_refused(tmp_path, monkeypatch):
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    path = boards / "FAKE-DIP.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["assumption"]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PindefError) as caught:
        pindefs.filled_board("FAKE-DIP", bsp, boards)
    assert "assumption" in str(caught.value)


# --- the committed tree, with and without the fetch --------------------------


def test_the_fetch_skip_names_only_the_packages_its_caller_reads(tmp_path, monkeypatch):
    """The helper decides whether the checks below run at all, so a wrong
    skip here is a green run that proved nothing. It must pass when what the
    caller opens is present, and name what is missing when it is not."""
    import sys

    (tmp_path / "zephyr").mkdir()
    monkeypatch.setattr(sys.modules[__name__], "BSP_DIR", tmp_path)

    # A wrong skip must FAIL here, not skip: a test that skips when the
    # helper misbehaves reports the same green as one that ran, which is the
    # whole failure this helper can cause. (Measured: mutating the helper to
    # ignore its arguments turned this test from failing into skipping.)
    try:
        _needs_the_fetched_packages("zephyr")
    except pytest.skip.Exception as skipped:
        pytest.fail(f"skipped though zephyr is present: {skipped}")

    # `pytest.skip.Exception`, not `Exception`: a skip is a BaseException, so
    # `pytest.raises(Exception)` does not catch it and this test SKIPPED
    # itself instead of asserting -- which is the failure it exists to catch,
    # met while writing it.
    with pytest.raises(pytest.skip.Exception) as caught:
        _needs_the_fetched_packages("arduino-pico")
    assert "arduino-pico" in str(caught.value)
    assert "--fetch" in str(caught.value), "the message names the command that fixes it"

    with pytest.raises(pytest.skip.Exception) as caught:
        _needs_the_fetched_packages()
    message = str(caught.value)
    assert "zephyr" not in message, "it is there; naming it would send a reader wrong"
    assert "seeed-samd" in message and "arduino-esp32" in message


#: ` @ 0a2e408` in a citation, and the `revision` field of a board file's
#: `pindefs.packages`. Blanked before the two comparisons below.
_CITED_REVISION = re.compile(r" @ [0-9a-f]{4,40}\b")


def _pins_only(block: str) -> str:
    """A `HEADER` block with the revision in each citation blanked.

    **The comparison is about the pins, and the revision is not one.** CI
    clones each package `--depth 1` at today's default-branch HEAD, and the
    committed blocks cite the revision they were read at -- 2026-08-23 and
    -24 for these six. Comparing the two byte for byte therefore failed all
    four modules and all 25 board files on any commit to any of the six
    repositories, for any reason, while every pin still agreed (measured
    2026-09-04 by holding the files identical and changing only the string).
    That is not the failure these tests are for: it is loud, it is constant,
    and the remedy it points at -- re-run the writers -- would be a 29-file
    diff changing nothing but provenance.

    A citation stays true when upstream moves anyway. It says the table was
    read from that file at that revision, which it was, and this test says
    the same file still says the same thing today.
    """
    return _CITED_REVISION.sub(" @ <revision>", block)


def _document_pins_only(document: dict) -> dict:
    """A board file with every revision it records blanked. See above.

    Two places carry one, and missing the second is how this normalisation
    was wrong for a minute: `pindefs.packages[].revision`, and the ` @ ...`
    inside each `sources` citation of an `on_board` pin -- the board LEDs,
    which are the only pads that carry their sources into the file.
    """
    copy = json.loads(json.dumps(document))
    pindefs_ = copy.get("pindefs", {})
    for package in pindefs_.get("packages", []):
        package["revision"] = "<revision>"
    for pin in pindefs_.get("on_board", []):
        pin["sources"] = [_CITED_REVISION.sub(" @ <revision>", s) for s in pin["sources"]]
    return copy


def test_the_two_artefacts_cite_the_same_revisions_as_each_other():
    """Needs no fetch, and is what the normalisation above gives up.

    The blocks and the board files are written by two commands, and a run of
    one without the other is exactly how a generated pair drifts. They must
    agree about provenance: for every board whose chip carries a block, each
    package the file names at a revision is cited at that same revision in
    the module, and every revision is a short hash rather than a word.
    """
    for name in sorted(BOARDS):
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        recorded = {
            package["name"]: package["revision"]
            for package in document["pindefs"]["packages"]
        }
        for package, revision in recorded.items():
            assert re.fullmatch(r"[0-9a-f]{7,40}", revision), f"{name} {package}"
        module = pindefs.module_path(pindefs.BOARDS[name].chip)
        # Most chips have no module, and three that do carry no block: the
        # SAMD21's table is its own and the Uno is not in this registry.
        if not module.is_file():
            continue
        if pindefs.HEADER_BEGIN not in module.read_text(encoding="utf-8"):
            continue
        block = module.read_text(encoding="utf-8")
        block = block[block.find(pindefs.HEADER_BEGIN):block.find(pindefs.HEADER_END)]
        for package, revision in recorded.items():
            assert f"{package} " in block, f"{name} names {package}, {module.name} does not"
            assert f" @ {revision}" in block, (
                f"{name} records {package} at {revision} and {module.name} cites "
                f"another revision for it"
            )


def test_the_committed_modules_match_the_generator():
    """The four described boards with a flat GPIO number carry a block, and
    each block is what the generator emits today, pin for pin. A hand edit
    inside the markers, or a fetch that MOVED a pin, fails here by name; a
    fetch that moved only the revision does not, for the reason `_pins_only`
    gives at length."""
    _needs_the_fetched_packages()
    chips = pindefs.chips_with_header_markers()
    assert chips == ["ESP32-C3", "ESP32-C5", "ESP32-C6", "RP2040"]
    for chip in chips:
        text = pindefs.module_path(chip).read_text(encoding="utf-8")
        start = text.find(pindefs.HEADER_BEGIN)
        stop = text.find(pindefs.HEADER_END) + len(pindefs.HEADER_END)
        assert _pins_only(text[start:stop]) == _pins_only(
            pindefs.render_header(pindefs.header_table(chip))
        ), chip


def test_the_committed_board_files_match_the_generator():
    """Every registered file is what `--write-boards` would write, so the
    summary the generator prints and the counts the files carry are one
    computation -- and a file regenerated by `tools/import_board.py` without
    this step is named here rather than shipped with its pins gone."""
    _needs_the_fetched_packages()
    for name in sorted(BOARDS):
        on_disk = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        assert _document_pins_only(pindefs.filled_board(name)) == _document_pins_only(
            on_disk
        ), name


def test_every_registered_board_file_carries_the_join():
    """Needs no fetch: the shape every file has, and its own counts agreeing."""
    for name in sorted(BOARDS):
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        keys = list(document)
        assert keys.index("pindefs") == keys.index("assumption") + 1, name
        pads = document["pads"]
        for pad in pads:
            assert pad["pin"] is None, f"{name} {pad['label']}: `pin` is the PICSimLab index"
            assert "chip_pin" in pad and "chip_index" in pad, f"{name} {pad['label']}"
            assert (pad["chip_pin"] is None) == ("why_null" in pad), f"{name} {pad['label']}"
            assert (pad["chip_index"] is None) or (pad["chip_pin"] is not None), name
        counts = document["pindefs"]
        assert counts["resolved"] == sum(1 for pad in pads if pad["chip_pin"]), name
        assert counts["unresolved"] == sum(1 for pad in pads if not pad["chip_pin"]), name
        assert counts["disputed"] == 0, name


def test_the_board_file_and_the_module_agree_on_every_labelled_pad():
    """The ticket's own test, and it needs no fetch: for every pad on every
    board whose chip has a module, the file's `chip_pin` is what the module's
    `PIN_NAMES` says under the key `webui.api.header_key` joins the label to,
    and the flat index is the module's `HEADER` entry. Both directions: a pad
    the packages leave null is a label the module does not claim either."""
    from webui import api

    checked = set()
    for name in sorted(BOARDS):
        module = api.description_for(name)
        names = getattr(module, "PIN_NAMES", None)
        if names is None:
            continue
        header = module.HEADER
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        for pad in document["pads"]:
            key = api.header_key(pad["label"], names)
            if pad["chip_pin"] is None:
                assert key not in names, (
                    f"{name} {pad['label']}: the module claims {names.get(key)} "
                    f"and the packages nothing"
                )
                continue
            assert names[key] == pad["chip_pin"], f"{name} {pad['label']}"
            if isinstance(header[key], int):
                assert header[key] == pad["chip_index"], f"{name} {pad['label']}"
            checked.add(name)
    # Three C3 files, two each of C5, C6, RP2040 and SAMD21. A module added
    # for another chip joins this check and moves the number, on purpose.
    assert len(checked) == 11, sorted(checked)


# --- the board nothing publishes, and the sentence it must not borrow --------


def test_a_board_no_package_covers_says_so_rather_than_that_its_labels_are_missing(tmp_path, monkeypatch):
    """"No package covering this board defines this label" is vacuously true
    of all 35 pads of the XIAO STM32C5 and reads as though a package had been
    consulted. The fact OH-26 recorded is that the count of packages covering
    it is zero -- no Zephyr board, no Seeed core -- so the pads, the
    `assumption` and the `derivation` all say that instead of citing a
    `packages` list that is empty."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    covered = dict(pindefs.BOARDS)
    _board_file(boards, "FAKE-NOTHING", [("D0", "1"), ("GND", "12")])
    monkeypatch.setattr(pindefs, "BOARDS", covered | {
        "FAKE-NOTHING": pindefs.Board("NOTHING", ()),
    })
    report = board_report("FAKE-NOTHING", bsp, boards)
    assert report["resolved"] == 0 and report["packages"] == []
    assert {pad["reason"] for pad in report["pads"]} == {pindefs.NO_PACKAGE_AT_ALL}

    document = pindefs.filled_board("FAKE-NOTHING", bsp, boards)
    assert document["pindefs"]["derivation"] == pindefs.BOARD_DERIVATION_UNCOVERED
    assert "there are none to name, not because none was read" in document["pindefs"]["derivation"]
    assert {pad["why_null"] for pad in document["pads"]} == {pindefs.NO_PACKAGE_AT_ALL}
    assumption = document["assumption"]
    assert "no board-support package covers this board at all" in assumption
    assert "NOTHING XIAO" in assumption
    assert "the join is ready, not made" not in assumption, (
        "there is nothing here to join, so the undescribed board's sentence is wrong"
    )
    # The covered board in the same tree keeps the per-label reason, which is
    # the sentence this one must not borrow.
    other = pindefs.filled_board("FAKE-DIP", bsp, boards)
    gnd = next(pad for pad in other["pads"] if pad["label"] == "GND")
    assert gnd["why_null"] == pindefs.NOT_PUBLISHED


def test_the_block_states_the_agreement_rule_rather_than_claiming_every_package_agrees(tmp_path, monkeypatch):
    """This block said "every package naming the same pin for every row" until
    it was reviewed, and that is false of the `LED` row on three of the four
    chips: only arduino-esp32 defines the C5's and C6's, only arduino-pico the
    RP2040's, and no Zephyr connector names one at all. The rule `agree`
    enforces is the true sentence -- packages that BOTH define a row must
    match -- and a row one package alone defines is that package's."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    block = pindefs.render_header(pindefs.header_table("FAKE", bsp, boards))
    # The block wraps at 76 columns, so the sentence is read back unwrapped:
    # a test matching the wrapped form would pass or fail on where a line
    # happened to break.
    prose = " ".join(
        line.removeprefix("#:").strip()
        for line in block.splitlines()
        if line.startswith("#:")
    )
    assert "every package naming the same pin for every row" not in prose
    assert "A row is here only where every package that defines it names the same pin" in prose
    assert "a row only one package defines is that package's" in prose
    # And the fixture really is such a tree: the connector names D0, D1, D6 and
    # D10; only the Arduino variant names LED.
    zephyr = read_zephyr_connector((RP2040_CONNECTOR_DTSI,), naming=flat_gpio)
    assert "LED" not in zephyr
    assert read_flat_pins((PICO_PINS_ARDUINO_H,), extras=("LED",))["LED"] == ChipPin("GPIO17", 17)


def test_the_committed_stm32c5_file_is_the_one_no_package_covers():
    """Needs no fetch. One board in the registry has no source, and its file
    must say which of the two nulls it is; every other file must not."""
    borrowed = sorted(
        name for name in BOARDS
        if pindefs.NO_PACKAGE_AT_ALL in pindefs.board_path(name).read_text(encoding="utf-8")
    )
    assert borrowed == ["XIAO-XIAO STM32C5-SMD"]
    document = json.loads(pindefs.board_path(borrowed[0]).read_text(encoding="utf-8"))
    assert document["pindefs"]["packages"] == []
    assert len(document["pads"]) == 35, "OH-26: 0 of 35"
    assert {pad["why_null"] for pad in document["pads"]} == {pindefs.NO_PACKAGE_AT_ALL}
    assert "no board-support package covers this board at all" in document["assumption"]


# --- the pins their vendors publish no number for (OH-26's blocker) ----------


def test_a_pin_with_a_name_and_no_number_says_which_it_is_and_why(tmp_path, monkeypatch):
    """`{"chip_pin": "PA02", "chip_index": null}` with nothing said is the
    shape a reader cannot tell from a failed reading. OH-26 recorded the fact
    -- SAMD21, EFR32MG24, nRF54L15 and nRF54LM20A publish no flat GPIO
    numbering -- and three of those four chips have no module to write it in,
    so the board file is where it goes."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    (bsp / "zephyr" / "boards" / "seeed" / "ported").mkdir()
    (bsp / "zephyr" / "boards" / "seeed" / "ported" / "seeed_xiao_connector.dtsi").write_text(
        SAMD_CONNECTOR_DTSI, encoding="utf-8"
    )
    _board_file(boards, "FAKE-PORTED", [("D0", "1"), ("D6", "7"), ("GND", "12")])
    monkeypatch.setattr(pindefs, "BOARDS", dict(pindefs.BOARDS) | {
        "FAKE-PORTED": pindefs.Board(
            "PORTED", (pindefs.zephyr_connector("ported", microchip_port_pin),)
        ),
    })
    document = pindefs.filled_board("FAKE-PORTED", bsp, boards)
    by_label = {pad["label"]: pad for pad in document["pads"]}
    assert (by_label["D0"]["chip_pin"], by_label["D0"]["chip_index"]) == ("PA02", None)
    assert "why_null" not in by_label["D0"], "it resolved; it just has no number"

    assumption = document["assumption"]
    assert "2 pins on this board are named with NO flat number -- PA02, PB08" in assumption
    assert "and so on" not in assumption, "two pads is the whole list, not a sample"
    assert "no flat GPIO numbering is published for the PORTED at all" in assumption
    assert "a module for it would key its own table the way webui/boards/samd21.py does" in assumption

    # And a board whose pins ARE numbered says none of it.
    assert "NO flat number" not in pindefs.filled_board("FAKE-DIP", bsp, boards)["assumption"]


def test_the_chip_with_its_own_table_is_not_sent_to_read_its_own_file(tmp_path, monkeypatch):
    """The sentence points at `samd21.py` as the shape to copy, which is the
    wrong thing to tell a reader of the SAMD21's own board file: there the
    module exists and the sentence says what it does instead."""
    bsp, boards = _fake_tree(tmp_path, monkeypatch)
    (bsp / "zephyr" / "boards" / "seeed" / "ported").mkdir()
    (bsp / "zephyr" / "boards" / "seeed" / "ported" / "seeed_xiao_connector.dtsi").write_text(
        SAMD_CONNECTOR_DTSI, encoding="utf-8"
    )
    _board_file(boards, "FAKE-PORTED", [("D0", "1"), ("D6", "7")])
    monkeypatch.setattr(pindefs, "BOARDS", dict(pindefs.BOARDS) | {
        "FAKE-PORTED": pindefs.Board(
            "PORTED", (pindefs.zephyr_connector("ported", microchip_port_pin),)
        ),
    })
    (boards / "ported.py").write_text("HEADER = {}\n", encoding="utf-8")
    assumption = pindefs.filled_board("FAKE-PORTED", bsp, boards)["assumption"]
    assert "webui/boards/ported.py keys its own table by port and bit" in assumption
    assert "a module for it would key" not in assumption


def test_the_eight_committed_files_with_unnumbered_pins_are_the_eight_oh_26_named():
    """Needs no fetch. OH-26 measured 123 resolved pads on 8 boards with no
    flat integer; those 8 files, and only those, carry the sentence."""
    carrying = sorted(
        name for name in BOARDS
        if "NO flat number" in pindefs.board_path(name).read_text(encoding="utf-8")
    )
    assert carrying == [
        "XIAO-MG24-DIP", "XIAO-MG24-SMD",
        "XIAO-SAMD21-DIP", "XIAO-SAMD21-SMD",
        "XIAO-nRF54LM20A-DIP", "XIAO-nRF54LM20A-SMD",
        "XIAO-nRF54l15-DIP", "XIAO-nRF54l15-SMD",
    ]
    unnumbered = 0
    for name in carrying:
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        pads = [
            pad for pad in document["pads"]
            if pad["chip_pin"] is not None and pad["chip_index"] is None
        ]
        pins = {pad["chip_pin"] for pad in pads}
        # The sentence counts PINS. On these eight boards no pin is on two
        # pads, so the two numbers coincide -- asserted here rather than
        # assumed, because it is what makes OH-26's pad count comparable.
        assert len(pins) == len(pads), name
        unnumbered += len(pads)
        assert f"{len(pins)} pins on this board are named with NO flat number" in (
            document["assumption"]
        ), name
    assert unnumbered == 123, "OH-26's count, recomputed rather than restated"
    # Every other board's resolved pads carry a number, so the sentence would
    # be false on them.
    for name in set(BOARDS) - set(carrying):
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        assert all(
            pad["chip_index"] is not None
            for pad in document["pads"] if pad["chip_pin"] is not None
        ), name
