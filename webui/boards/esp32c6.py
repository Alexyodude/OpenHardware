#!/usr/bin/env python3
# OpenHardware - the ESP32-C6 as regions and registers over the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an ESP32-C6 to a `core.riscv32` CPU.

The second RISC-V board, and the one that answers whether `webui/boards/`
scales by *chip* or only by *architecture*. Reading it against
`webui/boards/esp32c3.py` is the fastest way to see the answer: same core,
same file shape, and **one address in common out of six**.

## Where these numbers come from

ESP-IDF v5.5.0 -- commit `8c750b0`, tag `v5.5` -- in a sibling checkout. See
`docs/esp-idf-reference.md` for how to get it and why it is a sibling.

    components/soc/esp32c6/include/soc/soc.h
    components/soc/esp32c6/include/soc/soc_caps.h
    components/soc/esp32c6/include/soc/ext_mem_defs.h
    components/soc/esp32c6/register/soc/reg_base.h
    components/soc/esp32c6/register/soc/gpio_reg.h

Every address below cites the file and line it was read from, which is the
same shape `esp32c3.py` cites its headers and `samd21.py` its CMSIS ones.

**A different tree from the C3's, and that needed licensing rather than
assuming.** `esp32c3.py` reads `framework-arduinoespressif32`, which ships
ESP-IDF 4.4.7 and has no `esp32c6` directory at all -- so this part could not
be described from it. What made IDF v5.5 admissible is that it *reproduces*
the C3: `components/soc/esp32c3/include/soc/soc.h:152-163` gives 0x3C000000,
0x3C800000, 0x42000000, 0x42800000, 0x4037C000, 0x403E0000, 0x3FC80000,
0x3FCE0000, and `register/soc/reg_base.h:23` gives 0x60004000 -- every number
`esp32c3.py` already carries, from the older tree, unchanged.
`test_the_new_header_tree_reproduces_the_board_this_repository_already_had`
keeps that check runnable rather than leaving it as this paragraph.

## Three ways this is not an ESP32-C3

1. **It has atomics, and this core does not execute them.** A C3 is RV32IMC
   and must *trap* `amoor.w`; a C6 is RV32IMAC and must *execute* it. This
   core classifies A and implements none of it, so it answers `Unimplemented`
   here and `Illegal` on a C3 -- two different words for two different facts,
   which is what `ISA` below buys and why it is set before anything else.

2. **SRAM has one address, not two.** `soc.h:162-165` gives `SOC_IRAM_LOW`,
   `SOC_IRAM_HIGH`, `SOC_DRAM_LOW` and `SOC_DRAM_HIGH` as 0x40800000 and
   0x40880000 -- the same numbers, twice. The C3's two views of one array are
   the reason `esp32c3.py` maps its SRAM once and lets the other alias fault;
   here there is no second view, so this board's SRAM is **complete** rather
   than a modelled half.

3. **There is no separate rodata window.** `soc.h:156-157` writes
   `SOC_DROM_LOW  SOC_IROM_LOW` and `SOC_DROM_HIGH SOC_IROM_HIGH`: on this
   part the instruction and data busses share one flash address range, where a
   C3 has 0x3C000000 for data and 0x42000000 for code. So this file maps one
   flash region and `esp32c3.py` maps two, and neither is the other with a
   line deleted.

## What is deliberately absent

Every timer but SYSTIMER's unit 0 (OH-161's step 2, see `install_systimer`),
the ADC, SPI, I2C, the LP core and its LP_SRAM, and the
whole clock and reset subsystem. Same growth rule the other boards keep: a
peripheral is added when a real image faults on it and not before. Here the
rule has teeth -- `core/riscv32/cpu.h` faults on any address no region and no
register covers, so a program that touches an undescribed peripheral stops and
names the address rather than reading zero and hanging.

**The UART is half here since OH-161**: UART0's transmit FIFO and the clock
bit that gates it, which is what a `Serial.print` needs. Its receive half, its
baud divisors and `UART_TXFIFO_CNT` stay unmapped, so firmware that waits for
room in the FIFO faults at a named address rather than spinning on a zero;
`webui/boards/esp32c3.py` carries the argument in full.

**The pins read since OH-161's step 3**: `GPIO_IN` and the IO_MUX pad
register of every GPIO. See `install_gpio_in`.

