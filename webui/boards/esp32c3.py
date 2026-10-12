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

Every timer but one, the ADC, SPI, I2C, and the whole clock and reset
subsystem. Same growth rule the other three boards keep: a peripheral is added
when a real image faults on it and not before. Here the rule has teeth --
`core/riscv32/cpu.h` faults on any address no region and no register covers, so
a program that touches an undescribed peripheral stops and names the address
rather than reading zero and hanging.

**The UART is half here since OH-161**, and the half is the load-bearing part
of the sentence: UART0's transmit FIFO and the clock bit that gates it, which
is what a `Serial.print` needs and no more. Its receive half, its baud
divisors and `UART_TXFIFO_CNT` are unmapped, so firmware that waits for room
in the FIFO or reads a byte back faults at a named address instead of spinning
on a zero, and UART1 is not mapped at all.

**The one timer is SYSTIMER's unit 0, since OH-161's step 2** -- the counter
ESP-IDF's `esp_timer` reads (`SYSTIMER_COUNTER_ESPTIMER 0`, ESP-IDF v5.5's
`components/esp_hw_support/include/esp_private/systimer.h:30`), which is
what arduino-esp32's own `millis()` and `micros()` return
(`cores/esp32/esp32-hal-misc.c:204-210` @ 2787dab) -- so it is what this
repository's own two read. Its enable, its UPDATE / VALUE_VALID handshake and
its two value registers; not unit 1, which is the one ESP-IDF's OS tick
counts on (:31), not the LOAD registers that set a count, and not the three
comparators, whose alarms need an interrupt this core cannot deliver. See
`install_systimer`.

**The pins read since OH-161's step 3**: `GPIO_IN` and the IO_MUX pad
register of every GPIO, whose input enable and pulls decide what an input
reads. What the outside drives onto a pin arrives only through
`drive_pins`. See `install_gpio_in`.
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

#: IO_MUX, `soc.h:49` -- `#define DR_REG_IO_MUX_BASE 0x60009000`.
IO_MUX = 0x60009000

#: GPIO0's pad register, `io_mux_reg.h:175` --
#: `#define PERIPHS_IO_MUX_XTAL_32K_P_U (REG_IO_MUX_BASE +0x04)` -- and each
#: next GPIO's four bytes on: C3 TRM v1.4, Register 5.21, `IO_MUX_GPIOn_REG
#: (n: 0-21) (0x0004+4*n)`, p.187. **+ 0x04 here and on a C6, + 0x0 on a
#: C5**, the third offset this block moves between neighbours.
IO_MUX_GPIO0 = 0x04
IO_MUX_STRIDE = 4

#: The pad register's bits this model reads, `io_mux_reg.h`:
#:
#:     #define FUN_PD (BIT(7))     :51    pull-down enable
#:     #define FUN_PU (BIT(8))     :56    pull-up enable
#:     #define FUN_IE (BIT(9))     :61    input enable
#:     #define FUN_DRV_S 10        :69    drive strength, [11:10]
#:
#: The TRM calls the first two `FUN_WPD` and `FUN_WPU` (Register 5.21).
IO_MUX_FUN_PD = 1 << 7
IO_MUX_FUN_PU = 1 << 8
IO_MUX_FUN_IE = 1 << 9
IO_MUX_FUN_DRV_SHIFT = 10

#: Every pad this part has, GPIO -> its "DRV" and "Reset" columns in C3 TRM
#: v1.4 Table 5.12-1, "IO MUX Pin Functions", p.174. Twenty-two GPIOs, 0 to
#: 21, as Register 5.21's `n: 0-21` says.
IO_MUX_PADS: dict[int, tuple[int, str]] = {
    0: (2, "0"), 1: (2, "0"), 2: (2, "1"), 3: (2, "1"), 4: (2, "1"),
    5: (2, "1"), 6: (2, "1*"), 7: (2, "1"), 8: (2, "1"), 9: (2, "3"),
    10: (2, "1"), 11: (2, "0"), 12: (2, "3"), 13: (2, "3"), 14: (2, "3"),
    15: (2, "3"), 16: (2, "3"), 17: (2, "3"), 18: (3, "0"), 19: (3, "0*"),
    20: (2, "3"), 21: (2, "4"),
}

