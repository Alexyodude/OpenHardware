#!/usr/bin/env python3
# OpenHardware - source in, a loadable image out.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Compile a sketch for a board, using a toolchain this machine already has.

## What this is for

`webui/api.py` takes BYTES and a board name; somebody has to have built them.
`tools/import_firmware.py` finds artefacts somebody else built. This is the
third door: source, and a board name, and the bytes come back.

    from webui import compile as compiler

    built = compiler.build("Arduino Uno", "void setup(){} void loop(){}")
    if built.ok:
        api.load_firmware("Arduino Uno", built.image, base=0)
    else:
        print(built.diagnostics)      # avr-gcc's own words, line numbers and all

## The safety boundary, and it is the whole design

**The request carries source and a board name. Nothing else.** The compiler,
its flags, the framework, the linker arguments and the output format are read
out of `RECIPES` here, keyed by the chip the catalogue says that board carries.

A request that could name its own compiler, or add its own flags, is a request
that can run any program on this machine -- `-specs=`, `-B`, `@file` and plain
`-o` over something important are all ordinary compiler arguments. So the
untrusted half of the input reaches `subprocess` in exactly one place: as the
CONTENTS of a file, written into a fresh temporary directory that is removed
afterwards.

That is the same posture `webui/bridge.py` argues for at length and the one
the user chose on 2026-08-25 when this was proposed: loopback bind plus an
Origin check, and the server decides what runs.

## A compile error is a RESULT, not a fault

It is the most common thing that will happen here. `Build.ok` is false, the
compiler's own stderr is in `Build.diagnostics` with its line numbers intact,
and no exception is raised. A service that answered "build failed" would be
useless, and one that raised would make the ordinary case the exceptional
path.

What DOES raise is a request that cannot be attempted at all: an unknown
board, or a toolchain this machine does not have. `ToolchainMissing` names the
package it wanted, because "install PlatformIO's toolchain-atmelavr" is
actionable and "compile failed" is not.

## Why the recipes live here and not in the board module

`webui/boards/atmega328p.py` describes the part to a *core*: address spaces and
peripheral registers. Which compiler builds for it is a fact about this
machine's PlatformIO install, and it changes when a package is upgraded rather
than when the silicon does. Keeping them apart means a board description stays
readable to somebody who never compiles anything.
"""

from __future__ import annotations

import dataclasses
import functools
import os
import pathlib
import re
import subprocess
import tempfile
import time

from tools import board_manifest
from webui.boards import catalogue as board_catalogue
from webui.boards import esp32c3, esp32c5, esp32c6, samd21

#: Where PlatformIO puts the toolchains and frameworks.
#:
#: `$USERPROFILE` and not `~`: Git Bash on this machine sets `HOME` to a
#: profile redirect, so `~/.platformio` resolves to a directory that does not
#: exist. Measured, twice, and it is the reason every path in this repository
#: spells it out.
PACKAGES = pathlib.Path(
    os.environ.get("PLATFORMIO_CORE_DIR")
    or pathlib.Path(os.environ.get("USERPROFILE", pathlib.Path.home()), ".platformio")
) / "packages"

#: The Arduino core this repository writes itself (OH-148), because no
#: vendor's can execute on the described boards: Espressif's is a face on
#: ESP-IDF, which boots FreeRTOS and calls a mask ROM, and Arduino's RP2040
#: core is a face on mbed -- so an image built on either stops in its first
#: hundred instructions, and a Build whose output does not run is the false
#: affordance OH-140 removed. `webui/arduino/` implements exactly what the
#: board descriptions model, bare-metal, the way the blink fixtures are
#: built; its own header says the rest.
ARDUINO_LITE = pathlib.Path(__file__).resolve().parent / "arduino"

#: Where the board-support packages this project fetches itself live.
#:
#: A second root, because PlatformIO does not have everything: a XIAO's variant
#: is in Seeed's fork of the Arduino core, which is not a PlatformIO package.
#: `tools/import_pindefs.py --fetch` puts it here, and this tree is
#: git-ignored for the reason that file gives -- fetch, do not vendor.
BOARD_SUPPORT = pathlib.Path(__file__).resolve().parents[1] / "third_party" / "bsp"

#: How long one INVOCATION may take before it is killed. For a while this was
#: the whole story, and its comment claimed it stopped a hung compiler
#: "holding the server's lock forever" -- untrue twice over (OH-136): a
#: SAMD21 build is ~24 invocations plus a link and an objcopy, so the
#: per-invocation cap allowed the better part of an hour; and the build no
#: longer runs under the server's lock at all (see `emulator_server._api`).
#: The whole-build cap is `BUILD_BUDGET_SECONDS`.
TIMEOUT_SECONDS = 120

#: The whole build's wall-clock budget, enforced by `_run` shrinking every
#: invocation's timeout to what remains of it. Blowing it is a RESULT, not a
#: raise: the synthetic exit rides the same nonzero-returncode rail every
#: real compiler failure takes, and its message names the command that was
#: running -- "the toolchain hung" is actionable where silence is not.
BUILD_BUDGET_SECONDS = 300

#: A sketch larger than this is refused before a compiler is started. Not a
#: security boundary -- the body limit in `emulator_server.py` is that -- but a
#: sketch of a megabyte is a mistake and saying so beats a two-minute timeout.
MAX_SOURCE_BYTES = 256 << 10


class CompileError(Exception):
    """The build could not be attempted. Not "the code did not compile"."""


class UnknownBoard(CompileError):
    """No recipe for this board's chip."""


class ToolchainMissing(CompileError):
    """The recipe names a package this machine does not have."""


@dataclasses.dataclass(frozen=True)
class Library:
    """One framework library a sketch may `#include`, and what including costs.

    **A library is compiled only for a sketch that names its header** -- the
    Arduino IDE's own rule, kept for the reason the IDE keeps it: `Wire`
    carries the TWI interrupt handler, and an interrupt handler is pulled into
    the image by the vector table whether or not anything calls it, so
    compiling every library into every build would put the TWI handler in
    blink.

    The lookup is the same test `preamble` applies to `Arduino.h`: the
    header's name between angle brackets or quotes, anywhere in the source. A
    mention in a comment therefore compiles the library too -- a false
    positive that costs build time and image bytes, never a wrong refusal.

    Selection chooses among rows written HERE; nothing from the request names
    a path, which keeps the boundary the module docstring argues for.
    """

    header: str                #: what the sketch writes: "Wire.h"
    include: str               #: include root, relative to the framework root
    sources: tuple[str, ...]   #: compiled alongside the sketch, same root


