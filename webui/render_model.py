# OpenHardware — turn simulator state plus board art into a draw list.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""The decision layer of the web UI, kept in Python so it can be tested.

There is no npm in this repository and therefore no browser test runner, so
logic living in a `.js` file has no reachable fixture and the ledger cells it
backs could never move past `in-progress`
(`.claude/rules/conformance-fixtures.md` §3). The response is to put the
decisions here and leave the browser a painter:

    info dump + board art  ->  draw list  ->  the browser paints it

This module performs no I/O and imports no transport. Everything it needs
arrives as arguments, which is what makes it a table-driven test target and
what lets the same draw list be produced later from a WASM core without
changing a line of it.

The rule for the front-end is the mirror image: **if a browser file contains a
decision, it is in the wrong file.**
"""

from __future__ import annotations

import dataclasses
import re

from webui.assets import BoardArt, Region

#: `    board.out[01] LD_L=   0`
_BOARD_OUT = re.compile(r"^\s*board\.out\[(\d+)\]\s+(\S+?)=\s*(-?[\d.]+)\s*$")
#: `    board.in[00] SW_PWR= 1`
_BOARD_IN = re.compile(r"^\s*board\.in\[(\d+)\]\s+(\S+?)=\s*(-?[\d.]+)\s*$")
#: `  part[00]: Push Buttons`
_PART = re.compile(r"^\s*part\[(\d+)\]:\s*(.+?)\s*$")
#: `    part[00].in[00] PB_1= 0`
_PART_IO = re.compile(
    r"^\s*part\[(\d+)\]\.(in|out)\[(\d+)\]\s+(\S+?)=\s*(-?[\d.]+)\s*$"
)
_FIELD = re.compile(r"^\s*([A-Za-z ]+):\s*(.+?)\s*$")


class StateError(Exception):
    """An `info` reply did not carry the fields it always carries."""


@dataclasses.dataclass(frozen=True)
class Element:
    """One named, indexed value the simulator reported."""

    index: int
    name: str
    value: float


@dataclasses.dataclass(frozen=True)
class Part:
    index: int
    name: str
    inputs: tuple[Element, ...]
    outputs: tuple[Element, ...]


@dataclasses.dataclass(frozen=True)
class SimState:
    board: str
    processor: str
    frequency: str
    use_spare: bool
    board_outputs: tuple[Element, ...]
    board_inputs: tuple[Element, ...]
    parts: tuple[Part, ...]

    def output_named(self, name: str) -> Element | None:
        return next((e for e in self.board_outputs if e.name == name), None)

    def input_named(self, name: str) -> Element | None:
        return next((e for e in self.board_inputs if e.name == name), None)


def parse_info(text: str) -> SimState:
    """Parse one `info` reply into typed state.

    `info` is the whole-state dump: one command returns the board identity, its
    outputs, and every placed part with its named inputs. Polling it once per
    frame is what keeps the render loop from scaling with the circuit, which
    matters because `bridge.py` serialises every request behind one lock.

    Raises when the board line is absent. An `info` reply always carries it, so
    its absence means the reply is not an `info` reply and a caller must not
    treat a blank state as an empty board.
    """
    fields: dict[str, str] = {}
    board_outputs: list[Element] = []
    board_inputs: list[Element] = []
    parts: list[tuple[int, str, list[Element], list[Element]]] = []

    for line in text.splitlines():
        if not line.strip():
            continue

        match = _BOARD_OUT.match(line)
        if match:
            board_outputs.append(
                Element(int(match.group(1)), match.group(2), float(match.group(3)))
            )
            continue

        match = _BOARD_IN.match(line)
        if match:
            board_inputs.append(
                Element(int(match.group(1)), match.group(2), float(match.group(3)))
            )
            continue

        match = _PART_IO.match(line)
        if match:
            if not parts:
                raise StateError(f"part I/O line before any part header: {line!r}")
            element = Element(int(match.group(3)), match.group(4), float(match.group(5)))
            target = parts[-1][2] if match.group(2) == "in" else parts[-1][3]
            target.append(element)
            continue

        match = _PART.match(line)
        if match:
            parts.append((int(match.group(1)), match.group(2), [], []))
            continue

        match = _FIELD.match(line)
        if match:
            fields[match.group(1).strip().lower()] = match.group(2)

    if "board" not in fields:
        raise StateError(
            f"no `Board:` line; this is not an info reply. Got fields: "
            f"{sorted(fields)}"
        )

    return SimState(
        board=fields["board"],
        processor=fields.get("processor", ""),
        frequency=fields.get("frequency", ""),
        use_spare=fields.get("use spare", "0").strip() == "1",
        board_outputs=tuple(board_outputs),
        board_inputs=tuple(board_inputs),
        parts=tuple(
            Part(index, name, tuple(ins), tuple(outs)) for index, name, ins, outs in parts
        ),
    )


#: Outputs report a magnitude rather than a flag -- the Arduino Uno's on-board
#: L LED reads 97 when lit and 0 when dark. Anything above zero is treated as
#: lit and the raw value is passed through as intensity, so the browser renders
#: brightness without this module deciding what a given scale means.
_FULL_SCALE = 255.0


@dataclasses.dataclass(frozen=True)
class Drawable:
    """One region, resolved against live state, ready to paint."""

    id: str
    role: str
    name: str
    shape: str
    left: int
    top: int
    right: int
    bottom: int
    radius: int | None
    #: None when the simulator reports nothing for this region -- the art
    #: declares it but this board or firmware does not drive it.
    value: float | None
    active: bool
    intensity: float
    #: Protocol index, or None when unbound. Interaction needs this.
    index: int | None
    clickable: bool

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _drawables(
    regions: tuple[Region, ...],
    outputs: tuple[Element, ...],
    inputs: tuple[Element, ...],
) -> list[Drawable]:
    """Resolve regions against named elements. Shared by boards and parts.

    Parts ship the same image-map format as boards and their region ids carry
    the same names the simulator reports, so one function covers both. A second
    implementation would be a second place for the binding rule to drift.
    """
    by_name_out = {e.name: e for e in outputs}
    by_name_in = {e.name: e for e in inputs}

    resolved: list[Drawable] = []
    for region in regions:
        table = by_name_out if region.role == "output" else by_name_in
        element = table.get(region.name)
        value = None if element is None else element.value
        resolved.append(
            Drawable(
                id=region.id,
                role=region.role,
                name=region.name,
                shape=region.shape,
                left=region.left,
                top=region.top,
                right=region.right,
                bottom=region.bottom,
                radius=region.radius,
                value=value,
                active=bool(value),
                intensity=0.0 if not value else min(1.0, abs(value) / _FULL_SCALE),
                index=None if element is None else element.index,
                clickable=region.role in ("button", "input") and element is not None,
            )
        )
    return resolved


#: A part's pin-number labels are drawn at `O_PN_<n>` regions in its art, and
#: its schema lists the same pins as config fields. Nothing states the
#: correspondence, so it is taken positionally: the nth pin field is drawn at
#: `O_PN_<n>`.
#:
#: That assumption is checked rather than trusted -- if the counts disagree the
#: part gets no anchors at all and says so, because a wire drawn from the wrong
#: pin is worse than a wire the user has to place through the form. Position is
#: cosmetic (wiring is by pin number), but a *label* attached to the wrong dot
#: would make the picture lie about which pin is connected.
_PIN_LABEL_REGION = re.compile(r"^O_PN_(\d+)$")


def _anchors(regions: tuple[Region, ...], labels: list[str], wiring: dict) -> list[dict]:
    numbered: dict[int, Region] = {}
    for region in regions:
        match = _PIN_LABEL_REGION.match(region.id)
        if match:
            numbered[int(match.group(1))] = region

    if len(numbered) != len(labels):
        return []

    out = []
    for position, label in enumerate(labels, start=1):
        region = numbered.get(position)
        if region is None:
            return []
        x, y = region.centre
        out.append(
            {
                "label": label,
                "x": x,
                "y": y,
                "wired_to": wiring.get(label) or None,
            }
        )
    return out


def build(state: SimState, art: BoardArt, part_art=None, part_detail=None) -> dict:
    """Combine live state with board and part art into a draw list.

    `part_art` is an optional callable taking a part name and returning its
    `BoardArt`, or None when that part has no drawable art. It is injected
    rather than imported so this module keeps doing no I/O.

    Regions the simulator says nothing about are kept with `value=None` rather
    than dropped, and counted in `unbound`. A board whose art and firmware
    disagree is a real condition worth seeing, and silently omitting the
    element would make it invisible.
    """
    drawables = _drawables(art.regions, state.board_outputs, state.board_inputs)

    parts: list[dict] = []
    for part in state.parts:
        rendered = part_art(part.name) if part_art else None
        regions = (
            _drawables(rendered.regions, part.outputs, part.inputs) if rendered else []
        )
        detail = part_detail(part.index, part.name) if part_detail else None
        anchors = (
            _anchors(rendered.regions, detail["labels"], detail["wiring"])
            if rendered and detail
            else []
        )
        parts.append(
            {
                "index": part.index,
                "name": part.name,
                "width": rendered.width if rendered else None,
                "height": rendered.height if rendered else None,
                "regions": [d.as_dict() for d in regions],
                "inputs": [dataclasses.asdict(e) for e in part.inputs],
                "outputs": [dataclasses.asdict(e) for e in part.outputs],
                # Where each schema pin is drawn, and what it is wired to.
                # Empty when the part has no schema, no art, or when the two
                # disagree about how many pins it has -- see _anchors.
                "anchors": anchors,
                # Stated per part so a peripheral that is placed but cannot be
                # drawn is visible as such, rather than just missing.
                "drawable": rendered is not None,
            }
        )

    return {
        "board": state.board,
        "processor": state.processor,
        "frequency": state.frequency,
        "use_spare": state.use_spare,
        "width": art.width,
        "height": art.height,
        "regions": [d.as_dict() for d in drawables],
        "parts": parts,
        "unbound": sum(1 for d in drawables if d.value is None),
    }
