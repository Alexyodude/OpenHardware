#!/usr/bin/env python3
# OpenHardware - the ESP32-C3 as regions and registers over the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an ESP32-C3 to a `core.riscv32` CPU.

The fourth board here and the first RISC-V one. Reading it against
`webui/boards/rp2040.py`, `samd21.py` and `atmega328p.py` is the fastest way to
see which parts of "describe a board" are the architecture and which are the
chip -- and this one lands between them: flat-addressed like the Arm boards,
entering at the image's start like the AVR.

## Where these numbers come from

Espressif's own SoC headers, shipped inside `framework-arduinoespressif32` and
fetched with PlatformIO:

    tools/sdk/esp32c3/include/soc/esp32c3/include/soc/{soc,gpio_reg}.h

Every address below cites the file and line it was read from, the same shape
`samd21.py` cites its CMSIS headers and `atmega328p.py` its `iom328p.h`. There
is no research directory for this part; the headers *are* the source.

## Three ways this is not an Arm board

1. **There is no vector table**, so this file declares no
   `VECTOR_TABLE_OFFSETS` and is not asked for one --
   `core/riscv32/machine.py`'s `REQUIRES` is empty. An RV32 part resets to a
   chip-defined address, and on this one that address is inside mask ROM.

2. **The mask ROM is not modelled and cannot be.** It is 384 KB of Espressif's
   code, not redistributable, and it is what an ESP-IDF application expects to
   have set up the cache, the clock and its own function table before `app_main`
   runs. So **an ESP-IDF application will not run on this board.** A bare-metal
   image linked into the flash execute window will, which is the standard the
   RP2040, SAMD21 and ATmega328P images already meet, and
   `tests/riscv32/test_esp32c3_board.py` is the one that watched it.

3. **The same SRAM appears twice, at two addresses.** 0x3FC80000 is the data
   bus view and 0x4037C000 is the instruction bus view of the same 384 KB, so a
   naive model maps it twice and lets a program write through one alias and read
   nothing through the other. See `install_memory`.

## Why there is no LED

**The XIAO ESP32-C3 has no user LED**, and that is measured rather than
assumed: Seeed's own variant file,
`framework-arduinoespressif32/variants/XIAO_ESP32C3/pins_arduino.h`, is 34
lines and contains the string "LED" zero times, where the Arduino Uno's defines
`LED_BUILTIN 13`. So the fixture watches a GPIO register rather than a pin
anything is wired to, and `GPIO8` below is the pin Espressif's own devkit uses
-- a real output on this part either way.

## What is deliberately absent

