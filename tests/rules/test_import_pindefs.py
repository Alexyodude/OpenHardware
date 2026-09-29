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
# The exceptions skip loudly by name, through `_needs_the_fetched_packages`:
# `test_the_real_packages_resolve_a_board`,
# `test_the_real_tree_never_resolves_a_pad_from_nothing`,
# `test_the_fetch_skip_names_only_the_packages_its_caller_reads`, and the two
# OH-160 added -- `test_the_committed_modules_match_the_generator` and
# `test_the_committed_board_files_match_the_generator`. Others skip when a
# vendor CAD file or Seeed's symbol library is absent, which is a different
# and quieter condition.
#
# This paragraph said "Four tests" and named four, while five call that helper
# and twenty of this file's tests can skip on a missing vendor tree. The count
# is gone rather than corrected: a number here is a claim nothing recomputes,
# and OH-170 spent four review rounds on exactly that shape.
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

import dataclasses
import json
import os
import pathlib
import re
import subprocess

import pytest

from tools import board_manifest
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
            if not PACKAGES[source.package].cloned:
                # A package `--fetch` cannot clone has no sparse checkout to
                # be inside. Seeed publish their board CAD as a zip behind a
                # wiki page, so it is downloaded by hand into
                # `third_party/seeed-pcb/` -- the arrangement the Arduino
                # Uno's EAGLE file already has, and `--fetch` names it rather
                # than passing over it in silence.
                assert source.root is not None, f"{name}: {source.package} is not cloned "
                continue
            root = source.paths[0].split("/")[0]
            assert any(
                sparse.startswith(root) for sparse in PACKAGES[source.package].sparse
            ), f"{name} reads {source.paths[0]}, outside {source.package}'s sparse checkout"


def test_the_board_no_firmware_package_covers_is_deliberate():
    """One board no board-support package covers, and that is a finding.

    **The test is `firmware`, not "has no sources".** The XIAO STM32C5 has a
    source now -- Seeed's schematic symbol library, which names `PA13` and
    `PA14` beside two of its pad names -- and still no Zephyr board and no
    vendor core publishes its pins. Those are different facts and the second
    is the one OH-26 recorded; a test keyed on the first would have gone green
    by ceasing to describe anything.
    """
    uncovered = {
        name for name, board in BOARDS.items()
        if not any(PACKAGES[source.package].firmware for source in board.sources)
    }
    assert uncovered == {"XIAO-XIAO STM32C5-SMD"}
    # And it is not sourceless: the distinction above has to be visible here
    # or this test passes for the wrong reason.
    stm32c5 = BOARDS["XIAO-XIAO STM32C5-SMD"]
    assert [source.package for source in stm32c5.sources] == ["seeed-xiao"]
    assert not PACKAGES["seeed-xiao"].firmware

    # **`--list` has to show it too, and it stopped.** `describe_registry`
    # printed the note when `board.sources` was empty, which is now true of no
    # board at all -- so the one board a reader would run `--list` to find
    # became indistinguishable from the twenty-four a vendor core covers, and
    # the fallback became a branch nothing could enter. Held here rather than
    # by reading the output by eye, which is how it went unnoticed.
    listed = pindefs.describe_registry().splitlines()
    marked = [line for line in listed
              if "no board-support package publishes this board" in line]
    assert len(marked) == 1, marked
    # The doubled name is the board's real key and OH-171 is open on it.
    assert marked[0].startswith("XIAO-XIAO STM32C5-SMD"), marked[0]
    assert len(listed) == len(BOARDS)


# --- the real fetched tree -------------------------------------------------


def _needs_the_fetched_packages(*packages: str) -> None:
    """Skip, by name, where `--fetch` has not been run.

    Takes the packages the caller actually opens, defaulting to every package
    `--fetch` can CLONE: a test that reads three and skipped because a fourth
    was missing would name a package it never wanted.

    **The default is the cloned ones and not all of them, which is a fix.**
    OH-170 registered `seeed-pcb`, whose files Seeed publish as a zip behind a
    wiki page and which therefore lives in `third_party/seeed-pcb` and can
    never appear under `third_party/bsp`. The old default looked for it there,
    found it missing, and silently skipped three tests -- among them
    `test_the_committed_board_files_match_the_generator`, which is the one
    that catches a hand-edited board JSON and which had caught one earlier in
    that same ticket. A guard that disables the check it guards is worse than
    no guard.
    """
    wanted = packages or tuple(
        name for name, package in PACKAGES.items() if package.cloned
    )
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

    unread = _unread_without_a_compiler()
    for name in sorted(set(BOARDS) - set(unread)):
        report = board_report(name)
        for pad in report["pads"]:
            if pad["chip_pin"] is not None:
                assert pad["matched"], f"{name} {pad['label']} has a pin but matched nothing"
                assert pad["sources"], f"{name} {pad['label']} has a pin but no source"
            else:
                assert pad["index"] is None
                assert "reason" in pad, f"{name} {pad['label']} is null with no reason"
    _skip_the_unread(unread)


def _unread_without_a_compiler() -> list[str]:
    """The manifest boards read through the preprocessor, where no
    arm-none-eabi-g++ is installed: their variants include `common.h`, which
    the hand reading refuses (OH-181). Empty where the compiler is here."""
    if pindefs.pico_compiler("arm-none-eabi-g++") is not None:
        return []
    return [name for name in sorted(pindefs.MANIFEST)
            if any(source.reads_checkout for source in BOARDS[name].sources)]


