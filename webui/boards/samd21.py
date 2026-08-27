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

## Two images, and every register here belongs to one of them

**A bare-metal blink needs PORT and nothing else.** `PM_APBBMASK` resets to
`0x0000007F` and `PM_APBBMASK_PORT` is bit 3 (`component/pm.h:322,330-331`), so
PORT is clocked before the first instruction executes and writing `DIRSET`
straight away is correct rather than a shortcut. That is what
`tests/cortexm0/test_samd21_blink.py` measures, and `PM_APBBMASK` is *still*
not modelled, because that image never reaches it.

**A vendor Arduino image configures a clock tree whether the sketch needs one
or not**, and that is where the rest of this file came from. Measured on
2026-08-26 by running a real Arduino-core sketch and recording every address
that faulted: **twenty-seven registers, and this file models exactly those
twenty-seven.** Not one was added because a datasheet has it.
`tests/cortexm0/test_samd21_arduino.py` is the image, and it is the reason each
of them is here.

So the rule `rp2040.py` states is unchanged -- a model acquires registers
nobody has checked by adding them speculatively -- and what changed is that a
second image now checks a larger set. PM's `CTRL` and `APBBMASK`, PORT's
`WRCONFIG`, `IN` and `PMUX`, every SERCOM, EIC, the timers and USB are all
still absent and still fault, because nothing here has reached them.

## Four registers are POLLED, and two of them poll the other way

This is the half that turns a missing register into a hang rather than a
message, so it is worth stating before the constants:

  * `SYSCTRL.PCLKSR` is waited on until a bit is **set** -- `OSC32KRDY`,
    `XOSC32KRDY`, `DFLLRDY`, `DFLLLCKC`, `DFLLLCKF`. All ten waits in
    `startup.c` are this direction, checked. A register reading zero hangs.
  * `GCLK.STATUS.SYNCBUSY`, `ADC.STATUS.SYNCBUSY` and `DAC.STATUS.SYNCBUSY`
    are waited on until **clear**. A register reading all-ones hangs.

Getting either backwards produces an infinite loop and no diagnostic, which is
the one failure `core/cortexm0/cpu.h` cannot make loud: the address *is*
modelled and the read *does* answer.

**A constant is the honest model here and not a shortcut.** There is no crystal
in a simulator and no DFLL, so "the oscillator is ready" and "the synchroniser
is never busy" are the accurate answers rather than the convenient ones -- the
same argument `rp2040.py` makes for `UARTFR`. What it cannot express is startup
*time*: firmware that measures how long a clock took to lock will measure zero.
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

#: `PINCFG`, a byte per pin, from `component/port.h`:
#:
#:     __IO PORT_PINCFG_Type PINCFG[32];  /**< Offset: 0x40 (R/W  8) Pin Configuration */
#:
#: `pinMode` read-modify-writes one byte of this per pin, and `init()` calls
#: `pinMode(pin, INPUT)` for every pin on the board -- which is why both groups
#: are modelled and not only the one with the LED on it.
PORT_PINCFG = 0x40
#: Eight words, because 32 pins at a byte each. Modelled as a whole array
#: rather than as the six words the measured image happened to touch: a PINCFG
#: where pin 20 answers and pin 21 faults would be a stranger model than either
#: all of it or none of it.
PORT_PINCFG_WORDS = 8

#: Group index of PORTA, the only group either XIAO SAMD21 wires an LED to.
PORTA = 0
#: And of PORTB, which two of the header pins are on. Named rather than
#: written as `1` at the two places that need it, because `group(1)` says
#: nothing and `group(PORTB)` says which half of the header it is.
PORTB = 1

#: The XIAO SAMD21's user LED, from Seeed's own pin table:
#: `third_party/bsp/seeed-samd/variants/XIAO_m0/variant.h:67-69` defines
#: `LED_BUILTIN` as pin 13, and entry 13 of `g_APinDescription` in
#: `variant.cpp` is `{ PORTA, 17 }`. So the LED is PA17 -- a fact about the
#: board rather than the chip, kept here because the blink test needs a pin
#: and an arbitrary one would prove less.
LED_PIN = 17

