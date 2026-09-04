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

Every generated board file used to repeat the consequence in its own
`assumption` field -- *a pad with pin null draws and refuses a wire* -- and
since OH-160 this tool writes those fields itself, so what they now say is
`assumption_for` below. This is the other half of that join. A footprint knows
pad 7 sits at 30.4 x 20.8 and is silkscreened `D6`. It cannot know that `D6`
reaches GPIO0 on a XIAO RP2040 and GPIO21 on a XIAO ESP32-C3 -- same label,
same connector position, different wire.

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
`tools/get_board_sources.py` makes for the CAD -- and which
`tools/get_seeed_hardware.sh` argued for before it was retired. What is extracted is a pin
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

## Where the answer goes (OH-160)

From OH-26 (2026-08-25) to OH-160 the report above was written and nothing
read it: `webui/api.py` fills a pad's `chip_pin` from the board MODULE's
`PIN_NAMES`, and only `atmega328p.py` and `samd21.py` had one. So the same
resolution now lands in two places, both generated, and a test holds them
equal:

**The board module.** `--write-headers` rewrites a `HEADER` block between two
markers in every `webui/boards/<chip>.py` that carries them -- label -> GPIO
number, with the packages and revisions it was read from in the block's own
comment. The module derives `PIN_NAMES` from it and reads levels through it,
which is the shape `samd21.py` established by hand: one table, so a label
cannot mean one pin in a register read and another in a tooltip. The block is
emitted only for chips whose vendor publishes a flat number; SAMD21's `PA02`
has none, so its module keeps its own `(group, bit)` table and this generator
refuses to write one.

**The board file.** `--write-boards` adds `chip_pin` and `chip_index` to every
pad of every registered `webui/boards/*.json`, a `why_null` on every pad that
resolves to nothing, and a `pindefs` object naming the packages. **`pin` stays
null**, because that field means something else: `webui/pinmap.py` defines it
as the rcontrol pin index of a PICSimLab board, 1..99, and no PICSimLab board
exists for any XIAO. Writing a GPIO number there would be a different fact in
a field that already has one -- and on a XIAO RP2040 `D6` is GPIO0, which that
field's own validator refuses.

`tools/import_board.py` regenerates the geometry from the vendor's CAD and
writes `pin: null` and a fresh `assumption` of its own; run `--write-boards`
after it, and `test_the_committed_board_files_match_the_generator` names the
file that was not.

