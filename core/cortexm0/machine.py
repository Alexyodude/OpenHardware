#!/usr/bin/env python3
# OpenHardware - hosting a board on an Armv6-M core: power-on, and the register file.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""What `webui/api.py` has to know about *this kind of machine* rather than
about a particular chip.

## Why this module exists at all

`webui/api.py` used to hold all of it, and that was correct while every board
here ran on a Cortex-M0+. Its `Core` protocol reads like a description of "a
core", and it is not: it is the shape two flat-address 32-bit machines happen
to share. Measured against `core/avr/abi.py`, which is the first non-Arm core a
board can use, **ten of its twelve methods are absent** -- not unwritten, but
meaningless. An AVR has two overlapping address spaces, so `write_block(address,
data)` cannot say which one it means; it is 8-bit, so `read_word` invents a
width; and `set_regs([0] * 13 + [sp, 0, entry], apsr=0)` is the Armv6-M
register file written out longhand.

So the divergence is real, and the house rules say split rather than
parameterise. `webui/api.py` resolves `core.<core>.machine` the way
`listing_view` already resolves `core.<core>.disasm` -- an existing mechanism
in that file, applied to the load path.

## The two questions, and why they are one file

**How does this machine power on**, and **what are its registers called**.
They belong together because they are the same fact approached from either
side: `enter` writes the register file, `view` reads it. Splitting them would
put the definition of "r13 is the stack pointer" in two places.

## What a board still owes

`REQUIRES` names it. An Armv6-M board must declare `VECTOR_TABLE_OFFSETS`,
because `enter` reads an initial stack pointer and a reset handler out of two
words and has to be told where to look. `webui/boards/contract.py` asks the
core rather than listing it, so a board on a machine that begins at address
zero is not asked for a table it does not have.
"""

from __future__ import annotations

import dataclasses
import struct
import typing

#: Register names, in the order `Regs.as_list()` delivers them. r13, r14 and
#: r15 are named for their architectural roles rather than their numbers,
#: because that is how every Arm document and every debugger names them.
REGISTER_NAMES: tuple[str, ...] = (
    "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
    "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc",
)

#: Index of the program counter in that list.
PC = 15

#: Every register on this machine is a 32-bit word.
REGISTER_WIDTH = 32

#: The flags Armv6-M models and their APSR bit positions. The core drops the
#: rest on write rather than storing them, so reporting more would report
#: something the model does not have.
FLAG_BITS: tuple[tuple[str, int], ...] = (("N", 31), ("Z", 30), ("C", 29), ("V", 28))

#: What a board description on this core must define, beyond the contract's
#: own `install`. Pairs rather than `contract.Requirement` objects, so that
#: nothing under `core/` imports from `webui/`.
REQUIRES: tuple[tuple[str, str], ...] = (
    (
        "VECTOR_TABLE_OFFSETS",
        (
            "core/cortexm0/machine.py enter(): where the reset vector sits "
            "relative to the image base. An RP2040 image is linked past 256 "
            "bytes of boot2 and a SAMD21 image is not, so guessing one for "
            "the other enters at a word that is not a stack pointer"
        ),
    ),
)


class MachineError(Exception):
    """This machine cannot be entered as asked, with the reason.

    Raised rather than returned, because the caller has nothing to do with a
    half-loaded board. `webui/api.py` catches it and adds the board's name and
    how to override the search, which are facts it has and this does not.
    """


class Cpu(typing.Protocol):
    """The calls this module makes of `core.cortexm0.abi.Cpu`.

    Written out rather than imported for the reason `webui/boards/rp2040.py`
    writes out its own: a reader can see the whole dependency without a built
    library, and a second core is told exactly what it must provide.
    """

    def clear_memory(self) -> None: ...
    def clear_registers(self) -> None: ...
    def clear_regions(self) -> None: ...
    def write_block(self, address: int, data: bytes) -> None: ...
    def read_word(self, address: int) -> int: ...
    def read_block(self, address: int, length: int) -> bytes: ...
    def in_range(self, address: int, size: int = ...) -> bool: ...
    def is_mapped(self, address: int) -> bool: ...
    def get_regs(self) -> typing.Any: ...
    def set_regs(self, regs: list[int], apsr: int) -> None: ...


class Image(typing.Protocol):
    """The part of `webui.firmware.Image` this reads.

    A protocol rather than an import, because `core/` does not depend on
    `webui/`. The one consequence is that the two words of the vector table are
    unpacked here as well as in `firmware.read_vector_table`, four lines that
    now exist twice. That is the cheaper of the two prices: the alternative is
    a core module that cannot be used without the web layer.
    """

    segments: tuple[typing.Any, ...]

    def read(self, address: int, count: int) -> bytes | None: ...


@dataclasses.dataclass(frozen=True)
class Entry:
    """Where a loaded image begins, and what a reader should look at first."""

    #: The program counter after power-on, in the unit this machine counts.
    entry: int
    #: Where a hexdump should open. The vector table here, because that is the
    #: one address this layer knows is on the board and worth seeing.
    window: int
    #: What this machine has that the others do not, passed straight to the
    #: wire. Empty is the normal answer; an Arm board fills in the two words it
    #: entered through, which have no counterpart on a machine that starts at
    #: address zero. A mapping rather than two optional fields, so that a board
    #: with no stack-pointer word **omits** it rather than reporting null --
    #: which would claim there is one and that it is unknown.
    detail: dict[str, int]
    notes: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Register:
    """One register, named as this machine names it."""

    name: str
    value: int
    #: Bits. On the wire so a page can decide how wide to render the value,
    #: rather than assuming eight hex digits and showing an AVR's r0 as
    #: `0x000000a5`.
    width: int


@dataclasses.dataclass(frozen=True)
class View:
    """Everything a page renders of this machine's state."""

    registers: tuple[Register, ...]
    flags: tuple[tuple[str, bool], ...]
    #: The program counter, for the disassembly listing. Separate from the
    #: register tuple so a caller stops meaning "index 15".
    pc: int


