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
# ## And OH-59's, since the timer landed
#
# It used to end here, with `loop()` entered exactly once: `delay()` waits on
# `micros()`, `micros()` reads timer 0, and the board mapped no timer, so
# `TCNT0` read back the zero it was reset to and the sketch spun forever.
# `test_the_sketch_blinks_at_the_period_it_asked_for` is what that assertion
# turned into.
#
# **The period is arithmetic, not a fitted constant.** `micros()` is
# `(overflows * 256 + TCNT0) * 4`, the counter ticks every
# `INSTRUCTIONS_PER_TICK` retired instructions, and the two cancel to sixteen
# instructions per microsecond — so `delay(500)` is 8,000,000 of them and
# anything else is a defect rather than a tolerance.

import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from webui import api
from webui.boards import atmega328p

HERE = pathlib.Path(__file__).resolve().parent
BLINK = HERE / "arduino" / "blink.cpp"
SERIAL = HERE / "arduino" / "serial.cpp"

#: The board, spelled as `webui/boards/catalogue.py`'s `IRREGULAR` spells it.
BOARD = "Arduino Uno"

#: PB5, through the board description rather than as a literal.
LED = 1 << atmega328p.LED_PIN

#: Enough steps for `setup()`, the first `digitalWrite`, and several thousand
#: turns of the `delay()` spin. The whole sketch reaches `loop()` inside 200.
BUDGET = 50_000

#: The Uno's crystal, and the prescaler Arduino's `init()` selects. Both are
#: facts about the sketch's world rather than about this model, which is why
#: they are spelled out instead of folded into one ratio.
F_CPU_MHZ = 16
PRESCALER = 64

#: How many retired instructions this model calls one microsecond.
#:
#: TCNT0 advances once per `INSTRUCTIONS_PER_TICK` here and once per
#: `PRESCALER` clock cycles on the part, so one instruction is
#: `PRESCALER / INSTRUCTIONS_PER_TICK` cycles -- one, as the board says. At 16
#: MHz that is sixteen instructions to the microsecond, and the two 256s in
#: `micros()`'s own arithmetic cancel out entirely.
INSTRUCTIONS_PER_MICROSECOND = (
    F_CPU_MHZ * PRESCALER // atmega328p.INSTRUCTIONS_PER_TICK
)

#: `delay(500)`, in retired instructions. Derived rather than written down, so
#: a change to the board's approximation moves this with it.
HALF_PERIOD = 500_000 * INSTRUCTIONS_PER_MICROSECOND

#: Two half-periods, and a fifth over for the run-up through `setup()`.
BLINK_BUDGET = HALF_PERIOD * 2 + HALF_PERIOD // 5

#: How often the LED is looked at. See the blink test for the arithmetic.
SAMPLE_EVERY = 256

#: `#define UDRIE0 5` at `iom328p.h:753`. Not exported by the board, because
#: the board does not model the interrupt it enables -- it is named here only
#: so a test can assert the sketch never needed it.
UDRIE0 = 1 << 5


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


#: The Arduino core files a `Serial` sketch needs beyond the four a blink does.
#: `HardwareSerial` is the port, `Print` and `Stream` are what `println` is
#: inherited from, `WString` is what a string literal becomes, and `abi`/`new`
#: are what C++ virtual dispatch links against -- which is also what makes the
#: image reach `ijmp`.
SERIAL_SOURCES = ("HardwareSerial.cpp", "HardwareSerial0.cpp", "Print.cpp",
                  "Stream.cpp", "WString.cpp", "abi.cpp", "new.cpp")


def compile_sketch(sketch: pathlib.Path,
                   extra: tuple[str, ...] = ()) -> tuple[bytes, dict[str, int]]:
    """Compile and link one sketch, and return its image and its symbols.

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
        sketch,
        core / "main.cpp",
        core / "hooks.c",
        core / "wiring.c",
        core / "wiring_digital.c",
        *(core / name for name in extra),
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


@pytest.fixture(scope="module")
def sketch() -> tuple[bytes, dict[str, int]]:
    """The blink. Module-scoped: six tests want it and the link takes a second."""
    return compile_sketch(BLINK)


@pytest.fixture(scope="module")
def serial_sketch() -> tuple[bytes, dict[str, int]]:
    """The serial hello, which needs seven more of Arduino's own files."""
    return compile_sketch(SERIAL, SERIAL_SOURCES)


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
        counts["#tcnt0"] = session.cpu.read_data(atmega328p.TCNT0)
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


def test_the_timer_overflow_handler_is_reached(sketch):
    """`millis()` is maintained by an interrupt, and this is that interrupt.

    `__vector_16` is Arduino's `ISR(TIMER0_OVF_vect)`. Nothing calls it: it is
    reached only because the core delivers a vector, which is the half of
    OH-59 that is not a counter. Before that existed this symbol was entered
    zero times no matter how long the sketch ran.
    """
    image, symbols = sketch
    counts = entered(image, symbols)
    assert counts.get("__vector_16", 0) >= 3, (
        f"the overflow handler ran {counts.get('__vector_16', 0)} times in "
        f"{BUDGET} steps; one overflow is "
        f"{256 * atmega328p.INSTRUCTIONS_PER_TICK} instructions"
    )