The mask ROM is not modelled and cannot be, for the reason `esp32c3.py` gives
at length: it is Espressif's, it is not redistributable, and an ESP-IDF
application expects it to have set up the cache, the clock and its own function
table before `app_main` runs. **An ESP-IDF application will not run on this
board.** A bare-metal image linked into the flash window will, and
`tests/riscv32/test_esp32c6_board.py` is the one that watched it.
"""

from __future__ import annotations

import typing

#: The flash execute window's base, `soc.h:154`:
#:
#:     #define SOC_IROM_LOW    0x42000000
#:
#: The one address this part shares with a C3.
IROM = 0x42000000

#: **The top of that window is a build option on this part, not a constant**,
#: and saying so is the whole reason these two names exist instead of a
#: subtraction. `soc.h:155` writes it as a formula rather than a number:
#:
#:     #define SOC_IROM_HIGH   (SOC_IROM_LOW + (SOC_MMU_PAGE_SIZE<<8))
#:
#: `SOC_MMU_PAGE_SIZE` comes from the application's own `CMakeLists.txt`
#: (`components/soc/CMakeLists.txt:187` binds it to `CONFIG_MMU_PAGE_SIZE`),
#: and `soc_caps.h:298-299` records `SOC_MMU_PAGE_SIZE_CONFIGURABLE 1` with
#: 8 KB among the choices. A C3's window is 8 MB whatever anyone configures;
#: this one is 256 pages of whatever size the build picked.
#:
#: 0x10000 is the header's own default, `ext_mem_defs.h:19`, and 256 is
#: `SOC_MMU_ENTRY_NUM`, `ext_mem_defs.h:61` -- which is where the `<<8` above
#: comes from. So the window mapped here is 16 MB, and an image built with an
#: 8 KB page would see a smaller one on silicon than it sees here. That
#: direction is the safe one: this board maps more than the smallest build
#: would, so an address a real part rejects is rejected there rather than
#: silently working here -- but it is a *difference*, and it is written down
#: rather than rounded off.
MMU_PAGE_SIZE = 0x10000
MMU_ENTRY_NUM = 256
IROM_SIZE = MMU_PAGE_SIZE * MMU_ENTRY_NUM

#: Erased flash reads 0xFF. On RV32 both fills are loud -- a word of zeros and
#: a word of ones are *both* illegal encodings -- so a program that runs off
#: the end of its image stops either way.
FLASH_ERASED = 0xFF

#: HP SRAM, `soc.h:162-165`:
#:
#:     #define SOC_IRAM_LOW    0x40800000
#:     #define SOC_IRAM_HIGH   0x40880000
#:     #define SOC_DRAM_LOW    0x40800000
#:     #define SOC_DRAM_HIGH   0x40880000
#:
#: **Four defines, two numbers.** `soc_caps.h:302` says why in one comment --
#: `SOC_MMU_DI_VADDR_SHARED (1) /*!< D/I vaddr are shared */`. This is the
#: single fact that makes this board's memory map complete where the C3's is
#: knowingly partial.
SRAM = 0x40800000
SRAM_SIZE = 0x40880000 - 0x40800000

#: GPIO, `register/soc/reg_base.h:48`:
#:
#:     #define DR_REG_GPIO_BASE                        0x60091000
#:
#: A C3's is 0x60004000. The peripheral bus was renumbered wholesale between
#: these parts; nothing about the C3's map transfers.
GPIO = 0x60091000

#: The registers this board models, from `register/soc/gpio_reg.h`. Offsets
#: rather than absolute addresses, because that is how the header writes them:
#:
#:     #define GPIO_OUT_REG           (DR_REG_GPIO_BASE + 0x4)     :29
#:     #define GPIO_OUT_W1TS_REG      (DR_REG_GPIO_BASE + 0x8)     :41
#:     #define GPIO_OUT_W1TC_REG      (DR_REG_GPIO_BASE + 0xc)     :53
#:     #define GPIO_ENABLE_REG        (DR_REG_GPIO_BASE + 0x20)    :113
#:     #define GPIO_ENABLE_W1TS_REG   (DR_REG_GPIO_BASE + 0x24)    :125
#:     #define GPIO_ENABLE_W1TC_REG   (DR_REG_GPIO_BASE + 0x28)    :137
#:     #define GPIO_IN_REG            (DR_REG_GPIO_BASE + 0x3c)    :197
#:
#: These offsets do match the C3's, and that is worth one sentence rather than
#: none: the *base* moved and the register file did not. It is also not a rule
#: -- `webui/boards/esp32c5.py` documents the same seven registers at
#: different offsets on a part one generation further on, which is why each
#: board reads its own header instead of importing a neighbour's.
GPIO_OUT = 0x04
GPIO_OUT_W1TS = 0x08
GPIO_OUT_W1TC = 0x0C
GPIO_ENABLE = 0x20
GPIO_ENABLE_W1TS = 0x24
GPIO_ENABLE_W1TC = 0x28
GPIO_IN = 0x3C

#: IO_MUX, `register/soc/reg_base.h:47` --
#: `#define DR_REG_IO_MUX_BASE 0x60090000`.
IO_MUX = 0x60090000

#: GPIO0's pad register, `register/soc/io_mux_reg.h:175` --
#: `#define PERIPHS_IO_MUX_XTAL_32K_P_U (REG_IO_MUX_BASE + 0x4)` -- and each
#: next GPIO's four bytes on: C6 TRM v1.2, Register 7.20, `IO_MUX_GPIOn_REG
#: (n: 0-30) (0x0004+4*n)`, p.282. A C3's offset at a C5's base, and a C5's
#: GPIO0 is at + 0x0.
IO_MUX_GPIO0 = 0x04
IO_MUX_STRIDE = 4

#: The pad register's bits this model reads, `register/soc/io_mux_reg.h`:
#:
#:     #define FUN_PD (BIT(7))     :42    pull-down enable
#:     #define FUN_PU (BIT(8))     :47    pull-up enable
#:     #define FUN_IE (BIT(9))     :52    input enable
#:     #define FUN_DRV_S 10        :60    drive strength, [11:10]
IO_MUX_FUN_PD = 1 << 7
IO_MUX_FUN_PU = 1 << 8
IO_MUX_FUN_IE = 1 << 9
IO_MUX_FUN_DRV_SHIFT = 10

#: Every pad this part has, GPIO -> its "DRV" and "Reset" columns in C6 TRM
#: v1.2 Table 7.12-1, "IO MUX Functions List", p.262: GPIO0 to GPIO30, as
#: Register 7.20's `n: 0-30` says.
IO_MUX_PADS: dict[int, tuple[int, str]] = {
    0: (2, "0"), 1: (2, "0"), 2: (2, "1"), 3: (2, "1"), 4: (2, "1"),
    5: (2, "1"), 6: (2, "1*"), 7: (2, "1"), 8: (2, "1"), 9: (2, "3"),
    10: (2, "1"), 11: (2, "1"), 12: (3, "1"), 13: (3, "3"), 14: (2, "1"),
    15: (2, "1"), 16: (2, "4"), 17: (2, "3"), 18: (2, "3"), 19: (2, "3"),
    20: (2, "3"), 21: (2, "3"), 22: (2, "3"), 23: (2, "3"), 24: (2, "3"),
    25: (2, "3"), 26: (2, "3"), 27: (2, "0"), 28: (2, "3"), 29: (2, "3"),
    30: (2, "3"),
}

#: The "Reset" column's codes as pad bits, from the legend under the table,
#: "Reset Configurations", pp.262-263 -- the C3's codes:
#:
#:   0   IE = 0                    4   OE = 1, WPU = 1
#:   1   IE = 1                    1*  MTCK: IE = 1, WPU = 1 while
#:   3   IE = 1, WPU = 1               EFUSE_DIS_PAD_JTAG is 0, its default
#:                                     (datasheet v1.5, note 5 under
#:                                     Table 2-2, p.18)
#:
#: "4"'s OE is UART0's transmitter driving GPIO16 through function 0, and
#: GPIO12's and GPIO13's USB pull-ups are USB_SERIAL_JTAG registers: neither
#: is a bit of the pad register, and this model maps neither.
IO_MUX_RESET_BITS: dict[str, int] = {
    "0": 0,
    "1": IO_MUX_FUN_IE,
    "1*": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "3": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "4": IO_MUX_FUN_PU,
}

#: Each pad register's word out of reset: Register 7.20's reset row, p.282,
#: with its drive strength and its three pad bits replaced by the pad's own
#: two columns. Every other field of that row is 0, `MCU_SEL` among them.
IO_MUX_AT_RESET: dict[int, int] = {
    gpio: (drv << IO_MUX_FUN_DRV_SHIFT) | IO_MUX_RESET_BITS[code]
    for gpio, (drv, code) in IO_MUX_PADS.items()
}

#: UART0's base, `register/soc/reg_base.h:13` -- `#define DR_REG_UART_BASE 0x60000000`. UART0 is the base itself and the only one modelled.
#:
#: **Not because it is where a XIAO's `Serial` goes by default.** On these
#: parts Arduino's default is USB_SERIAL_JTAG; Seeed's own
#: `XIAO_ESP32C6_Pin_Multiplexing.md:65-73` documents the hardware UART as
#: `D6` for TX and `D7` for RX, to an external device. `esp32c3.py` carries
#: the argument in full, including the research file that recorded this in
#: August and that this comment contradicted until the OH-161 review: UART0
#: is modelled because it is the ROM console, not because it is the default
#: `Serial`.
UART0 = 0x60000000

#: The transmit FIFO, `register/soc/uart_reg.h:17` -- `UART_FIFO_REG(i)`
#: at `REG_UART_BASE(i) + 0x0`, data field `UART_RXFIFO_RD_BYTE` `bitpos: [7:0]`
#: (:21).
#:
#: **A queue, not a word.** `core/riscv32` grew `map_stream` for exactly this:
#: a `map_register` here would keep the last byte written, so a program
#: printing `hello` would leave an `o` behind -- a plausible letter rather than
#: a loud absence.
UART_FIFO = 0x00

#: The clock register, `register/soc/uart_reg.h:1477`, and the bit
#: that gates the transmitter: `UART_TX_SCLK_EN` at `BIT(24)` (:1481),
#: `default: 1`.
#:
#: **+ 0x88 here, and + 0x78 on an ESP32-C3.** The same peripheral, the same
#: bit, a different offset -- the same shape of difference this file's GPIO
#: block already carries, and the reason each part reads its own header rather
#: than importing a neighbour's constants.
UART_CLK_CONF = 0x88
UART_TX_SCLK_EN = 1 << 24

#: What that register holds out of reset. This part documents four fields in
#: it -- `TX_SCLK_EN` [24] 1, `RX_SCLK_EN` [25] 1, `TX_RST_CORE` [26] 0,
#: `RX_RST_CORE` [27] 0 -- and no divider fields at all, where an ESP32-C3
#: carries `SCLK_SEL` and three divisors in the same register. The clock
#: source moved to the PCR block on this part, which is why the reset word is
#: two bits rather than the C3's `0x03701000`. **Checked rather than assumed**
#: (OH-161 review): `register/soc/pcr_reg.h:51` puts
#: `PCR_UART0_SCLK_DIV_NUM` at `bitpos: [19:12]` of `PCR_UART0_SCLK_CONF_REG`
#: -- the same field, at the same bit positions, that a C3 carries inside
#: `UART_CLK_CONF_REG` itself.
UART_CLK_CONF_AT_RESET = (1 << 24) | (1 << 25)

#: SYSTIMER's base, `register/soc/reg_base.h:23` --
#: `#define DR_REG_SYSTIMER_BASE 0x6000A000`. A C3's is 0x60023000.
SYSTIMER = 0x6000A000

#: The four registers of it this board models, from
#: `register/soc/systimer_reg.h`:
#:
#:     #define SYSTIMER_CONF_REG            (DR_REG_SYSTIMER_BASE + 0x0)   :17
#:     #define SYSTIMER_UNIT0_OP_REG        (DR_REG_SYSTIMER_BASE + 0x4)   :106
#:     #define SYSTIMER_UNIT0_VALUE_HI_REG  (DR_REG_SYSTIMER_BASE + 0x40)  :342
#:     #define SYSTIMER_UNIT0_VALUE_LO_REG  (DR_REG_SYSTIMER_BASE + 0x44)  :354
#:
#: **The C3's offsets, and here that is a fact rather than a copy**: the
#: block moved and its register file did not, which this file's GPIO block
#: says of GPIO too. Everything else in it is unmapped -- `UNIT0_LOAD_LO`
#: at + 0x10 (:156), `UNIT1_OP` at + 0x8 (:125), the comparators -- so
#: firmware reaching for one faults at a named address.
SYSTIMER_CONF = 0x00
SYSTIMER_UNIT0_OP = 0x04
SYSTIMER_UNIT0_VALUE_HI = 0x40
SYSTIMER_UNIT0_VALUE_LO = 0x44

#: The bits, each with the header's access type and default:
#:
#:     SYSTIMER_TIMER_UNIT0_WORK_EN      R/W       [30]    default 1   :88, :91
#:     SYSTIMER_TIMER_UNIT0_UPDATE       WT        [30]    default 0   :114, :117
#:     SYSTIMER_TIMER_UNIT0_VALUE_VALID  R/SS/WTC  [29]    default 0   :107, :110
#:     SYSTIMER_TIMER_UNIT0_VALUE_HI     RO        [19:0]  default 0   :343, :346
#:
#: The unit counts out of reset. Twenty bits over 32 is a 52-bit counter,
#: `soc_caps.h:444-445`'s `SOC_SYSTIMER_BIT_WIDTH_LO 32` and `_HI 20`.
SYSTIMER_TIMER_UNIT0_WORK_EN = 1 << 30
SYSTIMER_TIMER_UNIT0_UPDATE = 1 << 30
SYSTIMER_TIMER_UNIT0_VALUE_VALID = 1 << 29
SYSTIMER_TIMER_UNIT0_VALUE_HI = 0x000FFFFF

#: `SYSTIMER_CONF_REG` out of reset, from every field default
#: `systimer_reg.h:18-95` states: `CLK_FO` [0] 0, `ETM_EN` [1] 0 -- a field
#: the C3 does not have, and it resets to zero, so the word is the C3's --
#: `TARGET2..0_WORK_EN` [22..24] 0, `TIMER_UNIT1_CORE1_STALL_EN` [25] 1,
#: `TIMER_UNIT1_CORE0_STALL_EN` [26] 1, `TIMER_UNIT0_CORE1_STALL_EN` [27] 0,
#: `TIMER_UNIT0_CORE0_STALL_EN` [28] 0, `TIMER_UNIT1_WORK_EN` [29] 0,
#: `TIMER_UNIT0_WORK_EN` [30] 1, `CLK_EN` [31] 0.
SYSTIMER_CONF_AT_RESET = (1 << 25) | (1 << 26) | (1 << 30)

#: How fast unit 0 counts: 16 MHz. **Arithmetic in this tree and a statement
#: just outside it.** `soc.h:145` gives `XTAL_CLK_FREQ (40*1000000)` and
#: `soc_caps.h:446` `SOC_SYSTIMER_FIXED_DIVIDER 1 // Clock source divider is
#: fixed: 2.5`, and 40 MHz over 2.5 is 16; `tests/riscv32/test_esp32c6_board.py`
#: reads both. ESP-IDF says it in words at
#: `components/esp_hw_support/port/esp32c6/systimer.c:10-11` (8c750b0),
#: "the resolution of the systimer is 40MHz/2.5 = 16MHz", outside the sparse
#: checkout `docs/esp-idf-reference.md` describes.
SYSTIMER_HZ = 16_000_000

#: The clock a sketch on this part runs at: `build.f_cpu=160000000L` for
#: `XIAO_ESP32C6`, arduino-esp32's `boards.txt:38098` @ 2787dab. The board's
#: own Arduino build, for the reason `esp32c3.py` gives at its own `CPU_HZ`,
#: and every ESP32-C6 row in `tools/board_manifest.py` declares the same --
#: `test_every_c6_boards_arduino_build_declares_the_clock_the_rate_assumes`.
CPU_HZ = 160_000_000

#: Retired instructions per SYSTIMER tick, ten: one instruction standing for
#: one cycle at `CPU_HZ`. **A judgement**, the one `esp32c3.py` states in
#: full at its own `SYSTIMER_INSTRUCTIONS_PER_TICK` and `rp2040.py` made
#: first.
SYSTIMER_INSTRUCTIONS_PER_TICK = CPU_HZ // SYSTIMER_HZ
# The division above floors without a word, so a clock that is not a whole
# number of ticks would be timed at a rate nobody cited. Refused at import.
if CPU_HZ % SYSTIMER_HZ:
    raise ValueError(
        f"CPU_HZ {CPU_HZ} is not a multiple of SYSTIMER_HZ {SYSTIMER_HZ}: "
        f"SYSTIMER_INSTRUCTIONS_PER_TICK would be {SYSTIMER_INSTRUCTIONS_PER_TICK}, "
        f"rounded down from {CPU_HZ / SYSTIMER_HZ}")


#: The pin the fixture watches. **Not the board's LED.** GPIO8 is ESP-IDF's
#: own blink default -- `examples/get-started/blink/main/Kconfig.projbuild:34-37`,
#: `default 8` -- and a real output on this part either way; on a XIAO it is
#: not a header pad at all (`D8` is GPIO19 here, see `HEADER`). When this
#: constant was written no Seeed variant file for the C6 was installed and
#: the comment said so; OH-26 fetched one into `third_party/bsp`, and the
#: board's own LED is now `HEADER["LED"]` below, GPIO15, read out of that
#: file by the generator rather than remembered here.
LED_PIN = 8

# --- BEGIN HEADER: generated by `python tools/import_pindefs.py --write-headers`; do not edit by hand ---
#: Header label -> GPIO number: the pin `pin_states` reads a level
#: through and `PIN_NAMES` spells. Read out of the board-support
#: packages, never typed here:
#:     zephyr boards/seeed/xiao_esp32c6/seeed_xiao_connector.dtsi @ 0a2e408
#:     arduino-esp32 variants/XIAO_ESP32C6/pins_arduino.h @ 2787dab
#: for XIAO-ESP32-C6-DIP, XIAO-ESP32-C6-SMD. A row is here only where every
#: package that defines it names the same pin; a row only one package
#: defines is that package's.
#: `MTDI`, `MTDO`, `MTMS`, `MTCK`, `BOOT` are read out of the vendor's own
#: board CAD instead, which is not a board-support package:
#:     seeed-pcb ESP32-C6.kicad_pcb @ sha256:401ef70a8c1f
#: `MTDI`, `MTDO`, `MTMS`, `MTCK`, `BOOT` are pads of XIAO-ESP32-C6-SMD
#: alone; no other file here has a pad for them.
#: `LED` has no pad: it is the board's own LED, which the Arduino variant
#: above defines and the header does not carry.
#: `tests/rules/test_import_pindefs.py` holds this block equal to what the
#: generator emits from the fetched packages.
HEADER: dict[str, int] = {
    "D0": 0,
    "D1": 1,
    "D2": 2,
    "D3": 21,
    "D4": 22,
    "D5": 23,
    "D6": 16,
    "D7": 17,
    "D8": 19,
    "D9": 20,
    "D10": 18,
    "LED": 15,
    "MTDI": 5,
    "MTDO": 7,
    "MTMS": 4,
    "MTCK": 6,
    "BOOT": 9,
}
# --- END HEADER ---

#: The same table read the other way, `D6` -> `GPIO16`, derived from
#: `HEADER` so the two cannot disagree. `esp32c3.py` says why the keys are
#: the vendor's labels and not the silkscreen's compound ones.
PIN_NAMES: dict[str, str] = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}

#: What a pin of this part drives and the levels it reads, for the bench's
#: circuit (OH-161 step 3), read out of ESP32-C6 Series Datasheet v1.5 and
#: the C6 TRM v1.2 on 2026-10-13. **`esp32c3.py`'s `SUPPLY` carries the
#: argument**, and it holds here word for word: the input levels are
#: guarantees, and the two resistances are TYPICAL -- this part's VOH and VOL
#: are measured into no load (Table 5-4 note 2) and its currents are Typ --
#: so `typical` is set and the page says "about" and holds a current through
#: a pin to no rating. The numbers are the C3's because the table's are,
#: line for line, and the TRM's drive strengths are too; what this part does
#: not have is the C3's exception, so every header pad's reset `FUN_DRV` 2 is
#: ~20 mA.
SUPPLY: dict[str, object] = {
    "chip": "ESP32-C6",
    "volts": 3.3,
    "source_ohms": 33.0,
    "sink_ohms": 35.4,
    "typical": True,
    "rated_amps": None,
    "absolute_amps": None,
    "input_high_volts": 2.475,
    "input_low_volts": 0.825,
    "cited": {
        "volts": (
            "every XIAO ESP32-C6 pad map's `3V3_OUT` pad, from Seeed's own "
            "CAD, and the 3.3 V typical of datasheet v1.5 Table 5-2, "
            "`Recommended Operating Conditions`, p.64, for VDDPST1 -- the I/O "
            "supply on every board carrying this part"
        ),
        "source_ohms": (
            "derived: (3.3 - 0.8 * 3.3) / 0.020. Datasheet v1.5 Table 5-4, "
            "`DC Characteristics (3.3 V, 25 C)`, p.65: IOH typ 40 mA at "
            "VDD = 3.3 V, VOH >= 2.64 V, PAD_DRIVER = 3. TRM v1.2 Register "
            "7.20, `IO_MUX_GPIOn_REG`, p.283: FUN_DRV 3 is ~40 mA and 2, every "
            "header pad's reset drive, is ~20 mA. TYPICAL, not a bound"
        ),
        "sink_ohms": (
            "derived: 0.495 / (0.028 / 2), rounded to 0.1 ohm. Same table: "
            "IOL typ 28 mA at VDD = 3.3 V, VOL = 0.495 V, PAD_DRIVER = 3, "
            "halved to FUN_DRV 2 by the same register's ~20 of ~40 mA -- an "
            "assumption, since the TRM gives one strength per field value and "
            "does not say sourcing or sinking. TYPICAL, not a bound"
        ),
        "typical": (
            "Table 5-4 note 2, p.65: `VOH and VOL are measured using "
            "high-impedance load`, so no output voltage is guaranteed at any "
            "current, and IOH and IOL are stated only in the Typ column"
        ),
        "rated_amps": (
            "there is not one. Table 5-4 gives IOH and IOL as typical currents "
            "at a test point, which is not a rating, and no other table states "
            "a per-pin current"
        ),
        "absolute_amps": (
            "there is not one per pin. Table 5-1, `Absolute Maximum Ratings`, "
            "p.64, gives `Cumulative IO output current` 1000 mA -- every pin "
            "together, not one"
        ),
        "input_high_volts": (
            "0.75 * 3.3: Table 5-4, p.65, VIH `High-level input voltage` min "
            "0.75 x VDD"
        ),
        "input_low_volts": (
            "0.25 * 3.3: Table 5-4, p.65, VIL `Low-level input voltage` max "
            "0.25 x VDD"
        ),
    },
}

#: This part's ISA, exactly as `webui/boards/catalogue.py`'s `CHIPS` records
#: it, with `test_the_board_agrees_with_the_catalogue_about_the_isa` pinning
#: the two together.
#:
#: **The A is the letter that distinguishes this part from a C3**, and it is
#: the reason `install` sets this before it maps anything. A core still
#: configured as a C3 refuses `amoor.w` as *illegal* -- a claim that this
#: silicon does not have atomics, which is false. Told it is a C6, the same
#: core answers *unimplemented*, which is a claim about this repository and is
#: true. Two words, two facts, and the wrong one is a wrong answer about a chip.
#:
#: This core executes no atomic either way. That is a gap in the emulator, and
#: it is the honest kind: it stops and names the encoding.
#: `tests/riscv32/test_esp32c6_board.py` asserts both halves.
ISA = "RV32IMAC"


class Cpu(typing.Protocol):
    """What this module needs of a core.

    The same five calls `esp32c3.py` needs, which is the evidence that the
    difference between these two parts is entirely in the numbers.
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
    """The flash window and SRAM. **Two regions, where a C3 needs three.**

    Not a simplification: `soc.h:156-157` makes DROM the same window as IROM
    on this part, and `soc.h:162-165` gives IRAM and DRAM one base and one
    top. A C3 has a separate rodata window at 0x3C000000 and a second view of
    SRAM at 0x4037C000, and `esp32c3.py` maps the first and deliberately drops
    the second because `add_region` cannot express an alias.

    Here there is no alias to drop. Every address a C6 image can name is
    mapped, so a fault out of this board is a fault about the *image* rather
    than about the model -- which is not something `esp32c3.py` can say.

    SRAM is executable because it genuinely is on this part -- the instruction
    bus reaches the same words -- and because an image that copies a function
    into RAM and jumps to it is a normal thing an ESP32 image does.
    """
    cpu.add_region(IROM, IROM_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True, fill=0x00)


