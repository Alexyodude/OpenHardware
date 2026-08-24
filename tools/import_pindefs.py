#!/usr/bin/env python3
# OpenHardware - recover the label -> chip pin map that a board's CAD does not carry.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Say which MCU pin each silkscreen label on a board actually reaches.

`tools/import_kicad_board.py` got the geometry exactly right and left the
electrics blank on purpose, and said so:

    **`pin`: always null.** That field is the *simulator's* pin index [...]
    Writing a plausible number would be the exact failure
    `rules/conformance-fixtures.md` exists to stop: a config that looks valid
    and wires the circuit wrongly.

Every generated board file repeats the consequence in its own `assumption`
field: *a pad with pin null draws and refuses a wire*. This is the other half
of that join. A footprint knows pad 7 sits at 30.4 x 20.8 and is silkscreened
`D6`. It cannot know that `D6` reaches GPIO0 on a XIAO RP2040 and GPIO21 on a
XIAO ESP32-C3 -- same label, same connector position, different wire.

## Where the mapping lives

Not in the CAD. In the board-support packages, one small file per board:

    zephyr          boards/seeed/<board>/seeed_xiao_connector.dtsi
    arduino-pico    variants/seeed_xiao_rp2040/pins_arduino.h
    arduino-esp32   variants/XIAO_ESP32C3/pins_arduino.h
    seeed-nrf52     variants/Seeed_XIAO_nRF52840/variant.{h,cpp}
    seeed-samd      variants/XIAO_m0/variant.{h,cpp}
    silabs-arduino  variants/xiao_mg24/{pins_arduino.h,arduino_variant.cpp}

Nothing is vendored. `--fetch` clones each blobless and sparse into
`third_party/bsp/`, which is git-ignored, the same fetch-don't-vendor trade
`tools/get_seeed_hardware.sh` argues for the CAD. What is extracted is a pin
number -- a fact about a piece of hardware, not an expression of the package
that recorded it -- and every report names the file and the short revision it
came from, so the claim can be checked rather than believed.

## The three traps

**A label is not a number.** On the RP2040 and ESP32 cores an Arduino pin
number *is* the GPIO: `static const uint8_t D6 = (0u);` means GPIO0. On the
nRF52840, SAMD21 and EFR32MG24 cores it is an index into the core's own table:
`static const uint8_t D6 = 6;` means `g_ADigitalPinMap[6]`, which is 43, which
is P1.11. A reader that took the first form for the second would emit `D6 -> 6`
for a XIAO nRF52840 and look entirely successful doing it. Hence two readers,
`read_flat_pins` and `read_indexed_pins`, and a per-board choice between them.

**Packages disagree, and disagreement is data.** `agree()` returns a pin only
when every package covering the board names the same one; otherwise the pad
stays null and the report records each rival claim beside its file. Averaging,
or preferring a package, would silently pick a winner. Measured on the
revisions `--list` prints, nothing currently disagrees -- worth knowing, and
not the same as the mechanism being untested.

**A pad no package covers stays null.** `3V3_OUT`, `VBUS`, `GND`, `EN`, `PAD`
and the SWD pads are not GPIOs, and `SAMD11_SWDIO` belongs to the other chip
on the board. The existing null is honest and this tool leaves it alone.

## Why only `D<n>`, and extras by name

A board-support package defines far more than pads: `SDA`, `PIN_SPI0_SCK`,
`LED_BUILTIN`, `PIN_VBAT`. Most are alternate functions of a pin already named
`D<n>`, so sweeping them in adds nothing. Some are worse than nothing:
`PIN_VBAT` on the XIAO nRF52840 is P0.31, the GPIO that *senses* the battery
pad through a divider -- it is not the pad silkscreened `VBAT`, and writing it
there would wire a battery terminal to an ADC input. So the readers keep
`D<n>`, and every other label is opted into by name in `BOARDS`, one board at
a time. Today that is `NFC1` and `NFC2` on the XIAO nRF52840, which genuinely
are P0.09 and P0.10.

## Usage

    python tools/import_pindefs.py --fetch                # ~70 MB, git-ignored
    python tools/import_pindefs.py --list                 # boards and sources
    python tools/import_pindefs.py XIAO-RP2040-DIP        # one board's report
    python tools/import_pindefs.py --all -o pindefs.json  # every board
    python tools/import_pindefs.py --all --summary        # counts, computed

This deliberately does **not** write `webui/boards/*.json`. Those files are
another ticket's to edit, and the report carries the pad number so the join
can be made on it rather than on label order.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import pathlib
import re
import subprocess
import sys
import typing

