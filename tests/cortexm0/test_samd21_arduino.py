# OpenHardware — a vendor Arduino sketch, executed on the XIAO SAMD21 board.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## This is OH-68's Done-when, and it is what OH-66 was blocked on
#
# The ticket opened on a measurement. A real Arduino-core sketch compiled for
# this board faulted on its FIRST peripheral access --
#
#     data access at 0x41004004 is outside the modelled memory
#     (instruction at 0x000020d4)
#
# -- twelve instructions into `SystemInit`, at `NVMCTRL.CTRLB`, because
# `webui/boards/samd21.py` modelled flash, SRAM and PORT and nothing else. That
# was exactly right for the bare-metal blink in `test_samd21_blink.py` and is
# not enough for a vendor core, which configures a clock tree whether the
# sketch needs one or not.
#
# Stubbing every fault and re-running produced the list the board now models:
# **twenty-seven chip registers, and not one more.** This file is the image
# that reaches them, so each of those registers has a reason to exist that is
# not "the datasheet has it".
#
# ## What this proves that `test_samd21_blink.py` does not
#
# That one is 48 bytes of `-nostdlib` assembly writing two PORT registers.
# This is 5 KB of vendor C++ that walks NVMCTRL, PM, SYSCTRL, GCLK, ADC and DAC
# before `setup()` is called, takes 6 SysTick exceptions per `delay(1)`, and
# only then reaches the line somebody typed. It is the difference between "a
# board" and "a board an Arduino sketch runs on".
#
# ## Why it builds rather than loading a committed binary
#
# The licence, and the same one as `tests/avr/test_arduino_sketch.py`: linking
# Arduino's core makes the image a derivative of LGPL-2.1 code, and
# `rules/licence-hygiene.md` keeps this tree MIT with nothing vendored. So the
# sketch source is here and the toolchain is not.
#
# It **skips** where any of the four pieces is absent and never passes quietly.
# Four, because an Arm board needs more than the AVR one did, and each skip
# names its own fix: the compiler, the Arduino core, Microchip's CMSIS device
# headers, and Seeed's variant -- which is the one that is not a PlatformIO
# package at all.
#
# ## The linker script is the trap, and it is worth reading twice
#
# Seeed's `boards.txt:154` says `flash_with_bootloader.ld` and that is right
# for a real XIAO: a UF2 bootloader owns the first 8 KB, so a sketch links at
# 0x2000. **There is no bootloader here**, and an image linked that way would
# put its vector table at 0x2000 while a Cortex-M0+ reads one at zero --
# producing an image that links, loads, and executes whatever 0xFF happens to
# decode as. So this builds with `flash_without_bootloader.ld`, and
# `webui/boards/samd21.py`'s `VECTOR_TABLE_OFFSETS` is `(0,)` for the same
# reason, from the other end.

import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0.abi import Cpu, MemoryFault
from webui.boards import samd21

HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "samd21_arduino" / "blink.cpp"
REPO = HERE.parents[1]

#: PA17, through the board description rather than as a literal.
LED = 1 << samd21.LED_PIN

#: The XIAO SAMD21 runs at 48 MHz and Arduino's `init()` asks `SysTick_Config`
#: for a millisecond, so `SYST_RVR` is 47999 and the period is one more than
#: that -- see `core/cortexm0/cpu.cc`, and `SysTick_Config`'s own `n - 1`.
#:
#: This core has no cycle model, so one SysTick tick is one retired
#: instruction. That makes a millisecond of `millis()` exactly this many
#: instructions, **by construction rather than by measurement**, which is why
#: the period below is derived and not written down.
F_CPU = 48_000_000
INSTRUCTIONS_PER_MILLISECOND = F_CPU // 1000

#: `delay(1)`, plus the sketch's own `digitalWrite` and the loop around it.
#: Measured at 48,083 on 2026-08-26, which is 0.17% over the 48,000 the
#: arithmetic gives -- so the tolerance is what a reader should look at, not
#: the measurement.
PERIOD_TOLERANCE = 0.01

#: Three half-periods and a run-up: `SystemInit` and `init()` cost about 8,400
#: instructions before `setup()` is reached.
BUDGET = INSTRUCTIONS_PER_MILLISECOND * 4