@dataclasses.dataclass(frozen=True)
class Recipe:
    """Everything needed to build for one chip, and none of it from a request.

    `core_sources` are files of the vendor framework compiled alongside the
    sketch. Compiling the whole framework would work and take twenty times as
    long, so the list is what a sketch actually calls -- and it is a list here
    rather than a glob so that adding a file is a decision somebody made.
    """

    toolchain: str                    #: PlatformIO package holding the compiler
    prefix: str                       #: e.g. "avr-", how its binaries are named
    framework: str                    #: PlatformIO package holding the core
    core: str                         #: subdirectory of it holding the sources
    variant: str                      #: subdirectory holding pins_arduino.h
    flags: tuple[str, ...]            #: compile flags, identical for C and C++
    cxx_flags: tuple[str, ...]        #: added for C++ only; errors on C
    link_flags: tuple[str, ...]
    core_sources: tuple[str, ...]
    #: The base address `webui/api.load_firmware` should be given.
    #:
    #: **Taken from the board module, not written down here.** A flash origin
    #: is a fact about the silicon and `webui/boards/` carries those with the
    #: header line they were read from; a second copy in this table is a second
    #: thing to keep right. The Uno is the exception and stays a literal,
    #: because a Harvard part's program space starts at zero and there is no
    #: board constant to point at.
    base: int

    # --- what an Arm board needs and an AVR one does not --------------------
    #
    # Three fields, and each of them was a surprise to somebody. They are empty
    # on the Uno row, which is what "an AVR toolchain already knows this"
    # looks like in a table.

    #: Where the variant tree is, when it is **not** the framework's own.
    #:
    #: A directory under `third_party/bsp`, or empty when the variant ships
    #: with the framework. This is the single most surprising thing about
    #: building for a XIAO: `framework-arduino-samd` ships *Arduino's* boards
    #: -- zero, mzero, the MKRs -- and a XIAO is Seeed's, so its variant is in
    #: Seeed's fork of the core and not in the framework at all.
    #:
    #: Arduino's `arduino_zero` variant would compile, and would be a different
    #: board that happens to put `LED_BUILTIN` on the same pin -- the kind of
    #: coincidence that looks right until a second pin is used.
    variant_package: str

    #: The linker script, relative to the variant directory. Empty for AVR.
    #:
    #: **`avr-gcc` knows where flash starts from `-mmcu` alone and an Arm
    #: toolchain does not.** Worse, the *right* script is not the one the
    #: vendor's `boards.txt` names: a XIAO SAMD21 has a UF2 bootloader owning
    #: the first 8 KB, so a real sketch links at 0x2000 -- and there is no
    #: bootloader in an emulator, so an image built that way puts its vector
    #: table where a Cortex-M0+ never looks. It links, it loads, and it
    #: executes erased flash.
    linker_script: str

    #: Include directories outside the framework, each `<package>/<path>`
    #: under PlatformIO's packages.
    #:
    #: The Arduino SAMD core's second line is `#include <samd.h>`, which is
    #: neither Arduino's nor Arm's: it is Microchip's device layer, in
    #: `framework-cmsis-atmel`, and it needs Arm's `core_cm0plus.h` from
    #: `framework-cmsis` beside it. Two packages that nothing else here
    #: installs, which is why `toolchain_root` is not the only thing that can
    #: refuse a build.
    extra_includes: tuple[str, ...]

    #: Include directories under `third_party/bsp`, each `<package>/<path>`
    #: of a checkout `tools/import_pindefs.py --fetch` makes: the same job as
    #: `extra_includes`, from the other root.
    #:
    #: **Because PlatformIO does not have every vendor pin table.** The
    #: framework-arduinoespressif32 it installs ships the XIAO_ESP32C3 and
    #: XIAO_ESP32S3 variants and no other XIAO, while Espressif's own
    #: repository has the C5's and the C6's -- and `import_pindefs.py`
    #: already fetches that repository's whole `variants/` tree, blobless
    #: and sparse, to write the pin-map reports. So the file that tells a
    #: board page which GPIO `D10` reaches is the file a sketch compiles
    #: against, from one checkout at one revision; and it is fetched rather
    #: than vendored for the reason that tool gives. Refused, naming the
    #: fetch, when the checkout is absent -- the SAMD21's `variant_package`
    #: refusal, for a header instead of a source tree.
    bsp_includes: tuple[str, ...]

    #: The framework's own bundled libraries, each an opt-in of `Library`'s
    #: kind. What is NOT here is a statement too: neither framework ships
    #: `Servo.h` -- it lives in a separate arduino-libraries repository -- so
    #: a sketch including it is refused with the compiler's own "No such
    #: file", which is the honest answer until somebody decides to fetch it.
    libraries: tuple[Library, ...]

    #: (substring, note) pairs: when a failed build's diagnostics contain the
    #: substring, the note is appended. **For errors this table CAUSED**
    #: (OH-138): a recipe that deliberately builds without something owes the
    #: person who reaches for it the reason and the alternative, in the pane
    #: they are looking at -- not in a comment here they will never read.
    hints: tuple[tuple[str, str], ...]


