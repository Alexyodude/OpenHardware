#!/usr/bin/env python3
# OpenHardware - hosting a board on an AVR: power-on, and the register file.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""What `webui/api.py` has to know about an AVR rather than about an ATmega328P.

The counterpart to `core/cortexm0/machine.py`, and reading the two side by side
is the fastest way to see which parts of "hosting a board" are the architecture
and which are the plumbing. This module exists because that one could not be
made to serve both: see its docstring for the measurement.

## Two address spaces, and every function here says which it means

`core/avr/cpu.h` opens by refusing to let a caller confuse them, because 0x0100
is a flash word *and* a byte of SRAM and only the instruction asking knows
which. That refusal is the reason `webui/api.py`'s old `Core` protocol could
not simply be implemented here: `write_block(address, data)` has no answer.

So the split runs through this file:

- **`refuses` and `write` mean program memory**, because that is what firmware
  *is*. An image loads into flash and nowhere else.
- **`readable`, `read` and `word` mean data memory**, because that is what a
  person watching a running board wants to see -- the register file, the IO
  window, SRAM. The program side is what a disassembly listing shows, and
  showing flash twice while never showing SRAM would be the worse pair.

Two names for what is one predicate on a flat machine. On this one they are
genuinely different questions and the names are how a caller states which it
asked.

## The unit of an address

`refuses` and `write` take **byte** addresses, because that is what an image
carries -- `avr-objcopy -O binary` emits a flat blob whose first byte is word
zero's low half. `write_program_block` counts words, so the conversion happens
here, and an odd address is refused rather than rounded: which half of a word
a byte belongs to is a question a loader must not answer by guessing.

`view().pc` is in **words**, as the machine counts it and as `abi.py` reports
it. Not converted to bytes: an AVR PC is a word index in every AVR document,
in avr-gdb, and in this core, and quietly presenting a different number under
the same name is how a reader ends up looking for `rjmp .-22` at the wrong
place.

## What this cannot claim

`docs/architectures.md` records AVR's candidate oracles -- simavr, avr-gdb --
as neither of them hardware-captured, and neither is installed here. Nothing in
this file changes that. What it does is let a board reach the standard the
RP2040 and SAMD21 met: a real compiled image, watched.
"""

from __future__ import annotations

import dataclasses
import typing

#: SREG bits, as the datasheet numbers them, in datasheet order. The same
#: mapping `core/avr/abi.FLAGS` holds; repeated here because this module
#: reports them as an ordered view and that ordering is a display decision
#: rather than a fact about the silicon.
FLAG_BITS: tuple[tuple[str, int], ...] = (
    ("C", 0), ("Z", 1), ("N", 2), ("V", 3),
    ("S", 4), ("H", 5), ("T", 6), ("I", 7),
)

#: R0-R31. Every one of them eight bits wide, which is why `Register` carries a
#: width at all: rendered through the Arm path they would print as
#: `0x000000a5`, eight hex digits for a byte.
REGISTER_COUNT = 32
REGISTER_WIDTH = 8

#: SP and PC are sixteen bits on this part. SP addresses the data space, whose
#: top is RAMEND; PC indexes 16 K words of flash.
POINTER_WIDTH = 16

#: What a board description on this core must define, beyond the contract's
#: own `install`. **Empty, and that is the entire point of OH-52.**
#:
#: An Armv6-M board owes `VECTOR_TABLE_OFFSETS` because
#: `core/cortexm0/machine.py` reads an initial stack pointer and a reset
#: handler out of two words. An AVR begins executing at word zero, so there is
#: nothing to look for and nothing to be told. A contract that demanded the
#: offsets of every board would have forced `webui/boards/atmega328p.py` to
#: declare `(0,)` and mean nothing by it -- after which the catalogue would
#: report Arduino Uno runnable while `api.load_firmware` could not enter it.
REQUIRES: tuple[tuple[str, str], ...] = ()


class MachineError(Exception):
    """This machine cannot be entered as asked, with the reason."""


class Cpu(typing.Protocol):
    """The calls this module makes of `core.avr.abi.Cpu`.

    **Every accessor names its address space**, which is `cpu.h`'s rule
    carried up into Python. There is deliberately no `read` or `write` here
    without a space in its name.
    """

    #: `core.avr.abi.Cpu` exposes these five as properties; declared here as
    #: plain attributes because that is what a caller sees and a Protocol
    #: describes the shape rather than the implementation.
    program_words: int
    data_bytes: int
    pc: int
    sreg: int
    sp: int

    def reset(self) -> None: ...
    def write_program_block(self, address: int, data: bytes) -> None: ...
    def read_data(self, address: int) -> int: ...
    def reg(self, index: int) -> int: ...


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

    `reset()` and not three clears, because this core has no regions to clear
    and no register file separate from data memory -- `reset` zeroes the data
    space, fills program memory with the erased word, and puts SP at the top.
    The board's `install` then calls `configure`, which does it again with the
    real sizes.
    """
    cpu.reset()


