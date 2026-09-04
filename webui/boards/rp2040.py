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

#: UART0, from `rp2040_v2/rp2040_uart.json`, which cites pico-sdk's
#: `hardware/regs/uart.h` and `hardware_uart/uart.c`. UART1 is at 0x40038000
#: and is not modelled: the SVD declares it `derivedFrom="UART0"`, so it is the
#: same registers at another base, and nothing has asked for a second one.
UART0 = 0x40034000

#: The first 256 bytes of flash are boot2, the XIP setup blob, so a linked
#: image puts its vector table after it -- which is why `blink.ld` links at
#: 0x10000100 and not 0x10000000.
BOOT2_BYTES = 256

#: Where the reset vector may sit, relative to the lowest address the image
#: loads at. Tried in order.
#:
#: **This is a chip fact and it used to live in `webui/api.py`**, in a table
#: keyed by chip name beside the code that speaks HTTP. That was harmless while
#: one board could run anything and became a question with two answers the
#: moment a second could: a SAMD21 image has no boot2 in front of it, so an
#: RP2040's 256 would enter at a word that is not a stack pointer.
#:
#: Both are offered because a bare-metal image linked at 0x10000000 is as real
#: as a pico-sdk one linked past boot2, and `api.py` checks each candidate
#: against this board's own map rather than assuming.
VECTOR_TABLE_OFFSETS: tuple[int, ...] = (0, BOOT2_BYTES)

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

# --- BEGIN HEADER: generated by `python tools/import_pindefs.py --write-headers`; do not edit by hand ---
#: Header label -> GPIO number: the pin `pin_states` reads a level
#: through and `PIN_NAMES` spells. Read out of the board-support
#: packages, never typed here:
#:     zephyr boards/seeed/xiao_rp2040/seeed_xiao_connector.dtsi @ 0a2e408
#:     arduino-pico variants/seeed_xiao_rp2040/pins_arduino.h @ 33201a6
#: for XIAO-RP2040-DIP, XIAO-RP2040-SMD. A row is here only where every
#: package that defines it names the same pin; a row only one package
#: defines is that package's.
#: `LED` has no pad: it is the board's own LED, which the Arduino variant
#: above defines and the header does not carry.
#: `tests/rules/test_import_pindefs.py` holds this block equal to what the
#: generator emits from the fetched packages.
HEADER: dict[str, int] = {
    "D0": 26,
    "D1": 27,
    "D2": 28,
    "D3": 29,
    "D4": 6,
    "D5": 7,
    "D6": 0,
    "D7": 1,
    "D8": 2,
    "D9": 4,
    "D10": 3,
    "LED": 17,
}
# --- END HEADER ---

#: The same table read the other way, `D6` -> `GPIO0`, derived from `HEADER`
#: so the two cannot disagree; `samd21.py` makes the argument at its own
#: `PIN_NAMES`, and `webui/api.py` captions every pad from this.
#:
#: **`LED` is `PIN_LED`, the red element of the board's three-colour LED.**
#: Seeed's variant file wires red to GPIO17, green to GPIO16 and blue to
#: GPIO25, and a NeoPixel to GPIO12 with its power switch on GPIO11; only
#: `PIN_LED` is opted in, because it is what `LED_BUILTIN` names and so
#: the one pin a stock Blink drives. The other four are in the same file,
#: cited in the block above, for whoever models the rest.
PIN_NAMES: dict[str, str] = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}

#: UART (PL011) register offsets, from `rp2040_v2/rp2040_uart.json`, each
#: citing a line of pico-sdk's `hardware/regs/uart.h`.
UART_DR = 0x00
UART_FR = 0x18
UART_IBRD = 0x24
UART_FBRD = 0x28
UART_LCR_H = 0x2C
UART_CR = 0x30

#: `UARTCR.UARTEN`, bit 0, reset 0. The master enable, and the gate on the data
#: register. The research file is explicit about why it is load-bearing:
#: "A model letting TXFF/BUSY move before UARTEN==1 lets firmware appear to
#: print successfully before the UART is enabled -- silently wrong the same way
#: FUNCSEL errors are silently wrong."
UART_CR_UARTEN = 1 << 0

#: `UARTFR` bits, from the same file. `RXFE` is the only one set in the model
#: this board can express -- see `install_uart0`.
UART_FR_BUSY = 1 << 3
UART_FR_RXFE = 1 << 4
UART_FR_TXFF = 1 << 5

#: What `UARTFR` reads in this model: receive FIFO empty, transmit FIFO not
#: full, transmitter not busy.
UART_FR_AT_REST = UART_FR_RXFE

#: TIMER, from pico-sdk's `hardware/regs/addressmap.h`:
#: `#define TIMER_BASE _u(0x40054000)`. The research file names the same base.
TIMER = 0x40054000

#: `TIMER_TIMERAWL_OFFSET _u(0x00000028)` -- "Raw read from bits 31:0 of time
#: (no side effects)", access "RO". Read from the header rather than from the
#: research, which records these offsets as ungrepped.
TIMER_TIMERAWL = 0x28

