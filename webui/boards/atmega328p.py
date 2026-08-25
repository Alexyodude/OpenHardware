#!/usr/bin/env python3
# OpenHardware - the ATmega328P as two sized address spaces over the AVR core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an ATmega328P to a `core.avr` CPU.

The third board here and the first that is not Arm, which makes it the one
worth reading against the other two. `webui/boards/rp2040.py` and `samd21.py`
are 400 and 230 lines of memory-mapped registers; this is a hundred, and
almost none of it is registers. That difference is the architecture and not an
omission -- see "Why there is no peripheral section" below.

## Where these numbers come from

The toolchain's own `iom328p.h`, which is Microchip's, shipped inside
`toolchain-atmelavr@3.70300.220127` and fetched with PlatformIO:

    ~/.platformio/packages/toolchain-atmelavr/avr/include/avr/iom328p.h

Every constant below cites the file and line it was read from, the same shape
`samd21.py` cites its CMSIS headers. There is no research directory for this
part; the header *is* the source, and it is generated from the same device
description the datasheet is.

The board is the **Arduino Uno**, per `webui/boards/catalogue.py`'s `IRREGULAR`
table -- the one board in the catalogue that is not a Seeed XIAO.

## Two spaces, sized rather than mapped

`install(cpu)` calls `configure(program_words, data_bytes)` and stops. There is
no `add_region`, because there are no regions: an AVR has exactly two address
spaces, both starting at zero, and the only thing a board chooses is how big
each is. A Cortex-M0+ board must place flash (0x00000000 on a SAMD21,
0x10000000 on an RP2040) because that part is genuinely a decision; here it
is not.

**The data space is one span and not three.** 0x0000-0x001F is the register
file, 0x0020-0x00FF is the IO window, and SRAM starts at `RAMSTART` 0x0100 --
but they are consecutive addresses in one space, and `lds r0, 0x0025` reads
PORTB exactly as `in r0, 0x05` does. Modelling them separately would invent a
boundary the instruction set does not have.

## Why there is no peripheral section

`rp2040.py` and `samd21.py` both spend most of their length on `map_register`
and `map_alias`, and this file has neither -- because `core/avr` has no MMIO
mechanism at all. On this part it does not yet need one: `DDRB` and `PORTB`
are bytes of the data space, so a write to 0x24 stores and a read returns what
was stored, which is what the silicon does for those two registers.

**Where that stops being true, and it does:** `PINB` reads the *electrical
level on the pins*, so on a pin driven as an output it follows `PORTB`, and on
a pin driven as an input it follows whatever is wired to it. This model returns
the stored zero. That is a wrong answer rather than a fault, which is the
failure class this repository ranks worst -- and unlike `samd21.py`, which
could leave its `PORT_IN` unmapped so a read faults instead of lying, there is
nothing to unmap here: every byte of the data space exists.

So it is written down instead. `PINB` is exported below so a test can name it,
`test_reading_the_input_register_is_not_yet_modelled` pins the limitation
rather than the behaviour, and the fix -- a mirror of `PORTB` masked by `DDRB`
-- needs a mapping mechanism this core does not have. Nothing has read `PINB`
yet; the day something does, that is the first claim to re-check.

## What is deliberately absent

Every timer, the USART, the ADC, the EEPROM. Same growth rule the other two
boards keep: a peripheral is added when a real image faults on it and not
before. Here the rule bites differently, because a missing peripheral on this
core does not fault -- it reads zero. `tests/avr/test_uno_board.py` is what
makes that visible: it watches an image that touches only PORTB, so nothing in
it depends on a register this file does not describe.
"""

from __future__ import annotations

import typing

#: Flash, from `iom328p.h:889`:
#:
#:     #define FLASHEND     0x7FFF
#:
#: The last **byte** address, so 32 KB, so 16,384 sixteen-bit words. The core
#: is configured in words because that is what the program counter counts.
FLASH_BYTES = 0x8000
PROGRAM_WORDS = FLASH_BYTES // 2

#: The data space, from `iom328p.h:883-884`:
#:
#:     #define RAMSTART     (0x100)
#:     #define RAMEND       0x8FF     /* Last On-Chip SRAM Location */
#:
#: `RAMEND` is the last address in the whole data space, not the last address
#: of SRAM alone -- the register file and the IO window are below `RAMSTART`
#: and are part of the same space. So the size is `RAMEND + 1`, which is 2,304
#: bytes: 32 registers, 64 IO registers, 160 extended IO registers, and 2 KB of
#: SRAM.
RAMSTART = 0x0100
RAMEND = 0x08FF
DATA_BYTES = RAMEND + 1

#: Where SP comes up. Not configured here -- `core/avr/cpu.cc`'s `reset()`
#: derives it from the size above -- but named because a bare-metal image built
#: with `-nostartfiles` never writes SP itself, so this is the value the first
#: `push` uses and a test asserts it.
STACK_TOP = RAMEND

#: PORTB and its two companions, as **data** addresses. From `iom328p.h:54,64,74`:
#:
#:     #define PINB  _SFR_IO8(0x03)
#:     #define DDRB  _SFR_IO8(0x04)
#:     #define PORTB _SFR_IO8(0x05)
#:
#: `_SFR_IO8(x)` is `x + 0x20` in the data space, so an `in`/`out` instruction
#: uses the small number and everything else uses the one below. **That +0x20
#: is the likeliest off-by-something in an AVR model**, which is why both forms
#: are written out here rather than one being derived at the call site.
PINB_IO, PINB = 0x03, 0x23
DDRB_IO, DDRB = 0x04, 0x24
PORTB_IO, PORTB = 0x05, 0x25

#: The Uno's user LED. From Arduino's own variant file,
#: `framework-arduino-avr/variants/standard/pins_arduino.h:54`, which defines
#: `LED_BUILTIN` as 13, and its pinout comment at line 99: `PB5 (D 13)`.
#:
#: A fact about the board rather than the chip, kept here because the blink
#: test needs a pin and an arbitrary one would prove less.
LED_PIN = 5


class Cpu(typing.Protocol):
    """What this module needs of a core, which is one call.

    Narrower than either Arm board's protocol by every mapping method, because
    this machine has nothing to map. Stated as a protocol anyway, and stated
    this small on purpose: it is the clearest single piece of evidence that
    "describe a board" means something different on a Harvard part.
    """

    def configure(self, program_words: int, data_bytes: int) -> None: ...


def install(cpu: Cpu) -> None:
    """Size both address spaces. That is the whole of this board's model.

    **Postcondition, and `core/avr/machine.py` depends on it:** `configure`
    resets the machine -- data zeroed, program filled with the erased word
    0xFFFF, SP at `STACK_TOP`. `webui/api.py` writes the image *after* calling
    this and enters afterwards, so the order is install, load, enter, and
    reversing the first two would erase the image.
    """
    cpu.configure(program_words=PROGRAM_WORDS, data_bytes=DATA_BYTES)