#: One recipe per chip, keyed as `webui/boards/catalogue.py` spells the chip.
#:
#: **Two KINDS of row.** The Uno and SAMD21 build the vendor's own Arduino
#: core, because those cores run bare on the modelled parts. The ESP32 rows
#: build `webui/arduino/` instead -- the vendor's cannot run without the
#: RTOS and ROM nothing here models -- while the vendor still supplies what
#: a vendor honestly can: the board's own `pins_arduino.h`, riding in
#: through `extra_includes`, so `D10` is Seeed's number and not a copy.
#:
#: **Two rows, and the second one is why `Recipe` has the shape it has.** The
#: flags in neither are guessed: each row is what a test in this repository has
#: been building real sketches with, and the second copy is deliberate for the
#: reason `tests/avr/test_arduino_sketch.py` gives -- a board test proves the
#: board and this proves the service, and coupling them would make a compiler
#: bug fail a core test.
#:
#: **Twelve boards are runnable and this builds for ten of them**, over
#: five chips, because `recipe_for` keys on the *chip*: one SAMD21 row
#: serves both the DIP and the SMD, one ESP32-C3 row serves its three
#: boards, the C5 and C6 rows serve a pair each, and the Uno row serves
#: itself. Counted from `catalogue.catalogue()` against this table on
#: 2026-09-04 rather than estimated -- earlier versions of this comment
#: said four, then fourteen and six, each from adding rows to boards. A row
#: in `tools/board_manifest.py` is keyed on the board instead: `recipe_for`.
#:
#: The two without a row are the RP2040s, waiting on the same `openhardware`
#: framework the ESP32 rows use -- a Cortex-M0+ `_start` and vector table,
#: which `main.c` refuses loudly rather than guesses -- and `recipe_for`
#: names the chip rather than failing to find a compiler.
def _openhardware(*, variant: str, march: str, base: int,
                  extra_includes: tuple[str, ...] = (),
                  bsp_includes: tuple[str, ...] = ()) -> Recipe:
    """A row for a board the repository's own core serves (see ARDUINO_LITE).

    **The three ESP32 rows differ in exactly four things** -- the variant,
    the ISA string the compiler is told, the flash origin, and which root the
    vendor's pin names come from -- and everything else is the mechanism
    OH-148 built once for the C3. Written out three times it is the copy
    the C3 row's own comments warned against, so the mechanism lives here
    and each row states only what is its own. The API surface is exactly
    what the board descriptions map, and each absence a sketch can reach
    for has a hint below naming the model decision -- the hint names the
    row's OWN `oh_board.h`, which is why this is a function and not a
    constant.
    """
    header = f"webui/arduino/{variant}/oh_board.h"
    no_timer = (f"needs a timer and nothing on this board's model is one; "
                f"delay() exists, as a counted loop whose cost {header} states.")
    return Recipe(
        toolchain="toolchain-riscv32-esp",
        prefix="riscv32-esp-elf-",
        framework="openhardware",
        core="cores/openhardware",
        variant=variant,
        # No F_CPU define -- this model claims no clock, and the delay
        # constant in oh_board.h says what kind of number it is.
        flags=(
            f"-march={march}", "-mabi=ilp32",
            "-Os", "-ffunction-sections", "-fdata-sections",
        ),
        cxx_flags=("-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics"),
        # Bare metal, like the blink fixtures: no crt0, no libc start files;
        # the core's own _start is the entry and link.ld keeps it first.
        link_flags=(
            f"-march={march}", "-mabi=ilp32", "-Os",
            "-nostartfiles", "-nostdlib", "-Wl,--gc-sections",
        ),
        core_sources=("main.c", "wiring.c", "serial.cpp"),
        base=base,
        variant_package="",
        linker_script="link.ld",
        extra_includes=extra_includes,
        bsp_includes=bsp_includes,
        libraries=(),
        # Every hint names the modelling decision the absence stands on, in
        # the pane the person is looking at (the OH-138 pattern).
        #
        # **`Serial` used to be one of these and is not any more** (OH-161):
        # the three ESP32 descriptions map UART0's transmit FIFO, so the
        # symbol exists and the bytes have somewhere to go. A hint naming an
        # absence that has been filled would send a reader to look for a
        # decision nobody is making any more. What is still absent of that
        # peripheral -- the receive half, the divisors, `TXFIFO_CNT` -- is
        # unmapped rather than hinted, so it faults at a named address.
        hints=(
            ("digitalRead",
             ("digitalRead does not exist on this board's model: its "
              "webui/boards/ description leaves GPIO_IN unmapped on purpose "
              "-- on a driven pin IN follows OUT, and a stored zero would "
              "answer firmware wrongly. The build fails rather than lie.")),
            ("millis", "millis " + no_timer),
            ("micros", "micros " + no_timer),
            ("analogWrite",
             ("analogWrite needs the LEDC peripheral and this board's model "
              "maps GPIO only.")),
            ("analogRead",
             ("analogRead needs the ADC and this board's model maps GPIO "
              "only.")),
            ("attachInterrupt",
             ("this model has no interrupt controller; the emulated core "
              "executes straight-line code only.")),
        ),
    )