REPO = pathlib.Path(__file__).resolve().parents[1]
BSP_DIR = REPO / "third_party" / "bsp"
BOARDS_DIR = REPO / "webui" / "boards"


class PindefError(Exception):
    """A board-support package could not be turned into a label -> pin map."""


# --------------------------------------------------------------------------
# What a pin is
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ChipPin:
    """One pin of the MCU, as the chip's own documentation names it.

    `name` is the answer: `GPIO0`, `P1.11`, `PA02`, `PC0`.

    `index` is a flat integer, and is present only where the chip's own vendor
    publishes one. RP2040, RP2350 and the ESP32 parts number their GPIOs flat.
    The nRF52840 Arduino core publishes the 32-per-port encoding its own API
    takes. SAMD21, EFR32MG24 and the nRF54L parts have no flat numbering at
    all -- an nRF54L15's P0 is five pins wide, so 32-per-port arithmetic would
    produce a number appearing in no Nordic document -- and there `index`
    stays None rather than being invented.
    """

    name: str
    index: int | None = None


PinNaming = typing.Callable[[str, int], ChipPin]

_GPIO_BANK = re.compile(r"^gpio(\d+)$")
_PORT_LETTER = re.compile(r"^(?:gpio|port)([a-z])$")


def flat_gpio(controller: str, offset: int) -> ChipPin:
    """RP2040, RP2350, ESP32: one flat GPIO space, 32 per Zephyr bank.

    `&gpio0 26` is GPIO26; `&gpio1 11` on an ESP32-S3 is GPIO43, which is
    exactly what arduino-esp32 writes for `D6`.
    """
    bank = _GPIO_BANK.match(controller)
    if not bank:
        raise PindefError(f"expected a numbered gpio controller, got {controller!r}")
    number = int(bank.group(1)) * 32 + offset
    return ChipPin(f"GPIO{number}", number)


def nordic_flat_pin(controller: str, offset: int) -> ChipPin:
    """nRF52840: `&gpio1 11` is P1.11, and its Arduino core calls that pin 43."""
    bank = _GPIO_BANK.match(controller)
    if not bank:
        raise PindefError(f"expected a numbered gpio controller, got {controller!r}")
    port = int(bank.group(1))
    return ChipPin(f"P{port}.{offset:02d}", port * 32 + offset)


def nordic_port_pin(controller: str, offset: int) -> ChipPin:
    """nRF54L15 and nRF54LM20A: `&gpio2 8` is P2.08, and there it stops.

    No flat index. These parts' ports are not 32 pins wide -- P0 on an
    nRF54L15 has five -- so the arithmetic that is right for the nRF52840
    would be a fabrication here.
    """
    bank = _GPIO_BANK.match(controller)
    if not bank:
        raise PindefError(f"expected a numbered gpio controller, got {controller!r}")
    return ChipPin(f"P{int(bank.group(1))}.{offset:02d}")


def microchip_port_pin(controller: str, offset: int) -> ChipPin:
    """SAMD21: `&porta 2` is PA02, zero-padded as Microchip writes it."""
    port = _PORT_LETTER.match(controller)
    if not port:
        raise PindefError(f"expected a lettered port controller, got {controller!r}")
    return ChipPin(f"P{port.group(1).upper()}{offset:02d}")


def silabs_port_pin(controller: str, offset: int) -> ChipPin:
    """EFR32MG24: `&gpioc 0` is PC0, unpadded as Silicon Labs writes it."""
    port = _PORT_LETTER.match(controller)
    if not port:
        raise PindefError(f"expected a lettered port controller, got {controller!r}")
    return ChipPin(f"P{port.group(1).upper()}{offset}")


# --------------------------------------------------------------------------
# Reading Zephyr
# --------------------------------------------------------------------------

#: `gpio-map-mask` and `gpio-map-pass-thru` are not matched: each is followed
#: by `-`, not by `=`, so the first hit is the nexus itself.
_GPIO_MAP = re.compile(r"gpio-map\s*=\s*(.*?);", re.S)

#: `<0 0 &gpio0 26 0>,  /* D0 */` -- cell, flags, controller, offset, flags,
#: and the trailing comment each row is annotated with.
_MAP_ENTRY = re.compile(
    r"<\s*(\d+)\s+\d+\s+&([A-Za-z0-9_]+)\s+(\d+)\s+\w+\s*>\s*[,;]?"
    r"(?:[ \t]*/\*\s*(\S+)[^*]*\*/)?"
)


