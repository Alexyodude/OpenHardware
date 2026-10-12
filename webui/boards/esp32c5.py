#!/usr/bin/env python3
# OpenHardware - the ESP32-C5 as regions and registers, and the part of its
# instruction set this core does not execute.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an ESP32-C5 to a `core.riscv32` CPU, including what it cannot run.

The third RISC-V board and the first one whose part speaks an instruction set
this core is **not** complete for. Everything else here is ordinary --
`webui/boards/esp32c6.py` is the file to read alongside it -- and the ISA
paragraph below is the reason this one exists separately.

## Described, then verified, and the two were separate steps

`webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` records the chips a real
compiled image has been watched executing on. When this file was written the
chip was deliberately not in it: describing a part makes its boards
*runnable*, meaning an image can be attempted, and `rules/board-claims.md`
reserves the stronger word for a named test. That test exists now --
`tests/riscv32/test_esp32c5_board.py` watches `c5blink/blink.bin` toggle a
GPIO register, and OH-156 watched a compiled sketch do the same -- so the
catalogue names it and this paragraph records that the order was describe,
then verify, and not both at once.

## The ISA: two spellings of one set, since OH-146

    ISA        RV32IMAC + Zcb/Zcmp/Zcmt   what the silicon has, as the
                                          datasheet prints it
    EXECUTES   RV32IMAC_ZCB_ZCMP_ZCMT     the same set, in `set_isa`'s
                                          grammar
    ABSENT     ()                         nothing -- kept because two test
                                          files assert the subtraction

This section used to name three groups the core could not represent, and
OH-146 is the core work its own paragraphs said it was waiting on: Zcb,
Zcmp and Zcmt have bits, implementations and refusal sweeps now, so
`install` configures the part whole.

`docs/architectures.md` 4.2 settles which of these is the datasheet's answer
and which is the toolchain's, and it is worth restating because both sources
are in this repository's reach and they disagree:

* The **datasheets** give the C5 Zcb, Zcmp and Zcmt, and `catalogue.CHIPS`
  records that string. That is what the hardware accepts.
* ESP-IDF's own `tools/cmake/toolchain-esp32c5.cmake:10` compiles this part
  with `-march=rv32imac_zicsr_zifencei` -- **no Zc at all**, because
  `ZCMP_WORKAROUND` gates them out of the default build. That is what a stock
  image contains.

Both are true and they answer different questions. The rule that file states is
that an emulator or decoder follows the **datasheet**: accept everything the
hardware accepts, or you trap a legal instruction. So `ISA` above is the
datasheet's string, and this file does not quietly shrink it to the toolchain's
in order to look finished.

`EXECUTES` is what `install` actually hands to `set_isa`. The datasheet's
spelling above is prose -- a plus and slashes -- and `set_isa` speaks
letters and underscore groups, so the two constants remain two: the same
set, once as the datasheet prints it and once as the core is told it.
`set_isa` still **refuses** anything it cannot represent rather than
dropping it, which is what keeps this pair honest.

## What happens when an image uses one of the Zc groups

Since OH-146 it executes, on the C5. The three groups live in compressed
slots base RVC leaves reserved -- Zcb in quadrant 0's `funct3=100` and the
RV64 half of quadrant 1's register group, Zcmp and Zcmt in quadrant 2's
`funct3=101`, the `c.fsdsp` slot no FPU-less part uses -- and
`core/riscv32/exec.cc` gates each on its own bit. On a C3 or a C6 every one
of those encodings is still refused as `Illegal`, which is now the RIGHT
word: those parts genuinely lack the groups, and
`tests/riscv32/test_esp32c5_board.py` sweeps all 4,224 encodings on both
configurations to hold the split. Rows the Zc spec itself reserves refuse
on the C5 too -- `tests/riscv32/test_zc.py` owns that half.

What `Illegal` no longer mislabels is not what put this chip in
`FIRMWARE_VERIFIED`: executing hand-placed encodings is not a compiled image
being watched, and the chip stayed out of that table until
`tests/riscv32/test_esp32c5_board.py` watched `c5blink/blink.bin` -- the
section above says so.

## Where these numbers come from

ESP-IDF v5.5.0 -- commit `8c750b0`, tag `v5.5` -- in a sibling checkout. See
`docs/esp-idf-reference.md`.

    components/soc/esp32c5/include/soc/soc.h
    components/soc/esp32c5/include/soc/soc_caps.h
    components/soc/esp32c5/register/soc/reg_base.h
    components/soc/esp32c5/register/soc/gpio_reg.h

**The GPIO register file is laid out differently from a C3's and a C6's, and
this is the concrete reason this repository does not accept remembered
numbers.** Those two parts put `GPIO_ENABLE_REG` at base + 0x20 and
`GPIO_IN_REG` at base + 0x3c. A C5 puts `GPIO_ENABLE_REG` at + 0x34 and
`GPIO_IN_REG` at + 0x64 -- and + 0x3c, which is `IN` on the older parts, is
`GPIO_ENABLE_W1TC_REG` here. So a C5 board written by copying its neighbour
would map a *write-one-to-clear enable* register at the address it believed was
a read-only input, and firmware disabling an output would appear to be reading
pins. `test_the_c5_register_file_is_not_the_c6_one` pins the collision.

The base is the same as a C6's, 0x60091000, which is exactly what makes the
mistake easy: the number a copy would get wrong is not the one it would check.

## What is deliberately absent

Every timer but SYSTIMER's unit 0 (OH-161's step 2, see `install_systimer`),
all of the ADC but ADC1's one-time sample, SPI, I2C, the LP core and its 16 KB
of LP_SRAM
at 0x50000000, and the whole clock and reset subsystem. Same growth rule the
other boards keep: a peripheral is added when a real image faults on it and not
before, and `core/riscv32/cpu.h` faults on any address no region and no
register covers.

**The UART is half here since OH-161**: UART0's transmit FIFO and the clock
bit that gates it, which is what a `Serial.print` needs. Its receive half, its
baud divisors and `UART_TXFIFO_CNT` stay unmapped, so firmware that waits for
room in the FIFO faults at a named address rather than spinning on a zero;
`webui/boards/esp32c3.py` carries the argument in full.