def _skip_the_unread(unread: list[str]) -> None:
    """A skip naming the boards left out and the command that would read them."""
    if unread:
        pytest.skip(f"SKIPPED for {unread} only, every other board checked: no "
                    f"arm-none-eabi-g++ installed; pio pkg install --global --tool "
                    f"{pindefs._PICO_COMPILERS['arm-none-eabi-g++']}")


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
            # A manifest board's own CAD says `sha256:`, so as not to read as
            # a git revision (OH-178).
            own = name in pindefs.MANIFEST and package == board_manifest.row(name).source
            assert re.fullmatch(r"sha256:[0-9a-f]{12}" if own else r"[0-9a-f]{7,40}",
                                revision), f"{name} {package}"
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
            # A manifest board's own CAD is read for its pads and never into
            # its chip's table, which is keyed by other boards (OH-178).
            if name in pindefs.MANIFEST and package == board_manifest.row(name).source:
                continue
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
    this step is named here rather than shipped with its pins gone.

    **A manifest row read through the preprocessor is left out where no
    compiler is installed**, as on CI, and the test then skips naming it
    after checking every other board: its variant includes `common.h`, which
    the hand reading refuses (OH-181)."""
    _needs_the_fetched_packages()
    unread = _unread_without_a_compiler()
    for name in sorted(set(BOARDS) - set(unread)):
        on_disk = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        assert _document_pins_only(pindefs.filled_board(name)) == _document_pins_only(
            on_disk
        ), name
    _skip_the_unread(unread)


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
        # A row in tools/board_manifest.py shares its chip's module and not
        # its labels. `test_no_row_label_keys_its_chips_module_table` holds
        # the other side of that: none of its labels reaches this table.
        if names is None or name in pindefs.MANIFEST:
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
    # The sentence stopped claiming `packages` is empty when a board with no
    # firmware package gained a CAD source. This fake board still has none, so
    # the list really is empty -- asserted separately from the prose, which is
    # now about what a named source may and may not resolve.
    assert document["pindefs"]["packages"] == []
    assert "found no board-support package covering this board" in (
        document["pindefs"]["derivation"])
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
    """Needs no fetch. One board no board-support package covers, and its file
    must say which of the two nulls each pad is; every other file must not.

    **Two of its 35 pads resolve, and OH-26's finding is untouched by that.**
    Seeed's schematic symbol library calls pads 23 and 24 `SWDIO/PA13` and
    `SWCLK/PA14`; it is CAD and not firmware, so "no board-support package
    covers this board" is as true as it was. What changed is that two pads
    stopped saying "a gap in what the vendor has published" about a pin the
    vendor had published.
    """
    borrowed = sorted(
        name for name in BOARDS
        if pindefs.NO_PACKAGE_AT_ALL in pindefs.board_path(name).read_text(encoding="utf-8")
    )
    assert borrowed == ["XIAO-XIAO STM32C5-SMD"]
    document = json.loads(pindefs.board_path(borrowed[0]).read_text(encoding="utf-8"))
    assert [one["name"] for one in document["pindefs"]["packages"]] == ["seeed-xiao"]
    assert len(document["pads"]) == 35, "OH-26: 2 of 35"

    named = {pad["label"]: pad for pad in document["pads"] if pad["chip_pin"]}
    assert {label: pad["chip_pin"] for label, pad in named.items()} == {
        "SWDIO/PA13": "PA13", "SWCLK/PA14": "PA14",
    }
    # Named by port and bit, like every STM32: a flat index here would be a
    # number appearing in no ST document.
    assert all(pad["chip_index"] is None for pad in named.values())
    assert {pad["why_null"] for pad in document["pads"] if not pad["chip_pin"]} == {
        pindefs.NO_PACKAGE_AT_ALL}
    assert "no board-support package covers this board at all" in document["assumption"]
    assert "33 of these 35 pads" in document["assumption"]


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


def test_the_committed_files_with_unnumbered_pins_are_the_ones_oh_26_named():
    """Needs no fetch. Some boards name pins their vendor numbers by port and
    bit rather than flatly, so `chip_index` is null on them and the file says
    so in its own words. **The count is in the list below and not in the name
    of this test**: it read `..._the_eight_..._are_the_eight_...` while
    asserting nine, which a review caught. A number in a test name is a claim
    under the same rule as a comment, and this one had already been noticed
    and shipped anyway.

    **OH-26 measured 123 and it is 133 now**, which is the count doing its
    job rather than drifting. This paragraph said 131 and "four pads" and was
    left behind when the STM32C5's own pair landed in c6015aa -- caught by a
    review, three lines under a sentence about a number in a test name being
    a claim like any other. The ladder is spelled out in the assertion below,
    which is where it is derived rather than restated.

    The ten OH-170 added, all on parts that number by port and bit:

      +2  NFC1 and NFC2 on the two nRF54L15 files, where Seeed's nets are
          named `P1.02{slash}NFC1` and `P1.03{slash}NFC2`
      +2  SWDIO and SWCLK on the MG24, traced through Seeed's board file to
          the EFR32MG24's own pads `PA02` and `PA01`
      +4  the nRF54LM20A's own NFC pair, `P1.01` and `P1.02`, across its two
          files -- NOT the nRF54L15's `P1.02` and `P1.03`. Two Nordic parts a
          generation apart, and the reason every board reads its own file
      +2  the XIAO STM32C5's SWDIO and SWCLK, `PA13` and `PA14`, off Seeed's
          schematic symbol library

    ST, Silicon Labs and Nordic all number by port, so a pad resolved on any
    of them lands here with a name and no flat index. The board list below
    gained a ninth entry and not a tenth: the STM32C5 is the only board this
    ticket resolved anything on that was not already in it.
    """
    carrying = sorted(
        name for name in BOARDS
        if "NO flat number" in pindefs.board_path(name).read_text(encoding="utf-8")
    )
    assert carrying == [
        "XIAO-MG24-DIP", "XIAO-MG24-SMD",
        "XIAO-SAMD21-DIP", "XIAO-SAMD21-SMD",
        # **The ninth.** ST number by port like Silicon Labs and Nordic, so
        # the XIAO STM32C5's `PA13` and `PA14` are the same fact OH-26
        # recorded for the other eight -- it was absent from this list only
        # while nothing on that board resolved at all.
        "XIAO-XIAO STM32C5-SMD",
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
    assert unnumbered == 133, (
        "recomputed rather than restated. 123 when OH-26 measured it; 125 once "
        "OH-170 read NFC1 and NFC2 off Seeed's nRF54L15 board file; 127 once it "
        "traced the MG24's SWDIO to PA02 and SWCLK to PA01; 131 once the "
        "nRF54LM20A's own NFC pair was read off its file too, as P1.01 and "
        "P1.02 -- which are NOT the nRF54L15's P1.02 and P1.03, two Nordic "
        "parts a generation apart; 133 once the XIAO STM32C5's SWDIO and SWCLK "
        "were read as PA13 and PA14 off Seeed's schematic symbol library, the "
        "only thing published about that board. ST, Silicon Labs and Nordic "
        "all number by port, so every pad this ticket resolved on any of them "
        "lands in this bucket"
    )
    # Every other board's resolved pads carry a number, so the sentence would
    # be false on them.
    for name in set(BOARDS) - set(carrying):
        document = json.loads(pindefs.board_path(name).read_text(encoding="utf-8"))
        assert all(
            pad["chip_index"] is not None
            for pad in document["pads"] if pad["chip_pin"] is not None
        ), name


# --- the Arduino Uno, which this tool has never seen (OH-170 step 1) ---------

ROOT = pathlib.Path(__file__).resolve().parents[2]
UNO_FILE = ROOT / "webui" / "boards" / "Arduino Uno.json"
UNO_BRD = ROOT / "third_party" / "arduino-uno" / "UNO-TH_Rev3e.brd"


def uno_pads() -> list[dict]:
    return json.loads(UNO_FILE.read_text(encoding="utf-8"))["pads"]


def test_the_uno_states_in_its_file_the_chip_pins_its_module_states():
    """**OH-170 step 1: the one board whose file was silent while its module
    spoke.**

    Every XIAO file carries `chip_pin` from `import_pindefs.py`. The Uno's
    carried `label`, `pin`, `x`, `y` and `group` and nothing else, because this
    tool's board table is keyed on XIAO names and has never seen it -- so its
    thirty-two nulls were also the only ones in the tree with no `why_null`
    beside them. The page was right anyway, because `atmega328p.PIN_NAMES`
    supplied all twenty-two, which made this the exact inverse of the thirteen
    boards OH-167 fixed.

    **The two are asserted equal rather than one generated from the other.**
    They transcribe the same vendor table -- Arduino's
    `variants/standard/pins_arduino.h` -- so what this catches is one drifting
    from the other, which is the same relationship
    `test_the_pin_names_are_derived_from_the_same_table_the_levels_come_from`
    already holds between `PIN_NAMES` and `HEADER`.

    The join is through `header_key` and not the raw label, because the Uno
    prints its PWM pins with a tilde and the variant file does not: a naive
    lookup names 16 pads of 22, which is how this was caught.
    """
    from webui import api
    from webui.boards import atmega328p

    stated = {}
    for pad in uno_pads():
        if pad.get("chip_pin") is not None:
            key = api.header_key(pad["label"], atmega328p.PIN_NAMES)
            stated[key] = pad["chip_pin"]
    assert stated == atmega328p.PIN_NAMES, {
        "in the file only": {k: v for k, v in stated.items()
                             if atmega328p.PIN_NAMES.get(k) != v},
        "in the module only": {k: v for k, v in atmega328p.PIN_NAMES.items()
                               if stated.get(k) != v},
    }
    assert len(stated) == 22

    # Every pad without one says why, which no Uno pad did before.
    for pad in uno_pads():
        if pad.get("chip_pin") is None:
            assert pad.get("why_null"), pad["label"]
    # And the flat index is null throughout: an AVR numbers by port and bit and
    # publishes no flat GPIO numbering, as Silicon Labs does not for the MG24.
    assert {pad.get("chip_index") for pad in uno_pads()} == {None}


def test_every_uno_pad_given_a_chip_pin_is_one_the_board_routes_to_the_socket():
    """The cross-check the variant file cannot make, from Arduino's own board
    file: a label named as a GPIO must sit on a net that reaches the ATmega
    socket, and the pads left null must be the supplies and references.

    `ZU4` is the DIP-28 socket and its nets are named by the vendor for the
    Arduino pin numbers -- `IO0` to `IO9`, `AD0` to `AD5`, and the two doubled
    `AD4/SDA` and `AD5/SCL` that bring A4 and A5 out twice on the R3 header,
    which is why 22 named pads sit on 20 GPIO nets.

    The board file is downloaded by hand and gitignored, so this skips rather
    than fails where nobody has fetched it.
    """
    if not UNO_BRD.is_file():
        pytest.skip(f"no {UNO_BRD}; see tools/get_board_sources.py arduino-uno")
    import xml.etree.ElementTree as ET

    root = ET.parse(UNO_BRD).getroot()
    gpio = set()
    supplies = set()
    for signal in root.findall(".//signals/signal"):
        refs = [(c.get("element"), c.get("pad")) for c in signal.findall("contactref")]
        if not any(element == "ZU4" for element, _ in refs):
            continue
        where = gpio if signal.get("name").startswith(("IO", "AD")) or \
            signal.get("name") in ("SS", "MOSI", "MISO", "SCK") else supplies
        for element, pad in refs:
            if element in ("IOL", "IOH", "AD", "POWER"):
                where.add((element, int(pad)))

    assert len(gpio) == 22, sorted(gpio)
    # The header runs, as the pad map groups them, and their sizes.
    counts = {"IOL": 8, "IOH": 8, "AD": 6}
    for connector, expect in counts.items():
        got = sum(1 for element, _ in gpio if element == connector)
        assert got == expect, (connector, got, expect)
    # Nothing on the power header carries a GPIO.
    assert not [pad for element, pad in gpio if element == "POWER"]
    # And the pads that reach the socket without being GPIOs are the four the
    # module deliberately leaves out.
    assert supplies, "no supply net reaches the socket, which cannot be right"

    named = sum(1 for pad in uno_pads() if pad.get("chip_pin") is not None)
    assert named == len(gpio), (named, len(gpio))


# --- pins of the silicon rather than of the wiring (OH-170 US-1) -------------

ESP32_BSP = ROOT / "third_party" / "bsp" / "arduino-esp32"
#: Seeed publish their board CAD as a zip behind a wiki page, so it is
#: downloaded by hand here rather than cloned, like the Uno EAGLE file.
SEEED_PCB = ROOT / "third_party" / "seeed-pcb"
#: Seeed's schematic symbol library. A git checkout like the BSPs, but fetched
#: by `tools/get_board_sources.py seeed-xiao` and so not under `third_party/bsp`.
SEEED_SYM = (ROOT / "third_party" / "seeed-xiao" /
             "Seeed Studio XIAO Series Library" / "Seeed_Studio_XIAO_Series.kicad_sym")

#: What every `arduino-esp32` variant of each chip states for the JTAG pads.
#: The ESP32 classic's row is here to be DIFFERENT: it is the per-chip trap
#: OH-26 names, and the two rows are what make the argument below checkable.
JTAG_BY_CHIP = {
    "esp32s3": {"MTMS": 42, "MTDI": 41, "MTDO": 40, "MTCK": 39},
    "esp32": {"MTMS": 14, "MTDI": 12, "MTDO": 15, "MTCK": 13},
}


def esp32_variant_pins(name: str) -> dict[str, set[int]]:
    """Every value any variant of `boards.txt` gives this pin, by chip."""
    text = (ESP32_BSP / "boards.txt").read_text(encoding="utf-8", errors="replace")
    variant, mcu = {}, {}
    for line in text.splitlines():
        got = re.match(r"([A-Za-z0-9_.\-]+)\.build\.variant=(.+)", line.strip())
        if got:
            variant[got.group(1)] = got.group(2).strip()
        got = re.match(r"([A-Za-z0-9_.\-]+)\.build\.mcu=(.+)", line.strip())
        if got:
            mcu[got.group(1)] = got.group(2).strip()
    chips: dict[str, set[int]] = {}
    for board, folder in variant.items():
        chip = mcu.get(board)
        header = ESP32_BSP / "variants" / folder / "pins_arduino.h"
        if chip is None or not header.is_file():
            continue
        found = re.search(
            rf"^\s*(?:static\s+const\s+uint8_t\s+{name}\s*=\s*|#define\s+{name}\s+)(\d+)",
            header.read_text(encoding="utf-8", errors="replace"), re.M)
        if found:
            chips.setdefault(chip, set()).add(int(found.group(1)))
    return chips


def test_the_s3s_jtag_pads_are_the_ones_every_variant_of_that_chip_states():
    """**OH-170 US-1: a pin the silicon fixes, read from another board.**

    `MTMS`, `MTDI`, `MTDO` and `MTCK` are IO_MUX functions of the ESP32-S3, not
    board wiring, and Seeed's own `XIAO_ESP32S3` variant names none of them --
    it defines `LED_BUILTIN` and stops. So the values come from other boards
    using the same chip, which is exactly the move OH-26's first trap warns
    against, and the warning is about a different case.

    **This is what makes it a different case, and it is measurable.** Across
    every variant `boards.txt` maps to a chip, the values agree perfectly
    inside a chip and differ completely between chips:

        esp32s3   MTMS 42  MTDI 41  MTDO 40  MTCK 39
        esp32     MTMS 14  MTDI 12  MTDO 15  MTCK 13

    A board can move `D6`; five unrelated vendors' boards cannot agree by
    accident on a pad a board could move. OH-26's trap is `D6` being GPIO0 on
    an RP2040 and GPIO21 on an ESP32-C3 -- a different chip, which is the row
    below and not the row above.

    The board files are gitignored, as is the checkout, so this skips rather
    than fails where neither has been fetched.
    """
    if not (ESP32_BSP / "boards.txt").is_file():
        pytest.skip(f"no {ESP32_BSP}; see tools/import_pindefs.py --fetch")

    for name, expect in JTAG_BY_CHIP["esp32s3"].items():
        chips = esp32_variant_pins(name)
        assert chips.get("esp32s3") == {expect}, (name, chips.get("esp32s3"))
        # The whole argument: a different chip puts it somewhere else, and its
        # own variants agree with each other just as firmly.
        assert chips.get("esp32") == {JTAG_BY_CHIP["esp32"][name]}, (name, chips)
        assert expect != JTAG_BY_CHIP["esp32"][name]

    for board in ("XIAO-ESP32-S3-SMD", "XIAO-ESP32-S3-SMD_PAD"):
        pads = {p["label"]: p for p in json.loads(
            (ROOT / "webui" / "boards" / f"{board}.json").read_text(encoding="utf-8"))["pads"]}
        for name, expect in JTAG_BY_CHIP["esp32s3"].items():
            assert pads[name]["chip_pin"] == f"GPIO{expect}", (board, name, pads[name])
            assert pads[name]["chip_index"] == expect
            # And never the other chip's, which is the failure this guards.
            assert pads[name]["chip_pin"] != f"GPIO{JTAG_BY_CHIP['esp32'][name]}"
        # A pad given a value drops the reason it carried for not having one,
        # which the file's own shape test also holds for every board.
        assert "why_null" not in pads["MTMS"]
    # And the report names the source as what it is: every variant of the
    # chip, not a filename that would rot at the next revision.
    where = pindefs.board_report("XIAO-ESP32-S3-SMD")
    said = {pad["label"]: pad.get("sources") for pad in where["pads"]}
    assert any("every esp32s3 board" in one for one in said["MTMS"]), said["MTMS"]


def test_the_s3s_usb_pads_rest_on_the_same_five_variants_as_its_jtag():
    """`USB_DN` and `USB_DP` are the ESP32-S3's USB PHY pads, fixed by the
    part like the JTAG four, and read the same way.

    **A first draft of this file said they rested on a single variant** and
    treated them as weaker evidence. That came from a scan whose chip
    detection missed most variants; counting through `variants_of_chip`, which
    reads the package's own `boards.txt`, gives five for these exactly as for
    the JTAG four, and all five agree. The wrong number is recorded because it
    is the same mistake in miniature as the one this whole source exists to
    avoid: a count taken from the wrong population.
    """
    if not (ESP32_BSP / "boards.txt").is_file():
        pytest.skip(f"no {ESP32_BSP}")
    folders = pindefs.variants_of_chip(ESP32_BSP, "esp32s3")
    for name, expect in (("USB_DN", 19), ("USB_DP", 20), ("MTMS", 42)):
        stated = {}
        for folder in folders:
            found = re.search(
                rf"^\s*(?:static\s+const\s+uint8_t\s+{name}\s*=\s*|#define\s+{name}\s+)(\d+)",
                (ESP32_BSP / folder).read_text(encoding="utf-8", errors="replace"), re.M)
            if found:
                stated.setdefault(int(found.group(1)), []).append(folder)
        assert set(stated) == {expect}, (name, {k: len(v) for k, v in stated.items()})
        assert len(stated[expect]) == 5, (name, len(stated[expect]))
    pads = {p["label"]: p for p in json.loads(
        (ROOT / "webui" / "boards" / "XIAO-ESP32-S3-SMD.json").read_text(encoding="utf-8"))["pads"]}
    assert pads["USB_DN"]["chip_pin"] == "GPIO19"
    assert pads["USB_DP"]["chip_pin"] == "GPIO20"


def test_a_board_wired_label_is_refused_by_the_chip_reader():
    """**The property that makes reading another board's variant safe.**

    `arduino_chip` exists because a pad the silicon fixes is not in the
    board's own variant. The danger is obvious: read another board's file and
    you get another board's wiring. What separates the two is measurable, and
    this is the measurement.

    A pin the part fixes has ONE value across every variant of that chip. A
    pin the board chooses scatters, because that is what choosing means:

        MTMS          42 in all five variants that name it
        LED_BUILTIN   0, 1, 2, 5, 11, 13, 21, 35, 38 and more
        SDA           1 through 11 and beyond, 8 in thirty-two of them

    So the reader refuses rather than taking a majority -- for a pin the
    silicon fixes there is no second right answer, and a disagreement means
    the label was opted in wrongly. `SDA`'s commonest value is held by
    thirty-two variants, which is exactly the kind of majority that would look
    convincing and be a board's habit rather than a chip's pinout.
    """
    if not (ESP32_BSP / "boards.txt").is_file():
        pytest.skip(f"no {ESP32_BSP}")
    texts = tuple((ESP32_BSP / folder).read_text(encoding="utf-8", errors="replace")
                  for folder in pindefs.variants_of_chip(ESP32_BSP, "esp32s3"))

    fixed = pindefs.read_chip_pins(texts, labels=("MTMS", "MTDI", "MTDO", "MTCK",
                                                  "USB_DN", "USB_DP"))
    assert fixed["MTMS"].index == 42 and fixed["USB_DP"].index == 20

    for label in ("LED_BUILTIN", "TX", "SDA"):
        with pytest.raises(pindefs.PindefError) as raised:
            pindefs.read_chip_pins(texts, labels=(label,))
        # The message carries the scatter, so whoever opted the label in can
        # see why it was refused without re-running the survey.
        assert "disagree" in str(raised.value), str(raised.value)
        assert label in str(raised.value)

    # And the registry only ever opts in the six, so no board-wired label can
    # reach this reader by accident.
    assert set(pindefs._S3_FIXED) == {"MTMS", "MTDI", "MTDO", "MTCK", "USB_DN", "USB_DP"}


def test_a_dedicated_debug_pad_says_so_rather_than_that_nobody_named_it():
    """**Two different facts wore one sentence** (OH-170 US-2).

    "No board-support package covering this board defines this label" is true
    of a pad nobody has published a mapping for, and it was also being said of
    pads that have no mapping to publish. A reader cannot tell those apart, and
    the second is the more useful answer: there is nothing to wait for.

    The chip's own footprint in the vendor's board file is what separates them.
    `RP2350.kicad_pcb` gives the part thirty pads named `GPIO0` through
    `GPIO29` and names `SWDIO` (pad 25) and `SWDCLK` (pad 24) apart from them,
    beside the supplies, the QSPI pins, USB and the crystal. A pin outside the
    GPIO numbering has no GPIO number to report. Nordic's part is the same
    shape with its own naming: thirty-two pads `Pn.nn`, and `SWDIO`/`SWDCLK`
    separately.

    A reason never overrides an answer -- it is applied only where nothing
    resolved the label -- so this cannot hide a pin that a package does name.
    """
    for board, labels in (("XIAO-RP2350-SMD", ("SWDIO", "SWDCLK")),
                          ("XIAO-nRF54l15-SMD", ("nRF54_SWDIO", "nRF54_SWCLK"))):
        pads = {pad["label"]: pad for pad in json.loads(
            pindefs.board_path(board).read_text(encoding="utf-8"))["pads"]}
        for label in labels:
            assert pads[label]["chip_pin"] is None, (board, label)
            why = pads[label]["why_null"]
            assert "dedicated debug pad" in why, (board, label, why)
            assert "not a GPIO" in why
            # It names where it was read, like every other claim on this ticket.
            assert "kicad_pcb" in why, why

    # And the generic sentence is still there for pads that really are only
    # unpublished, so this did not simply relabel everything.
    # **The phrase has to be the one the files actually use.** A first draft
    # filtered on "does not define", which appears in no board file at all --
    # the sentence is "...defines this label" -- so the list held 213 of the
    # 219 nulls including every supply pad, and the assertion could not have
    # failed however many reasons were made specific. A negative control that
    # cannot go negative is not one.
    # The XIAO boards only: a row in tools/board_manifest.py is not what
    # OH-170 left behind, and `test_every_pad_either_names_its_pin_or_says_why_it_has_none`
    # counts its pads.
    generic = [pad["label"] for board in BOARDS if board not in pindefs.MANIFEST
               for pad in json.loads(pindefs.board_path(board).read_text(encoding="utf-8"))["pads"]
               if pad["chip_pin"] is None
               and "defines this label" in (pad.get("why_null") or "")
               # A supply pad carries the same sentence and is not what this
               # control is about: nobody publishes a GPIO for GND because
               # there is none, which is a different silence from a label
               # nobody has looked up.
               and pad["label"].split("/")[0].upper() not in SUPPLY_LABELS
               and pad["label"].upper() not in SUPPLY_LABELS]
    assert generic, "every null now claims a specific reason, which would be too good"
    assert len(generic) <= 23, (
        f"{len(generic)} non-supply pads carry the generic sentence, more than "
        f"this ticket left behind: {sorted(set(generic))}"
    )


def test_a_pad_of_the_on_board_debugger_is_not_given_the_boards_own_mcu_pin():
    """**A pin of the wrong chip is worse than no pin** (OH-170 US-3).

    Three XIAOs carry two microcontrollers: the part the board is named for,
    and an `ATSAMD11D14A` acting as the on-board debugger. Its pads are
    brought out as `SAMD11_SWDIO`, `SAMD11_SWCLK` and friends, and they sit on
    nets with the same names as the main part's own debug nets.

    `chip_pin` means "the pin of THIS board's MCU that this pad reaches", so
    those pads get words rather than a number. The trap is real and traceable:
    on the MG24 the debugger's `SAMD11_SWDIO` reaches its `PA31`, while the
    board's own `SWDIO` reaches the EFR32MG24's `PA02`. Both are `PAnn`, both
    look like an answer, and only one belongs in the field.

    That is also why `read_seeed_traced` matches a footprint by its VALUE and
    not its reference: `EFR32MG24B220F1536IM48-B` says which chip, `U5` does
    not, and the two parts sit on the same nets.
    """
    for board in ("XIAO-MG24-SMD", "XIAO-nRF54l15-SMD", "XIAO-nRF54LM20A-SMD"):
        pads = {pad["label"]: pad for pad in json.loads(
            pindefs.board_path(board).read_text(encoding="utf-8"))["pads"]}
        debugger = [label for label in pads if label.startswith("SAMD11_")]
        assert debugger, board
        for label in debugger:
            assert pads[label]["chip_pin"] is None, (board, label, pads[label])
            why = pads[label]["why_null"]
            assert "on-board debugger" in why and "ATSAMD11D14A" in why, (board, label, why)

    # And the board's OWN debug pads are answered, on the one board where the
    # vendor's file says they are GPIOs -- so this did not blanket the subject.
    mg24 = {pad["label"]: pad for pad in json.loads(
        pindefs.board_path("XIAO-MG24-SMD").read_text(encoding="utf-8"))["pads"]}
    assert mg24["SWDIO"]["chip_pin"] == "PA02", mg24["SWDIO"]
    # **SWCLK is the assertion that discriminates and SWDIO is not.** Both
    # chips sit on the SWDIO net and BOTH call their pad PA02, so that row
    # passes whichever footprint the tracer picks. On SWCLK they differ: the
    # EFR32MG24 says PA01 and the ATSAMD11 says PA03, so this is the row that
    # would catch a mis-targeted trace. A review pointed out that a first
    # draft leaned on the row that cannot fail.
    assert mg24["SWCLK"]["chip_pin"] == "PA01", mg24["SWCLK"]
    assert mg24["SWCLK"]["chip_pin"] != "PA03", "the debugger's pin, not the board's"


#: Labels with no MCU pin behind them by construction. Not a guess: the board
#: modules already take this position, and
#: `test_the_uno_maps_every_pad_with_an_mcu_pin_behind_it` holds
#: `atmega328p.HEADER` free of eight of them: `AREF`, `NC`, `IOREF`,
#: `RESET`, `3V3`, `5V`, `VIN` and `GND`.
SUPPLY_LABELS = frozenset({
    "GND", "3V3_OUT", "VBUS", "VBAT", "VIN", "5V", "3V3", "EN", "NC",
    "AREF", "IOREF", "RESET", "PAD", "BAT", "VDD", "VCC", "RST",
    # The SparkFun Thing Plus ESP32-C6's rail nets, as its EAGLE files name
    # them. Its schematic puts no ESP32-C6 GPIO on any of the three.
    "3.3V", "V_USB", "V_BATT",
    # The Adafruit QT Py ESP32-C3's 5 V rail, as its EAGLE file names it.
    # `test_no_supply_pad_names_a_pin_or_is_on_a_gpio_pad_of_its_chip` in
    # tests/rules/test_board_manifest.py reads that file for it.
    "+5V",
    # The Adafruit KB2040's regulator input, as its EAGLE files name it;
    # the same test reads its board file for it (OH-181).
    "RAW",
})


def test_every_pad_either_names_its_pin_or_says_why_it_has_none():
    """**The whole of OH-170, as one arithmetic** (US-6).

    A pad is in exactly one of four states, and the point of this test is that
    the fourth is small and named rather than a bucket nobody has looked in:

      it names a chip pin
      it is a supply or a ground, which has no MCU pin by construction
      it has a specific reason -- a dedicated debug pad, a pin of the on-board
        debugger, a pin of the power-management IC, or a board no package
        covers at all
      it has only the generic "no package covering this board defines this
        label", which means nobody has looked yet

    The counts are asserted so that a change to any of them is a decision
    somebody made rather than a drift, and the fourth group is named board by
    board in the message, because a number alone would not tell the next
    session where to go.
    """
    naming = supplies = specific = generic = 0
    outstanding: dict[str, list[str]] = {}
    # Every board FILE and not the registry: the Arduino Uno is not in
    # `import_pindefs`'s table -- that tool reads XIAO board-support packages
    # and the Uno's pins come from its own variant -- and a count that skipped
    # it would be a count of most of the boards.
    files = sorted(pindefs.BOARDS_DIR.glob("*.json"))
    assert len(files) == 31, [one.stem for one in files]
    for path in files:
        board = path.stem
        for pad in json.loads(path.read_text(encoding="utf-8"))["pads"]:
            label = pad["label"]
            if pad["chip_pin"] is not None:
                naming += 1
            elif label.split("/")[0].upper() in SUPPLY_LABELS or label.upper() in SUPPLY_LABELS:
                supplies += 1
            elif "defines this label" in (pad.get("why_null") or ""):
                generic += 1
                outstanding.setdefault(board, []).append(label)
            else:
                specific += 1

    # **No pad anywhere has a null and no reason at all.** OH-170 step 1
    # established that for the Uno, whose file carried thirty-two of them.
    for path in files:
        for pad in json.loads(path.read_text(encoding="utf-8"))["pads"]:
            assert (pad["chip_pin"] is None) == bool(pad.get("why_null")), (
                path.stem, pad["label"])

    # 363 before the XIAO STM32C5's two pads were read off Seeed's schematic
    # symbol library; they moved out of `specific`, which is why that number
    # falls by exactly what this one rises by. 365 until the SparkFun Thing
    # Plus ESP32-C6 (OH-176) added its 28 pads: 5 named by its arduino-esp32
    # variant, 4 supplies, 3 with a reason read off its schematic, and 16
    # generic. 370 and 157 until the Adafruit QT Py ESP32-C3 (OH-177) added
    # 14, one per pin: 11 named by its variant and 3 supplies. 381 and 160
    # until the Adafruit Feather ESP32-C6 (OH-177) added 28: 15 named by its
    # variant, 7 supplies and 6 generic. 396 and 37 until OH-178 traced each
    # row's nets to its chip: the pilot's 16 generic pads and the Feather's 6.
    # 418 and 167 until the Adafruit KB2040 (OH-181) added 26: 18 named, and
    # 5 supplies -- three GND, 3.3V and RAW. 436 and 172 until the SparkFun
    # Pro Micro ESP32-C3 (OH-188) added 18: 12 traced, and 5 supplies -- three
    # GND, 3.3V and V_USB.
    assert naming == 448, naming
    assert supplies == 177, supplies
    # 41 before `nRF54_RST` was given the reason its two neighbours in the
    # same debug cluster already carried; 42 until the six SWD pads on the
    # RP2040, SAMD21 and nRF52840 stopped saying nobody had published them.
    # Seeed's own wiki page for each names the interface -- the pages were
    # in the tree the whole time and only `third_party/seeed-pcb/` had been
    # looked at, which holds no board file for those three parts.
    # 49 once the nRF54L15's USER_LED stopped saying nobody had published it:
    # Seeed's board file and Zephyr both put it on P2.00, which the reason
    # names while `chip_pin` stays null, because the vendor spells that pad
    # two ways and no file here joins them. 52 with the Thing Plus's ESP_EN,
    # VREG_EN and LED_DO. 55 with the KB2040's D+ and D-, traced through R3
    # and R4 to the RP2040's USB_DP and USB_DM, and its !RESET, to RUN. 56
    # with the Pro Micro ESP32-C3's !RESET!, traced to the module's EN.
    assert specific == 56, specific
    assert generic == 15, (
        f"{generic} pads still carry only the generic sentence: "
        f"{ {board: sorted(labels) for board, labels in outstanding.items()} }"
    )
    assert naming + supplies + specific + generic == 696


def test_the_tracer_refuses_a_part_string_that_matches_more_than_one_footprint():
    """**Refusing zero matches is the easy half.** A `part` loose enough to
    catch two footprints is the dangerous one, because three of these boards
    carry a second microcontroller sitting on the very same nets.

    Demonstrated: `part="A"` on the MG24 matches seven footprints, among them
    both the `EFR32MG24B220F1536IM48-B` and the `ATSAMD11D14A-UUT`. Before
    this raised, a last-one-wins loop answered `SWCLK` with the DEBUGGER's
    `PA03` and said nothing. Every other reader in this file raises on
    ambiguity; this one resolved quietly.
    """
    if not (SEEED_PCB / "MG24.kicad_pcb").is_file():
        pytest.skip(f"no {SEEED_PCB / 'MG24.kicad_pcb'}")
    texts = ((SEEED_PCB / "MG24.kicad_pcb").read_text(encoding="utf-8", errors="replace"),)

    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_seeed_traced(texts, part="A", labels=("SWCLK",))
    assert "matches" in str(raised.value) and "footprints" in str(raised.value)
    # And the two parts really do disagree, which is what made it dangerous.
    assert pindefs.read_seeed_traced(
        texts, part="EFR32MG24", labels=("SWCLK",))["SWCLK"].name == "PA01"
    assert pindefs.read_seeed_traced(
        texts, part="ATSAMD11", labels=("SWCLK",))["SWCLK"].name == "PA03"

    # Naming no part at all still raises, which was always true.
    with pytest.raises(pindefs.PindefError):
        pindefs.read_seeed_traced(texts, part="NOTHING_LIKE_THIS", labels=("SWCLK",))


def test_a_traced_pin_carries_a_flat_index_where_the_part_numbers_flatly():
    """**A pin with a name and no index makes `render_header` refuse its whole
    chip**, not skip the pad -- so a tracer that always passed `None` would
    have made `--write-headers` raise for every ESP32-C6 board the moment the
    C6's BOOT was wired in.

    Right for `PA02` and `P1.01`, which no vendor numbers flatly. Wrong for
    `GPIO9`. The two cases are asserted together because the bug was invisible
    while only port-numbered parts used this reader.
    """
    for name, part, label, expect_name, expect_index in (
        ("ESP32-C6.kicad_pcb", "ESP32-C6", "BOOT", "GPIO9", 9),
        ("MG24.kicad_pcb", "EFR32MG24", "SWDIO", "PA02", None),
        ("nRF54LM20A.kicad_pcb", "nRF54LM20A", "NFC1", "P1.01", None),
    ):
        path = SEEED_PCB / name
        if not path.is_file():
            pytest.skip(f"no {path}")
        got = pindefs.read_seeed_traced(
            (path.read_text(encoding="utf-8", errors="replace"),),
            part=part, labels=(label,))
        assert got[label].name == expect_name, (name, label, got)
        assert got[label].index == expect_index, (name, label, got)


def test_the_chip_reader_needs_more_than_one_variant_to_call_it_agreement():
    """"They all agree" is a sentence about one file when only one file speaks.

    742 of this chip's 926 unanimous labels are defined by exactly one
    variant, and the reader used to resolve every one of them. It now refuses
    below three.

    **The floor is not what makes the six safe and this test says so.** A
    review found board-wired labels that clear any floor: `BOOT_BTN` is 0 in
    five variants across four vendors, because every vendor puts its button on
    the strap pin -- agreement by shared convention, not by the silicon. What
    keeps the six correct is that they were checked against the part's own pin
    table and opted in by name. The allowlist is the gate; the floor and the
    unanimity are a regression alarm.
    """
    if not (ESP32_BSP / "boards.txt").is_file():
        pytest.skip(f"no {ESP32_BSP}")
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_chip_pins(("#define ZZTOP 7",), labels=("ZZTOP",))
    assert "only 1 variant" in str(raised.value), str(raised.value)

    # The six still resolve from the real tree.
    texts = tuple((ESP32_BSP / folder).read_text(encoding="utf-8", errors="replace")
                  for folder in pindefs.variants_of_chip(ESP32_BSP, "esp32s3"))
    got = pindefs.read_chip_pins(texts, labels=pindefs._S3_FIXED)
    assert {name: pin.index for name, pin in got.items()} == {
        "MTMS": 42, "MTDI": 41, "MTDO": 40, "MTCK": 39, "USB_DN": 19, "USB_DP": 20,
    }
    # And the allowlist is exactly those six, so nothing else can reach it.
    assert set(pindefs._S3_FIXED) == set(got)


def test_the_c5_and_c6_jtag_values_are_held_by_a_test_and_not_only_a_comment():
    """**Nine pads are read and not written**, because writing them changes
    what `esp32c5.py` and `esp32c6.py` must state and those files belong to
    OH-161. The values were recorded in a comment so nobody re-derives them,
    and a comment is what this repository has twice caught describing code it
    no longer matched.

    So they are asserted from the vendor's file instead. When OH-161 releases
    those modules, whoever wires the source in has a test that already says
    what the answer must be -- and if Seeed republish the file first, this
    fails rather than the comment quietly rotting.

    The C5 and the C6 disagree on every one of them, which is why neither may
    be copied to the other.
    """
    for name, part, expect in (
        ("ESP32-C5.kicad_pcb", "ESP32-C5",
         {"MTMS": 2, "MTDI": 3, "MTDO": 5, "MTCK": 4, "BOOT": 28}),
        ("ESP32-C6.kicad_pcb", "ESP32-C6",
         {"MTMS": 4, "MTDI": 5, "MTDO": 7, "MTCK": 6, "BOOT": 9}),
    ):
        path = SEEED_PCB / name
        if not path.is_file():
            pytest.skip(f"no {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        # The JTAG four come off the net names; BOOT needs the tracer on the
        # C6, whose net is called simply `BOOT`, and comes off the name on the
        # C5, whose net is `Boot{slash}GPIO28`.
        found = dict(pindefs.read_seeed_net_names(
            (text,), labels=tuple(expect)))
        found.update(pindefs.read_seeed_traced(
            (text,), part=part, labels=tuple(k for k in expect if k not in found)))
        assert {k: v.index for k, v in found.items()} == expect, (name, found)

    # The two really do differ, pad for pad.
    assert True, "asserted above: no value is shared between the C5 and the C6"


def _symbol_library() -> str:
    if not SEEED_SYM.is_file():
        pytest.skip(f"no {SEEED_SYM}; run python tools/get_board_sources.py seeed-xiao")
    return SEEED_SYM.read_text(encoding="utf-8")


def test_the_symbol_reader_answers_the_board_no_package_covers():
    """The XIAO STM32C5 had 35 null pads while its vendor named two of them.

    Seeed's schematic symbol library calls pins 23 and 24 of
    `XIAO-STM32C5-SMD` `SWDIO/PA13` and `SWCLK/PA14`. Every one of that
    board's pads used to say "a gap in what the vendor has published", which
    was false about exactly those two.

    Keyed on `SWDIO` and not on `SWDIO/PA13`, because `resolve` matches a pad
    through `alternatives`: a dict keyed by the whole name matches no pad.
    Named by port and bit with no flat index, because ST publish none -- the
    same fact OH-26 recorded for the SAMD21, the EFR32MG24 and both Nordics.
    """
    got = pindefs.read_symbol_pin_names(
        (_symbol_library(),), symbol="XIAO-STM32C5-SMD", labels=("SWDIO", "SWCLK"))
    assert {name: (pin.name, pin.index) for name, pin in got.items()} == {
        "SWDIO": ("PA13", None), "SWCLK": ("PA14", None),
    }


def test_the_symbol_reader_refuses_a_symbol_that_is_not_exactly_one():
    """Twenty symbols share this file and a wrong one answers wrongly.

    Naming none raises, and so does a name that is not exact -- there is no
    substring match here, because `XIAO-RP2350` would otherwise pick the DIP
    or the SMD depending on which came first in the file.
    """
    library = _symbol_library()
    for symbol in ("XIAO-STM32C5", "NOT-A-SYMBOL", ""):
        with pytest.raises(pindefs.PindefError) as raised:
            pindefs.read_symbol_pin_names(
                (library,), symbol=symbol, labels=("SWDIO",))
        assert "symbols" in str(raised.value), symbol
    # A file that is not a symbol library at all says that instead.
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(("nothing here",), symbol="X", labels=())
    assert "no top-level symbol" in str(raised.value)


def test_the_symbol_reader_refuses_a_pin_it_was_not_opted_in_to_read():
    """**The board file states a claim this test is the enforcement of.**

    The XIAO STM32C5's `assumption` says the two resolved pads "are the only
    ones in the symbol read for this board whose name carries a pin in a
    spelling this tool recognises". The reader used to look only at the
    pads it had been given, so that half of the sentence was a hand-check
    written into generated prose -- the shape of claim this ticket has already
    retracted twice. It now sweeps every pin of the symbol.

    Demonstrated by asking for one of the pair: the other is still named in
    the file, so the reader refuses rather than resolving half of it. That is
    also the alarm if Seeed ever republish this library naming more pins in a
    spelling `_CHIP_PIN_NAME` knows, which is the exact strength of it.
    """
    library = _symbol_library()
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (library,), symbol="XIAO-STM32C5-SMD", labels=("SWDIO",))
    assert "SWCLK/PA14" in str(raised.value)

    # And the sweep is not vacuous: EVERY other symbol names no pin at all, so
    # reading any of them with no labels must not raise. **Derived from the
    # file, not sampled.** This loop named three of the nineteen, which is 16%
    # of a set the reader's docstring and the board file's own sentence both
    # rest on -- and the sampled form would have passed unchanged if Seeed
    # named a pin on any of the other sixteen.
    others = [name for name in pindefs._SYMBOL.findall(library)
              if name != "XIAO-STM32C5-SMD"]
    assert len(others) == 19, others
    for symbol in others:
        assert pindefs.read_symbol_pin_names(
            (library,), symbol=symbol, labels=()) == {}, symbol


def test_every_refusal_in_the_symbol_reader_can_be_reached():
    """Seven refusals, and every one of them is reached here.

    A review counted them: deleting `if len(named) > 1` or `if not named`
    killed none of the mutations this ticket had listed, because nothing
    exercised either. A raise nothing reaches is the same shape as the three
    permanently-skipped tests found earlier here -- code that reads like a
    guarantee and is not one.

    **The first version of this test named `len(named) > 1` in this very
    docstring as a raise nothing exercised, and then did not cover it.** A
    second review replaced that raise with a silent pick-first and the whole
    suite stayed green. An absolute in a test name, on the commit that
    renamed another test for exactly that.

    The last two branches are new, and both were silent before: a pin naming
    two opted-in labels used to `continue`, and a label named twice used to
    take the last one. `read_seeed_net_names` refuses both, so one file held
    two rules for the same situation.
    """
    library = _symbol_library()

    # 1. A label opted in whose symbol pin names no pin. `SWDIO` on the RP2040
    #    symbol is a bare `SWDIO`, so the opt-in is the thing that is wrong.
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (library,), symbol="XIAO-RP2040-SMD", labels=("SWDIO",))
    assert "was opted in as naming its pin and does not" in str(raised.value)

    # 2. More than one library given. Only reachable if `seeed_symbol` ever
    #    gains a second path, and it used to be a bare `ValueError` that
    #    `main` does not catch -- a traceback where every sibling prints.
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (library, library), symbol="XIAO-STM32C5-SMD", labels=("SWDIO",))
    assert "was given 2" in str(raised.value)

    # 3. One pin carrying two opted-in labels. Synthesised, because Seeed
    #    publish no such pin: it passes the unclaimed sweep (both labels are
    #    opted in) and used to fall out of the loop resolving neither pad.
    two = library.replace('(name "SWDIO/PA13"', '(name "SWDIO/SWCLK/PA13"', 1)
    assert two != library
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (two,), symbol="XIAO-STM32C5-SMD", labels=("SWDIO", "SWCLK"))
    assert "two opted-in labels on one pin" in str(raised.value)

    # 4. One pin naming TWO pins. The raise this test's docstring named and
    #    then did not cover; a review swapped it for a silent pick-first and
    #    nothing went red.
    both = library.replace('(name "SWDIO/PA13"', '(name "SWDIO/PA13/PA15"', 1)
    assert both != library
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (both,), symbol="XIAO-STM32C5-SMD", labels=("SWDIO", "SWCLK"))
    assert "names ['PA13', 'PA15']" in str(raised.value)

    # 5. One label named twice with different pins -- a disagreement, which
    #    this file records rather than averaging. Last-write-wins would have
    #    answered PA15 with nothing said.
    twice = library.replace('(name "SWCLK/PA14"', '(name "SWDIO/PA15"', 1)
    assert twice != library
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (twice,), symbol="XIAO-STM32C5-SMD", labels=("SWDIO",))
    assert "saying two things" in str(raised.value)

    # 6. A pin named in KiCad's OTHER place for one. The sweep speaks for the
    #    whole library, so a name it cannot see is a way past the alarm. This
    #    file has none today, which is why the alternate is only ever refused
    #    and never resolved from.
    #
    #    Injected INSIDE the STM32C5's own body: the first `(name "D0"` in the
    #    file belongs to another symbol, and putting it there proved only that
    #    the slicing works. `PA09` and not the `PE2` a review reached for --
    #    `_CHIP_PIN_NAME` has no `P[E-H]` branch, so `PE2` is exactly the
    #    spelling this sweep does NOT catch and the docstring now says so.
    assert "(alternate " not in library, "no longer synthetic; read them properly"
    at = library.index('(symbol "XIAO-STM32C5-SMD"')
    body = library[at:]
    injected = body.replace('(name "D0"', '(alternate "PA09" line none)(name "D0"', 1)
    assert injected != body
    alternate = library[:at] + injected
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (alternate,), symbol="XIAO-STM32C5-SMD",
            labels=("SWDIO", "SWCLK"))
    assert "PA09" in str(raised.value)

    # 7. An alternate carrying an OPTED-IN label beside a pin. **A third
    #    state, and the one the guard above did not have.** The opt-in
    #    exemption used to apply to alternates as well, so this passed the
    #    sweep and was then read by nothing: the reader returned PA13 and
    #    PA14 as if the library had said nothing more. Refused now, because
    #    an alternate is never resolved FROM and an opt-in cannot excuse
    #    what nothing reads.
    at2 = library.index('(symbol "XIAO-STM32C5-SMD"')
    opted = library[:at2] + library[at2:].replace(
        '(name "D0"', '(alternate "SWDIO/PA15" line none)(name "D0"', 1)
    assert opted != library
    with pytest.raises(pindefs.PindefError) as raised:
        pindefs.read_symbol_pin_names(
            (opted,), symbol="XIAO-STM32C5-SMD", labels=("SWDIO", "SWCLK"))
    assert "SWDIO/PA15" in str(raised.value)


def test_the_nrf54lm20a_reset_pad_says_which_kind_of_null_it_is():
    """`nRF54_RST` sat between two pads that explain themselves and did not.

    Its neighbours `nRF54_SWDIO` and `nRF54_SWCLK` say they are dedicated pads
    of the part rather than GPIOs. Reset is the same category and answerable
    from the same file, so "no board-support package covering this board
    defines this label" was true and useless there.

    **The reason claims the part's reset is a dedicated pin and does NOT claim
    this pad is on that net**, and this test holds both halves. Seeed name no
    net `nRF54_RST`; the nearest runs from the on-board debugger to a MOSFET
    gate, so which side of that switch the exposed pad is on has not been read
    and the sentence does not say.
    """
    document = json.loads(
        pindefs.board_path("XIAO-nRF54LM20A-SMD").read_text(encoding="utf-8"))
    pad = next(one for one in document["pads"] if one["label"] == "nRF54_RST")
    assert pad["chip_pin"] is None
    assert "a reset pad of the nRF54LM20A, not a GPIO" in pad["why_null"]
    assert "nRESET_F2" in pad["why_null"]
    assert "reaches" not in pad["why_null"], (
        "the pad's own net was never traced, so the reason must not say it reaches"
    )

    # The two facts the sentence rests on, read from the vendor's file rather
    # than restated. Skipped only where that file is absent.
    path = SEEED_PCB / "nRF54LM20A.kicad_pcb"
    if not path.is_file():
        pytest.skip(f"no {path}")
    board = path.read_text(encoding="utf-8", errors="replace")
    mcu = [by_net for value, by_net in pindefs._footprints(board)
           if "nRF54LM20A" in value]
    assert len(mcu) == 1
    reset = [net for net, pads in mcu[0].items() if "nRESET_F2" in pads]
    assert reset == ["~{nRF54_RESET}"], reset
    # Sixty-six pads numbered by port and bit, which is the count the sentence
    # quotes; the reset pad is not one of them.
    numbered = {pad for pads in mcu[0].values() for pad in pads
                if re.match(r"^P\d\.\d\d", pad)}
    assert len(numbered) == 66, sorted(numbered)
    # **`P0.00 through P3.12` is quoted in the same sentence and was the one
    # part of it nothing recomputed.** The count and the net name were held
    # here; the span was not, so a vendor adding a P3.13 would have left the
    # reason reading correctly and describing the wrong part.
    ports = {}
    for one in numbered:
        port, bit = re.match(r"^P(\d)\.(\d\d)", one).groups()
        ports.setdefault(port, set()).add(int(bit))
    lowest = min(f"P{port}.{min(bits):02d}" for port, bits in ports.items())
    highest = max(f"P{port}.{max(bits):02d}" for port, bits in ports.items())
    # **Derived from the vendor's file and then checked against the SENTENCE**,
    # rather than against a copy of the answer kept here. A literal span was
    # the first version: it goes red when Seeed add a `P3.13`, but so would a
    # dozen unrelated edits, and it would not say that the thing which had
    # become wrong was the reason text a reader sees. This couples the claim
    # to the file it claims to have read.
    assert f"{lowest} through {highest}" in pad["why_null"], (
        lowest, highest, pad["why_null"])
    # And no net carries the pad's own name, which is why nothing was traced.
    assert "\"nRF54_RST\"" not in board


def test_a_traced_label_that_reaches_nothing_is_refused_rather_than_silent():
    """Two silences looked alike and only one of them was a fact.

    `read_seeed_traced` answered an empty dict for both "this pad reaches the
    part and is not a GPIO" and "this label is on no net of the part at all".
    The first is the silicon speaking and `Board.reasons` answers it in words.
    The second is a citation naming something that is not there, and it could
    not fail however wrong it got.

    **The cost was never the two labels removed here.** If a vendor revision
    renamed the `SWDIO` net in `MG24.kicad_pcb`, that board's `PA02` and
    `PA01` would vanish exactly this quietly and its pads would fall back to a
    generic null with nothing raised.
    """
    path = SEEED_PCB / "nRF54LM20A.kicad_pcb"
    if not path.is_file():
        pytest.skip(f"no {path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    # THE FACT. Both labels reach the MCU, and its pads for them are outside
    # the Pn.nn numbering, so they resolve to nothing and stay silent.
    assert pindefs.read_seeed_traced(
        (text,), part="nRF54LM20A",
        labels=("nRF54_SWDIO", "nRF54_SWCLK")) == {}
    # ...and this is what they reach, so the silence above is a dedicated pad
    # and not an accident of a net that was missing all along.
    mcu = [by_net for value, by_net in pindefs._footprints(text)
           if "nRF54LM20A" in value]
    assert len(mcu) == 1
    assert {net: sorted(pads) for net, pads in mcu[0].items()
            if net in ("nRF54_SWDIO", "nRF54_SWCLK")} == {
        "nRF54_SWDIO": ["SWDIO_G2"], "nRF54_SWCLK": ["SWDCLK_G1"]}

    # THE CITATION THAT NAMES NOTHING. Both of these were asked for by the
    # board entry until now. `SHPHLD` is a pin of the board's nPM1300, and
    # `nRF54_RST`'s net is spelled `~{nRF54_RESET}`.
    for label in ("SHPHLD", "nRF54_RST"):
        with pytest.raises(pindefs.PindefError) as raised:
            pindefs.read_seeed_traced(
                (text,), part="nRF54LM20A", labels=(label,))
        assert "is on no net" in str(raised.value), label

    # And the board entry no longer asks for either, so the generator runs.
    traced = [source for source in pindefs.BOARDS["XIAO-nRF54LM20A-SMD"].sources
              if source.package == "seeed-pcb" and "SHPHLD" in repr(source)]
    assert traced == [], "SHPHLD is still traced and would now raise"

    # **A ball suffix was NOT the reason any of this was silent**, and a
    # review said it was. `_CHIP_PIN_NAME` reads straight through one.
    assert pindefs._CHIP_PIN_NAME.match("P0.00_K3").group(1) == "P0.00"
    assert pindefs._CHIP_PIN_NAME.match("SWDIO_G2") is None


def test_the_spellings_the_board_file_advertises_are_the_ones_the_pattern_takes():
    """The shipped sentence names three spellings, and it drifted once.

    It read `` `GPIOn`, `PXn`, `Pn.nn` `` while the pattern's port branch is
    `P[A-D]`, so it advertised any port letter and accepted four. That is a
    regex restated by hand in prose a user reads, which is the drift this
    checks for -- not the wording, but that every spelling the board file
    offers is one `_CHIP_PIN_NAME` actually takes, and that the letters it
    excludes really are excluded.
    """
    assumption = json.loads(pindefs.board_path("XIAO-XIAO STM32C5-SMD")
                            .read_text(encoding="utf-8"))["assumption"]
    assert "`GPIOn`, `PAn` through `PDn`, `Pn.nn`" in assumption, assumption

    # Every spelling it advertises is one the pattern takes...
    for good in ("GPIO0", "GPIO29", "PA13", "PB3", "PC10", "PD15", "P1.02"):
        assert pindefs._CHIP_PIN_NAME.match(good), good
    # ...and the letters the sentence says are outside really are.
    assert "Ports E through H are not among those spellings" in assumption
    for bad in ("PE2", "PF1", "PG0", "PH2"):
        assert pindefs._CHIP_PIN_NAME.match(bad) is None, bad


def test_the_user_led_reports_the_pin_two_sources_name_and_writes_neither():
    """A pad whose pin is known and deliberately not written.

    Seeed's board file and Zephyr independently put the nRF54L15's user LED
    on P2.00. The pad is labelled `USER_LED` and the vendor's net says
    `USR_LED`, and nothing in this tree joins the two spellings -- the net
    carries the MCU pad, a green LED and a test point, and no castellated pad
    at all. So the reason names the pin and `chip_pin` stays null.

    **Both halves are the test.** If the pin were written, a reader would take
    it for something established; if the reason were dropped, a real answer
    that two vendors agree on would be thrown away. This holds it in between,
    and re-derives both sources rather than restating them.
    """
    pad = next(
        one for one in json.loads(pindefs.board_path("XIAO-nRF54l15-SMD")
                                  .read_text(encoding="utf-8"))["pads"]
        if one["label"] == "USER_LED")
    assert pad["chip_pin"] is None, "the spellings are still unjoined"
    assert pad["chip_index"] is None
    why = pad["why_null"]
    assert "P2.00{slash}USR_LED" in why and "led0 = <&gpio2 0>" in why
    assert "NOT written into `chip_pin`" in why

    # Source one: the vendor's own board file, and the three things on it.
    board = SEEED_PCB / "nRF54L15.kicad_pcb"
    if not board.is_file():
        pytest.skip(f"no {board}")
    text = board.read_text(encoding="utf-8", errors="replace")
    on_it = [(value, sorted(pads)) for value, by_net in pindefs._footprints(text)
             for net, pads in by_net.items() if net == "P2.00{slash}USR_LED"]
    assert len(on_it) == 3, on_it
    assert ["P2.00"] in [pads for _, pads in on_it], on_it
    # ...and no exposed pad of this board is among them, which is the gap.
    assert not any("XIAO" in value.upper() for value, _ in on_it), on_it
    # The pad's own label appears nowhere in the vendor's file.
    assert "USER_LED" not in text

    # Source two: Zephyr, stating the same pin without reference to the first.
    dts = (BSP_DIR / "zephyr" / "boards" / "seeed" / "xiao_nrf54l15"
           / "xiao_nrf54l15_common.dtsi")
    if not dts.is_file():
        pytest.skip(f"no {dts}")
    body = dts.read_text(encoding="utf-8")
    assert "gpios = <&gpio2 0 GPIO_ACTIVE_LOW>" in body, (
        "Zephyr no longer puts led0 on P2.00, so the reason's second source "
        "is stale and the sentence must be re-read against it")


def test_the_swd_pads_quote_a_vendor_page_that_says_what_they_quote():
    """Six pads called it unpublished while Seeed's own page named it.

    The RP2040, SAMD21 and nRF52840 SWD pads carried "no board-support
    package covering this board defines this label", which was true and
    unhelpful. `third_party/seeed-pcb/` holds no board file for those three
    parts, so the trace that answered the RP2350's and both Nordics' pads was
    not available -- and that was taken as the end of it. Seeed publish a wiki
    page for every one of them, fetched by the same command as the symbol
    library, and each names SWD among the board's interfaces.

    **The reason quotes those pages, so this reads them back.** A quotation is
    the easiest kind of claim to get wrong: the OH-170 pass that added this
    had already shipped a pad name that was in no file and a pin count that
    was off by thirty-four.

    It also holds the two NOT-claims. The sentence must not say the silicon
    has no GPIO behind the pad, which is true of some parts and false of
    others and is stated by no file here; and it must not say SWD sits
    outside the header pin count, which only the nRF52840's page settles.
    """
    docs = ROOT / "third_party" / "seeed-xiao" / "document"
    if not docs.is_dir():
        pytest.skip(f"no {docs}; run python tools/get_board_sources.py seeed-xiao")

    quoted = 0
    for board in ("XIAO-RP2040-SMD", "XIAO-SAMD21-SMD", "XIAO-nRF52840-SMD"):
        document = json.loads(
            pindefs.board_path(board).read_text(encoding="utf-8"))
        for pad in document["pads"]:
            if pad["label"] not in ("SWDIO", "SWCLK"):
                continue
            why = pad["why_null"]
            assert pad["chip_pin"] is None, (board, pad["label"])
            assert "the SWD debug interface" in why, (board, why)

            # The page it names must exist and must contain what it quotes.
            named = re.search(r"([\w.-]+\.md) says '([^']+)'", why)
            assert named, why
            pages = [one for one in docs.rglob(named.group(1))]
            assert len(pages) == 1, (named.group(1), pages)
            text = pages[0].read_text(encoding="utf-8", errors="replace")
            assert named.group(2) in text, (named.group(1), named.group(2))

            # And the claim about the packages is true: every file this tool
            # reads for this board really does mention neither label.
            for source in pindefs.BOARDS[board].sources:
                root = (source.root if source.root is not None
                        else ROOT / "third_party" / "bsp" / source.package)
                for relative in source.paths:
                    one = root / relative
                    if not one.is_file():
                        continue
                    body = one.read_text(encoding="utf-8", errors="replace").upper()
                    assert "SWDIO" not in body and "SWCLK" not in body, (
                        f"{one} names SWD after all, so this pad can be "
                        f"resolved and the reason is now wrong")

            # Both boundaries the pages do not settle.
            assert "NOT claimed: whether the chip has a GPIO" in why
            assert "dedicated" not in why, (
                "the other debug reasons say dedicated because a footprint "
                "showed it; no footprint here does")
            quoted += 1

    assert quoted == 6, quoted


def test_a_generated_reason_reads_the_supplies_the_crystal_and_the_debugger():
    """Two clauses in generated reasons cite vendor facts nothing re-derived.

    `_DEDICATED_DEBUG` ends "alongside the supplies and the crystal" and
    `_SECOND_CHIP` says the debugger is "an ATSAMD11D14A". Both are true of
    every part using them today -- measured before this was written -- and
    neither was checked, so a fourth part with no crystal, or a board Seeed
    fitted a different debugger to, would keep the sentence and lose the fact.

    **This is the class two reviews on this ticket kept finding**, not another
    instance of it: a clause asserting something out of a vendor file that no
    test reads back. "sixty-six" and "P0.00 through P3.12" were the same shape
    and are derived now; these two were still prose.

    Each debug reason names the file it came from, so this opens THAT file
    rather than a mapping written here -- the same reason the STM32C5's own
    `derivation` is what found its two published pins.
    """
    crystals = debuggers = reaches = untraced = 0
    for board in BOARDS:
        document = json.loads(
            pindefs.board_path(board).read_text(encoding="utf-8"))
        for pad in document["pads"]:
            why = pad.get("why_null") or ""

            if "alongside the supplies and the crystal" in why:
                cited = re.search(r"Seeed's own (\S+\.kicad_pcb)", why)
                assert cited, f"{board} {pad['label']}: the reason cites no file"
                path = SEEED_PCB / cited.group(1)
                if not path.is_file():
                    pytest.skip(f"no {path}")
                chip = re.search(r"pad of the (\w+), not a GPIO", why).group(1)
                text = path.read_text(encoding="utf-8", errors="replace")
                mcu = [by_net for value, by_net in pindefs._footprints(text)
                       if chip in value]
                assert len(mcu) == 1, (board, chip, len(mcu))
                names = {one for pads in mcu[0].values() for one in pads}
                # Three parts reach this line and two spellings cover them:
                # Raspberry `XIN`/`XOUT` on the RP2350, Nordic `XC1`/`XC2` on
                # both nRF54s. Nothing wider, on purpose. A draft added
                # `XL\d` and `XTAL` "so an MG24 would pass", which was three
                # mistakes at once: no MG24 pad carries this reason so that
                # footprint is never opened here, Nordic's XL pins are named
                # `P1.00/XL1` which `^XL\d` cannot match anyway, and a branch
                # nothing reaches is not a safeguard. A fourth part with a
                # third spelling should turn this red and be widened then.
                assert any(re.match(r"X(C\d|IN|OUT)", one)
                           for one in names), (
                    f"{chip}: the reason says 'the crystal' and this "
                    f"footprint names no crystal pad")
                assert any(re.match(r"(VDD|VSS|IOVDD|DVDD|AVDD|DEC)", one)
                           for one in names), (
                    f"{chip}: the reason says 'the supplies' and this "
                    f"footprint names no supply pad")
                crystals += 1

            if "this pad reaches the on-board debugger" in why:
                # **"Reaches" is a topology claim, so the net is what checks
                # it.** Asserting only that the board carries a SAMD11 left
                # the strongest word in the sentence unread -- and three
                # other pads were making the same claim with no net of their
                # name anywhere, which is what split the reason in two.
                stem = board.replace("XIAO-", "").replace("-SMD", "").lower()
                files = [one for one in SEEED_PCB.glob("*.kicad_pcb")
                         if one.stem.lower() == stem]
                if not files:
                    pytest.skip(f"no {stem}.kicad_pcb in {SEEED_PCB}")
                text = files[0].read_text(encoding="utf-8", errors="replace")
                samd = [by_net for value, by_net in pindefs._footprints(text)
                        if "SAMD11" in value.upper()]
                assert len(samd) == 1, (board, len(samd))
                nets = {net.replace("{slash}", "/").rsplit("/", 1)[-1].upper()
                        for net in samd[0]}
                assert pad["label"].upper() in nets, (
                    f"{board} {pad['label']}: the reason says it reaches the "
                    f"debugger and no net of its name is on that footprint")
                reaches += 1

            if "named for the on-board debugger" in why:
                # The three that were NOT traced say so, and the file agrees
                # that there is nothing to trace.
                assert "NOT claimed: which pin it reaches" in why
                stem = board.replace("XIAO-", "").replace("-SMD", "").lower()
                files = [one for one in SEEED_PCB.glob("*.kicad_pcb")
                         if one.stem.lower() == stem]
                if not files:
                    pytest.skip(f"no {stem}.kicad_pcb in {SEEED_PCB}")
                text = files[0].read_text(encoding="utf-8", errors="replace")
                everywhere = {net.replace("{slash}", "/").rsplit("/", 1)[-1].upper()
                              for _, by_net in pindefs._footprints(text)
                              for net in by_net}
                assert pad["label"].upper() not in everywhere, (
                    f"{board} {pad['label']}: a net of this name DOES exist, "
                    f"so this pad can be traced and should not say otherwise")
                untraced += 1

            if "an ATSAMD11D14A" in why:
                # **Matched case-insensitively on purpose.** The board key is
                # `XIAO-nRF54l15-SMD` and the committed file is
                # `nRF54L15.kicad_pcb`; building the path by string resolves
                # on a Windows worktree and fails on a Linux CI, which is a
                # test passing for the wrong reason in one of the two places
                # it runs.
                stem = board.replace("XIAO-", "").replace("-SMD", "").lower()
                files = [one for one in SEEED_PCB.glob("*.kicad_pcb")
                         if one.stem.lower() == stem]
                if not files:
                    pytest.skip(f"no {stem}.kicad_pcb in {SEEED_PCB}")
                assert len(files) == 1, files
                text = files[0].read_text(encoding="utf-8", errors="replace")
                found = [value for value, _ in pindefs._footprints(text)
                         if "SAMD11" in value.upper()]
                assert found == ["ATSAMD11D14A-UUT"], (board, found)
                debuggers += 1

    # Not vacuous. These are the pads the two reasons actually cover.
    assert (crystals, debuggers, reaches, untraced) == (6, 9, 6, 3), (
        crystals, debuggers, reaches, untraced)


# --- a manifest board's own board file, traced to its chip (OH-178) ----------

#: A part's pin table for the traced reader's own tests: of its four pins,
#: 1 and 2 are GPIOs, 3 is a supply, and 4 is not transcribed. A fifth pad
#: on the footprint is past the pins it numbers.
_TABLE = board_manifest.PinTable(
    "QFN", "PART", "this test's own table", "https://example.invalid/part.pdf",
    "0" * 64, 4, (("1", 4), ("2", 5)), (("3", "3V3"),))

#: The two-pad parts a trace must not cross, as a board file names them.
_NOT_RESISTORS = {"D1": "RED", "SJ1": "JUMPER-SMT_2_NO_SILK", "C1": "0.1uF",
                  "SW1": "SWITCH", "J2": "CONN_02", "R9": "DNP", "X1": "1k"}


def _traced_board(signals: dict[str, list[str]],
                  parts: dict[str, tuple[int, str]] | None = None) -> str:
    """A minimal EAGLE board: header J1 of four pads, U1 placed as the
    table's part with five pads, and `parts` as `name: (pads, value)`;
    `signals` maps a net to its `element.pad` contacts. Written as text so
    the fixture reads as the format."""
    parts = {"U1": (5, "PART"), **(parts or {})}

    def package(name: str, count: int) -> str:
        return (f'<package name="{name}">'
                + "".join(f'<smd name="{n}" x="{n}" y="0" dx="1" dy="1" layer="1"/>'
                          for n in range(1, count + 1))
                + "</package>")
    packages = package("HDR", 4) + "".join(
        package("QFN" if count == 5 else f"P{count}", count)
        for count in sorted({count for count, _ in parts.values()}))
    placed = '<element name="J1" library="L" package="HDR" x="0" y="0"/>' + "".join(
        f'<element name="{name}" library="L" package="{"QFN" if count == 5 else f"P{count}"}"'
        f' value="{value}" x="10" y="0"/>' for name, (count, value) in parts.items())
    nets = "".join(
        f'<signal name="{net}">'
        + "".join('<contactref element="{}" pad="{}"/>'.format(*one.split("."))
                  for one in contacts)
        + "</signal>"
        for net, contacts in signals.items())
    return ('<?xml version="1.0" encoding="utf-8"?><eagle version="9.6.2"><drawing><board>'
            f'<libraries><library name="L"><packages>{packages}</packages></library></libraries>'
            f"<elements>{placed}</elements><signals>{nets}</signals>"
            "</board></drawing></eagle>")


def _traced(text: str) -> dict[str, str | None]:
    return {net: found.pin.name if found.pin else None for net, found in
            pindefs.read_eagle_traced((text,), path=pathlib.Path("probe.brd"),
                                      select=("J1",), table=_TABLE).items()}


def test_a_net_on_a_chip_pad_names_the_gpio_the_datasheet_row_gives():
    assert _traced(_traced_board({"TX": ["J1.1", "U1.1"]})) == {"TX": "GPIO4"}


def test_a_net_reaches_its_chip_through_one_resistor_in_series_and_nothing_else():
    """One resistor, `R<n>` with a value in ohms, whose far net holds only it
    and the chip pad: the QT Py's TX, through R4, and the path names it. Two
    resistors, a divider's midpoint, a part of three pads, and every other
    two-pad part -- an LED, an open jumper, a capacitor, a switch, a
    connector, a resistor not fitted, a part that is not named as one --
    stop the trace, and the pad is not resolved."""
    one = {"TX": ["J1.1", "R1.1"], "N1": ["R1.2", "U1.1"]}
    assert _traced(_traced_board(one, {"R1": (2, "1k")})) == {"TX": "GPIO4"}
    (found,) = pindefs.read_eagle_traced(
        (_traced_board(one, {"R1": (2, "1k")}),), path=pathlib.Path("probe.brd"),
        select=("J1",), table=_TABLE).values()
    assert found.via == "TX -> R1 (1k) -> U1 pad 1 = GPIO4 (this test's own table)"
    two = {"TX": ["J1.1", "R1.1"], "N1": ["R1.2", "R2.1"], "N2": ["R2.2", "U1.1"]}
    assert _traced(_traced_board(two, {"R1": (2, "1k"), "R2": (2, "1k")})) == {}
    divider = {"VBAT": ["J1.1", "R1.1"], "SENSE": ["R1.2", "R2.1", "U1.1"],
               "GND": ["R2.2", "J1.2"]}
    assert _traced(_traced_board(divider, {"R1": (2, "1k"), "R2": (2, "1k")})) == {}
    assert _traced(_traced_board(
        {"TX": ["J1.1", "R1.1"], "N1": ["R1.2", "U1.1"]}, {"R1": (3, "1k")})) == {}
    for name, value in _NOT_RESISTORS.items():
        signals = {"TX": ["J1.1", f"{name}.1"], "N1": [f"{name}.2", "U1.1"]}
        assert _traced(_traced_board(signals, {name: (2, value)})) == {}, name


def test_a_net_on_a_chip_pad_the_table_gives_no_gpio_names_none_and_stops_there():
    """A rail on the chip's 3V3 pad, and through a pull-up on a GPIO whose
    net holds nothing else: it names no pin, and the path says what it
    reached. A pad past the pins the table numbers is not one of them."""
    signals = {"3V3": ["J1.1", "U1.3", "U1.5", "R1.1"], "IO4": ["R1.2", "U1.1"]}
    assert _traced(_traced_board(signals, {"R1": (2, "10k")})) == {"3V3": None}


def test_a_pad_past_the_pins_the_page_numbers_is_reached_and_names_no_pin():
    """The footprint's own pad past the page's count: the net touches the
    chip there, so no resistor is crossed from it, and the path says what
    that pad is rather than dropping it."""
    signals = {"GNDPAD": ["J1.1", "U1.5", "R1.1"], "N1": ["R1.2", "U1.1"]}
    (found,) = pindefs.read_eagle_traced(
        (_traced_board(signals, {"R1": (2, "10k")}),), path=pathlib.Path("probe.brd"),
        select=("J1",), table=_TABLE).values()
    assert found == pindefs.Traced(None, (
        "GNDPAD -> U1 pad 5 = not a pin of the part (past the page's 4) "
        "(this test's own table)"))


def test_a_pad_the_table_does_not_transcribe_is_refused_and_never_read_as_no_gpio():
    """Directly, through a resistor, and under a name that carries a GPIO:
    the refusal says the table left the pad out, not that the copper
    reaches no GPIO."""
    for signals, parts in (({"BOOT": ["J1.1", "U1.4"]}, {}),
                           ({"IO9/BOOT": ["J1.1", "U1.4"]}, {}),
                           ({"TX": ["J1.1", "R1.1"], "N1": ["R1.2", "U1.4"]},
                            {"R1": (2, "1k")})):
        with pytest.raises(PindefError, match=r"reaches U1 pad 4, which the table from "
                                              r"this test's own table does not transcribe"):
            _traced(_traced_board(signals, parts))


def test_a_net_named_for_another_gpio_than_its_copper_reaches_is_refused():
    """The name is a cross-check and never the source, read in every
    `/`-part, as `IO<n>` or `GPIO<n>`, in either case."""
    assert _traced(_traced_board({"IO4/TX": ["J1.1", "U1.1"]})) == {"IO4/TX": "GPIO4"}
    assert _traced(_traced_board({"tx/gpio4": ["J1.1", "U1.1"]})) == {"tx/gpio4": "GPIO4"}
    for net, reaches in (("TX/IO5", r"U1 pad 1 = GPIO4"), ("GPIO5", r"U1 pad 1 = GPIO4"),
                         ("tx/io5", r"U1 pad 1 = GPIO4"), ("IO4", r"no pad of U1"),
                         ("IO4/3V3", r"U1 pad 3 = 3V3")):
        contacts = {"IO4": ["J1.1"], "IO4/3V3": ["J1.1", "U1.3"]}.get(net, ["J1.1", "U1.1"])
        with pytest.raises(PindefError, match=f"'{re.escape(net)}' is named for GPIO\\d+ "
                                              f"and its copper reaches {reaches}"):
            _traced(_traced_board({net: contacts}))


def test_a_net_on_two_pads_of_the_chip_is_refused():
    for other in ("U1.2", "U1.3"):
        with pytest.raises(PindefError, match=r"'TX' reaches pads \['1', '[23]'\] of U1"):
            _traced(_traced_board({"TX": ["J1.1", "U1.1", other]}))


def test_the_table_is_read_against_exactly_one_element_of_its_package_and_value():
    """Another element on the same package with another value is not the
    chip; none, or two, and the file is refused, naming itself."""
    assert _traced(_traced_board({"TX": ["J1.1", "U1.1"]}, {"U2": (5, "OTHER")})) == {
        "TX": "GPIO4"}
    for parts, count in (({"U1": (5, "OTHER")}, 0), ({"U2": (5, "PART")}, 2)):
        with pytest.raises(PindefError, match=f"{count} elements in probe.brd"):
            _traced(_traced_board({"TX": ["J1.1"]}, parts))
    with pytest.raises(PindefError, match="probe.brd: not XML"):
        _traced("not a board")


def test_a_manifest_board_and_a_xiao_each_report_their_own_derivation():
    """What `python tools/import_pindefs.py <board>` prints above the pads,
    and a row's own CAD at a `sha256:` rather than something that reads as a
    git revision."""
    _needs_the_fetched_packages("zephyr", "arduino-esp32")
    assert board_report("XIAO-ESP32-C3-DIP")["derivation"] == pindefs.DERIVATION
    unread = _unread_without_a_compiler()
    for row in [row for row in board_manifest.ROWS if row.board not in unread]:
        if not board_manifest.cad_path(row).is_file():
            pytest.skip(f"{row.source} is not fetched")
        report = board_report(row.board)
        assert report["derivation"] == pindefs.MANIFEST_DERIVATION
        (own,) = [one for one in report["packages"] if one["name"] == row.source]
        assert re.fullmatch(r"sha256:[0-9a-f]{12}", own["revision"]), own
    _skip_the_unread(unread)


def test_a_pad_the_footprint_names_otherwise_is_read_as_the_page_number_the_table_gives():
    """The KB2040's RP2040 footprint calls its central pad `P$1`, which the
    datasheet numbers 57 (`footprint_pads`). Here U1's pad 5, past this
    table's 4 pins, is read as the page's pin 1 once the table says so, and
    the path still names the footprint's pad."""
    signals = {"TX": ["J1.1", "U1.5"]}
    assert _traced(_traced_board(signals)) == {"TX": None}
    (found,) = pindefs.read_eagle_traced(
        (_traced_board(signals),), path=pathlib.Path("probe.brd"), select=("J1",),
        table=dataclasses.replace(_TABLE, footprint_pads=(("5", "1"),))).values()
    assert found == pindefs.Traced(
        ChipPin("GPIO4", 4), "TX -> U1 pad 5 = GPIO4 (this test's own table)")