#: The "Reset" column's codes as pad bits, from the legend under the table,
#: "Reset Configurations", p.175:
#:
#:   0   IE = 0                    0*  IE = 0, WPU = 0, and GPIO19's USB
#:   1   IE = 1                        pull-up is on, which is a USB_SERIAL_JTAG
#:   3   IE = 1, WPU = 1               register this model does not map
#:   4   OE = 1, WPU = 1           1*  MTCK: IE = 1, WPU = 1 while
#:                                     EFUSE_DIS_PAD_JTAG is 0, its default
#:                                     (datasheet v2.4 Table 2-1 note 6, p.17)
#:
#: "4"'s OE is UART0's transmitter driving GPIO21 through function 0, not a
#: bit of the pad register, and this model routes no peripheral to a pad: an
#: image that reads GPIO21 without configuring it reads its IE, which is 0.
IO_MUX_RESET_BITS: dict[str, int] = {
    "0": 0,
    "0*": 0,
    "1": IO_MUX_FUN_IE,
    "1*": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "3": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "4": IO_MUX_FUN_PU,
}

#: Each pad register's word out of reset: Register 5.21's reset row with its
#: drive strength and its three pad bits replaced by the pad's own two
#: columns. Every other field of that row is 0 -- `MCU_SEL` 0x0 among them --
#: so the word is the two columns and nothing else. Firmware reading a pad
#: register back gets what the part gives it, the drive strength included,
#: though this model reads only the three bits.
IO_MUX_AT_RESET: dict[int, int] = {
    gpio: (drv << IO_MUX_FUN_DRV_SHIFT) | IO_MUX_RESET_BITS[code]
    for gpio, (drv, code) in IO_MUX_PADS.items()
}

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

#: SYSTIMER's base, `soc.h:61` -- `#define DR_REG_SYSTIMER_BASE 0x60023000`.
SYSTIMER = 0x60023000

#: The four registers of it this board models, from `systimer_reg.h`, as
#: offsets because that is how the header writes them:
#:
#:     #define SYSTIMER_CONF_REG            (DR_REG_SYSTIMER_BASE + 0x0)   :26
#:     #define SYSTIMER_UNIT0_OP_REG        (DR_REG_SYSTIMER_BASE + 0x4)   :108
#:     #define SYSTIMER_UNIT0_VALUE_HI_REG  (DR_REG_SYSTIMER_BASE + 0x40)  :344
#:     #define SYSTIMER_UNIT0_VALUE_LO_REG  (DR_REG_SYSTIMER_BASE + 0x44)  :356
#:
#: Every other register in the block is unmapped, so firmware that loads a
#: count (`SYSTIMER_UNIT0_LOAD_LO_REG` at + 0x10, :158), arms an alarm or
#: asks unit 1 for a snapshot (`SYSTIMER_UNIT1_OP_REG` at + 0x8, :127)
#: faults at a named address.
SYSTIMER_CONF = 0x00
SYSTIMER_UNIT0_OP = 0x04
SYSTIMER_UNIT0_VALUE_HI = 0x40
SYSTIMER_UNIT0_VALUE_LO = 0x44

#: The bits, each with the header's own access type and default:
#:
#:     SYSTIMER_TIMER_UNIT0_WORK_EN      R/W       [30]    default 1   :90, :93
#:     SYSTIMER_TIMER_UNIT0_UPDATE       WT        [30]    default 0   :116, :119
#:     SYSTIMER_TIMER_UNIT0_VALUE_VALID  R/SS/WTC  [29]    default 0   :109, :112
#:     SYSTIMER_TIMER_UNIT0_VALUE_HI     RO        [19:0]  default 0   :345, :348
#:
#: **The unit counts out of reset**, `WORK_EN` being 1, so a bare-metal image
#: reads time without configuring anything -- the same kind of fact as
#: `UART_TX_SCLK_EN`'s default. `VALUE_HI`'s twenty bits over `VALUE_LO`'s 32
#: make the counter 52 bits wide, which `soc_caps.h:248-249` states as
#: `SOC_SYSTIMER_BIT_WIDTH_LO (32)` and `SOC_SYSTIMER_BIT_WIDTH_HI (20)`.
SYSTIMER_TIMER_UNIT0_WORK_EN = 1 << 30
SYSTIMER_TIMER_UNIT0_UPDATE = 1 << 30
SYSTIMER_TIMER_UNIT0_VALUE_VALID = 1 << 29
SYSTIMER_TIMER_UNIT0_VALUE_HI = 0x000FFFFF