def toolchain() -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    """The four pieces, or the skip that names the missing one.

    `$USERPROFILE` rather than `~`: Git Bash here sets `HOME` to a profile
    redirect and `~/.platformio` resolves to a directory that does not exist.
    Every path in this repository spells it out for that reason.
    """
    packages = pathlib.Path(
        os.environ.get("USERPROFILE", pathlib.Path.home()), ".platformio", "packages"
    )

    found = shutil.which("arm-none-eabi-gcc")
    gcc = pathlib.Path(found) if found else (
        packages / "toolchain-gccarmnoneeabi" / "bin" / "arm-none-eabi-gcc.exe"
    )
    if not gcc.is_file():
        pytest.skip(
            f"no arm-none-eabi-gcc on PATH or at {gcc}. Install it with:\n"
            f"  pio pkg install --global --tool toolchain-gccarmnoneeabi"
        )

    framework = packages / "framework-arduino-samd"
    if not (framework / "cores" / "arduino" / "Arduino.h").is_file():
        pytest.skip(
            f"no framework-arduino-samd at {framework}. Install it with:\n"
            f"  pio pkg install --global --tool framework-arduino-samd"
        )

    # Two CMSIS packages, and they are not interchangeable. `framework-cmsis`
    # is Arm's: `core_cm0plus.h` and the intrinsics. `framework-cmsis-atmel` is
    # Microchip's device layer: `samd.h`, and the register definitions
    # `webui/boards/samd21.py` cites line by line. The Arduino core includes
    # `<samd.h>` on its second line and neither package alone provides it.
    cmsis = packages / "framework-cmsis" / "CMSIS" / "Core" / "Include"
    if not (cmsis / "core_cm0plus.h").is_file():
        pytest.skip(
            f"no CMSIS core headers at {cmsis}. Install them with:\n"
            f"  pio pkg install --global --tool framework-cmsis"
        )
    atmel = packages / "framework-cmsis-atmel" / "CMSIS" / "Device" / "ATMEL"
    if not (atmel / "samd.h").is_file():
        pytest.skip(
            f"no Microchip CMSIS device headers at {atmel}. Install them with:\n"
            f"  pio pkg install --global --tool framework-cmsis-atmel"
        )
    return gcc, framework, cmsis, atmel


def variant() -> pathlib.Path:
    """Seeed's XIAO_m0 variant, which is not a PlatformIO package.

    `framework-arduino-samd` ships Arduino's own boards -- zero, mzero, the
    MKRs -- and the XIAO is Seeed's. Its variant lives in Seeed's fork of the
    core, which this repository already fetches for pin definitions.

    The Arduino Zero variant would compile and would be a different board: it
    happens to put `LED_BUILTIN` on PA17 too, which is exactly the kind of
    coincidence that makes a wrong variant look right until a second pin is
    used.
    """
    path = REPO / "third_party" / "bsp" / "seeed-samd" / "variants" / "XIAO_m0"
    if not (path / "variant.cpp").is_file():
        pytest.skip(
            f"no Seeed SAMD variant at {path}. Fetch it with:\n"
            f"  python tools/import_pindefs.py --fetch"
        )
    return path


#: The Arduino core files this sketch reaches, and no more.
#:
#: Compiling the whole core would work and take twenty times as long, which is
#: the trade `tests/avr/test_arduino_sketch.py` and `webui/compile.py` both
#: make. `Uart.cpp` and `SERCOM.cpp` are here for a reason worth knowing:
#: Seeed's `variant.cpp` *defines* `Serial1` over SERCOM4, so its static
#: constructors reference them whether or not the sketch does.
CORE_SOURCES = (
    "main.cpp", "startup.c", "cortex_handlers.c", "delay.c", "hooks.c",
    "wiring.c", "wiring_digital.c", "wiring_analog.c", "wiring_private.c",
    "itoa.c", "WMath.cpp", "abi.cpp", "new.cpp", "Reset.cpp", "WInterrupts.c",
    "Uart.cpp", "SERCOM.cpp",
    "api/Common.cpp", "api/Print.cpp", "api/Stream.cpp", "api/String.cpp",
    "api/IPAddress.cpp",
)

#: From Seeed's `boards.txt:147-153`, minus the USB half of `build.extra_flags`.
#:
#: **`USBCON` is deliberately absent, and `CDC_ENABLED` deliberately present.**
#: `main()` calls `USBDevice.init()` and `attach()` only under `USBCON`, and a
#: USB device with no host to enumerate to is a peripheral nothing could check
#: -- `webui/boards/samd21.py` says so where it does not model one. But
#: `USBAPI.h` declares a `LineInfo` member whose type only exists under
#: `CDC_ENABLED`, so without it the *header* fails to compile, which is a bug
#: in this version of the core rather than a choice. Defining one and not the
#: other is what compiles the declaration and skips the device.
DEFINES = (
    "-DF_CPU=48000000L", "-DARDUINO=10808", "-DARDUINO_SAMD_ZERO",
    "-DARDUINO_ARCH_SAMD", "-D__SAMD21__", "-D__SAMD21G18A__",
    "-DARM_MATH_CM0PLUS", "-DSEEED_XIAO_M0", "-DCDC_ENABLED",
)


