# OpenHardware — a typed API over the rcontrol command surface.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
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
import importlib
import re
import types
import typing

from tools import board_manifest
from webui import firmware, pinmap, targets
from webui.boards import catalogue, contract
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

    def _values(self, index: int, schema: PartSchema) -> list[str]:
        """The config's fields as the part wrote them, still as text.

        Deliberately not parsed to `int` here. Not every field is an integer --
        `input_LDR.cc:240` writes `vthreshold` with `%f`, so an LDR reports
        `0,0,100,2.500000` -- and a read-modify-write that parsed to `int` and
        formatted back would rewrite `2.500000` as `2`, destroying a setting
        the caller never asked to change while reporting success.

        Keeping the raw token means every field this client does not touch is
        written back byte-for-byte.
        """
        raw = self.read_config(index)
        values = [v.strip() for v in raw.split(",") if v.strip() != ""]
        if len(values) != schema.arity:
            raise SchemaError(
                f"{schema.part}: arity mismatch — schema declares {schema.arity} "
                f"fields, part {index} reported {len(values)}: {raw!r}"
            )
        return values

    @staticmethod
    def _typed(field, raw: str) -> int | float | str:
        """Parse one field by what its schema says it is.

        An unparseable value is returned as text rather than raised on: the
        caller asked what the part reports, and refusing to answer because one
        setting has an unexpected shape would make the whole part unreadable.
        """
        try:
            return float(raw) if field.type == "float" else int(raw)
        except ValueError:
            return raw

    def read_wiring(self, index: int, schema: PartSchema) -> dict[str, int | float | str]:
        """Map every field label to its current value."""
        return {
            field.label: self._typed(field, raw)
            for field, raw in zip(schema.fields, self._values(index, schema))
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
        values[position] = str(value)
        # Every other field goes back exactly as it came, so a float setting
        # survives a pin write. See _values.
        self.write_config(index, ",".join(values))

    def connect(self, index: int, schema: PartSchema, label: str, pin: int) -> None:
        """Wire one of the part's pins to a board pin number."""
        self._set_field(index, schema, label, pin)

    def disconnect(self, index: int, schema: PartSchema, label: str) -> None:
        self._set_field(index, schema, label, UNCONNECTED)


# --------------------------------------------------------------------------
# Boards: putting a compiled image on the chip a person actually chose
# --------------------------------------------------------------------------
#
# **This section shares the file and nothing else with the rcontrol operations
# above.** Those drive PICSimLab over a socket; these drive a core in this
# process. They sit together because `api.py` is the layer a front-end calls
# and because OH-32 names it as the seam -- not because a board session is an
# rcontrol concept. When a third backend arrives this is the part to move.
#
# Everything here is a join between pieces that already exist and were built
# apart from each other:
#
#   webui/boards/catalogue.py   which chip is on a board, which core it needs
#   webui/targets.py            whether that core is built
#   webui/boards/<chip>.py      the memory map and the peripherals
#   webui/firmware.py           an artefact's bytes -> an addressed Image
#   core/<core>/abi.py          something that executes
#
# None of them is reimplemented. Each join refuses separately, because "this
# chip has no description", "that core is not built" and "that image is not
# for this chip" are three different problems with three different fixes, and
# a single message covering all three sends the reader to the wrong one.
#
# Selection is by **board**, which is the thing a person picks up and owns.
# `targets.py` already answers the core question and answers it well; asking
# someone which instruction set their board speaks is asking them to do the
# lookup this module exists to do.


class BoardRunError(Exception):
    """A board and an image that cannot be put together, and why.

    `reason` is a short stable slug -- `unknown-board`, `core-not-built` and
    the rest listed in `REASONS`. The message is the useful half and always
    carries the values that caused it; the slug exists so a transport can keep
    the refusals apart without matching on message text, which is the thing
    that breaks the first time a message is reworded.

    They are separate failures with separate fixes. Collapsing them into one
    "could not load" is how a person ends up rebuilding a core to fix an image
    that was simply linked at the wrong address.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        if reason not in REASONS:
            raise ValueError(f"unknown refusal reason {reason!r}; known: {sorted(REASONS)}")
        self.reason = reason


#: Every way this layer refuses, and what each one means for the person
#: reading it. `webui/emulator_server.py` maps these to status codes.
REASONS = {
    "unknown-board": "no board of that name in webui/boards/",
    "core-not-built": "the chip's core is missing or not compiled",
    "chip-not-described": "no module gives this chip a memory map",
    "nothing-for-this-chip": "the artefact holds no image for this chip",
    "outside-the-board-map": "the image loads where this board has no memory",
    # The slug is older than the second machine and names the Armv6-M case;
    # what it now covers is "this board could not be entered", whatever
    # entering means on it -- and on a machine that starts at address zero,
    # nothing can raise it. Left alone rather than renamed, because a slug is
    # a wire contract: `webui/emulator_server.py` maps it to a 400, and
    # `tests/webui/test_board_run.py` asserts a caller receives that slug.
    "no-vector-table": "no address in the image looks like one this board could enter",
    "budget-refused": "the number of instructions asked for is not usable",
    "window-refused": "the memory window asked for is not a usable size",
    "window-outside-the-map": "the memory window asked for is not on this board",
}


class Core(typing.Protocol):
    """What **this module** needs of a core, which is now two things.

    It used to be twelve, and that list read like a description of "a core"
    when it was nothing of the sort: it was the shape two flat-address 32-bit
    machines happen to share. Measured against `core/avr/abi.py`, ten of the
    twelve were absent -- not unwritten, but meaningless. A Harvard machine has
    two address spaces that overlap, so `write_block(address, data)` cannot say
    which one it means; an 8-bit machine has no `read_word`.

    Everything that was architecture-shaped moved to `core/<core>/machine.py`,
    resolved per core the way `listing_view` resolves `core.<core>.disasm`.
    What is left here is what a *session* needs regardless of machine: run one
    instruction, and give the native allocation back.
    """

    def step(self) -> None: ...
    def close(self) -> None: ...


#: The UF2 family a build for each chip declares, named from
#: `firmware.UF2_FAMILIES`.
#:
#: Passed straight through to `load_image`, so the filtering happens in the
#: layer that owns the format rather than being redone here. It matters most
#: on the RP2040: Raspberry Pi ships universal files carrying an RP2040 image
#: *and* an RP2XXX_ABSOLUTE one at the same addresses, and `parse_uf2` refuses
#: to choose between them unless it is told which one is wanted.
#:
#: A chip absent from here parses with `family=None`, which is correct for the
#: formats that carry no family at all and for a single-family UF2.
#:
#: **The RP2350 is here because it is two chips to a UF2.** Its bootrom knows
#: `rp2350_arm_s` 0xe48bff59, `rp2350_riscv` 0xe48bff5a and `rp2350_arm_ns`
#: 0xe48bff5b (RP2350 Datasheet 80d627281ed5, section 5.5.3, Table 469, PDF
#: p.368), and `webui/boards/rp2350.py` describes only the RISC-V half. Absent
#: from here, a file of one family loaded at 0x10000000 -- an Arm image or an
#: RP2040 one alike -- and stopped at an illegal encoding, which reads as the
#: part refusing the program; the XIAO's default Arm build, `--family
#: rp2350-arm-s --abs-block` (arduino-pico 33201a6, `boards.txt:36734`), holds
#: two families and was refused as unreadable. Asking for `RP2350_RISCV`
#: refuses all of those as `nothing-for-this-chip`, and also refuses the
#: `absolute` and `data` families alone, which the bootrom accepts, because
#: neither says which half its image is for. An `absolute` block BESIDE a
#: RISC-V image is skipped, so the UF2 arduino-pico's RISC-V build writes
#: for the XIAO -- `--family rp2350-riscv --abs-block`, its `boards.txt:36741`
#: at 33201a6 -- is read rather than refused as two families in one file.
#: Whether its image then runs is `webui/boards/rp2350.py`'s question.
UF2_FAMILY_BY_CHIP: dict[str, str] = {"RP2040": "RP2040", "RP2350": "RP2350_RISCV"}

#: Where a vector table sits **used to be here**, as
#: `VECTOR_TABLE_OFFSETS = {"RP2040": (0, 256)}`. It is not any more, and the
#: deletion is the point rather than a tidy-up: that is a fact about a chip,
#: and it now lives in `webui/boards/rp2040.py` and `samd21.py`, which is where
#: a reader looking for what an RP2040 does would go. `core/cortexm0/machine.py`
#: is what reads it, and asks only boards on a machine that has one --
#: `core/avr/machine.py` declares no such requirement, because an AVR begins
#: executing at address zero.


@dataclasses.dataclass(frozen=True)
class Runtime:
    """Everything that must already exist before a board can take an image."""

    board: str
    chip: str
    core: str
    #: `webui.boards.<chip>` -- the memory map and peripherals.
    description: types.ModuleType
    #: `core.<core>.abi` -- the thing that executes.
    abi: types.ModuleType
    #: `core.<core>.machine` -- how this kind of machine powers on, and what
    #: its registers are called. Separate from `abi` because `abi` is the
    #: library binding and this is the arrangement: two cores could share one
    #: and not the other.
    machine: types.ModuleType


def description_module(chip: str) -> str:
    """`RP2040` -> `webui.boards.rp2040`.

    The exact inverse of `catalogue.described_chips`, which reads a module
    stem as `stem.upper().replace("-", "")`. Written as a rule rather than a
    table so that adding a chip stays "add one file", which is the property
    that module is built around.
    """
    return f"webui.boards.{chip.lower().replace('-', '')}"


def runtime_for(board_name: str) -> Runtime:
    """Resolve a board to what would execute it, refusing at each join.

    Four things can be missing and each gets its own message, because each has
    a different fix: the board is not one we have, the chip has no description,
    the core is not built, or a module that should import does not.
    """
    boards = {board.name: board for board in catalogue.catalogue()}
    board = boards.get(board_name)
    if board is None:
        raise BoardRunError(
            "unknown-board",
            f"no such board: {board_name!r}. webui/boards/ holds "
            f"{len(boards)}, including {', '.join(sorted(boards)[:3])}"
        )

    # The core is asked about first, and the order is deliberate. Both facts
    # are missing for most boards, and of the two the core is the one that
    # decides: writing a memory map for a chip whose instruction set nothing
    # executes buys nothing. `catalogue.missing_cores` orders the backlog the
    # same way and for the same reason. targets.py already phrases this
    # refusal, including the build command, and its wording is the one the UI
    # shows elsewhere.
    try:
        targets.require_selectable(board.core)
    except targets.TargetError as error:
        raise BoardRunError(
            "core-not-built",
            f"{board_name} is a {board.chip} and needs the {board.core} "
            f"core: {error}"
        ) from error

    if not board.described:
        described = sorted(catalogue.described_chips()) or ["nothing"]
        raise BoardRunError(
            "chip-not-described",
            f"{board_name} is a {board.chip} and no module describes that "
            f"chip, so an image would have no memory to load into. "
            f"webui/boards/ describes {', '.join(described)}"
        )

    module_name = description_module(board.chip)
    try:
        description = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        raise BoardRunError(
            "chip-not-described",
            f"{board_name}: the catalogue reports {board.chip} as described, "
            f"but {module_name} does not import: {error}"
        ) from error
    abi_name = f"core.{board.core}.abi"
    try:
        abi = importlib.import_module(abi_name)
    except ModuleNotFoundError as error:
        raise BoardRunError(
            "core-not-built",
            f"{board_name}: the {board.core} core is built but {abi_name} "
            f"does not import: {error}"
        ) from error

    # The machine module before the contract check, because the contract asks
    # it what this board owes: `VECTOR_TABLE_OFFSETS` is required of an Armv6-M
    # board and of nothing else. A core with no machine module cannot host a
    # board at all, and `core_requirements` raises saying so rather than
    # answering that the board owes nothing.
    machine_name = f"core.{board.core}.machine"
    try:
        machine = importlib.import_module(machine_name)
    except ModuleNotFoundError as error:
        raise BoardRunError(
            "core-not-built",
            f"{board_name}: the {board.core} core is built, but nothing "
            f"describes how that kind of machine powers on -- {machine_name} "
            f"does not exist, so an image could be loaded and never entered"
        ) from error

    try:
        contract.check(description, board.core)
    except contract.RuntimeContractError as error:
        raise BoardRunError("chip-not-described", str(error)) from error

    return Runtime(board.name, board.chip, board.core, description, abi, machine)


#: A ceiling on one `run` call. `webui/emulator.py` states the reasoning for
#: its own: without one, a single request pins the server for as long as the
#: caller likes. A separate number rather than a shared one because these are
#: different cores at different speeds, and the right ceiling is a property of
#: the core, not of the idea.
MAX_RUN_STEPS = 200_000

#: The widest memory window `state` will read, so one request cannot ask for
#: the whole of a 2 MB flash and be handed it as a JSON array of integers.
MAX_WINDOW_BYTES = 4096

#: How many memory-mapped words one `state` call will read. A peripheral view
#: watches a handful; a request asking for thousands is reading flash the slow
#: way, one `read_word` at a time.
MAX_WATCHED_WORDS = 32

#: How much of a board's UART output one `state` call will carry. The core
#: keeps everything ever transmitted, so a program printing in a loop grows it
#: without bound and this is the only field in `state` that a *program* can
#: make arbitrarily large. Over the cap the **oldest** bytes are dropped and
#: the count of them is reported: a console wants the newest line, and silently
#: keeping the first 64 KiB of a program that has printed a megabyte would show
#: a console frozen at boot with no indication why.
MAX_UART_BYTES = 64 << 10


def uart_view(runtime: Runtime, cpu: Core) -> dict[str, object]:
    """What a board has printed, as something a page can render.

    Three decisions, all of which could have gone the other way:

    **Cumulative, not since-last-poll.** `uart0_output` is everything ever
    transmitted and this passes that through. A delta would make `state`
    answer differently on two identical calls, which is the one thing a GET
    should not do -- and with two browser tabs polling, each would consume
    bytes the other never saw. So the endpoint reports what is true and a
    console **replaces** its contents rather than appending. `bytes` is there
    so a client can tell "nothing new" without diffing the text.

    **Bytes are not text, and the answer says so rather than failing.**
    Firmware printing binary is ordinary and a decode error must not take the
    endpoint down. Undecodable bytes become backslash-x escapes, which is
    `backslashreplace` and not `replace`: U+FFFD throws the byte away, and a
    reader debugging a baud-rate mistake needs to see *which* byte arrived.
    `undecodable_bytes` is exact, so a page can say "this is not text" instead
    of showing escapes as though the firmware had printed them.

    **A board with no UART model says so.** Not an empty string: an empty
    console reads as "ran and printed nothing", which is a claim about the
    program. `present: false` is a claim about the model, and they are
    different facts.
    """
    printer = getattr(runtime.description, "uart0_output", None)
    if printer is None:
        return {
            "present": False,
            "note": (
                f"{runtime.description.__name__} models no UART, so nothing on "
                f"a {runtime.chip} can print. This is a gap in the board "
                f"description, not silence from the program."
            ),
        }

    data = printer(cpu)
    dropped = max(0, len(data) - MAX_UART_BYTES)
    shown = data[dropped:]
    # `ignore` drops exactly the undecodable bytes and UTF-8 round-trips the
    # rest, so re-encoding what survived gives the decodable byte count and
    # the difference is the rest. Exact, and it needs no second decoder.
    decodable = len(shown.decode("utf-8", errors="ignore").encode("utf-8"))
    return {
        "present": True,
        "bytes": len(data),
        "dropped_bytes": dropped,
        "text": shown.decode("utf-8", errors="backslashreplace"),
        "undecodable_bytes": len(shown) - decodable,
    }


#: What a pad can be doing.
#:
#: **Three of these are claims about the program and one is a claim about this
#: repository**, and keeping them in one vocabulary is the whole point of the
#: distinction. `high`, `low` and `input` say what the firmware has done to a
#: pin. `unknown` says nobody here can answer -- because nothing here reads
#: that pin's level at all, which `pad_view` states per pad as `modelled`
#: whether or not the pad names an MCU pin (OH-172); because no program is
#: running, which it states as `read_levels`; or because the running program
#: has taken the pin somewhere its registers do not show.
#:
#: Reporting `unknown` as `low` would be the failure this project ranks worst:
#: a picture of a board with every pad dark, indistinguishable from a program
#: that has driven nothing, and no way for a reader to tell which they are
#: looking at.
PIN_STATES = ("high", "low", "input", "unknown")

#: What the outside can drive a pad to, through `BoardSession.drive`: the
#: two levels, and "open" for a pad nothing drives (OH-161 step 3). Not
#: `PIN_STATES`' words, which say what the PROGRAM is doing to a pad.
DRIVE_LEVELS = ("high", "low", "open")

#: Arduino's silkscreen marks a PWM-capable pin with a leading tilde -- `~11`
#: is pin 11. The pad map carries the silkscreen's spelling because that is
#: what somebody reads off the board; a board module carries the pin's name.
#: One character, stripped in one place.
PWM_MARK = "~"


def header_key(label: str, names: typing.Mapping[str, object]) -> str:
    """The board module's key for a pad label, or the label itself.

    A XIAO's silkscreen writes two names on one pad where two things reach
    it: the ESP32-C3's `D9/BOOT` is its `D9`, and the same board's underside
    `D3/MTDI` is its `D3`. The board-support packages define `D9` and `D3`,
    so that is what `HEADER` and `pin_states` are keyed by (OH-160), and this
    is the one place a pad's spelling is joined onto the module's: the first
    `/`-separated part the module knows, after the PWM mark is stripped.

    A label the module knows nothing about comes back as itself, so a pad
    nobody answers for keeps its own name in the table -- `GND` stays `GND`
    rather than becoming whichever half of it happened to match nothing.

    A tilde before a brace is not the mark: KiCad writes a name drawn with
    a bar over it that way, as SparkFun's `~{RST}` (OH-194), and it stays.
    """
    name = label if label.startswith(PWM_MARK + "{") else label.lstrip(PWM_MARK)
    return next((part for part in name.split("/") if part in names), name)


def pin_levels(runtime: Runtime, cpu: Core) -> dict[str, str] | None:
    """Just the states, keyed by pin name. `None` when the board maps no pins.

    **Split from `pin_view` because the two things change at different rates.**
    Where a pad is never changes; what it is doing changes every time the
    program runs an instruction. So the geometry is fetched once when a board
    is loaded and this rides the state poll, which happens many times a second
    -- sending thirty-two coordinates twenty times a second to redraw the same
    board would be the whole difference in the payload.
    """
    if is_row(runtime.board):
        return row_levels(runtime, cpu)
    reader = getattr(runtime.description, "pin_states", None)
    return None if reader is None else reader(cpu)


def is_row(board: str) -> bool:
    """A board from `tools/board_manifest.py`, whose chip module's pin table
    is keyed by another board's labels (rules/board-claims.md §6)."""
    return board_manifest.find(board) is not None


def row_levels(runtime: Runtime, cpu: Core) -> dict[str, str] | None:
    """A row's levels, keyed by its own pad labels, each read at the pad's
    `chip_index` from the board file (OH-179).

    The chip module's `pin_states` would answer in a XIAO's labels, so this
    reads the module's `GPIO_ENABLE` and `GPIO_OUT` words itself, `ENABLE`
    deciding before `OUT` as those modules do; a test holds the two equal
    on every GPIO both name. `None` where the module names no such words,
    and a pad with no `chip_index` gets no level.

    **Those words decide only a pad they are routed to.** A module that
    names `unrouted_level` is asked first, per pad, and where it answers,
    its answer is the pad's level: the RP2040's does wherever the pad's
    `FUNCSEL` does not select SIO (OH-196), so a pad there reads `high` or
    `low` only where an image has selected SIO on it, as silicon requires.
    """
    description = runtime.description
    words = [getattr(description, name, None) for name in ("GPIO", "GPIO_ENABLE", "GPIO_OUT")]
    layout = pinmap.load(runtime.board)
    if None in words or layout is None:
        return None
    base, enable_at, out_at = words
    unrouted = getattr(description, "unrouted_level", None)
    enable = cpu.read_word(base + enable_at)
    out = cpu.read_word(base + out_at)
    levels: dict[str, str] = {}
    for pad in layout.pads:
        if pad.chip_index is None:
            continue
        mask = 1 << pad.chip_index
        instead = None if unrouted is None else unrouted(cpu, pad.chip_index)
        levels[header_key(pad.label, {})] = (instead if instead is not None
                                             else "input" if not enable & mask
                                             else "high" if out & mask else "low")
    return levels


def level_keys(board: str, description: types.ModuleType | None,
               layout: pinmap.PinMap | None) -> frozenset[str]:
    """The names this board could ever report a level under -- the keys
    `pin_levels` answers with -- known without a CPU (OH-172).

    A module's `pin_states` answers under its `HEADER`. A module with the
    reader and no `HEADER` is refused here, naming itself, rather than left
    to raise `AttributeError`: `webui/boards/contract.py` does not require a
    `HEADER`, and this is the caller that needs one.

    **A row's half restates `row_levels` rather than sharing with it**, and
    it restates three things: the word names `GPIO`, `GPIO_ENABLE` and
    `GPIO_OUT`; that a pad with no `chip_index` gets no level; and the key
    spelling `header_key(pad.label, {})`, which `pad_view`'s empty `names`
    for a row makes a third time and `drive_table` a fourth (OH-161 step 3).
    Not one helper, because `row_levels` needs the words' values, this needs
    only that they exist, and `drive_table` needs each key's index: a helper
    serving all three would hand back the words and a keyed index map, an
    interface no simpler than the lines it hides, for callers in one file
    (rules 6 to 8 of `.claude/CLAUDE.md`). What keeps the copies one answer
    is two tests: `tests/webui/test_pin_view.py` holds this set equal to the
    keys `pin_levels` answers, on every board in the catalogue, and
    `tests/webui/test_board_run.py` holds `drive_table`'s keys equal to it
    on every board whose description reads input.
    """
    if is_row(board):
        words = [getattr(description, name, None) for name in ("GPIO", "GPIO_ENABLE", "GPIO_OUT")]
        if None in words or layout is None:
            return frozenset()
        return frozenset(header_key(pad.label, {}) for pad in layout.pads
                         if pad.chip_index is not None)
    # The reader is asked for before the header, because OH-160 generates
    # `HEADER` and `PIN_NAMES` and leaves `pin_states` hand-written: a module
    # with a header and no reader models nothing.
    if getattr(description, "pin_states", None) is None:
        return frozenset()
    if not hasattr(description, "HEADER"):
        raise contract.RuntimeContractError(
            f"{getattr(description, '__name__', description)} has pin_states "
            f"and no HEADER, so nothing names the pins it reads a level for: "
            f"level_keys takes HEADER's keys as the names pin_states answers "
            f"under (OH-172)"
        )
    return frozenset(description.HEADER)


def drive_table(board: str, description: types.ModuleType,
                layout: pinmap.PinMap | None) -> dict[str, int]:
    """Each name `BoardSession.drive` accepts, and the GPIO it drives: on a
    manifest row, its own board file's pads with a `chip_index`, keyed by
    `header_key(pad.label, {})`; elsewhere the description's `HEADER`.

    **The fourth restatement of a row's half** that `level_keys`' docstring
    counts, kept a copy for the reason that docstring gives: this needs the
    index each name resolves to, which `level_keys` does not, and a helper
    serving both would be no simpler than the lines it hides.
    `tests/webui/test_board_run.py`'s
    `test_the_names_drive_accepts_are_the_names_pin_levels_answers_under`
    holds its keys equal to `level_keys` on every board whose description
    reads input. A row with no board file has no names, as it has no levels.
    """
    if is_row(board):
        if layout is None:
            return {}
        return {header_key(pad.label, {}): pad.chip_index
                for pad in layout.pads if pad.chip_index is not None}
    return dict(description.HEADER)


def description_for(board: str) -> types.ModuleType | None:
    """The board module for this board, or `None` where there is not one.

    **Deliberately not `runtime_for`, and that is the whole point of OH-94.**
    That function resolves everything needed to EXECUTE -- including a core
    that has been built -- and refuses at each join. Fourteen of the
    twenty-six boards have no core built, and a `XIAO-MG24-DIP` has no
    `webui/boards/mg24.py` at all. It also has twenty-four pads, and where
    they sit is not an execution: it must not need one.

    So this asks the smallest question that gets `PIN_NAMES` and `SUPPLY`, and
    answers `None` rather than raising when the module is absent -- which is a
    board drawn without pin names, not a board that cannot be drawn.
    """
    try:
        chip = catalogue.chip_for(board)
    except catalogue.CatalogueError:
        return None
    try:
        return importlib.import_module(description_module(chip))
    except ModuleNotFoundError:
        return None


def chip_pin_of(name: str, names: dict[str, str], pad: pinmap.Pad) -> str | None:
    """Which MCU pin a pad reaches, from the module first and the file second.

    **A caption and nothing more** (OH-172). Whether anything reads the pin's
    level is `modelled`, which `level_keys` answers from the board's reader;
    a pad on a board with no module names its chip pin here and is still not
    modelled.

    **Two sources and a fixed order, not a merge.** `PIN_NAMES` is the board
    module's, and it wins wherever it has an entry, because it is the same
    table `pin_states` reads levels through -- so a label cannot carry one pin
    in the caption and another in the state. The board file's `chip_pin` fills
    the holes: it comes from `tools/import_pindefs.py` reading the vendor's own
    board-support package, and it is the only source there is for a board
    that has no module at all.

    **The fallback can only ever fill a hole and never overrule one** (OH-167).
    Measured 2026-09-05 across all 26 boards: 125 pads where both state a pin
    and agree, 0 where they disagree, and 196 where only the file states one
    and the page therefore said "not modelled" over an answer sitting on disk
    beside it -- 19 of the MG24's 24 pads, 28 of the nRF54LM20A SMD's 48.

    A disagreement is left to the caller to notice rather than resolved here,
    for the reason OH-26 gives about two vendor readings in conflict: it is
    recorded, not averaged. There are none today, which is what makes this
    order safe to fix rather than a preference between two answers.
    """
    stated = names.get(name)
    return stated if stated is not None else pad.chip_pin


def pad_view(board: str, description: types.ModuleType | None,
             live: dict[str, str] | None) -> dict[str, object]:
    """Where a board's pads are, and what each one is doing if anything is.

    Two sources joined on the pad label, and neither of them is this function's
    own opinion. **Position** comes from `webui/pinmap.py`, which reads
    `webui/boards/<board>.json` -- coordinates the vendor's own KiCad footprint
    produced, exact to three decimals. **State** comes from the board module's
    `pin_states`, read by `pin_levels` for a caller that has a session.

    **`live` is None when nothing is running, and that is now a picture rather
    than a refusal.** It used to mean `present: False` -- draw nothing -- and
    that hid two different boards for one reason. A board that has been PICKED
    but not loaded has no levels; so does a board whose description models no
    pins, which is fourteen of the twenty-six: OH-160 gave the ESP32-C3, C5,
    C6 and RP2040 modules a generated `HEADER`, so twelve boards now answer
    where three did. (This sentence said "twenty-four" from OH-94 until then,
    and that was one too many: `samd21.py` already had a `pin_states`, so the
    boards that could not answer were twenty-three.) Both have pads, and the
    page has words for a pad it cannot answer for: `unknownWords` writes a
    sentence per row and the panel's note counts them.

    So `present` now means **there is something to draw** -- a pad map exists,
    or there are states to report -- and the two views are ONE implementation.
    Keeping them apart is what let the picker draw nothing for as long as it
    has: `webui/static/board3d-panel.js` asks one endpoint, and the answer for
    a board you chose has to be the same answer as for a board you loaded.

    **A pin with no pad is still reported.** The XIAO's user LED is on the
    board rather than on the header, so `LED` has a state and no coordinate --
    and it is the pin a stock Blink drives on a XIAO. Dropping it because it
    has nowhere to go on the picture would hide the one thing most sketches
    move; the caller gets `x: None` and puts it somewhere sensible.

    **A manifest board reports its pads and nothing else** (`row_levels`), so
    its `LED_BUILTIN` moves the page only where a pad's `chip_index` is that
    GPIO. On the Adafruit Feather ESP32-C6 one is: its own variant's
    `LED_BUILTIN` is `IO15`'s `chip_index` (OH-178), and
    `test_a_stock_blink_moves_the_pad_its_led_builtin_reaches` watches a stock
    Blink move that pad here (OH-183).
    """
    layout = pinmap.load(board)
    if layout is None and not live:
        module = getattr(description, "__name__", None)
        return {
            "present": False,
            "note": (
                f"{module or 'no board description'} maps no header pins, and "
                f"there is no pad map for {board!r} either, so there is "
                f"nothing to draw and nothing to report. This is a gap in the "
                f"board description, not a program that has driven nothing."
            ),
        }
    # **Whether anything was READ, which the next line is about to forget.**
    # `None` is a board that has been picked and not loaded; a dict, even an
    # empty one, is a board with a session that was asked. Kept before the
    # coalesce because after it there is nothing left to tell them apart with,
    # which is the whole of OH-164.
    #
    # **The invariant that makes those the only two cases lives in `pin_view`,
    # not here**, and a first draft of this comment claimed it lived in the
    # type: `pin_levels` returns `None` for a description with no `pin_states`,
    # so a running board could have arrived with `None` and reported that
    # nothing was running. `pin_view` coalesces for that reason and says so.
    read_levels = live is not None
    live = live or {}

    # Which MCU pin each label reaches -- `D6` -> `PB08`. **The connection the
    # view is named for**, and the board module derives it from the same table
    # it reads levels through, so a label cannot have one pin here and another
    # there. Absent for a board that does not publish it, which is a missing
    # caption rather than a missing state. A row's chip module spells another
    # board's labels, so a row keys each pad by its own and captions it from
    # its own file (`row_levels`).
    names: dict[str, str] = {} if is_row(board) else getattr(description, "PIN_NAMES", {})
    # **Whether anything reads a pad's level, which a caption does not say**
    # (OH-172). The panel's "not modelled" is asked of this and not of
    # `chip_pin`, because a board with no module captions its pads from its
    # own file and still has nothing that reads them.
    readable = level_keys(board, description, layout)

    pads: list[dict[str, object]] = []
    placed: set[str] = set()
    if layout is not None:
        for pad in layout.pads:
            # `pin` is the module's key and `label` the silkscreen's, and
            # they differ on a pad written `D9/BOOT`: `header_key` says how
            # they meet. The page wires and polls by `pin`, so two pads that
            # are one GPIO -- the C3 SMD's `D3` and its underside `D3/MTDI`
            # -- share a name and a state, as they share a wire.
            name = header_key(pad.label, names)
            placed.add(name)
            pads.append({
                "label": pad.label,
                "pin": name,
                "chip_pin": chip_pin_of(name, names, pad),
                "modelled": name in readable,
                "x": pad.x,
                "y": pad.y,
                "group": pad.group,
                "state": live.get(name, "unknown"),
            })
    # Pins the board can answer for that the pad map has nowhere to put. Listed
    # after the placed ones so a caller can render them in order and stop.
    # Modelled by construction: the reader answered under the name.
    for name in live:
        if name not in placed:
            pads.append({
                "label": name, "pin": name, "chip_pin": names.get(name),
                "modelled": True,
                "x": None, "y": None,
                "group": "on-board", "state": live[name],
            })

    return {
        "present": True,
        "board": board,
        "width": layout.width if layout is not None else None,
        "height": layout.height if layout is not None else None,
        # The map's own scale where it states one (every generated map), or
        # None for the traced Uno map, whose scale the page fits. OH-121.
        "px_per_mm": layout.px_per_mm if layout is not None else None,
        # **What a pin of this part can drive**, so that the 3D view can solve a
        # circuit instead of lighting an LED because one pad reads high. Found
        # by `getattr` exactly as `pin_states` and `PIN_NAMES` are, and `None`
        # for a board whose module publishes no electrical model -- which
        # `webui/static/circuit.js` reports in words rather than filling in.
        #
        # It rides the geometry fetch and not the state poll because it never
        # changes: an output resistance is a property of silicon, and sending
        # it twenty times a second beside the pin levels would be the same
        # mistake `pin_levels` exists to avoid.
        "supply": getattr(description, "SUPPLY", None),
        # **Which component on the board a pin lights** (OH-169), as the
        # vendor's board file names it, mapped to the header label that drives
        # it. Found by `getattr` exactly as `SUPPLY` and `PIN_NAMES` are, so
        # this function still does not know what an LED is -- and `None` for a
        # board whose module names none, which is twenty-five of twenty-six.
        #
        # It rides the geometry fetch rather than the state poll for the reason
        # `supply` does: which component is the LED never changes, and only its
        # level does.
        "led_parts": getattr(description, "LED_PARTS", None),
        # **Named rather than left for the caller to count.** "17 of 32 pads
        # cannot be answered for" is the sentence a reader needs in order to
        # know whether they are looking at a quiet program or a thin model.
        "unknown": sum(1 for pad in pads if pad["state"] == "unknown"),
        # **Stated rather than inferred** (OH-164). A pad with no state is one
        # of three things and the page could only tell two of them apart: a
        # pin no module models, a pin a running program has taken elsewhere,
        # and every pin of a board nobody has loaded. The third read as the
        # second, so a board you had merely picked told you 22 of its 32 pads
        # were in use while nothing was running.
        #
        # The page cannot work it out for itself, and the shape it would reach
        # for -- `unknown == len(pads)` -- is a guess that is also true of a
        # loaded program which happens to drive nothing. This is the fact, and
        # it is known here: OH-121 paid once already for a view re-deriving a
        # number the file could have said.
        "read_levels": read_levels,
        "pads": pads,
    }


def pin_view(runtime: Runtime, cpu: Core, board: str) -> dict[str, object]:
    """`pad_view` for a board that is loaded, with its levels read.

    **One line, and it is the point.** The view of a board you picked and the
    view of a board you loaded are the same view with and without states, so
    they are one implementation. Two functions answering the same question is
    how `readPalette` and the glTF writer disagreed about sRGB for as long as
    both existed.
    """
    # **`or {}` and not the bare call**, because `pin_levels` answers `None`
    # for a description with no `pin_states` -- and a board that is RUNNING
    # with no reader is still a board that was asked. Without this, such a
    # board would report `read_levels` false while its program ran.
    #
    # Nothing has that shape today: every module with `PIN_NAMES` also has
    # `pin_states`, which `tests/webui/test_pin_view.py`'s
    # `test_a_running_board_whose_module_reads_no_pins_still_says_one_is_running`
    # asserts. But OH-160 generates the first from a `HEADER` and leaves
    # the second hand-written, so the shape it produces is precisely a module
    # that could have one without the other. Coalescing here is what makes
    # `pad_view`'s `read_levels` mean what it says rather than what happens to
    # be true of today's board modules.
    #
    # **What such a board would then say**, stated here rather than found
    # later: "not modelled" on every pad since OH-172, with the coalesce or
    # without it. Where `pin_levels` answers `None`, `level_keys` is empty,
    # so no pad is modelled: the names that module publishes are captions and
    # nothing more -- the answer a board with no module gets. So the coalesce
    # changes no word on the page. What it keeps is `read_levels` true for a
    # board that is running, which is the fact that field states.
    return pad_view(board, runtime.description, pin_levels(runtime, cpu) or {})


#: How many instructions a listing carries. Enough to fill the pane without
#: making every poll disassemble a screenful nobody scrolls to.
LISTING_LENGTH = 24


def listing_view(runtime: Runtime, cpu: Core, at: int,
                 count: int = LISTING_LENGTH) -> dict[str, object]:
    """The instructions around the program counter, as something a page can
    render.

    **A core with no disassembler says so, exactly as a board with no UART
    does.** An empty listing reads as "there is no code there", which is a
    claim about the image; `present: false` is a claim about this repository,
    and they are different facts. `riscv32` is built and has no `disasm` module
    today, so this is a live case rather than a hypothetical.

    **The address is flat, and that is a board-shaped assumption rather than a
    universal one.** `core/cortexm0/disasm.py` takes `(cpu, address, count)`;
    `core/i8086/disasm.py` takes `(cpu, cs, ip, count)`, because that machine
    is genuinely segmented. The difference is real and it costs nothing here:
    **no board carries an i8086**, so the board path only ever needs the flat
    form. If one ever does, this is where the two shapes have to meet.
    """
    module_name = f"core.{runtime.core}.disasm"
    try:
        disasm = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return {
            "present": False,
            "note": (
                f"{runtime.chip} runs on the {runtime.core} core, which has no "
                f"disassembler: {module_name} does not exist. The board still "
                f"steps and its registers still read; only the listing is "
                f"missing."
            ),
            "lines": [],
        }

    return {
        "present": True,
        "at": at,
        "lines": [
            {
                "address": line.address,
                "raw": line.raw,
                "text": line.text.expandtabs(1),
                "current": line.address == at,
            }
            for line in disasm.disassemble_range(cpu, at, count)
        ],
    }


@dataclasses.dataclass(frozen=True)
class RunResult:
    """How far a run got, and why it stopped if it did."""

    steps: int
    #: "running" -- the budget ran out with the program still going --
    #: "stopped", the core having refused the firmware, or "faulted", the
    #: core having faulted on the host; `detail` carries what the core said.
    status: str
    detail: str


def _check_fits(runtime: Runtime, cpu: Core, image: firmware.Image) -> None:
    """Every byte must land somewhere this board maps.

    This is what rejects an image on its own addresses instead of on a fault
    twenty thousand instructions later. Again the board is the authority: an
    ESP32-C3 image at 0x42000020 fails here on a board whose flash is at
    0x10000000, and no table in this module had to know either number.

    `machine.refuses` rather than `cpu.in_range` because "can an image land
    here" and "can a hexdump read here" are the same question only on a
    machine with one address space. On an AVR an image loads into program
    memory and the hexdump reads data memory, and a single predicate would
    have to guess which was meant.

    **It answers with a sentence rather than a bool**, and this composes rather
    than writes the refusal. The reason is a lesson from the AVR: an odd
    program address is a real refusal with a real explanation, and this module
    -- which knows the board's name and the image's format but nothing about
    words -- could only have called it "maps nothing there", which is both
    false and a wrong lead.
    """
    for segment in image.segments:
        refusal = runtime.machine.refuses(cpu, segment.address, len(segment.data))
        if refusal is None:
            continue
        raise BoardRunError(
            "outside-the-board-map",
            f"{runtime.board} ({runtime.chip}) cannot take this "
            f"{image.format} image's {len(segment.data)}-byte segment: "
            f"{refusal}"
        )


def _place(
    runtime: Runtime, cpu: Core, image: firmware.Image, requested: int | None
) -> typing.Any:
    """Leave the board at reset, and say where that is.

    Every decision here belongs to the machine and none to this module: what a
    reset state *is*, whether there is a vector table to read, and what to do
    when there is not. All this adds is the board's name and the name of the
    keyword that overrides the search, which are facts about this layer's own
    interface rather than about the silicon.
    """
    offsets = getattr(runtime.description, "VECTOR_TABLE_OFFSETS", ())
    try:
        return runtime.machine.enter(cpu, image, requested, offsets)
    except runtime.machine.MachineError as error:
        # The override is only advice on a machine that searches offsets at
        # all. Suggesting `vector_table=` to someone whose board begins at
        # address zero would send them looking for a table that does not
        # exist -- a message that costs more than it saves.
        advice = (
            ". Pass vector_table= if the image is linked somewhere else"
            if offsets
            else ""
        )
        raise BoardRunError(
            "no-vector-table", f"{runtime.board}: {error}{advice}"
        ) from error


class BoardSession:
    """A board with an image on it, stopped at the reset vector.

    The caller owns the core's lifetime: `close()` releases it, and the class
    is a context manager so a test or a request handler does not have to
    remember. Stepping is the caller's too -- this deliberately does not run a
    budget of its own, because how long to run is a question about what is
    being watched, not about the board.
    """

    def __init__(
        self,
        runtime: Runtime,
        cpu: Core,
        image: firmware.Image,
        placement: typing.Any,
    ) -> None:
        self.runtime = runtime
        self.cpu = cpu
        self.image = image
        self.placement = placement
        #: "running" until the core refuses an instruction, then "stopped" --
        #: or "faulted", if the core itself faulted on the host (`_stop`).
        #: A program that faults is a fact about the program, not a failure of
        #: this layer, so it is recorded here and reported rather than raised.
        self.status = "running"
        self.detail = ""
        #: Instructions retired since the image was loaded, by `step` and
        #: `run` together: the clock `inputs` is stamped with.
        self.retired = 0
        #: Every `drive`, in order: the instructions retired when it took
        #: effect, and what it said (OH-161 step 3). **The replay record**:
        #: a level enters a session only through `drive`, so this image and
        #: this list reproduce the run -- no clock and no randomness is
        #: consulted, and when a call arrived in wall time is not part of it.
        self.inputs: list[tuple[int, dict[str, str]]] = []

    @property
    def board(self) -> str:
        return self.runtime.board

    @property
    def chip(self) -> str:
        return self.runtime.chip

    def step(self, count: int = 1) -> None:
        """`count` instructions, or raise from the core saying why not.

        Raises, unlike `run`. A caller stepping one instruction at a time is
        watching for the stop and wants the traceback; a caller asking for
        twenty thousand wants the answer.

        **The stop is recorded before it is raised**, as `run` records it, and
        a session that has stopped steps no further (OH-225): after a host
        fault the core has left the machine part-way through an instruction,
        and a step that carried on would run the program from a state no
        instruction produced. That refusal is the core's own `AbiError`,
        naming what stopped it. `/api/board/step` calls `run` instead, which
        reports a stop rather than raising it.
        """
        if self.status != "running":
            raise self.runtime.abi.AbiError(
                f"{self.board} is {self.status} and steps no further until "
                f"an image is loaded again: {self.detail}")
        for _ in range(count):
            try:
                self.cpu.step()
            except self.runtime.abi.AbiError as error:
                self._stop(error)
                raise
            self.retired += 1

    def _stop(self, error: Exception) -> None:
        """Record what stopped the core, for `step` and `run` alike.

        "faulted" when the core itself broke -- its `HostFault`, a fault on
        the host that is a bug in the core -- and "stopped" when it refused
        the firmware: an encoding it lacks, an access off the board's map.
        The 8086 debugger has said "faulted" for the first since OH-223, and
        a page that said "stopped" for both would send a reader to the
        firmware for a bug in the simulator (OH-225).
        """
        broke = isinstance(error, self.runtime.abi.HostFault)
        self.status = "faulted" if broke else "stopped"
        self.detail = str(error)

    def drive(self, levels: typing.Mapping[str, str]) -> None:
        """What the outside drives onto the pins: name -> "high", "low" or
        "open", each name as `pin_levels` keys it.

        **The names are `pin_levels`' and not only the pads'**: on a XIAO they
        are its description's `HEADER`, which names pins a package may have
        no pad for -- `LED` on every XIAO ESP32-C5 and C6, `BOOT` and `MTCK`
        on their DIPs -- and a level the page reports under a name is a level
        the bench may drive under it. On a manifest row they are its own
        board file's pads with a `chip_index`. `drive_table` resolves them,
        and `test_the_names_drive_accepts_are_the_names_pin_levels_answers_under`
        holds its keys equal to `level_keys`.

        **A whole statement, not a change.** A pin left out is a pin nothing
        drives, so each call says everything the outside is doing, and
        `inputs` records it with the instructions retired when it took
        effect. "open" says so explicitly. **The record keeps the names, not
        the GPIOs they resolve to**, because a replay goes back through this
        method, which resolves them again from the same board's tables; what
        the core saw follows from that, and
        `test_the_image_and_the_record_of_drives_replay_the_run` holds that a
        replay lands every drive on the same instruction and ends the same.

        **A drive on a pin the program drives as an output is accepted,
        recorded, and ignored by the core**: `IN` follows `OUT` there, and
        what a pin and a part fighting over one node do is the bench's to
        solve. A floating pin reads 0 and a bench drive beats the chip's own
        pull: the board description's `install_gpio_in` says why. This is
        what the page's bench will call, once it has solved what its parts
        put on each input pin (OH-161 step 3, slice B).

        `ValueError`, naming the values, for a level that is none of the
        three, a name that reaches no GPIO, two names of one GPIO driven two
        ways, a manifest row with no board file to resolve names against, and
        a board whose description reads no input at all. A refusal slug in
        `REASONS` waits for the transport that maps them to statuses.
        """
        driver = getattr(self.runtime.description, "drive_pins", None)
        if driver is None:
            raise ValueError(
                f"{self.board}: its description reads no input, so nothing "
                f"can be driven onto its pads")
        layout = pinmap.load(self.board) if is_row(self.board) else None
        if is_row(self.board) and layout is None:
            raise ValueError(
                f"{self.board}: no board file under webui/boards/ gives its "
                f"pads a GPIO, so no name can be resolved to drive")
        gpios = drive_table(self.board, self.runtime.description, layout)
        driven: dict[int, bool] = {}
        by_gpio: dict[int, str] = {}
        for label, level in levels.items():
            if level not in DRIVE_LEVELS:
                raise ValueError(
                    f"{self.board}: {label!r} driven {level!r}; a pad is driven "
                    f"{', '.join(repr(word) for word in DRIVE_LEVELS)}")
            if label not in gpios:
                raise ValueError(
                    f"{self.board}: no pad {label!r} reaches a GPIO; the pads "
                    f"that do are {sorted(gpios)}")
            if level == "open":
                continue
            gpio = gpios[label]
            if gpio in driven and driven[gpio] != (level == "high"):
                raise ValueError(
                    f"{self.board}: {by_gpio[gpio]!r} and {label!r} are both "
                    f"GPIO{gpio}, driven {levels[by_gpio[gpio]]!r} and {level!r}")
            driven[gpio] = level == "high"
            by_gpio[gpio] = label
        driver(self.cpu, driven)
        self.inputs.append((self.retired, dict(levels)))

    def run(self, budget: int) -> RunResult:
        """Up to `budget` instructions, stopping where the core does.

        A fault is **reported, not raised**. A program running off into
        unmapped memory is a fact about that program, and the message the core
        composed -- which access, at which address, from which instruction --
        is the most useful thing anyone gets all day. Losing it to a traceback
        in a request handler would be a waste.
        """
        if budget < 1:
            raise BoardRunError(
                "budget-refused", f"a budget of {budget} steps runs nothing"
            )
        if budget > MAX_RUN_STEPS:
            raise BoardRunError(
                "budget-refused",
                f"a budget of {budget} exceeds {MAX_RUN_STEPS}; ask again to "
                f"keep going. Without a ceiling one request pins the caller "
                f"for as long as it likes",
            )
        if self.status != "running":
            return RunResult(0, self.status, self.detail)

        taken = 0
        for _ in range(budget):
            try:
                self.cpu.step()
            except self.runtime.abi.AbiError as error:
                self._stop(error)
                break
            taken += 1
        self.retired += taken
        return RunResult(taken, self.status, self.detail)

    def state(self, memory_at: int | None = None, memory_length: int = 64,
              words: typing.Sequence[int] = ()) -> dict:
        """Registers, a window of memory, and any single words asked for.

        **Memory and peripherals are separate arguments because the core keeps
        them separate.** A region -- flash, SRAM -- is bulk memory and reads a
        block at a time. A memory-mapped register is one word that a
        peripheral computes; `in_range` is false for it by design and
        `read_block` refuses it. Watching a blink means reading SIO's
        GPIO_OUT, so a state call that could only do the first would be unable
        to show the thing the whole exercise is about.

        `memory_at` defaults to the vector table, the one address this layer
        knows is on the board. A window off the board is refused by name
        rather than left to fault: asking about an address is not executing
        one, and the answer should be a sentence.

        `uart` is the fourth thing and the only one a *program* writes: see
        `uart_view` for why it is cumulative rather than a delta, why an
        undecodable byte is rendered instead of raised, and why a board with
        no UART model says so rather than returning an empty string.
        """
        if memory_length < 1 or memory_length > MAX_WINDOW_BYTES:
            raise BoardRunError(
                "window-refused",
                f"a window of {memory_length} bytes is outside 1..{MAX_WINDOW_BYTES}",
            )
        if len(words) > MAX_WATCHED_WORDS:
            raise BoardRunError(
                "window-refused",
                f"{len(words)} watched words is more than {MAX_WATCHED_WORDS}",
            )
        machine = self.runtime.machine
        address = self.placement.window if memory_at is None else memory_at
        if not machine.readable(self.cpu, address, memory_length):
            hint = (
                " -- that is a mapped register, not a region, so ask for it "
                "with words="
                if machine.is_register(self.cpu, address)
                else ""
            )
            raise BoardRunError(
                "window-outside-the-map",
                f"{self.board} maps no region at 0x{address:08x}.."
                f"0x{address + memory_length:08x}{hint}",
            )

        watched = []
        for watch in words:
            if not machine.is_register(self.cpu, watch) and not machine.readable(
                self.cpu, watch, 4
            ):
                raise BoardRunError(
                    "window-outside-the-map",
                    f"{self.board} has nothing at 0x{watch:08x} to watch",
                )
            watched.append(
                {"address": watch, "value": machine.word(self.cpu, watch)}
            )

        view = machine.view(self.cpu)
        return {
            "board": self.board,
            "chip": self.chip,
            "status": self.status,
            "detail": self.detail,
            # **Named, not positional, and that is a wire change made on
            # purpose.** A page cannot render an AVR's thirty-two eight-bit
            # registers through a sixteen-name Arm table, and `width` is here
            # so it does not print r0 as `0x000000a5` either. The machine
            # module is the only thing that knows either fact.
            "registers": [
                {"name": r.name, "value": r.value, "width": r.width}
                for r in view.registers
            ],
            "flags": [{"name": name, "on": on} for name, on in view.flags],
            # Explicit, so no caller has to mean "index 15" -- which is true on
            # Armv6-M and on nothing else here.
            "pc": view.pc,
            "memory": {
                "at": address,
                "bytes": list(machine.read(self.cpu, address, memory_length)),
            },
            "words": watched,
            "uart": uart_view(self.runtime, self.cpu),
            # Levels only, and `null` for a board that maps no pins. The
            # geometry comes once from `/api/board/pins`; see `pin_levels` for
            # why the two are not one call.
            "pins": pin_levels(self.runtime, self.cpu),
            # Around the program counter rather than the load address: what a
            # debugger shows is where execution *is*, and after a run that is
            # nowhere near where the image started.
            "listing": listing_view(self.runtime, self.cpu, view.pc),
        }

    def close(self) -> None:
        self.cpu.close()

    def __enter__(self) -> BoardSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def as_json(self) -> dict[str, object]:
        """What a transport hands the UI after a successful load.

        `notes` carries `firmware.Image.notes` through unchanged, plus one of
        this layer's own when an ELF's declared entry point disagrees with the
        vector table that was entered. That disagreement is not an error --
        `e_entry` and the reset vector are allowed to differ -- but a reader
        watching an unexpected instruction stream needs to be told which one
        the core actually took.
        """
        notes = list(self.image.notes) + list(self.placement.notes)
        if self.image.entry is not None and (self.image.entry & ~1) != self.placement.entry:
            notes.append(
                f"the {self.image.format} declares entry "
                f"0x{self.image.entry & ~1:08x}; entered at "
                f"0x{self.placement.entry:08x} instead, which is where this "
                f"board powers on"
            )
        return {
            "board": self.board,
            "chip": self.chip,
            "core": self.runtime.core,
            "format": self.image.format,
            "family": self.image.family,
            "bytes": self.image.total_bytes,
            "segments": [
                {"address": segment.address, "bytes": len(segment.data)}
                for segment in self.image.segments
            ],
            "entry": self.placement.entry,
            "notes": notes,
            # `vector_table` and `stack_pointer` arrive through here on an Arm
            # board and are **absent** on one that has neither, rather than
            # null. Null would say "there is a stack-pointer word and its value
            # is unknown"; absence says the machine has no such word, which is
            # the true and the more useful claim.
            **self.placement.detail,
        }


def load_firmware(
    board_name: str,
    data: bytes,
    *,
    base: int | None = None,
    vector_table: int | None = None,
) -> BoardSession:
    """Put a compiled artefact on a named board, stopped at its reset vector.

    The operation OH-32 is about: a **board** goes in, not a core. Everything
    between is a lookup this module does so a person does not have to.

    `base` is passed to `firmware.load_image` and is required only for a raw
    `.bin`, which carries no address of its own. No default is invented here
    for the same reason `parse_bin` invents none: 0x10000000 is right for a
    pico-sdk RP2040 image and wrong for the bare-metal one in
    `tests/cortexm0/blink/`, which links to 0x10000100.

    `vector_table` overrides the board's `VECTOR_TABLE_OFFSETS` for an image
    linked somewhere neither convention covers. It is passed to the machine
    module, which is free to ignore it: a board whose core begins at address
    zero has no search to override.

    Raises `BoardRunError` at four separate joins -- unknown board, chip with
    no description, core not built, image that does not belong on this chip --
    and `firmware.FirmwareError` when the artefact cannot be read at all.
    """
    runtime = runtime_for(board_name)

    # **Two layers, and each says something the other cannot.**
    #
    # `firmware.EmptyImage` means the artefact parsed and holds nothing to
    # load. The parser knows *what the file contains* -- which UF2 families,
    # how many blocks -- and says so. It does not know which board anybody
    # asked about, so this adds that and keeps the refusal's own slug:
    # `unreadable-artefact` would tell a person to go and fix a file that is
    # perfectly fine and simply built for a different chip.
    #
    # This used to be `if not image.segments` *after* the call, because
    # `parse_uf2` returned an empty image rather than raising. That guard was
    # the only thing standing between a wrong-family UF2 and a successful load
    # of nothing, and a guard is the wrong place for it: every other caller of
    # `firmware.load_image` had the bug. It is a raise in the parser now, and
    # what is left here is the translation.
    try:
        image = firmware.load_image(
            data, base=base, family=UF2_FAMILY_BY_CHIP.get(runtime.chip)
        )
    except firmware.EmptyImage as error:
        raise BoardRunError(
            "nothing-for-this-chip",
            f"{runtime.board}: this artefact holds nothing for a "
            f"{runtime.chip}. {error}",
        ) from error

    cpu = runtime.abi.Cpu()
    try:
        runtime.machine.blank(cpu)
        runtime.description.install(cpu)

        _check_fits(runtime, cpu, image)
        for segment in image.segments:
            runtime.machine.write(cpu, segment.address, segment.data)

        # `enter` leaves the register file at reset as well as reporting where
        # that is, because those are one act. What "at reset" means is the
        # machine's to say: an Armv6-M loads a stack pointer and a reset
        # handler out of two words; an AVR comes up at word zero with SP at
        # RAMEND, which its own `configure` has already established.
        placement = _place(runtime, cpu, image, vector_table)
    except BaseException:
        # The core is a ctypes handle over a native allocation, so a refusal
        # after construction has to release it or the process leaks one per
        # rejected image.
        cpu.close()
        raise

    return BoardSession(runtime, cpu, image, placement)
