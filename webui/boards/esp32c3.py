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

Every timer, the ADC, SPI, I2C, and the whole clock and reset subsystem. Same
growth rule the other three boards keep: a peripheral is added when a real
image faults on it and not before. Here the rule has teeth --
`core/riscv32/cpu.h` faults on any address no region and no register covers, so
a program that touches an undescribed peripheral stops and names the address
rather than reading zero and hanging.

**The UART is half here since OH-161**, and the half is the load-bearing part
of the sentence: UART0's transmit FIFO and the clock bit that gates it, which
is what a `Serial.print` needs and no more. Its receive half, its baud
divisors and `UART_TXFIFO_CNT` are unmapped, so firmware that waits for room
in the FIFO or reads a byte back faults at a named address instead of spinning
on a zero, and UART1 is not mapped at all.
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

#: UART0's base, from `soc.h`:
#:
#:     #define DR_REG_UART_BASE  0x60000000                          :42
#:     #define REG_UART_BASE(i)  (DR_REG_UART_BASE + (i) * 0x10000)   :72
#:
#: So UART0 is the base itself and UART1 is 64 KB above it. Only UART0 is
#: modelled, and **not because it is where a XIAO's `Serial` goes by
#: default**, which it is not. This repository already recorded the opposite
#: twice and this comment claimed it anyway until the OH-161 review:
#:
#:   * `docs/research/peripheral-layer/esp32c3/uart-contract.json`, verified
#:     2026-08-24: the XIAO ESP32-C3 has no UART-to-USB bridge, Arduino
#:     defaults CDC-on-boot to 1, and `Serial` lands on USB_SERIAL_JTAG at
#:     0x60043000.
#:   * Seeed's own `XIAO_ESP32C3_Pin_Multiplexing.md:112-126`: "By default,
#:     USB serial is enabled... if you want to use UART0 as the serial, you
#:     need to connect pin D6 as the TX pin and pin D7 as RX pin with a
#:     USB-Serial adapter", and set USB CDC On Boot to Disabled.
#:
#: The two reasons that survive are the ones that research file gives: UART0
#: is the ROM download console and the target of `esp_rom_printf` before an
#: application configures anything, and non-XIAO C3 devkits -- an
#: ESP32-C3-DevKitM-1 -- do bridge it to a USB-serial chip. So a sketch
#: printing here models the vendor's *documented alternative* wiring, and
#: 0x60043000 is not mapped: a program reaching for USB_SERIAL_JTAG faults at
#: a named address rather than printing somewhere it would not have.
UART0 = 0x60000000

#: The transmit FIFO, `uart_reg.h:22` -- `UART_FIFO_REG(i)` at
#: `REG_UART_BASE(i) + 0x0`, whose data field `UART_RXFIFO_RD_BYTE` is
#: `bitpos:[7:0]` (:25).
#:
#: **A queue, not a word**, which is why `core/riscv32` grew `map_stream` for
#: it: a `map_register` here would hold the last byte written, so a program
#: printing `hello` would leave an `o` behind and a reader would see a
#: plausible letter rather than a wrong answer.
UART_FIFO = 0x00

#: The clock register, `uart_reg.h:1160`, and the bit that gates the
#: transmitter, `UART_TX_SCLK_EN` at `BIT(24)` (:1181), `default: 1'b1`.
#:
#: **On this part it is at + 0x78 and on a C5 or a C6 at + 0x88**, which is
#: the same shape of difference the GPIO file already carries: same peripheral,
#: same bit, different offset, and a board written by copying its neighbour
#: would gate on an address that is something else here.
UART_CLK_CONF = 0x78
UART_TX_SCLK_EN = 1 << 24

#: What that register holds out of reset, composed from the header's own
#: `default:` annotations at `uart_reg.h:1160-1215` rather than from the one
#: bit this model reads: `SCLK_DIV_B` [5:0] 0, `SCLK_DIV_A` [11:6] 0,
#: `SCLK_DIV_NUM` [19:12] 1, `SCLK_SEL` [21:20] 3, `SCLK_EN` [22] 1,
#: `RST_CORE` [23] 0, `TX_SCLK_EN` [24] 1, `RX_SCLK_EN` [25] 1,
#: `TX_RST_CORE` [26] 0, `RX_RST_CORE` [27] 0.
#:
#: Firmware that reads this register back gets what the part gives it,
#: including the divider fields nothing here uses -- a reset value narrowed to
#: the interesting bit would be a wrong answer to a driver that checked one of
#: the others.
UART_CLK_CONF_AT_RESET = 0x03701000

#: The pin the fixture watches. **Not a user LED** -- see the module docstring.
#: GPIO8 is what Espressif's own ESP32-C3-DevKitM-1 wires its RGB LED to, and
#: on a XIAO it is an ordinary exposed output -- the pad silkscreened `D8`,
#: as `HEADER` below reads out of Seeed's own variant file.
LED_PIN = 8

