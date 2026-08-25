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

## Described is not verified, and this board is the case that distinction is for

`webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` records the chips a real
compiled image has been watched executing on. **This chip is not in it, and
that is a decision rather than a gap yet to be filled.** Writing this file
makes the two XIAO ESP32-C5 boards *runnable*, meaning an image can be
attempted on them; `rules/board-claims.md` governs the stronger word, and
nothing here earns it.

## The ISA: three names for three different questions

    ISA        RV32IMAC + Zcb/Zcmp/Zcmt   what the silicon has
    EXECUTES   RV32IMAC                   what this core is told it is
    ABSENT     Zcb, Zcmp, Zcmt            the difference, named

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

`EXECUTES` is what `install` actually hands to `set_isa`, and it is a smaller
thing than `ISA` on purpose. `core/riscv32/abi.py`'s `set_isa` **refuses** a
letter it cannot represent rather than dropping it, so passing `ISA` here would
raise -- correctly. Two constants say what one string cannot: this is the part,
and this is the subset the core was configured as.

## What happens when an image uses one of the absent groups

It stops, on that instruction, and names the encoding. All three groups live in
compressed-encoding space that base RVC leaves reserved -- Zcb in quadrant 0's
`funct3=100`, Zcmp and Zcmt in quadrant 2's `funct3=101`, which on RV32 without
D is the illegal `c.fsdsp` slot -- so this core meets them as encodings it has
no rule for and refuses them. It does **not** decode them as something else,
which is the failure that would matter: a plausible wrong instruction executed
silently, twenty thousand steps before anything looks wrong.
`tests/riscv32/test_esp32c5_board.py` asserts each group is refused, so the
paragraph above is a test rather than a hope.

That refusal is why describing this part is safe. A board whose gap shows up as
a stop with an address is a board a reader can act on.

**It says `Illegal` where the truthful word is `Unimplemented`, and that is a
known cost of describing this part now.** Those two words are the whole point
of `set_isa`: `Illegal` claims the silicon does not have the instruction, and
`Unimplemented` admits this core has not written it. An ESP32-C6 gets the right
one -- `core/riscv32/cpu.h` classifies A, so an atomic on a C6 board is
correctly `Unimplemented` and the same encoding on a C3 board is correctly
`Illegal`, which `tests/riscv32/test_esp32c6_board.py` pins. There is no such
bit for Zcb, Zcmp or Zcmt, so this core cannot be *told* the part has them and
answers with the only word it has.

Loading a real C5 image therefore stops with, for example:

    pc=0x42000008: encoding 0x0001b842 is illegal for extensions 0x7

The address and the encoding are right; the word is not. Fixing it is core work
-- three classification bits and three letters `set_isa` can represent -- and
it is the same work the `FIRMWARE_VERIFIED` entry is waiting on, so it is not
being done here as a side effect of writing a board file.
`test_an_absent_group_is_refused_as_illegal_which_is_the_weaker_true_thing`
asserts the current wording so that adding those bits fails a test that says
what to change.

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

Every timer, the UART, the ADC, SPI, I2C, the LP core and its 16 KB of LP_SRAM
at 0x50000000, and the whole clock and reset subsystem. Same growth rule the
other boards keep: a peripheral is added when a real image faults on it and not
before, and `core/riscv32/cpu.h` faults on any address no region and no
register covers.

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

#: The pin a fixture would watch. **Not claimed as a user LED**, and no image
#: has been watched on this part at all -- see the module docstring. GPIO8 is
#: ESP-IDF's own blink default,
#: `examples/get-started/blink/main/Kconfig.projbuild:34-37`.
LED_PIN = 8

#: What the silicon has, exactly as `webui/boards/catalogue.py`'s `CHIPS`
#: records it, with `test_the_board_agrees_with_the_catalogue_about_the_isa`
#: pinning the two together.
#:
#: **This string cannot be passed to `set_isa` and is not meant to be.** See
#: `EXECUTES`.
ISA = "RV32IMAC + Zcb/Zcmp/Zcmt"

#: What `install` configures the core as: the part of `ISA` this core can be
#: told about at all.
#:
#: `core/riscv32/abi.py`'s `set_isa` maps letters to bits and **raises** on one
#: it cannot represent, rather than dropping it -- because an extension
#: silently dropped makes a part look like one it is not. `ISA` above names
#: three groups it has no bit for, so handing it over would raise, correctly.
#:
#: Naming the subset separately is the alternative to three worse options:
#: shrinking `ISA` to `RV32IMAC` (a false claim about the silicon), catching
#: the exception (a default where a fact belongs), or leaving this part
#: undescribed (a board nobody can even attempt). What it costs is one constant
#: that only this board has, and `webui/boards/esp32c6.py` deliberately does
#: **not** grow an `EXECUTES` equal to its `ISA` for symmetry -- a second board
#: with nothing to say would make this one's statement look like boilerplate.
EXECUTES = "RV32IMAC"

#: The difference between the two above, as the groups' own names.
#:
#: Not derivable: `ISA` is a datasheet string with slashes and a plus in it,
#: not a letter sequence anything can subtract from. Written out so
#: `tests/riscv32/test_esp32c5_board.py` can assert each one is *refused* by
#: this core rather than decoded as something else -- which is the property
#: that makes describing this part safe rather than misleading.
ABSENT: tuple[str, ...] = ("Zcb", "Zcmp", "Zcmt")


class Cpu(typing.Protocol):
    """What this module needs of a core."""

    def set_isa(self, letters: str) -> None: ...
    def add_region(self, base: int, size: int, executable: bool = ...,
                   fill: int = ...) -> None: ...
    def map_register(self, address: int, value: int = ...) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...


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


def install(cpu: Cpu) -> None:
    """Every region and register this board models, which is not every one.

    **Precondition: the core has no board.** `core/riscv32/machine.py`'s
    `blank` calls `reset`, which forgets the regions, the mapped registers and
    the extension mask together.
    """
    # `EXECUTES` and not `ISA`, and the difference is the whole of what this
    # board has to say. `set_isa(ISA)` would raise -- see `EXECUTES` above for
    # why that is the right behaviour and why this is the right response to it.
    cpu.set_isa(EXECUTES)
    install_memory(cpu)
    install_gpio(cpu)