RECIPES: dict[str, Recipe] = {
    "ATmega328P": Recipe(
        toolchain="toolchain-atmelavr",
        prefix="avr-",
        framework="framework-arduino-avr",
        core="cores/arduino",
        variant="variants/standard",
        flags=(
            "-mmcu=atmega328p", "-DF_CPU=16000000L", "-DARDUINO=10808",
            "-DARDUINO_AVR_UNO", "-DARDUINO_ARCH_AVR",
            "-Os", "-ffunction-sections", "-fdata-sections",
        ),
        cxx_flags=("-fno-exceptions", "-fno-threadsafe-statics"),
        link_flags=("-mmcu=atmega328p", "-Os", "-Wl,--gc-sections"),
        # main.cpp is what calls setup() then loop() forever; the rest are what
        # pinMode, digitalWrite, delay and Serial live in. HardwareSerial pulls
        # in Print, Stream and WString, and virtual dispatch pulls in abi/new.
        core_sources=(
            "main.cpp", "hooks.c", "wiring.c", "wiring_digital.c",
            "HardwareSerial.cpp", "HardwareSerial0.cpp", "Print.cpp",
            "Stream.cpp", "WString.cpp", "abi.cpp", "new.cpp",
            # The second half is OH-135: with only the eleven above, 8 of 13
            # beginner idioms were "undefined reference" -- map() and
            # random() live in WMath, analogWrite/analogRead in
            # wiring_analog, attachInterrupt in WInterrupts, tone in Tone,
            # shiftOut in wiring_shift, and pulseIn spans wiring_pulse.c AND
            # the cycle-counted loop in wiring_pulse.S. Measured by building
            # each idiom, before and after.
            "wiring_analog.c", "WMath.cpp", "WInterrupts.c", "Tone.cpp",
            "wiring_shift.c", "wiring_pulse.c", "wiring_pulse.S",
        ),
        # Zero, and the one row where this is a literal: a Harvard part's
        # program space starts there and no board module has a constant to
        # point at. See `Recipe.base`.
        base=0,
        # Empty three times over, which is what "avr-gcc already knows" looks
        # like: Arduino ships the Uno's variant, `-mmcu` places flash, and the
        # framework's own headers are the only ones the core includes.
        variant_package="",
        linker_script="",
        extra_includes=(),
        bsp_includes=(),
        libraries=(
            # AVR keeps library sources under `src/`, and `Wire` is two
            # files: `Wire.cpp` is the API and `utility/twi.c` is the bus
            # state machine its interrupt handler runs. `EEPROM.h` is
            # header-only.
            Library("EEPROM.h", "libraries/EEPROM/src", ()),
            Library("SPI.h", "libraries/SPI/src",
                    ("libraries/SPI/src/SPI.cpp",)),
            Library("Wire.h", "libraries/Wire/src",
                    ("libraries/Wire/src/Wire.cpp",
                     "libraries/Wire/src/utility/twi.c")),
        ),
        hints=(),
    ),
    "ESP32-C3": _openhardware(
        variant="variants/xiao_esp32c3",
        # RV32IMC: the C3's own ISA string, the same subset the emulator is
        # configured as.
        march="rv32imc",
        base=esp32c3.IROM,
        # The vendor's own pin names for this exact board -- a freestanding
        # header of constants (#include <stdint.h> and nothing else), so
        # using it costs no RTOS and no transcription.
        extra_includes=(
            "framework-arduinoespressif32/variants/XIAO_ESP32C3",
        ),
    ),
    "ESP32-C5": _openhardware(
        variant="variants/xiao_esp32c5",
        # RV32IMAC: the base of the C5's datasheet ISA, in the spelling this
        # toolchain accepts. The riscv32-esp-elf-gcc PlatformIO installs here
        # is 8.4.0 (esp-2021r2), for which `_zicsr_zifencei` is not yet a
        # suffix (that arrives with GCC 12; Zicsr is implicit) and the Zc
        # groups the C5 also has do not exist at all. ESP-IDF's own build of
        # the part makes the same omission on purpose -- `esp32c5.py`'s
        # docstring records its ZCMP_WORKAROUND -- so the core executes the
        # datasheet's set and the compiler emits the toolchain's subset,
        # which is the normal relationship between the two.
        march="rv32imac",
        base=esp32c5.IROM,
        # From the board-support checkout and not from PlatformIO, whose
        # framework-arduinoespressif32 (3.20017.241212 here) ships the
        # XIAO_ESP32C3 and XIAO_ESP32S3 variants and no other XIAO --
        # measured 2026-09-04 by listing its `variants/`. Espressif's own
        # repository has this table (last changed a850760, 2025-12-01) and
        # `tools/import_pindefs.py --fetch` already brings it; see
        # `Recipe.bsp_includes`. A freestanding header, like the C3's.
        bsp_includes=("arduino-esp32/variants/XIAO_ESP32C5",),
    ),
    "ESP32-C6": _openhardware(
        variant="variants/xiao_esp32c6",
        # RV32IMAC: the whole of the C6's ISA string, in the same spelling
        # and for the same toolchain reason as the C5 row above.
        march="rv32imac",
        base=esp32c6.IROM,
        # The same checkout, for the C5 row's reason (this table last changed
        # 38d6ed5, 2024-08-02). NOT freestanding: its first line includes
        # ESP-IDF's `soc/soc_caps.h` and then uses nothing from it, so the
        # variant directory carries an empty header of that name, and that
        # header's comment is where the argument lives.
        bsp_includes=("arduino-esp32/variants/XIAO_ESP32C6",),
    ),
    "SAMD21": Recipe(
        toolchain="toolchain-gccarmnoneeabi",
        prefix="arm-none-eabi-",
        framework="framework-arduino-samd",
        core="cores/arduino",
        variant="variants/XIAO_m0",
        # From Seeed's own `boards.txt:147-153`, minus the USB half.
        #
        # **`USBCON` is absent and `CDC_ENABLED` present**, which looks
        # backwards and is not. `main()` calls `USBDevice.init()` and
        # `attach()` only under `USBCON`, and a USB device with no host to
        # enumerate to is a peripheral nothing could check -- so this build
        # does not have one, and `Serial` on this board is USB CDC and
        # therefore does not work. But `USBAPI.h` declares a member whose type
        # exists only under `CDC_ENABLED`, so without it the *header* fails to
        # compile. That is a bug in this version of the core, not a choice, and
        # defining one and not the other is what compiles the declaration while
        # skipping the device.
        flags=(
            "-mcpu=cortex-m0plus", "-mthumb",
            "-DF_CPU=48000000L", "-DARDUINO=10808", "-DARDUINO_SAMD_ZERO",
            "-DARDUINO_ARCH_SAMD", "-D__SAMD21__", "-D__SAMD21G18A__",
            "-DARM_MATH_CM0PLUS", "-DSEEED_XIAO_M0", "-DCDC_ENABLED",
            "-Os", "-ffunction-sections", "-fdata-sections", "-nostdlib",
        ),
        cxx_flags=("-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics"),
        # `nano.specs` is newlib-nano and `nosys.specs` stubs the syscalls a
        # freestanding image has no kernel for. Without them the link fails on
        # `_write` and friends rather than warning about them.
        link_flags=(
            "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-Wl,--gc-sections",
            "--specs=nano.specs", "--specs=nosys.specs",
        ),
        # Longer than the Uno's, and the last two are the ones a reader would
        # not predict: Seeed's `variant.cpp` *defines* `Serial1` over SERCOM4,
        # so its static constructors reference `Uart` and `SERCOM` whether or
        # not the sketch mentions either. `startup.c` is the clock tree,
        # `cortex_handlers.c` is the vector table, and `variant.cpp` itself is
        # added by `build` because it is not in the core directory.
        core_sources=(
            "main.cpp", "startup.c", "cortex_handlers.c", "delay.c", "hooks.c",
            "wiring.c", "wiring_digital.c", "wiring_analog.c",
            "wiring_private.c", "itoa.c", "WMath.cpp", "abi.cpp", "new.cpp",
            "Reset.cpp", "WInterrupts.c", "Uart.cpp", "SERCOM.cpp",
            "api/Common.cpp", "api/Print.cpp", "api/Stream.cpp",
            "api/String.cpp", "api/IPAddress.cpp",
            # OH-135's four: tone, shiftOut and pulseIn were "undefined
            # reference" here exactly as on the Uno, and this core spells
            # pulse's pair `pulse.c`/`pulse_asm.S` where AVR says
            # `wiring_pulse.c`/`.S`.
            "Tone.cpp", "wiring_shift.c", "pulse.c", "pulse_asm.S",
        ),
        base=samd21.FLASH,
        variant_package="seeed-samd",
        # WITHOUT the bootloader. See `Recipe.linker_script`: the vendor's own
        # `boards.txt:154` names the other one, and it is right for a real
        # XIAO and wrong for every emulated one.
        linker_script="linker_scripts/gcc/flash_without_bootloader.ld",
        extra_includes=(
            "framework-cmsis/CMSIS/Core/Include",
            "framework-cmsis-atmel/CMSIS/Device/ATMEL",
        ),
        bsp_includes=(),
        libraries=(
            # This core keeps each library at its own root -- no `src/` --
            # and its `Wire.cpp` is single-file: the bus state machine the
            # AVR keeps in `utility/twi.c` lives in this core's own
            # `SERCOM.cpp`, which `core_sources` already compiles.
            Library("SPI.h", "libraries/SPI", ("libraries/SPI/SPI.cpp",)),
            Library("Wire.h", "libraries/Wire",
                    ("libraries/Wire/Wire.cpp",)),
        ),
        # The obvious thing to type at a page that shows a UART console is
        # `Serial`, and this build refuses it ON PURPOSE -- the USBCON note
        # up at `flags` is the argument. The refusal used to be gcc's bare
        # "'Serial' was not declared in this scope; did you mean 'Serial_'?",
        # which sends a person to `Serial_` -- a USB type that is more wrong.
        hints=((
            "'Serial' was not declared",
            ("note: this build has no USB device on purpose -- `Serial` on a "
             "XIAO is USB-CDC, and an emulated board has no host to enumerate "
             "to. The UART this page's console shows is `Serial1`."),
        ),),
    ),
}