def read_zephyr_connector(texts: tuple[str, ...], *, naming: PinNaming) -> dict[str, ChipPin]:
    """Read a `seeed_xiao_connector.dtsi` gpio nexus into label -> pin.

    The `seeed,xiao-gpio` binding makes the first cell the XIAO connector
    index, so `D<cell>` is definitional rather than read out of the comment.
    The comment is still checked against it: every board file annotates every
    row, and a file disagreeing with itself is worth stopping on.
    """
    (text,) = texts
    block = _GPIO_MAP.search(text)
    if not block:
        raise PindefError(
            f"no `gpio-map = ...;` in a {len(text)}-byte connector file; "
            f"it starts {text[:80]!r}"
        )
    pins: dict[str, ChipPin] = {}
    for cell, controller, offset, comment in _MAP_ENTRY.findall(block.group(1)):
        label = f"D{cell}"
        if comment and comment != label:
            raise PindefError(
                f"connector cell {cell} is commented {comment!r}; the "
                f"seeed,xiao-gpio binding makes cell 0 the D number, so this "
                f"file disagrees with itself"
            )
        pins[label] = naming(controller, int(offset))
    if not pins:
        raise PindefError(f"gpio-map parsed to no entries: {block.group(1)[:120]!r}")
    return pins


# --------------------------------------------------------------------------
# Reading Arduino cores
# --------------------------------------------------------------------------

_C_DEFINE = re.compile(
    r"^[ \t]*#define[ \t]+([A-Za-z_]\w*)[ \t]+\(?\s*(\d+)\s*[uUlL]*\s*\)?[ \t]*(?://.*)?$",
    re.M,
)
_C_CONST = re.compile(
    r"^[ \t]*static[ \t]+const[ \t]+uint8_t[ \t]+([A-Za-z_]\w*)\s*=\s*"
    r"\(?\s*(\d+)\s*[uUlL]*\s*\)?\s*;",
    re.M,
)

_D_LABEL = re.compile(r"^D\d+$")


def read_c_pin_constants(text: str) -> dict[str, int]:
    """Every integer pin constant in a `pins_arduino.h` or `variant.h`.

    The two spellings in use are `#define D0 (0u)` and
    `static const uint8_t D0 = (26u);`. A constant defined in terms of another
    constant -- `#define PIN_LED (LED_RED)` -- is not resolved and not
    returned; nothing this tool needs is written that way.
    """
    found: dict[str, int] = {}
    for pattern in (_C_DEFINE, _C_CONST):
        for name, value in pattern.findall(text):
            found.setdefault(name, int(value))
    return found


def select_labels(constants: dict[str, int], extras: tuple[str, ...]) -> dict[str, int]:
    """Keep `D<n>`, plus exactly the extras a board's registry entry names.

    The module docstring argues why this is an allowlist and not a sweep:
    `PIN_VBAT` on a XIAO nRF52840 is the ADC that senses the battery pad, not
    the pad.
    """
    wanted = {label: value for label, value in constants.items() if _D_LABEL.match(label)}
    for extra in extras:
        for spelling in (extra, f"PIN_{extra}"):
            if spelling in constants:
                wanted[extra] = constants[spelling]
                break
        else:
            raise PindefError(
                f"{extra!r} is registered as an extra label, but the file "
                f"defines neither it nor PIN_{extra}. It defines "
                f"{sorted(constants)[:12]}..."
            )
    if not wanted:
        raise PindefError(
            f"no D<n> constants among the {len(constants)} found: "
            f"{sorted(constants)[:12]}..."
        )
    return wanted


def read_flat_pins(texts: tuple[str, ...], *, extras: tuple[str, ...] = ()) -> dict[str, ChipPin]:
    """arduino-pico and arduino-esp32: the Arduino pin number *is* the GPIO."""
    (text,) = texts
    return {
        label: ChipPin(f"GPIO{number}", number)
        for label, number in select_labels(read_c_pin_constants(text), extras).items()
    }


def read_indexed_pins(
    texts: tuple[str, ...],
    *,
    read_table: typing.Callable[[str], tuple[ChipPin, ...]],
    extras: tuple[str, ...] = (),
) -> dict[str, ChipPin]:
    """Cores where `D0 = 0` indexes the core's own pin table, not a GPIO.

    Three packages do this and each spells the table differently --
    `g_ADigitalPinMap[]`, `gPinNames[]`, `g_APinDescription[]` -- but the
    indexing is identical, which is why the table reader is a parameter and
    this function is not written out three times.
    """
    labels_text, table_text = texts
    table = read_table(table_text)
    pins: dict[str, ChipPin] = {}
    for label, index in select_labels(read_c_pin_constants(labels_text), extras).items():
        if index >= len(table):
            raise PindefError(f"{label} = {index} indexes past a {len(table)}-entry pin table")
        pins[label] = table[index]
    return pins


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
#: `} ;` with a space is how seeed-samd's variant.cpp closes its array, so the
#: terminator is matched rather than searched for as the literal two bytes.
_ARRAY_END = re.compile(r"\}\s*;")