#: How many retired instructions make one microsecond of virtual time.
#:
#: **A stated approximation, and not a measurement.** The RP2040's TIMER counts
#: microseconds and the part's default system clock is 125 MHz, so 125 would be
#: exactly right if every instruction took one cycle -- which on a Cortex-M0+ it
#: does not: loads, stores and taken branches take more, and this core models no
#: cycle costs at all. So the number below is the right order of magnitude and
#: nothing finer, and **this model does not claim cycle accuracy**.
#:
#: What it does guarantee is what a busy-wait actually needs: virtual time that
#: is monotonic, deterministic and an integer -- the last per
#: `rules/determinism.md` §3, which notes that a float accumulator makes step
#: size affect results. A firmware delay measured in emulated microseconds is
#: therefore repeatable, and is not a claim about wall-clock time.
TIMER_INSTRUCTIONS_PER_TICK = 125

#: The RESETS bit that holds UART0. From `rp2040_v2/rp2040_uart.json`'s
#: instance table, cross-checked against `resets.json`'s bit table, where 22 is
#: UART0 and 23 is UART1.
RESET_UART0 = 1 << 22


class Cpu(typing.Protocol):
    """What this module needs of a core: the mapping calls it uses."""

    def map_register(self, address: int, value: int = 0) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...
    def map_mirror(self, address: int, source: int, *, invert: bool = ...,
                   mask: int = ...) -> None: ...
    def map_constant(self, address: int, value: int) -> None: ...
    def map_stream(self, address: int, *, enable: int,
                   enable_mask: int) -> None: ...
    def map_counter(self, address: int, instructions_per_tick: int) -> None: ...
    def stream(self, address: int) -> bytes: ...
    def add_region(self, base: int, size: int, *, executable: bool = ...,
                   fill: int = ...) -> None: ...
    def read_word(self, address: int) -> int: ...


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

    # `readable=False` on every one of these. They are dedicated write-only
    # registers, not alias windows: hardware reads them as zero, and the oracle
    # agrees -- rp2040js's SIO read switch has no case for them, while its bus
    # alias path masks an aliased address back to the base register and returns
    # that. Reading GPIO_OUT through GPIO_OUT_SET is a wrong value rather than
    # a missing feature, which is the one failure this project treats as worse
    # than a fault.
    cpu.map_register(SIO + SIO_GPIO_OUT, 0)
    cpu.map_alias(SIO + SIO_GPIO_OUT_SET, SIO + SIO_GPIO_OUT, "set", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OUT_CLR, SIO + SIO_GPIO_OUT, "clear", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OUT_XOR, SIO + SIO_GPIO_OUT, "xor", readable=False)

    cpu.map_register(SIO + SIO_GPIO_OE, 0)
    cpu.map_alias(SIO + SIO_GPIO_OE_SET, SIO + SIO_GPIO_OE, "set", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OE_CLR, SIO + SIO_GPIO_OE, "clear", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OE_XOR, SIO + SIO_GPIO_OE, "xor", readable=False)


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    `"high"`, `"low"` or `"input"` keyed by the label in `HEADER`, which is
    what `webui.api.pin_view` finds by `getattr`; `samd21.py` states the
    contract at its own `pin_states`, including why the power pads are
    absent and why a pin whose output is not enabled reports `input` rather
    than whatever `GPIO_OUT` holds for it.

    **`GPIO_OE` decides before `GPIO_OUT` does**, and each is read once:
    `rp2040_v2/rp2040_sio.json` records both as one read-write register,
    `GPIO_OUT` at 0x10 and `GPIO_OE` at 0x20 with "bits 29-0, output enable
    per pin" -- so every GPIO this part has is one bit of each, and
    `tests/webui/test_pin_view.py` holds every `HEADER` value under 30, which
    is that quoted range and not the register's width.
    """
    enabled = cpu.read_word(SIO + SIO_GPIO_OE)
    out = cpu.read_word(SIO + SIO_GPIO_OUT)
    states: dict[str, str] = {}
    for label, gpio in HEADER.items():
        mask = 1 << gpio
        if not enabled & mask:
            states[label] = "input"
        else:
            states[label] = "high" if out & mask else "low"
    return states


def install_uart0(cpu: Cpu) -> None:
    """UART0, far enough for a `printf` to arrive and no further.

    Register facts from `rp2040_v2/rp2040_uart.json`, which cites pico-sdk's
    `hardware/regs/uart.h` line by line.

    **`UARTDR` is a stream, not a register**, and that is the whole reason this
    peripheral needed something new in the core. The research file puts it
    plainly: "Queue-op semantics, not a plain register store -- the canonical
    reason this whole peripheral is coded:". A `map_register` here would hold
    one character, so every byte but the last would be lost, and a test reading
    it back would see a plausible single letter rather than an empty output --
    wrong rather than loud.

    **The `UARTEN` gate is why `map_stream` takes one.** Bytes are captured
    only while the master enable is set, so firmware that writes `UARTDR`
    before enabling the UART transmits nothing, exactly as the part does.

    **`UARTFR` is a constant, and that is a stated fidelity gap rather than an
    oversight.** In the model this board can express -- a transmitter that
    always accepts and a receiver with no wire on it -- `TXFF`, `RXFE` and
    `BUSY` never move, so they are not a register that changes. What this
    cannot show is FIFO backpressure, and the research file names the cost:
    forcing `TXFF` low forever "would erase FIFO-full backpressure a real
    firmware bug (printing faster than the wire) would actually hit". Modelling
    the 32-entry FIFO needs a virtual-cycle schedule tied to the baud divisors,
    which is `rules/determinism.md` work and a bigger change than a printf
    needs. `RXFE` reading empty forever is not a gap in the same way: nothing
    in this project drives RX, so an empty receive FIFO is the truth.

    The four configuration registers are plain latches. Firmware writes the
    baud divisors and the line control and never reads them back, so
    reads-as-written is both what the part does and all that is exercised.
    """
    # Written before the stream, because `map_stream` resolves its gate at
    # write time and a board that registered them the other way round would
    # still work -- but reading them in dependency order is how the reader
    # learns that the data register depends on the control register.
    cpu.map_register(UART0 + UART_CR, 0)
    cpu.map_register(UART0 + UART_IBRD, 0)
    cpu.map_register(UART0 + UART_FBRD, 0)
    cpu.map_register(UART0 + UART_LCR_H, 0)

    cpu.map_constant(UART0 + UART_FR, UART_FR_AT_REST)
    cpu.map_stream(UART0 + UART_DR, enable=UART0 + UART_CR,
                   enable_mask=UART_CR_UARTEN)

    # UART is one of the four peripherals whose atomic aliases are real, per
    # datasheet §2.1.2 as quoted in the research file: I2C, UART, SPI and SSI
    # get theirs "using a bus interposer". So `hw_set_bits()` on UARTCR works,
    # which pico-sdk's uart_init does, and leaving them out would fault on a
    # driver doing something ordinary.
    alias_block(cpu, UART0 + UART_CR)
    alias_block(cpu, UART0 + UART_LCR_H)


def uart0_output(cpu: Cpu) -> bytes:
    """Everything UART0 has transmitted, oldest byte first."""
    return cpu.stream(UART0 + UART_DR)


def install_timer(cpu: Cpu) -> None:
    """TIMER, far enough for a busy-wait to end, and no further.

    Offsets from pico-sdk's own `hardware/regs/timer.h`, which the research
    file explicitly did **not** grep -- it records TIMERAWL/H as "offsets not
    grepped this session", so these were read from the header directly:
    `TIMER_TIMERAWL_OFFSET _u(0x00000028)`, described there as "Raw read from
    bits 31:0 of time (no side effects)", access `"RO"`.

    **This is the hang class that is not a status bit.** `timer_busy_wait_us_32()`
    spins `while (timer->timerawl - start < delay_us)`, so a TIMERAWL that does
    not advance runs forever -- and that hang cannot be made loud the way a
    missing register can, because the address is modelled and the read does
    answer. It just answers the same thing every time.

    **What is deliberately not here, and why it cannot be.** `sleep_ms()` does
    not poll; it arms an alarm and waits for its interrupt. Modelling ALARM0-3
    needs an IRQ to deliver, and this core has no exceptions -- so the alarm
    half of TIMER is blocked on a piece of work this ticket does not contain,
    rather than skipped. TIMERAWH, TIMELR and TIMEHR are likewise unmapped, so
    a 64-bit `time_us_64()` faults and names the address instead of reading a
    plausible zero.
    """
    cpu.map_counter(TIMER + TIMER_TIMERAWL, TIMER_INSTRUCTIONS_PER_TICK)


def install_memory(cpu: Cpu) -> None:
    """Flash and SRAM. The core ships with neither.

    **SRAM is left zero-filled and executable, and that is a decision.** Flash
    gets 0xFF because that is what an erased part reads and because 0xFFFF
    stops the core; the temptation is to give SRAM a poison fill for the same
    reason, and it would be wrong three times over. SRAM contents really are
    undefined at power-on, so any specific fill invents a fact. rp2040js
    answers zero, and diverging from the oracle costs more than it buys. And
    making SRAM non-executable would be the worst of the three: a real
    Cortex-M0+ executes from SRAM, and firmware that copies a routine into RAM
    and calls it is ordinary rather than exotic.

    The asymmetry with flash is the interesting part, which is why it is
    written down rather than left as a default that fell out.
    """
    cpu.add_region(FLASH, FLASH_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True, fill=0x00)


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
    """Every region and peripheral this board models, which is not every one.

    **Precondition: no region may already cover this board's map.** Regions
    refuse to overlap, so a caller that has installed memory of its own -- the
    test suite's bare SRAM, for instance -- must `clear_regions()` first. The
    refusal is loud, but it is easier to read here than in a traceback.
    """
    install_memory(cpu)
    install_bootrom_stub(cpu)
    install_resets(cpu)
    install_sio(cpu)
    install_uart0(cpu)
    install_timer(cpu)
