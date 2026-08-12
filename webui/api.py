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

from webui.parts.schema import UNCONNECTED, PartSchema, SchemaError
from webui.rcontrol import RControlClient, RControlCommandError, Response

# `  pin[%02i] %c %c %i %03i %5.3f "%-8.8s" ` — rcontrol.cc:1095, the **pinsl**
# formatter. Confirmed against a live PICSimLab 0.9.3 on 2026-08-10.
#
# `pins` and `pinsl` are different commands with different output, and an
# earlier version of this file used this parser against `pins`, which fails on
# every line. `pins` emits two entries per line in a narrow form —
# `  pin[01] ( PC6/RST) < 0    pin[15] (PB1/~9  ) < 0` — with `<`/`>` for
# direction and no type, analog value, or count header.
#
# This module uses `pinsl` exclusively: it is strictly richer, and its header
# doubles as a checksum on its own body.
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

#: `blist` and `buclist` print **bare** comma-separated names, not quoted:
#: ` Arduino_Mega, Arduino_Nano, Arduino_Uno, ...`. Only `splist` quotes them.
#: Confirmed live on 2026-08-10; using the quoted parser here silently returns
#: an empty list, which is why board discovery must not share splist's parser.
_LIST_HEADER = re.compile(r":\s*$")

#: `pins` reports the output-analog value as ``(int)(oavalue - 55)``
#: (rcontrol.cc:1097). The offset is upstream's, its origin undocumented there.
#: It is preserved verbatim rather than "corrected", because a client that
#: silently disagreed with the server about a number's meaning would be worse
#: than one that reports what was sent.
OAVALUE_OFFSET = 55


class ApiError(Exception):
    """A reply was framed correctly but did not match its documented format."""


#: Widest index rcontrol can express. See `ix`.
INDEX_MAX = 99


def ix(value: int) -> str:
    """Format one protocol index. **The only place this is done.**

    rcontrol parses an index by character position, exactly two wide:

        int out = (ptr[11] - '0') * 10 + (ptr[12] - '0');   # rcontrol.cc:748

    so `board.out[1]` reads `']'` as the second digit, computes 55, fails the
    range test, and replies ERROR. The same shape indexes `pin[`, `apin[`,
    `board.in[`, and both halves of `part[NN].in[MM]` (rcontrol.cc:809-810).

    ERROR is a single undifferentiated reply, so a malformed index is
    indistinguishable from an unsupported feature without reading the parser.
    That ambiguity cost this project two recorded upstream defects that never
    existed -- `docs/known-issues.md` 4a.4 and 4a.5, both withdrawn -- and this
    module emitted the unpadded form for part I/O the whole time.

    Two digits is also a ceiling, so this raises rather than silently sending a
    three-digit index that the server would read as a different, valid one.
    """
    number = int(value)
    if not 0 <= number <= INDEX_MAX:
        raise ApiError(
            f"index {number} is outside 0..{INDEX_MAX}: rcontrol reads an index "
            f"as exactly two characters, so a wider one addresses the wrong "
            f"element rather than failing"
        )
    return f"{number:02}"


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
    """Parse a reply whose payload is quoted, comma-separated names (`splist`)."""
    return [name for name in _QUOTED.findall(response.body) if name]