@dataclasses.dataclass(frozen=True)
class Build:
    """What a build produced.

    Exactly one of `image` and a non-empty `diagnostics` is meaningful, and
    `ok` is the only thing a caller should branch on -- a zero-length image
    from a sketch that defines nothing is still a successful build.
    """

    ok: bool
    image: bytes
    diagnostics: str
    #: What was run, so a failure that is not the sketch's fault can be
    #: reproduced by hand. Rule 9: an error carries the values that caused it.
    command: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """What the wire carries. The image is left out on purpose.

        Bytes do not survive JSON, and the caller that wants them is in this
        process. `/api/compile` builds and loads in one step for that reason,
        so an image never crosses the wire in either direction.
        """
        return {
            "ok": self.ok,
            "bytes": len(self.image),
            "diagnostics": self.diagnostics,
            "command": list(self.command),
        }


def recipe_for(board: str) -> Recipe:
    """The recipe for a board, by the chip the catalogue says it carries.

    Keyed on the chip rather than the board name because four XIAO variants of
    one part build identically -- and because the catalogue is already the one
    place that maps a board to its silicon. A row in tools/board_manifest.py
    is the exception: its chip's recipe with its own pin table, `own_variant`,
    or a refusal naming what that table needs and this build lacks.
    """
    try:
        chip = board_catalogue.chip_for(board)
    except board_catalogue.CatalogueError as exc:
        # Re-raised as this module's own type, with the catalogue's reason
        # kept: "does not start with XIAO-" is the actionable half and losing
        # it would leave "unknown board" and nothing else.
        raise UnknownBoard(f"{board!r}: {exc}") from exc
    recipe = RECIPES.get(chip)
    if recipe is None:
        buildable = ", ".join(sorted(RECIPES)) or "none"
        raise UnknownBoard(
            f"{board} carries a {chip} and nothing here knows how to build for "
            f"one. Chips with a recipe: {buildable}."
        )
    row = next((r for r in board_manifest.ROWS if r.board == board), None)
    if row is None:
        return recipe
    recipe = own_variant(row, recipe)
    missing, answered = unmet(recipe)
    if missing:
        # rules/board-claims.md §6: never the chip's table in its place.
        raise UnknownBoard(
            f"{board} is a row in tools/board_manifest.py, and its own pin "
            f"table, {row.package} variants/{row.variant}/pins_arduino.h, "
            f"cannot be compiled here ({answered}): {'; '.join(missing)}"
        )
    return recipe


def own_variant(row: board_manifest.Row, recipe: Recipe) -> Recipe:
    """`recipe`, the row's chip's, with the row's variant as its only pin table.

    Only an `openhardware` recipe takes its pin names from `extra_includes`
    and `bsp_includes` alone, so only one can swap them; its `variant`
    directory keeps the chip's link script and registers, which
    `test_the_oh_board_header_restates_the_descriptions_own_numbers` holds
    to the chip's description. Any other recipe compiles a variant's
    sources, and is refused rather than built against a sibling's.
    """
    if recipe.framework != "openhardware":
        raise UnknownBoard(
            f"{row.board} is a row in tools/board_manifest.py, and the {row.chip} "
            f"recipe compiles {recipe.variant} from {recipe.variant_package or recipe.framework}"
            f", which is another board's; nothing here builds against "
            f"{row.package} variants/{row.variant}"
        )
    return dataclasses.replace(
        recipe,
        extra_includes=(),
        bsp_includes=(f"{row.package}/variants/{row.variant}",),
    )


