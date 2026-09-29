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
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import textwrap
import typing

try:
    from tools import board_manifest
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import board_manifest

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


def read_chip_pins(
    texts: tuple[str, ...], *, labels: tuple[str, ...]
) -> dict[str, ChipPin]:
    """Labels the SILICON fixes, read from every variant of the same chip.

    **The one reader that looks outside the board's own package files, and the
    reason it is safe is the reason it exists.** `MTMS` on an ESP32-S3 is an
    IO_MUX function of the part: no board can move it, and Seeed's own
    `XIAO_ESP32S3` variant does not name it because a board variant lists what
    the BOARD chose. So the evidence is every variant of that chip, and the
    agreement between them is the check.

    Measured 2026-09-06 across every variant `boards.txt` maps to a chip:

        esp32s3   MTMS 42  MTDI 41  MTDO 40  MTCK 39   5 variants, agree
                  USB_DN 19  USB_DP 20                 5 variants, agree
        esp32     MTMS 14  MTDI 12  MTDO 15  MTCK 13   2 variants, agree

    **What this test does NOT establish, and a review was right to press it.**
    Unanimity does not separate a pin the silicon fixes from a pin every board
    in the sample happens to wire alike. Measured across the same 158 esp32s3
    variants: `RST_LoRa` is 12 in all nine that define it, `DIO0` is 14 in all
    ten, and `WS_LCD_R5` is 42 in all seven -- the same number as `MTMS`.
    Those are Heltec's and Waveshare's board wiring, unanimous because
    same-vendor variants copy one another.

    So the agreement is a CONSISTENCY CHECK and not a proof. What keeps the
    six labels below correct is that they were checked against the part's
    IO_MUX table and then opted in BY NAME: nothing is swept in by pattern,
    and the allowlist is the safeguard. This function's job is to catch a
    typo or a revision that moved one of them, which it does.

    **The five are not five independent statements, and a first draft of this
    comment said they were.** It claimed the files "share no text". Measured:
    `XIAO_ESP32S3_Plus` and `uPesy_esp32s3_basic` share 27 of the smaller
    file's 67 non-blank lines, and three of the five write the JTAG block
    character-identically as `static const uint8_t MTCK = 39;`. So it is two
    distinct spellings across five files, and one of the five is Seeed's own
    sibling board, which is not independent evidence about a XIAO at all.

    What is worth leaning on is narrower: `esp32s3usbotg` is Espressif's own
    development kit, so one of the two spellings comes from the company that
    makes the silicon. That is the strongest thing here. **OH-26's first trap is the opposite
    case**: `D6` is GPIO0 on an RP2040 and GPIO21 on an ESP32-C3, which is two
    chips, and a label a board chooses would show exactly the scatter these do
    not show.

    **A disagreement raises rather than resolving to a majority.** For a pin
    the silicon fixes there is no such thing as two right answers, so variants
    that differ mean the label is not silicon-fixed after all and the caller
    has opted in the wrong one. Every label here is named explicitly for that
    reason -- nothing is swept in by pattern.
    """
    #: Below this, "they all agree" is a sentence about one file. A single
    #: variant defining a label used to resolve it outright, which is not
    #: agreement at all -- 742 of this chip's 926 unanimous labels are defined
    #: by exactly one variant.
    minimum = 3
    seen: dict[str, dict[int, int]] = {}
    for text in texts:
        for label, number in read_c_pin_constants(text).items():
            if label in labels:
                seen.setdefault(label, {})
                seen[label][number] = seen[label].get(number, 0) + 1
    pins: dict[str, ChipPin] = {}
    for label, counts in seen.items():
        if sum(counts.values()) < minimum:
            raise PindefError(
                f"{label} is defined by only {sum(counts.values())} variant(s) "
                f"of this chip; below {minimum} there is no agreement to read, "
                f"and a label opted in here is one somebody has checked "
                f"against the part's own pin table"
            )
        if len(counts) > 1:
            raise PindefError(
                f"{label} is opted in as a pin the silicon fixes, but the "
                f"variants of this chip disagree: {dict(sorted(counts.items()))} "
                f"(value -> how many variants). A pin a board can move is not "
                f"one this reader may answer for"
            )
        (number,) = counts
        pins[label] = ChipPin(f"GPIO{number}", number)
    return pins


#: A net name that carries the pin beside the label. Seeed write these four
#: ways in one directory -- `GPIO4{slash}MTMS`, `Boot{slash}GPIO28`,
#: `MTMS_GPIO2_ADC1_CH1`, `P1.02{slash}NFC1` -- so the pin is found as a token
#: rather than by position, and `{slash}` is KiCad's escape for `/`.
#: `(net 3 "NAME")` in KiCad 8 and `(net "NAME")` in KiCad 10, which Seeed
#: used for the nRF54LM20A. One expression rather than a version check,
#: because the number is the only difference and nothing here wants it.
_NET_NAME = re.compile(r'\(net (?:\d+ )?"([^"]*)"\)')

#: What a pad function looks like when it names a pin of the part: Espressif
#: and Raspberry Pi number flatly, Silicon Labs by port and pin, Nordic by
#: port and bit.
#:
#: **Anchored at the start and not at both ends**, because Nordic's newer
#: footprints append the ball: the nRF54LM20A writes `P1.01/NFC1_J6` and
#: `P0.00_K3` where the nRF54L15 writes `P1.01`. A pattern anchored at both
#: ends matched neither, so `read_seeed_traced` on that file returned nothing
#: at all while citing it as a source -- 2.4 MB read to say nothing, and no
#: test noticing.
#:
#: The start still has to BE the pin: `SWDIO_G2` does not begin with one, so
#: it is refused as it should be. A pad outside the part's numbering --
#: `SWDIO`, `XIN`, `IOVDD` -- has no pin number to report, and that is the
#: distinction this makes.
_CHIP_PIN_NAME = re.compile(r"^(GPIO\d+|P[A-D]\d{1,2}|P\d\.\d{1,2})(?:[/_]|$)")

_PIN_TOKEN = re.compile(r"^(?:GPIO(\d+)|P(\d)\.(\d+))$")


def read_seeed_net_names(
    texts: tuple[str, ...], *, labels: tuple[str, ...]
) -> dict[str, ChipPin]:
    """Labels the VENDOR names beside their pin, in their own board file.

    **The strongest source in this tree for these pads, and the only one that
    is per board.** Seeed's KiCad projects name a net for what it carries, and
    where a pad is both a header label and a chip pin the name says both:

        GPIO4{slash}MTMS        the C6's MTMS is GPIO4
        MTMS_GPIO2_ADC1_CH1     the C5's MTMS is GPIO2
        P1.02{slash}NFC1        the nRF54L15's NFC1 is P1.02

    The C5 and the C6 disagreeing about MTMS is not a fault: they are
    different chips, which is OH-26's first trap, and this reader answers per
    board so it never has to generalise. That is why it is preferred over
    `arduino_chip`, which infers from a chip's other boards.

    A net is used only when the label appears as a whole token and exactly one
    pin token sits beside it. Two pin tokens, or none, and the label is left
    for another source: `BOOT` on the C6 is a net called simply `BOOT`, which
    names no pin and is correctly not answered here.
    """
    wanted = {label.upper() for label in labels}
    found: dict[str, dict[str, ChipPin]] = {}
    for text in texts:
        for raw in set(_NET_NAME.findall(text)):
            parts = [p for p in re.split(r"\{slash\}|/|_", raw) if p]
            tokens = [p.upper() for p in parts]
            hit = wanted & set(tokens)
            if not hit:
                continue
            pins = [m for m in (_PIN_TOKEN.match(p) for p in parts) if m]
            if len(pins) != 1:
                continue
            gpio, port, bit = pins[0].groups()
            pin = (ChipPin(f"GPIO{gpio}", int(gpio)) if gpio is not None
                   else ChipPin(f"P{port}.{bit}", None))
            for label in hit:
                found.setdefault(label, {})[raw] = pin
    pins: dict[str, ChipPin] = {}
    for label, byname in found.items():
        distinct = {pin for pin in byname.values()}
        if len(distinct) > 1:
            raise PindefError(
                f"{label} appears on {len(byname)} nets naming different pins "
                f"({sorted(byname)}); the board file is saying two things and "
                f"a reader must not choose between them"
            )
        pins[label] = next(iter(distinct))
    return pins