# --- BEGIN HEADER: generated by `python tools/import_pindefs.py --write-headers`; do not edit by hand ---
#: Header label -> GPIO number: the pin `pin_states` reads a level
#: through and `PIN_NAMES` spells. Read out of the board-support
#: packages, never typed here:
#:     zephyr boards/seeed/xiao_esp32c3/seeed_xiao_connector.dtsi @ 0a2e408
#:     arduino-esp32 variants/XIAO_ESP32C3/pins_arduino.h @ 2787dab
#: for XIAO-ESP32-C3-DIP, XIAO-ESP32-C3-DIP-SMD, XIAO-ESP32-C3-SMD. A row is
#: here only where every package that defines it names the same pin; a row
#: only one package defines is that package's.
#: `tests/rules/test_import_pindefs.py` holds this block equal to what the
#: generator emits from the fetched packages.
HEADER: dict[str, int] = {
    "D0": 2,
    "D1": 3,
    "D2": 4,
    "D3": 5,
    "D4": 6,
    "D5": 7,
    "D6": 21,
    "D7": 20,
    "D8": 8,
    "D9": 9,
    "D10": 10,
}
# --- END HEADER ---

#: The same table read the other way: label -> the pin as Espressif spells
#: it, `D6` -> `GPIO21`. **Derived from `HEADER` rather than typed out**, so
#: the two cannot disagree; `samd21.py` makes the argument at its own
#: `PIN_NAMES`, and `webui/api.py` captions every pad from this.
#:
#: **Keyed by the vendor's label, not the silkscreen's.** The DIP's pad is
#: silkscreened `D9/BOOT` and the SMD's underside `D3/MTDI`; both packages
#: define `D9` and `D3`, and `webui.api.header_key` joins a pad's compound
#: label onto the half this table knows.
PIN_NAMES: dict[str, str] = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}


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
    def map_stream(self, address: int, *, enable: int,
                   enable_mask: int) -> None: ...
    def stream(self, address: int) -> bytes: ...
    def read_word(self, address: int) -> int: ...


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


def install_uart0(cpu: Cpu) -> None:
    """UART0, far enough for a `Serial.print` to arrive and no further.

    Two addresses: the FIFO as a stream, and the clock register that gates it.
    `webui/boards/rp2040.py` models the same shape on a PL011 and its
    `install_uart0` carries the long argument for why a FIFO is not a
    register; what differs here is the gate. A PL011 transmits when
    `UARTCR.UARTEN` is set, which firmware must do; this part's
    `UART_TX_SCLK_EN` is 1 out of reset, so a bare-metal image transmits
    without touching it and one that clears the bit goes quiet.

    **What is deliberately absent, and what it costs.** `UART_STATUS_REG`'s
    `UART_TXFIFO_CNT` is not mapped, so firmware that waits for room in the
    FIFO before writing faults at a named address rather than spinning on a
    zero -- the growth rule this board keeps. The baud divisors are not mapped
    either: nothing here has a wire or a bit rate, so a divisor would be a
    number with no meaning, and this model transmits every byte instantly.
    That is the same fidelity gap the RP2040's `UARTFR` records: what cannot
    be shown is backpressure, and a real firmware bug that printed faster than
    the wire would not show up here.
    """
    cpu.map_register(UART0 + UART_CLK_CONF, UART_CLK_CONF_AT_RESET)
    # After the gate, because `map_stream` resolves it at WRITE time and a
    # board that registered them the other way round would still work -- but
    # reading them in dependency order is how a reader learns that the data
    # register depends on the clock one.
    cpu.map_stream(UART0 + UART_FIFO, enable=UART0 + UART_CLK_CONF,
                   enable_mask=UART_TX_SCLK_EN)


def uart0_output(cpu: Cpu) -> bytes:
    """Every byte this board has transmitted, oldest first.

    The name `webui/api.py`'s `uart_view` finds by `getattr`, so a board that
    models a UART needs no change there and one that does not is reported as
    a board that cannot print rather than as a program that printed nothing.
    """
    return cpu.stream(UART0 + UART_FIFO)


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    `"high"`, `"low"` or `"input"`, keyed by the label in `HEADER`, which is
    what `webui.api.pin_view` finds by `getattr` -- the contract `samd21.py`
    states at its own `pin_states`, including why the three power pads are
    absent: `3V3_OUT` has no register behind it, and a `"low"` for `GND`
    would be a sentence about the program when the truth is one about the
    board.

    **`ENABLE` decides before `OUT` does.** A pin whose output driver is off
    has no driven level, and `OUT` for it holds the value the driver *would*
    use -- the plausible-but-wrong answer `install_gpio` refuses for `IN`.
    A pull-up makes a real input read high and this model has no pulls, so
    `input` is as far as it can honestly go.

    Each register is read once, because each is ONE register on this part:
    `gpio_reg.h:59` gives `GPIO_OUT_DATA` as `bitpos:[25:0]` and `:91`
    `GPIO_ENABLE_DATA` the same, and there is no `GPIO_OUT1_REG` -- which is
    also why a `HEADER` value of 26 or more could never be right here, and
    `tests/webui/test_pin_view.py` holds every value of this part's table
    under 26 for that reason rather than under 32.
    """
    enable = cpu.read_word(GPIO + GPIO_ENABLE)
    out = cpu.read_word(GPIO + GPIO_OUT)
    states: dict[str, str] = {}
    for label, gpio in HEADER.items():
        mask = 1 << gpio
        if not enable & mask:
            states[label] = "input"
        else:
            states[label] = "high" if out & mask else "low"
    return states


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
    install_uart0(cpu)
