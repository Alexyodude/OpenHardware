#!/usr/bin/env python3
# OpenHardware - the connectivity a running board consults, from its schematic.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Extract the small subgraph a simulated board needs, or say why there is none.

Not a general netlist. The questions a *running* board asks, which are five:
which MCU pin reaches which header pad, which indicator sits on which GPIO,
where the USB lines go, where the crystal goes, and what the regulator feeds.
Everything else in a 48-net schematic is decoupling.

## Why a footprint cannot answer this

`tools/import_board.py` reads pad positions and the net name printed beside
each pad. On the board this was written against, seven header pads are
silkscreened `GPIO0` to `GPIO6`. **Not one of them is on the MCU GPIO of that
number:**

    pad GPIO0 -> IO18      pad GPIO3 -> IO10      pad GPIO5 -> IO23
    pad GPIO1 -> IO22      pad GPIO4 -> IO8       pad GPIO6 -> IO15
    pad GPIO2 -> IO11

Those are Adafruit Feather positional labels, kept so the board is pin
compatible with a Feather, and they are what a person reads off the silkscreen.
A pin map built from them would be wrong seven times and look right. Only the
netlist says otherwise, and `gpio_to_pad` reports `pad_label_agrees` for every
row so the disagreement is in the output rather than in a commit message.

## The LED, which is the case this ticket exists for

`tools/import_firmware.py` records that XIAO ESP32-C3 defines no
`LED_BUILTIN`, so a fixture blink had to be rewritten. The board here has the
opposite problem and it is worse: it *does* define one, and it is not a pin.

    #define PIN_RGB_LED 23
    static const uint8_t LED_BUILTIN = SOC_GPIO_PIN_COUNT + PIN_RGB_LED;

`LED_BUILTIN` is deliberately past the end of the GPIO range — a sentinel
arduino-esp32 uses to send `digitalWrite` to an addressable-LED driver instead
of to a port. Firmware compiles either way. A simulator that took
`LED_BUILTIN` for a pin index would run off the end of its port model. The
netlist gives the answer the define does not: **GPIO23, to the data input of a
WS2812, with no series resistor, because an addressable LED does not have
one.**

## Roles come from reference designators, which are a real convention

`D5` is a diode because it is called `D5`. That is IEEE 315 / ANSI Y32.2 and
holds across vendors — unlike an EAGLE library name, which is whatever
SparkFun or Adafruit called their folder. The designator is refined by the
library and deviceset text only where the file makes it decisive: every `D` is
a diode, and one whose library or deviceset says LED is an LED.

A part whose designator is not in the table — this board has `SHLD`, `MEAS`,
`CHG`, `BOOT` — gets the role `unknown` and appears in `unresolved`. That is
the honest outcome and it is short.

## PDF only is an answer, not a failure

A schematic PDF is a picture of a netlist and no parsing turns one into the
other. Handed one, this reports `status: pdf-only` and stops: a fact about the
vendor, recorded, with the board's LED wiring left explicitly unknown. An
unknown that is written down is usable. One that is inferred is not.

    python tools/import_schematic.py <file.sch> --header J1
    python tools/import_schematic.py <file.pdf>