#: Header label -> the pin behind it, as `(PORT group, bit)`.
#:
#: **From Seeed's own `g_APinDescription`**, not from a pinout picture:
#: `third_party/bsp/seeed-samd/variants/XIAO_m0/variant.cpp`, whose entries 0
#: to 10 are the eleven header pins in silkscreen order and whose entry 13 is
#: the user LED. The labels are the ones
#: `webui/boards/XIAO-SAMD21-DIP.json` carries, so a pad and its pin meet on a
#: string both files got from the vendor rather than on one this file invented.
#:
#: Independently corroborated: `python tools/import_pindefs.py XIAO-SAMD21-DIP`
#: resolves the same eleven from Zephyr's `seeed_xiao_connector.dtsi` *and*
#: this variant, and reports zero disputed.
#:
#: **`LED` is here and is not a pad.** The XIAO's user LED is on the board
#: rather than on the header, so it has no coordinate in the pad map and
#: `webui.api.pin_view` reports it as a pin with no position. That is the pin
#: `LED_BUILTIN` names and the one a stock Blink drives, so leaving it out
#: would mean the commonest sketch there is moved nothing a person could see.
HEADER: dict[str, tuple[int, int]] = {
    "D0": (PORTA, 2),
    "D1": (PORTA, 4),
    "D2": (PORTA, 10),
    "D3": (PORTA, 11),
    "D4": (PORTA, 8),    # SDA
    "D5": (PORTA, 9),    # SCL
    "D6": (PORTB, 8),    # TX
    "D7": (PORTB, 9),    # RX
    "D8": (PORTA, 7),    # SCK
    "D9": (PORTA, 5),    # MISO
    "D10": (PORTA, 6),   # MOSI
    "LED": (PORTA, LED_PIN),
}

#: The same table read the other way: label -> the pin as the datasheet spells
#: it, `D6` -> `PB08`.
#:
#: **Derived from `HEADER` rather than typed out**, so the two cannot disagree.
#: A second hand-written table is a second thing to get right, and this one
#: would be checked by nobody -- it is a name, so a wrong one is wrong in a
#: tooltip rather than in a register read.
#:
#: The two-digit form is Microchip's own: `samd21g18a.h` spells the pin
#: `PIN_PA17` and `tools/import_pindefs.py` reports `PA17`, so a reader can
#: paste it into either.
PIN_NAMES: dict[str, str] = {
    label: f"P{'AB'[index]}{bit:02d}" for label, (index, bit) in HEADER.items()
}

#: What a pin of this part can actually drive, so that a circuit can be solved.
#: `webui/boards/atmega328p.py`'s `SUPPLY` carries the long version of why the
#: resistances are stated as upper bounds; the short version is that each comes
#: from a guaranteed datasheet corner, so every current computed through it is
#: a lower bound and the page may warn but may never reassure.
#:
#: **This part is far weaker than the AVR and the numbers say so.** A SAM D21
#: pin at its reset drive strength is specified to source two milliamps; an
#: ATmega328P pin is specified at twenty. An LED on a XIAO is dim for a reason.
#:
#: **DRVSTR = 0 is an assumption, and it is the reset value.** `PORT.PINCFG`'s
#: reset state has the bit clear, `install_port` above stores that byte without
#: interpreting any bit of it, and the Arduino SAMD core's `pinMode` does not
#: set it. Firmware that did would double these currents and nothing here would
#: notice -- which is a limitation of the board description, recorded here
#: rather than discovered later.
SUPPLY: dict[str, object] = {
    "chip": "SAMD21",
    "volts": 3.3,
    "source_ohms": 330.0,
    "sink_ohms": 264.0,
    "rated_amps": 0.002,
    # **Absent, and it is a real absence.** The SAM D21 states no per-pin
    # absolute maximum at all -- its limit is per CLUSTER, and this repository
    # models no clusters. Filling this in with a plausible number would be the
    # invention `circuit.js` exists to stop.
    "absolute_amps": None,
    "cited": {
        "volts": (
            "the board's own silkscreen: both XIAO SAMD21 pad maps carry a "
            "`3V3_OUT` pad and no other rail but `VBUS`, and "
            "`webui/boards/XIAO-SAMD21-DIP.json` got those labels from Seeed's "
            "own CAD"
        ),
        "source_ohms": (
            "derived: (3.3 - 0.8 * 3.3) / 0.002. SAM D21/DA1 Family datasheet "
            "DS40001882L (Microchip, 2026), Table 37-15 `Normal I/O Pins "
            "Characteristics` on page 916: VOH min 0.8*VDD at IOH max, and "
            "IOH max 2 mA for VDD = 3 - 3.63 V with PORT.PINCFG.DRVSTR = 0"
        ),
        "sink_ohms": (
            "derived: (0.2 * 3.3) / 0.0025. Same table, same page: VOL max "
            "0.2*VDD at IOL max, and IOL max 2.5 mA for VDD = 3 - 3.63 V with "
            "PORT.PINCFG.DRVSTR = 0"
        ),
        "rated_amps": (
            "the smaller of the two limits in that table, the 2 mA source "
            "figure. Sinking is rated 2.5 mA; one number is quoted and it is "
            "the one that binds first"
        ),
        "absolute_amps": (
            "there is not one. DS40001882L Table 37-2 on page 906 gives "
            "absolute maxima per VDD and GND PIN, and its note 1 reads "
            "`Maximum source current is 46mA and maximum sink current is 65mA "
            "per cluster` -- a group of GPIOs, not a pin"
        ),
    },
}