def _footprints(text: str) -> list[tuple[str, dict[str, list[str]]]]:
    """Every footprint as `(value, {net: [pad function, ...]})`.

    Keyed on the value rather than the reference, because a reference is a
    position on a board and a value is the part: `EFR32MG24B220F1536IM48-B`
    says which chip this is and `U5` does not.
    """
    out = []
    for block in re.split(r"\n\t\(footprint ", text)[1:]:
        value = re.search(r'\(property "Value" "([^"]*)"', block)
        by_net: dict[str, list[str]] = {}
        for pad in re.finditer(r'\(pad "[^"]*"[^\n]*(?:\n(?!\t\t\(pad ).*)*', block):
            chunk = pad.group(0)
            function = re.search(r'\(pinfunction "([^"]*)"', chunk)
            net = _NET_NAME.search(chunk)
            if function and net:
                by_net.setdefault(net.group(1), []).append(function.group(1))
        out.append((value.group(1) if value else "", by_net))
    return out


def read_seeed_traced(
    texts: tuple[str, ...], *, part: str, labels: tuple[str, ...]
) -> dict[str, ChipPin]:
    """Follow a pad's net to the board's own MCU and read that pad's function.

    **For labels the net name does not spell out.** Seeed name a net `SWDIO`
    and leave the pin to the footprint, so the answer is one hop away: find
    the net, find the MCU's pad on it, and that pad's own function names the
    pin. On the XIAO MG24 it gives `SWDIO` -> `PA02` and `SWCLK` -> `PA01`,
    ordinary GPIOs of that part.

    **Which footprint is the MCU matters more here than anywhere else on this
    ticket, because these boards carry two.** The MG24 has an
    `ATSAMD11D14A-UUT` beside its `EFR32MG24...`, and that SAMD11 is the
    on-board debugger -- its pads sit on nets with the very same names, and
    its own `PA02` is a different pin of a different chip. Matching the part's
    value string is what keeps the debugger out of a field that means "a pin
    of this board's MCU".

    A pad whose function is not a pin name -- `SWDIO`, `XIN`, `IOVDD` -- is
    outside the part's GPIO numbering and resolves to nothing. That is the
    RP2350's case, and `Board.reasons` answers it in words instead.

    **A label that is on no net of the part at all raises instead of
    resolving to nothing.** Those two silences used to be one: the first is
    the silicon saying it has no GPIO number for this pad, the second is a
    citation naming something that is not there, and only the first is a
    fact worth keeping quiet about.
    """
    pins: dict[str, ChipPin] = {}
    for text in texts:
        matched = [(value, by_net) for value, by_net in _footprints(text)
                   if part in value]
        if not matched:
            raise PindefError(
                f"no footprint in this board file has {part!r} in its value, "
                f"so which of its parts is the MCU is not established and "
                f"nothing may be traced to it"
            )
        # **More than one match is refused, and that is the half that matters.**
        # Refusing zero is easy; a `part` loose enough to catch two footprints
        # is the dangerous case, because these boards carry a second
        # microcontroller on the same nets. `part="A"` on the MG24 matches both
        # the EFR32MG24 and the ATSAMD11, and a last-one-wins loop answered
        # SWCLK with the DEBUGGER's PA03 without a word. Every other reader in
        # this file raises on ambiguity; this one used to resolve quietly.
        if len(matched) > 1:
            raise PindefError(
                f"{part!r} matches {len(matched)} footprints on this board "
                f"({sorted(value for value, _ in matched)}); it must name one "
                f"part, because a board carrying two microcontrollers puts "
                f"them on nets with the same names"
            )
        mine = [by_net for _, by_net in matched]
        for label in labels:
            wanted = label.upper()
            reached = False
            for by_net in mine:
                for net, functions in by_net.items():
                    plain = net.replace("{slash}", "/").rsplit("/", 1)[-1].upper()
                    if plain != wanted:
                        continue
                    reached = True
                    named = {match.group(1) for match in
                             (_CHIP_PIN_NAME.match(one) for one in functions)
                             if match}
                    if len(named) > 1:
                        raise PindefError(
                            f"{label} reaches {sorted(named)} on this part, so "
                            f"the board file names more than one pin for one "
                            f"pad and a reader must not choose between them"
                        )
                    if named:
                        # **The flat index, where the part has one.** This used
                        # to pass `None` always: right for `PA02` and `P1.01`,
                        # which no vendor numbers flatly, and wrong for
                        # `GPIO9`. `render_header` refuses an entire chip whose
                        # pin has a name and no index, so the C6's BOOT would
                        # have made `--write-headers` raise for every ESP32-C6
                        # board rather than skip one pad. `_PIN_TOKEN` already
                        # knew how to tell the two apart.
                        one = next(iter(named))
                        token = _PIN_TOKEN.match(one)
                        flat = token.group(1) if token else None
                        pins[label] = ChipPin(
                            one, int(flat) if flat is not None else None)
            # **Two different silences, and only one of them is a fact.**
            # A label that REACHES this part and whose pad is not a pin name
            # resolves to nothing above, and that is right: `SWDIO_G2` says
            # the silicon has no GPIO number for it, which `Board.reasons`
            # then answers in words. A label that is on no net of this part
            # at all says nothing about silicon -- it is a citation naming
            # something that is not there, and it used to return the same
            # empty answer as the real fact.
            #
            # Measured on the nRF54LM20A, which asked for four: `SHPHLD` is a
            # pin of the board's nPM1300 and never was on the MCU, and
            # `nRF54_RST`'s net is `~{nRF54_RESET}`. Both were answered
            # correctly in words while still being asked for here, so the
            # request could not fail however wrong it got. The cost is not
            # those two: if a vendor revision renamed `MG24.kicad_pcb`'s
            # `SWDIO` net, the MG24's `PA02` and `PA01` would vanish exactly
            # this quietly and the pads would fall back to a generic null.
            if not reached:
                raise PindefError(
                    f"{label!r} is on no net of the {part} footprint in this "
                    f"board file, so there is nothing to trace to. A label "
                    f"traced here must reach this part: a pad that reaches it "
                    f"and is not a GPIO resolves to nothing, which is a fact "
                    f"about the silicon, but a net that is absent is a "
                    f"citation that names nothing"
                )
    return pins


_SYMBOL = re.compile(r'^\t\(symbol "([^"]+)"', re.M)
_SYMBOL_PIN_NAME = re.compile(r'\(name "([^"]*)"')
#: KiCad's second place to put a pin's function. A symbol may publish
#: `(alternate "PA13" ...)` beside a pin whose `(name ...)` is plain, and the
#: sweep below asserts what the board file says about the WHOLE library, so a
#: name it cannot see is a way past the alarm. This file has zero of them
#: today -- measured, which is why nothing resolves from one and why the
#: sweep only has to refuse them.
_SYMBOL_ALTERNATE = re.compile(r'\(alternate "([^"]*)"')