"""

from __future__ import annotations

import argparse
import enum
import json
import pathlib
import re
import sys
import typing

try:
    from tools import eagle
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import eagle


class SchematicError(Exception):
    """The file cannot become a connectivity report, and here is why."""


class Status(enum.Enum):
    """What kind of answer this report is.

    The two must never share a column. `NETLIST` means the connectivity was
    read; `PDF_ONLY` means the vendor published a rendering and the answers
    are unknown — which is a finding about the vendor, not a failure here.
    """

    NETLIST = ("netlist", "the schematic source was parsed and its nets read")
    PDF_ONLY = (
        "pdf-only",
        "the vendor publishes a schematic, but only as a picture of one",
    )

    def __init__(self, label: str, gloss: str) -> None:
        self.label = label
        self.gloss = gloss


#: Reference-designator prefixes, IEEE 315 / ANSI Y32.2. A convention rather
#: than a guarantee: a part whose prefix is not here is reported `unknown`,
#: never guessed at from its position or its neighbours.
DESIGNATORS = {
    "C": "capacitor",
    "D": "diode",
    "FB": "ferrite",
    "GND": "supply",
    "J": "connector",
    "L": "inductor",
    "Q": "transistor",
    "R": "resistor",
    "SUPPLY": "supply",
    "SW": "switch",
    "TP": "testpoint",
    "U": "ic",
    "X": "crystal",
    "Y": "crystal",
}
#: How a pin name spells a GPIO number. `IO23` and `SDIO_D3/IO23` are the same
#: pin: Espressif modules stack every alternate function into one name,
#: slash-separated, and the bare `IOn` is the port bit. Only these two
#: spellings are read; a part using another is reported as having no GPIO pins
#: rather than being scanned with a looser pattern that would match anything.
GPIO_SPELLINGS = (
    re.compile(r"(?:^|/)IO(\d+)$"),
    re.compile(r"(?:^|/)GPIO(\d+)$"),
)
#: Pin names that mark a USB differential pair, in the spellings seen.
USB_PINS = frozenset({"D+", "D-", "DP", "DM"})
#: Substring of an MCU pin name that marks a crystal connection.
CRYSTAL_MARK = "XTAL"
#: Pin names by which a regulator announces its output.
REGULATOR_OUT = frozenset({"OUT", "VOUT", "VO"})


_PREFIX = re.compile(r"^([A-Za-z_]+)")


def role_of(part: eagle.Part) -> str:
    """What kind of component this is, from its reference designator.

    The designator is the alphabetic run at the start of the name, so `SUPPLY13`
    is `SUPPLY` and `D5` is `D` with no ambiguity about which prefix wins. A
    `D` whose library or deviceset says LED is an LED rather than a plain
    diode — the only refinement, and it is taken from text the file states.
    """
    match = _PREFIX.match(part.name)
    role = DESIGNATORS.get(match.group(1).upper(), "unknown") if match else "unknown"
    if role == "diode" and "LED" in f"{part.library} {part.deviceset}".upper():
        return "led"
    return role


def gpio_of(pin: str) -> int | None:
    """The GPIO number a pin name states, or None when it states none."""
    for spelling in GPIO_SPELLINGS:
        found = spelling.search(pin)
        if found:
            return int(found.group(1))
    return None


class Chosen(typing.NamedTuple):
    """A part this tool picked rather than was told, and what it beat."""

    part: str
    gpio_pins: int
    runner_up: str | None
    runner_up_pins: int


def choose_mcu(schematic: eagle.Schematic) -> Chosen:
    """The part with the most GPIO-named pins, and the one that came second.

    Not a guess dressed as a fact: the count and the runner-up go into the
    report, so a reader can see the margin. On the board this was written
    against it is 23 pins against 7, and the 7 belong to the *header*, whose
    pins are named after silkscreen positions. A rule that took the header for
    the MCU would invert every row of `gpio_to_pad`, so the margin is the
    thing worth showing.
    """
    counts = sorted(
        (
            (sum(1 for pin in schematic.pins_of(part.name) if gpio_of(pin) is not None), part.name)
            for part in schematic.parts
        ),
        reverse=True,
    )
    if not counts or counts[0][0] == 0:
        raise SchematicError(
            f"{schematic.name}: no part has a pin named like a GPIO in any "
            f"spelling this reads ({', '.join(s.pattern for s in GPIO_SPELLINGS)}). "
            f"Either this is not an MCU board, or its family spells pins some "
            f"other way and that spelling has to be added before the answers "
            f"here would mean anything."
        )
    best = counts[0]
    second = counts[1] if len(counts) > 1 and counts[1][0] else (0, None)
    return Chosen(best[1], best[0], second[1], second[0])


class Link(typing.NamedTuple):
    """One MCU GPIO, and the header pad it reaches."""

    gpio: int
    mcu_pin: str
    net: str
    pad: str
    #: True when the pad's own name states the GPIO it is actually on, False
    #: when it states a different one, and **None when it states no GPIO at
    #: all**. The three are not the same finding and collapsing them would
    #: make the report shout: a pad called `SDA` names a function rather than
    #: a number and is not wrong about anything, while a pad called `GPIO5`
    #: sitting on IO23 is wrong in the way that silently breaks a pin map.
    pad_label_agrees: bool | None


def gpio_to_pad(
    schematic: eagle.Schematic, mcu: str, header: str
) -> tuple[Link, ...]:
    """Every net carrying both an MCU GPIO pin and a header pin.

    One hop, deliberately. A net is an electrical node, so "reaches" needs no
    traversal: if the module pin and the header pin are on the same net they
    are the same node. Anything needing two hops is a different question and
    is not answered here rather than being answered approximately.
    """
    links = []
    for net in schematic.nets:
        pads = net.on(header)
        if not pads:
            continue
        for ref in net.on(mcu):
            gpio = gpio_of(ref.pin)
            if gpio is None:
                continue
            for pad in pads:
                claimed = gpio_of(pad.pin)
                links.append(
                    Link(
                        gpio,
                        ref.pin,
                        net.name,
                        pad.pin,
                        None if claimed is None else claimed == gpio,
                    )
                )
    return tuple(sorted(links))


#: A net is a supply rail when an EAGLE power symbol sits on it. That is a
#: part in the file, not a threshold on pin count: `GND` here has 29 `GND*`
#: symbols on it and `IO23/STAT` has none, so the test is exact and needs no
#: tuning. Pin count would have been a guess — `IO23/STAT` has three pins and
#: is a signal, while a two-pin net can be either.
def is_rail(net: eagle.Net, roles: dict[str, str]) -> bool:
    return any(roles.get(ref.part) == "supply" for ref in net.pins)


class Indicator(typing.NamedTuple):
    """One LED, the GPIO that drives it, and what is in between."""

    part: str
    deviceset: str
    #: The net the drive signal is on, or None when nothing drives this LED.
    net: str | None
    led_pin: str | None
    gpio: int | None
    mcu_pin: str | None
    #: Resistors between the GPIO and the LED. Empty is a real answer, not a
    #: missing one: an addressable LED takes a data line and has no series
    #: resistor. `note` says which case this is.
    series_resistors: tuple[str, ...]
    #: What drives it when a GPIO does not — `U3.STAT` for a charger status
    #: LED. Recorded because "not firmware-drivable" is the useful half of the
    #: answer and "we found nothing" is not the same statement.
    driver: str | None
    note: str


def indicators(schematic: eagle.Schematic, mcu: str) -> tuple[Indicator, ...]:
    """One row per LED: what drives it, and through what.

    Every LED gets a row, including the ones firmware cannot touch. A report
    listing only the drivable ones would look like it had found every LED on
    the board when it had found a third of them, and "this LED is the charger's
    and not yours" is the answer that stops somebody wiring a blink to it.

    Three ways an LED is reached, tried in order and each one stated:

    1. **A GPIO on one of its own nets.** The addressable case, and the one
       this ticket exists for.
    2. **A GPIO one resistor away**, through a net that is not a rail. The
       classic GPIO-resistor-LED-ground topology. One resistor, not a search:
       anything further is a different question and is left unanswered rather
       than answered approximately.
    3. **An IC pin on a non-rail net**, which is a status LED wired to a
       driver rather than to firmware.

    A rail is excluded from all three because an LED's anode sitting on 3.3V
    says nothing about what switches it, and the twenty other things on that
    rail are not in series with anything.
    """
    roles = {part.name: role_of(part) for part in schematic.parts}
    devicesets = {part.name: part.deviceset for part in schematic.parts}
    signal_nets = [net for net in schematic.nets if not is_rail(net, roles)]

    def gpio_on(net: eagle.Net) -> tuple[int, str] | None:
        for ref in net.on(mcu):
            number = gpio_of(ref.pin)
            if number is not None:
                return number, ref.pin
        return None

    found = []
    for name in sorted(part.name for part in schematic.parts if roles[part.name] == "led"):
        deviceset = devicesets.get(name, "")
        own = [net for net in signal_nets if net.on(name)]

        direct = next(((net, gpio_on(net)) for net in own if gpio_on(net)), None)
        if direct:
            net, (number, pin) = direct
            resistors = tuple(
                sorted({r.part for r in net.pins if roles.get(r.part) == "resistor"})
            )
            found.append(
                Indicator(
                    name,
                    deviceset,
                    net.name,
                    net.on(name)[0].pin,
                    number,
                    pin,
                    resistors,
                    None,
                    f"driven directly by {pin}"
                    + (
                        f" through {', '.join(resistors)}"
                        if resistors
                        else ". No series resistor, which for an addressable LED "
                        "is correct: this is its data line, not its supply"
                    ),
                )
            )
            continue

        hop = _through_a_resistor(own, signal_nets, roles, gpio_on, name)
        if hop:
            found.append(hop._replace(part=name, deviceset=deviceset))
            continue

        driver = _driven_by_an_ic(own, roles, name, mcu)
        found.append(
            Indicator(
                name,
                deviceset,
                driver[0] if driver else None,
                driver[1] if driver else None,
                None,
                None,
                (),
                driver[2] if driver else None,
                f"no GPIO reaches it; {driver[2]} drives it" if driver
                else "no GPIO reaches it directly or through one resistor, and "
                "no other IC drives it, so firmware cannot switch this one. "
                "What was searched is what is claimed: a longer path would not "
                "have been followed",
            )
        )
    return tuple(found)


def _through_a_resistor(own, signal_nets, roles, gpio_on, led) -> Indicator | None:
    """A GPIO one resistor away from the LED, or None. One hop, never two."""
    for net in own:
        for ref in net.pins:
            if roles.get(ref.part) != "resistor":
                continue
            for other in signal_nets:
                if other.name == net.name or not other.on(ref.part):
                    continue
                reached = gpio_on(other)
                if reached:
                    return Indicator(
                        led,
                        "",
                        other.name,
                        net.on(led)[0].pin,
                        reached[0],
                        reached[1],
                        (ref.part,),
                        None,
                        f"driven by {reached[1]} through {ref.part}",
                    )
    return None


def _driven_by_an_ic(own, roles, led, mcu) -> tuple[str, str, str] | None:
    """(net, led pin, driver) when an IC other than the MCU is on a signal net."""
    for net in own:
        for ref in net.pins:
            if ref.part != led and ref.part != mcu and roles.get(ref.part) == "ic":
                return net.name, net.on(led)[0].pin, f"{ref.part}.{ref.pin}"
    return None

class Wiring(typing.NamedTuple):
    """A net worth naming, and the pins on it. The last three views share it."""

    what: str
    net: str
    pins: tuple[str, ...]


def usb(schematic: eagle.Schematic) -> tuple[Wiring, ...]:
    """Nets carrying a pin named as one half of a USB differential pair."""
    return _named_pins(schematic, "usb", lambda ref: ref.pin.upper() in USB_PINS)


def crystal(schematic: eagle.Schematic) -> tuple[Wiring, ...]:
    """Nets touching a crystal part, or an MCU pin that says XTAL."""
    parts = {part.name for part in schematic.parts if role_of(part) == "crystal"}
    return _named_pins(
        schematic,
        "crystal",
        lambda ref: ref.part in parts or CRYSTAL_MARK in ref.pin.upper(),
    )


def regulator(schematic: eagle.Schematic) -> tuple[Wiring, ...]:
    """Nets driven by a pin an IC calls its output, and what else is on them."""
    ics = {part.name for part in schematic.parts if role_of(part) == "ic"}
    return _named_pins(
        schematic,
        "regulator",
        lambda ref: ref.part in ics and ref.pin.upper() in REGULATOR_OUT,
    )


def _named_pins(schematic: eagle.Schematic, what: str, matches) -> tuple[Wiring, ...]:
    """Every net with a pin `matches` accepts, and everything on that net."""
    return tuple(
        Wiring(
            what,
            net.name,
            tuple(sorted({f"{ref.part}.{ref.pin}" for ref in net.pins})),
        )
        for net in schematic.nets
        if any(matches(ref) for ref in net.pins)
    )


def pdf_only(path: pathlib.Path) -> dict:
    """The report for a vendor who publishes a schematic as a picture.

    Deliberately not an exception. `tools/import_board.py` refuses a PDF
    because geometry cannot come out of one and the caller asked for
    geometry. Here the question is *what does this vendor publish*, and
    "a rendering" is the answer to it. Recording that leaves the board's LED
    wiring an explicit unknown, which is usable; raising would leave it
    indistinguishable from a file nobody looked at.
    """
    return {
        "board": path.stem,
        "status": Status.PDF_ONLY.label,
        "source": {"file": path.as_posix(), "format": "pdf"},
        "derivation": (
            f"{path.name} is a rendering of a schematic. {Status.PDF_ONLY.gloss}. "
            f"No connectivity is reported from it and none was inferred: a PDF "
            f"is a picture of a netlist and no parsing turns one into the other."
        ),
        "unknown": ["gpio_to_pad", "indicators", "usb", "crystal", "regulator"],
    }


def _named_mcu(schematic: eagle.Schematic, mcu: str) -> Chosen:
    part = schematic.part(mcu)
    pins = sum(1 for pin in schematic.pins_of(part.name) if gpio_of(pin) is not None)
    if not pins:
        raise SchematicError(
            f"{schematic.name}: {mcu} has no pin named like a GPIO, so nothing "
            f"downstream of choosing it would find anything"
        )
    return Chosen(part.name, pins, None, 0)


def _wirings(found: tuple[Wiring, ...]) -> list[dict]:
    return [{"net": item.net, "pins": list(item.pins)} for item in found]


def connectivity(path: pathlib.Path, header: str, mcu: str | None = None) -> dict:
    """The five views, from an EAGLE schematic, as the JSON the CLI prints."""
    schematic = eagle.read_schematic(path)
    chosen = choose_mcu(schematic) if mcu is None else _named_mcu(schematic, mcu)
    schematic.part(header)

    links = gpio_to_pad(schematic, chosen.part, header)
    roles = {part.name: role_of(part) for part in schematic.parts}
    unresolved = sorted(name for name, role in roles.items() if role == "unknown")

    return {
        "board": schematic.name,
        "status": Status.NETLIST.label,
        "source": {
            "file": path.as_posix(),
            "format": "eagle-schematic",
            "eagle_version": schematic.version,
        },
        "derivation": (
            f"Generated by tools/import_schematic.py from the vendor's own EAGLE "
            f"{schematic.version} schematic: {len(schematic.parts)} parts and "
            f"{len(schematic.nets)} nets, of which the {len(links)} carrying both "
            f"an MCU GPIO pin and a header pin are reported. Connections are one "
            f"hop on a shared net, which is what a net means. Component roles are "
            f"reference designators (IEEE 315), refined by library text only where "
            f"the file states it. Nothing here was measured off an image."
        ),
        "mcu": {
            "part": chosen.part,
            "deviceset": schematic.part(chosen.part).deviceset,
            "gpio_pins": chosen.gpio_pins,
            "runner_up": chosen.runner_up,
            "runner_up_gpio_pins": chosen.runner_up_pins,
        },
        "header": {"part": header, "pins": len(schematic.pins_of(header))},
        "gpio_to_pad": [
            {
                "gpio": link.gpio,
                "mcu_pin": link.mcu_pin,
                "net": link.net,
                "pad": link.pad,
                "pad_label_agrees": link.pad_label_agrees,
            }
            for link in links
        ],
        "indicators": [
            {
                "part": item.part,
                "deviceset": item.deviceset,
                "net": item.net,
                "led_pin": item.led_pin,
                "gpio": item.gpio,
                "mcu_pin": item.mcu_pin,
                "series_resistors": list(item.series_resistors),
                "driver": item.driver,
                "note": item.note,
            }
            for item in indicators(schematic, chosen.part)
        ],
        "usb": _wirings(usb(schematic)),
        "crystal": _wirings(crystal(schematic)),
        "regulator": _wirings(regulator(schematic)),
        "unresolved": {
            "parts_with_an_unrecognised_designator": unresolved,
            "note": (
                "Reference designators outside IEEE 315. Reported rather than "
                "guessed at from position; each is a jumper, a label or a "
                "mounting feature on the boards seen so far."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=pathlib.Path, help="the vendor's schematic")
    parser.add_argument(
        "--header",
        help="the part that is the board's pin header. Not derivable: "
        "tools/import_board.py had to ask the same question of the layout",
    )
    parser.add_argument(
        "--mcu", help="the part that is the MCU; chosen by GPIO pin count if absent"
    )
    parser.add_argument("--out", type=pathlib.Path, help="write here instead of stdout")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"import_schematic: {args.file}: no such file", file=sys.stderr)
        return 2

    suffix = args.file.suffix.lower()
    try:
        if suffix == ".pdf":
            report = pdf_only(args.file)
        elif suffix == ".sch":
            if not args.header:
                parser.error("a .sch needs --header, naming the board's pin header")
            report = connectivity(args.file, args.header, args.mcu)
        else:
            raise SchematicError(
                f"{args.file}: nothing here reads {suffix or 'a file with no suffix'}. "
                f"A schematic is .sch, read as a netlist, or .pdf, recorded as "
                f"pdf-only. A .kicad_sch would belong here too, and no vendor in "
                f"tools/board_sources.py publishes one."
            )
    except (SchematicError, eagle.EagleError) as exc:
        print(f"import_schematic: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}  ({report['status']})")
    else:
        print(text, end="")

    if report["status"] == Status.PDF_ONLY.label:
        print(
            f"note: {args.file.name} is a picture. Every connectivity question "
            f"about this board stays unknown, which is recorded above rather "
            f"than filled in.",
            file=sys.stderr,
        )
        return 0

    claiming = [
        row for row in report["gpio_to_pad"] if row["pad_label_agrees"] is not None
    ]
    wrong = [row for row in claiming if row["pad_label_agrees"] is False]
    if wrong:
        print(
            f"note: {len(wrong)} of the {len(claiming)} header pads whose name states "
            f"a GPIO number state the wrong one, for example {wrong[0]['pad']} on "
            f"{wrong[0]['mcu_pin']}. A pin map built from silkscreen would be wrong "
            f"on each. The other {len(report['gpio_to_pad']) - len(claiming)} pads "
            f"name a function rather than a number and claim nothing.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