_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
#: `#include "..."`; an angle-bracket include is the toolchain's.
_QUOTED_INCLUDE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', re.MULTILINE)
#: `#define NAME body`, the body possibly empty.
_MACRO = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)[ \t]*(.*)$", re.MULTILINE)
#: `static const <type> NAME = <expression>;`
_CONSTANT = re.compile(r"^[ \t]*static[ \t]+const[ \t]+\w+[ \t]+(\w+)[ \t]*=([^;]+);",
                       re.MULTILINE)
#: A C identifier; a numeral's suffix does not start one.
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*")


def unmet(recipe: Recipe) -> tuple[list[str], str]:
    """What an `own_variant` recipe's pin table needs and this build lacks,
    and which answered.

    The compiler, where the recipe's toolchain is installed
    (`compiled_gaps`); the header, read, where it is not (`read_gaps`).
    Neither where the table was never fetched.
    """
    (own,) = recipe.bsp_includes
    table = BOARD_SUPPORT / own / "pins_arduino.h"
    if not table.is_file():
        return ([f"there is no {_shown(table)}; fetch it with python "
                 f"tools/import_pindefs.py --fetch"], "not asked")
    try:
        tools = toolchain_root(recipe)
    except ToolchainMissing:
        return (read_gaps(recipe),
                f"read from the header, with no {recipe.prefix}gcc here to ask")
    return (compiled_gaps(recipe, tools),
            f"asked of {recipe.prefix}g++ and {recipe.prefix}gcc -fsyntax-only")


def _shown(path: pathlib.Path) -> str:
    """`path` from this checkout's root where it is under it."""
    root = ARDUINO_LITE.parents[1]
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


#: One compiler error: its file (a Windows path's drive colon is stepped
#: over by the lazy match), its line, and what it says.
_ERROR = re.compile(r"^(.+?):(\d+):\d+: (?:fatal )?error: (.*)$", re.MULTILINE)


def compiled_gaps(recipe: Recipe, tools: pathlib.Path) -> list[str]:
    """The errors of `Arduino.h`, which every source of a build includes and
    which includes the table, compiled syntax-only with the build's flags
    and include path: as C++, the sketch's language, then as C, `main.c`'s;
    the first that fails."""
    core = framework_root(recipe) / recipe.core
    includes = (f"-I{core}", f"-I{variant_root(recipe)}",
                *(f"-I{root}" for root in include_roots(recipe)))
    (own,) = recipe.bsp_includes
    table = BOARD_SUPPORT / own / "pins_arduino.h"
    text = table.read_bytes() if table.is_file() else b""
    for language, tool, extra in (("c++", "g++", recipe.cxx_flags), ("c", "gcc", ())):
        command = (_tool(tools, recipe, tool), "-fsyntax-only", "-x", language,
                   *recipe.flags, *extra, *includes, str(core / "Arduino.h"))
        errors = _syntax_errors(command, text)
        if errors:
            return list(errors)
    return []


@functools.lru_cache(maxsize=None)
def _syntax_errors(command: tuple[str, ...], table: bytes) -> tuple[str, ...]:
    """`command`'s errors, each `file:line: what`, once per command and
    table text: `/api/boards` asks of every board on every request, and
    `table` is here as the key, so a table fetched again is asked again."""
    done = _run(command, time.monotonic() + TIMEOUT_SECONDS)
    if done.returncode == 0:
        return ()
    errors = tuple(dict.fromkeys(
        f"{_shown(pathlib.Path(where))}:{line}: {what}"
        for where, line, what in _ERROR.findall(done.stderr)))
    return errors or (f"{command[0]} exited {done.returncode} naming no error: "
                      f"{done.stderr.strip()}",)


def read_gaps(recipe: Recipe) -> list[str]:
    """What an `own_variant` recipe's pin table needs and its include path
    lacks, read rather than compiled, for a machine with no compiler.

    Every quoted `#include` must be a file on the path the build gives, and
    every name a `static const` initialiser uses, through any macro it
    names, must be defined in the table or a header it includes. A macro no
    initialiser uses is compiled only where a sketch does, so it is not
    asked of. C read with regexes, so it can be wrong where the compiler is
    not: `test_every_upstream_variants_verdict_is_the_compilers` counts
    where.
    """
    (own,) = recipe.bsp_includes
    table = BOARD_SUPPORT / own / "pins_arduino.h"
    if not table.is_file():
        return [f"there is no {_shown(table)}"]
    path = (table.parent, ARDUINO_LITE / recipe.core, ARDUINO_LITE / recipe.variant)
    missing: list[str] = []
    defined: set[str] = set()
    bodies: dict[str, str] = {}
    pending, seen = [table], {table}
    while pending:
        text = _COMMENT.sub("", pending.pop().read_text(encoding="utf-8", errors="replace"))
        bodies.update(_MACRO.findall(text))
        defined |= set(bodies) | {name for name, _ in _CONSTANT.findall(text)}
        for name in _QUOTED_INCLUDE.findall(text):
            found = next((d / name for d in path if (d / name).is_file()), None)
            if found is None:
                missing.append(f"it includes {name}, which is in none of "
                               f"{', '.join(_shown(d) for d in path)}")
            elif found not in seen:
                seen.add(found)
                pending.append(found)
    text = _COMMENT.sub("", table.read_text(encoding="utf-8", errors="replace"))
    used = {n for _, value in _CONSTANT.findall(text) for n in _IDENTIFIER.findall(value)}
    reached = list(used)
    while reached:
        for name in _IDENTIFIER.findall(bodies.get(reached.pop(), "")):
            if name not in used:
                used.add(name)
                reached.append(name)
    missing += [f"it uses {name}, which no header it reaches defines"
                for name in sorted(used - defined)]
    return missing


def toolchain_root(recipe: Recipe) -> pathlib.Path:
    """Where the compiler is, or a refusal naming the package it wanted."""
    root = PACKAGES / recipe.toolchain
    compiler = root / "bin" / f"{recipe.prefix}gcc"
    if not compiler.is_file() and not compiler.with_suffix(".exe").is_file():
        raise ToolchainMissing(
            f"no {recipe.prefix}gcc under {root}. Install it with:\n"
            f"  pio pkg install --global --tool {recipe.toolchain}"
        )
    return root


