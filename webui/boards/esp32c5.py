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

Every timer, the ADC, SPI, I2C, the LP core and its 16 KB of LP_SRAM
at 0x50000000, and the whole clock and reset subsystem. Same growth rule the
other boards keep: a peripheral is added when a real image faults on it and not
before, and `core/riscv32/cpu.h` faults on any address no region and no
register covers.

**The UART is half here since OH-161**: UART0's transmit FIFO and the clock
bit that gates it, which is what a `Serial.print` needs. Its receive half, its
baud divisors and `UART_TXFIFO_CNT` stay unmapped, so firmware that waits for
room in the FIFO faults at a named address rather than spinning on a zero;
`webui/boards/esp32c3.py` carries the argument in full.

The mask ROM is not modelled and cannot be. **An ESP-IDF application will not
run on this board**, for the reason `esp32c6.py` gives at length.
"""

from __future__ import annotations

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

    `GPIO_IN` is left **unmapped on purpose**: `IN` reads the electrical level
    on the pin, so on a pin driven as an output it follows `OUT`, and a stored
    register reading zero would answer wrongly to firmware that drives a pin
    high and reads it back. On this part that decision has a second edge --
    `GPIO_IN` is at + 0x64 here and a C6's is at + 0x3c, which is this part's
    `GPIO_ENABLE_W1TC`. Mapping the wrong one would not fault; it would work,
    wrongly.
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
    install_uart0(cpu)