def install_gpio(cpu: Cpu) -> None:
    """GPIO_OUT and GPIO_ENABLE, each with its W1TS and W1TC aliases.

    **The W1TS and W1TC registers are write-only and read as zero**, which is
    what the part does and is not this model shrugging. `webui/boards/samd21.py`
    documents the opposite case -- Microchip's header marks the same-shaped
    PORT registers `__IO ... (R/W)` -- so which way round it goes is a per-chip
    fact read from the vendor's own header, never a default.

    `GPIO_IN` is `install_gpio_in`'s.
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
    """`GPIO_IN`, reading the pins, and the IO_MUX pad register of every
    GPIO.

    The C3's `install_gpio_in` carries the argument in full: what each bit
    reads and in what order, why a floating pin reads 0 and is not a fault,
    and why the outside beats a pull. This part's datasheet, v1.5 Table 5-4,
    p.65, states the same `IIH`, `IIL`, `CIN` and 45 kohm `RPU` as the
    C3's. The block is the C3's shape -- GPIO0 at + 0x4 -- at a C5's base,
    with every GPIO a pad.
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

    A whole statement, as the C3's `drive_pins` says. A GPIO this part has
    no pad for is refused, naming it.
    """
    driven = 0
    high = 0
    for gpio, level in levels.items():
        if gpio not in IO_MUX_PADS:
            raise ValueError(
                f"GPIO{gpio} has no pad on an ESP32-C6; its pads are GPIO"
                f"{min(IO_MUX_PADS)} to GPIO{max(IO_MUX_PADS)}")
        driven |= 1 << gpio
        if level:
            high |= 1 << gpio
    cpu.drive_input(GPIO + GPIO_IN, driven=driven, levels=high)


def install_uart0(cpu: Cpu) -> None:
    """UART0, far enough for a `Serial.print` to arrive and no further.

    The FIFO as a stream and the clock register that gates it.
    `webui/boards/esp32c3.py`'s `install_uart0` carries the argument in full,
    including what is deliberately absent: `UART_TXFIFO_CNT` is unmapped, so
    firmware that waits for room in the FIFO faults at a named address instead
    of spinning on a zero, and the baud divisors are unmapped because nothing
    here has a wire or a bit rate.
    """
    cpu.map_register(UART0 + UART_CLK_CONF, UART_CLK_CONF_AT_RESET)
    cpu.map_stream(UART0 + UART_FIFO, enable=UART0 + UART_CLK_CONF,
                   enable_mask=UART_TX_SCLK_EN)


def uart0_output(cpu: Cpu) -> bytes:
    """Every byte this board has transmitted, oldest first.

    The name `webui/api.py`'s `uart_view` finds by `getattr`.
    """
    return cpu.stream(UART0 + UART_FIFO)


def install_systimer(cpu: Cpu) -> None:
    """SYSTIMER unit 0, far enough for a program to read the time.

    `CONF` at its composed reset value, and unit 0 as a snapshot counter
    gated on `TIMER_UNIT0_WORK_EN`: UPDATE copies the count into the two value
    registers and sets VALUE_VALID, ESP-IDF's own read. `esp32c3.py`'s
    `install_systimer` carries the argument in full, including what is
    absent: the LOAD registers, unit 1, and the comparators whose alarms need
    an interrupt this core cannot take.
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

    `"high"`, `"low"` or `"input"` keyed by the label in `HEADER`, `ENABLE`
    deciding before `OUT` does; `esp32c3.py` carries the argument for both
    at its own `pin_states`, and `LED` is here because the vendor's file
    puts the board's LED on GPIO15.

    Each register is read once because each is ONE register on this part:
    `gpio_reg.h:30` gives `GPIO_OUT_DATA_ORIG` as `bitpos: [31:0]` and
    `:114` `GPIO_ENABLE_DATA` the same, so every GPIO this part has is one
    bit of each -- and `tests/webui/test_pin_view.py` holds every `HEADER`
    value under 32 for that reason, which is this part's own width and not a
    shared default: a C3's field is `[25:0]`.
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
    the extension mask together.
    """
    # **The ISA first**, and on this board that ordering is load-bearing in
    # the direction opposite to the C3's. There, the danger was a core still
    # believing it was a C6 and executing an atomic a C3 must trap. Here it is
    # a core still believing it is a C3 and *refusing* an atomic this part
    # has -- calling a real instruction illegal, which is a wrong answer about
    # silicon rather than an admission about the emulator.
    cpu.set_isa(ISA)
    install_memory(cpu)
    install_gpio(cpu)
    # After `install_gpio`: the input register reads `OUT` and `ENABLE`.
    install_gpio_in(cpu)
    install_uart0(cpu)
    install_systimer(cpu)