def framework_root(recipe: Recipe) -> pathlib.Path:
    """Where the core is, or a refusal naming the package.

    `openhardware` is the one framework that does not come from PlatformIO:
    it is this repository's own tree, present whenever the checkout is --
    see `ARDUINO_LITE`.
    """
    if recipe.framework == "openhardware":
        root = ARDUINO_LITE
        if not (root / recipe.core).is_dir():
            raise ToolchainMissing(
                f"no {recipe.core} under {root}; the checkout is missing its "
                f"own webui/arduino tree"
            )
        return root
    root = PACKAGES / recipe.framework
    if not (root / recipe.core).is_dir():
        raise ToolchainMissing(
            f"no {recipe.core} under {root}. Install it with:\n"
            f"  pio pkg install --global --tool {recipe.framework}"
        )
    return root


def variant_root(recipe: Recipe) -> pathlib.Path:
    """Where `pins_arduino.h` and the linker scripts are, or a refusal.

    One path out, two places it can come from, and the refusal names a
    different command for each -- which is the whole reason this is a function
    rather than a `/` in `build`. A board whose vendor also wrote its framework
    has its variant installed by PlatformIO; a XIAO does not, and telling
    somebody to `pio pkg install` a package that does not exist would send them
    in a circle.
    """
    if not recipe.variant_package:
        root = framework_root(recipe)
        fix = f"pio pkg install --global --tool {recipe.framework}"
    else:
        root = BOARD_SUPPORT / recipe.variant_package
        fix = "python tools/import_pindefs.py --fetch"
    path = root / recipe.variant
    if not path.is_dir():
        raise ToolchainMissing(f"no {recipe.variant} under {root}. Get it with:\n  {fix}")
    return path


def include_roots(recipe: Recipe) -> tuple[pathlib.Path, ...]:
    """`extra_includes` and `bsp_includes`, resolved, or a refusal naming what is out.

    The package is the first segment of each path, so a missing
    `framework-cmsis-atmel` says `framework-cmsis-atmel` rather than the
    seventy characters of directory underneath it. A board-support checkout
    is one fetch for every package, so its refusal names the fetch.
    """
    roots = []
    for relative in recipe.extra_includes:
        path = PACKAGES / relative
        if not path.is_dir():
            package = relative.split("/", 1)[0]
            raise ToolchainMissing(
                f"no {relative} under {PACKAGES}. Install it with:\n"
                f"  pio pkg install --global --tool {package}"
            )
        roots.append(path)
    for relative in recipe.bsp_includes:
        path = BOARD_SUPPORT / relative
        if not path.is_dir():
            raise ToolchainMissing(
                f"no {relative} under {BOARD_SUPPORT}. Fetch it with:\n"
                f"  python tools/import_pindefs.py --fetch"
            )
        roots.append(path)
    return tuple(roots)


def linker_script(recipe: Recipe) -> pathlib.Path | None:
    """The script this board links with, or `None` where the toolchain knows.

    `None` rather than an empty path, so `build` cannot accidentally pass
    `-T` with nothing after it -- which the linker reads as the next argument
    and fails on somewhere much less obvious.
    """
    if not recipe.linker_script:
        return None
    path = variant_root(recipe) / recipe.linker_script
    if not path.is_file():
        raise ToolchainMissing(
            f"no {recipe.linker_script} under {variant_root(recipe)}. The "
            f"variant is there and its linker scripts are not, which usually "
            f"means the fetch was narrowed."
        )
    return path


def _tool(root: pathlib.Path, recipe: Recipe, name: str) -> str:
    """One binary of the toolchain, with the platform's suffix if it needs one."""
    path = root / "bin" / f"{recipe.prefix}{name}"
    return str(path if path.is_file() else path.with_suffix(".exe"))


def build(board: str, source: str) -> Build:
    """Compile `source` for `board`, and return the image or the diagnostics.

    Raises `UnknownBoard` or `ToolchainMissing` when the build cannot be
    ATTEMPTED. A build that is attempted and fails returns `ok=False` -- see
    the module docstring for why that difference is load-bearing.
    """
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CompileError(
            f"sketch is {len(source.encode('utf-8'))} bytes, over the "
            f"{MAX_SOURCE_BYTES} this accepts"
        )
    # One deadline for the WHOLE build (OH-136): ~24 invocations each
    # entitled to TIMEOUT_SECONDS is not a bound anybody meant.
    deadline = time.monotonic() + BUILD_BUDGET_SECONDS
    recipe = recipe_for(board)
    tools = toolchain_root(recipe)
    framework = framework_root(recipe)
    core = framework / recipe.core
    variant = variant_root(recipe)
    script = linker_script(recipe)

    gcc = _tool(tools, recipe, "gcc")
    gxx = _tool(tools, recipe, "g++")
    objcopy = _tool(tools, recipe, "objcopy")

    # Which of the recipe's libraries this sketch names. Scanned on the raw
    # source rather than the preamble's output -- the preamble adds only
    # `Arduino.h`, which is not a row.
    wanted = tuple(
        lib for lib in recipe.libraries
        if f"<{lib.header}>" in source or f'"{lib.header}"' in source
    )
    includes = (f"-I{core}", f"-I{variant}",
                *(f"-I{framework / lib.include}" for lib in wanted),
                *(f"-I{root}" for root in include_roots(recipe)))
    # **A variant outside the framework is a source file as well as a header
    # directory.** Arduino's own variants are compiled from the framework by
    # naming them in `core_sources`; Seeed's cannot be, because it is not under
    # the framework at all -- and `g_APinDescription` lives in it, so an image
    # linked without it has no pin table and does not link.
    extra_sources = ((variant / "variant.cpp",) if recipe.variant_package else ())
    with tempfile.TemporaryDirectory(prefix="openhardware-build-") as tmp:
        out = pathlib.Path(tmp)
        # **The one place untrusted input reaches the filesystem**, and it is
        # as file contents in a directory that exists for this build alone.
        # The name is ours; nothing from the request chooses a path.
        sketch = out / "sketch.cpp"
        sketch.write_text(preamble(source), encoding="utf-8")

        objects: list[str] = []
        sources = [sketch, *(core / n for n in recipe.core_sources),
                   *(framework / s for lib in wanted for s in lib.sources),
                   *extra_sources]
        for index, path in enumerate(sources):
            cxx = path.suffix == ".cpp"
            # Numbered rather than named after the source: two framework files
            # could share a stem, and one silently overwriting the other's
            # object is a link error nobody could read.
            obj = out / f"{index:02d}.o"
            command = (
                _tool(tools, recipe, "g++") if cxx else gcc,
                "-c", *recipe.flags, *includes,
                *(recipe.cxx_flags if cxx else ()),
                str(path), "-o", str(obj),
            )
            done = _run(command, deadline)
            if done.returncode != 0:
                # The sketch is compiled first, so a failure here is almost
                # always the caller's -- but the command is returned either way
                # so a framework file that stopped compiling is not mistaken
                # for a syntax error in three lines of sketch.
                return Build(False, b"",
                             _hinted(_diagnostics(done, sketch), recipe),
                             command)
            objects.append(str(obj))

        elf = out / "sketch.elf"
        link = (
            gxx, *recipe.link_flags,
            *(("-T", str(script)) if script is not None else ()),
            *objects, "-o", str(elf), "-lm",
        )
        done = _run(link, deadline)
        if done.returncode != 0:
            return Build(False, b"", _diagnostics(done, sketch), link)

        image = out / "sketch.bin"
        extract = (objcopy, "-O", "binary", "-R", ".eeprom", str(elf), str(image))
        done = _run(extract, deadline)
        if done.returncode != 0:
            return Build(False, b"", _diagnostics(done, sketch), extract)

        return Build(True, image.read_bytes(), "", extract)