## Usage

    python tools/import_pindefs.py --fetch                # ~70 MB, git-ignored
    python tools/import_pindefs.py --list                 # boards and sources
    python tools/import_pindefs.py XIAO-RP2040-DIP        # one board's report
    python tools/import_pindefs.py --all -o pindefs.json  # every board
    python tools/import_pindefs.py --all --summary        # counts, computed
    python tools/import_pindefs.py --emit-header ESP32-C3 # the module block
    python tools/import_pindefs.py --write-headers        # into every marked module
    python tools/import_pindefs.py --write-boards         # into every board file
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
import textwrap
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
        # Three spellings, because the packages use all three for one thing:
        # seeed-nrf52 writes `PIN_NFC1`, arduino-pico `PIN_LED`, and
        # arduino-esp32 `LED_BUILTIN` -- Arduino's own name for the board LED,
        # which arduino-pico defines too but as an alias of `PIN_LED`, and an
        # alias is not a number, so on that core it is the `PIN_` spelling
        # that carries the value.
        spellings = (extra, f"PIN_{extra}", f"{extra}_BUILTIN")
        for spelling in spellings:
            if spelling in constants:
                wanted[extra] = constants[spelling]
                break
        else:
            raise PindefError(
                f"{extra!r} is registered as an extra label, but the file "
                f"defines none of {list(spellings)} as an integer. It defines "
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
    #: Labels with a pin and no pad: the board's own LED, which is on the
    #: board rather than on the header and so has no coordinate in the pad
    #: map. Resolved from the same packages as the pads -- the label must be
    #: opted in as a source's `extras` too, or no package will claim it --
    #: reported under `on_board`, and emitted into the module's `HEADER`, so
    #: that a stock Blink moves something a person can see. `samd21.py` made
    #: the same choice by hand and says why at its `HEADER`.
    on_board: tuple[str, ...] = ()


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


def arduino_flat(package: str, variant: str, extras: tuple[str, ...] = ()) -> Source:
    return Source(
        package,
        (f"variants/{variant}/pins_arduino.h",),
        functools.partial(read_flat_pins, extras=extras),
    )


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
#
# `LED` is opted in where the Arduino variant defines the board's own LED
# with a number: `PIN_LED (17u)` on the XIAO RP2040, `LED_BUILTIN = 27` on
# the C5 and `= 15` on the C6, each in the file named below. The XIAO
# ESP32-C3's variant defines no LED at all -- `webui/boards/esp32c3.py`
# measured that -- so it opts nothing in, and the Zephyr connector files
# never claim one because a connector describes the header. It is an
# `on_board` label on the Board rows, not a pad: see `Board.on_board`.
_RP2040 = (
    zephyr_connector("xiao_rp2040", flat_gpio),
    arduino_flat("arduino-pico", "seeed_xiao_rp2040", extras=("LED",)),
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
    arduino_flat("arduino-esp32", "XIAO_ESP32C5", extras=("LED",)),
)
_ESP32C6 = (
    zephyr_connector("xiao_esp32c6", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C6", extras=("LED",)),
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
    "XIAO-ESP32-C5-DIP": Board("ESP32-C5", _ESP32C5, on_board=("LED",)),
    "XIAO-ESP32-C5-SMD": Board("ESP32-C5", _ESP32C5, on_board=("LED",)),
    "XIAO-ESP32-C6-DIP": Board("ESP32-C6", _ESP32C6, on_board=("LED",)),
    "XIAO-ESP32-C6-SMD": Board("ESP32-C6", _ESP32C6, on_board=("LED",)),
    "XIAO-ESP32-S3-DIP": Board("ESP32-S3", _ESP32S3),
    "XIAO-ESP32-S3-SMD": Board("ESP32-S3", _ESP32S3),
    "XIAO-ESP32-S3-SMD_PAD": Board("ESP32-S3", _ESP32S3),
    "XIAO-MG24-DIP": Board("EFR32MG24", _MG24),
    "XIAO-MG24-SMD": Board("EFR32MG24", _MG24),
    "XIAO-RP2040-DIP": Board("RP2040", _RP2040, on_board=("LED",)),
    "XIAO-RP2040-SMD": Board("RP2040", _RP2040, on_board=("LED",)),
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

    #: The footprint's pad number, or None for an `on_board` pin, which has
    #: a label and a package's claim and nowhere on the board to be.
    pad: str | None
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


def board_path(name: str, boards_dir: pathlib.Path = BOARDS_DIR) -> pathlib.Path:
    """The board file a registry name stands for, or an error naming both."""
    if name not in BOARDS:
        raise PindefError(f"no registry entry for {name!r}. Known: {sorted(BOARDS)}")
    path = boards_dir / f"{name}.json"
    if not path.is_file():
        raise PindefError(f"{path} does not exist, but {name!r} is in the registry")
    return path


def resolve(
    name: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> tuple[list[Resolved], list[Resolved]]:
    """Join one board file's pads against what the packages publish.

    Two lists: the pads, in the file's order, and then the board's `on_board`
    labels -- pins with no pad, so `pad` is None on those and `matched` is
    the label itself. Kept apart because a caller counting pads must not
    count the LED as one, and a caller drawing the LED has nowhere to put it.
    """
    pads = json.loads(board_path(name, boards_dir).read_text(encoding="utf-8"))["pads"]
    board = BOARDS[name]
    claims = published_pins(board, bsp_dir)

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
    on_board = [
        Resolved(
            pad=None,
            label=label,
            matched=label if label in claims else None,
            claims=tuple(claims.get(label, ())),
        )
        for label in board.on_board
    ]
    return resolved, on_board


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

#: The board FILE's version of the sentence: its pads carry no `sources`
#: list, so it points at the command that prints them instead.
BOARD_DERIVATION = (
    "Generated by tools/import_pindefs.py from the board-support packages in "
    "`packages`, at those revisions. Nothing was inferred from the CAD, the "
    "silkscreen or a pinout image: a label resolves only when every package "
    "covering the board that defines it names the same pin, and "
    "`python tools/import_pindefs.py <board>` prints the file that named it."
)

#: And for a board no package covers, where the sentence above would cite an
#: empty list as though something had been read from it.
BOARD_DERIVATION_UNCOVERED = (
    "Generated by tools/import_pindefs.py, which found no board-support package "
    "covering this board: `packages` is empty because there are none to name, "
    "not because none was read. Every pad's `chip_pin` is null and says so in "
    "its own `why_null`."
)

NOT_PUBLISHED = "no board-support package covering this board defines this label"
DISPUTED = "the packages disagree; recorded rather than averaged, so the pad stays null"

#: The reason on a board no package covers, which is a different fact from
#: `NOT_PUBLISHED` and reads identically if it is not told apart: "no package
#: covering this board defines this label" is vacuously true of all 35 pads of
#: the XIAO STM32C5 and hides that the count of packages covering it is zero.
#: OH-26 searched and found no Zephyr board and no Seeed core for that part.
NO_PACKAGE_AT_ALL = (
    "no board-support package covers this board at all, so no label on it "
    "resolves; this is a gap in what the vendor has published, not in this tool"
)


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


def board_report(
    name: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> dict:
    """Everything known about one board's pads, and where each claim came from.

    The counts are of pads. An `on_board` pin is listed under its own key and
    counted in neither `resolved` nor `unresolved`, because "11 of 14 pads
    resolve" is a sentence about the header and the LED is not on it.
    """
    board = BOARDS[name]
    entries, on_board = resolve(name, bsp_dir, boards_dir)
    pads = [pad_report(entry) for entry in entries]
    if not board.sources:
        # Every pad of this board is null for ONE reason, and it is not the
        # per-label one `pad_report` can see from a pad alone.
        for pad in pads:
            pad["reason"] = NO_PACKAGE_AT_ALL
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
        "on_board": [pad_report(entry) for entry in on_board],
    }


def full_report(
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> dict:
    """Every board in `webui/boards/`, including the ones with no registry entry."""
    boards = [board_report(name, bsp_dir, boards_dir) for name in sorted(BOARDS)]
    unregistered = sorted(
        path.stem for path in boards_dir.glob("*.json") if path.stem not in BOARDS
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
# The board module's table (OH-160)
# --------------------------------------------------------------------------

#: The two lines a board module carries so that this tool can find where its
#: `HEADER` goes. Both are matched whole; a module with one and not the other,
#: or with two of either, is refused rather than guessed at.
HEADER_BEGIN = (
    "# --- BEGIN HEADER: generated by "
    "`python tools/import_pindefs.py --write-headers`; do not edit by hand ---"
)
HEADER_END = "# --- END HEADER ---"

_D_NUMBER = re.compile(r"^D(\d+)$")


@dataclasses.dataclass(frozen=True)
class HeaderTable:
    """One chip's label -> pin table, and the files it was read out of."""

    chip: str
    #: The board files that contributed, so the block can name them.
    boards: tuple[str, ...]
    #: Label -> pin, in the order the block will print them: `D0` upward,
    #: then the on-board labels, then anything else in the order first seen.
    #: Keyed by the label the PACKAGES define -- `D9`, not the DIP's
    #: `D9/BOOT` -- because that is the name `pin_states` answers under and
    #: `webui.api.header_key` joins a pad label onto it.
    pins: dict[str, ChipPin]
    #: `zephyr boards/seeed/... @ 0a2e408`, one per package file, deduplicated.
    citations: tuple[str, ...]
    #: Labels with no pad, so the block can say which rows are not header.
    on_board: tuple[str, ...]


def _label_order(label: str) -> tuple[int, int]:
    number = _D_NUMBER.match(label)
    return (0, int(number.group(1))) if number else (1, 0)


def header_table(
    chip: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> HeaderTable:
    """The union of every registered board file of one chip, and one table.

    DIP and SMD are two footprints of one board, and the SMD file carries
    more pads: the C3's underside `D3/MTDI` is the same GPIO5 as its
    castellated `D3`. So the table is the union over the chip's files, keyed
    by the label the packages define -- and a label that two files send to
    two different pins is refused, because one chip has one table and a
    module cannot carry two.
    """
    names = tuple(name for name, board in sorted(BOARDS.items()) if board.chip == chip)
    if not names:
        raise PindefError(
            f"no registered board has chip {chip!r}; chips: "
            f"{sorted({board.chip for board in BOARDS.values()})}"
        )
    pins: dict[str, ChipPin] = {}
    first_seen: dict[str, str] = {}
    citations: list[str] = []
    on_board: list[str] = []
    for name in names:
        report = board_report(name, bsp_dir, boards_dir)
        for entry in report["pads"] + report["on_board"]:
            if entry["chip_pin"] is None:
                continue
            label = entry["matched"]
            pin = ChipPin(entry["chip_pin"], entry["index"])
            if label in pins and pins[label] != pin:
                raise PindefError(
                    f"{chip}: {label} is {pins[label].name} in {first_seen[label]} "
                    f"and {pin.name} in {name}; one chip has one table"
                )
            pins.setdefault(label, pin)
            first_seen.setdefault(label, name)
            for source in entry["sources"]:
                if source not in citations:
                    citations.append(source)
        for entry in report["on_board"]:
            if entry["chip_pin"] is not None and entry["matched"] not in on_board:
                on_board.append(entry["matched"])
    if not pins:
        raise PindefError(f"{chip}: no pad on {names} resolves to a pin; nothing to emit")
    ordered = dict(sorted(pins.items(), key=lambda item: _label_order(item[0])))
    return HeaderTable(chip, names, ordered, tuple(citations), tuple(on_board))


def render_header(table: HeaderTable) -> str:
    """The Python block a board module embeds, from `HEADER_BEGIN` to `HEADER_END`.

    Emitted only where every pin has a flat number. `SAMD21`'s `PA02` has
    none, and a module for such a chip keys its own table as `(group, bit)`
    the way `samd21.py` does; writing `"D0": None` into it would be a table
    that parses and answers nothing.
    """
    unnumbered = [label for label, pin in table.pins.items() if pin.index is None]
    if unnumbered:
        raise PindefError(
            f"{table.chip}: {unnumbered} name a chip pin with no flat number "
            f"({table.pins[unnumbered[0]].name}); a module for this chip keys "
            f"its own table the way samd21.py does, and this generator does "
            f"not write one"
        )
    lines = [
        HEADER_BEGIN,
        "#: Header label -> GPIO number: the pin `pin_states` reads a level",
        "#: through and `PIN_NAMES` spells. Read out of the board-support",
        "#: packages, never typed here:",
    ]
    lines.extend(f"#:     {citation}" for citation in table.citations)
    # **Not "every package agrees on every row"**, which is what this said
    # until it was reviewed and is false wherever one package alone defines a
    # row: only arduino-esp32 names the C5's and C6's `LED`, only arduino-pico
    # the RP2040's, and no Zephyr connector names any of them. What is true is
    # the rule `agree` enforces -- a row that two packages define twice and
    # differently resolves to nothing and never reaches this block.
    sentences = [
        (
            f"for {', '.join(table.boards)}. A row is here only where every package "
            f"that defines it names the same pin; a row only one package defines is "
            f"that package's."
        )
    ]
    if table.on_board:
        rows = ", ".join(f"`{label}`" for label in table.on_board)
        sentences.append(
            f"{rows} has no pad: it is the board's own LED, which the Arduino "
            f"variant above defines and the header does not carry."
        )
    sentences.append(
        "`tests/rules/test_import_pindefs.py` holds this block equal to what the "
        "generator emits from the fetched packages."
    )
    for sentence in sentences:
        lines.extend(textwrap.wrap(sentence, width=76, initial_indent="#: ",
                                   subsequent_indent="#: "))
    lines.append("HEADER: dict[str, int] = {")
    lines.extend(f'    "{label}": {pin.index},' for label, pin in table.pins.items())
    lines.append("}")
    lines.append(HEADER_END)
    return "\n".join(lines)


def module_path(chip: str, boards_dir: pathlib.Path = BOARDS_DIR) -> pathlib.Path:
    """`ESP32-C3` -> `webui/boards/esp32c3.py`: `webui.api.description_module`'s rule."""
    return boards_dir / f"{chip.lower().replace('-', '')}.py"


def chips_with_header_markers(boards_dir: pathlib.Path = BOARDS_DIR) -> list[str]:
    """Which chips take a generated block: read off the modules, not listed here.

    A module opts in by carrying the two markers. A marked module that no
    registered chip maps to is an error, because the alternative is a block
    that is never regenerated and looks exactly like one that is.
    """
    by_path = {module_path(board.chip, boards_dir): board.chip for board in BOARDS.values()}
    chips = []
    for path in sorted(boards_dir.glob("*.py")):
        if HEADER_BEGIN not in path.read_text(encoding="utf-8"):
            continue
        if path not in by_path:
            raise PindefError(
                f"{path} carries {HEADER_BEGIN!r} but no registered board's chip "
                f"maps to it; add the board to BOARDS or take the markers out"
            )
        chips.append(by_path[path])
    return chips


def splice_header(text: str, block: str, where: str) -> str:
    """`text` with what lies between the markers replaced by `block`."""
    begin = text.find(HEADER_BEGIN)
    end = text.find(HEADER_END)
    if begin < 0 or end < 0:
        raise PindefError(
            f"{where}: needs both {HEADER_BEGIN!r} and {HEADER_END!r} to write "
            f"between, and has {'the first' if begin >= 0 else 'neither' if end < 0 else 'the second'}"
        )
    if end < begin:
        raise PindefError(f"{where}: {HEADER_END!r} comes before {HEADER_BEGIN!r}")
    if text.find(HEADER_BEGIN, begin + 1) >= 0 or text.find(HEADER_END, end + 1) >= 0:
        raise PindefError(f"{where}: carries more than one HEADER block")
    return text[:begin] + block + text[end + len(HEADER_END):]


def write_header(
    chip: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> bool:
    """Regenerate one module's block in place. True when the file changed."""
    path = module_path(chip, boards_dir)
    if not path.is_file():
        raise PindefError(f"{path} does not exist; no module describes {chip}")
    text = path.read_text(encoding="utf-8")
    block = render_header(header_table(chip, bsp_dir, boards_dir))
    new = splice_header(text, block, str(path))
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


# --------------------------------------------------------------------------
# The board file (OH-160)
# --------------------------------------------------------------------------


#: How many spellings the sentence below shows before it stops. Three is
#: enough to recognise `PA02` from `P2.08` from `PC6`; an SMD file has
#: fifteen and the rest are the same fact again.
UNNUMBERED_EXAMPLES = 3


def unnumbered_sentence(chip: str, pins: list[str], described: bool) -> str:
    """Why `chip_index` is null on a pad whose `chip_pin` is not.

    OH-26's one real blocker, and the clause of OH-160 that would otherwise
    have no home: on the SAMD21, EFR32MG24, nRF54L15 and nRF54LM20A a
    resolved pad names `PA02`, `PC6` or `P2.08` and no flat integer, because
    those vendors publish no flat GPIO numbering -- an nRF54L15's P0 is five
    pins wide, so the 32-per-port arithmetic that is right for an nRF52840
    would invent a number appearing in no Nordic document (`ChipPin`).

    `webui/boards/samd21.py` is the shape such a chip's module takes when it
    gets one: its own `(group, bit)` table, and `PIN_NAMES` derived from it.
    Three of the four chips have no module at all, so this sentence in the
    board file is the only place the fact is written for them.
    """
    shown = ", ".join(pins[:UNNUMBERED_EXAMPLES])
    more = "" if len(pins) <= UNNUMBERED_EXAMPLES else ", and so on"
    # The module sentence differs by which chip this is: on a SAMD21 the file
    # being pointed at is this board's own, and telling a reader to look at
    # the way another chip does it would send them to the file they are
    # already reading about.
    module = f"webui/boards/{chip.lower().replace('-', '')}.py"
    keying = (
        f"so {module} keys its own table by port and bit instead, and derives "
        f"`PIN_NAMES` from that"
        if described
        else f"so a module for it would key its own table the way "
             f"webui/boards/samd21.py does, and until one exists no level is "
             f"read for any pad here"
    )
    return (
        f" {len(pins)} pins on this board are named with NO flat number -- "
        f"{shown}{more} -- so every pad reaching one carries `chip_index` null "
        f"for that reason and not for a missing reading: no flat GPIO numbering "
        f"is published for the {chip} at all, {keying}."
    )


def assumption_for(chip: str, described: bool, covered: bool,
                   unnumbered: list[str] | None = None) -> str:
    """What a board file says about its own `pin`, `chip_pin` and `chip_index`.

    Three shapes, because three things can be true of a board. `pin` is null
    on every one of them and still means what `webui/pinmap.py` says -- the
    rcontrol index of a PICSimLab board that does not exist. What varies is
    whether any package publishes this board's pins at all, and, where one
    does, whether a module here reads a level through the same table.

    The uncovered case is its own sentence rather than the undescribed one
    with an empty `packages` list: "the join is ready, not made" would be
    false on a board with nothing to join, and that is the XIAO STM32C5.
    """
    head = (
        "Every `pin` is null: that field is the rcontrol pin index of a PICSimLab "
        "board implementation (webui/pinmap.py), and none exists for this board. "
    )
    if not covered:
        return head + (
            f"`chip_pin` and `chip_index` are null on every pad here, and `pindefs` "
            f"names no package, because no board-support package covers this board "
            f"at all -- no Zephyr board and no vendor core publishes a {chip} XIAO "
            f"(OH-26). Each pad says the same in its own `why_null`. The pin view "
            f"reports every pad as not modelled, and will until the vendor "
            f"publishes something to read."
        )
    head += (
        "`chip_pin` and `chip_index` are what tools/import_pindefs.py read out of "
        "the board-support packages named in `pindefs`; a pad whose `chip_pin` is "
        "null says why in `why_null`. "
    )
    if described:
        body = (
            f"webui/boards/{chip.lower().replace('-', '')}.py reads a level through "
            f"the same table, so a pad with a `chip_pin` answers for itself in the "
            f"pin view; a pad without one is drawn and reported as not modelled."
        )
    else:
        body = (
            f"No board module describes {chip} here, so no level is read for any pad "
            f"and the pin view reports every one as not modelled until a module and a "
            f"core exist; `chip_pin` is recorded so that the join is ready, not made."
        )
    if unnumbered:
        body += unnumbered_sentence(chip, unnumbered, described)
    return head + body


def filled_board(
    name: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> dict:
    """The board file's document with the report written into it.

    Joined by POSITION, which is exact because `board_report` below reads
    this same file in this same call and returns one entry per pad in its
    order. The pad NUMBER the report carries for other consumers is not a
    key and could not be one: the nRF54LM20A SMD footprint numbers all three
    of its `GND` pads `46`, which is how Seeed's CAD names a multi-pad net.
    Everything else in the document is kept as it is.
    """
    path = board_path(name, boards_dir)
    document = json.loads(path.read_text(encoding="utf-8"))
    report = board_report(name, bsp_dir, boards_dir)
    pads = []
    # `strict` rather than a length check and a per-row comparison: both lists
    # are this one call's reading of this one file, so a mismatch is not a
    # state that can arise, and a hand-written guard for it would be a branch
    # no test could ever enter. `strict` still refuses to truncate silently if
    # that ever stops being true.
    for pad, entry in zip(document["pads"], report["pads"], strict=True):
        filled = {
            "label": pad["label"],
            "pin": pad.get("pin"),
            "chip_pin": entry["chip_pin"],
            "chip_index": entry["index"],
        }
        if entry["chip_pin"] is None:
            filled["why_null"] = entry["reason"]
        for key, value in pad.items():
            if key not in filled and key != "why_null":
                filled[key] = value
        pads.append(filled)

    covered = bool(report["packages"])
    # The PINS the packages resolved to a name with no number, in the file's
    # own order, deduplicated so the sentence quotes real pins off this board
    # rather than a class.
    #
    # **Pins and not pads, and the two are one number here only by accident
    # of the data.** Two pads can reach one pin -- the ESP32-C3 SMD has four
    # such pairs, `D3` and its underside `D3/MTDI` among them -- but on all
    # eight boards that have unnumbered pins, no pin is on two pads (measured
    # 2026-09-04). Counting pads would therefore be an unfalsifiable choice:
    # nothing in the tree could tell the two counts apart.
    spellings = list(dict.fromkeys(
        pad["chip_pin"] for pad in pads
        if pad["chip_pin"] is not None and pad["chip_index"] is None
    ))
    pindefs = {
        "generated_by": "tools/import_pindefs.py",
        "derivation": BOARD_DERIVATION if covered else BOARD_DERIVATION_UNCOVERED,
        "packages": report["packages"],
        "resolved": report["resolved"],
        "unresolved": report["unresolved"],
        "disputed": report["disputed"],
        "on_board": report["on_board"],
    }
    described = module_path(report["chip"], boards_dir).is_file()
    filled_document: dict = {}
    for key, value in document.items():
        if key == "pads":
            filled_document["pads"] = pads
        elif key in ("pindefs",):
            continue
        else:
            filled_document[key] = value
        if key == "assumption":
            filled_document["assumption"] = assumption_for(
                report["chip"], described, covered, spellings
            )
            filled_document["pindefs"] = pindefs
    if "pindefs" not in filled_document:
        raise PindefError(f"{path}: has no `assumption` field to put `pindefs` after")
    return filled_document


def write_board(
    name: str,
    bsp_dir: pathlib.Path = BSP_DIR,
    boards_dir: pathlib.Path = BOARDS_DIR,
) -> bool:
    """Write the filled document back. True when the file changed."""
    path = board_path(name, boards_dir)
    text = json.dumps(filled_board(name, bsp_dir, boards_dir), indent=2, ensure_ascii=False) + "\n"
    if path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


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
    `tools/get_board_sources.py` makes about the vendor CAD applies: size
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
        epilog=(
            "Writes a report by default. --write-headers and --write-boards "
            "write the same answer into the board modules and the board files."
        ),
    )
    parser.add_argument("board", nargs="?", help="a board in webui/boards/")
    parser.add_argument("--fetch", action="store_true", help="clone or update every package")
    parser.add_argument("--list", action="store_true", help="the registry, one board per line")
    parser.add_argument("--all", action="store_true", help="report every registered board")
    parser.add_argument("--summary", action="store_true", help="counts instead of JSON")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="write JSON here, not to stdout")
    parser.add_argument(
        "--emit-header", metavar="CHIP", help="print the HEADER block a module embeds"
    )
    parser.add_argument(
        "--write-headers", action="store_true",
        help="regenerate the HEADER block in every module that carries the markers",
    )
    parser.add_argument(
        "--write-boards", action="store_true",
        help="write chip_pin, chip_index and why_null into every registered board file",
    )
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

    if args.emit_header:
        print(render_header(header_table(args.emit_header)))
        return 0

    if args.write_headers or args.write_boards:
        if args.write_headers:
            chips = chips_with_header_markers()
            if not chips:
                raise PindefError(f"no module under {BOARDS_DIR} carries {HEADER_BEGIN!r}")
            for chip in chips:
                changed = write_header(chip)
                print(f"{'wrote' if changed else 'unchanged'}  {module_path(chip)}")
        if args.write_boards:
            for name in sorted(BOARDS):
                changed = write_board(name)
                print(f"{'wrote' if changed else 'unchanged'}  {board_path(name)}")
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
