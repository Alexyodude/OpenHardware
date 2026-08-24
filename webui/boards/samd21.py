#!/usr/bin/env python3
# OpenHardware - the SAMD21 as a set of registers over the Cortex-M0+ core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe a SAMD21 to a `core.cortexm0` CPU.

The second board over the same core, and the reason the core has no addresses
of its own. `webui/boards/rp2040.py` is the first; reading the two side by side
is the fastest way to see which parts of a "Cortex-M0+ board" are the
architecture and which are the chip.

## Where these numbers come from

Microchip's own generated CMSIS headers, shipped inside
`framework-arduino-samd@1.8.14` and fetched with PlatformIO:

    bootloaders/mzero/Bootloader_D21/src/ASF/sam0/utils/cmsis/samd21/include/

Every address below cites the file and line it was read from, in the same shape
`rp2040.py` cites `docs/research/peripheral-layer/rp2040_v2/`. There is no
research directory for this chip; the headers *are* the source, and they are
generated from the same device description the datasheet is, which makes them a
better citation than a page number anyway.

The part is the **ATSAMD21G18A** -- the one on both XIAO SAMD21 boards, per
`third_party/bsp/seeed-samd/variants/XIAO_m0/`. Flash and SRAM sizes are that
part's; the G18A is the 256K/32K member and its siblings differ.

## Three ways this is not an RP2040, all of them load-bearing

1. **Flash is at zero.** Not `0x10000000`. The vector table a Cortex-M0+ reads
   at reset therefore lands in flash directly, with no XIP window and no 256-
   byte boot2 blob in front of it. This is the difference that moved the memory
   map out of the core, and until this file existed it was a difference only a
   test asserted.

2. **There is no boot ROM at zero, so there is no stub.** The RP2040 needs
   `install_bootrom_stub` because 16 KB of unshippable mask ROM sits where a
   SAMD21 puts its own flash. Here the absence is the accurate model.

3. **There are no bus-level atomic alias windows.** No `+0x1000`/`+0x2000`/
   `+0x3000`; that is an RP2040 bus feature, not an Arm one. What the SAMD21
   has instead is dedicated SET/CLR/TGL *registers* inside PORT, which is the
   same mechanism SIO uses -- and, as below, not quite the same semantics.

## What is deliberately absent