# --- the clock tree ---------------------------------------------------------
#
# Every address in this section is read from the same generated headers as the
# ones above, and every one of them is reached by the image in
# `tests/cortexm0/test_samd21_arduino.py` before it gets to `setup()`.

#: NVMCTRL, from `samd21g18a.h:384` -- `#define NVMCTRL (0x41004000UL)`.
NVMCTRL = 0x41004000
#: `CTRLB`, `component/nvmctrl.h:338`, offset 0x04 (R/W 32). The **first**
#: peripheral access any Arduino SAMD image makes: `SystemInit` sets the flash
#: read wait states twelve instructions in, before any clock is touched.
NVMCTRL_CTRLB = 0x04

#: PM, from `samd21g18a.h:395` -- `#define PM (0x40000400UL)`.
PM = 0x40000400
#: The word at 0x08 holds four byte-wide registers -- `CPUSEL` (0x08),
#: `APBASEL` (0x09), `APBBSEL` (0x0A) and `APBCSEL` (0x0B),
#: `component/pm.h:513-516` -- and `SystemInit` writes all four in a row.
#: One mapped word serves them because a byte write reaches its own byte.
PM_CPUSEL = 0x08
#: `APBAMASK`, `component/pm.h:519`, offset 0x18 (R/W 32).
PM_APBAMASK = 0x18
#: `APBCMASK`, `component/pm.h:521`, offset 0x20 (R/W 32).
PM_APBCMASK = 0x20

#: Reset values, from `component/pm.h:287` and `:373`. Given rather than left
#: at zero because the firmware read-modify-writes both -- `PM->APBAMASK.reg |=
#: PM_APBAMASK_GCLK` -- so a register starting at zero would silently clear
#: six enables that a real part has set before the first instruction.
PM_APBAMASK_RESET = 0x0000007F
PM_APBCMASK_RESET = 0x00010000

#: SYSCTRL, from `samd21g18a.h:405` -- `#define SYSCTRL (0x40000800UL)`.
SYSCTRL = 0x40000800
#: `PCLKSR`, `component/sysctrl.h:918`, offset 0x0C and marked `__I` -- the
#: only read-only register in this section, and the one every wait loop reads.
SYSCTRL_PCLKSR = 0x0C
#: `XOSC32K`, `:921`, offset 0x14 (R/W 16).
SYSCTRL_XOSC32K = 0x14
#: `OSC8M`, `:926`, offset 0x20 (R/W 32).
SYSCTRL_OSC8M = 0x20
#: `DFLLCTRL`, `:927`, offset 0x24 (R/W 16).
SYSCTRL_DFLLCTRL = 0x24
#: `DFLLMUL`, offset 0x2C (R/W 32).
#:
#: `DFLLVAL` at 0x28 sits between them and is **not** modelled, which is the
#: measurement rather than an oversight: `startup.c` writes it only inside its
#: `#if defined(CRYSTALLESS)` branch, and the XIAO SAMD21 has a crystal.
SYSCTRL_DFLLMUL = 0x2C