def run(command: list[str]) -> None:
    """A build step, with the compiler's own words in the failure.

    `check=True` alone reports the exit status and hides the diagnostic, which
    on a toolchain that has moved is the only useful part of it.
    """
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(
            f"{pathlib.Path(command[0]).name} exited {done.returncode}\n"
            f"  {' '.join(command)}\n{done.stderr}"
        )


def build() -> bytes:
    """Compile and link the sketch, and return the raw image."""
    gcc, framework, cmsis, atmel = toolchain()
    board = variant()
    core = framework / "cores" / "arduino"
    gxx = gcc.with_name(gcc.name.replace("gcc", "g++"))
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))

    includes = [
        f"-I{core}", f"-I{core / 'api' / 'deprecated'}",
        f"-I{core / 'api' / 'deprecated-avr-comp'}",
        f"-I{board}", f"-I{cmsis}", f"-I{atmel}",
    ]
    common = ["-mcpu=cortex-m0plus", "-mthumb", "-c", "-Os",
              "-ffunction-sections", "-fdata-sections", "-nostdlib"]

    with tempfile.TemporaryDirectory(prefix="openhardware-samd21-") as tmp:
        out = pathlib.Path(tmp)
        objects = []
        sources = [SKETCH, *(core / name for name in CORE_SOURCES),
                   board / "variant.cpp"]
        for index, source in enumerate(sources):
            obj = out / f"{index:02d}.o"
            cxx = source.suffix == ".cpp"
            # `arm-none-eabi-gcc` for C and `-g++` for C++, never one for both:
            # `-fno-threadsafe-statics` is a hard error on a `.c` file, which
            # is how the AVR sibling's fixture failed first.
            run([
                str(gxx if cxx else gcc), *common,
                *(["-std=gnu++11", "-fno-threadsafe-statics", "-fno-rtti",
                   "-fno-exceptions"] if cxx else ["-std=gnu11"]),
                *DEFINES, *includes, str(source), "-o", str(obj),
            ])
            objects.append(str(obj))

        elf = out / "sketch.elf"
        image = out / "sketch.bin"
        run([
            str(gxx), "-mcpu=cortex-m0plus", "-mthumb", "-Os",
            "-Wl,--gc-sections",
            # See the header: WITHOUT the bootloader, because there is no
            # bootloader here and a vector table at 0x2000 is unreachable.
            "-T", str(board / "linker_scripts" / "gcc"
                      / "flash_without_bootloader.ld"),
            "--specs=nano.specs", "--specs=nosys.specs",
            *objects, "-o", str(elf), "-lm",
        ])
        run([str(objcopy), "-O", "binary", str(elf), str(image)])
        return image.read_bytes()


@pytest.fixture(scope="module")
def image() -> bytes:
    """Built once for the module. Four compilers' worth of work per test would
    make this the slowest file in the suite for no extra coverage."""
    return build()


def start(cpu, image: bytes) -> None:
    """Install the board, load the image, and enter at its reset vector."""
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    samd21.install(cpu)
    cpu.write_block(samd21.FLASH, image)
    sp = cpu.read_word(samd21.FLASH)
    entry = cpu.read_word(samd21.FLASH + 4)
    cpu.set_regs([0] * 13 + [sp, 0, entry & ~1], apsr=0)