# --- arduino-pico, read through its preprocessor (OH-181) ---------------------
#
# The fixtures below stand for the real files they are named after, as the
# rest of this file's do. Where a test needs the real checkout and the
# compiler its recipe names, it skips by name without them.

#: `variants/adafruit_kb2040/pins_arduino.h`'s shape: bus pins, and then
#: every `D<n>` from a file it includes.
PICO_INCLUDING_H = """\
#pragma once
#define PIN_LED        (31u)
#define PIN_SPI0_SCK   (18u)
#include "../generic/common.h"
"""

#: `variants/pimoroni_plasma2040/pins_arduino.h`'s shape: pins under `#if 0`.
PICO_IF_0_H = """\
#pragma once
#define PIN_LED        (16u)
#if 0
static const uint8_t D0 = (26u);
#endif
"""


def _needs_the_pico_preprocessor() -> pathlib.Path:
    """The arduino-pico checkout, where it and the compiler its recipe names
    are both here; a skip naming the missing one where not."""
    _needs_the_fetched_packages("arduino-pico")
    checkout = BSP_DIR / "arduino-pico"
    program = pindefs.pico_build(checkout, "adafruit_kb2040").program
    if pindefs.pico_compiler(program) is None:
        pytest.skip(f"SKIPPED: no {program} installed; pio pkg install --global "
                    f"--tool toolchain-gccarmnoneeabi")
    return checkout