Everything a blink does not touch, for the reason `rp2040.py` gives: a model
acquires registers nobody has checked exactly by adding them speculatively.
PM and GCLK are the ones a reader will expect and they are not here, because
**PORT is already clocked at power-on** -- `PM_APBBMASK` resets to `0x0000007F`
and `PM_APBBMASK_PORT` is bit 3 (`component/pm.h:322,330-331`), so the bit is
already set before the first instruction executes.
`tests/cortexm0/test_samd21_blink.py` is what turns that from a claim into a
measurement: the image there never reads or writes `0x40000400`, and if it did,
the fault would name the address.
"""

from __future__ import annotations

import typing

#: The memory map, from `samd21g18a.h:531-538`:
#:
#:     #define FLASH_SIZE            0x40000 /* 256 kB */
#:     #define FLASH_ADDR            (0x00000000U) /**< FLASH base address */
#:     #define HMCRAMC0_SIZE         0x8000 /* 32 kB */
#:     #define HMCRAMC0_ADDR         (0x20000000U) /**< HMCRAMC0 base address */
#:
#: **`FLASH_ADDR` is zero**, which is the whole point of this file existing.
FLASH = 0x00000000
FLASH_SIZE = 256 * 1024

#: Erased flash reads 0xFF on a real part, and `0xFFFF` is not a valid Thumb
#: encoding, so a program that runs off the end of its image stops instead of
#: executing zeros as `MOVS r0, r0`. Same value and same two reasons as the
#: RP2040; this is a property of NOR flash and of the ISA, not of either chip.
FLASH_ERASED = 0xFF

#: Microchip calls SRAM `HMCRAMC0`. Same base as the RP2040 by coincidence of
#: the Arm memory model, an eighth the size.
SRAM = 0x20000000
SRAM_SIZE = 32 * 1024

#: Where the reset vector sits, relative to the lowest address the image loads
#: at. One candidate, and it is zero.
#:
#: The plain Cortex-M arrangement, and the contrast with the RP2040 is the
#: point: that part reserves the first 256 bytes of flash for boot2 and links
#: its vector table after it, so its tuple carries both 0 and 256. A SAMD21 has
#: no such blob -- flash *is* the reset address space -- so offering 256 here
#: would invite entering at whatever instruction happens to sit there.
VECTOR_TABLE_OFFSETS: tuple[int, ...] = (0,)

#: PORT, from `samd21g18a.h:389` -- `#define PORT (0x41004400U)`.
PORT = 0x41004400

#: PORT is two register groups, PA and PB, at a 0x80 stride. Read straight off
#: the instance header rather than assumed: `REG_PORT_DIR0` is `0x41004400` and
#: `REG_PORT_DIR1` is `0x41004480` (`instance/port.h:48,62`).
PORT_GROUP_STRIDE = 0x80
PORT_GROUPS = 2

#: Register offsets within a group, from `component/port.h:367-382`, which
#: gives offset and access type together:
#:
#:     __IO PORT_DIR_Type    DIR;     /**< Offset: 0x00 (R/W 32) Data Direction */
#:     __IO PORT_DIRCLR_Type DIRCLR;  /**< Offset: 0x04 (R/W 32) ... Clear */
#:     __IO PORT_DIRSET_Type DIRSET;  /**< Offset: 0x08 (R/W 32) ... Set */
#:     __IO PORT_DIRTGL_Type DIRTGL;  /**< Offset: 0x0C (R/W 32) ... Toggle */
#:     __IO PORT_OUT_Type    OUT;     /**< Offset: 0x10 (R/W 32) Data Output Value */
#:     __IO PORT_OUTCLR_Type OUTCLR;  /**< Offset: 0x14 (R/W 32) ... Clear */
#:     __IO PORT_OUTSET_Type OUTSET;  /**< Offset: 0x18 (R/W 32) ... Set */
#:     __IO PORT_OUTTGL_Type OUTTGL;  /**< Offset: 0x1C (R/W 32) ... Toggle */
#:     __IO PORT_IN_Type     IN;      /**< Offset: 0x20 (R/  32) Data Input Value */
PORT_DIR = 0x00
PORT_DIRCLR = 0x04
PORT_DIRSET = 0x08
PORT_DIRTGL = 0x0C
PORT_OUT = 0x10
PORT_OUTCLR = 0x14
PORT_OUTSET = 0x18
PORT_OUTTGL = 0x1C
PORT_IN = 0x20

#: Group index of PORTA, the only group either XIAO SAMD21 wires an LED to.
PORTA = 0

#: The XIAO SAMD21's user LED, from Seeed's own pin table:
#: `third_party/bsp/seeed-samd/variants/XIAO_m0/variant.h:67-69` defines
#: `LED_BUILTIN` as pin 13, and entry 13 of `g_APinDescription` in
#: `variant.cpp` is `{ PORTA, 17 }`. So the LED is PA17 -- a fact about the
#: board rather than the chip, kept here because the blink test needs a pin
#: and an arbitrary one would prove less.
LED_PIN = 17


class Cpu(typing.Protocol):
    """What this module needs of a core: the mapping calls it uses.

    Narrower than `rp2040.py`'s by one method -- nothing here mirrors, because
    the SAMD21 has no ready-follows-enable register on a blink's path. The
    protocol states what this board needs rather than what a board might.
    """

    def map_register(self, address: int, value: int = 0) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...
    def add_region(self, base: int, size: int, *, executable: bool = ...,
                   fill: int = ...) -> None: ...


def group(index: int) -> int:
    """Base address of PORT group `index` -- 0 is PA, 1 is PB."""
    if not 0 <= index < PORT_GROUPS:
        raise ValueError(
            f"PORT group {index} does not exist on this part: it has "
            f"{PORT_GROUPS} groups, 0 (PA) and {PORT_GROUPS - 1} (PB)"
        )
    return PORT + index * PORT_GROUP_STRIDE


def install_memory(cpu: Cpu) -> None:
    """Flash at zero and SRAM. The core ships with neither.

    SRAM is zero-filled and executable for the three reasons `rp2040.py`
    spells out at length -- contents are genuinely undefined at power-on so any
    specific fill invents a fact, and a real Cortex-M0+ executes from RAM. Both
    reasons are about the architecture and the physics, so they carry across to
    this part unchanged.
    """
    cpu.add_region(FLASH, FLASH_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True, fill=0x00)


def install_port(cpu: Cpu) -> None:
    """PORT: both groups, with their SET, CLR and TGL registers.

    **These read back, and SIO's identical-looking ones do not.** That is the
    one place this file departs from the shape `rp2040.py` set, and it is
    departing on evidence rather than symmetry.

    `component/port.h:367-382` marks `DIRSET`, `DIRCLR`, `DIRTGL`, `OUTSET`,
    `OUTCLR` and `OUTTGL` as `__IO ... (R/W 32)`. Only `WRCONFIG` in the whole
    group carries `__O  ... ( /W 32)`, so the header does draw the write-only
    distinction -- it simply does not draw it here. `readable=True` (the
    default) is therefore the sourced answer, and these are modelled as alias
    windows onto `DIR` and `OUT` rather than as write-only registers.

    Worth stating plainly, because the pull toward the other answer is strong:
    the SIO registers at the same conceptual position *are* write-only, that
    took a review round to get right, and the obvious move is to copy it
    across. The chips disagree, and the vendor header is what says so.

    **The residual, stated rather than buried.** No code in the fetched tree
    ever reads these -- every one of the ~20 uses across the Arduino core, the
    bootloaders and ASF's `port.h` driver is a write. So the read-back *value*
    is asserted by the header's access type and is not exercised by any driver
    here. If a future image reads `OUTSET` and acts on it, that is the claim to
    re-check first.
    """
    for index in range(PORT_GROUPS):
        base = group(index)

        cpu.map_register(base + PORT_DIR, 0)
        cpu.map_alias(base + PORT_DIRCLR, base + PORT_DIR, "clear")
        cpu.map_alias(base + PORT_DIRSET, base + PORT_DIR, "set")
        cpu.map_alias(base + PORT_DIRTGL, base + PORT_DIR, "xor")

        cpu.map_register(base + PORT_OUT, 0)
        cpu.map_alias(base + PORT_OUTCLR, base + PORT_OUT, "clear")
        cpu.map_alias(base + PORT_OUTSET, base + PORT_OUT, "set")
        cpu.map_alias(base + PORT_OUTTGL, base + PORT_OUT, "xor")

    # **`IN` is left unmapped on purpose, and that is not the same as
    # forgetting it.** The obvious move is `map_register(base + PORT_IN, 0)`,
    # mirroring SIO's `GPIO_IN` in `rp2040.py`, and here it would be worse than
    # nothing: `IN` reads the pin's electrical level, so on a pin driven as an
    # output it follows `OUT`. A stored register reading zero would answer
    # *wrongly* to firmware that drives PA17 high and reads it back -- the
    # failure class this project ranks above a fault, because a fault costs an
    # hour and a wrong value a driver acts on costs a day.
    #
    # The correct model is "OUT where DIR says output, external level where it
    # says input", which needs a mirror masked by a second register and is not
    # something the core can express today. Nothing has read `IN` yet, so the
    # honest answer is to fault until something does. `PORT_IN` stays exported
    # so a test can name the address it expects to fault at.


def install(cpu: Cpu) -> None:
    """Every region and peripheral this board models, which is not every one.

    **Precondition: no region may already cover this board's map.** Regions
    refuse to overlap, so a caller that installed memory of its own -- the test
    suite's bare SRAM, for instance -- must `clear_regions()` first.
    """
    install_memory(cpu)
    install_port(cpu)
