#!/usr/bin/env python3
# OpenHardware - hosting a board on an RV32 core: power-on, and the register file.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""What `webui/api.py` has to know about an RV32 machine rather than about an
ESP32-C3.

The third of these, after `core/cortexm0/machine.py` and `core/avr/machine.py`,
and the one that shows the interface was not shaped around either of them: this
machine is flat-addressed like the Arm one and enters like the AVR one, and it
needed no new function to say so.

## Entering: no vector table, and no address zero either

An Armv6-M board reads an initial stack pointer and a reset handler out of two
words. An AVR begins at word zero. **An RV32 part does neither**: reset jumps
to a chip-defined address, and on an ESP32-C3 that address is inside mask ROM
which then loads the application.

That ROM is not modelled and cannot be -- it is Espressif's, it is not
redistributable, and `webui/boards/` has nowhere to put 384 KB of it. So what
this enters is **the lowest address the image loads at**, which is exactly
right for the bare-metal images this repository can build and compile, and
which is what `-Wl,-Ttext=0x42000000` means.

Stated plainly because it is a real limitation and not a detail: an ESP-IDF
application will not run here. It expects the ROM to have set up the cache, the
clock and its own function table, and `docs/architectures.md` records that
PICSimLab's own ESP route runs the vendor's QEMU rather than modelling any of
it. What runs here is a bare-metal image, which is the standard the RP2040, the
SAMD21 and the ATmega328P images already meet.

## What a board owes: nothing beyond `install`

`REQUIRES` is empty, like the AVR's. There is no offsets tuple because there is
no table to look for. A board that wanted to enter somewhere other than its
image's start passes `vector_table=` to `webui.api.load_firmware`, which
arrives here as `requested` -- the keyword is named for the Armv6-M case that
first needed it and is simply "where to enter" on every other machine.

## The stack pointer is the image's problem, not this module's

An Armv6-M part loads SP from the vector table before its first instruction. An
RV32 part does not: `sp` is whatever reset left it, and **every** RISC-V image
begins by setting it -- that is what `crt0` is for.

So this leaves it at zero, and `tests/riscv32/c3blink/blink.c` sets its own in
`_start`, which is the one thing the startup file a `-nostartfiles` build omits
would have done. That is not a workaround: it is what the real image does, and
an image that did not would fault on its first push here exactly as it would on
silicon.

Inventing a stack pointer here would be inventing a fact about a chip in a
module that describes an instruction set -- and inventing one in the *board*
would hide an image that never set up its stack.
"""

from __future__ import annotations

import dataclasses
import typing

#: The RV32 register file, in the order `Regs.as_list()` delivers it. The
#: ABI names rather than x0..x31, because that is how every RISC-V document,
#: every disassembler and objdump itself spell them -- and `sp` reads as a
#: stack pointer where `x2` reads as a number.
REGISTER_NAMES: tuple[str, ...] = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)

#: Every register on this machine is a 32-bit word.
REGISTER_WIDTH = 32

#: **No flags.** RV32 has no condition-code register: a comparison writes its
#: answer into a register and a branch compares two registers. There is nothing
#: to report, and reporting an empty list is the true answer rather than a
#: missing feature -- the same distinction `uart_view` draws with `present`.
FLAG_BITS: tuple[tuple[str, int], ...] = ()

#: What a board on this core must define beyond `install`. Nothing: see the
#: module docstring on entering.
REQUIRES: tuple[tuple[str, str], ...] = ()


class MachineError(Exception):
    """This machine cannot be entered as asked, with the reason."""


class Cpu(typing.Protocol):
    """The calls this module makes of `core.riscv32.abi.Cpu`."""

    pc: int

    def clear_memory(self) -> None: ...
    def clear_regions(self) -> None: ...
    def write_block(self, address: int, data: bytes) -> None: ...
    def read_word(self, address: int) -> int: ...
    def peek_word(self, address: int) -> int: ...
    def read_block(self, address: int, length: int) -> bytes: ...
    def in_range(self, address: int, bytes_: int = ...) -> bool: ...
    def is_mapped(self, address: int) -> bool: ...
    def get_regs(self) -> typing.Any: ...
    def set_regs(self, regs: list[int], pc: int) -> None: ...
    def reset(self) -> None: ...


class Image(typing.Protocol):
    """The part of `webui.firmware.Image` this reads."""

    segments: tuple[typing.Any, ...]

    def read(self, address: int, count: int) -> bytes | None: ...


@dataclasses.dataclass(frozen=True)
class Entry:
    """Where a loaded image begins, and what a reader should look at first."""

    entry: int
    window: int
    detail: dict[str, int]
    notes: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Register:
    """One register, named as this machine names it."""

    name: str
    value: int
    width: int


@dataclasses.dataclass(frozen=True)
class View:
    """Everything a page renders of this machine's state."""

    registers: tuple[Register, ...]
    flags: tuple[tuple[str, bool], ...]
    pc: int


