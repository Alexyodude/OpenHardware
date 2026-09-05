# OpenHardware — where a board's header pins sit on its image.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Load `webui/boards/<board>.json`: pad label, pin number, and x/y on the art.

**Nothing upstream knows where a board's pins are.** Boards expose pin *names*
through `MGetPinName` and are only ever shown as a list -- the oscilloscope
channel picker, `pinsl`. No `board.map` declares a header region and no
`src/boards/*.cc` carries a coordinate. So a UI that lets you drag a wire onto
a physical header needs data that does not exist yet, and this is it.

Parts are the opposite case and need nothing: all 48 drawable ones already
carry `O_PN_*` regions in their `part.map`.

## Why being wrong here is cheap

A pad's position is **cosmetic**. Wiring is by pin *number*, so the dot you
drag to always wires the pin its label names; a coordinate that is off by ten
pixels looks slightly wrong and miswires nothing. That is the opposite of a
part schema, where a transposed field round-trips clean while wiring the
circuit incorrectly (`docs/known-issues.md` §4b).

Which is why authoring these by hand is a reasonable thing to do, and why the
Arduino Uno's were derived from `board.svg` rather than guessed: the pads are
circles on a 0.1 inch pitch, and that pitch is what identifies a header run.

## A pad need not have a pin

`NC`, `IOREF`, `3V3` and `VIN` exist on an Uno's header and have no ATmega328P
pin behind them. They are kept with `pin: null` so the board looks right and so
a drag onto one can be refused for the correct reason, rather than silently
finding nothing there.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

#: rcontrol indexes pins as exactly two characters (`webui.api.ix`), so a board
#: cannot expose a pin above this through the protocol at all.
PIN_MAX = 99

BOARDS_DIR = pathlib.Path(__file__).resolve().parent / "boards"


class PinMapError(Exception):
    """A pin map is missing, malformed, or disagrees with the board art."""


@dataclasses.dataclass(frozen=True)
class Pad:
    label: str
    #: Protocol pin index, or None for a header pad with no MCU pin behind it.
    pin: int | None
    x: float
    y: float
    group: str
    #: The MCU pin this pad reaches, as its vendor names it -- `GPIO5`, `PA02`,
    #: `P2.08`. **A caption and not a handle**: `pin` above is what the
    #: protocol addresses, and only the Arduino Uno has one. Every XIAO file
    #: says so at length in its own `assumption` field, and pressing
    #: `chip_index` into `pin` would be inventing a protocol index the board
    #: has not got.
    #:
    #: Read out of six board-support packages by `tools/import_pindefs.py`
    #: (OH-26), each value naming the vendor file and revision that resolved
    #: it. **It was written into the board files and then dropped here**, so
    #: for fourteen boards the page had no source for it at all and said
    #: "not modelled" over 196 pads whose answer was on disk beside it.
    chip_pin: str | None = None
    #: The same pin as a flat integer, where the vendor publishes flat
    #: numbering. Null on the SAMD21, MG24, nRF54L15 and nRF54LM20A, whose
    #: vendors number by port and bit (`PA02`) and never flatly -- which is
    #: why `chip_pin` is the string and this is the extra.
    chip_index: int | None = None

    @property
    def wireable(self) -> bool:
        return self.pin is not None


@dataclasses.dataclass(frozen=True)
class PinMap:
    board: str
    width: int
    height: int
    pads: tuple[Pad, ...]
    #: True when the positions were laid out evenly rather than read from the
    #: board's art. The wiring is exact either way; only the picture is
    #: schematic, and the UI says so rather than implying a real pinout.
    derived: bool = False
    #: The map's own statement of its scale, or None for the one TRACED map
    #: (the Arduino Uno's), whose artwork has no single true scale -- it is
    #: anisotropic by 0.41% -- and whose scale the page fits from the pads.
    #: A generated map is exact at a stated 8 px/mm, and OH-121 measured what
    #: re-deriving that number from mismatched pad fields cost: every
    #: composed SMD model drawn 9% small.
    px_per_mm: float | None = None

    @property
    def wireable(self) -> tuple[Pad, ...]:
        return tuple(pad for pad in self.pads if pad.wireable)

    def by_pin(self, pin: int) -> Pad | None:
        return next((pad for pad in self.pads if pad.pin == pin), None)

    def as_dict(self) -> dict:
        return {
            "board": self.board,
            "width": self.width,
            "height": self.height,
            "derived": self.derived,
            "px_per_mm": self.px_per_mm,
            "pads": [dataclasses.asdict(pad) for pad in self.pads],
        }


