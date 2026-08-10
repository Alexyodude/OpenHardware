# OpenHardware — a typed API over the rcontrol command surface.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Turn rcontrol's text protocol into named operations and typed results.

Every command and every response format here was read from
``src/lib/rcontrol.cc`` and is cited at its parser. Nothing is inferred from a
command's name.

This is the layer both transports share. The websocket bridge calls it today;
a WASM build calling the same operations through ``ccall`` would substitute
only the transport underneath ``RControlClient``, which is why the shape is
worth pinning down before either front-end exists.
"""

from __future__ import annotations

import dataclasses
import re

from webui.rcontrol import RControlClient, Response

# `  pin[%02i] %c %c %i %03i %5.3f "%-8.8s" ` — rcontrol.cc:1095
_PIN_LINE = re.compile(
    r"""^\s*pin\[(?P<index>\d+)\]\s+
        (?P<type>\S)\s+
        (?P<direction>[IO])\s+
        (?P<value>-?\d+)\s+
        (?P<oavalue>-?\d+)\s+
        (?P<avalue>-?[\d.]+)\s+
        "(?P<name>[^"]*)"\s*$""",
    re.VERBOSE,
)

# `%i pins [%s]:` — rcontrol.cc:1091
_PIN_HEADER = re.compile(r"^(?P<count>\d+)\s+pins\s+\[(?P<processor>[^\]]*)\]:")

# ProcessInput writes `<echo> <NAME>= <value>` — rcontrol.cc:319
_TRAILING_VALUE = re.compile(r"=\s*(?P<value>-?[\d.]+)\s*$")

# splist prints `"name", "name", ` — rcontrol.cc:1322
_QUOTED = re.compile(r'"([^"]*)"')

#: `pins` reports the output-analog value as ``(int)(oavalue - 55)``
#: (rcontrol.cc:1097). The offset is upstream's, its origin undocumented there.
#: It is preserved verbatim rather than "corrected", because a client that
#: silently disagreed with the server about a number's meaning would be worse
#: than one that reports what was sent.
OAVALUE_OFFSET = 55


class ApiError(Exception):
    """A reply was framed correctly but did not match its documented format."""


@dataclasses.dataclass(frozen=True)
class Pin:
    index: int
    type: str
    direction: str
    value: int
    oavalue_raw: int
    avalue: float
    name: str

    @property
    def is_input(self) -> bool:
        return self.direction == "I"


def parse_pins(response: Response) -> list[Pin]:
    """Parse the `pins` reply. Raises if a line does not match rcontrol.cc:1095."""
    pins: list[Pin] = []
    expected: int | None = None

    for line in response.lines:
        header = _PIN_HEADER.match(line.strip())
        if header:
            expected = int(header.group("count"))
            continue
        match = _PIN_LINE.match(line)
        if not match:
            raise ApiError(f"unparseable pin line: {line!r}")
        pins.append(
            Pin(
                index=int(match.group("index")),
                type=match.group("type"),
                direction=match.group("direction"),
                value=int(match.group("value")),
                oavalue_raw=int(match.group("oavalue")),
                avalue=float(match.group("avalue")),
                name=match.group("name").strip(),
            )
        )

    if expected is None:
        raise ApiError("pins reply carried no header line; refusing to guess")
    if len(pins) != expected:
        raise ApiError(f"header promised {expected} pins, parsed {len(pins)}")
    return pins


def parse_quoted_list(response: Response) -> list[str]:
    """Parse a reply whose payload is quoted, comma-separated names."""
    return [name for name in _QUOTED.findall(response.body) if name]


def parse_trailing_value(response: Response) -> float:
    """Parse `<echo> <NAME>= <value>` from a `get` reply."""
    for line in reversed(response.lines):
        match = _TRAILING_VALUE.search(line)
        if match:
            return float(match.group("value"))
    raise ApiError(f"no `= value` found in reply: {response.body!r}")


class SimulatorApi:
    """Named operations over one rcontrol session."""

    def __init__(self, client: RControlClient) -> None:
        self.client = client

    # -- identity ----------------------------------------------------------

    def version(self) -> str:
        return self.client.command("version").body.strip()

    def info(self) -> str:
        return self.client.command("info").body.strip()

    def supported_boards(self) -> list[str]:
        return parse_quoted_list(self.client.command("blist"))

    def supported_mcus(self) -> list[str]:
        return parse_quoted_list(self.client.command("buclist"))

    # -- run control -------------------------------------------------------

    def run(self) -> None:
        self.client.command("sim 1")

    def pause(self) -> None:
        self.client.command("sim 0")

    def reset(self) -> None:
        self.client.command("reset")

    def load_firmware(self, path: str) -> None:
        self.client.command(f"loadhex {path}")

    # -- pins --------------------------------------------------------------

    def pins(self) -> list[Pin]:
        return parse_pins(self.client.command("pins"))

    def get_pin(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get pin[{index:02}]"))

    def get_apin(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get apin[{index:02}]"))

    def set_pin(self, index: int, value: int) -> None:
        self.client.command(f"set pin[{index:02}] = {int(value)}")

    def set_apin(self, index: int, value: float) -> None:
        self.client.command(f"set apin[{index:02}] = {float(value)}")

    # -- board inputs and outputs ------------------------------------------

    def get_board_input(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get board.in[{index:02}]"))

    def get_board_output(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get board.out[{index:02}]"))

    def set_board_input(self, index: int, value: int) -> None:
        self.client.command(f"set board.in[{index:02}] = {int(value)}")

    # -- spare parts -------------------------------------------------------

    def supported_parts(self) -> list[str]:
        return parse_quoted_list(self.client.command("splist"))

    def add_part(self, name: str) -> None:
        self.client.command(f"spadd {name}")

    def remove_part(self, index: int) -> None:
        self.client.command(f"spdel {index}")

    def get_part_input(self, part: int, index: int) -> float:
        return parse_trailing_value(
            self.client.command(f"get part[{part}].in[{index}]")
        )

    def get_part_output(self, part: int, index: int) -> float:
        return parse_trailing_value(
            self.client.command(f"get part[{part}].out[{index}]")
        )

    def set_part_input(self, part: int, index: int, value: int) -> None:
        self.client.command(f"set part[{part}].in[{index}] = {int(value)}")

    def read_part_config(self, index: int) -> str:
        return self.client.command(f"sprdcfg {index}").body.strip()

    def write_part_config(self, index: int, config: str) -> None:
        self.client.command(f"spwrcfg {index} {config}")

    # -- oscilloscope ------------------------------------------------------

    def scope_measures(self, channel: int) -> list[str]:
        return self.client.command(f"oscmeasures {channel}").lines

    def scope_read_config(self) -> list[str]:
        return self.client.command("oscrdcfg").lines