def read_symbol_pin_names(
    texts: tuple[str, ...], *, symbol: str, labels: tuple[str, ...]
) -> dict[str, ChipPin]:
    """A pad whose name in the vendor's schematic symbol also names its pin.

    **The only source there is for the one board nothing else covers.** No
    Zephyr board and no vendor core publishes a STM32C5 XIAO, so every one of
    its 35 pads was null -- and two of them were null while Seeed's own symbol
    library called them `SWDIO/PA13` and `SWCLK/PA14`. A pad reported as "a
    gap in what the vendor has published" when the vendor has published it is
    the report being wrong, not the board being unknowable.

    Two pads of 582 across the catalogue. It reaches nothing another source
    would have: measured over all twenty symbols, `SWDIO/PA13` and
    `SWCLK/PA14` are the only names in the library that name a pin at all.

    **What the other nineteen carry is not `D0` through `D15`**, which is
    what this paragraph said until a review swept them. They run `D0` through
    `D27`, and 51 of their names are not a bare `Dn` -- pads and supplies
    (`3V3_OUT`, `VBUS`, `VBAT`, `BAT`, `VIN`, `EN`, `PAD`), functions
    (`NFC1`, `SHPHLD`, `USER_LED`, `MTMS`, `SWDIO`, `USB_DN`, `MG24_EN`,
    `54L15_TX20`), and on `XIAO-Add-On-Plus` nine pins named `"15"` through
    `"23"`. Nine of the 51 are compounds like `D15/MTMS` whose
    `alternatives()` do include a `Dn`, so "not a bare `Dn`" is the accurate
    form and "not `Dn` at all" was not. The half that is load-bearing is the
    other one, and it is the half that is checked: none of them names a pin.

    Keyed on the LABEL half and not the whole name, because `resolve` matches
    a pad through `alternatives`, which splits `SWDIO/PA13` into its two
    names. A dict keyed `SWDIO/PA13` would have matched no pad at all.

    **Every pin of the symbol is swept, not only the opted-in ones**, and a
    pin naming a pin that nobody opted in is refused. The board file's
    `assumption` used to tell a reader this CAD names a pin beside those pad
    names "and beside no others", and until this swept the whole symbol that
    half of the sentence was a hand-check written into generated prose. The
    sweep is what made it a claim the tool stands behind; the sentence was
    then narrowed twice more, to the spellings actually recognised and to
    THIS symbol rather than the whole library, for the reasons below.

    **The sweep recognises a pin by `_CHIP_PIN_NAME`, and that is the exact
    strength of the alarm.** Its branches are `GPIO\\d+`, `P[A-D]\\d{1,2}` and
    `P\\d\\.\\d{1,2}`. Republish this library naming a pin in one of those and
    the generator stops; name one in any other spelling and it goes past,
    `PE2` being the nearest miss to what is already read here. So the
    sentence the board file generates speaks for the symbol read for that
    board and names the spellings this tool recognises, which is what is
    enforced, rather than claiming a universal nothing checked.

    **Retracted from this paragraph, twice over.** It claimed "this same
    STM32 part has ports E through H", then a correction claimed "`P100`
    appears nowhere in this tree". Both were written rather than read, and
    the second was wrong about the first in a way worth keeping:

      - The STM32C5's ports really are unsourced here. `PA13` and `PA14` are
        its only pin names in the tree, and Seeed's document folder has no
        STM32 among its boards. (A draft said "eleven XIAOs". There are
        eleven `SeeedStudio_XIAO_*` directories and one is an expansion
        board, so the count was decoration and wrong in a paragraph whose
        subject is decoration being wrong. The half that carries the
        argument is that none of them is an STM32.)
      - Renesas `Pnnn` was NOT unsourced. `document/SeeedStudio_XIAO_RA4M1/`
        names `BAT_DET_PIN/P105` and `BAT_READ_EN/P400`, and neither matches
        `_CHIP_PIN_NAME`. Only the token `P100` was invented; the example it
        was standing in for was in the repository the whole time.

    The lesson is not "check harder before writing a fact". It is that a
    paragraph justifying a pattern does not need silicon in it at all: the
    gap is a property of the regex, and every part named beside it was
    decoration that had to be verified and twice was not.
    """
    if len(texts) != 1:
        raise PindefError(
            f"this reader takes one symbol library and was given {len(texts)}; "
            f"a pin read from the wrong file is a wrong answer that looks right"
        )
    (text,) = texts
    starts = [(match.group(1), match.start()) for match in _SYMBOL.finditer(text)]
    if not starts:
        raise PindefError(
            "this file has no top-level symbol, so it is not the symbol "
            "library this reader was pointed at"
        )
    mine = [i for i, (name, _) in enumerate(starts) if name == symbol]
    if len(mine) != 1:
        raise PindefError(
            f"{symbol!r} names {len(mine)} of this library's {len(starts)} "
            f"symbols ({sorted(name for name, _ in starts)}); it must name "
            f"exactly one, because a pin read off the wrong board is a wrong "
            f"answer that looks like a right one"
        )
    index = mine[0]
    end = starts[index + 1][1] if index + 1 < len(starts) else len(text)
    body = text[starts[index][1]:end]

    pins: dict[str, ChipPin] = {}
    # Both places KiCad puts a pin's function, because the sweep speaks for
    # the whole symbol. An `(alternate ...)` is never resolved FROM, so a
    # republished library naming a pin there must stop the generator instead
    # of slipping past the sentence the board file emits.
    #
    # **The opt-in exemption applies to `(name ...)` only, and that asymmetry
    # is the point.** A pin name carrying an opted-in label is exempt because
    # the loop below reads it. An ALTERNATE carrying one is read by nothing,
    # so exempting it would leave a third state beside refused and resolved:
    # `(alternate "SWDIO/PA15")` with `SWDIO` opted in used to pass the sweep
    # on the opt-in and then be ignored, returning PA13 with nothing raised.
    unclaimed = [
        name for name in _SYMBOL_PIN_NAME.findall(body)
        if any(_CHIP_PIN_NAME.match(alt) for alt in alternatives(name))
        and not any(alt in labels for alt in alternatives(name))
    ] + [
        name for name in _SYMBOL_ALTERNATE.findall(body)
        if any(_CHIP_PIN_NAME.match(alt) for alt in alternatives(name))
    ]
    if unclaimed:
        raise PindefError(
            f"{symbol} names a pin on {sorted(set(unclaimed))}, which nobody "
            f"opted in; every pin this symbol publishes must be listed, "
            f"because the board file states that the listed pads are the only "
            f"ones in this symbol whose name carries a pin in a spelling this "
            f"tool recognises"
        )
    for name in _SYMBOL_PIN_NAME.findall(body):
        alts = alternatives(name)
        mentioned = [alt for alt in alts if alt in labels]
        if not mentioned:
            continue
        # **A pin naming two opted-in labels is refused, not skipped.** This
        # was `if len(mentioned) != 1: continue`, so `SWDIO/SWCLK/PA13` -- a
        # pin that DOES name a pin, and passes the sweep above because both
        # its labels are opted in -- fell out silently and resolved neither
        # pad. It is the one path where the only-these-pads chain broke
        # quietly, in a function otherwise built entirely from raises.
        if len(mentioned) > 1:
            raise PindefError(
                f"the symbol pin {name!r} carries {sorted(mentioned)}, which "
                f"are two opted-in labels on one pin; which pad it names is "
                f"not for a reader to choose"
            )
        named = {match.group(1) for match in
                 (_CHIP_PIN_NAME.match(alt) for alt in alts) if match}
        if len(named) > 1:
            raise PindefError(
                f"the symbol pin {name!r} names {sorted(named)}, so one pad "
                f"claims more than one pin and a reader must not choose"
            )
        if not named:
            raise PindefError(
                f"the symbol pin {name!r} was opted in as naming its pin and "
                f"does not; a label is listed here because somebody read it"
            )
        # **Last-write-wins is a disagreement averaged**, and the sibling
        # reader refuses exactly this. Two pins named `SWDIO/PA13` and
        # `SWDIO/PA15` would each pass every check above -- one opted-in
        # label, one pin name apiece -- and the second would replace the
        # first with nothing said. `read_seeed_net_names` guards it; this
        # did not, and one file should not hold both rules.
        one = named.pop()
        token = _PIN_TOKEN.match(one)
        pin = ChipPin(one, int(token.group(1)) if token and token.group(1) else None)
        if mentioned[0] in pins and pins[mentioned[0]] != pin:
            raise PindefError(
                f"{symbol} names {mentioned[0]!r} twice, as "
                f"{pins[mentioned[0]].name} and {pin.name}; the symbol is "
                f"saying two things and a reader must not choose between them"
            )
        pins[mentioned[0]] = pin
    return pins


def seeed_symbol(symbol: str, labels: tuple[str, ...]) -> Source:
    """Seeed's schematic symbol library, read for the pads that name a pin."""
    return Source(
        "seeed-xiao",
        ("Seeed Studio XIAO Series Library/Seeed_Studio_XIAO_Series.kicad_sym",),
        functools.partial(read_symbol_pin_names, symbol=symbol, labels=labels),
        root=REPO / "third_party" / "seeed-xiao",
    )