def parse(raw: object, where: str) -> PinMap:
    """Validate one decoded pin-map document, or raise."""
    if not isinstance(raw, dict):
        raise PinMapError(f"{where}: not an object")
    for key in ("board", "image", "pads"):
        if key not in raw:
            raise PinMapError(f"{where}: has no {key!r}")

    image = raw["image"]
    if not isinstance(image, dict) or "width" not in image or "height" not in image:
        raise PinMapError(f"{where}: image needs width and height")
    width, height = int(image["width"]), int(image["height"])

    entries = raw["pads"]
    if not isinstance(entries, list) or not entries:
        raise PinMapError(
            f"{where}: declares no pads. An empty map would render a board with "
            f"nowhere to wire and report no error."
        )

    pads: list[Pad] = []
    seen_pins: dict[int, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PinMapError(f"{where}: pad {index} is not an object")
        label = entry.get("label")
        if not label:
            raise PinMapError(f"{where}: pad {index} has no label")

        pin = entry.get("pin")
        if pin is not None:
            if not isinstance(pin, int) or not 1 <= pin <= PIN_MAX:
                raise PinMapError(
                    f"{where}: pad {label!r} has pin {pin!r}; must be 1..{PIN_MAX} "
                    f"or null for a pad with no MCU pin"
                )
            # Duplicates are legitimate -- an Uno's SCL and A5 are one pin, and
            # GND appears twice -- so this records rather than rejects.
            seen_pins.setdefault(pin, label)

        try:
            x, y = float(entry["x"]), float(entry["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PinMapError(f"{where}: pad {label!r} has no usable x/y") from exc
        if not (0 <= x <= width and 0 <= y <= height):
            raise PinMapError(
                f"{where}: pad {label!r} at ({x}, {y}) is outside the "
                f"{width}x{height} image"
            )
        # **Read rather than ignored, which is OH-167.** These two were in the
        # files from OH-26 and this function dropped them, so the page's only
        # source for a chip pin was the board module's `PIN_NAMES` -- and
        # fourteen boards have no module. Validated rather than coerced: a
        # number where a name belongs is a board file to fix, not a caption to
        # render as `5`.
        chip_pin = entry.get("chip_pin")
        if chip_pin is not None and not isinstance(chip_pin, str):
            raise PinMapError(
                f"{where}: pad {label!r} has chip_pin {chip_pin!r}; must be a "
                f"name like 'GPIO5' or 'PA02', or null"
            )
        chip_index = entry.get("chip_index")
        if chip_index is not None and not isinstance(chip_index, int):
            raise PinMapError(
                f"{where}: pad {label!r} has chip_index {chip_index!r}; must "
                f"be an integer or null"
            )
        pads.append(Pad(label=label, pin=pin, x=x, y=y,
                        group=entry.get("group", ""),
                        chip_pin=chip_pin, chip_index=chip_index))

    # Optional and validated only when present: a traced map states none.
    scale = raw.get("px_per_mm")
    if scale is not None and (not isinstance(scale, (int, float)) or scale <= 0):
        raise PinMapError(f"{where}: px_per_mm must be a positive number, "
                          f"not {scale!r}")
    return PinMap(board=raw["board"], width=width, height=height,
                  pads=tuple(pads),
                  px_per_mm=float(scale) if scale is not None else None)


def load(board: str, directory: pathlib.Path | None = None) -> PinMap | None:
    """Return a board's pin map, or None when nobody has authored one.

    None is not an error. Coverage is deliberately partial -- twenty-one boards
    ship and each needs its pads placed by hand -- so a board without a map
    falls back to the pin rail rather than losing the ability to wire.
    """
    path = (directory or BOARDS_DIR) / f"{board}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PinMapError(f"{path}: not valid JSON: {exc}") from exc
    return parse(raw, path.name)


def synthesise(board: str, pins: list, width: int, height: int) -> PinMap:
    """Lay the simulator's own pins along the board's bottom edge.

    Twenty-one boards ship and only their headers' *positions* are missing, so
    hand-authoring every one is a lot of work for something cosmetic. This gives
    the other twenty a droppable header immediately, built from what the
    simulator reports rather than from anything invented: the labels are
    `pinsl` names and the indices are the protocol's own.

    **The positions are approximate and say so** -- `derived` is True and the
    UI reports it. They are laid out evenly rather than where the pads actually
    are, which is honest about being a placeholder for an authored map. Since
    wiring is by pin number, a wire dropped here connects exactly what its
    label names; only the picture is schematic.

    Pins are split across two rows when there are more than sixteen, because a
    single row of forty on a small board is unusable.
    """
    if not pins:
        raise PinMapError(
            f"{board}: the simulator reports no pins, so no header can be "
            f"synthesised. A board with no pins cannot be wired at all."
        )

    rows = 1 if len(pins) <= 16 else 2
    per_row = -(-len(pins) // rows)
    margin = max(width * 0.06, 8.0)
    span = width - 2 * margin
    pads: list[Pad] = []

    for position, pin in enumerate(pins):
        row = position // per_row
        column = position % per_row
        step = span / max(per_row - 1, 1)
        pads.append(
            Pad(
                label=pin.name,
                pin=pin.index,
                x=round(margin + column * step, 1),
                y=round(height - 10 - row * 12, 1),
                group=f"synthetic-row-{row}",
            )
        )

    return PinMap(board=board, width=width, height=height, pads=tuple(pads),
                  derived=True)


def available(directory: pathlib.Path | None = None) -> tuple[str, ...]:
    base = directory or BOARDS_DIR
    if not base.is_dir():
        return ()
    return tuple(sorted(p.stem for p in base.glob("*.json")))