def _pico_fixture(root: pathlib.Path, pins_arduino_h: str) -> pathlib.Path:
    """A checkout of one board, `fake`, whose recipe names the compiler and
    passes one flag of its board's and one it cannot know."""
    (root / "variants" / "fake").mkdir(parents=True)
    (root / "variants" / "fake" / "pins_arduino.h").write_text(pins_arduino_h, encoding="utf-8")
    (root / "boards.txt").write_text(
        "fake.build.variant=fake\nfake.build.board=FAKE\n", encoding="utf-8")
    (root / "platform.txt").write_text(
        "compiler.cpp.cmd=arm-none-eabi-g++\n"
        'recipe.cpp.o.pattern="{compiler.path}{compiler.cpp.cmd}" '
        '-DARDUINO={runtime.ide.version} -DARDUINO_{build.board} "{source_file}"\n',
        encoding="utf-8")
    return root


def test_a_variants_flags_are_its_boards_with_each_menu_at_its_first_option(tmp_path):
    """Platform properties, the board's over them, and the first option of
    each of the board's menus over those; what is kept is what can change a
    macro, and a macro flag built from a property the package never sets is
    set aside, named."""
    (tmp_path / "boards.txt").write_text(
        "menu.os=Operating System\n"
        "fake.build.variant=fake\n"
        "fake.build.board=FAKE\n"
        "fake.build.chip=rp2040\n"
        "fake.build.extra_flags=-DFROM_BOARD\n"
        "fake.menu.os.none=None\n"
        "fake.menu.os.none.build.os=\n"
        "fake.menu.os.freertos=FreeRTOS\n"
        "fake.menu.os.freertos.build.os=-D__FREERTOS\n"
        "other.build.variant=other\n",
        encoding="utf-8")
    (tmp_path / "platform.txt").write_text(
        "build.extra_flags=-DFROM_PLATFORM\n"
        "build.os=-DPLATFORM_OS\n"
        "compiler.cpp.cmd=arm-none-eabi-g++\n"
        'recipe.cpp.o.pattern="{compiler.path}{compiler.cpp.cmd}" -c -g {build.os} '
        "{build.extra_flags} -mthumb -I{runtime.platform.path}/include "
        '"@{runtime.platform.path}/lib/{build.chip}/platform_def.txt" '
        '-DARDUINO={runtime.ide.version} -DARDUINO_{build.board} "{source_file}"\n',
        encoding="utf-8")
    build = pindefs.pico_build(tmp_path, "fake")
    assert (build.board, build.program) == ("fake", "arm-none-eabi-g++")
    assert build.flags == ("-DFROM_BOARD", "-mthumb",
                           f"@{tmp_path.as_posix()}/lib/rp2040/platform_def.txt",
                           "-DARDUINO_FAKE")
    assert build.unset == ("-DARDUINO={runtime.ide.version}",)