# --- power-on -------------------------------------------------------------


def blank(cpu: Cpu) -> None:
    """A machine with nothing on it, before a board describes itself.

    `reset()` rather than three separate clears, because this core's reset
    already forgets the regions, the mapped registers and the extension mask
    together -- and the extension mask is the one the other two machines do not
    have. A board that installed onto a core still believing it was an ESP32-C6
    would execute atomics an ESP32-C3 must trap.
    """
    cpu.reset()


def refuses(cpu: Cpu, address: int, length: int) -> str | None:
    """Why `length` bytes of an image cannot land at `address`, or None."""
    if cpu.in_range(address, length):
        return None
    if cpu.is_mapped(address):
        return (
            f"0x{address:08x} is a memory-mapped register, not memory an image "
            f"can be written into"
        )
    return f"it maps nothing at 0x{address:08x}..0x{address + length:08x}"


def write(cpu: Cpu, address: int, data: bytes) -> None:
    """Put one segment of an image where it loads."""
    cpu.write_block(address, data)


def enter(
    cpu: Cpu, image: Image, requested: int | None, offsets: tuple[int, ...]
) -> Entry:
    """Leave the machine at reset, which here is the start of the image.

    `offsets` is ignored and always empty: there is no vector table on this
    machine, so there is nothing to search and `REQUIRES` asks a board for no
    tuple. `requested` is honoured, because "enter somewhere else" is a real
    thing to want and the caller has to be able to say it.

    **Every register comes up zero, `sp` included.** That is what an RV32 part
    does -- there is no vector table to load one from -- so the image sets its
    own, as every RISC-V image does. See the module docstring.
    """
    lowest = min(segment.address for segment in image.segments)
    at = lowest if requested is None else requested

    if not cpu.in_range(at, 2):
        raise MachineError(
            f"0x{at:08x} is in no region this board maps, so there is nothing "
            f"to execute there"
        )

    notes: tuple[str, ...] = ()
    if requested is not None and requested != lowest:
        notes = (
            (
                f"entered at 0x{requested:08x} rather than the image's start "
                f"0x{lowest:08x}, because one was asked for"
            ),
        )

    cpu.set_regs([0] * 32, pc=at)
    return Entry(entry=at, window=lowest, detail={}, notes=notes)


# --- looking at it --------------------------------------------------------


def view(cpu: Cpu) -> View:
    """Registers and flags, named. There are no flags; see `FLAG_BITS`."""
    values = cpu.get_regs().as_list()
    registers = [
        Register(name, values[index], REGISTER_WIDTH)
        for index, name in enumerate(REGISTER_NAMES)
    ]
    # **`pc` is appended rather than being one of the thirty-two.** On Armv6-M
    # the program counter *is* r15 and the view has sixteen entries; here it is
    # architecturally separate and `x0` is the hardwired zero instead. A page
    # still needs it, and `webui/api.py` looks it up by name.
    registers.append(Register("pc", cpu.pc, REGISTER_WIDTH))
    return View(registers=tuple(registers), flags=(), pc=cpu.pc)


def readable(cpu: Cpu, address: int, length: int) -> bool:
    """Can a hexdump read `length` bytes from `address`?"""
    return cpu.in_range(address, length)


def is_register(cpu: Cpu, address: int) -> bool:
    """Is `address` a memory-mapped register rather than bulk memory?"""
    return cpu.is_mapped(address)


def read(cpu: Cpu, address: int, length: int) -> bytes:
    """A window of bulk memory."""
    return cpu.read_block(address, length)


def word(cpu: Cpu, address: int) -> int:
    """One watched location -- a peripheral register, or a word of memory.

    **Peeked, not read**: a FIFO's read takes the byte the firmware was to
    read, and a viewer polling one would eat it (OH-161 step 5)."""
    return cpu.peek_word(address)