def _array_body(text: str, declaration: str) -> str:
    """The comment-free contents of a C array initialiser, outer braces excluded."""
    start = text.find(declaration)
    if start < 0:
        raise PindefError(f"no {declaration!r} in a {len(text)}-byte source")
    opened = text.find("{", start)
    end = _ARRAY_END.search(text, opened + 1) if opened >= 0 else None
    if opened < 0 or end is None:
        raise PindefError(
            f"{declaration!r} at offset {start} has no brace-and-semicolon "
            f"body: {text[start:start + 80]!r}"
        )
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text[opened + 1 : end.start()]))


def _entries(body: str) -> list[str]:
    return [token.strip() for token in body.split(",") if token.strip()]


def read_nrf_pin_map(text: str) -> tuple[ChipPin, ...]:
    """`g_ADigitalPinMap[]`: Arduino pin -> nRF absolute pin, 32 per port.

    43 is P1.11. The file's own comments say so too, and are ignored.
    """
    pins = []
    for position, token in enumerate(_entries(_array_body(text, "g_ADigitalPinMap[]"))):
        if not token.isdigit():
            raise PindefError(f"g_ADigitalPinMap entry {position} is {token!r}, not a number")
        number = int(token)
        pins.append(ChipPin(f"P{number // 32}.{number % 32:02d}", number))
    if not pins:
        raise PindefError("g_ADigitalPinMap parsed to no entries")
    return tuple(pins)


_SILABS_PIN = re.compile(r"^P[A-Z]\d+$")


def read_silabs_pin_names(text: str) -> tuple[ChipPin, ...]:
    """`gPinNames[]`: Arduino pin -> an EFR32 port pin, written `PC0`."""
    pins = []
    for position, token in enumerate(_entries(_array_body(text, "gPinNames[]"))):
        if not _SILABS_PIN.match(token):
            raise PindefError(f"gPinNames entry {position} is {token!r}, not a PXn port pin")
        pins.append(ChipPin(token))
    if not pins:
        raise PindefError("gPinNames parsed to no entries")
    return tuple(pins)


_SAMD_ENTRY = re.compile(r"\{([^{}]*)\}")
_SAMD_PORT = re.compile(r"^\s*PORT([A-Z])\s*,\s*(\d+)\s*,")


def read_samd_pin_description(text: str) -> tuple[ChipPin, ...]:
    """`g_APinDescription[]`: Arduino pin -> `{ PORTA, 2, ... }`, written PA02.

    Every brace group must parse. A `NOT_A_PORT` row skipped quietly would
    shift every pin after it by one, which reads as success right up until the
    wire is in the wrong place.
    """
    pins = []
    body = _array_body(text, "g_APinDescription[]")
    for position, group in enumerate(_SAMD_ENTRY.findall(body)):
        entry = _SAMD_PORT.match(group)
        if not entry:
            raise PindefError(
                f"g_APinDescription entry {position} does not start with a "
                f"`PORTx, n,` pair: {group.strip()[:60]!r}"
            )
        pins.append(ChipPin(f"P{entry.group(1)}{int(entry.group(2)):02d}"))
    if not pins:
        raise PindefError(f"g_APinDescription parsed to no entries: {body[:120]!r}")
    return tuple(pins)


# --------------------------------------------------------------------------
# The registry: which packages publish which board
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Package:
    """A board-support package checkout under `third_party/bsp/<name>`."""

    name: str
    repository: str
    sparse: tuple[str, ...]
    licence: str


@dataclasses.dataclass(frozen=True)
class Source:
    """One package's files for one board, and the reader that understands them."""

    package: str
    paths: tuple[str, ...]
    read: typing.Callable[[tuple[str, ...]], dict[str, ChipPin]]


@dataclasses.dataclass(frozen=True)
class Board:
    """A file in `webui/boards/`, its MCU, and everywhere its pins are published."""

    chip: str
    sources: tuple[Source, ...]