#: `SYSTIMER_CONF_REG` out of reset, composed from every field default
#: `systimer_reg.h:27-97` states rather than from the one bit this model
#: reads: `CLK_FO` [0] 0, `TARGET2..0_WORK_EN` [22..24] 0,
#: `TIMER_UNIT1_CORE1_STALL_EN` [25] 1, `TIMER_UNIT1_CORE0_STALL_EN` [26] 1,
#: `TIMER_UNIT0_CORE1_STALL_EN` [27] 0, `TIMER_UNIT0_CORE0_STALL_EN` [28] 0,
#: `TIMER_UNIT1_WORK_EN` [29] 0, `TIMER_UNIT0_WORK_EN` [30] 1, `CLK_EN` [31] 0.
SYSTIMER_CONF_AT_RESET = (1 << 25) | (1 << 26) | (1 << 30)

#: How fast unit 0 counts: 16 MHz, sixteen ticks a microsecond. **Stated, in
#: this file's own tree**: `soc_caps.h:250`,
#: `SOC_SYSTIMER_FIXED_TICKS_US (16) // Number of ticks per microsecond is
#: fixed`. ESP-IDF v5.5 dropped that define and says the same in prose --
#: `components/esp_hw_support/port/esp32c3/systimer.c:10-11` at 8c750b0,
#: "fixed to XTAL (40MHz), and has a fixed fractional divider (2.5). So the
#: resolution of the systimer is 40MHz/2.5 = 16MHz" -- a file outside the
#: sparse checkout `docs/esp-idf-reference.md` describes, so no test reads
#: it; `tests/riscv32/test_esp32c3_board.py` reads the define.
SYSTIMER_HZ = 16_000_000

#: The clock a sketch on this part runs at: `build.f_cpu=160000000L` for
#: `XIAO_ESP32C3` in arduino-esp32's `boards.txt:37756` @ 2787dab, the
#: checkout the manifest's C3 rows build against -- and PlatformIO's
#: `framework-arduinoespressif32/boards.txt:22087`, whose `XIAO_ESP32C3`
#: variant this board's own recipe includes, says the same. **The board's
#: own Arduino build, not this chip's maximum and not its reset clock**: an
#: Arduino sketch for this board is compiled for and run at that frequency.
#: Every ESP32-C3 row in `tools/board_manifest.py` declares the same, and
#: `test_every_c3_boards_arduino_build_declares_the_clock_the_rate_assumes`
#: holds that, because the rate below is per chip and a row at another clock
#: would be timed wrongly by it.
CPU_HZ = 160_000_000