def watch(cpu, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state."""
    out = samd21.group(samd21.PORTA) + samd21.PORT_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        cpu.step()
        now = cpu.read_word(out) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


def test_the_image_links_at_zero_and_not_at_the_bootloader_offset(cpu, image):
    """The trap in this file's header, asserted rather than described.

    A stack pointer in SRAM and a Thumb entry point inside the image are what
    `flash_without_bootloader.ld` produces. Build with the other script and the
    first eight bytes are erased flash, so this fails before anything runs.
    """
    start(cpu, image)
    assert cpu.read_word(samd21.FLASH) == samd21.SRAM + samd21.SRAM_SIZE
    entry = cpu.read_word(samd21.FLASH + 4)
    assert entry & 1, f"reset vector 0x{entry:08x} has no Thumb bit"
    assert entry < len(image), f"reset vector 0x{entry:08x} is outside the image"


def test_the_whole_startup_runs_without_faulting(cpu, image):
    """**The one that made this ticket exist.**

    `SystemInit` walks NVMCTRL, PM, SYSCTRL and GCLK; `init()` adds SysTick,
    every pin's `PINCFG`, the ADC and the DAC. Any address the board does not
    model raises here, and the message names it -- which is how the list of
    twenty-seven was found in the first place.
    """
    start(cpu, image)
    watch(cpu)


def test_the_led_pin_is_configured_as_an_output_by_pinmode(cpu, image):
    """Not by this test writing `DIRSET`, but by `pinMode(LED_BUILTIN, OUTPUT)`
    going through Seeed's pin table to PA17. A blink on a pin still set to
    input is a lie the value register alone cannot catch."""
    start(cpu, image)
    watch(cpu)
    assert cpu.read_word(samd21.group(samd21.PORTA) + samd21.PORT_DIR) & LED


def test_the_led_actually_blinks(cpu, image):
    """The whole point. Two transitions is a blink; one is a pin that came on
    and stayed on, which is what a dead `delay` looks like from outside."""
    start(cpu, image)
    transitions = watch(cpu)
    assert len(transitions) >= 2, f"LED changed state {len(transitions)} times"


def test_the_blink_alternates_rather_than_only_rising(cpu, image):
    start(cpu, image)
    states = [state for _, state in watch(cpu)]
    assert states[0] is True
    assert states[1] is False


def test_the_period_is_the_millisecond_the_sketch_asked_for(cpu, image):
    """**`delay(1)`, and the number is derived rather than fitted.**

    `SysTick_Config(SystemCoreClock / 1000)` writes 47999, the period is one
    more than the reload, and one tick is one retired instruction -- so a
    millisecond is 48,000 steps by construction. What the sketch adds on top is
    its own `digitalWrite` and the loop around it, which is why there is a
    tolerance at all; measured 48,083, which is 0.17% over.

    A wrong SysTick would not fail `test_the_led_actually_blinks` -- it would
    blink at the wrong speed, which nothing else here can see.
    """
    start(cpu, image)
    steps = [step for step, _ in watch(cpu)]
    assert len(steps) >= 3, steps
    gaps = [b - a for a, b in zip(steps, steps[1:])]
    for gap in gaps:
        assert abs(gap - INSTRUCTIONS_PER_MILLISECOND) <= (
            INSTRUCTIONS_PER_MILLISECOND * PERIOD_TOLERANCE
        ), f"half period {gap} is not a millisecond of {INSTRUCTIONS_PER_MILLISECOND}"


def test_the_systick_handler_runs_at_exactly_a_millisecond(cpu, image):
    """**`delay` cannot return without this, which is what OH-67 was for.**

    `micros()` is `(_ulTickCount + PENDSTSET) * 1000` plus a sub-millisecond
    term, and `_ulTickCount` moves only inside `SysTick_Handler`. So the
    handler running is not an implementation detail of this blink -- it is the
    only reason `delay(1)` ever comes back.

    **And this one has no tolerance**, unlike the LED period above. The gap
    between handler entries is the SysTick period itself with nothing else in
    it, so it is 48,000 exactly; the LED's 48,083 is that number plus the
    sketch's own `digitalWrite` and loop. Measuring both is what separates a
    wrong reload from a wrong sketch.

    The first entry is not at zero -- `SysTick_Config` is about 4,600
    instructions into `init()` -- so the gaps are what is asserted rather than
    the absolute positions.
    """
    start(cpu, image)
    handler = cpu.read_word(samd21.FLASH + 4 * 15) & ~1
    entries = []
    for step in range(BUDGET):
        cpu.step()
        if cpu.get_regs().as_list()[15] == handler:
            entries.append(step)
    assert len(entries) >= 3, f"SysTick handler entered {len(entries)} times"
    gaps = {b - a for a, b in zip(entries, entries[1:])}
    assert gaps == {INSTRUCTIONS_PER_MILLISECOND}, sorted(gaps)


def test_an_unmodelled_peripheral_still_faults_under_a_real_image(cpu, image):
    """The board grew by twenty-seven registers and did not become permissive.

    SERCOM3 is the one to check: this image *links* `SERCOM.cpp` and
    constructs a `SERCOM` object for `Serial1`, so a model that had quietly
    started answering everything would look identical from the blink's side.
    A sketch that calls `Serial1.begin()` must stop at a named address rather
    than transmit into nothing.
    """
    start(cpu, image)
    watch(cpu, budget=1000)
    with pytest.raises(MemoryFault) as caught:
        cpu.read_word(0x42001000)  # SERCOM3, samd21g18a.h
    assert "42001000" in str(caught.value)
