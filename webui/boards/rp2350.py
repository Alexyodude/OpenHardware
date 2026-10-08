#!/usr/bin/env python3
# OpenHardware - the RP2350 as regions and registers over the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an RP2350 to a `core.riscv32` CPU: the chip's Hazard3 half.

**The RP2350 is two architectures on one die, and this file describes one.**
It carries two Cortex-M33 cores and two Hazard3 RISC-V cores, and "Cortex-M33
is the default option. Whichever processor is unused is held in reset with
its clock gated at the top level" (RP2350 Datasheet, chapter 3's
introduction, PDF p.34). So a real RP2350 boots its Arm half unless told
otherwise, and an image built for the Arm half does not run here.

**The Cortex-M33 half is not modelled.** It is Armv8-M with the Security,
DSP and FPU extensions, and it has no core and no oracle in this repository:
that is OH-36, which claims `core/cortexm33/**` and `tests/cortexm33/**`, and
none of it is touched here. What this file buys is the cheaper door
`docs/architectures.md` 5.4 describes -- the RISC-V half, on the core the
three ESP32 boards already run on.

## Where these numbers come from

Two sources, and every number below names one of them.

**pico-sdk's register headers**, at the commit arduino-pico pins: pico-sdk
2.3.0, `98a542c1a62f`, the `pico-sdk` submodule of arduino-pico `33201a6`
(the arduino-pico revision `HEADER` below is generated from). BSD-3-Clause.
Fetched blobless and sparse into the submodule's own, otherwise empty, path:

    cd third_party/bsp/arduino-pico/pico-sdk
    git init && git remote add origin https://github.com/raspberrypi/pico-sdk.git
    git fetch --depth 1 --filter=blob:none origin 98a542c1a62fb549ffb5d66a3e5892b06276b670
    git sparse-checkout set src/rp2350/hardware_regs && git checkout FETCH_HEAD

Every address cites a line of `src/rp2350/hardware_regs/include/hardware/
regs/<file>.h` there, the way `esp32c6.py` cites ESP-IDF's `soc.h`, and
`tests/webui/test_xiao_rp2350_board.py` reads each one back out of that
header where the checkout exists and skips by name where it does not.

**The RP2350 Datasheet** for what the headers do not say: build version
80d627281ed5, build date 01/10/2026, release 8, from
https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf, sha256
a638d6780da919162660691bfa02c6dcf7c2a0b6e9f18e2d7519c80b664a2e39 when it
was read. The URL names no version, so the digest is what says which
document a page number is in. Cited by section and PDF page, as
`rp2040.py` cites the RP2040's. CC BY-ND, so it is quoted in short and
never copied in.

## How an image is entered, and why that is honest for a bare-metal blink

The boot ROM is not modelled. It boots a flash image only if it finds an
IMAGE_DEF block in the first 4 kB (section 5.9.5, PDF p.390), and for the
minimum RISC-V IMAGE_DEF, which names no entry point, "the bootrom will
enter the binary at its lowest address, which is the default behaviour on
RISC-V" (section 5.9.5.2, Table 504, PDF p.391). `core/riscv32/machine.py`
enters a raw image at its lowest address too. So an image loaded at
`XIP_BASE` -- as `test_xiao_rp2350_board.py`'s is, carrying that 20-byte block
after its code -- starts here at the instruction the ROM would hand over to.

What is skipped is everything the ROM does first: its flash scan and XIP
setup, and "Reset all PADS and IO registers, and remove isolation from QSPI
pads" (section 5.2, Table 462, PDF p.340). The model starts with every
register at its documented reset value, which is the state that step
leaves. A blink that touches only RESETS, IO_BANK0, PADS_BANK0 and SIO
depends on nothing else the ROM sets up -- not the clocks, which this model
does not have, and not the ROM's function table, which it does not call.
**A pico-sdk or Arduino image is not that**, and it will stop at the first
register this file leaves unmapped, naming the address.

