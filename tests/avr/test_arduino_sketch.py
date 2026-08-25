# OpenHardware — a vendor Arduino sketch, executed on the Uno board.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## This is OH-58's Done-when
#
# The ticket opened on a measurement: a real sketch compiled against
# `framework-arduino-avr` stopped on its FIRST instruction —
#
#     STOPPED after 0 steps: Unimplemented: no implementation for 0x940c at
#     word 0x0000
#
# — because 0x940C is the `JMP` in the reset vector and `core/avr` had been
# sized to one hand-written image. This file is the other end of that: the same
# kind of sketch, crossing the vector table, through `setup()`, into `loop()`.
#
# ## Why it builds rather than loading a committed binary
#
# `tests/avr/blink/blink.bin` is committed because 46 bytes of `-nostdlib`
# assembly is this repository's own work. **This image is not**, and the
# difference is the licence: linking Arduino's core makes the result a
# derivative of LGPL-2.1 code, and `rules/licence-hygiene.md` keeps this tree
# MIT with nothing vendored. So the sketch source is here and the toolchain is
# not, exactly as `docs/esp-idf-reference.md` arranges the ESP-IDF headers and
# `tools/gen_avr_corpus.mjs` arranges avr8js.
#
# It **skips** without the framework and never passes quietly, which is the
# rule `CLAUDE.md` states for the rule checkers and the reason it is a rule.
#
# ## What it does not claim
#
# That the sketch *blinks*. It does not, and the reason is not the instruction
# set — see `test_the_sketch_stops_making_progress_inside_delay`. `delay()`
# waits on `micros()`, `micros()` reads timer 0, and
# `webui/boards/atmega328p.py` maps no timer, so `TCNT0` reads the zero it was
# written. That is the next ticket and it is named in the assertion rather than
# left as a silence.

import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from webui import api
from webui.boards import atmega328p

HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "arduino" / "blink.cpp"

#: The board, spelled as `webui/boards/catalogue.py`'s `IRREGULAR` spells it.
BOARD = "Arduino Uno"

#: PB5, through the board description rather than as a literal.
LED = 1 << atmega328p.LED_PIN

#: `TCNT0` is `_SFR_IO8(0x26)` in `iom328p.h:212`, so 0x46 in the data space.
#: Named here because the assertion about it is the point of the last test.
TCNT0 = 0x46

#: Enough steps for `setup()`, the first `digitalWrite`, and several thousand
#: turns of the `delay()` spin. The whole sketch reaches `loop()` inside 200.
BUDGET = 50_000


def toolchain() -> tuple[pathlib.Path, pathlib.Path]:
    """Where avr-g++ and the Arduino core are, or a skip saying they are not.

    PlatformIO's layout, because that is where every other AVR fact in this
    repository was read from. `$USERPROFILE` rather than `~`: Git Bash here
    sets `HOME` to a redirect and `~/.platformio` resolves to nothing.
    """
    found = shutil.which("avr-g++")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        os.environ.get("USERPROFILE", pathlib.Path.home()),
        ".platformio/packages/toolchain-atmelavr/bin/avr-g++.exe",
    )
    if not gcc.is_file():
        pytest.skip(f"no avr-g++ on PATH or at {gcc}")

    framework = pathlib.Path(
        os.environ.get("USERPROFILE", pathlib.Path.home()),
        ".platformio/packages/framework-arduino-avr",
    )
    if not (framework / "cores" / "arduino" / "Arduino.h").is_file():
        pytest.skip(
            f"no framework-arduino-avr at {framework}. Install it with:\n"
            f"  pio pkg install --global --tool framework-arduino-avr"
        )
    return gcc, framework


