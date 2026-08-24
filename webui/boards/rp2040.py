#!/usr/bin/env python3
# OpenHardware - the RP2040 as a set of registers over the Cortex-M0+ core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an RP2040 to a `core.cortexm0` CPU.

`core/cortexm0` is the architecture and knows no chip. This is the other half:
the addresses, the reset values and the wiring between registers that make a
particular part. Nothing here is an instruction and nothing in the core is an
address.

## Where these numbers come from

`docs/research/peripheral-layer/rp2040_v2/`, which nine agents produced with
citations to the datasheet and to pico-sdk, and which is marked **unadopted**.
This file adopts a small part of it -- the part a blink image actually reaches
-- and nothing else. Each register below cites the research file that carries
its provenance, so the chain back to a datasheet page survives.

## The atomic aliases, and the one exception

RP2040 gives most peripherals three extra windows: `+0x1000` XOR, `+0x2000`
SET, `+0x3000` CLR. Datasheet §2.1.2 (p.17) is quoted in full in
`rp2040_v2/rp2040.json`; the short version is that this is a property of
**almost every peripheral**, and SIO is the only named exception.

That exception matters and the research corrected itself on it once: the first
reading was "aliases apply to the APB range", which is wrong, because SSI at
0x18000000 is nowhere near APB and does have them. The rule is per-peripheral,
not per-address-range, so `alias_block` below is called explicitly per
peripheral rather than applied to a region.

## What is deliberately absent

