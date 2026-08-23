# OpenHardware - an i8086 debugging session, without a transport.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The emulator the UI drives, per ticket OH-7.

## Why this is not the server

Everything here is a plain method on a plain object: load a program, step,
run, read the state back. No HTTP, no JSON, no sockets. `emulator_server.py`
is a thin translation of these calls, and the tests drive *this* -- so what is
tested is the behaviour rather than the encoding around it.

That split is the same one `webui/api.py` already makes for the PICSimLab
bridge, and for the same stated reason: a future WASM build calls these
methods through `ccall` and only the transport changes.

## Running is bounded, always

`run` takes a step budget and returns when it is spent. There is no
"run until it finishes", because a program with a loop that never exits does
not finish, and a server that waits for one stops answering. The UI asks for
another budget when it wants more, which also gives it somewhere to notice
that the user pressed stop.
"""

from __future__ import annotations

import dataclasses

from core.i8086 import abi, disasm

#: The first byte above the interrupt vector table and the BIOS data area.
#:
#: The vector table is 256 entries of four bytes: 0x0000 to 0x03FF. 0x0400 to
#: 0x04FF is where a real machine keeps its BIOS data.
FIRST_FREE = 0x0500

#: Where a program is loaded unless the caller says otherwise.
#:
#: **0x0500, not 0x0100.** This was 0x0100 -- "where DOS loads a .COM" -- and
#: the reason given for it was that it cleared the vector table, which at
#: 0x0100 is simply false: vectors 0x40 through 0xFF live at 0x0100-0x03FF and
#: a program loaded there lands on top of them. DOS gets away with 0x0100
#: because the offset is inside a *segment* whose base is far above the table,
#: and this emulator starts every segment at zero.
#:
#: Caught by a test asserting the property the comment claimed.
DEFAULT_ORIGIN = FIRST_FREE

#: The highest offset a program can occupy. CS is zero and IP is sixteen bits,
#: so nothing above 64 KB is reachable at all.
ADDRESSABLE = 0x10000

#: Where the stack starts: the top of the reachable 64 KB, growing down.
DEFAULT_STACK = 0xFFFE

#: How many instructions a state snapshot disassembles ahead of CS:IP.
DISASSEMBLY_LINES = 24

#: The largest run budget a caller may ask for in one call.
#:
#: A bound, not a preference: without one, a single request can pin the server
#: for as long as the program loops, and the UI has no way to interrupt it.
MAX_RUN_STEPS = 200_000


class EmulatorError(Exception):
    """The session was asked for something it cannot do."""


@dataclasses.dataclass(frozen=True)
class RunResult:
    """What a bounded run did."""

    steps: int
    #: "running", "halted", or "unimplemented".
    status: str
    #: Set only when status is "unimplemented".
    detail: str = ""


class Session:
    """One processor, one loaded program, and the state a UI wants back.

    Owns its `abi.Cpu` and frees it on `close`. Used as a context manager in
    tests; the server keeps one alive for the life of the process.
    """

    def __init__(self, origin: int = DEFAULT_ORIGIN) -> None:
        self.origin = origin
        self.cpu = abi.Cpu()
        self.program = b""
        self.steps = 0
        self.status = "running"
        self.detail = ""
        self.reset()

    # --- lifetime -----------------------------------------------------------

    def close(self) -> None:
        self.cpu.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- loading and resetting ----------------------------------------------

    def load(self, program: bytes, origin: int | None = None) -> None:
        """Replace the loaded program and reset around it."""
        if not program:
            raise EmulatorError("a program of zero bytes has nothing to run")
        if origin is not None:
            self.origin = origin & 0xFFFF
        if self.origin + len(program) > ADDRESSABLE:
            # 64 KB, not a megabyte: the check used to compare against the
            # whole address space *after* masking the origin to sixteen bits,
            # so it could never fire.
            raise EmulatorError(
                f"a {len(program)}-byte program at {self.origin:#06x} runs past "
                f"the {ADDRESSABLE >> 10} KB reachable with CS at zero"
            )
        self.program = bytes(program)
        self.reset()

    def reset(self) -> None:
        """Back to the state the program was loaded in.

        Memory is cleared first, so a second run cannot inherit what the first
        one wrote -- which is the whole point of a reset button, and is not
        what the processor's own RESET does (that leaves DRAM alone).
        """
        self.cpu.clear_memory()
        self.cpu.set_regs(
            cs=0x0000, ip=self.origin, ds=0x0000, es=0x0000, ss=0x0000,
            sp=DEFAULT_STACK, ax=0, bx=0, cx=0, dx=0, si=0, di=0, bp=0, flags=0,
        )
        if self.program:
            self.cpu.write_block(self.origin, self.program)
        self.steps = 0
        self.status = "running"
        self.detail = ""

    # --- execution ----------------------------------------------------------

    def step(self) -> RunResult:
        """One instruction."""
        if self.status != "running":
            return RunResult(0, self.status, self.detail)
        try:
            still_running = self.cpu.step()
        except abi.Unimplemented as exc:
            self.status = "unimplemented"
            self.detail = str(exc)
            return RunResult(0, self.status, self.detail)
        self.steps += 1
        if not still_running:
            self.status = "halted"
        return RunResult(1, self.status, self.detail)

    def run(self, budget: int) -> RunResult:
        """Up to `budget` instructions, stopping early on halt or a gap."""
        if budget < 1:
            raise EmulatorError(f"a run budget of {budget} would do nothing")
        if budget > MAX_RUN_STEPS:
            raise EmulatorError(
                f"a budget of {budget} exceeds {MAX_RUN_STEPS}; ask again "
                f"rather than asking for longer, so the UI stays answerable"
            )
        taken = 0
        for _ in range(budget):
            if self.status != "running":
                break
            result = self.step()
            taken += result.steps
            if result.status != "running":
                break
        return RunResult(taken, self.status, self.detail)

    # --- what the UI reads --------------------------------------------------

    def registers(self) -> dict[str, int]:
        return self.cpu.regs.as_dict()

    def flags(self) -> dict[str, bool]:
        """The nine bits this part defines, by name.

        Named rather than returned as a word because "FLAGS is 0xF086" is not
        something a person reads, and working it out by hand is exactly the
        job a debugger exists to do for them.
        """
        value = self.cpu.regs.flags
        return {name: bool(value >> bit & 1) for name, bit in FLAG_BITS.items()}

    def disassembly(self, count: int = DISASSEMBLY_LINES) -> list[dict[str, object]]:
        regs = self.cpu.regs
        return [
            {
                "cs": line.cs, "ip": line.ip, "address": line.address,
                "length": line.length, "text": line.text, "bytes": line.hex,
                "current": line.ip == regs.ip and line.cs == regs.cs,
            }
            for line in disasm.disassemble_range(self.cpu, regs.cs, regs.ip, count)
        ]

    def memory(self, address: int, length: int) -> dict[str, object]:
        """A window of memory, as bytes plus the address it starts at."""
        if length < 1:
            raise EmulatorError(f"a window of {length} bytes shows nothing")
        if length > 4096:
            raise EmulatorError(f"{length} bytes is more than a view can use")
        address &= 0xFFFFF
        return {
            "address": address,
            "bytes": list(self.cpu.read_block(address, length)),
        }

    def state(self, memory_at: int = 0x0200, memory_length: int = 256,
              disassembly_lines: int = DISASSEMBLY_LINES) -> dict[str, object]:
        """Everything the UI needs to redraw, in one call.

        One call rather than four, because four means four chances for the
        panes to disagree about which instant they are showing.
        """
        return {
            "registers": self.registers(),
            "flags": self.flags(),
            "disassembly": self.disassembly(disassembly_lines),
            "memory": self.memory(memory_at, memory_length),
            "status": self.status,
            "detail": self.detail,
            "steps": self.steps,
            "origin": self.origin,
        }


#: Bit positions of the nine flags the 8086 defines. The same nine
#: `tools/sst8088.py` names, deliberately -- a UI showing a tenth would be
#: showing a bit the part does not have.
FLAG_BITS = {
    "CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7,
    "TF": 8, "IF": 9, "DF": 10, "OF": 11,
}


@dataclasses.dataclass(frozen=True)
class Sample:
    """A demonstration program, its source, and what it claims to produce."""

    name: str
    hex: str
    #: The address the UI should show in its memory pane afterwards.
    watch: int
    #: `(address, bytes)` the program leaves behind. **Asserted by the test
    #: suite**, so a sample whose name stops being true fails the build rather
    #: than quietly demonstrating something else.
    produces: tuple[int, bytes]
    listing: tuple[str, ...]

    @property
    def program(self) -> bytes:
        return bytes.fromhex("".join(self.hex.split()))


#: The samples the UI offers.
#:
#: **In Python, not in the JavaScript.** They were written there first, which
#: made them the one part of the emulator no test could reach -- a broken
#: sample would have shipped as a broken demonstration and nothing would have
#: said so. `/api/samples` serves them and `tests/webui/test_emulator.py` runs
#: every one of them to the end and checks `produces`.
SAMPLES: tuple[Sample, ...] = (
    Sample(
        name="Sum 1 to 10",
        hex="B9 0A 00 31 C0 01 C8 E2 FC A3 00 02 F4",
        watch=0x0200,
        produces=(0x0200, bytes([55, 0])),
        listing=(
            "mov cx, 10", "xor ax, ax",
            "add ax, cx", "loop -4",
            "mov [0200h], ax", "hlt",
        ),
    ),
    Sample(
        name="Five factorial",
        hex="B8 01 00 B9 05 00 F7 E1 E2 FC A3 00 02 F4",
        watch=0x0200,
        produces=(0x0200, bytes([120, 0])),
        listing=(
            "mov ax, 1", "mov cx, 5",
            "mul cx", "loop -4",
            "mov [0200h], ax", "hlt",
        ),
    ),
    Sample(
        name="Fibonacci, twelve terms",
        hex="BF 00 02 B8 00 00 BB 01 00 B9 0C 00 89 05 83 C7 02 01 D8 93 E2 F6 F4",
        watch=0x0200,
        produces=(0x0200, b"\x00\x00\x01\x00\x01\x00\x02\x00\x03\x00\x05\x00"
                          b"\x08\x00\x0d\x00\x15\x00\x22\x00\x37\x00\x59\x00"),
        listing=(
            "mov di, 0200h", "mov ax, 0", "mov bx, 1", "mov cx, 12",
            "mov [di], ax", "add di, 2", "add ax, bx", "xchg ax, bx",
            "loop -10", "hlt",
        ),
    ),
    Sample(
        name="Fill memory with 'A' (REP STOSB)",
        hex="B8 41 00 BF 00 02 B9 20 00 F3 AA F4",
        watch=0x0200,
        produces=(0x0200, b"A" * 32),
        listing=(
            "mov ax, 41h", "mov di, 0200h", "mov cx, 32",
            "rep stosb", "hlt",
        ),
    ),
    Sample(
        name="Copy a string (REP MOVSB)",
        hex="C7 06 00 02 4F 70 C7 06 02 02 65 6E C7 06 04 02 48 61 "
            "C7 06 06 02 72 64 C7 06 08 02 77 61 C7 06 0A 02 72 65 "
            "BE 00 02 BF 00 03 B9 0C 00 F3 A4 F4",
        watch=0x0300,
        produces=(0x0300, b"OpenHardware"),
        listing=(
            "mov word [0200h], 'pO'  ; six stores spell the source",
            "...", "mov si, 0200h", "mov di, 0300h", "mov cx, 12",
            "rep movsb", "hlt",
        ),
    ),
    Sample(
        name="Divide by zero, handled and resumed",
        hex="C7 06 00 00 20 05 C7 06 02 00 00 00 B8 10 00 B3 00 "
            "F6 F3 A3 00 02 F4 90 90 90 90 90 90 90 90 90 "
            "C7 06 02 02 EF BE CF",
        watch=0x0200,
        # 0200 is AX, stored after the handler returned; 0202 is the handler's
        # own mark. Both together prove the fault dispatched AND came back.
        produces=(0x0200, bytes([0x10, 0x00, 0xEF, 0xBE])),
        listing=(
            "mov word [0000h], 0520h  ; vector 0 -> the handler",
            "mov word [0002h], 0000h",
            "mov ax, 16", "mov bl, 0", "div bl", "mov [0200h], ax", "hlt",
            "handler: mov word [0202h], 0BEEFh", "iret",
        ),
    ),
)