def refuses(cpu: Cpu, address: int, length: int) -> str | None:
    """Why `length` bytes of an image cannot land at byte `address` of
    **program** memory, or None.

    Two separate reasons, and telling them apart is why this returns a sentence
    instead of a bool. Off the end of flash is one thing; an **odd address** is
    another entirely -- the board maps it perfectly well, and what it cannot do
    is put half a word somewhere. A bool forced the caller to report both as
    "maps nothing there", which sends a reader to check their linker script's
    base against a memory map that was never the problem.

    Odd is refused rather than rounded for the reason
    `avr_write_program_block` refuses an odd *length* one level down: which
    half of a word a byte belongs to is a question a loader must not answer by
    guessing.
    """
    if address < 0 or length < 0:
        return f"0x{address:04x} and {length} bytes is not a span"
    if address % 2:
        return (
            f"0x{address:04x} is an odd program address, so those bytes begin "
            f"halfway through a word -- an AVR's flash is addressed in whole "
            f"16-bit words and which half this is cannot be guessed"
        )
    if address + length > cpu.program_words * 2:
        return (
            f"0x{address:04x}..0x{address + length:04x} runs past the "
            f"{cpu.program_words * 2} bytes of program memory this board has"
        )
    return None


def write(cpu: Cpu, address: int, data: bytes) -> None:
    """Put one segment of an image into program memory.

    **The image counts bytes and this machine counts words**, so the conversion
    is here and it is the only place it happens. `webui/api.py` calls `refuses`
    first, so the check below never fires through that path -- it is the
    precondition stated where it is relied on, for the direct callers a module
    function has. `tests/avr/test_uno_board.py` calls it directly to keep it
    honest, because an unreachable guard nobody exercises is one that silently
    stops working.
    """
    if address % 2:
        raise MachineError(
            f"0x{address:04x} is an odd program address, so the {len(data)} "
            f"bytes there begin halfway through a word"
        )
    cpu.write_program_block(address // 2, data)


def enter(
    cpu: Cpu, image: Image, requested: int | None, offsets: tuple[int, ...]
) -> Entry:
    """Leave the machine at reset, which on an AVR is word zero.

    **No vector table is read, and `requested` and `offsets` are ignored.**
    That is not a gap: an AVR's reset vector *is* address zero, holding an
    instruction rather than an address, so there is nothing to look up and
    nothing a caller could usefully override. `webui/api.py` passes both
    because it does not know which machine it is talking to, and suppresses its
    own `vector_table=` advice when a board declares no offsets.

    The reset *state* is already established: the board's `install` calls
    `configure`, which zeroes the data space -- registers and SREG with it,
    since on this machine those are data memory -- and puts SP at RAMEND. The
    image was written into program memory afterwards and is untouched by any of
    that. So all that is left is to say where execution starts.

    `window` is 0 in the **data** space, which is the register file: r0 at 0x00
    through r31 at 0x1F, then the IO window. That is what a person watching an
    AVR wants a hexdump open on, and the program side is what the disassembly
    pane is for.
    """
    lowest = min(segment.address for segment in image.segments)
    notes: tuple[str, ...] = ()
    if lowest != 0:
        # Not refused. A linker script can start an image above zero, and the
        # gap is erased flash -- but the machine still enters at zero, so a
        # reader watching it execute 0xFFFF needs to be told why.
        notes = (
            (
                f"this image starts at 0x{lowest:04x} of program memory, and "
                f"an AVR enters at 0x0000 regardless; the words before it are "
                f"erased flash"
            ),
        )
    cpu.pc = 0
    return Entry(entry=0, window=0, detail={}, notes=notes)


# --- looking at it --------------------------------------------------------


def view(cpu: Cpu) -> View:
    """Registers and flags, named.

    Thirty-four entries: R0-R31, then SP and PC. SP and PC are listed with the
    registers even though they are not part of the register file, because a
    person reading the pane wants them and there is nowhere else to put them --
    the same reason an Arm view calls r13 `sp`.

    SREG is deliberately **not** among them. It is reported as `flags`, which
    is the form it is read in; showing both would put one byte on the screen
    twice and invite a reader to check they agree.
    """
    registers = [
        Register(f"r{index}", cpu.reg(index), REGISTER_WIDTH)
        for index in range(REGISTER_COUNT)
    ]
    registers.append(Register("sp", cpu.sp, POINTER_WIDTH))
    registers.append(Register("pc", cpu.pc, POINTER_WIDTH))
    sreg = cpu.sreg
    return View(
        registers=tuple(registers),
        flags=tuple((name, bool((sreg >> bit) & 1)) for name, bit in FLAG_BITS),
        pc=cpu.pc,
    )


def readable(cpu: Cpu, address: int, length: int) -> bool:
    """Can a hexdump read `length` bytes from **data** memory at `address`?"""
    if address < 0 or length < 0:
        return False
    return address + length <= cpu.data_bytes


def is_register(cpu: Cpu, address: int) -> bool:
    """Is `address` a memory-mapped register rather than bulk memory?

    **Always false, and that is a claim rather than a stub.** This core models
    no peripheral registers at all: DDRB and PORTB are storage in the data
    space like every other byte, which is why `tests/avr/test_blink.py` watches
    a blink by reading data address 0x25. There is nothing here that `read`
    cannot reach, so the `words=` hint the Arm path gives would send a caller
    somewhere that is not better.

    It will stop being always-false the day this core grows a timer or a UART,
    and that day it becomes the same question `core/cortexm0` answers.
    """
    return False


def read(cpu: Cpu, address: int, length: int) -> bytes:
    """A window of **data** memory.

    Byte at a time because that is the only accessor this machine has -- an
    8-bit core has no block read, and inventing one in C to serve a hexdump
    would be optimising the pane that refreshes twice a second.
    """
    return bytes(cpu.read_data(address + offset) for offset in range(length))


def word(cpu: Cpu, address: int) -> int:
    """One watched location: a byte of **data** memory.

    A byte and not four. The Arm path returns a 32-bit word because that is
    what one of its peripheral registers is; here the unit of a watchable thing
    is a byte, and packing four of them together would report a number no AVR
    instruction can produce.
    """
    return cpu.read_data(address)