#: Reset values, `component/sysctrl.h:371`, `:481` and `:539`. `OSC8M`'s
#: matters most: `SystemInit` does `SYSCTRL->OSC8M.bit.PRESC = 0`, a
#: read-modify-write, and starting from zero would write back a disabled
#: oscillator.
SYSCTRL_XOSC32K_RESET = 0x0080
SYSCTRL_OSC8M_RESET = 0x87070382
SYSCTRL_DFLLCTRL_RESET = 0x0080

#: What `PCLKSR` answers: every ready and every lock bit set at once. See the
#: module docstring -- the accurate answer for a part with no analogue in it,
#: and the one thing it cannot express is how long a real clock takes.
CLOCKS_ALL_READY = 0xFFFFFFFF

#: GCLK, from `samd21g18a.h:380` -- `#define GCLK (0x40000C00UL)`.
GCLK = 0x40000C00
#: The word at 0x00 holds three registers of different widths:
#: `CTRL` (0x0, R/W 8), `STATUS` (0x1, `__I` 8) and `CLKCTRL` (0x2, R/W 16),
#: `component/gclk.h:300-302`. **`SYNCBUSY` is bit 7 of `STATUS`**, so the
#: byte that decides whether every `while (GCLK->STATUS.reg & SYNCBUSY)` in
#: the framework terminates is byte 1 of this word. Nothing writes byte 1, so
#: it reads zero, so the wait ends -- which is the right answer for a model
#: with no clock domains to cross.
GCLK_CTRL = 0x00
#: `GENCTRL`, `:303`, offset 0x04 (R/W 32).
GCLK_GENCTRL = 0x04
#: `GENDIV`, `:304`, offset 0x08 (R/W 32).
GCLK_GENDIV = 0x08

#: ADC, from `samd21g18a.h:374` -- `#define ADC (0x42004000UL)`.
#:
#: A blink does not convert anything, and Arduino's `init()` configures the ADC
#: for it anyway -- eight writes and two waits before `setup()` runs. So these
#: are here for the same reason the clock tree is: the image reaches them.
ADC = 0x42004000
#: The word at 0x00 holds `CTRLA`, `REFCTRL`, `AVGCTRL` and `SAMPCTRL`, all
#: byte-wide, `component/adc.h:668-671`.
ADC_CTRLA = 0x00
#: `CTRLB`, `:672`, offset 0x04 (R/W 16).
ADC_CTRLB = 0x04
#: `INPUTCTRL`, `:678`, offset 0x10 (R/W 32).
ADC_INPUTCTRL = 0x10
#: The word at 0x18 holds `INTFLAG` (0x18, 8), `STATUS` (0x19, `__I` 8) and
#: `RESULT` (0x1A, `__I` 16), `component/adc.h:487-532`. **`SYNCBUSY` is bit 7
#: of `STATUS`**, byte 1 of this word, and `init()` spins on it twice.
ADC_INTFLAG = 0x18
#: `CALIB`, `component/adc.h:624`, offset 0x28 (R/W 16). Written by `init()`
#: from the calibration row below, which is why both exist or neither works.
ADC_CALIB = 0x28

#: DAC, from `samd21g18a.h:375` -- `#define DAC (0x42004800UL)`.
DAC = 0x42004800
#: The word at 0x00 holds `CTRLA`, `CTRLB` and `EVCTRL`, `component/dac.h:270-272`.
DAC_CTRLA = 0x00
#: The word at 0x04 holds `INTENCLR`, `INTENSET`, `INTFLAG` and `STATUS`
#: (0x07, `__I` 8), `component/dac.h:274-277`. **`SYNCBUSY` is bit 7 of
#: `STATUS`**, byte 3 of this word.
DAC_INTENCLR = 0x04