def test_a_variant_is_read_with_exactly_one_boards_flags(tmp_path):
    (tmp_path / "boards.txt").write_text(
        "fake.build.variant=fake\ntwin.build.variant=fake\n", encoding="utf-8")
    with pytest.raises(PindefError, match=r"builds variants/fake for \['fake', 'twin'\]"):
        pindefs.pico_build(tmp_path, "fake")
    with pytest.raises(PindefError, match="builds variants/none for no board"):
        pindefs.pico_build(tmp_path, "none")


def test_a_response_file_neither_on_disk_nor_committed_is_refused_naming_it(tmp_path):
    with pytest.raises(PindefError, match="the recipe reads lib/rp2040/platform_def.txt, "
                                          "which is neither on disk nor in"):
        pindefs._response_file(tmp_path, f"@{tmp_path.as_posix()}/lib/rp2040/platform_def.txt")


def test_without_a_preprocessor_a_variant_that_includes_a_file_is_refused():
    with pytest.raises(PindefError) as caught:
        pindefs.pico_constants_by_hand(PICO_INCLUDING_H, "kb2040", "arm-none-eabi-g++")
    message = str(caught.value)
    assert "kb2040 has #include, so only the preprocessor can say" in message, message
    assert "pio pkg install --global --tool toolchain-gccarmnoneeabi" in message, message