PACKAGES = {
    package.name: package
    for package in (
        Package(
            "zephyr",
            "https://github.com/zephyrproject-rtos/zephyr.git",
            ("boards/seeed",),
            "Apache-2.0",
        ),
        Package(
            "arduino-pico",
            "https://github.com/earlephilhower/arduino-pico.git",
            ("variants",),
            "LGPL-2.1-or-later",
        ),
        Package(
            "arduino-esp32",
            "https://github.com/espressif/arduino-esp32.git",
            ("variants",),
            "LGPL-2.1-or-later",
        ),
        Package(
            "seeed-samd",
            "https://github.com/Seeed-Studio/ArduinoCore-samd.git",
            ("variants",),
            # No LICENSE at the repository root; the variant files carry the
            # Arduino LLC LGPL-2.1-or-later notice verbatim in their headers.
            "LGPL-2.1-or-later (per-file header)",
        ),
        Package(
            "seeed-nrf52",
            "https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino.git",
            ("variants",),
            "LGPL-2.1-or-later",
        ),
        Package(
            "silabs-arduino",
            "https://github.com/SiliconLabs/arduino.git",
            ("variants",),
            "MIT for Silicon Labs code, LGPL-2.1-or-later where Arduino-derived",
        ),
    )
}


def zephyr_connector(board: str, naming: PinNaming) -> Source:
    return Source(
        "zephyr",
        (f"boards/seeed/{board}/seeed_xiao_connector.dtsi",),
        functools.partial(read_zephyr_connector, naming=naming),
    )


def arduino_flat(package: str, variant: str) -> Source:
    return Source(package, (f"variants/{variant}/pins_arduino.h",), read_flat_pins)


def arduino_indexed(
    package: str,
    labels: str,
    table: str,
    read_table: typing.Callable[[str], tuple[ChipPin, ...]],
    extras: tuple[str, ...] = (),
) -> Source:
    return Source(
        package,
        (labels, table),
        functools.partial(read_indexed_pins, read_table=read_table, extras=extras),
    )