**The pins read since OH-161's step 3**: `GPIO_IN` and the IO_MUX pad
register of every GPIO that has one, which on this part is not every GPIO.
See `install_gpio_in`.

**ADC1 converts since OH-161's step 4**: its one-time sample, as
`core/riscv32`'s sampler, gated on a clock that resets OFF on this part and
on on a C6. What voltage the outside holds a pin at arrives only through
`hold_volts`, and the code is the TRM's formula's, typical and
uncalibrated. See `install_adc`.

The mask ROM is not modelled and cannot be. **An ESP-IDF application will not
run on this board**, for the reason `esp32c6.py` gives at length.
"""

from __future__ import annotations

import math
import typing

#: The flash execute window, `soc.h:148-149`:
#:
#:     #define SOC_IROM_LOW    0x42000000
#:     #define SOC_IROM_HIGH   0x44000000
#:
#: 32 MB, and written as literals on this part where a C6's top is a formula
#: over a configurable page size. `ext_mem_defs.h:68` gives `SOC_MMU_ENTRY_NUM`
#: 512 against the C6's 256, which is where the doubled window comes from, and
#: `soc_caps.h` carries no `SOC_MMU_PAGE_SIZE_CONFIGURABLE` for this part. So
#: this is a chip constant and `esp32c6.py`'s is a build option, which is why
#: that file spells its size as a multiplication and this one does not.
IROM = 0x42000000
IROM_SIZE = 0x44000000 - 0x42000000

#: Erased flash reads 0xFF. On RV32 both fills are loud -- a word of zeros and
#: a word of ones are *both* illegal encodings.
FLASH_ERASED = 0xFF

#: HP SRAM, `soc.h:158-161`:
#:
#:     #define SOC_IRAM_LOW    0x40800000
#:     #define SOC_IRAM_HIGH   0x40860000
#:     #define SOC_DRAM_LOW    0x40800000
#:     #define SOC_DRAM_HIGH   0x40860000
#:
#: One address for both busses, `soc_caps.h:325`'s `SOC_MMU_DI_VADDR_SHARED`,
#: the same as a C6 and unlike a C3. 384 KB, which is the C6's 512 less a
#: quarter -- the base matches and the size does not.
SRAM = 0x40800000
SRAM_SIZE = 0x40860000 - 0x40800000

#: GPIO, `register/soc/reg_base.h:62`:
#:
#:     #define DR_REG_GPIO_BASE                          0x60091000
#:
#: The same base as a C6. See the module docstring on why that is the
#: dangerous half rather than the reassuring one.
GPIO = 0x60091000

#: The registers this board models, from `register/soc/gpio_reg.h`. Offsets
#: rather than absolute addresses, because that is how the header writes them:
#:
#:     #define GPIO_OUT_REG           (DR_REG_GPIO_BASE + 0x4)     :38
#:     #define GPIO_OUT_W1TS_REG      (DR_REG_GPIO_BASE + 0x8)     :54
#:     #define GPIO_OUT_W1TC_REG      (DR_REG_GPIO_BASE + 0xc)     :70
#:     #define GPIO_ENABLE_REG        (DR_REG_GPIO_BASE + 0x34)    :137
#:     #define GPIO_ENABLE_W1TS_REG   (DR_REG_GPIO_BASE + 0x38)    :152
#:     #define GPIO_ENABLE_W1TC_REG   (DR_REG_GPIO_BASE + 0x3c)    :169
#:     #define GPIO_IN_REG            (DR_REG_GPIO_BASE + 0x64)    :235
#:
#: The `OUT` trio matches a C6's and the `ENABLE` trio and `IN` do not.
GPIO_OUT = 0x04
GPIO_OUT_W1TS = 0x08
GPIO_OUT_W1TC = 0x0C
GPIO_ENABLE = 0x34
GPIO_ENABLE_W1TS = 0x38
GPIO_ENABLE_W1TC = 0x3C
GPIO_IN = 0x64

#: IO_MUX, `register/soc/reg_base.h:61` --
#: `#define DR_REG_IO_MUX_BASE 0x60090000`, a C6's base too.
IO_MUX = 0x60090000

#: GPIO0's pad register, `register/soc/io_mux_reg.h:155` --
#: `#define PERIPHS_IO_MUX_U_PAD_XTAL_32K_P (REG_IO_MUX_BASE + 0x0)` -- and
#: each next GPIO's four bytes on: C5 TRM v1.1, Register 8.25,
#: `IO_MUX_GPIOn_REG (n: 0-14, 23-28) (0x0000+0x4*n)`, p.352. **+ 0x0, where
#: a C3's and a C6's GPIO0 is at + 0x4**, so a board copied from either would
#: read every pin's pulls out of its neighbour's register.
IO_MUX_GPIO0 = 0x00
IO_MUX_STRIDE = 4

#: The pad register's bits this model reads, `register/soc/io_mux_reg.h`:
#:
#:     #define FUN_PD (BIT(7))     :46    pull-down enable
#:     #define FUN_PU (BIT(8))     :51    pull-up enable
#:     #define FUN_IE (BIT(9))     :56    input enable
#:     #define FUN_DRV_S 10        :64    drive strength, [11:10]
#:     #define MCU_SEL_S 12        :69    function select, [14:12]
#:
#: `io_mux_struct.h` calls the first two `fun_wpd` and `fun_wpu`.
IO_MUX_FUN_PD = 1 << 7
IO_MUX_FUN_PU = 1 << 8
IO_MUX_FUN_IE = 1 << 9
IO_MUX_FUN_DRV_SHIFT = 10
IO_MUX_MCU_SEL_SHIFT = 12

#: Every pad this model gives a register, GPIO -> its "DRV" and "Reset"
#: columns in C5 TRM v1.1 Table 8.13-1, "HP IO MUX Pin Functions",
#: pp.322-323. **GPIO15 to GPIO22 are not in that table**, and Register
#: 8.25's `n: 0-14, 23-28` leaves them out too. They are the SPI flash pads:
#: `io_mux_reg.h:113-120` names their registers at + 0x3C to + 0x58, and the
#: datasheet's Table 2-1 note 6, p.21, says some variants do not connect
#: them. With no reset configuration stated for any of them, this model maps
#: none: a write to one faults naming its address, and their `GPIO_IN` bits
#: read 0. No board here names one of them as a pin.
IO_MUX_PADS: dict[int, tuple[int, str]] = {
    0: (2, "0"), 1: (2, "0"), 2: (2, "1"), 3: (2, "1"), 4: (2, "1*"),
    5: (2, "1"), 6: (2, "0"), 7: (2, "1"), 8: (2, "0"), 9: (2, "0"),
    10: (2, "0"), 11: (2, "4"), 12: (2, "1"), 13: (3, "1"), 14: (3, "3*"),
    23: (2, "0"), 24: (2, "0"), 25: (2, "1"), 26: (2, "1"), 27: (2, "3"),
    28: (2, "3"),
}

#: The "Reset" column's codes as pad bits, from the legend under the table,
#: "Reset", p.323. **Not the C3's legend**: this part's "4" is IE = 1, OE = 1
#: where a C3's is OE = 1, WPU = 1.
#:
#:   0   IE = 0                    3*  IE = 1, WPU = 0, and GPIO14's USB
#:   1   IE = 1                        pull-up is on, which is a USB_SERIAL_JTAG
#:   3   IE = 1, WPU = 1               register this model does not map
#:   4   IE = 1, OE = 1            1*  MTCK: IE = 1, WPU = 1 while
#:                                     EFUSE_DIS_PAD_JTAG is 0, its default
#:                                     (datasheet v1.5 Table 2-1 note 5, p.21)
#:
#: "4"'s OE is UART0's transmitter driving GPIO11 through function 0, not a
#: bit of the pad register, and this model routes no peripheral to a pad.
#:
#: **Two pins where this model and the silicon read differently out of
#: reset, both because of that**, and both held as they are by
#: `test_each_pad_comes_out_of_reset_as_its_row_of_the_table_says`, which
#: expects each to read 0. GPIO11 ("4", a XIAO ESP32-C5's D6) has its input
#: on and UART0's idle-high transmitter on it, so silicon reads 1 and this
#: model, with no pull of the pad's own, floats it to 0. GPIO14 ("3*") has
#: its input on and USB_SERIAL_JTAG's pull-up on it, so silicon reads 1 and
#: this model, which maps no USB register, floats it to 0. After a
#: `pinMode`, this model reads either pin as the pad bits `pinMode` set and
#: whatever `drive_pins` says; whether silicon still sees the peripheral
#: there is not modelled, and this core's `pinMode` leaves `MCU_SEL` alone
#: (wiring.c says why).
IO_MUX_RESET_BITS: dict[str, int] = {
    "0": 0,
    "1": IO_MUX_FUN_IE,
    "1*": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "3": IO_MUX_FUN_IE | IO_MUX_FUN_PU,
    "3*": IO_MUX_FUN_IE,
    "4": IO_MUX_FUN_IE,
}

#: Register 8.25's reset row, p.352, which `io_mux_struct.h`'s field
#: defaults restate: `mcu_sel` 1, `fun_drv` 2, every other field 0. **Not a
#: C3's or a C6's row**, whose `MCU_SEL` is 0 and whose `FUN_IE` and
#: `FUN_WPU` are 1.
IO_MUX_RESET_ROW = (1 << IO_MUX_MCU_SEL_SHIFT) | (2 << IO_MUX_FUN_DRV_SHIFT)

#: Each pad register's word out of reset: the reset row with its drive
#: strength and its three pad bits replaced by the pad's own two columns.
IO_MUX_AT_RESET: dict[int, int] = {
    gpio: ((IO_MUX_RESET_ROW & ~(0b11 << IO_MUX_FUN_DRV_SHIFT))
           | (drv << IO_MUX_FUN_DRV_SHIFT) | IO_MUX_RESET_BITS[code])
    for gpio, (drv, code) in IO_MUX_PADS.items()
}

#: The current each `FUN_DRV` value drives, in amps: the "Drive Strength"
#: legend under Table 8.13-1, p.324, 5 mA to 40 mA for 0 to 3, with no pad
#: excepted -- the C3's legend swaps 1 and 2 on six pads and this one does
#: not -- and Register 8.25, p.353, the same.
FUN_DRV_AMPS: dict[int, float] = {0: 0.005, 1: 0.010, 2: 0.020, 3: 0.040}

#: Each pad's current at the drive it comes out of reset with, its
#: `IO_MUX_PADS` "DRV" column read through the legend: ~20 mA but for GPIO13
#: and 14, the USB pads, at ~40 mA. `SUPPLY` takes its resistances from these.
RESET_DRIVE_AMPS: dict[int, float] = {
    gpio: FUN_DRV_AMPS[drv] for gpio, (drv, _code) in IO_MUX_PADS.items()
}

#: UART0's base, `register/soc/reg_base.h:13` -- `#define DR_REG_UART0_BASE 0x60000000`. UART0 is the base itself and the only one modelled.
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
#: (:22).
#:
#: **A queue, not a word.** `core/riscv32` grew `map_stream` for exactly this:
#: a `map_register` here would keep the last byte written, so a program
#: printing `hello` would leave an `o` behind -- a plausible letter rather than
#: a loud absence.
UART_FIFO = 0x00

#: The clock register, `register/soc/uart_reg.h:1548`, and the bit
#: that gates the transmitter: `UART_TX_SCLK_EN` at `BIT(24)` (:1554),
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
#: (OH-161 review): `register/soc/pcr_reg.h:58` puts
#: `PCR_UART0_SCLK_DIV_NUM` at `bitpos: [19:12]` of `PCR_UART0_SCLK_CONF_REG`
#: -- the same field, at the same bit positions, that a C3 carries inside
#: `UART_CLK_CONF_REG` itself.
UART_CLK_CONF_AT_RESET = (1 << 24) | (1 << 25)

#: SYSTIMER's base, `register/soc/reg_base.h:23` --
#: `#define DR_REG_SYSTIMER_BASE 0x6000A000`, a C6's base and not a C3's.
SYSTIMER = 0x6000A000

#: The four registers of it this board models, from
#: `register/soc/systimer_reg.h`:
#:
#:     #define SYSTIMER_CONF_REG            (DR_REG_SYSTIMER_BASE + 0x0)   :17
#:     #define SYSTIMER_UNIT0_OP_REG        (DR_REG_SYSTIMER_BASE + 0x4)   :121
#:     #define SYSTIMER_UNIT0_VALUE_HI_REG  (DR_REG_SYSTIMER_BASE + 0x40)  :370
#:     #define SYSTIMER_UNIT0_VALUE_LO_REG  (DR_REG_SYSTIMER_BASE + 0x44)  :382
#:
#: The same offsets as a C6's, read from this part's own header -- which is
#: the lesson of this file's GPIO block, where the base matched and the
#: offsets did not. Everything else is unmapped: `UNIT0_LOAD_LO` at + 0x10
#: (:177), `UNIT1_OP` at + 0x8 (:143), the comparators.
SYSTIMER_CONF = 0x00
SYSTIMER_UNIT0_OP = 0x04
SYSTIMER_UNIT0_VALUE_HI = 0x40
SYSTIMER_UNIT0_VALUE_LO = 0x44

#: The bits, each with the header's access type and default:
#:
#:     SYSTIMER_TIMER_UNIT0_WORK_EN      R/W       [30]    default 1   :99, :104
#:     SYSTIMER_TIMER_UNIT0_UPDATE       WT        [30]    default 0   :129, :135
#:     SYSTIMER_TIMER_UNIT0_VALUE_VALID  R/SS/WTC  [29]    default 0   :122, :125
#:     SYSTIMER_TIMER_UNIT0_VALUE_HI     RO        [19:0]  default 0   :371, :374
#:
#: The unit counts out of reset. Twenty bits over 32 is a 52-bit counter,
#: `soc_caps.h:491-492`'s `SOC_SYSTIMER_BIT_WIDTH_LO 32` and `_HI 20`.
SYSTIMER_TIMER_UNIT0_WORK_EN = 1 << 30
SYSTIMER_TIMER_UNIT0_UPDATE = 1 << 30
SYSTIMER_TIMER_UNIT0_VALUE_VALID = 1 << 29
SYSTIMER_TIMER_UNIT0_VALUE_HI = 0x000FFFFF

#: `SYSTIMER_CONF_REG` out of reset, from every field default
#: `systimer_reg.h:18-108` states: `CLK_FO` [0] 0, `ETM_EN` [1] 0,
#: `TARGET2..0_WORK_EN` [22..24] 0, `TIMER_UNIT1_CORE1_STALL_EN` [25] 1,
#: `TIMER_UNIT1_CORE0_STALL_EN` [26] 1, `TIMER_UNIT0_CORE1_STALL_EN` [27] 0,
#: `TIMER_UNIT0_CORE0_STALL_EN` [28] 0, `TIMER_UNIT1_WORK_EN` [29] 0,
#: `TIMER_UNIT0_WORK_EN` [30] 1, `CLK_EN` [31] 0.
SYSTIMER_CONF_AT_RESET = (1 << 25) | (1 << 26) | (1 << 30)

#: How fast unit 0 counts: 16 MHz -- **and the arithmetic the C3 and C6 do
#: gives the wrong answer here**, which is why this one cites a sentence
#: rather than a sum. `soc_caps.h:493` still reads
#: `SOC_SYSTIMER_FIXED_DIVIDER 1 // Clock source divider is fixed: 2.5`, and
#: the XIAO ESP32-C5 carries a 48 MHz crystal -- Seeed's own board file,
#: `third_party/seeed-pcb/ESP32-C5.kicad_pcb:7943`, crystal `X1`, value
#: `48Mhz`, and
#: `include/soc/clk_tree_defs.h:22` names "External 48MHz Crystal Clock" for
#: the part -- so 48 over 2.5 would say 19.2 MHz. ESP-IDF says otherwise in
#: `components/esp_hw_support/port/esp32c5/systimer.c:12-13` at 8c750b0:
#: "the fixed fractional divider is changed according to EFUSE_XTAL_48M_SEL.
#: No matter 48MHz or 40MHz XTAL, the resolution of the systimer is always
#: 16MHz", and `systimer_ticks_to_us` is `ticks / 16` (:18). That file is
#: outside the sparse checkout `docs/esp-idf-reference.md` describes, so no
#: test reads it; `test_the_c5_divider_comment_would_time_this_board_wrongly`
#: holds the two facts that make the comment the wrong source.
SYSTIMER_HZ = 16_000_000

#: The clock a sketch on this part runs at: `build.f_cpu=240000000L` for
#: `XIAO_ESP32C5`, arduino-esp32's `boards.txt:37911` @ 2787dab -- half again
#: a C3's or a C6's. The board's own Arduino build, for the reason
#: `esp32c3.py` gives at its own `CPU_HZ`; every ESP32-C5 row in
#: `tools/board_manifest.py` declares the same, and
#: `test_every_c5_boards_arduino_build_declares_the_clock_the_rate_assumes`
#: holds that.
CPU_HZ = 240_000_000

#: Retired instructions per SYSTIMER tick, fifteen: one instruction standing
#: for one cycle at `CPU_HZ`. **A judgement**, stated in full at
#: `esp32c3.py`'s `SYSTIMER_INSTRUCTIONS_PER_TICK`; what differs here is only
#: the clock, so a millisecond is 240,000 retired instructions where a C3's
#: is 160,000.
SYSTIMER_INSTRUCTIONS_PER_TICK = CPU_HZ // SYSTIMER_HZ
# The division above floors without a word, so a clock that is not a whole
# number of ticks would be timed at a rate nobody cited. Refused at import.
if CPU_HZ % SYSTIMER_HZ:
    raise ValueError(
        f"CPU_HZ {CPU_HZ} is not a multiple of SYSTIMER_HZ {SYSTIMER_HZ}: "
        f"SYSTIMER_INSTRUCTIONS_PER_TICK would be {SYSTIMER_INSTRUCTIONS_PER_TICK}, "
        f"rounded down from {CPU_HZ / SYSTIMER_HZ}")


#: The SAR ADC's digital controller, `reg_base.h:27` --
#: `#define DR_REG_APB_SARADC_BASE 0x6000E000`, the C6's base too.
APB_SARADC = 0x6000E000

#: The five registers of it this board models (OH-161 step 4), from v5.5's
#: `register/soc/apb_saradc_reg.h`, as offsets: the C3's and the C6's, here
#: at the C6's base.
#:
#:     #define APB_SARADC_CTRL_REG            (DR_REG_APB_SARADC_BASE + 0x0)   :17
#:     #define APB_SARADC_ONETIME_SAMPLE_REG  (DR_REG_APB_SARADC_BASE + 0x20)  :225
#:     #define APB_SARADC_SAR1DATA_STATUS_REG (DR_REG_APB_SARADC_BASE + 0x2c)  :352
#:     #define APB_SARADC_INT_RAW_REG         (DR_REG_APB_SARADC_BASE + 0x44)  :508
#:     #define APB_SARADC_INT_CLR_REG         (DR_REG_APB_SARADC_BASE + 0x4c)  :616
#:
#: The one-time path the TRM's own procedure names (v1.1 46.8.1, p.1716)
#: and nothing more; every other register in the block is unmapped.
APB_SARADC_CTRL = 0x00
APB_SARADC_ONETIME_SAMPLE = 0x20
APB_SARADC_SAR1_DATA = 0x2C
APB_SARADC_INT_RAW = 0x44
APB_SARADC_INT_CLR = 0x4C

#: The bits, each with the header's own access type and default:
#:
#:     APB_SARADC_SARADC_SAR_CLK_GATED      R/W        [6]      default 1   :32
#:     APB_SARADC_SARADC1_ONETIME_SAMPLE    R/W        [31]     default 0   :254
#:     APB_SARADC_SARADC2_ONETIME_SAMPLE    R/W        [30]     default 0   :247
#:     APB_SARADC_SARADC_ONETIME_START      R/W        [29]     default 0   :240
#:     APB_SARADC_SARADC_ONETIME_CHANNEL    R/W        [28:25]  default 13  :233
#:     APB_SARADC_SARADC_ONETIME_ATTEN      R/W        [24:23]  default 0   :226
#:     APB_SARADC_APB_SARADC1_DATA          RO         [16:0]   default 0   :353
#:     APB_SARADC_APB_SARADC1_DONE_INT_RAW  R/WTC/SS   [31]     default 0   :551
#:     APB_SARADC_APB_SARADC1_DONE_INT_CLR  WT         [31]     default 0   :659
APB_SARADC_SAR_CLK_GATED = 1 << 6
ONETIME_SAR1 = 1 << 31
ONETIME_SAR2 = 1 << 30
ONETIME_START = 1 << 29
ONETIME_CHANNEL_SHIFT = 25
ONETIME_ATTEN_SHIFT = 23
ADC1_DONE = 1 << 31

#: The bits of `ONETIME_SAMPLE` that choose what a start converts: both
#: unit-select bits, the channel and the attenuation.
ONETIME_CONVERSION = (ONETIME_SAR1 | ONETIME_SAR2 | (0xF << ONETIME_CHANNEL_SHIFT)
                      | (0x3 << ONETIME_ATTEN_SHIFT))

#: PCR, `reg_base.h:67` -- `#define DR_REG_PCR_BASE 0x60096000` -- and the
#: ADC's two clock registers in it, `register/soc/pcr_reg.h`:
#:
#:     #define PCR_SARADC_CONF_REG       (DR_REG_PCR_BASE + 0x88)  :987
#:         PCR_SARADC_REG_CLK_EN   R/W  [2]   default 0             :1002
#:     #define PCR_SARADC_CLKM_CONF_REG  (DR_REG_PCR_BASE + 0x8c)  :1020
#:         PCR_SARADC_CLKM_EN      R/W  [22]  default 0             :1052
#:
#: **+ 0x88 and + 0x8c here and + 0x80 and + 0x84 on a C6**, and both bits
#: reset to 0 here and to 1 there.
PCR = 0x60096000
PCR_SARADC_CONF = 0x88
PCR_SARADC_CLKM_CONF = 0x8C
PCR_SARADC_REG_CLK_EN = 1 << 2
PCR_SARADC_CLKM_EN = 1 << 22

#: The register and the bit that gate a conversion on this part: PCR's
#: `SARADC_CLKM_EN`, the SAR ADC's function clock, which the TRM's
#: procedure sets in its step 4 (v1.1 46.8.1, p.1716) and ESP-IDF in
#: `adc_ll_enable_func_clock` (v5.5 `hal/esp32c5/include/hal/adc_ll.h`).
#: **It resets to 0**, so a bare-metal image converts nothing until it sets
#: it, and a C5 described by copying a C6, whose resets to 1 at + 0x84,
#: would convert with its clock off. `SAR_CLK_GATED` in `CTRL` resets to 1
#: and is mapped and not checked; so is `PCR_SARADC_REG_CLK_EN`, the
#: register clock, which also resets to 0: on silicon a write with it clear
#: does not land, and here it does. `analogRead` sets both PCR bits.
ADC_GATE = (PCR + PCR_SARADC_CLKM_CONF, PCR_SARADC_CLKM_EN)

#: `APB_SARADC_CTRL_REG` out of reset, composed from every field default
#: `apb_saradc_reg.h:18-80` states: `START_FORCE` [0] 0, `START` [1] 0,
#: `SAR_CLK_GATED` [6] 1, `SAR_CLK_DIV` [14:7] 4, `SAR_PATT_LEN` [17:15] 7,
#: `SAR_PATT_P_CLEAR` [23] 0, `XPD_SAR_FORCE` [28:27] 0, `SARADC2_PWDET_DRV`
#: [29] 0, `WAIT_ARB_CYCLE` [31:30] 1.
APB_SARADC_CTRL_AT_RESET = (1 << 30) | (7 << 15) | (4 << 7) | (1 << 6)

#: `ONETIME_SAMPLE_REG` out of reset: `ONETIME_CHANNEL` 13, every other
#: field 0 (:226-260). Channel 13 is no channel of this part's.
ONETIME_SAMPLE_AT_RESET = 13 << ONETIME_CHANNEL_SHIFT

#: The two PCR registers out of reset, every field `pcr_reg.h:988-1058`
#: states: `SARADC_CONF` -- `CLK_EN` [0] 1, `RST_EN` [1] 0, `REG_CLK_EN` [2]
#: 0, `REG_RST_EN` [3] 0; `SARADC_CLKM_CONF` -- `DIV_A` [5:0] 0, `DIV_B`
#: [11:6] 0, `DIV_NUM` [19:12] 4, `SEL` [21:20] 0, `EN` [22] 0.
PCR_SARADC_CONF_AT_RESET = 1 << 0
PCR_SARADC_CLKM_CONF_AT_RESET = 4 << 12

#: ADC1's channels, GPIO -> channel: GPIO1 to GPIO6 are channels 0 to 5,
#: TRM v1.1 Table 46.5-1, p.1709, and v5.5 `include/soc/adc_channel.h:10-25`.
#: **A channel is not its GPIO here**, as it is on a C3 and a C6: a XIAO
#: ESP32-C5's A0 is GPIO1, channel 0. The part has one ADC (`soc_caps.h:114`,
#: `SOC_ADC_PERIPH_NUM (1U)`), so no ADC2 key is held.
ADC1_CHANNELS: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}

#: The conversion, in the TRM's own words (v1.1 46.5.6, pp.1710-1711): "The
#: SAR ADC can measure analog voltages from 0 mV to Vref. Vref is the SAR
#: ADC's internal reference voltage (1100 mV by design)", and
#: `Vdata = Vref / k * data / 4095`, k 100%, 75%, 50% and 25% at 0, 2.5, 6
#: and 12 dB, which `ONETIME_ATTEN` spells 0 to 3 -- ESP-IDF's `adc_atten_t`
#: (`components/hal/include/hal/adc_types.h:47-50` at v5.5), which
#: `adc_oneshot_ll_set_atten` writes into the field as it is.
ADC_VREF_VOLTS = 1.1
ADC_ATTEN_K: dict[int, float] = {0: 1.0, 1: 0.75, 2: 0.5, 3: 0.25}
ADC_FULL_CODE = 4095

#: The pin the fixture watches. **Not the board's LED**: GPIO8 is ESP-IDF's
#: own blink default, `examples/get-started/blink/main/Kconfig.projbuild:34-37`,
#: and on a XIAO it is the pad silkscreened `D8`. The board's own LED is
#: `HEADER["LED"]` below, GPIO27, read out of Seeed's variant file by the
#: generator rather than remembered here. The fixture watches GPIO8 because
#: `c5blink/blink.bin` drives it, and a fixture pin need not be the LED.
LED_PIN = 8

# --- BEGIN HEADER: generated by `python tools/import_pindefs.py --write-headers`; do not edit by hand ---
#: Header label -> GPIO number: the pin `pin_states` reads a level
#: through and `PIN_NAMES` spells. Read out of the board-support
#: packages, never typed here:
#:     zephyr boards/seeed/xiao_esp32c5/seeed_xiao_connector.dtsi @ 0a2e408
#:     arduino-esp32 variants/XIAO_ESP32C5/pins_arduino.h @ 2787dab
#: for XIAO-ESP32-C5-DIP, XIAO-ESP32-C5-SMD. A row is here only where every
#: package that defines it names the same pin; a row only one package
#: defines is that package's.
#: `MTDI`, `MTDO`, `MTMS`, `MTCK`, `BOOT` are read out of the vendor's own
#: board CAD instead, which is not a board-support package:
#:     seeed-pcb ESP32-C5.kicad_pcb @ sha256:e06eeb887f0d
#: `MTDI`, `MTDO`, `MTMS`, `MTCK`, `BOOT` are pads of XIAO-ESP32-C5-SMD
#: alone; no other file here has a pad for them.
#: `LED` has no pad: it is the board's own LED, which the Arduino variant
#: above defines and the header does not carry.
#: `tests/rules/test_import_pindefs.py` holds this block equal to what the
#: generator emits from the fetched packages.
HEADER: dict[str, int] = {
    "D0": 1,
    "D1": 0,
    "D2": 25,
    "D3": 7,
    "D4": 23,
    "D5": 24,
    "D6": 11,
    "D7": 12,
    "D8": 8,
    "D9": 9,
    "D10": 10,
    "LED": 27,
    "MTDI": 3,
    "MTDO": 5,
    "MTMS": 2,
    "MTCK": 4,
    "BOOT": 28,
}
# --- END HEADER ---

#: The same table read the other way, `D6` -> `GPIO11`, derived from
#: `HEADER` so the two cannot disagree. `esp32c3.py` says why the keys are
#: the vendor's labels and not the silkscreen's compound ones.
PIN_NAMES: dict[str, str] = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}

#: What a pin of this part drives and the levels it reads, for the bench's
#: circuit (OH-161 step 3), read out of ESP32-C5 Series Datasheet v1.5 and
#: the C5 TRM v1.1 on 2026-10-13. **`esp32c3.py`'s `SUPPLY` carries the
#: argument**, and it holds here word for word: the input levels are
#: guarantees, and the two resistances are TYPICAL -- this part's VOH and VOL
#: are measured into no load (Table 5-4 note 2) and its currents are Typ --
#: so `typical` is set and the page says "about", rests no verdict on a
#: current through a pin, and says a limit it passes is typically passed.
#: The numbers are the C3's because the table's are,
#: line for line, and so is the arithmetic from each pad's reset current,
#: `RESET_DRIVE_AMPS`: `source_ohms` and `sink_ohms` are the ~20 mA pads',
#: and `pad_ohms` the two that reset at ~40 mA. What this part does not have
#: is the C3's ~10 mA pads.
SUPPLY: dict[str, object] = {
    "chip": "ESP32-C5",
    "volts": 3.3,
    "source_ohms": 33.0,
    "sink_ohms": 35.4,
    "pad_ohms": {
        gpio: (round(0.66 / amps, 1), round(0.495 / (0.028 * amps / 0.040), 1))
        for gpio, amps in RESET_DRIVE_AMPS.items() if amps != 0.020
    },
    "typical": True,
    "rated_amps": None,
    "absolute_amps": None,
    "input_high_volts": 2.475,
    "input_low_volts": 0.825,
    "cited": {
        "volts": (
            "every XIAO ESP32-C5 pad map's `3V3_OUT` pad, from Seeed's own "
            "CAD, and the 3.3 V typical of datasheet v1.5 Table 5-2, "
            "`Recommended Power Characteristics`, p.70, for VDDPST1 and "
            "VDDPST3 -- the I/O supply on every board carrying this part"
        ),
        "source_ohms": (
            "derived: (3.3 - 0.8 * 3.3) / 0.020, for a pad that resets at "
            "~20 mA. Datasheet v1.5 Table 5-4, `DC Characteristics (3.3 V, "
            "25 C)`, p.71: IOH typ 40 mA at VDD = 3.3 V, VOH >= 2.64 V, "
            "PAD_DRIVER = 3. TRM v1.1 Register 8.25, `IO_MUX_GPIOn_REG`, "
            "p.353: FUN_DRV 3 is ~40 mA and 2 is ~20 mA -- as v5.5's "
            "`io_mux_struct.h:75-80` also states. TYPICAL, not a bound"
        ),
        "pad_ohms": (
            "source_ohms' and sink_ohms' arithmetic at each other pad's own "
            "reset current, `RESET_DRIVE_AMPS`: ~40 mA on GPIO13 and 14 "
            "(16.5 and 17.7 ohm). TYPICAL, not a bound"
        ),
        "sink_ohms": (
            "derived: 0.495 / (0.028 / 2), rounded to 0.1 ohm. Same table: "
            "IOL typ 28 mA at VDD = 3.3 V, VOL = 0.495 V, PAD_DRIVER = 3, "
            "halved for a ~20 mA pad as the source current is -- an "
            "assumption, since the TRM gives one strength per field value and "
            "does not say sourcing or sinking. TYPICAL, not a bound"
        ),
        "typical": (
            "Table 5-4 note 2, p.71: `VOH and VOL are measured using "
            "high-impedance load`, so no output voltage is guaranteed at any "
            "current, and IOH and IOL are stated only in the Typ column"
        ),
        "rated_amps": (
            "there is not one. Table 5-4 gives IOH and IOL as typical currents "
            "at a test point, which is not a rating, and no other table states "
            "a per-pin current"
        ),
        "absolute_amps": (
            "there is not one. Table 5-1, `Absolute Maximum Ratings`, p.70, "
            "states only the input power pins' voltage and the storage "
            "temperature: no output current at all, per pin or together"
        ),
        "input_high_volts": (
            "0.75 * 3.3: Table 5-4, p.71, VIH `High-level input voltage` min "
            "0.75 x VDD"
        ),
        "input_low_volts": (
            "0.25 * 3.3: Table 5-4, p.71, VIL `Low-level input voltage` max "
            "0.25 x VDD"
        ),
    },
}

#: What the silicon has, exactly as `webui/boards/catalogue.py`'s `CHIPS`
#: records it, with `test_the_board_agrees_with_the_catalogue_about_the_isa`
#: pinning the two together.
#:
#: **This string cannot be passed to `set_isa` and is not meant to be.** See
#: `EXECUTES`.
ISA = "RV32IMAC + Zcb/Zcmp/Zcmt"

#: What `install` hands to `set_isa`: the whole of `ISA`, in the grammar
#: `set_isa` speaks (OH-146). The datasheet's spelling above has a plus and
#: slashes in it, so the two constants stay two -- one set, spelled for a
#: reader and spelled for the core -- and `set_isa`'s refusal of anything it
#: cannot represent is what keeps them the same set rather than drifting.
#: `webui/boards/esp32c6.py` deliberately does **not** grow an `EXECUTES` of
#: its own for symmetry -- a board whose ISA string IS the grammar has
#: nothing to say twice.
EXECUTES = "RV32IMAC_ZCB_ZCMP_ZCMT"

#: Empty since OH-146, and kept rather than deleted: `tests/rv32/
#: test_gating.py` asserts this equals the C5's unmodelled set -- so a new
#: datasheet row nobody implements must land in both places or fail a test
#: that names the other.
ABSENT: tuple[str, ...] = ()


class Cpu(typing.Protocol):
    """What this module needs of a core."""

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
    def map_sampler(self, control: int, *, value: int, start_mask: int,
                    key_mask: int, result: int, status: int, done_mask: int,
                    enable: int, enable_mask: int) -> None: ...
    def hold_samples(self, control: int,
                     samples: typing.Mapping[int, int]) -> None: ...
    def stream(self, address: int) -> bytes: ...
    def read_word(self, address: int) -> int: ...


def install_memory(cpu: Cpu) -> None:
    """The flash window and SRAM.

    Two regions, like a C6's and unlike a C3's: `soc.h:152-153` makes DROM the
    same window as IROM, and `soc.h:158-161` gives IRAM and DRAM one base and
    one top, so there is no separate rodata window and no second view of SRAM
    to leave unmapped.

    SRAM is executable because it genuinely is -- the instruction bus reaches
    the same words -- and because an image that copies a function into RAM and
    jumps to it is a normal thing an ESP32 image does.
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

    `GPIO_IN` is `install_gpio_in`'s, at + 0x64 here where a C6's is at
    + 0x3c, which is this part's `GPIO_ENABLE_W1TC`.
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
    GPIO that has one.

    The C3's `install_gpio_in` carries the argument in full: what each bit
    reads and in what order, why a floating pin reads 0 and is not a fault,
    and why the outside beats a pull. This part's datasheet, v1.5 Table 5-4,
    p.71, states the same `IIH`, `IIL`, `CIN` and 45 kohm `RPU` as the
    C3's.

    **What differs is where the pads are.** GPIO0's register is at + 0x0,
    not + 0x4, and GPIO15 to GPIO22 have none: their bits are outside
    `pads`, so they read 0 and no register is asked for them. And this
    part's pads come out of reset with `FUN_IE` clear on more GPIOs than a
    C3's -- GPIO0, 8, 9 and 10 among them, a XIAO ESP32-C5's D1, D8, D9 and
    D10 -- so a pin `pinMode` has not touched reads 0 whatever drives it,
    as the silicon's does.
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
    no pad for -- GPIO15 to GPIO22 among them -- is refused, naming it.
    """
    driven = 0
    high = 0
    for gpio, level in levels.items():
        if gpio not in IO_MUX_PADS:
            raise ValueError(
                f"GPIO{gpio} has no pad on an ESP32-C5; its pads are GPIO"
                f"{', GPIO'.join(str(pad) for pad in sorted(IO_MUX_PADS))}")
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


def adc_code(volts: float, atten: int) -> int:
    """The 12-bit code this part's ADC gives `volts` at `atten`: the TRM's
    `Vdata = Vref / k * data / 4095` solved for `data`, rounded half up and
    held to 4095.

    **Typical, and uncalibrated.** Vref is "1100 mV by design"; the
    datasheet states accuracy only after hardware and software calibration
    (v1.5 Table 5-6, ADC Calibration Results, p.72) and DNL and INL only as
    LSB bounds (Table 5-5, p.72), and states no uncalibrated spread. No
    eFuse calibration, no nonlinearity and no noise are modelled. At 12 dB
    the effective range is 0 to 3300 mV (Table 5-6).

    `ValueError` with the value for a voltage that is not a finite number at
    or above 0 V, and for an attenuation `ONETIME_ATTEN` cannot spell.
    """
    if atten not in ADC_ATTEN_K:
        raise ValueError(
            f"attenuation {atten!r} is none of ONETIME_ATTEN's {sorted(ADC_ATTEN_K)}")
    if not (isinstance(volts, (int, float)) and math.isfinite(volts) and volts >= 0):
        raise ValueError(f"an ADC converts a voltage of 0 V or more, got {volts!r}")
    return min(ADC_FULL_CODE,
               math.floor(volts * ADC_ATTEN_K[atten] / ADC_VREF_VOLTS * ADC_FULL_CODE + 0.5))


def install_adc(cpu: Cpu) -> None:
    """ADC1's one-time sample, far enough for an `analogRead` and no further.

    `webui/boards/esp32c3.py`'s `install_adc` carries the argument; what
    differs here is the clock. `CTRL` and the two PCR registers are mapped at
    their composed reset values, and the sampler is gated on PCR's
    `SARADC_CLKM_EN`, which is 0 out of reset: a start converts nothing
    until firmware sets it, as the TRM's procedure does in its step 4.
    """
    cpu.map_register(APB_SARADC + APB_SARADC_CTRL, APB_SARADC_CTRL_AT_RESET)
    cpu.map_register(PCR + PCR_SARADC_CONF, PCR_SARADC_CONF_AT_RESET)
    cpu.map_register(PCR + PCR_SARADC_CLKM_CONF, PCR_SARADC_CLKM_CONF_AT_RESET)
    cpu.map_register(APB_SARADC + APB_SARADC_SAR1_DATA, 0)
    cpu.map_register(APB_SARADC + APB_SARADC_INT_RAW, 0)
    cpu.map_alias(APB_SARADC + APB_SARADC_INT_CLR, APB_SARADC + APB_SARADC_INT_RAW,
                  "clear", readable=False)
    cpu.map_sampler(
        APB_SARADC + APB_SARADC_ONETIME_SAMPLE,
        value=ONETIME_SAMPLE_AT_RESET,
        start_mask=ONETIME_START,
        key_mask=ONETIME_CONVERSION,
        result=APB_SARADC + APB_SARADC_SAR1_DATA,
        status=APB_SARADC + APB_SARADC_INT_RAW,
        done_mask=ADC1_DONE,
        enable=ADC_GATE[0],
        enable_mask=ADC_GATE[1],
    )
    hold_volts(cpu, {})


def hold_volts(cpu: Cpu, volts: typing.Mapping[int, float]) -> None:
    """What the outside holds each pin at, GPIO -> volts, as ADC1 converts it.

    A whole statement, as `webui/boards/esp32c3.py`'s says: a pin left out
    floats and converts to 0, and each channel is held at every
    attenuation. A GPIO this part has no pad for -- the SPI flash pads among
    them -- is refused, naming it.
    """
    for gpio in volts:
        if gpio not in IO_MUX_PADS:
            raise ValueError(
                f"GPIO{gpio} has no pad on an ESP32-C5; its pads are GPIO"
                f"{', GPIO'.join(str(pad) for pad in sorted(IO_MUX_PADS))}")
    cpu.hold_samples(APB_SARADC + APB_SARADC_ONETIME_SAMPLE, {
        ONETIME_SAR1 | channel << ONETIME_CHANNEL_SHIFT | atten << ONETIME_ATTEN_SHIFT:
            adc_code(volts.get(gpio, 0.0), atten)
        for gpio, channel in ADC1_CHANNELS.items()
        for atten in ADC_ATTEN_K
    })


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    `"high"`, `"low"` or `"input"` keyed by the label in `HEADER`, `ENABLE`
    deciding before `OUT` does; `esp32c3.py` carries the argument for both
    at its own `pin_states`, and `LED` is here because the vendor's file
    puts the board's LED on GPIO27.

    Each register is read once because each is ONE register on this part:
    `gpio_reg.h:39` gives `GPIO_OUT_DATA_ORIG` as `bitpos: [31:0]` and
    `:138` `GPIO_ENABLE_DATA` the same, so every GPIO this part has is one
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
    # `EXECUTES` and not `ISA`: the same set in the grammar `set_isa`
    # speaks. The datasheet's own spelling would raise -- see `EXECUTES` for
    # why that is the right behaviour and why this is the right response to it.
    cpu.set_isa(EXECUTES)
    install_memory(cpu)
    install_gpio(cpu)
    # After `install_gpio`: the input register reads `OUT` and `ENABLE`.
    install_gpio_in(cpu)
    install_uart0(cpu)
    install_systimer(cpu)
    # After `install_gpio_in`, whose pad registers `analogRead` writes.
    install_adc(cpu)