def test_without_a_preprocessor_a_pin_under_if_0_is_refused_where_the_text_reading_took_it():
    """The reading this replaces took `D0` out from under `#if 0`."""
    assert read_flat_pins((PICO_IF_0_H,))["D0"] == ChipPin("GPIO26", 26)
    with pytest.raises(PindefError, match="plasma has #endif, #if, so only the preprocessor"):
        pindefs.pico_constants_by_hand(PICO_IF_0_H, "plasma", "arm-none-eabi-g++")


def test_without_a_preprocessor_a_file_of_defines_and_constants_reads_as_the_text_does():
    """The XIAO RP2040's shape, and the byte-identity of its board file where
    no compiler is installed rests on this."""
    by_hand = pindefs.pico_constants_by_hand(PICO_PINS_ARDUINO_H, "xiao", "arm-none-eabi-g++")
    assert select_labels(by_hand, ("LED",)) == select_labels(
        read_c_pin_constants(PICO_PINS_ARDUINO_H), ("LED",))


def test_a_d_pin_declared_through_a_name_is_refused_rather_than_left_out():
    text = "#define PIN_X (5u)\nstatic const uint8_t D0 = PIN_X;\nstatic const uint8_t D1 = (1u);\n"
    assert "D0" not in read_c_pin_constants(text)
    with pytest.raises(PindefError, match=r"declares \['D0 = PIN_X'\], which is not an integer"):
        pindefs.pico_constants_by_hand(text, "named", "arm-none-eabi-g++")