# DIP and SMD are two footprints of one board, so they take the same sources.
# The SMD files carry more pads, not different pins.
_RP2040 = (
    zephyr_connector("xiao_rp2040", flat_gpio),
    arduino_flat("arduino-pico", "seeed_xiao_rp2040"),
)
_RP2350 = (
    zephyr_connector("xiao_rp2350", flat_gpio),
    arduino_flat("arduino-pico", "seeed_xiao_rp2350"),
)
_ESP32C3 = (
    zephyr_connector("xiao_esp32c3", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C3"),
)
_ESP32C5 = (
    zephyr_connector("xiao_esp32c5", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C5"),
)
_ESP32C6 = (
    zephyr_connector("xiao_esp32c6", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C6"),
)
_ESP32S3 = (
    zephyr_connector("xiao_esp32s3", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32S3"),
)
_MG24 = (
    zephyr_connector("xiao_mg24", silabs_port_pin),
    arduino_indexed(
        "silabs-arduino",
        "variants/xiao_mg24/pins_arduino.h",
        "variants/xiao_mg24/arduino_variant.cpp",
        read_silabs_pin_names,
    ),
)
# Zephyr still calls the SAMD21 XIAO by its original name, `seeeduino_xiao`.
_SAMD21 = (
    zephyr_connector("seeeduino_xiao", microchip_port_pin),
    arduino_indexed(
        "seeed-samd",
        "variants/XIAO_m0/variant.h",
        "variants/XIAO_m0/variant.cpp",
        read_samd_pin_description,
    ),
)
# Zephyr calls the nRF52840 XIAO `xiao_ble`. NFC1 and NFC2 are opted in by
# name: they really are P0.09 and P0.10, the nRF52840's NFC antenna pins.
_NRF52840 = (
    zephyr_connector("xiao_ble", nordic_flat_pin),
    arduino_indexed(
        "seeed-nrf52",
        "variants/Seeed_XIAO_nRF52840/variant.h",
        "variants/Seeed_XIAO_nRF52840/variant.cpp",
        read_nrf_pin_map,
        extras=("NFC1", "NFC2"),
    ),
)
# One source each: Nordic ships these boards inside nRF Connect rather than as
# an Arduino core, and Zephyr upstream already carries the same connector node.
_NRF54L15 = (zephyr_connector("xiao_nrf54l15", nordic_port_pin),)
_NRF54LM20A = (zephyr_connector("xiao_nrf54lm20a", nordic_port_pin),)

BOARDS = {
    "XIAO-ESP32-C3-DIP": Board("ESP32-C3", _ESP32C3),
    "XIAO-ESP32-C3-DIP-SMD": Board("ESP32-C3", _ESP32C3),
    "XIAO-ESP32-C3-SMD": Board("ESP32-C3", _ESP32C3),
    "XIAO-ESP32-C5-DIP": Board("ESP32-C5", _ESP32C5),
    "XIAO-ESP32-C5-SMD": Board("ESP32-C5", _ESP32C5),
    "XIAO-ESP32-C6-DIP": Board("ESP32-C6", _ESP32C6),
    "XIAO-ESP32-C6-SMD": Board("ESP32-C6", _ESP32C6),
    "XIAO-ESP32-S3-DIP": Board("ESP32-S3", _ESP32S3),
    "XIAO-ESP32-S3-SMD": Board("ESP32-S3", _ESP32S3),
    "XIAO-ESP32-S3-SMD_PAD": Board("ESP32-S3", _ESP32S3),
    "XIAO-MG24-DIP": Board("EFR32MG24", _MG24),
    "XIAO-MG24-SMD": Board("EFR32MG24", _MG24),
    "XIAO-RP2040-DIP": Board("RP2040", _RP2040),
    "XIAO-RP2040-SMD": Board("RP2040", _RP2040),
    "XIAO-RP2350-DIP": Board("RP2350", _RP2350),
    "XIAO-RP2350-SMD": Board("RP2350", _RP2350),
    "XIAO-SAMD21-DIP": Board("SAMD21", _SAMD21),
    "XIAO-SAMD21-SMD": Board("SAMD21", _SAMD21),
    # Nobody has published this one. Zephyr has no xiao_stm32c5 board and
    # Seeed has released no core for it, so every pad stays null and the
    # report says why rather than the board going missing from the run.
    "XIAO-XIAO STM32C5-SMD": Board("STM32C5", ()),
    "XIAO-nRF52840-DIP": Board("nRF52840", _NRF52840),
    "XIAO-nRF52840-SMD": Board("nRF52840", _NRF52840),
    "XIAO-nRF54LM20A-DIP": Board("nRF54LM20A", _NRF54LM20A),
    "XIAO-nRF54LM20A-SMD": Board("nRF54LM20A", _NRF54LM20A),
    "XIAO-nRF54l15-DIP": Board("nRF54L15", _NRF54L15),
    "XIAO-nRF54l15-SMD": Board("nRF54L15", _NRF54L15),
}


# --------------------------------------------------------------------------
# Resolving a board
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Claim:
    """One package's answer for one label, and the file that gave it."""

    pin: ChipPin
    #: `zephyr boards/seeed/xiao_rp2040/seeed_xiao_connector.dtsi @ 0a2e408`,
    #: in the spirit of the `derivation` field already naming a footprint.
    source: str


@dataclasses.dataclass(frozen=True)
class Resolved:
    """A pad on the board, and everything the packages say about its label."""

    pad: str
    label: str
    #: The alternative a package recognised. `D9/BOOT` is one pad silkscreened
    #: twice, and it is `D9` that the packages define.
    matched: str | None
    claims: tuple[Claim, ...]


def alternatives(label: str) -> tuple[str, ...]:
    """`D9/BOOT` is one pad wearing two names; try each of them."""
    return tuple(part.strip() for part in label.split("/") if part.strip())


def agree(claims: tuple[Claim, ...]) -> ChipPin | None:
    """The one pin every claim names, or None when they do not all name it.

    A claim naming a pin without numbering it does not contradict one that
    numbers it: Zephyr's `&gpio1 11` says P1.11 and stops, while the nRF52840
    Arduino core's table says P1.11 *and* calls it 43. So names must be equal,
    and indices must be equal or absent.
    """
    if not claims:
        return None
    names = {claim.pin.name for claim in claims}
    if len(names) != 1:
        return None
    indices = {claim.pin.index for claim in claims if claim.pin.index is not None}
    if len(indices) > 1:
        return None
    return ChipPin(names.pop(), indices.pop() if indices else None)


def revision(checkout: pathlib.Path) -> str:
    """The short commit a package checkout is at, so a claim can be re-read."""
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PindefError(
            f"cannot read the revision of {checkout}: git exited "
            f"{result.returncode}, {result.stderr.strip()!r}"
        )
    return result.stdout.strip()


def published_pins(board: Board, bsp_dir: pathlib.Path) -> dict[str, list[Claim]]:
    """Every claim every package covering this board makes, keyed by label."""
    claims: dict[str, list[Claim]] = {}
    for source in board.sources:
        checkout = bsp_dir / source.package
        if not checkout.is_dir():
            raise PindefError(
                f"{checkout} is missing; run "
                f"`python tools/import_pindefs.py --fetch` to clone "
                f"{PACKAGES[source.package].repository}"
            )
        texts = []
        for relative in source.paths:
            path = checkout / relative
            if not path.is_file():
                raise PindefError(
                    f"{path} is missing from the {source.package} checkout at "
                    f"{revision(checkout)}; the sparse-checkout may be stale, "
                    f"or the package may have renamed the variant"
                )
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        # Every path, not just the first: on the nRF52840, SAMD21 and MG24
        # the labels are in one file and the pin table in another, and the
        # answer is not checkable without both.
        citation = f"{source.package} {', '.join(source.paths)} @ {revision(checkout)}"
        for label, pin in source.read(tuple(texts)).items():
            claims.setdefault(label, []).append(Claim(pin, citation))
    return claims


def resolve(name: str, bsp_dir: pathlib.Path = BSP_DIR) -> list[Resolved]:
    """Join one board file's pads against what the packages publish."""
    if name not in BOARDS:
        raise PindefError(f"no registry entry for {name!r}. Known: {sorted(BOARDS)}")
    path = BOARDS_DIR / f"{name}.json"
    if not path.is_file():
        raise PindefError(f"{path} does not exist, but {name!r} is in the registry")
    pads = json.loads(path.read_text(encoding="utf-8"))["pads"]
    claims = published_pins(BOARDS[name], bsp_dir)

    resolved = []
    for pad in pads:
        matched = next((alt for alt in alternatives(pad["label"]) if alt in claims), None)
        resolved.append(
            Resolved(
                pad=pad["pad"],
                label=pad["label"],
                matched=matched,
                claims=tuple(claims[matched]) if matched else (),
            )
        )
    return resolved


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

DERIVATION = (
    "Generated by tools/import_pindefs.py from the board-support packages "
    "named in each pad's `sources`, at the revisions in `packages`. Nothing "
    "was inferred from the CAD, the silkscreen or a pinout image: a label "
    "resolves only when a package states it, and every pad below carries the "
    "file that stated it."
)

NOT_PUBLISHED = "no board-support package covering this board defines this label"
DISPUTED = "the packages disagree; recorded rather than averaged, so the pad stays null"


def pad_report(entry: Resolved) -> dict:
    """One pad, as JSON: the answer, or precisely why there is not one."""
    pin = agree(entry.claims)
    report = {
        "pad": entry.pad,
        "label": entry.label,
        "matched": entry.matched,
        "chip_pin": pin.name if pin else None,
        "index": pin.index if pin else None,
        "sources": [claim.source for claim in entry.claims],
    }
    if pin:
        return report
    if not entry.claims:
        report["reason"] = NOT_PUBLISHED
        return report
    rivals: dict[str, list[str]] = {}
    for claim in entry.claims:
        rivals.setdefault(claim.pin.name, []).append(claim.source)
    report["reason"] = DISPUTED
    report["disputed"] = [
        {"chip_pin": name, "sources": sources} for name, sources in sorted(rivals.items())
    ]
    return report


def board_report(name: str, bsp_dir: pathlib.Path = BSP_DIR) -> dict:
    """Everything known about one board's pads, and where each claim came from."""
    board = BOARDS[name]
    entries = resolve(name, bsp_dir)
    pads = [pad_report(entry) for entry in entries]
    packages = sorted({source.package for source in board.sources})
    return {
        "board": name,
        "chip": board.chip,
        "generated_by": "tools/import_pindefs.py",
        "derivation": DERIVATION,
        "packages": [
            {
                "name": package,
                "repository": PACKAGES[package].repository,
                "revision": revision(bsp_dir / package),
                "licence": PACKAGES[package].licence,
            }
            for package in packages
        ],
        "resolved": sum(1 for pad in pads if pad["chip_pin"]),
        "unresolved": sum(1 for pad in pads if not pad["chip_pin"]),
        "disputed": sum(1 for pad in pads if "disputed" in pad),
        "pads": pads,
    }


def full_report(bsp_dir: pathlib.Path = BSP_DIR) -> dict:
    """Every board in `webui/boards/`, including the ones with no registry entry."""
    boards = [board_report(name, bsp_dir) for name in sorted(BOARDS)]
    unregistered = sorted(
        path.stem for path in BOARDS_DIR.glob("*.json") if path.stem not in BOARDS
    )
    return {
        "generated_by": "tools/import_pindefs.py",
        "derivation": DERIVATION,
        "boards": boards,
        # Named, not dropped. The Arduino Uno is here because its pins come
        # from webui/pinmap.py, measured out of PICSimLab's own board.svg, and
        # no board-support package is involved.
        "not_in_registry": unregistered,
        "totals": totals(boards),
    }


def totals(boards: list[dict]) -> dict:
    """The counts, added up. CLAUDE.md: run the generator, do not keep a list."""
    return {
        "boards": len(boards),
        "pads": sum(len(board["pads"]) for board in boards),
        "resolved": sum(board["resolved"] for board in boards),
        "unresolved": sum(board["unresolved"] for board in boards),
        "disputed": sum(board["disputed"] for board in boards),
    }


# --------------------------------------------------------------------------
# Fetching, not vendoring
# --------------------------------------------------------------------------


def _git(*args: str) -> None:
    result = subprocess.run(["git", *args], check=False)
    if result.returncode != 0:
        raise PindefError(f"git {' '.join(args)} exited {result.returncode}")


def fetch(package: Package, bsp_dir: pathlib.Path = BSP_DIR) -> pathlib.Path:
    """Clone or update one package, blobless and sparse.

    arduino-esp32 is ~1 GB checked out whole and zephyr rather more; between
    them the six packages here need eleven small text files. `--filter=blob:none`
    with a cone sparse-checkout brings ~70 MB instead, and the same argument
    `tools/get_seeed_hardware.sh` makes about the vendor CAD applies: size
    decides, not licence.
    """
    destination = bsp_dir / package.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not (destination / ".git").is_dir():
        _git(
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--depth",
            "1",
            package.repository,
            str(destination),
        )
        _git("-C", str(destination), "sparse-checkout", "init", "--cone")
    _git("-C", str(destination), "sparse-checkout", "set", *package.sparse)
    _git("-C", str(destination), "checkout")

    # A silent empty fetch would make every board report zero resolved pads,
    # which reads exactly like a board nobody has published pins for.
    present = [path for path in package.sparse if (destination / path).is_dir()]
    if len(present) != len(package.sparse):
        raise PindefError(
            f"{destination} is missing {sorted(set(package.sparse) - set(present))} "
            f"after a sparse checkout of {package.sparse}"
        )
    return destination


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def describe_registry() -> str:
    """Which packages cover which board, and which board no package covers."""
    lines = []
    for name in sorted(BOARDS):
        board = BOARDS[name]
        sources = ", ".join(f"{s.package}:{s.paths[0]}" for s in board.sources)
        lines.append(f"{name:24s} {board.chip:11s} {sources or '(no package publishes this board)'}")
    return "\n".join(lines)


def summarise(boards: list[dict], not_in_registry: list[str]) -> str:
    """One line per board, then the totals added up."""
    lines = [
        f"{'board':24s} {'chip':11s} {'pads':>5s} {'resolved':>9s} "
        f"{'null':>5s} {'disputed':>9s}"
    ]
    for board in boards:
        lines.append(
            f"{board['board']:24s} {board['chip']:11s} {len(board['pads']):5d} "
            f"{board['resolved']:9d} {board['unresolved']:5d} {board['disputed']:9d}"
        )
    counts = totals(boards)
    lines.append(
        f"{'TOTAL':24s} {'':11s} {counts['pads']:5d} {counts['resolved']:9d} "
        f"{counts['unresolved']:5d} {counts['disputed']:9d}"
    )
    if not_in_registry:
        lines.append(f"not in the registry: {', '.join(not_in_registry)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract label -> chip pin from board-support packages.",
        epilog="Writes a report. It never edits webui/boards/*.json.",
    )
    parser.add_argument("board", nargs="?", help="a board in webui/boards/")
    parser.add_argument("--fetch", action="store_true", help="clone or update every package")
    parser.add_argument("--list", action="store_true", help="the registry, one board per line")
    parser.add_argument("--all", action="store_true", help="report every registered board")
    parser.add_argument("--summary", action="store_true", help="counts instead of JSON")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="write JSON here, not to stdout")
    args = parser.parse_args(argv)

    if args.fetch:
        for package in PACKAGES.values():
            print(f"--- {package.name}: {package.repository}")
            fetch(package)
        for package in PACKAGES.values():
            print(f"{package.name:16s} {revision(BSP_DIR / package.name)}  {package.licence}")
        return 0

    if args.list:
        print(describe_registry())
        return 0

    if args.all:
        report = full_report()
    elif args.board:
        report = board_report(args.board)
    else:
        parser.error("give a board name, or --all, or --list, or --fetch")

    if args.summary:
        if args.all:
            print(summarise(report["boards"], report["not_in_registry"]))
        else:
            print(summarise([report], []))
        return 0

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PindefError as error:
        print(f"import_pindefs: {error}", file=sys.stderr)
        sys.exit(1)