def seeed_pcb_traced(board_file: str, part: str, labels: tuple[str, ...]) -> Source:
    """Seeed's own board file, followed one hop from the pad to the MCU."""
    return Source(
        "seeed-pcb",
        (board_file,),
        functools.partial(read_seeed_traced, part=part, labels=labels),
        root=REPO / "third_party" / "seeed-pcb",
    )


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
    #: False for a source `--fetch` cannot clone. Seeed publish their board
    #: CAD as a zip behind a wiki page, so it is downloaded by hand into
    #: `third_party/seeed-pcb/` exactly as the Arduino Uno's EAGLE file is --
    #: `tools/get_board_sources.py` prints the URL and refuses to fetch an
    #: https archive itself, for the reason that file gives.
    cloned: bool = True
    #: False for a source that is CAD rather than firmware. **"No
    #: board-support package covers this board" stays true of a board whose
    #: schematic symbol names two of its pins**, and three sentences this tool
    #: generates turn on that fact -- the board file's `derivation`, its
    #: `assumption`, and `NO_PACKAGE_AT_ALL` on each pad. Keying them on
    #: "has no sources at all" was right only while the uncovered board had
    #: none; the moment its symbol library was read, that test would have had
    #: the file claim a core publishes its pins. Keying them on `cloned` would
    #: have worked today by coincidence and rotted, because `cloned` is about
    #: how a file arrives and not about what it is.
    firmware: bool = True
    #: The command that produces this checkout, where `--fetch` is not it.
    #: **`cloned=False` was carrying two meanings and one of them was a lie
    #: to the user.** It is true that `--fetch` clones neither `seeed-pcb`
    #: nor `seeed-xiao`, but only the first is a hand download: the second is
    #: a `git-sparse` source that `tools/get_board_sources.py seeed-xiao`
    #: fetches in one command, which `--list` on that tool prints. Both the
    #: `--fetch` summary and the missing-checkout error said "download by
    #: hand" for it, and the second named `--fetch` as the cure -- a loop,
    #: since `--fetch` skips every `cloned=False` package.
    fetch: str | None = None

    def how_to_fetch(self) -> str:
        """What to actually run to get this package, as a sentence."""
        if self.cloned:
            return "run `python tools/import_pindefs.py --fetch` to clone it"
        if self.fetch is not None:
            return f"run `{self.fetch}`"
        return f"download it by hand from {self.repository}"


@dataclasses.dataclass(frozen=True)
class Source:
    """One package's files for one board, and the reader that understands them."""

    package: str
    paths: tuple[str, ...]
    read: typing.Callable[[tuple[str, ...]], dict[str, ChipPin]]
    #: Given the checkout, the files to read instead of `paths`. Only
    #: `arduino_chip` sets it, because only that source cannot know its files
    #: until it has read the package's own board table -- every variant of one
    #: chip, which is a different set at every revision. `paths` is what the
    #: citation names either way, so a file records what it consulted rather
    #: than a list that would rot.
    expand: typing.Callable[[pathlib.Path], tuple[str, ...]] | None = None
    #: Where this source's files live, when they are not a `--fetch` clone
    #: under `third_party/bsp/`. Two packages sit here and they arrive
    #: differently, which this said of only the first:
    #:
    #:   seeed-pcb   board CAD published as a zip on a wiki page rather than
    #:               in a repository, downloaded by hand into
    #:               `third_party/seeed-pcb/` exactly as the Arduino Uno's
    #:               EAGLE file is. `tools/get_board_sources.py` prints the
    #:               URL and refuses to fetch an https archive itself.
    #:   seeed-xiao  a real git checkout, fetched by one command --
    #:               `python tools/get_board_sources.py seeed-xiao` -- into
    #:               `third_party/seeed-xiao/`. Not under `third_party/bsp/`,
    #:               which is the only reason it needs a `root` at all.
    #:
    #: `Package.how_to_fetch` is where that difference is stated to a user;
    #: saying "downloaded by hand" of both is what sent one into a loop.
    root: pathlib.Path | None = None


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
    #: Labels whose null has a better reason than "no package names it", as
    #: `(label, why)` pairs. **The generic sentence is true and unhelpful**: it
    #: says nobody published a mapping, when for some pads the fact is that
    #: there is no mapping to publish. A dedicated debug pad is not an unread
    #: label, and telling a reader which one they are looking at is the whole
    #: point of `why_null` carrying prose rather than a flag.
    #:
    #: Every reason here cites where it was read. A reason is a claim like any
    #: other and gets no easier ride for being about an absence.
    reasons: tuple[tuple[str, str], ...] = ()