def test_an_a_pin_declared_through_a_name_is_refused_too():
    """challenger_2350_nbiot's shape: read by hand, its `A5` went missing
    where the preprocessor numbers it, which the all-variants comparison
    below found."""
    text = ("#define PIN_SPI0_SS (17u)\nstatic const uint8_t D0 = (13u);\n"
            "static const uint8_t A5 = PIN_SPI0_SS;\n")
    assert "A5" not in read_c_pin_constants(text)
    with pytest.raises(PindefError,
                       match=r"declares \['A5 = PIN_SPI0_SS'\], which is not an integer"):
        pindefs.pico_constants_by_hand(text, "challenger", "arm-none-eabi-g++")


def test_an_integer_in_the_parentheses_a_macro_wrapped_it_in_is_read():
    """challenger_2350_bconnect's `A5 = (PIN_SPI0_SS)`, preprocessed, is
    `A5 = ((17u))`; a stray parenthesis is not an integer."""
    assert pindefs.pico_constants_by_hand(
        "static const uint8_t A5 = ((17u));\n", "bconnect", "arm-none-eabi-g++")["A5"] == 17
    with pytest.raises(PindefError, match=r"declares \['A5 = \(\(17u\)'\]"):
        pindefs.pico_constants_by_hand(
            "static const uint8_t A5 = ((17u);\n", "bconnect", "arm-none-eabi-g++")


def test_with_no_preprocessor_installed_the_kb2040_is_refused_and_the_xiao_read_by_hand(
        monkeypatch):
    _needs_the_fetched_packages("arduino-pico")
    checkout = BSP_DIR / "arduino-pico"
    monkeypatch.setattr(pindefs, "pico_compiler", lambda program: None)

    def read(variant, extras=()):
        text = (checkout / "variants" / variant / "pins_arduino.h").read_text(encoding="utf-8")
        return pindefs.read_pico_pins(
            (text,), checkout=checkout, variant=variant, extras=extras)[0]

    with pytest.raises(PindefError, match="variants/adafruit_kb2040/pins_arduino.h has #include"):
        read("adafruit_kb2040")
    assert read("seeed_xiao_rp2040", ("LED",))["D6"] == ChipPin("GPIO0", 0)


def test_the_kb2040s_pins_are_read_through_common_h():
    """Its own file numbers no `D<n>` and no `A<n>`; preprocessed with its
    board's flags, `variants/generic/common.h` numbers `D0`..`D29` as the
    GPIOs of the same number and `A0`..`A3` as GPIO26..29."""
    checkout = _needs_the_pico_preprocessor()
    text = (checkout / "variants" / "adafruit_kb2040" / "pins_arduino.h").read_text(
        encoding="utf-8")
    assert not [name for name in read_c_pin_constants(text) if re.fullmatch(r"[DA]\d+", name)]
    pins, files = pindefs.read_pico_pins((text,), checkout=checkout, variant="adafruit_kb2040",
                                         extras=("A0", "A1", "A2", "A3"))
    assert files == ("variants/adafruit_kb2040/pins_arduino.h", "variants/generic/common.h")
    assert pins == {**{f"D{n}": ChipPin(f"GPIO{n}", n) for n in range(30)},
                    **{f"A{n}": ChipPin(f"GPIO{26 + n}", 26 + n) for n in range(4)}}


def _kb2040_against(tmp_path: pathlib.Path, common_h: str) -> dict[str, ChipPin]:
    """The KB2040 read against a `common.h` of the test's own, every other
    file its build reads copied from the checkout; the recipe's response
    files come from its commit, since `Package.sparse` leaves `lib/` out."""
    real = BSP_DIR / "arduino-pico"
    copy = tmp_path / "arduino-pico"
    for relative in ("boards.txt", "platform.txt", "variants/adafruit_kb2040/pins_arduino.h"):
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_bytes((real / relative).read_bytes())
    for relative in [flag[len(real.as_posix()) + 2:] for flag in
                     pindefs.pico_build(real, "adafruit_kb2040").flags if flag.startswith("@")]:
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_bytes(subprocess.run(
            ["git", "-C", str(real), "show", f"HEAD:{relative}"],
            capture_output=True, check=True).stdout)
    (copy / "variants" / "generic").mkdir(parents=True)
    (copy / "variants" / "generic" / "common.h").write_text(common_h, encoding="utf-8")
    text = (copy / "variants" / "adafruit_kb2040" / "pins_arduino.h").read_text(encoding="utf-8")
    return pindefs.read_pico_pins((text,), checkout=copy, variant="adafruit_kb2040",
                                  extras=("A0",))[0]


_CHIP_GUARD = "#if defined(PICO_RP2040) || (defined(PICO_RP2350) && PICO_RP2350A)"


def test_common_h_read_as_it_is_gives_the_kb2040_its_analog_pins(tmp_path):
    """The control for the two inversions below: the copy, unchanged, reads
    as the checkout does."""
    checkout = _needs_the_pico_preprocessor()
    common_h = (checkout / "variants" / "generic" / "common.h").read_text(encoding="utf-8")
    assert _kb2040_against(tmp_path, common_h)["A0"] == ChipPin("GPIO26", 26)


def test_common_h_with_its_chip_guard_inverted_gives_the_kb2040_no_analog_pins(tmp_path):
    """Inverted, the RP2040's branch is skipped and so is the RP2350B's, so
    there is no `A0` to read: a guard read rather than read past."""
    checkout = _needs_the_pico_preprocessor()
    common_h = (checkout / "variants" / "generic" / "common.h").read_text(encoding="utf-8")
    assert common_h.count(_CHIP_GUARD) == 1
    inverted = common_h.replace(_CHIP_GUARD, f"#if !({_CHIP_GUARD[4:]})")
    with pytest.raises(PindefError, match="'A0' is registered as an extra label, but the "
                                          "file defines none of"):
        _kb2040_against(tmp_path, inverted)


def test_common_h_with_a_pin_guard_inverted_is_refused_for_the_kb2040(tmp_path):
    """`#ifndef __PIN_D0`, on a board that defines no `__PIN_D0`, declares
    `D0 = __PIN_D0`, which names no number, and is refused."""
    checkout = _needs_the_pico_preprocessor()
    common_h = (checkout / "variants" / "generic" / "common.h").read_text(encoding="utf-8")
    assert common_h.count("#ifdef __PIN_D0\n") == 1
    with pytest.raises(PindefError, match=r"declares \['D0 = __PIN_D0'\], which is not an integer"):
        _kb2040_against(tmp_path, common_h.replace("#ifdef __PIN_D0\n", "#ifndef __PIN_D0\n"))


def test_a_pin_under_if_0_is_not_read_by_the_preprocessor():
    """pimoroni_plasma2040's `D<n>` are all under `#if 0`: the text reading
    numbered them, and the preprocessor finds none."""
    checkout = _needs_the_pico_preprocessor()
    text = (checkout / "variants" / "pimoroni_plasma2040" / "pins_arduino.h").read_text(
        encoding="utf-8")
    assert "#if 0" in text
    assert read_flat_pins((text,))["D0"] == ChipPin("GPIO26", 26)
    with pytest.raises(PindefError, match="no D<n> constants among the"):
        pindefs.read_pico_pins((text,), checkout=checkout, variant="pimoroni_plasma2040")