# --- power-on -------------------------------------------------------------


def blank(cpu: Cpu) -> None:
    """A machine with nothing on it, before a board describes itself."""
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()


def refuses(cpu: Cpu, address: int, length: int) -> str | None:
    """Why `length` bytes of an image cannot land at `address`, or None.

    A reason rather than a bool, the same shape `_vector_table_at` uses below
    and for the same reason: the caller composing the refusal knows the board's
    name and the image's format, and this knows what is wrong. A bool would
    make the caller guess, and on the AVR it guessed wrong -- an odd program
    address was reported as "maps nothing there" when the board maps it
    perfectly well and simply cannot split a word.

    Distinct from `readable` even though both consult `in_range` here, and the
    distinction is the point: on a Harvard machine an image loads into program
    memory while a hexdump reads data memory, and one predicate serving both
    would have to guess which was asked.
    """
    if cpu.in_range(address, length):
        return None
    return f"it maps nothing at 0x{address:08x}..0x{address + length:08x}"


def write(cpu: Cpu, address: int, data: bytes) -> None:
    """Put one segment of an image where it loads."""
    cpu.write_block(address, data)


def enter(
    cpu: Cpu, image: Image, requested: int | None, offsets: tuple[int, ...]
) -> Entry:
    """Leave the machine at reset, and say where that is.

    The vector table is **checked rather than assumed**, which is the whole
    difference between this and a guess: every candidate is validated against
    the board's own map before any is accepted. Assuming the first convention
    is how an earlier version answered 0x4b32b500, which is two instructions of
    boot2, and called it a stack pointer.

    A bare-metal image linked past boot2 and a pico-sdk image that includes it
    are both ordinary, so the RP2040 genuinely has two conventions rather than
    one convention and one mistake -- hence a tuple of offsets and not a
    number.
    """
    lowest = min(segment.address for segment in image.segments)
    if requested is not None:
        candidates: tuple[int, ...] = (requested,)
    else:
        candidates = tuple(lowest + offset for offset in offsets)

    reasons = []
    for address in candidates:
        found = _vector_table_at(cpu, image, address)
        if isinstance(found, str):
            reasons.append(found)
            continue
        table, stack_pointer, reset = found
        # r0..r12 zero, then SP, LR, PC. The core has no reset sequence of its
        # own: a board description says what memory exists and this says where
        # execution begins, which together are the whole of a power-on.
        cpu.set_regs([0] * 13 + [stack_pointer, 0, reset], apsr=0)
        return Entry(
            entry=reset,
            window=table,
            detail={"vector_table": table, "stack_pointer": stack_pointer},
        )
    raise MachineError(
        "no vector table this board could enter. Tried " + "; ".join(reasons)
    )


def _vector_table_at(
    cpu: Cpu, image: Image, address: int
) -> tuple[int, int, int] | str:
    """A checked vector table at `address`, or the reason it is not one.

    Armv6-M puts the initial stack pointer in the first word and the reset
    handler in the second with bit 0 set for Thumb. Both are checked against
    **the board's own map**, which is the authority: `in_range` asks the
    regions `install` just built, so a chip with flash at zero and one with
    flash at 0x10000000 are told apart without either address appearing here.

    Returning a reason rather than raising, because the caller tries more than
    one candidate and the interesting message is all of them at once.
    """
    words = image.read(address, 8)
    if words is None:
        return f"0x{address:08x}: the image does not cover both words"
    sp, reset = struct.unpack("<II", words)
    if not sp or not cpu.in_range(sp - 4, 4):
        return (
            f"0x{address:08x}: first word 0x{sp:08x} is not a stack pointer "
            f"this board could have, because nothing is mapped below it"
        )
    if not reset & 1:
        return (
            f"0x{address:08x}: second word 0x{reset:08x} has bit 0 clear, so "
            f"it is not a Thumb reset address"
        )
    if not cpu.in_range(reset & ~1, 2):
        return (
            f"0x{address:08x}: reset address 0x{reset & ~1:08x} is in no "
            f"region this board maps"
        )
    return address, sp, reset & ~1


# --- looking at it --------------------------------------------------------


def view(cpu: Cpu) -> View:
    """Registers and flags, named."""
    regs = cpu.get_regs()
    values = regs.as_list()
    return View(
        registers=tuple(
            Register(name, values[index], REGISTER_WIDTH)
            for index, name in enumerate(REGISTER_NAMES)
        ),
        flags=tuple(
            (name, bool((regs.apsr >> bit) & 1)) for name, bit in FLAG_BITS
        ),
        pc=values[PC],
    )


def readable(cpu: Cpu, address: int, length: int) -> bool:
    """Can a hexdump read `length` bytes from `address`?"""
    return cpu.in_range(address, length)


def is_register(cpu: Cpu, address: int) -> bool:
    """Is `address` a memory-mapped register rather than bulk memory?

    Only ever asked to improve a refusal: a caller that asked for a window over
    SIO's GPIO_OUT wants to be told to use `words=`, not that the board maps
    nothing there.
    """
    return cpu.is_mapped(address)


def read(cpu: Cpu, address: int, length: int) -> bytes:
    """A window of bulk memory."""
    return cpu.read_block(address, length)


def word(cpu: Cpu, address: int) -> int:
    """One watched location -- a peripheral register, or a word of memory."""
    return cpu.read_word(address)