def test_the_sketch_blinks_at_the_period_it_asked_for(sketch):
    """**The headline, and OH-59's Done-when.**

    `delay(500)` at 16 MHz is 8,000,000 microseconds' worth of
    `INSTRUCTIONS_PER_TICK`: `micros()` returns
    `(overflows * 256 + TCNT0) * 4`, the counter ticks every 64 retired
    instructions, and the two cancel to exactly **16 instructions per
    microsecond**. So a half-period is 8,000,000 steps and the number is
    arithmetic rather than a fitted constant.

    **This is the most expensive test in the repository, at about eight
    seconds.** Two full periods of a real 500 ms blink is sixteen million
    instructions and there is no way to watch a blink for less. It earns it:
    everything else here asserts that a mechanism behaves, and this is the only
    thing that asserts the machine does what the sketch on it says.

    PORTB is sampled every 256 steps rather than every step, which halves the
    run and places each transition to within 256 instructions -- three parts in
    a hundred thousand of the gap being measured, against a tolerance of one in
    a thousand.
    """
    image, _ = sketch
    led = 1 << atmega328p.LED_PIN
    transitions: list[int] = []
    last = 0

    with api.load_firmware(BOARD, image, base=0) as session:
        for batch in range(BLINK_BUDGET // SAMPLE_EVERY):
            for _ in range(SAMPLE_EVERY):
                session.step()
            now = session.cpu.read_data(atmega328p.PORTB) & led
            if now != last:
                transitions.append(batch * SAMPLE_EVERY)
                last = now
                if len(transitions) == 3:
                    break

    assert len(transitions) == 3, (
        f"the pin changed state {len(transitions)} times in {BLINK_BUDGET} "
        f"instructions; two full half-periods is {2 * HALF_PERIOD}"
    )
    gaps = [b - a for a, b in zip(transitions, transitions[1:])]
    for gap in gaps:
        assert abs(gap - HALF_PERIOD) <= HALF_PERIOD // 1000, (
            f"a half-period of {gap} instructions, not {HALF_PERIOD}. "
            f"That is {gap / INSTRUCTIONS_PER_MICROSECOND / 1000:.1f} ms where the "
            f"sketch asked for 500."
        )


# --- Serial, which is OH-63's Done-when -------------------------------------


def test_a_vendor_serial_sketch_prints_through_the_board_console(serial_sketch):
    """`Serial.begin(9600); Serial.println("hello")`, end to end.

    Read through `webui/api.py`'s own view rather than off the core, because
    the claim is that a person watching the page sees it -- and `uart_view` is
    where "the board printed nothing" and "this board models no UART" are
    turned into two different answers.

    The `\r\n` is Arduino's, not the sketch's: `println` appends it. Asserting
    the exact bytes is therefore also asserting that two bytes nobody wrote
    arrive, in that order.
    """
    image, _ = serial_sketch
    with api.load_firmware(BOARD, image, base=0) as session:
        for _ in range(BUDGET):
            session.step()
        view = session.state()["uart"]

    assert view["present"] is True, "the board reports no UART model"
    assert view["text"] == "hello\r\n", view


def test_the_serial_sketch_takes_the_fast_path_and_needs_no_interrupt(serial_sketch):
    """**The measurement that shaped this ticket**, pinned so it cannot rot.

    `HardwareSerial::write` queues the byte and sets UDRIE0 when UDRE0 reads
    clear, and writes straight to UDR0 when it reads set. UDRIE0 left set after
    the sketch has printed would mean the byte went into the ring buffer and is
    waiting for an interrupt `core/avr` does not raise -- which is exactly the
    state this board was in before OH-63, with UCSR0B at 0xB8.
    """
    image, _ = serial_sketch
    with api.load_firmware(BOARD, image, base=0) as session:
        for _ in range(BUDGET):
            session.step()
        control = session.cpu.read_data(atmega328p.UCSR0B)

    assert control & (1 << atmega328p.TXEN0), "the transmitter is not enabled"
    assert not control & UDRIE0, (
        f"UCSR0B is {control:#04x}; UDRIE0 set means the byte is queued for an "
        f"interrupt this core does not raise"
    )


def test_the_serial_sketch_configures_the_baud_rate_it_asked_for(serial_sketch):
    """The divisor is read back and reported rather than accepted and dropped.

    9,615 and not 9,600: `Serial.begin(9600)` on a 16 MHz part writes 207 with
    double-speed set, and 16,000,000 / (8 * 208) is 9,615. The 0.16% error is
    the silicon's, and reporting 9,600 here would be reporting the request
    rather than the configuration.
    """
    image, _ = serial_sketch
    with api.load_firmware(BOARD, image, base=0) as session:
        for _ in range(BUDGET):
            session.step()
        assert atmega328p.baud_rate(session.cpu) == 9615