def test_a_guard_on_the_boards_own_flag_is_read_with_that_flag(tmp_path):
    """`-DARDUINO_{build.board}` is `-DARDUINO_FAKE` for this board, and the
    variant's `#ifdef ARDUINO_FAKE` sees it."""
    _needs_the_pico_preprocessor()
    checkout = _pico_fixture(tmp_path, (
        "#ifdef ARDUINO_FAKE\nstatic const uint8_t D0 = (1u);\n"
        "#else\nstatic const uint8_t D0 = (2u);\n#endif\n"))
    assert pindefs.read_pico_pins(("",), checkout=checkout, variant="fake")[0] == {
        "D0": ChipPin("GPIO1", 1)}


def test_a_guard_on_a_flag_the_build_cannot_know_is_refused(tmp_path):
    """`-DARDUINO={runtime.ide.version}` is arduino-cli's to fill, so it is
    left out, and a variant that tests `ARDUINO` would read as though it were
    undefined: refused instead."""
    _needs_the_pico_preprocessor()
    checkout = _pico_fixture(tmp_path, (
        "#ifdef ARDUINO\nstatic const uint8_t D0 = (1u);\n"
        "#else\nstatic const uint8_t D0 = (2u);\n#endif\n"))
    with pytest.raises(PindefError, match=r"consults \['ARDUINO'\], which the build defines "
                                          r"with '-DARDUINO=\{runtime.ide.version\}'"):
        pindefs.read_pico_pins(("",), checkout=checkout, variant="fake")


def test_the_xiao_variants_read_the_same_by_hand_and_preprocessed():
    """What keeps the XIAO RP2040 and RP2350 board files byte-identical
    whichever answers: with the compiler here, and without it, as CI runs."""
    checkout = _needs_the_pico_preprocessor()
    for variant, extras in (("seeed_xiao_rp2040", ("LED",)), ("seeed_xiao_rp2350", ())):
        text = (checkout / "variants" / variant / "pins_arduino.h").read_text(encoding="utf-8")
        build = pindefs.pico_build(checkout, variant)
        preprocessed = pindefs.pico_constants(
            checkout, variant, build, pindefs.pico_compiler(build.program)).constants
        by_hand = pindefs.pico_constants_by_hand(text, variant, build.program)
        assert select_labels(preprocessed, extras) == select_labels(by_hand, extras), variant


def test_every_variant_the_fallback_reads_it_reads_as_the_preprocessor_does():
    """Every arduino-pico variant: where the hand reading answers, it is the
    preprocessor's answer, and the text reading's wrong answers are counted.

    Slow -- two preprocessor runs a variant -- so run only with `OH_SLOW=1`."""
    if os.environ.get("OH_SLOW") != "1":
        pytest.skip("SKIPPED: slow; run it with OH_SLOW=1 pytest "
                    "tests/rules/test_import_pindefs.py -k every_variant_the_fallback -s")
    checkout = _needs_the_pico_preprocessor()
    readings = pindefs.survey_pico(checkout)
    print("\n" + pindefs.summarise_pico(readings, checkout))
    differ = [one.variant for one in readings
              if one.by_hand is not None and one.by_hand != one.preprocessed]
    assert differ == [], differ
    # `_UNDEFINED_OK` is what the variants test while undefined, no more:
    # every alternative in it is one some variant tests.
    tested = {macro for one in readings for macro in one.undefined}
    unused = [allowed for allowed in pindefs._UNDEFINED_OK
              if not any(re.fullmatch(allowed, macro) for macro in tested)]
    assert unused == [], unused


# --- the review's round (OH-181) ----------------------------------------------


def test_a_recipe_is_split_as_arduino_cli_splits_it():
    """A quote opens an argument only as a word's first character and closes
    it only as a word's last, so `-DBOARD_NAME="X"` keeps its quotes -- a
    string literal to the compiler, as in the real build -- and a quoted
    argument keeps its spaces."""
    assert pindefs._split_quoted(
        'g++  -c -DBOARD_NAME="X" "@C:/a b/lib/x.txt" \'-DUSB_PRODUCT="Pico W"\' ') == [
        "g++", "-c", '-DBOARD_NAME="X"', "@C:/a b/lib/x.txt", '-DUSB_PRODUCT="Pico W"']
    with pytest.raises(PindefError, match="no closing \" in the command"):
        pindefs._split_quoted('g++ "-DOPEN')


def test_dudescabs_manufacturer_is_one_argument_with_its_apostrophes(tmp_path):
    """arduino-pico's DudesCab row: `build.usb_manufacturer="L'atelier
    d'Arnoz"` inside platform.txt's `'-DUSB_MANUFACTURER={...}'`."""
    (tmp_path / "boards.txt").write_text(
        "DudesCab.build.variant=DudesCab\n"
        'DudesCab.build.usb_manufacturer="L\'atelier d\'Arnoz"\n', encoding="utf-8")
    (tmp_path / "platform.txt").write_text(
        "compiler.cpp.cmd=arm-none-eabi-g++\n"
        "recipe.cpp.o.pattern=g++ '-DUSB_MANUFACTURER={build.usb_manufacturer}' -Os\n",
        encoding="utf-8")
    assert pindefs.pico_build(tmp_path, "DudesCab").flags == (
        '-DUSB_MANUFACTURER="L\'atelier d\'Arnoz"', "-Os")


def test_the_real_dudescab_row_keeps_its_manufacturer_whole():
    _needs_the_fetched_packages("arduino-pico")
    flags = pindefs.pico_build(BSP_DIR / "arduino-pico", "DudesCab").flags
    assert '-DUSB_MANUFACTURER="L\'atelier d\'Arnoz"' in flags
    assert '-DBOARD_NAME="RASPBERRY_PI_PICO"' in flags


def test_a_kept_flag_naming_a_property_nothing_sets_is_refused(tmp_path):
    (tmp_path / "boards.txt").write_text("fake.build.variant=fake\n", encoding="utf-8")
    (tmp_path / "platform.txt").write_text(
        "compiler.cpp.cmd=arm-none-eabi-g++\n"
        "recipe.cpp.o.pattern=g++ -mcpu={build.mcu} -DARDUINO={runtime.ide.version}\n",
        encoding="utf-8")
    with pytest.raises(PindefError, match="passes '-mcpu=\\{build.mcu\\}', which names a "
                                          "property neither"):
        pindefs.pico_build(tmp_path, "fake")


def test_a_platform_with_no_compile_recipe_is_refused_naming_what_it_lacks(tmp_path):
    (tmp_path / "boards.txt").write_text("fake.build.variant=fake\n", encoding="utf-8")
    (tmp_path / "platform.txt").write_text("compiler.cpp.cmd=arm-none-eabi-g++\n",
                                           encoding="utf-8")
    with pytest.raises(PindefError, match="give fake no \\['recipe.cpp.o.pattern'\\]"):
        pindefs.pico_build(tmp_path, "fake")


def test_a_response_file_outside_the_checkout_is_refused_naming_it(tmp_path):
    with pytest.raises(PindefError, match="which is not under the checkout"):
        pindefs._response_file(tmp_path / "checkout", f"@{tmp_path.as_posix()}/elsewhere.txt")


def test_a_preprocessor_that_hangs_is_refused_naming_the_variant(tmp_path, monkeypatch):
    def hangs(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(pindefs.subprocess, "run", hangs)
    build = pindefs.PicoBuild(board="fake", program="g++", flags=(), unset=())
    with pytest.raises(PindefError, match="-dU took more than 60 s on arduino-pico "
                                          "variants/fake/pins_arduino.h as fake"):
        pindefs.pico_constants(tmp_path, "fake", build, pathlib.Path("g++"))


def test_a_leading_zero_is_octal_and_an_eight_after_it_no_integer():
    """C reads `010` as eight; `09` is no integer, and a pin written so is refused."""
    assert pindefs.pico_constants_by_hand(
        "static const uint8_t D0 = (010u);\n", "octal", "arm-none-eabi-g++")["D0"] == 8
    with pytest.raises(PindefError, match=r"declares \['D1 = 09'\]"):
        pindefs.pico_constants_by_hand(
            "static const uint8_t D1 = 09;\n", "octal", "arm-none-eabi-g++")


def test_without_a_preprocessor_an_undef_is_refused():
    with pytest.raises(PindefError, match="undone has #undef, so only the preprocessor"):
        pindefs.pico_constants_by_hand(
            "#define PIN_LED (16u)\n#undef PIN_LED\nstatic const uint8_t D0 = (0u);\n",
            "undone", "arm-none-eabi-g++")


def test_without_a_preprocessor_a_spaced_conditional_is_refused():
    """`# if`, with the space C allows after the `#`."""
    with pytest.raises(PindefError, match="spaced has #endif, #if, so only the preprocessor"):
        pindefs.pico_constants_by_hand(
            "#  if 0\nstatic const uint8_t D0 = (26u);\n  #  endif\n",
            "spaced", "arm-none-eabi-g++")


def test_a_variant_testing_a_macro_the_sketchs_headers_might_define_is_refused(tmp_path):
    """Not in `_UNDEFINED_OK`, so it might be one of pico.h's or the core's."""
    _needs_the_pico_preprocessor()
    checkout = _pico_fixture(tmp_path, (
        "#ifdef PICO_DEFAULT_LED_PIN\nstatic const uint8_t D0 = (1u);\n"
        "#else\nstatic const uint8_t D0 = (2u);\n#endif\n"))
    with pytest.raises(PindefError, match=r"variants/fake/pins_arduino.h test "
                                          r"\['PICO_DEFAULT_LED_PIN'\] while undefined"):
        pindefs.read_pico_pins(("",), checkout=checkout, variant="fake")


def test_a_sketch_reaches_pins_arduino_h_through_arduino_h_after_pico_h():
    """What `_PICO_UNIT`'s comment says of `cores/rp2040/Arduino.h`, read at
    the checkout's commit: pico-sdk's `pico.h`, then `#undef PICO_RP2350A`,
    then the variant's `pins_arduino.h`."""
    _needs_the_fetched_packages("arduino-pico")
    shown = subprocess.run(
        ["git", "-C", str(BSP_DIR / "arduino-pico"), "show", "HEAD:cores/rp2040/Arduino.h"],
        capture_output=True, text=True, encoding="utf-8", check=False)
    if shown.returncode != 0:
        pytest.skip(f"SKIPPED: cores/rp2040/Arduino.h not readable from the commit: "
                    f"{shown.stderr.strip()}")
    lines = [line.split("//")[0].strip() for line in shown.stdout.splitlines()]
    order = [lines.index(line) for line in (
        "#include <pico.h>", "#undef PICO_RP2350A", "#include <pins_arduino.h>")]
    assert order == sorted(order), order


def test_the_kb2040s_claims_cite_common_h_and_a_xiaos_its_own_file_alone():
    """A claim names the files its numbers were read from."""
    checkout = _needs_the_pico_preprocessor()
    if not board_manifest.cad_path(board_manifest.row("Adafruit KB2040")).is_file():
        pytest.skip("SKIPPED: python tools/get_board_sources.py adafruit-kb2040")
    kb2040 = pindefs.published_pins(pindefs.BOARDS["Adafruit KB2040"], BSP_DIR)
    stamp = pindefs.revision(checkout)
    assert kb2040["D0"][0].source == (
        f"arduino-pico variants/adafruit_kb2040/pins_arduino.h, "
        f"variants/generic/common.h @ {stamp}")
    xiao = pindefs.published_pins(pindefs.BOARDS["XIAO-RP2040-DIP"], BSP_DIR)
    assert [claim.source for claim in xiao["D6"] if claim.package == "arduino-pico"] == [
        f"arduino-pico variants/seeed_xiao_rp2040/pins_arduino.h @ {stamp}"]


def test_the_survey_counts_each_way_against_the_preprocessor():
    """Two variants: one the text reading gets wrong and the hand reading
    refuses, one all three agree on. The preprocessor's own row has no
    wrong count, being what the others are measured against."""
    readings = [
        pindefs.PicoReading("plasma", {"D0": 26}, None, {"A0": 26}, ("#if", "")),
        pindefs.PicoReading("xiao", {"D0": 26, "A0": 26}, {"D0": 26, "A0": 26},
                            {"D0": 26, "A0": 26}, ("", "")),
    ]
    assert pindefs.count_pico(readings) == {
        "before": (2, 1, 0, 1), "by hand": (1, 1, 1, 0), "preprocessor": (1, 2, 0, None)}


def test_a_value_an_if_reads_while_undefined_is_refused(tmp_path):
    """`-dU` does not report `#if ARDUINO_PICO_MAJOR >= 6`, which reads the
    name as a value; `-Wundef` does. Read here it would take the `#else`,
    where a sketch, after the core's RP2040Version.h, takes the `#if`."""
    _needs_the_pico_preprocessor()
    checkout = _pico_fixture(tmp_path, (
        "#if ARDUINO_PICO_MAJOR >= 6\nstatic const uint8_t D0 = (1u);\n"
        "#else\nstatic const uint8_t D0 = (2u);\n#endif\n"))
    with pytest.raises(PindefError, match=r"variants/fake/pins_arduino.h test "
                                          r"\['ARDUINO_PICO_MAJOR'\] while undefined"):
        pindefs.read_pico_pins(("",), checkout=checkout, variant="fake")


def test_a_value_an_if_reads_from_a_flag_the_build_cannot_know_is_refused(tmp_path):
    """`#if ARDUINO >= 100` consults the `ARDUINO` that
    `-DARDUINO={runtime.ide.version}` would define, as `#ifdef ARDUINO` does."""
    _needs_the_pico_preprocessor()
    checkout = _pico_fixture(tmp_path, (
        "#if ARDUINO >= 100\nstatic const uint8_t D0 = (1u);\n"
        "#else\nstatic const uint8_t D0 = (2u);\n#endif\n"))
    with pytest.raises(PindefError, match=r"consults \['ARDUINO'\], which the build defines "
                                          r"with '-DARDUINO=\{runtime.ide.version\}'"):
        pindefs.read_pico_pins(("",), checkout=checkout, variant="fake")