#: Retired instructions per SYSTIMER tick: `CPU_HZ // SYSTIMER_HZ`, ten.
#:
#: **A judgement, and the same one `webui/boards/rp2040.py`'s
#: `TIMER_INSTRUCTIONS_PER_TICK` makes**: this core has no cycle model, so
#: one retired instruction stands for one cycle at `CPU_HZ`. On silicon a
#: load, a taken branch, a divide or a flash-cache miss takes more than one,
#: so a real C3 retires fewer instructions in a millisecond than the 160,000
#: this counts -- `millis()` here runs fast against a wall clock by however
#: far the program's real CPI is above one. What it does guarantee is what a
#: program reading time needs: virtual time that is monotonic, deterministic
#: and an integer (`rules/determinism.md` §3), at a rate whose every factor
#: is cited.
SYSTIMER_INSTRUCTIONS_PER_TICK = CPU_HZ // SYSTIMER_HZ
# The division above floors without a word, so a clock that is not a whole
# number of ticks would be timed at a rate nobody cited. Refused at import.
if CPU_HZ % SYSTIMER_HZ:
    raise ValueError(
        f"CPU_HZ {CPU_HZ} is not a multiple of SYSTIMER_HZ {SYSTIMER_HZ}: "
        f"SYSTIMER_INSTRUCTIONS_PER_TICK would be {SYSTIMER_INSTRUCTIONS_PER_TICK}, "
        f"rounded down from {CPU_HZ / SYSTIMER_HZ}")

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
    def map_snapshot_counter(self, *, op: int, update_mask: int,
                             valid_mask: int, low: int, high: int,
                             high_mask: int, enable: int, enable_mask: int,
                             instructions_per_tick: int) -> None: ...
    def map_input(self, address: int, *, out: int, enable: int, pad_base: int,
                  pad_stride: int, pads: int, input_enable: int, pull_up: int,
                  pull_down: int) -> None: ...
    def drive_input(self, address: int, *, driven: int, levels: int) -> None: ...
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

    `GPIO_IN` is `install_gpio_in`'s. It was left unmapped here until
    OH-161's step 3, because a stored register reading zero would answer
    wrongly to firmware that drives GPIO8 high and reads it back.
    """
    cpu.map_register(GPIO + GPIO_OUT, 0)
    cpu.map_alias(GPIO + GPIO_OUT_W1TS, GPIO + GPIO_OUT, "set", readable=False)
    cpu.map_alias(GPIO + GPIO_OUT_W1TC, GPIO + GPIO_OUT, "clear", readable=False)

    cpu.map_register(GPIO + GPIO_ENABLE, 0)
    cpu.map_alias(GPIO + GPIO_ENABLE_W1TS, GPIO + GPIO_ENABLE, "set",
                  readable=False)
    cpu.map_alias(GPIO + GPIO_ENABLE_W1TC, GPIO + GPIO_ENABLE, "clear",
                  readable=False)


def install_gpio_in(cpu: Cpu) -> None:
    """`GPIO_IN`, reading the pins, and the IO_MUX pad register it reads them
    through.

    **`IN` reads the electrical level on the pin**, so it is neither a
    stored word nor a mirror of `OUT`. Per pin, `core/riscv32`'s `map_input`
    answers 0 where the pad's `FUN_IE` is clear -- the TRM's 5.4.4, p.163,
    says reading needs "the input via IO MUX" enabled, and ESP-IDF's own
    `gpio_get_level` says what is read without it: "If the pad is not
    configured for input (or input and output) the returned value is always
    0" (`components/esp_driver_gpio/include/driver/gpio.h:146` at v5.5) --
    `OUT` where `ENABLE` drives it, what `drive_pins` says the outside
    drives it to, 1 where only `FUN_PU` is set, and 0 otherwise.

    **That last 0 is a floating pin, and it is a decision, not a
    measurement.** Datasheet v2.4 Table 5-4, p.55, gives no level for an
    input nothing drives: its leakage, `IIH`/`IIL` at most 50 nA, on `CIN`
    of 2 pF can move the node 25 mV a microsecond, so any held level would
    model charge this model does not have. 0 is what `circuit.js` solves an
    undriven node to, and it is not a fault because the read is a word: the
    core cannot tell which bit the program will look at, and GPIO2, 3, 4,
    5, 7, 8 and 10 -- a XIAO ESP32-C3's D0 to D3, D5, D8 and D10 -- come out
    of reset input-enabled and unpulled, so they float until something
    drives them.
    A pull-up reads 1 because `RPU` (typ 45 kohm, the same table) against
    50 nA is a 2.25 mV drop. And a level from the outside beats a pull: the
    bench's drive is taken as stronger than 45 kohm, which is right for a
    rail, a switch or a resistor well under it and wrong for a weak
    resistor fighting the pull -- the Thevenin form that would get that
    right is deferred, as OH-161's step-3 note records.

    Every pad is mapped at `IO_MUX_AT_RESET`, because this core enters an
    image with no ROM in front of it, so the pads are as reset leaves them.
    """
    pads = 0
    for gpio, word in IO_MUX_AT_RESET.items():
        cpu.map_register(IO_MUX + IO_MUX_GPIO0 + gpio * IO_MUX_STRIDE, word)
        pads |= 1 << gpio
    cpu.map_input(
        GPIO + GPIO_IN,
        out=GPIO + GPIO_OUT,
        enable=GPIO + GPIO_ENABLE,
        pad_base=IO_MUX + IO_MUX_GPIO0,
        pad_stride=IO_MUX_STRIDE,
        pads=pads,
        input_enable=IO_MUX_FUN_IE,
        pull_up=IO_MUX_FUN_PU,
        pull_down=IO_MUX_FUN_PD,
    )


def drive_pins(cpu: Cpu, levels: typing.Mapping[int, bool]) -> None:
    """What the outside drives onto the pins: GPIO -> high (True) or low.

    **A whole statement, not a change**: a pin left out is a pin nothing
    drives, and the core forgets the previous call. `webui/api.py`'s
    `BoardSession.drive` is the caller, and the only way a level from
    outside reaches this board. A GPIO this part has no pad for is refused,
    naming it and the pads there are.
    """
    driven = 0
    high = 0
    for gpio, level in levels.items():
        if gpio not in IO_MUX_PADS:
            raise ValueError(
                f"GPIO{gpio} has no pad on an ESP32-C3; its pads are GPIO"
                f"{min(IO_MUX_PADS)} to GPIO{max(IO_MUX_PADS)}")
        driven |= 1 << gpio
        if level:
            high |= 1 << gpio
    cpu.drive_input(GPIO + GPIO_IN, driven=driven, levels=high)


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


def install_systimer(cpu: Cpu) -> None:
    """SYSTIMER unit 0, far enough for a program to read the time and no
    further.

    `CONF` as a register at its composed reset value, and unit 0 as a
    snapshot counter gated on `CONF`'s `TIMER_UNIT0_WORK_EN`: a write of
    `UPDATE` to `UNIT0_OP` copies the count into `VALUE_HI` and `VALUE_LO`
    and sets `VALUE_VALID`, which is ESP-IDF's own read --
    `systimer_hal_get_counter_value` writes the bit, spins on the flag, then
    reads the two halves. The copy is taken the instant UPDATE is written, so
    the spin ends on its first read; on silicon it takes the few clock
    edges the halves need to synchronise.

    **What is deliberately absent, and what it costs.** The LOAD registers,
    so a program cannot set the count; unit 1; the three comparators and
    their interrupts, which need an interrupt controller this core does not
    have -- so ESP-IDF's FreeRTOS tick, an alarm on unit 1, cannot run here,
    and a `millis()` that polls unit 0 can. And `VALUE_VALID`'s `WTC`: the header
    says hardware clears it on a write, and here it is set by the first
    UPDATE and stays set, because each UPDATE refreshes the copy before
    anything can read the flag.
    """
    cpu.map_register(SYSTIMER + SYSTIMER_CONF, SYSTIMER_CONF_AT_RESET)
    cpu.map_snapshot_counter(
        op=SYSTIMER + SYSTIMER_UNIT0_OP,
        update_mask=SYSTIMER_TIMER_UNIT0_UPDATE,
        valid_mask=SYSTIMER_TIMER_UNIT0_VALUE_VALID,
        low=SYSTIMER + SYSTIMER_UNIT0_VALUE_LO,
        high=SYSTIMER + SYSTIMER_UNIT0_VALUE_HI,
        high_mask=SYSTIMER_TIMER_UNIT0_VALUE_HI,
        enable=SYSTIMER + SYSTIMER_CONF,
        enable_mask=SYSTIMER_TIMER_UNIT0_WORK_EN,
        instructions_per_tick=SYSTIMER_INSTRUCTIONS_PER_TICK,
    )


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
    # After `install_gpio`: the input register reads `OUT` and `ENABLE`.
    install_gpio_in(cpu)
    install_uart0(cpu)
    install_systimer(cpu)