Unlike the RP2040's, this ROM's source is published under BSD-3-Clause
(chapter 5's introduction, PDF p.327). What keeps it out of this model is
work, not licence.

## Core 1 does not exist

"After reset, processor core 1 sleeps at start-up, and remains asleep until
woken by core 0 via the SIO FIFOs" (section 5.3, PDF p.346). Nothing at boot
waits for core 1 (`docs/architectures.md` 5.5), so this file models one
hart, `SIO_CPUID` reads 0 as it does on core 0 (section 3.1.2, PDF p.36),
and the FIFO registers exist only so that an image touching them does not
fault: see `install_sio_fifo`. `multicore_launch_core1` would wait forever
for an answer no core sends.

## What is deliberately absent

The ROM, every clock, the timers, UART, SPI, I2C, PIO, DMA, USB, the
interpolators and spinlocks, the Arm half, core 1, and every register of
RESETS, IO_BANK0, PADS_BANK0 and SIO that a blink does not write. The same
growth rule the other boards keep: a peripheral is added when a real image
faults on it, and `core/riscv32/cpu.h` faults on any address no region and
no register covers, naming it.
"""

from __future__ import annotations

import typing

from core.riscv32 import abi

#: The Hazard3's ISA as the datasheet spells it -- RVCSR MISA's description,
#: "On RP2350, Hazard3's full `-march` string is:" (section 3.8.9, PDF p.288),
#: the same string `docs/architectures.md` 5.4 and `abi.RP2350_MODELLED`
#: quote. The silicon's, and not what `install` configures; see `EXTENSIONS`.
ISA = "rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp"

#: What `install` gives the core: `abi.RP2350_MODELLED`, the part of `ISA`
#: `core/riscv32` models -- M, A (classified, not executed), C for Zca, Zba,
#: Zbs, Zcb and Zcmp. A bitmask rather than `set_isa`'s letters because
#: `set_isa` names no group for Zba or Zbs, and dropping them would make
#: this core call `sh1add` illegal on a part that has it.
#:
#: **Zbb and Zbkb are not in it, and that is a wrong answer about this
#: part.** The core has no bit for either group and refuses their encodings
#: on every part as `Illegal` -- the word for "the silicon lacks this",
#: which the RP2350 does not. abi.py's note on `RP2350_MODELLED` says the
#: constant "describes a part that does not exist"; this board inherits that
#: rather than fixing it, because the fix is `core/riscv32`'s. An image with a
#: Zbb or Zbkb instruction stops here, loudly, with the wrong word; the blink
#: `test_xiao_rp2350_board.py` runs is built `-march=rv32imac` and has none.
EXTENSIONS = abi.RP2350_MODELLED

#: The XIP window's base, `addressmap.h:24` -- `#define XIP_BASE
#: _u(0x10000000)`. Where flash is executed from, and where an image loads.
XIP = 0x10000000

#: The XIAO RP2350's flash: `seeed_xiao_rp2350.menu.flash.2097152_0.
#: build.flash_total=2097152`, arduino-pico 33201a6 `boards.txt:36689`, and
#: "2MB Flash" in Seeed's own `XIAO-RP2350.md:41`. **The board's, not the
#: chip's**: the window is 64 MB, of which "the lower 32 MB is occupied by
#: the QSPI Memory Interface" (section 2.2.2, PDF p.29), and the RP2350A
#: carries no flash of its own. An address past 2 MB is unmapped here, where
#: a XIAO would read whatever its flash part answers there.
FLASH_SIZE = 2 * 1024 * 1024

#: Erased flash reads 0xFF, and 0xFFFFFFFF is no RV32 encoding, so a program
#: that runs off the end of its image stops.
FLASH_ERASED = 0xFF

#: SRAM, `addressmap.h:34` and `:42`:
#:
#:     #define SRAM_BASE _u(0x20000000)
#:     #define SRAM_END _u(0x20082000)
#:
#: 520 KB, which is Seeed's "520kB SRAM" (`XIAO-RP2350.md:41`): SRAM0-7
#: striped, then SRAM8 and SRAM9 unstriped (section 2.2.3, PDF p.29). One
#: region, because striping decides which bank a word lives in and not which
#: address names it.
SRAM = 0x20000000
SRAM_SIZE = 0x20082000 - 0x20000000

#: Peripheral bases, `addressmap.h`:
#:
#:     #define RESETS_BASE _u(0x40020000)       :47
#:     #define IO_BANK0_BASE _u(0x40028000)     :48
#:     #define PADS_BANK0_BASE _u(0x40038000)   :50
#:     #define SIO_BASE _u(0xd0000000)          :105
#:
#: **Only SIO's is the RP2040's.** The RP2040 has RESETS at 0x4000c000,
#: IO_BANK0 at 0x40014000 and PADS_BANK0 at 0x4001c000 -- pico-sdk 1.3.0's
#: RP2040 `addressmap.h:40`, `:42` and `:44`, the copy PlatformIO's
#: framework-arduino-mbed 4.6.0 vendors, which is not in this tree; `rp2040.py`
#: carries the first two. SIO is 0xd0000000 on both (`:71` there), and its
#: register file kept some offsets and not others -- see `SIO_GPIO_OE`.
RESETS = 0x40020000
IO_BANK0 = 0x40028000
PADS_BANK0 = 0x40038000
SIO = 0xD0000000

#: The atomic write aliases, `addressmap.h:19-21`: `REG_ALIAS_XOR_BITS` is
#: `0x1 << 12`, SET `0x2 << 12`, CLR `0x3 << 12` -- "Addr + 0x1000 : atomic
#: XOR on write" and so on (section 2.1.3, PDF p.24). "SIO ... though some
#: individual registers (for example, GPIO) have set, clear, and XOR aliases"
#: is the named exception (PDF p.25), so SIO gets none of these.
ALIAS_XOR = 0x1000
ALIAS_SET = 0x2000
ALIAS_CLR = 0x3000

#: RESETS.RESET, `resets.h:17-19`: offset 0x0, `RESETS_RESET_RESET
#: _u(0x1fffffff)` -- every block held in reset at power-up, "To use the
#: component, software must deassert the reset" (section 7.5.1, PDF p.459).
RESETS_RESET = 0x00
RESETS_RESET_AT_RESET = 0x1FFFFFFF

#: The two bits a blink clears, `resets.h:177` and `:156`:
#: `RESETS_RESET_IO_BANK0_BITS _u(0x00000040)`,
#: `RESETS_RESET_PADS_BANK0_BITS _u(0x00000200)`.
RESET_IO_BANK0 = 0x40
RESET_PADS_BANK0 = 0x200

#: `RESETS_RESET_DONE_OFFSET _u(0x00000008)`, `resets.h:433`. **Exported and
#: left unmapped**: it reads as the inverse of RESET, and `core/riscv32` has
#: no mirror to compute that with, so a read of it faults and names this
#: address rather than answering a value nothing keeps true.
RESETS_RESET_DONE = 0x08

#: IO_BANK0's per-GPIO control, `io_bank0.h:55` --
#: `IO_BANK0_GPIO0_CTRL_OFFSET _u(0x00000004)` -- and `:193`, GPIO1's at
#: 0x00c: eight apart, beside each GPIO's STATUS. 0x0ec for GPIO29
#: (`:4029`) closes the run.
IO_BANK0_GPIO_CTRL = 0x004
IO_BANK0_GPIO_STRIDE = 8

#: "30 user GPIOs in the QFN-60 package (RP2350A)" (section 9.1, PDF p.539),
#: and the XIAO's is the QFN-60: Seeed's own `RP2350.kicad_pcb:13967` places
#: `Ic:QFN60-0.4-7X7X0.9MM`. The header goes on to GPIO47 for the RP2350B.
GPIOS = 30

#: `IO_BANK0_GPIO0_CTRL_RESET _u(0x0000001f)` (`io_bank0.h:57`):
#: `FUNCSEL`, bits 4:0 (`_FUNCSEL_BITS _u(0x0000001f)`, `:137`), at
#: `_FUNCSEL_VALUE_NULL _u(0x1f)` (`:152`), every other field 0. All 48
#: GPIOs reset the same, which the header test reads.
GPIO_CTRL_AT_RESET = 0x1F
GPIO_CTRL_FUNCSEL = 0x1F
FUNCSEL_NULL = 0x1F

#: `IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_SIO_0 _u(0x05)` (`io_bank0.h:146`),
#: and SIO is function 5 on every GPIO: "For the output and output enable
#: registers to take effect, the SIO function must be selected on each GPIO
#: (function 5)" (section 9.8, PDF p.546).
FUNCSEL_SIO = 5

#: PADS_BANK0's per-GPIO pad register, `pads_bank0.h:30` --
#: `PADS_BANK0_GPIO0_OFFSET _u(0x00000004)` -- and `:109`, GPIO1's at
#: 0x008: four apart, after VOLTAGE_SELECT at 0x000.
PADS_BANK0_GPIO = 0x004
PADS_BANK0_STRIDE = 4

#: `PADS_BANK0_GPIO0_RESET _u(0x00000116)` (`pads_bank0.h:32`): ISO set,
#: 4 mA drive, pull-down, Schmitt trigger. Every Bank 0 pad resets the same.
PAD_AT_RESET = 0x116

#: **The isolation latch, which the RP2040 does not have.**
#: `PADS_BANK0_GPIO0_ISO_BITS _u(0x00000100)` (`pads_bank0.h:38`), reset 1.
#: While it is set, "the control signals currently presented to that pad are
#: latched until the isolation is disabled", and "Non-SDK applications ported
#: from RP2040 must clear the ISO bit before using a GPIO, as this feature was
#: not present on RP2040" (section 9.7, PDF pp.545-546).
PAD_ISO = 0x100

#: `PADS_BANK0_GPIO0_OD_BITS _u(0x00000080)` (`pads_bank0.h:47`), reset 0:
#: "Output disable. Has priority over output enable from peripherals".
PAD_OD = 0x80

#: SIO registers, `sio.h`. **GPIO_OUT's SET, CLR and XOR, GPIO_OE, and
#: GPIO_OE's SET, CLR and XOR moved from the RP2040's offsets**, each now
#: beside a `GPIO_HI_` register; CPUID, GPIO_IN and GPIO_OUT did not, and
#: neither did the FIFO registers below. The RP2040 put `GPIO_OE` at 0x020,
#: which here is `GPIO_OUT_CLR`, so an RP2040 image enabling its outputs
#: would clear output levels on this chip instead. Compared against pico-sdk
#: 1.3.0's RP2040 `sio.h`, the copy cited for the bases above.
#:
#:     SIO_CPUID_OFFSET        0x000  :23   RO
#:     SIO_GPIO_IN_OFFSET      0x004  :35   RO
#:     SIO_GPIO_OUT_OFFSET     0x010  :113  RW
#:     SIO_GPIO_OUT_SET_OFFSET 0x018  :188  WO
#:     SIO_GPIO_OUT_CLR_OFFSET 0x020  :249  WO
#:     SIO_GPIO_OUT_XOR_OFFSET 0x028  :310  WO
#:     SIO_GPIO_OE_OFFSET      0x030  :380  RW
#:     SIO_GPIO_OE_SET_OFFSET  0x038  :456  WO
#:     SIO_GPIO_OE_CLR_OFFSET  0x040  :517  WO
#:     SIO_GPIO_OE_XOR_OFFSET  0x048  :578  WO
SIO_CPUID = 0x000
SIO_GPIO_IN = 0x004
SIO_GPIO_OUT = 0x010
SIO_GPIO_OUT_SET = 0x018
SIO_GPIO_OUT_CLR = 0x020
SIO_GPIO_OUT_XOR = 0x028
SIO_GPIO_OE = 0x030
SIO_GPIO_OE_SET = 0x038
SIO_GPIO_OE_CLR = 0x040
SIO_GPIO_OE_XOR = 0x048

#: The inter-processor FIFOs, `sio.h`:
#:
#:     SIO_FIFO_ST_OFFSET 0x050  :645   reset 0x2 (:647): RDY set, VLD clear
#:     SIO_FIFO_WR_OFFSET 0x054  :687   "WF"
#:     SIO_FIFO_RD_OFFSET 0x058  :696   "RF"
#:
#: The header calls each FIFO "8 words deep" (`sio.h:638`) and the datasheet
#: "four entries deep" (section 3.1.5, PDF p.39). Nothing here depends on
#: which, because nothing here fills one; the two sources are recorded as
#: disagreeing rather than one chosen.
SIO_FIFO_ST = 0x050
SIO_FIFO_WR = 0x054
SIO_FIFO_RD = 0x058
SIO_FIFO_ST_AT_RESET = 0x2

# --- BEGIN HEADER: generated by `python tools/import_pindefs.py --write-headers`; do not edit by hand ---
#: Header label -> GPIO number: the pin `pin_states` reads a level
#: through and `PIN_NAMES` spells. Read out of the board-support
#: packages, never typed here:
#:     zephyr boards/seeed/xiao_rp2350/seeed_xiao_connector.dtsi @ 0a2e408
#:     arduino-pico variants/seeed_xiao_rp2350/pins_arduino.h @ 33201a6
#: for XIAO-RP2350-DIP, XIAO-RP2350-SMD. A row is here only where every
#: package that defines it names the same pin; a row only one package
#: defines is that package's.
#: `tests/rules/test_import_pindefs.py` holds this block equal to what the
#: generator emits from the fetched packages.
HEADER: dict[str, int] = {
    "D0": 26,
    "D1": 27,
    "D2": 28,
    "D3": 5,
    "D4": 6,
    "D5": 7,
    "D6": 0,
    "D7": 1,
    "D8": 2,
    "D9": 4,
    "D10": 3,
    "D11": 21,
    "D12": 20,
    "D13": 17,
    "D14": 16,
    "D15": 11,
    "D16": 12,
    "D17": 10,
    "D18": 9,
}
# --- END HEADER ---

#: The same table read the other way, `D3` -> `GPIO5`, derived from `HEADER`
#: so the two cannot disagree. **`D3` is the one label of `D0` to `D10` that
#: this XIAO and the XIAO RP2040 send to different GPIOs** -- 5 here, 29 in
#: `rp2040.HEADER` -- which is why the blink watches it.
PIN_NAMES: dict[str, str] = {label: f"GPIO{gpio}" for label, gpio in HEADER.items()}


class Cpu(typing.Protocol):
    """What this module needs of a core."""

    def set_extensions(self, mask: int) -> None: ...
    def add_region(self, base: int, size: int, executable: bool = ...,
                   fill: int = ...) -> None: ...
    def map_register(self, address: int, value: int = ...) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...
    def read_word(self, address: int) -> int: ...


def gpio_ctrl(gpio: int) -> int:
    """The address of `GPIO<gpio>_CTRL` in IO_BANK0."""
    if not 0 <= gpio < GPIOS:
        raise ValueError(f"GPIO{gpio}: an RP2350A has GPIO0 to GPIO{GPIOS - 1}")
    return IO_BANK0 + IO_BANK0_GPIO_CTRL + IO_BANK0_GPIO_STRIDE * gpio


def pad(gpio: int) -> int:
    """The address of PADS_BANK0's `GPIO<gpio>` pad register."""
    if not 0 <= gpio < GPIOS:
        raise ValueError(f"GPIO{gpio}: an RP2350A has GPIO0 to GPIO{GPIOS - 1}")
    return PADS_BANK0 + PADS_BANK0_GPIO + PADS_BANK0_STRIDE * gpio


def install_memory(cpu: Cpu) -> None:
    """The XIAO's flash in the XIP window, and SRAM. Both executable, because
    the processors fetch from both (sections 2.2.2 and 2.2.3, PDF p.29).

    The ROM at 0x00000000 is not mapped: nothing here calls into it, and a
    read of it faults rather than answering a ROM this repository does not
    have. `rp2040.py` maps a zero-filled stub there because the RP2040's
    runtime walks a table in its ROM; a bare-metal image does not.
    """
    cpu.add_region(XIP, FLASH_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True, fill=0x00)


def install_resets(cpu: Cpu) -> None:
    """RESETS.RESET and its three atomic aliases, so that an image can
    release IO_BANK0 and PADS_BANK0 as silicon requires.

    **Stored, and not obeyed.** This model does not hold a block in reset:
    IO_BANK0 and PADS_BANK0 take writes whatever RESET says, as `rp2040.py`'s
    do, so an image that never releases them drives its pad here and would
    not on silicon. RESET_DONE is unmapped, for the reason `RESETS_RESET_DONE`
    gives, and WDSEL because nothing writes it.

    **The aliases read as the register**, as `rp2040.py`'s `alias_block`
    windows do. The datasheet says what a write through one does (section
    2.1.3, PDF p.24) and nothing about a read; that half is carried over from
    the RP2040's oracle, rp2040js, and is unverified for this part.
    """
    reset = RESETS + RESETS_RESET
    cpu.map_register(reset, RESETS_RESET_AT_RESET)
    cpu.map_alias(reset + ALIAS_XOR, reset, "xor")
    cpu.map_alias(reset + ALIAS_SET, reset, "set")
    cpu.map_alias(reset + ALIAS_CLR, reset, "clear")


def install_io_bank0(cpu: Cpu) -> None:
    """`GPIO<n>_CTRL` for GPIO0 to GPIO29, each a plain register at its
    reset value: what `rp2040.py`'s `install_io_bank0` maps, at this part's
    addresses. STATUS, the interrupt registers and the atomic aliases are
    not mapped, so an image reaching for them faults and names the address.
    """
    for gpio in range(GPIOS):
        cpu.map_register(gpio_ctrl(gpio), GPIO_CTRL_AT_RESET)


def install_pads_bank0(cpu: Cpu) -> None:
    """PADS_BANK0's pad register for GPIO0 to GPIO29, each at its reset
    value, ISO set. **The RP2040 model maps none**, because there "all pads
    come out of reset ready to use"; here none is until its ISO is cleared,
    and `pin_states` reads that bit. VOLTAGE_SELECT, the SWD pads and the
    atomic aliases are not mapped.
    """
    for gpio in range(GPIOS):
        cpu.map_register(pad(gpio), PAD_AT_RESET)


def install_sio(cpu: Cpu) -> None:
    """SIO's CPUID and the GPIO output and output-enable registers.

    The SET, CLR and XOR registers are SIO's own write-only registers, "WO"
    in `sio.h`, not bus alias windows, so they read as zero
    (`readable=False`) -- `rp2040.py` makes the same call and gives the
    reason. `GPIO_IN` is left **unmapped**, as `esp32c6.py` leaves its own:
    it reads the pins, so a stored zero would answer wrongly on a pin driven
    high. `CPUID` is 0, core 0's.
    """
    cpu.map_register(SIO + SIO_CPUID, 0)

    cpu.map_register(SIO + SIO_GPIO_OUT, 0)
    cpu.map_alias(SIO + SIO_GPIO_OUT_SET, SIO + SIO_GPIO_OUT, "set", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OUT_CLR, SIO + SIO_GPIO_OUT, "clear", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OUT_XOR, SIO + SIO_GPIO_OUT, "xor", readable=False)

    cpu.map_register(SIO + SIO_GPIO_OE, 0)
    cpu.map_alias(SIO + SIO_GPIO_OE_SET, SIO + SIO_GPIO_OE, "set", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OE_CLR, SIO + SIO_GPIO_OE, "clear", readable=False)
    cpu.map_alias(SIO + SIO_GPIO_OE_XOR, SIO + SIO_GPIO_OE, "xor", readable=False)


def install_sio_fifo(cpu: Cpu) -> None:
    """The mailbox to core 1, as stubs that do not fault, because core 1
    does not exist (see the module docstring).

    * `FIFO_ST` reads its reset value, RDY set and VLD clear: room to send,
      nothing received.
    * `FIFO_WR` takes a write and keeps it nowhere, and reads as zero: a
      message to a core that is not there.
    * `FIFO_RD` reads as zero and ignores a write: an empty mailbox.

    Those two are each an alias of itself that cannot be read, which is the
    one way `core/riscv32` has to make an address swallow a write.

    **Two things silicon does that this does not.** Writing `FIFO_ST` latches
    the word written, where silicon clears ROE and WOF and leaves RDY and VLD
    alone -- "To clear the ROE and WOF flags, write any value to FIFO_ST"
    (section 3.1.5, PDF p.39) -- because this core has no register that
    ignores a write; an image that writes `0xff` there, as pico-sdk's
    `multicore_fifo_clear_irq` does, reads VLD set afterwards. And reading an
    empty `FIFO_RD` does not set ROE, nor do writes ever fill the FIFO and
    clear RDY. A blink touches none of them.
    """
    cpu.map_register(SIO + SIO_FIFO_ST, SIO_FIFO_ST_AT_RESET)
    cpu.map_alias(SIO + SIO_FIFO_WR, SIO + SIO_FIFO_WR, "store", readable=False)
    cpu.map_alias(SIO + SIO_FIFO_RD, SIO + SIO_FIFO_RD, "store", readable=False)


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    `"high"`, `"low"`, `"input"` or `"unknown"` keyed by the label in
    `HEADER`, which `webui.api.pin_view` finds by `getattr`. Four things
    decide a pad, read from the pad inward, so the stage nearest it answers
    first:

    1. **The isolation latch.** On silicon "all signals passing from the
       switched core power domain to the pads pass through isolation latches"
       (section 9.7, PDF p.545), so while ISO is set the pad holds what it
       was presented when isolation began, whatever function is selected
       behind it. From power-up that is the reset state, output disabled --
       "The latches reset to the reset value of the signal being isolated"
       (section 9.7, PDF p.546) -- so this reports `input`. An image that
       clears ISO, drives the pad and sets ISO again holds its level on
       silicon and reads `input` here: this module keeps no history.
    2. **OD**, the pad's output disable, "overriding the Output Enable
       signal from the function controlling the pad" (section 9.6, PDF
       p.545): `input`, whatever that function is.
    3. **FUNCSEL.** NULL selects nothing, so nothing drives the pad:
       `input`. A peripheral this module does not model: `unknown`. Only SIO
       goes on (section 9.8, PDF p.546).
    4. **SIO's GPIO_OE, then GPIO_OUT**, as `rp2040.py` reads them.

    **RESETS is not consulted**, for the reason `install_resets` gives.
    `GPIO_OE` and `GPIO_OUT` are each read once: `sio.h:381` and `:114` give
    both as `_BITS _u(0xffffffff)`, one bit per GPIO0...31, and every `HEADER`
    value is under `GPIOS`.
    """
    enabled = cpu.read_word(SIO + SIO_GPIO_OE)
    out = cpu.read_word(SIO + SIO_GPIO_OUT)
    states: dict[str, str] = {}
    for label, gpio in HEADER.items():
        funcsel = cpu.read_word(gpio_ctrl(gpio)) & GPIO_CTRL_FUNCSEL
        control = cpu.read_word(pad(gpio))
        mask = 1 << gpio
        if control & (PAD_ISO | PAD_OD):
            states[label] = "input"
        elif funcsel == FUNCSEL_NULL:
            states[label] = "input"
        elif funcsel != FUNCSEL_SIO:
            states[label] = "unknown"
        elif not enabled & mask:
            states[label] = "input"
        else:
            states[label] = "high" if out & mask else "low"
    return states


def install(cpu: Cpu) -> None:
    """Every region and register this board models, which is not every one.

    **Precondition: the core has no board.** `core/riscv32/machine.py`'s
    `blank` calls `reset`, which forgets the regions, the mapped registers and
    the extension mask together. The extensions first, as `esp32c6.py` sets
    its ISA first: a core still configured as some other part would answer
    for that part's instruction set.
    """
    cpu.set_extensions(EXTENSIONS)
    install_memory(cpu)
    install_resets(cpu)
    install_io_bank0(cpu)
    install_pads_bank0(cpu)
    install_sio(cpu)
    install_sio_fifo(cpu)