@pytest.fixture(scope="module")
def sketch() -> tuple[bytes, dict[str, int]]:
    """Compile and link the sketch, and return its image and its symbols.

    Module-scoped: five tests want the same image and the link takes a second.
    The symbol table comes from `avr-nm` rather than from constants here,
    because addresses move whenever the framework version does — and a test
    that hardcoded 0xE8 for `loop` would go quietly wrong rather than loudly.
    """
    pytest.importorskip("core.avr.abi")
    gcc, framework = toolchain()
    core = framework / "cores" / "arduino"
    variant = framework / "variants" / "standard"
    objcopy = gcc.with_name(gcc.name.replace("g++", "objcopy"))
    nm = gcc.with_name(gcc.name.replace("g++", "nm"))

    # `avr-gcc` for the C sources and `avr-g++` for the C++ ones. Not
    # interchangeable: `-fno-threadsafe-statics` is a hard error on a `.c`
    # file, which is how the first version of this fixture failed.
    cc = gcc.with_name(gcc.name.replace("g++", "gcc"))
    flags = [
        "-mmcu=atmega328p", "-DF_CPU=16000000L", "-DARDUINO=10808",
        "-DARDUINO_AVR_UNO", "-DARDUINO_ARCH_AVR",
        f"-I{core}", f"-I{variant}",
        "-Os", "-ffunction-sections", "-fdata-sections",
    ]
    # `main.cpp` is what calls `setup()` and then `loop()` forever; the other
    # three are what `pinMode`, `digitalWrite` and `delay` live in. Compiling
    # the whole core would work and take twenty times as long.
    sources = [
        SKETCH,
        core / "main.cpp",
        core / "hooks.c",
        core / "wiring.c",
        core / "wiring_digital.c",
    ]

    def run(command: list[str]) -> str:
        """Run a build step, and put the compiler's own words in the failure.

        `check=True` alone reports the exit status and hides the diagnostic,
        which on a toolchain that moved is the only useful part.
        """
        done = subprocess.run(command, capture_output=True, text=True)
        if done.returncode != 0:
            raise AssertionError(
                f"{pathlib.Path(command[0]).name} exited {done.returncode}\n"
                f"  {' '.join(command)}\n{done.stderr}"
            )
        return done.stdout

    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp)
        objects = []
        for source in sources:
            obj = out / (source.stem + ".o")
            cxx = source.suffix == ".cpp"
            run([str(gcc if cxx else cc), "-c", *flags,
                 *(["-fno-exceptions", "-fno-threadsafe-statics"] if cxx else []),
                 str(source), "-o", str(obj)])
            objects.append(str(obj))

        elf = out / "sketch.elf"
        image = out / "sketch.bin"
        run([str(gcc), "-mmcu=atmega328p", "-Os", "-Wl,--gc-sections",
             *objects, "-o", str(elf), "-lm"])
        run([str(objcopy), "-O", "binary", "-R", ".eeprom", str(elf), str(image)])
        listing = run([str(nm), str(elf)])

        # `avr-nm` gives BYTE addresses; the PC counts WORDS. That halving is
        # the single most likely off-by-something in an AVR test, so it happens
        # once, here.
        symbols = {}
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in ("T", "t", "W"):
                symbols[parts[2]] = int(parts[0], 16) // 2
        return image.read_bytes(), symbols


def entered(image: bytes, symbols: dict[str, int], budget: int = BUDGET) -> dict:
    """Run the image and record which functions the PC ever landed on.

    Goes through `webui/api.py` rather than driving the core, because the claim
    being made is a *board* one — `rules/board-claims.md` — and the board path
    is what has to be watched.
    """
    # Address -> every name at it. **A list and not a name**: linker-generated
    # labels share addresses with real functions, and a dict keyed the other
    # way silently keeps whichever came last — which is how an assertion about
    # `__ctors_end` came to look like the reset jmp never fired.
    watch: dict[int, list[str]] = {}
    for name, address in symbols.items():
        watch.setdefault(address, []).append(name)

    counts: dict[str, int] = {}
    with api.load_firmware(BOARD, image, base=0) as session:
        for _ in range(budget):
            for name in watch.get(session.cpu.pc, ()):
                counts[name] = counts.get(name, 0) + 1
            session.step()
        counts["#portb"] = session.cpu.read_data(atmega328p.PORTB)
        counts["#ddrb"] = session.cpu.read_data(atmega328p.DDRB)
        counts["#tcnt0"] = session.cpu.read_data(TCNT0)
        counts["#pc"] = session.cpu.pc
    return counts