#: The NVM software calibration row, `samd21g18a.h:389` --
#: `#define NVMCTRL_OTP4 (0x00806020UL)`. Eight bytes, and both words of it are
#: read: the DFLL trim from the first, and `ADC_FUSES_BIASCAL_ADDR`, which
#: `component/nvmctrl.h:376` defines as `NVMCTRL_OTP4 + 4`, from the second.
#:
#: **A region and not a register**, because it is flash -- outside the 256K
#: program flash, in the auxiliary space, which is why `install_memory` adds it
#: rather than `install_clocks` mapping it.
CALIBRATION = 0x00806020
CALIBRATION_SIZE = 8


class Cpu(typing.Protocol):
    """What this module needs of a core: the mapping calls it uses.

    Still narrower than `rp2040.py`'s by one method -- nothing here mirrors,
    because the SAMD21 has no ready-follows-enable register on either image's
    path. `map_constant` joined it when the clock tree did: `PCLKSR` is
    `__I` in the header and is the one register in this file that answers
    something firmware never wrote. The protocol states what this board needs
    rather than what a board might.
    """

    def map_register(self, address: int, value: int = 0) -> None: ...
    def map_alias(self, address: int, target: int, op: str, *,
                  readable: bool = ...) -> None: ...
    def map_constant(self, address: int, value: int) -> None: ...
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

    **The calibration row is a third region, not a peripheral.** It is flash in
    the auxiliary space, and `SystemInit` and `init()` both read it.

    It reads **erased**, and that is a limit worth stating rather than hiding:
    a real part is trimmed at the factory and this model has no trim to offer,
    so 0xFF is the honest stand-in -- it is what an unprogrammed part reads,
    and the ADC bias and linearity it yields are legal values. What they are
    not is *this* part's. Firmware that expects a converted voltage to be
    accurate will be disappointed by a number rather than by a fault, and
    nothing here can do better without a device to read one off.

    Not executable, because nothing executes from a fuse row and a jump into
    one should say so rather than run 0xFF as an instruction.
    """
    cpu.add_region(FLASH, FLASH_SIZE, executable=True, fill=FLASH_ERASED)
    cpu.add_region(SRAM, SRAM_SIZE, executable=True, fill=0x00)
    cpu.add_region(CALIBRATION, CALIBRATION_SIZE, executable=False,
                   fill=FLASH_ERASED)


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

    # `PINCFG`, which is what `pinMode` actually writes. `INEN`, `PULLEN` and
    # `PMUXEN` all live in one byte per pin, and `pinMode` reads the byte back
    # to change one bit of it -- so this has to be a stored register and not a
    # constant, or every `pinMode` would undo the last one.
    #
    # **`WRCONFIG` at 0x28 is the other way to write the same bits and is
    # deliberately not here.** This framework's `pinMode` uses `PINCFG`
    # directly; a board that modelled both would have two paths to one piece of
    # state and only one of them exercised.
    for index in range(PORT_GROUPS):
        base = group(index)
        for word in range(PORT_PINCFG_WORDS):
            cpu.map_register(base + PORT_PINCFG + 4 * word, 0)


def install_clocks(cpu: Cpu) -> None:
    """What `SystemInit` configures before `main` runs, and nothing more.

    A blink needs none of this -- PORT is clocked out of reset -- and a vendor
    Arduino image walks the whole tree anyway: flash wait states, the 32 kHz
    crystal, the DFLL, four generic clock generators and the APB dividers. It
    reaches the first of them twelve instructions in.

    **`PCLKSR` is the one that decides whether any of it terminates**, and it
    is the only `map_constant` here. See the module docstring for why "every
    clock is ready" is the accurate answer rather than the convenient one, and
    for the four poll directions this has to get right.
    """
    cpu.map_register(NVMCTRL + NVMCTRL_CTRLB, 0)

    cpu.map_register(PM + PM_CPUSEL, 0)
    cpu.map_register(PM + PM_APBAMASK, PM_APBAMASK_RESET)
    cpu.map_register(PM + PM_APBCMASK, PM_APBCMASK_RESET)

    cpu.map_constant(SYSCTRL + SYSCTRL_PCLKSR, CLOCKS_ALL_READY)
    cpu.map_register(SYSCTRL + SYSCTRL_XOSC32K, SYSCTRL_XOSC32K_RESET)
    cpu.map_register(SYSCTRL + SYSCTRL_OSC8M, SYSCTRL_OSC8M_RESET)
    cpu.map_register(SYSCTRL + SYSCTRL_DFLLCTRL, SYSCTRL_DFLLCTRL_RESET)
    cpu.map_register(SYSCTRL + SYSCTRL_DFLLMUL, 0)

    # **The residual, stated rather than buried.** `GCLK.CTRL.SWRST` is
    # write-one-and-self-clearing on silicon, and a stored register keeps it
    # set. Nothing in this framework polls it alone -- `startup.c:93` is
    # `while ((CTRL & SWRST) && (STATUS & SYNCBUSY))`, and `STATUS` reads zero,
    # so the loop ends on its second term. Firmware that polled `SWRST` by
    # itself would spin here, and this is the line that would have to change.
    #
    # A constant reading zero would fix that and break something worse:
    # `CLKCTRL` shares this word, is genuinely read/write, and would stop
    # reading back what was written.
    cpu.map_register(GCLK + GCLK_CTRL, 0)
    cpu.map_register(GCLK + GCLK_GENCTRL, 0)
    cpu.map_register(GCLK + GCLK_GENDIV, 0)


def install_analog(cpu: Cpu) -> None:
    """The ADC and DAC control registers Arduino's `init()` writes.

    Neither converts anything. **These are configuration registers and there is
    no converter behind them**, which is a real limit and not a rounding of
    one: `analogRead` would set `SWTRIG.START` and then wait on
    `INTFLAG.RESRDY`, and `SWTRIG` is not modelled, so it faults at a named
    address instead of returning a made-up voltage. That is the intended
    behaviour -- the failure this repository ranks worst is a plausible number.

    They are here because `init()` writes them on the way to `setup()`, so
    without them no sketch runs at all.
    """
    cpu.map_register(ADC + ADC_CTRLA, 0)
    cpu.map_register(ADC + ADC_CTRLB, 0)
    cpu.map_register(ADC + ADC_INPUTCTRL, 0)
    cpu.map_register(ADC + ADC_INTFLAG, 0)
    cpu.map_register(ADC + ADC_CALIB, 0)

    cpu.map_register(DAC + DAC_CTRLA, 0)
    cpu.map_register(DAC + DAC_INTENCLR, 0)


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    `"high"`, `"low"` or `"input"`, keyed by the label on the silkscreen.
    `webui.api.pin_view` is the caller, and it finds this by `getattr` exactly
    as it finds `uart0_output` -- so a board with no such function is reported
    as a board that cannot answer, rather than as a board whose pins are low.

    **A label absent from `HEADER` is absent from the result**, and that is the
    contract rather than an accident. The three power pads a XIAO carries --
    `3V3_OUT`, `GND`, `VBUS` -- have no MCU pin behind them and never will, and
    returning `"low"` for `GND` would be a sentence about the program when the
    truth is a sentence about the board.

    **`DIR` decides before `OUT` does.** A pin configured as an input has no
    driven level at all, and reading `OUT` for it would report the value the
    output driver *would* use if it were enabled -- which is exactly the
    plausible-but-wrong answer `install_port` refuses for `IN`. A pull-up makes
    an input read high on real silicon and this model has no pulls, so `input`
    is as far as it can honestly go.
    """
    states: dict[str, str] = {}
    for label, (index, bit) in HEADER.items():
        base = group(index)
        mask = 1 << bit
        if not cpu.read_word(base + PORT_DIR) & mask:
            states[label] = "input"
        else:
            states[label] = "high" if cpu.read_word(base + PORT_OUT) & mask else "low"
    return states


def install(cpu: Cpu) -> None:
    """Every region and peripheral this board models, which is not every one.

    **Precondition: no region may already cover this board's map.** Regions
    refuse to overlap, so a caller that installed memory of its own -- the test
    suite's bare SRAM, for instance -- must `clear_regions()` first.

    There is no flag for "just enough for a blink". The clock tree costs three
    dozen dictionary entries and a board that had two shapes would need every
    caller to know which one it wanted -- which is the parameter rule 7 says to
    split rather than add. A real SAMD21 has a clock tree whether or not the
    program running on it configures one.
    """
    install_memory(cpu)
    install_port(cpu)
    install_clocks(cpu)
    install_analog(cpu)