PACKAGES = {
    package.name: package
    for package in (
        # A git checkout like the BSPs, but fetched by
        # `tools/get_board_sources.py seeed-xiao` into `third_party/seeed-xiao`
        # rather than by `--fetch` into `third_party/bsp/`, so `cloned` is
        # False and its citations carry a digest of the file read.
        Package(
            "seeed-xiao",
            "https://github.com/Seeed-Studio/OSHW-XIAO-Series.git",
            (),
            "MIT, per LICENSE at the repository root",
            cloned=False,
            firmware=False,
            fetch="python tools/get_board_sources.py seeed-xiao",
        ),
        Package(
            "seeed-pcb",
            "https://wiki.seeedstudio.com/ -- each XIAO's own page, as a zip",
            (),
            "OSHW, per Seeed's XIAO series repository",
            cloned=False,
            firmware=False,
        ),
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


def variants_of_chip(checkout: pathlib.Path, chip: str) -> tuple[str, ...]:
    """Every `variants/<v>/pins_arduino.h` the package builds for one chip.

    `boards.txt` is the only in-tree statement of which chip a variant belongs
    to: a board row names both its `build.variant` and its `build.mcu`, and
    several boards share one variant. Sorted so the file a run produces does
    not depend on a directory's order.
    """
    text = (checkout / "boards.txt").read_text(encoding="utf-8", errors="replace")
    variant: dict[str, str] = {}
    mcu: dict[str, str] = {}
    for line in text.splitlines():
        for pattern, into in ((r"([\w.\-]+)\.build\.variant=(.+)", variant),
                              (r"([\w.\-]+)\.build\.mcu=(.+)", mcu)):
            found = re.match(pattern, line.strip())
            if found:
                into[found.group(1)] = found.group(2).strip()
    wanted = {folder for board, folder in variant.items() if mcu.get(board) == chip}
    return tuple(sorted(
        f"variants/{folder}/pins_arduino.h" for folder in wanted
        if (checkout / "variants" / folder / "pins_arduino.h").is_file()
    ))


def arduino_chip(package: str, chip: str, labels: tuple[str, ...]) -> Source:
    """Labels the silicon fixes, from every variant of that chip.

    For pins no board can move and which the board's OWN variant therefore
    does not list. See `read_chip_pins`, which refuses when the variants
    disagree rather than taking a majority.
    """
    return Source(
        package,
        (f"variants/*/pins_arduino.h for every {chip} board in boards.txt",),
        functools.partial(read_chip_pins, labels=labels),
        expand=functools.partial(variants_of_chip, chip=chip),
    )


def seeed_pcb(board_file: str, labels: tuple[str, ...]) -> Source:
    """Seeed's own KiCad board file for one XIAO, read for its net names.

    Per board and per chip at once, which is what makes it the best source
    here: the C5 and the C6 name different pins for `MTMS` and this reader
    never has to know that, because it reads each board's own file.

    Not a `--fetch` clone. Seeed publish the CAD as a zip from a wiki page, so
    it is downloaded by hand into `third_party/seeed-pcb/`, like the Uno's
    EAGLE file. A board whose file is absent raises with the path, the same as
    a stale sparse checkout does.
    """
    return Source(
        "seeed-pcb",
        (board_file,),
        functools.partial(read_seeed_net_names, labels=labels),
        root=REPO / "third_party" / "seeed-pcb",
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
#: The JTAG pads and the boot strap. **Per board and not per chip**: Seeed's
#: own file puts the C5's MTMS on GPIO2 and the C6's on GPIO4, which is
#: exactly OH-26's first trap, and reading each board's own file is how this
#: never has to be generalised. `BOOT` is here for the C5, whose net is
#: `Boot{slash}GPIO28`, and NOT for the C6, whose net is called simply `BOOT`
#: and names no pin -- so the C6's stays null and says so.
_ESP32_JTAG = ("MTMS", "MTDI", "MTDO", "MTCK", "BOOT")
_ESP32C5 = (
    zephyr_connector("xiao_esp32c5", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C5", extras=("LED",)),
    # **Seeed's own board file resolves five more pads here and it is not
    # wired in, which is a claim and not an oversight.** `ESP32-C5.kicad_pcb`
    # names `MTMS_GPIO2_ADC1_CH1`, `MTDI_GPIO3_...`, `MTDO_GPIO5_...`,
    # `MTCK_GPIO4_...` and `Boot{slash}GPIO28`, all read cleanly by
    # `read_seeed_net_names`. Adding them changes what this board's module
    # must claim -- `test_the_board_file_and_the_module_agree_on_every_labelled_pad`
    # holds the file and `PIN_NAMES` equal in both directions -- and
    # `webui/boards/esp32c5.py` is OH-161's file, not OH-170's. It goes in
    # when that ticket releases it. The C6 is the same, with its own values:
    # MTMS 4, MTDI 5, MTDO 7, MTCK 6, which is why neither may be copied to
    # the other.
)
_ESP32C6 = (
    zephyr_connector("xiao_esp32c6", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32C6", extras=("LED",)),
    # As the C5 above: FIVE more pads are readable from `ESP32-C6.kicad_pcb`
    # and wait on OH-161 releasing `esp32c6.py` -- MTMS 4, MTDI 5, MTDO 7,
    # MTCK 6, and BOOT 9.
    #
    # **BOOT needs the tracer and not the net names**, which is worth writing
    # down because a first pass here said it was unreadable. The C5's net is
    # `Boot{slash}GPIO28` and states the pin; the C6's is called simply
    # `BOOT`. But the C6 module's own pad on that net is named `GPIO9`, so
    # `seeed_pcb_traced` answers it where `seeed_pcb` cannot -- two readers
    # over one file, and which one a label needs is a property of how the
    # vendor drew that sheet rather than of the label.
)
#: The ESP32-S3's JTAG and USB pads, which are the part's and not the board's
#: (OH-170 US-1). Seeed's own variant names none of them -- it defines
#: `LED_BUILTIN` and stops -- because a board variant lists what the board
#: chose, and a board chooses none of these. `arduino_chip` reads every
#: variant of the chip instead and refuses if they disagree. Measured
#: 2026-09-06: five esp32s3 variants define each of the six, and all five
#: agree on every one -- MTMS 42, MTDI 41, MTDO 40, MTCK 39, USB_DN 19,
#: USB_DP 20. A first draft of this comment said the USB pair rested on a
#: single variant; that came from a scan whose chip detection missed most
#: variants, and re-counting through `variants_of_chip` refuted it.
_S3_FIXED = ("MTMS", "MTDI", "MTDO", "MTCK", "USB_DN", "USB_DP")
_ESP32S3 = (
    zephyr_connector("xiao_esp32s3", flat_gpio),
    arduino_flat("arduino-esp32", "XIAO_ESP32S3"),
    arduino_chip("arduino-esp32", "esp32s3", _S3_FIXED),
)
#: `SWDIO` and `SWCLK` are ordinary GPIOs on this part, and Seeed's own
#: board file is what says which: the net named `SWDIO` reaches the
#: EFR32MG24's pad `PA02` and `SWCLK` reaches `PA01`. Traced rather than
#: read off a net name, because Seeed name these nets for the function and
#: leave the pin to the footprint.
#:
#: **The part is named because this board carries two.** An
#: `ATSAMD11D14A-UUT` sits beside the MG24 as the on-board debugger, its
#: pads are on nets with the same names, and its own `PA02` is a different
#: pin of a different chip. Its pads are `SAMD11_*` on the header and are
#: answered in words below, not with a number.
_MG24 = (
    zephyr_connector("xiao_mg24", silabs_port_pin),
    seeed_pcb_traced("MG24.kicad_pcb", "EFR32MG24", ("SWDIO", "SWCLK")),
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
#: `NFC1` and `NFC2` are GPIOs on this part when the NFC protection bit is
#: clear, and Seeed name them beside their pin -- `P1.02{slash}NFC1`. The
#: SAMD11 and nRF54 debug pads on the same board are NOT here: they belong
#: to a second chip and are OH-170 US-3's question, not this source's.
_NRF54L15 = (
    zephyr_connector("xiao_nrf54l15", nordic_port_pin),
    seeed_pcb("nRF54L15.kicad_pcb", ("NFC1", "NFC2")),
)
#: **The NFC pair is P1.01 and P1.02 here and P1.02 and P1.03 on the
#: nRF54L15**, which is why every one of these reads its own board's file
#: rather than a sibling's. Two Nordic parts one generation apart, two
#: answers, and a family resemblance would have got one of them wrong --
#: OH-26's first trap, met again on parts closer than any it named.
#:
#: The nRF54's own debug pads are traced instead: Seeed name those nets for
#: the function and leave the pin to the footprint. Tracing them resolves
#: nothing and is still worth doing -- it establishes that they reach THIS
#: part and that its pads for them (`SWDIO_G2`, `SWDCLK_G1`) are outside the
#: `Pn.nn` numbering, which is what `_NRF54LM20A_DEBUG` then says in words.
#:
#: **`SHPHLD` and `nRF54_RST` were asked for here and could never answer.**
#: `SHPHLD` is a pin of the board's nPM1300, not of the MCU; `nRF54_RST`'s
#: net is `~{nRF54_RESET}` and no net carries the pad's own name. Both are
#: answered by `Board.reasons`, so nothing changes by removing them -- but
#: while they were listed, a traced label that reached nothing was
#: indistinguishable from one that reached a dedicated pad, and
#: `read_seeed_traced` now refuses the first.
_NRF54LM20A = (
    zephyr_connector("xiao_nrf54lm20a", nordic_port_pin),
    seeed_pcb("nRF54LM20A.kicad_pcb", ("NFC1", "NFC2")),
    seeed_pcb_traced(
        "nRF54LM20A.kicad_pcb", "nRF54LM20A",
        ("nRF54_SWDIO", "nRF54_SWCLK"),
    ),
)

#: **A dedicated pad is not an unread label**, and the chip's own footprint in
#: the vendor's board file is what tells the two apart. The RP2350's footprint
#: in `third_party/seeed-pcb/RP2350.kicad_pcb` names thirty pads `GPIO0`
#: through `GPIO29` and names `SWDIO` (pad 25) and `SWDCLK` (pad 24)
#: separately, alongside the supplies, the QSPI flash pins, USB and the
#: crystal. A pin outside the GPIO numbering has no GPIO number to report.
_DEDICATED_DEBUG = (
    "a dedicated debug pad of the {chip}, not a GPIO: {where} names its {which} "
    "pads {gpio} and names this one {label!r} separately, alongside the "
    "supplies and the crystal, so there is no GPIO number for it to have"
)
#: **Two sources name this pad's pin and it is still not written**, which is
#: the honest end of a search rather than a shrug. Seeed's own
#: `nRF54L15.kicad_pcb` calls a net `P2.00{slash}USR_LED` and puts exactly
#: three things on it: the MCU's own `P2.00` pad, a green LED, and a test
#: point. Zephyr states the same pin independently -- `led0` in
#: `boards/seeed/xiao_nrf54l15/xiao_nrf54l15_common.dtsi` is `<&gpio2 0>`,
#: which is P2.00. Two vendors, one answer, no disagreement to record.
#:
#: **The gap is one letter and it is not mine to close.** The pad is labelled
#: `USER_LED`; the vendor's net says `USR_LED`. No file here joins the two
#: spellings. `resolve` matches a pad through `alternatives(label)`, so
#: nothing keyed `USR_LED` reaches this pad, and the net carries no
#: castellated-pad footprint -- only the LED and a test point -- so which
#: exposed pad sits on it was never read. Matching them would be a join made
#: from resemblance, which is the trap OH-26 exists for. So the pin is
#: reported in words and left out of `chip_pin`, where a reader would take it
#: for something this tool had established.
_NRF54L15_USER_LED = (
    ("USER_LED",
     "the board's user LED. Two sources name its pin and neither names this "
     "pad: Seeed's own nRF54L15.kicad_pcb has a net 'P2.00{slash}USR_LED' "
     "carrying the nRF54L15's own P2.00 pad, a green LED and a test point, "
     "and Zephyr's xiao_nrf54l15 board states the same pin independently as "
     "`led0 = <&gpio2 0>`. NOT written into `chip_pin`: the vendor spells "
     "this pad USER_LED in the symbol library the labels come from and "
     "USR_LED in the board file, and no file here says those are one pad"),
)
#: **The three boards Seeed publish no `.kicad_pcb` for.** The RP2350's and
#: both Nordics' debug pads were answered by tracing the vendor's own board
#: file; `third_party/seeed-pcb/` holds none for the RP2040, the SAMD21 or the
#: nRF52840, so there is nothing here to trace and these six pads carried the
#: generic "no package defines this label" instead.
#:
#: What Seeed DO publish for each is a wiki page, fetched into
#: `third_party/seeed-xiao/document/` by the same command as the symbol
#: library, and every one of the three names SWD among the board's
#: interfaces. That is a source, and not having looked at it was the gap.
#:
#: **NOT claimed: that the silicon has no GPIO behind the pad.** The other
#: debug reasons say that because a footprint showed it; nothing here does.
#: It is true of some parts and false of others, and which is a fact about
#: the chip that no file in this tree states.
#:
#: **Also not claimed: that SWD sits outside the header pin count.** Only the
#: nRF52840's page is unambiguous, listing `1xSWD` beside `11xGPIO(PWM)`. The
#: RP2040's and the SAMD21's read either way -- "14 GPIO PINs, on which there
#: are ... 1 SWD Bonding pad interface" can be parsed with SWD inside or
#: outside the fourteen. So the sentence claims only what all three support:
#: the vendor documents the interface and publishes no pin number for it.
_SWD_DOCUMENTED = (
    "the SWD debug interface, which Seeed's own page for this board names: "
    "{where} says {quote!r}. No pin number for it is published anywhere in "
    "this tree -- no board-support package file this tool reads for this "
    "board mentions SWDIO or SWCLK, and Seeed publish no board CAD for this "
    "part as they do for the RP2350 and both nRF54s. NOT claimed: whether "
    "the chip has a GPIO behind this pad, which no file here states"
)
_RP2040_SWD = tuple(
    (label, _SWD_DOCUMENTED.format(
        where="XIAO-RP2040.md", quote="1 SWD Bonding pad interface"))
    for label in ("SWDIO", "SWCLK")
)
_SAMD21_SWD = tuple(
    (label, _SWD_DOCUMENTED.format(
        where="Seeeduino-XIAO.md", quote="1 SWD pad interface"))
    for label in ("SWDIO", "SWCLK")
)
_NRF52840_SWD = tuple(
    (label, _SWD_DOCUMENTED.format(
        where="XIAO_BLE.md", quote="1xSWD"))
    for label in ("SWDIO", "SWCLK")
)
_RP2350_DEBUG = tuple(
    (label, _DEDICATED_DEBUG.format(
        chip="RP2350", where="Seeed's own RP2350.kicad_pcb", which="thirty GPIO",
        gpio="GPIO0 through GPIO29", label=label))
    for label in ("SWDIO", "SWDCLK")
)
#: The same shape on Nordic's part, which numbers its GPIOs by port and bit:
#: `nRF54L15.kicad_pcb` gives U6 thirty-two pads named `Pn.nn` and names
#: `SWDIO` and `SWDCLK` apart from them.
#: The pad's own name is passed rather than derived. A first version built
#: it with `label.replace("nRF54_", "SWD")`, which turned `nRF54_SWDIO` into
#: `SWDSWDIO` -- a name the board file does not contain, quoted inside a
#: sentence claiming the board file names it.
_NRF54L15_DEBUG = tuple(
    (label, _DEDICATED_DEBUG.format(
        chip="nRF54L15", where="Seeed's own nRF54L15.kicad_pcb",
        which="thirty-two", gpio="P0.00 through P2.10 by port and bit",
        label=named))
    for label, named in (("nRF54_SWDIO", "SWDIO"), ("nRF54_SWCLK", "SWDCLK"))
)

#: **A pin of the wrong chip is worse than no pin**, so these are answered in
#: words. `chip_pin` means "the pin of THIS board's MCU that this pad
#: reaches", and every label below reaches the on-board debugger instead --
#: an `ATSAMD11D14A-UUT`, which Seeed's own board files name beside the main
#: part. Traced, the MG24's `SAMD11_SWDIO` reaches that chip's `PA31` and
#: `SAMD11_SWCLK` its `PA30`; writing either into `chip_pin` would put a
#: SAMD11 pin in a field the page reads as an MG24 pin, and the page has no
#: way to tell.
_SECOND_CHIP = (
    "this pad reaches the on-board debugger, an ATSAMD11D14A, and not this "
    "board's own MCU; `chip_pin` names a pin of the board's MCU, so a number "
    "here would be a pin of the wrong chip. Seeed's own board file names both "
    "parts, and the debugger's pins are reachable from it if they are ever "
    "wanted under a field that says which chip it means"
)
#: **"Reaches" is a topology claim and only six of these nine were traced.**
#: `SAMD11_SWDIO` and `SAMD11_SWCLK` sit on a net of their own name on the
#: debugger's own footprint, on all three boards that carry them. `SAMD11_EN`
#: and `SAMD11_RST2` sit on no net of that name anywhere in the vendor's
#: file, so where they go has not been read and the sentence must not say.
#:
#: This is the same split `nRF54_RST` already forced: a category claim, that
#: the label is not the board's MCU, is provable from the label and from what
#: `chip_pin` means. A topology claim needs a trace. Saying both in one
#: sentence made three pads assert something nothing had looked up.
_SECOND_CHIP_UNTRACED = (
    "this pad is named for the on-board debugger, an ATSAMD11D14A, and not "
    "for this board's own MCU; `chip_pin` names a pin of the board's MCU, so "
    "a number here would be a pin of the wrong chip. NOT claimed: which pin "
    "it reaches. No net in Seeed's own board file carries this pad's name, "
    "so unlike the SWDIO and SWCLK pads on the same header nothing here was "
    "traced"
)
_SAMD11_TRACED = ("SAMD11_SWDIO", "SAMD11_SWCLK")
_SAMD11_UNTRACED = ("SAMD11_EN", "SAMD11_RST2")
_MG24_DEBUGGER = (
    tuple((label, _SECOND_CHIP) for label in _SAMD11_TRACED)
    + tuple((label, _SECOND_CHIP_UNTRACED) for label in _SAMD11_UNTRACED)
)

#: The nRF54LM20A's own debug pads, which its footprint names `SWDIO_G2` and
#: `SWDCLK_G1` -- outside the `Pn.nn` numbering its GPIOs use, so there is no
#: pin number for them to have. The same shape as the RP2350's and the
#: nRF54L15's, with this part's own spelling.
#: **Sixty-six, not thirty-two.** The count was copied from the nRF54L15's
#: reason, where it is right. This part's footprint carries P0.00-P0.09,
#: P1.00-P1.31, P2.00-P2.10 and P3.00-P3.12.
_NRF54LM20A_DEBUG = tuple(
    (label, _DEDICATED_DEBUG.format(
        chip="nRF54LM20A", where="Seeed's own nRF54LM20A.kicad_pcb",
        which="sixty-six", gpio="P0.00 through P3.12 by port and bit",
        label=named))
    for label, named in (("nRF54_SWDIO", "SWDIO_G2"), ("nRF54_SWCLK", "SWDCLK_G1"))
)

#: **Reset, which is neither a GPIO nor a debug pad.** Seeed's own
#: `nRF54LM20A.kicad_pcb` gives the MCU footprint a pad `nRESET_F2` on the net
#: `~{nRF54_RESET}`, apart from all sixty-six of its `Pn.nn` pads. A part's
#: reset is a dedicated pin, so there is no port and bit for this label to
#: name -- the same fact `_DEDICATED_DEBUG` states about SWDIO and SWCLK, and
#: the reason those two say it while this one said "no package defines this
#: label" was that nobody had written it down.
#:
#: **What is NOT claimed here: that this pad is on that net.** No net in that
#: file is called `nRF54_RST`; the nearest, `nRF54_RST_CTL`, runs from the
#: on-board ATSAMD11 debugger's `PA04_A3` to the gate of an LN237N3T5G whose
#: drain sits on `~{nRF54_RESET}`. So the board's reset line is switched
#: rather than driven straight through, and which side of that switch this
#: exposed pad is on has not been read. It does not need to be: the sentence
#: below is about the part's reset being a dedicated pin, which is true either
#: way, and a `why_null` that claimed a trace it had not followed would be the
#: mistake this ticket has already had to correct twice.
_DEDICATED_RESET = (
    "a reset pad of the {chip}, not a GPIO: {where} names that part's reset "
    "{pin!r} on the net {net!r}, apart from all {which} of its pads numbered "
    "{gpio}. A reset is a dedicated pin of the silicon, so there is no GPIO "
    "number for this label to have"
)
_NRF54LM20A_RESET = (
    ("nRF54_RST", _DEDICATED_RESET.format(
        chip="nRF54LM20A", where="Seeed's own nRF54LM20A.kicad_pcb",
        pin="nRESET_F2", net="~{nRF54_RESET}", which="sixty-six",
        gpio="P0.00 through P3.12 by port and bit")),
)

#: **A third chip, and not even a microcontroller.** `SHPHLD` reaches an
#: `nPM1300-CAAA` -- Nordic's power-management IC -- on its `SHPHLD_D4` pad.
#: Ship-hold is that part's own function, so the label names nothing on the
#: board's MCU at all, which is a different answer again from a debugger's
#: pin and from a dedicated debug pad.
_POWER_IC = (
    "this pad reaches the board's power-management IC, an nPM1300, on its "
    "SHPHLD_D4 pin -- not the board's MCU and not its debugger. `chip_pin` "
    "names a pin of the board's MCU, and this label names none. Read from "
    "Seeed's own nRF54LM20A.kicad_pcb, which carries all three parts"
)
_NRF54LM20A_OTHER = (("SHPHLD", _POWER_IC),)

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
    "XIAO-MG24-SMD": Board("EFR32MG24", _MG24, reasons=_MG24_DEBUGGER),
    "XIAO-RP2040-DIP": Board("RP2040", _RP2040, on_board=("LED",)),
    "XIAO-RP2040-SMD": Board(
        "RP2040", _RP2040, on_board=("LED",), reasons=_RP2040_SWD
    ),
    "XIAO-RP2350-DIP": Board("RP2350", _RP2350),
    "XIAO-RP2350-SMD": Board("RP2350", _RP2350, reasons=_RP2350_DEBUG),
    "XIAO-SAMD21-DIP": Board("SAMD21", _SAMD21),
    "XIAO-SAMD21-SMD": Board("SAMD21", _SAMD21, reasons=_SAMD21_SWD),
    # Nobody has published this one. Zephyr has no xiao_stm32c5 board and
    # Seeed has released no core for it, so every pad stays null and the
    # report says why rather than the board going missing from the run.
    # The one board no board-support package covers. Seeed's schematic
    # symbol library names a pin for two of its 35 pads and for none of the
    # others, which is the whole of what has been published about this part.
    "XIAO-XIAO STM32C5-SMD": Board(
        "STM32C5",
        (seeed_symbol("XIAO-STM32C5-SMD", ("SWDIO", "SWCLK")),),
    ),
    "XIAO-nRF52840-DIP": Board("nRF52840", _NRF52840),
    "XIAO-nRF52840-SMD": Board("nRF52840", _NRF52840, reasons=_NRF52840_SWD),
    "XIAO-nRF54LM20A-DIP": Board(
        "nRF54LM20A", _NRF54LM20A, reasons=_NRF54LM20A_OTHER
    ),
    "XIAO-nRF54LM20A-SMD": Board(
        "nRF54LM20A", _NRF54LM20A,
        reasons=(_MG24_DEBUGGER + _NRF54LM20A_DEBUG + _NRF54LM20A_RESET
                 + _NRF54LM20A_OTHER),
    ),
    "XIAO-nRF54l15-DIP": Board("nRF54L15", _NRF54L15),
    "XIAO-nRF54l15-SMD": Board(
        "nRF54L15", _NRF54L15,
        reasons=_NRF54L15_DEBUG + _MG24_DEBUGGER + _NRF54L15_USER_LED,
    ),
}

#: Boards that are rows in `tools/board_manifest.py` (OH-176), each read from
#: the one variant its row names, with the labels its row opts in. Registered
#: like any other, and kept out of one thing: a chip module's table, which is
#: keyed by the labels of the other boards of that chip. One chip has one
#: table, and a row brings labels of its own.
MANIFEST: dict[str, Board] = {
    entry.board: Board(
        entry.chip,
        (arduino_flat(entry.package, entry.variant, extras=entry.labels),),
        reasons=entry.reasons,
    )
    for entry in board_manifest.ROWS
}
if set(MANIFEST) & set(BOARDS):
    raise PindefError(
        f"tools/board_manifest.py has a row for {sorted(set(MANIFEST) & set(BOARDS))}, "
        f"which BOARDS already registers; a row may not replace a board"
    )
BOARDS.update(MANIFEST)


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


def _digest(texts: tuple[str, ...]) -> str:
    """The first twelve hex of a sha256 over the files a source read.

    For sources that are not a git checkout. Stable across machines and across
    a re-download of the same file, which a commit id would not be.
    """
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
    return digest.hexdigest()[:12]


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
        checkout = source.root if source.root is not None else bsp_dir / source.package
        if not checkout.is_dir():
            raise PindefError(
                f"{checkout} is missing; "
                f"{PACKAGES[source.package].how_to_fetch()}"
            )
        texts = []
        # `expand` names files the source could not know until it read the
        # package's own board table; `paths` is still what the citation says,
        # because "every esp32s3 variant at this revision" is the honest
        # description and a list of thirty filenames is not.
        wanted = source.expand(checkout) if source.expand else source.paths
        for relative in wanted:
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
        # **The digest is the identifier because neither of these checkouts
        # is one `revision()` can read**, which looks at
        # `third_party/bsp/<name>`. The two `cloned=False` packages are not
        # alike beyond that, and a first draft of this comment described only
        # one of them:
        #
        #   seeed-pcb    a zip extracted into the working tree, with no `.git`
        #                of its own -- so `git rev-parse` there answers with
        #                OpenHardware's OWN head, a revision that says nothing
        #                about the vendor's file and moves every time this
        #                project commits. That is the trap this guards.
        #   seeed-xiao   a real git checkout with its own head (`f07e6ff` when
        #                measured), so the trap above does NOT apply to it.
        #
        # The digest still wins for both: it names the bytes that were read,
        # which is what a reader compares a fresh download against, and it is
        # the same answer whether or not the source happens to carry history.
        stamp = (f"sha256:{_digest(texts)}" if source.root is not None
                 else revision(checkout))
        citation = f"{source.package} {', '.join(source.paths)} @ {stamp}"
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
    "covering this board. Anything named in `packages` is a source read anyway "
    "-- the vendor's own CAD rather than firmware -- and resolves a pad only "
    "where it names the pin outright. Every pad it does not reach is null and "
    "says why in its own `why_null`."
)

NOT_PUBLISHED = "no board-support package covering this board defines this label"
DISPUTED = "the packages disagree; recorded rather than averaged, so the pad stays null"

#: The reason on a board no package covers, which is a different fact from
#: `NOT_PUBLISHED` and reads identically if it is not told apart: "no package
#: covering this board defines this label" is vacuously true of all 35 pads of
#: the XIAO STM32C5 and hides that the count of packages covering it is zero.
#: OH-26 searched and found no Zephyr board and no Seeed core for that part.
NO_PACKAGE_AT_ALL = (
    "no board-support package covers this board at all, and the vendor's own "
    "CAD does not name a pin beside this pad; that is a gap in what the vendor "
    "has published, not in this tool"
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
    # A pad still null on a board no FIRMWARE package covers is null for ONE
    # reason, and it is not the per-label one `pad_report` can see from a pad
    # alone. The condition is `firmware` and not `board.sources`: this board
    # has a source now -- Seeed's schematic symbols -- and two of its pads
    # resolve from it, while the sentence about board-support packages stays
    # exactly as true of the other thirty-three as it ever was.
    if not any(PACKAGES[source.package].firmware for source in board.sources):
        for pad in pads:
            if pad["chip_pin"] is None:
                pad["reason"] = NO_PACKAGE_AT_ALL
    # A label the registry has a better reason for, applied only where nothing
    # resolved it -- a reason never overrides an answer.
    reasons = dict(board.reasons)
    for pad in pads:
        if pad["chip_pin"] is None and pad["label"] in reasons:
            pad["reason"] = reasons[pad["label"]]
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
                # Neither `cloned=False` checkout lives under
                # `third_party/bsp/`, which is the only place `revision()`
                # looks, so both are identified by a digest of the bytes read.
                # `seeed-pcb` additionally has no `.git` of its own and would
                # answer OpenHardware's head; `seeed-xiao` does have one. The
                # long form of this is beside `stamp` in `published_pins`.
                "revision": (revision(bsp_dir / package)
                             if PACKAGES[package].cloned
                             else _digest(tuple(
                                 (source.root / one).read_text(
                                     encoding="utf-8", errors="replace")
                                 for source in board.sources
                                 if source.package == package and source.root
                                 for one in source.paths))),
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


def header_boards(chip: str) -> tuple[str, ...]:
    """The registered boards whose labels key this chip's module table."""
    return tuple(
        name for name, board in sorted(BOARDS.items())
        if board.chip == chip and name not in MANIFEST
    )


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
    names = header_boards(chip)
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
                   unnumbered: list[str] | None = None,
                   resolved: int = 0, unresolved: int = 0,
                   keyed_by: tuple[str, ...] = ()) -> str:
    """What a board file says about its own `pin`, `chip_pin` and `chip_index`.

    Three shapes, because three things can be true of a board. `pin` is null
    on every one of them and still means what `webui/pinmap.py` says -- the
    rcontrol index of a PICSimLab board that does not exist. What varies is
    whether any package publishes this board's pins at all, and, where one
    does, whether a module here reads a level through the same table.
    `keyed_by` is a fourth: a module describes the chip, and its table is
    keyed by those boards' labels and not this one's.

    The uncovered case is its own sentence rather than the undescribed one
    with an empty `packages` list: "the join is ready, not made" would be
    false on a board with nothing to join, and that is the XIAO STM32C5.

    **The uncovered sentence counts its pads and does not assert them.** It
    used to read "null on every pad here", which was true only while nothing
    at all had been read for that board. Two of its pads now resolve from
    Seeed's own schematic symbols, and a number written into prose that the
    code does not derive is one that goes stale without a test noticing --
    which has already happened twice in this file.
    """
    head = (
        "Every `pin` is null: that field is the rcontrol pin index of a PICSimLab "
        "board implementation (webui/pinmap.py), and none exists for this board. "
    )
    if not covered:
        why = (
            f"because no board-support package covers this board at all -- no "
            f"Zephyr board and no vendor core publishes a {chip} XIAO (OH-26)"
        )
        if not resolved:
            return head + (
                f"`chip_pin` and `chip_index` are null on every pad here, and "
                f"`pindefs` names no package, {why}. Each pad says the same in "
                f"its own `why_null`. The pin view reports every pad as not "
                f"modelled, and will until the vendor publishes something to read."
            )
        body = (
            f"`chip_pin` and `chip_index` are null on {unresolved} of these "
            f"{resolved + unresolved} pads, {why}. The other {resolved} were "
            f"read from the vendor's own CAD, named in `pindefs`, which is a "
            f"schematic and not firmware. Those {resolved} pads are the only "
            f"ones in the symbol read for this board whose name carries a pin "
            f"in a spelling this tool recognises: `GPIOn`, `PAn` through "
            f"`PDn`, `Pn.nn`. Ports E through H are not among those "
            f"spellings, so what was checked is those three and not every "
            f"spelling there could be. Each null pad says which of the two it is in "
            f"its own `why_null`. The pin view reports every null pad as not "
            f"modelled, and will until the vendor publishes something to read."
        )
        # **The uncovered branch owes this sentence too**, and returning
        # before it was a hole the moment anything resolved here: the XIAO
        # STM32C5's two pads are `PA13` and `PA14`, port-and-bit names with no
        # flat number, which is OH-26's own category. Every other file
        # carrying such a pin says why `chip_index` is null on it, and this
        # one would have been the single file that did not.
        if unnumbered:
            body += unnumbered_sentence(chip, unnumbered, described)
        return head + body
    head += (
        "`chip_pin` and `chip_index` are what tools/import_pindefs.py read out of "
        "the board-support packages named in `pindefs`; a pad whose `chip_pin` is "
        "null says why in `why_null`. "
    )
    if described and keyed_by:
        # A manifest board (OH-176): the module describes the chip, and its
        # table is keyed by `keyed_by`'s labels rather than this board's.
        body = (
            f"webui/boards/{chip.lower().replace('-', '')}.py describes the "
            f"{chip}, and its table is keyed by the labels of "
            f"{', '.join(keyed_by)}, which are not this board's; no level is "
            f"read through it for any pad here, and `chip_pin` is recorded so "
            f"that the join is ready, not made."
        )
    elif described:
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
    modules_dir: pathlib.Path | None = None,
) -> dict:
    """The board file's document with the report written into it.

    Joined by POSITION, which is exact because `board_report` below reads
    this same file in this same call and returns one entry per pad in its
    order. The pad NUMBER the report carries for other consumers is not a
    key and could not be one: the nRF54LM20A SMD footprint numbers all three
    of its `GND` pads `46`, which is how Seeed's CAD names a multi-pad net.
    Everything else in the document is kept as it is.

    `modules_dir` is where the chip modules are when the file is not beside
    them: `tools/board_manifest.py` builds a whole board file from pads it
    staged elsewhere, so that a failure leaves `webui/boards/` untouched.
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

    # **Not `bool(packages)`.** The XIAO STM32C5 now names a package -- Seeed's
    # schematic symbol library -- and no board-support package covers it, so a
    # truthiness test would have `assumption_for` tell a reader that a core
    # publishes this board's pins. It is CAD; see `Package.firmware`.
    covered = any(PACKAGES[entry["name"]].firmware
                  for entry in report["packages"])
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
    described = module_path(
        report["chip"], boards_dir if modules_dir is None else modules_dir
    ).is_file()
    keyed_by = header_boards(report["chip"]) if name in MANIFEST else ()
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
                report["chip"], described, covered, spellings,
                report["resolved"], report["unresolved"], keyed_by,
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
    """Which packages cover which board, and which board no firmware covers.

    **The second half of that sentence stopped working and this is the fix.**
    The column keyed on `board.sources` being empty, which was the same test
    as "no package publishes this board" only while the uncovered board named
    nothing at all. The XIAO STM32C5 now names `seeed-xiao` -- a schematic
    symbol library, which is CAD -- so `--list` showed it exactly like the
    twenty-four boards a vendor core covers, and `not board.sources` became a
    branch nothing in the registry can enter.
    """
    lines = []
    for name in sorted(BOARDS):
        board = BOARDS[name]
        sources = ", ".join(f"{s.package}:{s.paths[0]}" for s in board.sources)
        covered = any(PACKAGES[s.package].firmware for s in board.sources)
        note = "" if covered else "  <- no board-support package publishes this board"
        lines.append(f"{name:24s} {board.chip:11s} {sources}{note}")
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
        clonable = [one for one in PACKAGES.values() if one.cloned]
        for package in clonable:
            print(f"--- {package.name}: {package.repository}")
            fetch(package)
        for package in clonable:
            print(f"{package.name:16s} {revision(BSP_DIR / package.name)}  {package.licence}")
        # Named rather than skipped silently: a source this cannot fetch is
        # one somebody has to go and get, and a run that says nothing about it
        # looks like a run that covered everything.
        for package in PACKAGES.values():
            if not package.cloned:
                print(f"{package.name:16s} not cloned by --fetch: "
                      f"{package.how_to_fetch()}")
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