def parse_comma_list(response: Response) -> list[str]:
    """Parse a reply whose payload is bare, comma-separated names.

    Used by `blist` and `buclist`. The first line is a heading ending in `:`
    and is skipped; everything after is split on commas.
    """
    names: list[str] = []
    for line in response.lines:
        if _LIST_HEADER.search(line):
            continue
        names.extend(part.strip() for part in line.split(",") if part.strip())
    return names


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
        # blist is bare comma-separated, unlike splist. See parse_comma_list.
        return parse_comma_list(self.client.command("blist"))

    def supported_mcus(self) -> list[str]:
        return parse_comma_list(self.client.command("buclist"))

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
        # `pinsl`, not `pins`: see the note on _PIN_LINE. `pins` is a narrow
        # two-column display with no type, analog value, or count header.
        return parse_pins(self.client.command("pinsl"))

    def get_pin(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get pin[{ix(index)}]"))

    def get_apin(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get apin[{ix(index)}]"))

    def set_pin(self, index: int, value: int) -> None:
        self.client.command(f"set pin[{ix(index)}] = {int(value)}")

    def set_apin(self, index: int, value: float) -> None:
        self.client.command(f"set apin[{ix(index)}] = {float(value)}")

    # -- board inputs and outputs ------------------------------------------

    def get_board_input(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get board.in[{ix(index)}]"))

    def get_board_output(self, index: int) -> float:
        return parse_trailing_value(self.client.command(f"get board.out[{ix(index)}]"))

    def set_board_input(self, index: int, value: int) -> None:
        self.client.command(f"set board.in[{ix(index)}] = {int(value)}")

    # -- spare parts -------------------------------------------------------

    def supported_parts(self) -> list[str]:
        return parse_quoted_list(self.client.command("splist"))

    def add_part(self, name: str, xpos: int = 0, ypos: int = 0) -> None:
        """Place a spare part at a canvas position.

        `spadd` parses `" \\"%99[^\\"]\\" %i %i"` (rcontrol.cc:1266), so the name
        must be **quoted** and both coordinates are required. An earlier version
        of this method sent `spadd {name}` bare; the server rejected every call.
        Reading the dispatch found the format, and a live server confirmed it.

        The name must match `splist` exactly. A name that does not match logs
        "Erro creating part" and returns ERROR.

        **Warning, observed on PICSimLab 0.9.3:** placing a part whose assets
        are not installed does not fail cleanly — it logs `Erro CC_LOADIMAGE!`
        and then **segfaults the simulator**. Callers should expect the
        connection to drop rather than an ERROR reply. This is an upstream
        robustness bug, recorded in docs/known-issues.md.
        """
        self.client.command(f'spadd "{name}" {int(xpos)} {int(ypos)}')

    def remove_part(self, index: int) -> None:
        self.client.command(f"spdel {index}")

    def get_part_input(self, part: int, index: int) -> float:
        return parse_trailing_value(
            self.client.command(f"get part[{ix(part)}].in[{ix(index)}]")
        )

    def get_part_output(self, part: int, index: int) -> float:
        return parse_trailing_value(
            self.client.command(f"get part[{ix(part)}].out[{ix(index)}]")
        )

    def set_part_input(self, part: int, index: int, value: int) -> None:
        self.client.command(f"set part[{ix(part)}].in[{ix(index)}] = {int(value)}")

    def read_part_config(self, index: int) -> str:
        """Deprecated alias for read_config; kept for the bridge's allowlist.

        Used to send `.body.strip()` without stripping the quotes `sprdcfg`
        actually returns, and `write_part_config` below used to send `spwrcfg`
        unquoted -- two constructions of the same commands that had drifted
        from the ones `read_config`/`write_config` get right. Delegating
        collapses both pairs to one construction site per command so the wire
        formats cannot diverge again.
        """
        return self.read_config(index)

    def write_part_config(self, index: int, config: str) -> None:
        """Deprecated alias for write_config; kept for symmetry."""
        self.write_config(index, config)

    # -- oscilloscope ------------------------------------------------------

    def scope_measures(self, channel: int) -> list[str]:
        return self.client.command(f"oscmeasures {channel}").lines

    def scope_read_config(self) -> list[str]:
        return self.client.command("oscrdcfg").lines

    # -- wiring ------------------------------------------------------------

    MAX_PARTS = 256

    def part_count(self) -> int:
        """Count placed parts by probing until the server refuses.

        There is no count command. `spadd` returns Ok rather than an index and
        `spshow` returns a flag, so the only way to learn how many parts exist
        is to ask for each in turn until one errors.

        Bounded defensively at `MAX_PARTS`: a live server does return ERROR
        past the last part, so this loop always returns well before the bound
        against observed behaviour. The bound exists to guard a changed or
        misbehaving server, not because probing has ever run away in practice.
        """
        for index in range(self.MAX_PARTS):
            try:
                self.client.command(f"sprdcfg {index}")
            except RControlCommandError:
                return index
        raise SchemaError(
            f"part count exceeded {self.MAX_PARTS}; sprdcfg never returned ERROR"
        )

    def place_part(self, name: str, xpos: int, ypos: int) -> int:
        """Place a part and return the index it landed at."""
        index = self.part_count()
        self.add_part(name, xpos, ypos)
        return index

    def read_config(self, index: int) -> str:
        # A live `sprdcfg 0` returned `"0,0,0,0,0,0,0,0,1,0,8"` -- quoted.
        return self.client.command(f"sprdcfg {index}").body.strip().strip('"')

    def write_config(self, index: int, config: str) -> None:
        """Write a part's whole config string.

        The quotes are mandatory. rcontrol.cc:1307 parses this argument with
        `sscanf(cmd + 8, "%d \\"%511[^\\"]\\"", &pid, scfg)`, so an unquoted
        config never reaches the part -- the same trap `spadd` sets.

        The server's arity guard is one-sided. rcontrol.cc:1310 compares
        `Part->ReadPreferences(scfg)` against `Part->PreferencesNumberFields()`
        and answers ERROR when they disagree -- but `sscanf`'s assignment
        count, which is what `ReadPreferences` returns, can only ever be *less
        than or equal to* the number of `%`-conversions in its own format
        string. It has no way to notice trailing input past the last field, so
        it cannot detect an over-long config. Measured live against a placed
        Push Buttons part (11-field schema):

            OVER-ARITY  (12 fields sent): ACCEPTED -- extra field silently dropped
            UNDER-ARITY  (3 fields sent): REJECTED

        So the server only ever rejects *under*-arity. An over-long config is
        silently truncated to the part's real field count and the write still
        reports Ok. What actually catches over-arity on this client is
        `_values()`'s own length check against the schema, on the **read**
        path -- so an over-long write is only caught on a subsequent read, not
        at write time.
        """
        self.client.command(f'spwrcfg {index} "{config}"')

    def _values(self, index: int, schema: PartSchema) -> list[int]:
        raw = self.read_config(index)
        values = [int(v) for v in raw.split(",") if v.strip() != ""]
        if len(values) != schema.arity:
            raise SchemaError(
                f"{schema.part}: arity mismatch — schema declares {schema.arity} "
                f"fields, part {index} reported {len(values)}: {raw!r}"
            )
        return values

    def read_wiring(self, index: int, schema: PartSchema) -> dict[str, int]:
        """Map every field label to its current value."""
        return {
            field.label: value
            for field, value in zip(schema.fields, self._values(index, schema))
        }

    #: The config field a pin value lands in is `%hhu` (rcontrol.cc:1266,
    #: :1307 and every part's own `sprintf`/`sscanf` pair) -- an unsigned
    #: char. A value outside this range does not fail on the wire; it wraps
    #: mod 256, so `connect(..., 300)` is silently accepted and reads back as
    #: 44. Confirmed live against PICSimLab 0.9.3 on a placed Push Buttons
    #: part: `connect(index, schema, "B1", 300)` read back 44,
    #: `connect(index, schema, "B1", -1)` read back 255. `UNCONNECTED` (0)
    #: is within this range and stays valid.
    PIN_MIN = 0
    PIN_MAX = 255

    def _set_field(self, index: int, schema: PartSchema, label: str, value: int) -> None:
        position = schema.index_of(label)
        if schema.fields[position].role != "pin":
            raise SchemaError(f"{schema.part}: {label!r} is not a pin field")
        value = int(value)
        if not self.PIN_MIN <= value <= self.PIN_MAX:
            raise SchemaError(
                f"{schema.part}: {label!r} pin value {value} is out of range "
                f"{self.PIN_MIN}..{self.PIN_MAX}"
            )
        values = self._values(index, schema)
        values[position] = value
        self.write_config(index, ",".join(str(v) for v in values))

    def connect(self, index: int, schema: PartSchema, label: str, pin: int) -> None:
        """Wire one of the part's pins to a board pin number."""
        self._set_field(index, schema, label, pin)

    def disconnect(self, index: int, schema: PartSchema, label: str) -> None:
        self._set_field(index, schema, label, UNCONNECTED)