# --- the headline -----------------------------------------------------------


def test_a_vendor_arduino_sketch_runs_without_meeting_an_encoding_this_core_lacks(sketch):
    """The assertion OH-58 exists to make true.

    `session.step()` raises `Unimplemented` on an encoding this core does not
    have, so fifty thousand steps that return normally is the whole claim. The
    ticket's opening measurement was zero.
    """
    image, symbols = sketch
    counts = entered(image, symbols)
    assert counts["main"] == 1, "the image never reached the C runtime"


def test_the_sketch_crosses_its_vector_table(sketch):
    """The exact instruction the ticket opened on, in one step.

    `0x940C` at word 0 is the `JMP` every Arduino image begins with. The target
    is decoded from the image rather than looked up by symbol, so what this
    asserts is that the *encoding* was read right — 22 bits of word address
    scattered across two words — and not that some name happens to be there.
    """
    image, _ = sketch
    first = int.from_bytes(image[0:2], "little")
    assert first & 0xFE0E == 0x940C, f"word 0 is {first:#06x}, not a jmp"
    target = (((first & 0x01F0) << 13) | ((first & 0x0001) << 16)
              | int.from_bytes(image[2:4], "little"))

    with api.load_firmware(BOARD, image, base=0) as session:
        assert session.cpu.pc == 0
        session.step()
        assert session.cpu.pc == target, (
            f"the reset jmp landed on {session.cpu.pc:#06x}, not {target:#06x}"
        )


def test_setup_runs_and_configures_the_led_pin_as_an_output(sketch):
    """`pinMode(13, OUTPUT)` is the whole of `setup()`, and DDRB bit 5 is what
    it does. A sketch that reached `setup` and left DDRB alone would mean the
    pin tables in program memory were read wrong — which is `lpm`."""
    image, symbols = sketch
    counts = entered(image, symbols)
    assert counts.get("setup", 0) == 1
    assert counts.get("pinMode", 0) == 1
    assert counts["#ddrb"] & LED, f"DDRB is {counts['#ddrb']:#04x}"


def test_loop_runs_and_drives_the_led_pin_high(sketch):
    """Past `setup()` and into the first statement of `loop()`.

    PORTB bit 5 set is `digitalWrite(13, HIGH)` having executed. That is the
    farthest the sketch gets and the next assertion says why.
    """
    image, symbols = sketch
    counts = entered(image, symbols)
    assert counts.get("loop", 0) == 1
    assert counts.get("digitalWrite", 0) == 1
    assert counts["#portb"] & LED, f"PORTB is {counts['#portb']:#04x}"


def test_the_sketch_stops_making_progress_inside_delay(sketch):
    """**The remaining gap, measured rather than assumed — and it is not the
    instruction set.**

    `delay()` calls `micros()`, `micros()` reads `TCNT0` and the overflow count
    that timer 0's interrupt maintains, and `webui/boards/atmega328p.py` maps
    no timer at all. An AVR data space has no holes, so `TCNT0` is a byte of
    memory that reads back the zero it was reset to: `micros()` returns the
    same number forever and `delay(500)` never finishes.

    So `loop()` is entered exactly once and `micros()` thousands of times.
    Asserting that is what keeps the limitation visible; the alternative is a
    test that watches the LED and fails without saying which layer is missing.
    """
    image, symbols = sketch
    counts = entered(image, symbols)
    assert counts.get("loop", 0) == 1, "loop ran more than once; did a timer start?"
    assert counts.get("micros", 0) > 100, (
        f"micros was entered {counts.get('micros', 0)} times; delay() should "
        f"be spinning on it"
    )
    assert counts["#tcnt0"] == 0, "TCNT0 is still an unmapped byte of memory"