Every timer, the UART, the ADC, SPI, I2C, and the whole clock and reset
subsystem. Same growth rule the other three boards keep: a peripheral is added
when a real image faults on it and not before. Here the rule has teeth --
`core/riscv32/cpu.h` faults on any address no region and no register covers, so
a program that touches an undescribed peripheral stops and names the address
rather than reading zero and hanging.
"""

from __future__ import annotations

import typing

#: The flash execute window, from `soc.h:219-220`:
#:
#:     #define SOC_IROM_LOW    0x42000000
#:     #define SOC_IROM_HIGH   0x42800000
#:
#: 8 MB of address space, backed by however much flash the module carries. This
#: is where a bare-metal image is linked and where `-Wl,-Ttext=0x42000000`
#: points, so it is the region an image loads into.
IROM = 0x42000000
IROM_SIZE = 0x42800000 - 0x42000000

#: Erased flash reads 0xFF. On RV32 both fills are loud -- a word of zeros and a
#: word of ones are *both* illegal encodings -- so a program that runs off the
#: end of its image stops either way. That is a mercy the Thumb cores do not
#: get, and it is `core/riscv32/cpu.h`'s observation rather than this file's.
FLASH_ERASED = 0xFF

#: The read-only data window, `soc.h:217-218`. Constants and string literals
#: land here on a real image; a `-nostdlib` blink puts everything in .text, so
#: nothing has needed it yet and it is mapped anyway because an image *may*
#: place a segment there and faulting on a rodata read would name an address a
#: reader would have to look up.
DROM = 0x3C000000
DROM_SIZE = 0x3C800000 - 0x3C000000

#: SRAM, `soc.h:225-228`:
#:
#:     #define SOC_IRAM_LOW    0x4037C000
#:     #define SOC_IRAM_HIGH   0x403E0000
#:     #define SOC_DRAM_LOW    0x3FC80000
#:     #define SOC_DRAM_HIGH   0x3FCE0000
#:
#: **These are two views of one 384 KB array**, not two arrays: the data bus
#: sees it at 0x3FC80000 and the instruction bus at 0x4037C000. See
#: `install_memory` for what this model does about that and what it does not.
DRAM = 0x3FC80000
DRAM_SIZE = 0x3FCE0000 - 0x3FC80000
IRAM = 0x4037C000
IRAM_SIZE = 0x403E0000 - 0x4037C000

#: GPIO, from `soc.h:45` -- `#define DR_REG_GPIO_BASE 0x60004000`.
GPIO = 0x60004000

#: The registers this board models, from `gpio_reg.h`. Offsets rather than
#: absolute addresses, because that is how the header writes them:
#:
#:     #define GPIO_OUT_REG           (DR_REG_GPIO_BASE + 0x4)     :58
#:     #define GPIO_OUT_W1TS_REG      (DR_REG_GPIO_BASE + 0x8)     :66
#:     #define GPIO_OUT_W1TC_REG      (DR_REG_GPIO_BASE + 0xC)     :74
#:     #define GPIO_ENABLE_REG        (DR_REG_GPIO_BASE + 0x20)    :90
#:     #define GPIO_ENABLE_W1TS_REG   (DR_REG_GPIO_BASE + 0x24)    :98
#:     #define GPIO_ENABLE_W1TC_REG   (DR_REG_GPIO_BASE + 0x28)    :106
#:     #define GPIO_IN_REG            (DR_REG_GPIO_BASE + 0x3C)    :122
GPIO_OUT = 0x04
GPIO_OUT_W1TS = 0x08
GPIO_OUT_W1TC = 0x0C
GPIO_ENABLE = 0x20
GPIO_ENABLE_W1TS = 0x24
GPIO_ENABLE_W1TC = 0x28
GPIO_IN = 0x3C

#: The pin the fixture watches. **Not a user LED** -- see the module docstring.
#: GPIO8 is what Espressif's own ESP32-C3-DevKitM-1 wires its RGB LED to, and
#: on a XIAO it is an ordinary exposed output.
LED_PIN = 8


#: This part's ISA, exactly as its datasheet spells it and as
#: `webui/boards/catalogue.py`'s `CHIPS` records it.
#:
#: **Letters and not a bitmask.** A mask is a fact about `core/riscv32/abi.py`;
#: `RV32IMC` is a fact about the silicon, and `set_isa` translates. That keeps
#: the letters-to-bits map in one place -- the core -- and the ISA string in
#: one place, here, with `test_the_board_agrees_with_the_catalogue_about_the_isa`
#: pinning it against the catalogue so the two cannot drift.
#:
#: The C is the load-bearing letter: two thirds of a real image is compressed.
#: The absent A is equally load-bearing in the other direction -- this part
#: must *trap* an atomic, and an ESP32-C6 must execute one.
ISA = "RV32IMC"


class Cpu(typing.Protocol):
    """What this module needs of a core.

    Narrower than `rp2040.py`'s by every mirror and stream, and wider than
    `atmega328p.py`'s by everything: an AVR board sizes two spaces and stops,
    and this one has a sparse map with holes that must fault.
    """

    def set_isa(self, letters: str) -> None: ...
    def add_region(self, base: int, size: int, executable: bool = ...,
                   fill: int = ...) -> None: ...
    def map_register(self, address: int, value: int = ...) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...


def install_memory(cpu: Cpu) -> None:
    """The flash window, the rodata window, and SRAM.

    **SRAM is mapped once, at its data-bus address, and the instruction-bus
    alias is deliberately left out.** 0x3FC80000 and 0x4037C000 are two views
    of the same 384 KB, and `add_region` has no notion of an alias -- mapping
    both would create two independent arrays, so a program that wrote a
    function through the instruction view and called it through the data view
    would run zeros. Two arrays that must agree are two arrays that will not,
    which is the argument `core/avr/cpu.h` makes about its register file.

    So the instruction view faults, loudly, naming 0x4037xxxx -- and a reader
    who meets that fault is told by this docstring what it means. That is the
    honest half of a model that cannot yet express aliasing; the alternative
    silently runs the wrong bytes.

    A bare-metal image does not need the instruction view: it executes from the
    flash window and uses SRAM for its stack and data.
    """
    cpu.add_region(IROM, IROM_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(DROM, DROM_SIZE, executable=False, fill=FLASH_ERASED)
    cpu.add_region(DRAM, DRAM_SIZE, executable=True, fill=0x00)


def install_gpio(cpu: Cpu) -> None:
    """GPIO_OUT and GPIO_ENABLE, each with its W1TS and W1TC aliases.

    **The W1TS and W1TC registers are write-only and read as zero**, which is
    what the part does and is not this model shrugging. `webui/boards/samd21.py`
    documents the opposite case -- Microchip's header marks the same-shaped
    PORT registers `__IO ... (R/W)` -- so which way round it goes is a per-chip
    fact read from the vendor's own header, never a default.

    `GPIO_IN` is left **unmapped on purpose**, the same decision `samd21.py`
    makes about its own `PORT_IN` and for the same reason: `IN` reads the
    electrical level on the pin, so on a pin driven as an output it follows
    `OUT`. A stored register reading zero would answer *wrongly* to firmware
    that drives GPIO8 high and reads it back, and a wrong value a driver acts
    on costs more than a fault. `GPIO_IN` stays exported so a test can name the
    address it expects to fault at.
    """
    cpu.map_register(GPIO + GPIO_OUT, 0)
    cpu.map_alias(GPIO + GPIO_OUT_W1TS, GPIO + GPIO_OUT, "set", readable=False)
    cpu.map_alias(GPIO + GPIO_OUT_W1TC, GPIO + GPIO_OUT, "clear", readable=False)

    cpu.map_register(GPIO + GPIO_ENABLE, 0)
    cpu.map_alias(GPIO + GPIO_ENABLE_W1TS, GPIO + GPIO_ENABLE, "set",
                  readable=False)
    cpu.map_alias(GPIO + GPIO_ENABLE_W1TC, GPIO + GPIO_ENABLE, "clear",
                  readable=False)


def install(cpu: Cpu) -> None:
    """Every region and register this board models, which is not every one.

    **Precondition: the core has no board.** `core/riscv32/machine.py`'s
    `blank` calls `reset`, which forgets the regions, the mapped registers and
    the extension mask together -- and the extension mask matters here, because
    a core still believing it is an ESP32-C6 would execute atomics this part
    must trap.
    """
    # **The ISA first**, because it is the thing a core cannot guess and the
    # one it is silently wrong about. A core still believing it is an ESP32-C6
    # would execute atomics this part must trap, and no lockstep run against
    # rvcpp could ever say so -- rvcpp runs both.
    cpu.set_isa(ISA)
    install_memory(cpu)
    install_gpio(cpu)