Everything a blink does not touch. Adding a peripheral here is cheap and
adding one that has never been exercised is how a model acquires registers
nobody has checked -- so this grows only when a real image faults on something,
and `tools/lockstep_armv6m.mjs --profile-peripherals` says what that is.
"""

from __future__ import annotations

import typing

#: The memory map. The core has none of its own, so this is the whole of it.
#: Flash is XIP-mapped at 0x10000000; a SAMD21 over the same core puts its
#: flash at zero, which is the difference that moved these out of the core.
FLASH = 0x10000000
FLASH_SIZE = 2 * 1024 * 1024

#: Erased flash reads 0xFF on a real part. It is also the loud value: 0xFFFF is
#: not a valid Thumb encoding, so a program that runs off the end of its image
#: stops, rather than executing zeros as `MOVS r0, r0` for as long as anyone
#: watches.
FLASH_ERASED = 0xFF

SRAM = 0x20000000
SRAM_SIZE = 264 * 1024

#: The boot ROM. 16 KB at zero on the real part; the first words are a vector
#: table and a table of function pointers the runtime looks up.
BOOTROM = 0x00000000
BOOTROM_SIZE = 16 * 1024

#: Peripheral bases, from `rp2040_v2/rp2040.json`.
RESETS = 0x4000C000
SIO = 0xD0000000

#: The three alias windows, from datasheet §2.1.2.
ALIAS_XOR = 0x1000
ALIAS_SET = 0x2000
ALIAS_CLR = 0x3000

#: RESETS register offsets, from `rp2040_v2/resets.json`, which cites
#: `hardware/regs/resets.h` and cross-checks against RP2040.svd.
RESETS_RESET = 0x00
RESETS_WDSEL = 0x04
RESETS_RESET_DONE = 0x08

#: All 25 resettable blocks come up held in reset. Undoing this is the first
#: thing `runtime_init()` does, and a model that came up with 0 here would let
#: firmware skip the unreset it is about to wait on.
RESETS_RESET_AT_POR = 0x01FFFFFF

#: Bits 25-31 of RESET and RESET_DONE are reserved and read zero.
RESETS_BLOCK_MASK = 0x01FFFFFF

#: SIO registers a blink reaches, from `rp2040_v2/rp2040_sio.json`.
SIO_CPUID = 0x000
SIO_GPIO_IN = 0x004
SIO_GPIO_OUT = 0x010
SIO_GPIO_OUT_SET = 0x014
SIO_GPIO_OUT_CLR = 0x018
SIO_GPIO_OUT_XOR = 0x01C
SIO_GPIO_OE = 0x020
SIO_GPIO_OE_SET = 0x024
SIO_GPIO_OE_CLR = 0x028
SIO_GPIO_OE_XOR = 0x02C


class Cpu(typing.Protocol):
    """What this module needs of a core: the three mapping calls."""

    def map_register(self, address: int, value: int = 0) -> None: ...
    def map_alias(self, address: int, target: int, op: str) -> None: ...
    def map_mirror(self, address: int, source: int, *, invert: bool = ...,
                   mask: int = ...) -> None: ...
    def add_region(self, base: int, size: int, *, executable: bool = ...,
                   fill: int = ...) -> None: ...


def alias_block(cpu: Cpu, address: int) -> None:
    """Give one register its XOR, SET and CLR windows.

    Called per register rather than per peripheral, because the aliases are
    address arithmetic on the whole peripheral window: the SET view of the
    register at `base + 0x08` is at `base + 0x2008`, not at `base + 0x2000`.
    """
    cpu.map_alias(address + ALIAS_XOR, address, "xor")
    cpu.map_alias(address + ALIAS_SET, address, "set")
    cpu.map_alias(address + ALIAS_CLR, address, "clear")


def install_resets(cpu: Cpu) -> None:
    """RESETS, and the RESET_DONE mirror a driver spins on.

    `unreset_block_num_wait_blocking()` clears a bit in RESET and then loops
    until the matching bit appears in RESET_DONE. RESET_DONE is not a stored
    register: it is the inverse of RESET, so the mirror is what makes that loop
    terminate. Storing it instead would leave the loop spinning on a value
    nothing updates -- a hang that looks exactly like a bad instruction.
    """
    cpu.map_register(RESETS + RESETS_RESET, RESETS_RESET_AT_POR)
    cpu.map_register(RESETS + RESETS_WDSEL, 0)
    cpu.map_mirror(RESETS + RESETS_RESET_DONE, RESETS + RESETS_RESET,
                   invert=True, mask=RESETS_BLOCK_MASK)
    alias_block(cpu, RESETS + RESETS_RESET)
    alias_block(cpu, RESETS + RESETS_WDSEL)


def install_sio(cpu: Cpu) -> None:
    """SIO: the core's identity and the GPIO registers.

    **No `alias_block` here.** SIO is the one peripheral on this chip without
    bus-level atomic aliases; its GPIO registers instead carry their own
    dedicated SET/CLR/XOR registers at fixed offsets, which is a different
    mechanism reaching the same result. Applying the +0x1000 windows here would
    invent registers the part does not have.

    CPUID reads 0 for core 0. The runtime reads it to tell the two cores apart,
    and it is the very first peripheral access a Pico image makes.
    """
    cpu.map_register(SIO + SIO_CPUID, 0)
    cpu.map_register(SIO + SIO_GPIO_IN, 0)

    cpu.map_register(SIO + SIO_GPIO_OUT, 0)
    cpu.map_alias(SIO + SIO_GPIO_OUT_SET, SIO + SIO_GPIO_OUT, "set")
    cpu.map_alias(SIO + SIO_GPIO_OUT_CLR, SIO + SIO_GPIO_OUT, "clear")
    cpu.map_alias(SIO + SIO_GPIO_OUT_XOR, SIO + SIO_GPIO_OUT, "xor")

    cpu.map_register(SIO + SIO_GPIO_OE, 0)
    cpu.map_alias(SIO + SIO_GPIO_OE_SET, SIO + SIO_GPIO_OE, "set")
    cpu.map_alias(SIO + SIO_GPIO_OE_CLR, SIO + SIO_GPIO_OE, "clear")
    cpu.map_alias(SIO + SIO_GPIO_OE_XOR, SIO + SIO_GPIO_OE, "xor")


def install_memory(cpu: Cpu) -> None:
    """Flash and SRAM. The core ships with neither."""
    cpu.add_region(FLASH, FLASH_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True)


def install_bootrom_stub(cpu: Cpu) -> None:
    """A zero-filled, **non-executable** boot ROM.

    The real contents are not ours to ship. A compiled RP2040 boot ROM contains
    `mufplib`, licensed for use "solely on a Raspberry Pi RP2040 device" or
    else under GPL-2 -- and an emulator is not that device. So this repository
    ships zeros and the question of fetching a real image stays a decision for
    a person, recorded in the 2026-08-24 handoff §6.5.

    Zeros are also what the oracle answers: rp2040js allocates a 4 KB bootrom
    array and leaves it zeroed unless `loadBootrom()` is called, which the
    lockstep harness does not do. So this matches the model the core is
    compared against, rather than diverging from it.

    **Non-executable is the load-bearing half.** Firmware *reads* this region
    -- `rom_func_lookup` walks a table here -- and answering zero to a read is
    survivable and matches the oracle. *Executing* zeros is not: they decode as
    `MOVS r0, r0` and the core would run quietly off the end of the region
    instead of saying the boot ROM is a stub.
    """
    cpu.add_region(BOOTROM, BOOTROM_SIZE, executable=False)


def install(cpu: Cpu) -> None:
    """Every region and peripheral this board models, which is not every one."""
    install_memory(cpu)
    install_bootrom_stub(cpu)
    install_resets(cpu)
    install_sio(cpu)