#: What the Arduino IDE silently puts at the top of every `.ino`, and what
#: PlatformIO does NOT put at the top of a `.cpp` -- a difference recorded in
#: OH-10's own notes after it cost somebody a build.
#:
#: **The `#line` is the load-bearing half.** Without it every diagnostic is
#: reported one line further down than the person typed, which is worse than no
#: line number at all: a number that is confidently wrong sends a reader to the
#: wrong line and they believe it.
ARDUINO_PREAMBLE = '#include <Arduino.h>\n#line 1 "sketch.cpp"\n'


def preamble(source: str) -> str:
    """`source` with the Arduino header prepended, unless it has its own.

    Left alone when the sketch already includes it, so a person who writes the
    include -- which is what a PlatformIO project does -- gets exactly the file
    they wrote and no shifted line numbers from a duplicate.

    **`#line` costs gcc's quoted source line, and that is the right trade.**
    Measured: without it a diagnostic reads

        sketch.cpp:3:22: error: expected primary-expression before ';' token
         void loop(){ int x = ; }
                              ^

    -- the caret is helpful and the number is wrong by two. With it the number
    is right and gcc drops the quote, because it can no longer map the reported
    line back to a physical one to read. The editor quotes the line instead,
    from the source the person actually typed, which is better than gcc's copy
    of a file it was handed.
    """
    if "<Arduino.h>" in source or '"Arduino.h"' in source:
        return source
    return ARDUINO_PREAMBLE + source


def _run(command: tuple[str, ...],
         deadline: float) -> subprocess.CompletedProcess[str]:
    """One invocation, inside what remains of the build's budget.

    Running out of time COMES BACK as a failed command rather than raising:
    every call site already turns a nonzero exit into a diagnosed `Build`,
    so the budget message rides the rail real compiler failures ride. 124
    because that is the exit code `timeout(1)` gave the idea to.
    """
    remaining = deadline - time.monotonic()
    if remaining > 0:
        try:
            return subprocess.run(
                command, capture_output=True, text=True,
                timeout=min(TIMEOUT_SECONDS, remaining),
            )
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            # A toolchain whose gcc exists and whose objcopy does not is a
            # broken INSTALL, not a bad sketch -- and it used to kill the
            # whole request with no response at all (OH-139). Rule 9: the
            # error carries the value that caused it. 127 is the shell's own
            # "command not found".
            return subprocess.CompletedProcess(
                command, returncode=127, stdout="",
                stderr=(f"no such tool: {command[0]} -- the compiler was "
                        f"found, so the toolchain package is incomplete. "
                        f"Reinstall it with pio pkg install."),
            )
    return subprocess.CompletedProcess(
        command, returncode=124, stdout="",
        stderr=(f"the build ran out of its {BUILD_BUDGET_SECONDS} s budget "
                f"while running {command[0]}"),
    )


def _hinted(diagnostics: str, recipe: Recipe) -> str:
    """`diagnostics`, with the recipe's note under any error its table caused.

    Appended rather than rewritten: the compiler's own words stay intact and
    first, because they carry the line number and the caret, and a hint that
    replaced them would trade the where for the why.
    """
    said = [diagnostics]
    for needle, note in recipe.hints:
        if needle in diagnostics:
            said.append(note)
    return "\n".join(said)


def _diagnostics(done: subprocess.CompletedProcess[str],
                 sketch: pathlib.Path) -> str:
    """The compiler's own words, with the temporary path taken back out.

    A person reading `C:\\Users\\...\\Temp\\openhardware-build-3f2a\\sketch.cpp:2:1`
    learns nothing from the first sixty characters, and the line number is the
    only part that matters. Replacing the path rather than stripping it keeps
    the `file:line:column:` shape an editor can parse.
    """
    text = (done.stderr or done.stdout or "").strip()
    text = text.replace(str(sketch), "sketch.cpp").replace(
        str(sketch).replace("\\", "/"), "sketch.cpp"
    )
    # The build's other paths say nothing a caller can use (OH-139): the
    # temporary directory is gone before anybody reads this, and sixty
    # characters of toolchain install path bury the one line that matters --
    # a SAMD21 link error led with eight of them. Both slash spellings of
    # each, exactly as with the sketch above.
    for root, label in ((str(sketch.parent), "<build>"),
                        (str(PACKAGES), "<toolchain>")):
        text = text.replace(root, label).replace(
            root.replace("\\", "/"), label)
    return text
