# OpenHardware — the compile service, and the boundary it holds.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Two kinds of test here, and the split matters
#
# Most of these need no compiler: they check `recipe_for`, the preamble, and
# the refusals, which are decisions this repository makes rather than things
# avr-gcc does. They run everywhere.
#
# The rest actually build, and **skip loudly** where PlatformIO's toolchain is
# absent. The compiled image is never committed, for the licence reason
# `tests/avr/arduino/blink.cpp` records: linking Arduino's core makes the
# result a derivative of LGPL-2.1 code.
#
# ## What "the server decides what runs" is worth asserting
#
# The whole safety argument of `webui/compile.py` is that a request carries
# source and a board name and cannot influence the command line. That is a
# property of the code, not of a compiler, so it is checked by reading the
# recipe rather than by trying to exploit it — an attempted exploit that fails
# proves one payload was handled, and a structural check proves the shape.

import itertools
import pathlib

import pytest

from webui import api
from webui import compile as compiler
from webui.boards import atmega328p, esp32c3, samd21

BOARD = "Arduino Uno"

#: The second board, and a XIAO rather than an Arduino for a reason that is not
#: arbitrary: it is the one whose variant is not in its framework, whose flash
#: needs a linker script, and whose core needs two CMSIS packages. A second AVR
#: board would have proved that a dictionary can hold two rows.
SAMD_BOARD = "XIAO-SAMD21-DIP"

BLINK = """
void setup() { pinMode(13, OUTPUT); }
void loop() {
  digitalWrite(13, HIGH);
  delay(500);
  digitalWrite(13, LOW);
  delay(500);
}
"""

#: The same sketch for the other board, and the two differences are both real.
#:
#: `LED_BUILTIN` rather than 13, because the whole point is that Seeed's
#: variant is what maps it -- to PA17, which `webui/boards/samd21.py` cites the
#: same two lines for.
#:
#: `delay(1)` rather than `delay(500)`, because virtual time on this core is
#: retired instructions and a millisecond is 48,000 of them. `delay(500)` is
#: twenty-four million steps through a ctypes boundary, which is a slow test
#: rather than a better one.
SAMD_BLINK = """
void setup() { pinMode(LED_BUILTIN, OUTPUT); }
void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(1);
  digitalWrite(LED_BUILTIN, LOW);
  delay(1);
}
"""


def needs_toolchain(board: str = BOARD) -> None:
    """Skip with the reason, rather than failing, where nothing can build.

    Takes a board because the two rows need different things installed and
    would otherwise skip for each other's reasons: the Uno needs a compiler and
    a framework, and a XIAO needs those plus two CMSIS packages and a
    board-support tree that PlatformIO does not supply at all. Each resolver
    raises `ToolchainMissing` naming its own fix, so the message a reader gets
    is the command they have to run.
    """
    recipe = compiler.recipe_for(board)
    try:
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
        compiler.variant_root(recipe)
        compiler.include_roots(recipe)
        compiler.linker_script(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))


# --- recipes, which need no compiler ----------------------------------------


def test_a_board_resolves_to_the_recipe_for_its_chip():
    """Keyed on the chip and not the board name, because four XIAO variants of
    one part build identically."""
    assert compiler.recipe_for(BOARD).toolchain == "toolchain-atmelavr"


def test_both_xiao_samd21_boards_resolve_to_one_recipe():
    """**The reason `recipe_for` keys on the chip.**

    The DIP and the SMD are two catalogue entries, one part, and one build.
    Keying on the board name would need a row each and they would drift.
    """
    assert (compiler.recipe_for("XIAO-SAMD21-DIP")
            is compiler.recipe_for("XIAO-SAMD21-SMD"))


def test_a_board_with_no_recipe_is_refused_and_names_its_chip():
    """"Unknown board" is not actionable; "carries an RP2040 and nothing
    here knows how to build for one" is.

    The example board used to be a C3, until OH-148 gave the C3 a recipe --
    which is this test's own point working: the refusal names the chip, and
    a chip gaining a row moves the example rather than the property.
    """
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("XIAO-RP2040-DIP")
    assert "RP2040" in str(caught.value)
    assert "SAMD21" in str(caught.value), (
        "the refusal should say what it can build for, not only what it cannot"
    )


def test_a_board_that_is_not_in_the_catalogue_is_refused():
    with pytest.raises(compiler.UnknownBoard):
        compiler.recipe_for("not a board")


def test_the_recipe_carries_the_base_address_the_loader_needs():
    """A raw `.bin` has no address of its own, so somebody must supply one.
    That somebody is the recipe and not the request."""
    assert compiler.recipe_for(BOARD).base == 0


def test_the_base_address_is_the_board_modules_and_not_a_second_copy():
    """**A flash origin is a fact about the silicon, and one place holds it.**

    `webui/boards/samd21.py` cites `samd21g18a.h:531-538` for `FLASH_ADDR`
    being zero -- which is the whole reason that file exists, since the RP2040
    over the same core puts flash at 0x10000000. A literal here would be a
    second copy with no citation, right today and unattached to the thing that
    would change it.

    Identity, not equality: both are zero, so `== 0` would pass against a
    literal and prove nothing.
    """
    assert compiler.recipe_for(SAMD_BOARD).base is samd21.FLASH


def test_the_arm_recipe_carries_a_linker_script_and_the_avr_one_does_not():
    """`avr-gcc` places flash from `-mmcu` alone; an Arm toolchain cannot.

    The emptiness on the AVR row is the assertion worth making: a field that
    was required everywhere would have been a worse design than one that says
    "this toolchain already knows".
    """
    assert compiler.recipe_for(BOARD).linker_script == ""
    assert compiler.recipe_for(SAMD_BOARD).linker_script.endswith(".ld")


def test_the_samd21_links_without_the_bootloader_the_vendor_assumes():
    """**The trap, pinned by name.**

    Seeed's `boards.txt:154` names `flash_with_bootloader.ld`, which is right
    for a real XIAO: a UF2 bootloader owns the first 8 KB and a sketch links at
    0x2000. There is no bootloader here, so an image built that way puts its
    vector table where a Cortex-M0+ never looks -- and it links, and it loads,
    and it executes erased flash.

    `webui/boards/samd21.py` says the same thing from the other end, with
    `VECTOR_TABLE_OFFSETS` of `(0,)` and a paragraph on why 0x2000 is not
    offered.
    """
    script = compiler.recipe_for(SAMD_BOARD).linker_script
    assert "without_bootloader" in script, script
    assert samd21.VECTOR_TABLE_OFFSETS == (0,), (
        "the board offers an entry offset this recipe does not link for"
    )


def test_the_samd21_variant_comes_from_seeed_and_not_from_the_framework():
    """`framework-arduino-samd` ships *Arduino's* boards -- zero, mzero, the
    MKRs -- and a XIAO is Seeed's.

    Arduino's `arduino_zero` variant compiles for the same chip and puts
    `LED_BUILTIN` on the same pin, which is exactly the coincidence that makes
    a wrong variant look right until a second pin is used.
    """
    recipe = compiler.recipe_for(SAMD_BOARD)
    assert recipe.variant_package == "seeed-samd"
    assert recipe.variant == "variants/XIAO_m0"
    assert compiler.recipe_for(BOARD).variant_package == "", (
        "the Uno's variant is the framework's own and needs no second tree"
    )


def test_nothing_in_a_recipe_comes_from_a_request():
    """**The safety property, checked structurally.**

    `build` takes exactly two strings and neither reaches a command line: the
    source becomes the contents of a file, and the board name selects a row of
    `RECIPES`. If a third parameter ever appears here, this test is where the
    argument about it should happen.
    """
    import inspect

    parameters = list(inspect.signature(compiler.build).parameters)
    assert parameters == ["board", "source"], (
        f"build() grew parameters {parameters}; anything beyond a board name "
        f"and source is something a request could use to choose a command line"
    )


def test_a_sketch_too_large_to_be_a_sketch_is_refused_before_a_compiler_starts():
    with pytest.raises(compiler.CompileError) as caught:
        compiler.build(BOARD, "/*" + " " * (compiler.MAX_SOURCE_BYTES + 1) + "*/")
    assert str(compiler.MAX_SOURCE_BYTES) in str(caught.value)


# --- the preamble -----------------------------------------------------------


def test_the_arduino_header_is_prepended_when_the_sketch_omits_it():
    """What the Arduino IDE does for a `.ino` and PlatformIO does not do for a
    `.cpp` — a difference recorded in OH-10's notes after it cost a build."""
    assert compiler.preamble("void setup(){}").startswith("#include <Arduino.h>")


def test_a_sketch_with_its_own_include_is_left_exactly_alone():
    """So a PlatformIO project's file compiles as the file it is, with no
    duplicate include and no shifted line numbers."""
    source = "#include <Arduino.h>\nvoid setup(){}"
    assert compiler.preamble(source) == source


def test_the_preamble_resets_the_line_counter():
    """**The load-bearing half.** Without `#line`, every diagnostic is one line
    further down than the person typed — and a line number that is confidently
    wrong is worse than none, because a reader believes it."""
    assert '#line 1 "sketch.cpp"' in compiler.preamble("void setup(){}")


# --- building, which needs the toolchain ------------------------------------


def test_a_sketch_and_a_board_name_produce_an_image_the_loader_accepts():
    """OH-61's headline: a string in, bytes `webui/api.py` will run."""
    needs_toolchain()
    built = compiler.build(BOARD, BLINK)
    assert built.ok, built.diagnostics
    assert built.image[:2] == b"\x0c\x94", "no reset jmp; this is not an AVR image"

    # **Five thousand and not two hundred.** The image this service builds
    # links `HardwareSerial`, so `Serial`'s global constructor runs before
    # `setup()` does -- measured at step 941, against 116 for the four-source
    # blink `tests/avr/test_arduino_sketch.py` builds. A budget copied from
    # there would fail here for a reason that has nothing to do with compiling.
    with api.load_firmware(BOARD, built.image, base=0) as session:
        for _ in range(5_000):
            session.step()
        assert session.cpu.read_data(atmega328p.DDRB) & (1 << atmega328p.LED_PIN)


def test_the_compiled_sketch_blinks_at_the_period_it_asked_for():
    """The image is not merely accepted, it is correct.

    Sixteen instructions to the microsecond, so `delay(500)` is 8,000,000 of
    them — the arithmetic `tests/avr/test_arduino_sketch.py` derives. Sampling
    every 256 steps places the transition to three parts in a hundred thousand.
    """
    needs_toolchain()
    built = compiler.build(BOARD, BLINK)
    assert built.ok, built.diagnostics

    led = 1 << atmega328p.LED_PIN
    half_period = 500_000 * 16
    transitions: list[int] = []
    last = 0
    with api.load_firmware(BOARD, built.image, base=0) as session:
        for batch in range(half_period * 2 // 256):
            for _ in range(256):
                session.step()
            now = session.cpu.read_data(atmega328p.PORTB) & led
            if now != last:
                transitions.append(batch * 256)
                last = now
                if len(transitions) == 2:
                    break

    assert len(transitions) == 2, f"the pin changed state {len(transitions)} times"
    gap = transitions[1] - transitions[0]
    assert abs(gap - half_period) <= half_period // 1000, (
        f"a half-period of {gap} instructions, not {half_period}"
    )


# --- the second board, which is OH-66 ---------------------------------------


def test_a_sketch_builds_for_the_second_board_too():
    """**OH-66's headline.** The same two strings in, a different chip's image
    out, and nothing about the request said so."""
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(SAMD_BOARD, SAMD_BLINK)
    assert built.ok, built.diagnostics
    # A Cortex-M0+ vector table opens with the initial stack pointer, which for
    # this part is the top of its 32K SRAM. An image linked at the bootloader
    # offset would open with erased flash instead, so this is the cheapest
    # possible check that the right linker script was used.
    stack = int.from_bytes(built.image[:4], "little")
    assert stack == samd21.SRAM + samd21.SRAM_SIZE, f"0x{stack:08x}"


def test_the_two_boards_do_not_produce_the_same_image():
    """A table with two rows that both build for the Uno would pass every
    other test in this file."""
    needs_toolchain()
    needs_toolchain(SAMD_BOARD)
    uno = compiler.build(BOARD, BLINK)
    xiao = compiler.build(SAMD_BOARD, SAMD_BLINK)
    assert uno.ok and xiao.ok
    assert uno.image[:2] == b"\x0c\x94", "no reset jmp; this is not an AVR image"
    assert uno.image != xiao.image


def test_the_second_boards_image_blinks_the_pin_its_variant_names():
    """**OH-66's Done-when: the pin, the way the Uno's PB5 is checked above.**

    PA17, and this test never says so -- `samd21.LED_PIN` does, from Seeed's
    variant table, and the sketch says `LED_BUILTIN`. If those two ever
    disagree the pin stops moving, which is the only way a test can tell that a
    variant is the wrong one.

    A millisecond is 48,000 retired instructions here, derived rather than
    fitted: `SysTick_Config(SystemCoreClock / 1000)` writes 47999 and the
    period is one more than the reload. What the sketch adds is its own
    `digitalWrite`, measured at 83 instructions, so the tolerance is a
    hundredth and the measurement is well inside it.
    """
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(SAMD_BOARD, SAMD_BLINK)
    assert built.ok, built.diagnostics

    half_period = 48_000
    out = samd21.group(samd21.PORTA) + samd21.PORT_OUT
    led = 1 << samd21.LED_PIN
    transitions: list[int] = []
    last = 0
    with api.load_firmware(SAMD_BOARD, built.image,
                           base=compiler.recipe_for(SAMD_BOARD).base) as session:
        for batch in range(half_period * 4 // 256):
            for _ in range(256):
                session.step()
            now = session.cpu.read_word(out) & led
            if now != last:
                transitions.append(batch * 256)
                last = now
                if len(transitions) == 2:
                    break
        # The direction register, not only the value: a blink on a pin still
        # set to input is a lie the value register alone cannot catch.
        assert session.cpu.read_word(
            samd21.group(samd21.PORTA) + samd21.PORT_DIR) & led

    assert len(transitions) == 2, f"the pin changed state {len(transitions)} times"
    gap = transitions[1] - transitions[0]
    assert abs(gap - half_period) <= half_period // 100, (
        f"a half-period of {gap} instructions, not {half_period}"
    )


def test_a_syntax_error_in_a_sketch_for_the_second_board_is_still_a_result():
    """The refusal shape does not change with the chip, and it is worth
    checking on the row that has three more ways to fail before a compiler
    even starts."""
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(SAMD_BOARD, "void setup(){ int broken = ; }\nvoid loop(){}")
    assert not built.ok
    assert "sketch.cpp:1" in built.diagnostics, built.diagnostics
    assert built.image == b""


def test_a_syntax_error_is_a_result_and_not_an_exception():
    """The commonest thing that will ever happen here, and it is ordinary."""
    needs_toolchain()
    built = compiler.build(BOARD, "void setup(){}\nvoid loop(){ int x = ; }")
    assert not built.ok
    assert built.image == b""


def test_a_syntax_error_names_the_line_the_person_typed():
    """Line 2, because the sketch's second line is where the error is — not
    line 3, which is where it is in the file the compiler actually saw."""
    needs_toolchain()
    built = compiler.build(BOARD, "void setup(){}\nvoid loop(){ int x = ; }")
    assert "sketch.cpp:2:" in built.diagnostics, built.diagnostics


def test_the_temporary_path_is_not_in_the_diagnostics():
    """A reader learns nothing from sixty characters of `AppData\\Local\\Temp`,
    and the `file:line:column:` shape has to survive for an editor to parse."""
    needs_toolchain()
    built = compiler.build(BOARD, "void setup(){}\nvoid loop(){ int x = ; }")
    assert "Temp" not in built.diagnostics
    assert "openhardware-build" not in built.diagnostics


def test_a_failed_build_leaves_nothing_behind():
    """The temporary directory is removed either way. A build that fails is
    the common case, so leaking on that path would fill a disk first."""
    needs_toolchain()
    built = compiler.build(BOARD, "void setup(){}\nvoid loop(){ int x = ; }")
    assert not built.ok
    leaked = [p for p in pathlib.Path(compiler.tempfile.gettempdir()).glob(
        "openhardware-build-*")]
    assert not leaked, f"left behind: {leaked}"


# --- the rest of the core and the libraries, which is OH-135 ----------------

#: Every idiom the 2026-08-30 survey probed, in one sketch. Before OH-135 the
#: Uno recipe carried 11 core sources and 8 of 13 idioms were "undefined
#: reference" -- map and random live in WMath, analogWrite/analogRead in
#: wiring_analog, attachInterrupt in WInterrupts, tone in Tone, shiftOut in
#: wiring_shift, pulseIn across wiring_pulse.c/.S -- and the library headers
#: were "No such file or directory". One build proves the lot.
IDIOMS = """
#include <Wire.h>
#include <SPI.h>
#include <EEPROM.h>
void bump() {}
void setup() {
  Wire.begin();
  SPI.begin();
  EEPROM.read(0);
  long scaled = map(analogRead(A0), 0, 1023, 0, 255);
  randomSeed(scaled);
  analogWrite(3, random(256));
  tone(8, 440, 100);
  attachInterrupt(digitalPinToInterrupt(2), bump, RISING);
  shiftOut(11, 13, MSBFIRST, 0x55);
  pulseIn(7, HIGH, 1000);
}
void loop() {}
"""

#: The same idioms on pins a XIAO actually has (0-10), and no `EEPROM.h`: a
#: SAMD21 has no EEPROM and its core ships no such library, so the include
#: stays out rather than pretending. Its refusal is asserted separately.
SAMD_IDIOMS = """
#include <Wire.h>
#include <SPI.h>
void bump() {}
void setup() {
  Wire.begin();
  SPI.begin();
  long scaled = map(analogRead(A0), 0, 1023, 0, 255);
  randomSeed(scaled);
  analogWrite(4, random(256));
  tone(3, 440, 100);
  attachInterrupt(digitalPinToInterrupt(2), bump, RISING);
  shiftOut(1, 2, MSBFIRST, 0x55);
  pulseIn(5, HIGH, 1000);
}
void loop() {}
"""


def test_the_beginner_idioms_all_build():
    """**OH-135's headline.** Eight of these were "undefined reference" and
    three of the includes "No such file" while the page said "Type an Arduino
    sketch and build it here". Now the whole set links in one image."""
    needs_toolchain()
    built = compiler.build(BOARD, IDIOMS)
    assert built.ok, built.diagnostics


def test_the_beginner_idioms_build_for_the_second_board_too():
    """The SAMD21 row was missing its own four -- `Tone.cpp`,
    `wiring_shift.c`, and pulse's pair, which this core spells
    `pulse.c`/`pulse_asm.S` where AVR says `wiring_pulse.c`/`.S`."""
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(SAMD_BOARD, SAMD_IDIOMS)
    assert built.ok, built.diagnostics


def test_a_library_is_compiled_only_for_a_sketch_that_names_it():
    """**The opt-in, read out of the vector table.**

    An AVR interrupt handler is pulled into the image by the vector table
    whether or not anything calls it, which is exactly why `Library` compiles
    nothing for a sketch that never names the header. The observable is
    precise: `iom328p.h` places TWI_vect at vector 24 and SPM_READY at 25 --
    4-byte `jmp` slots at 0x60 and 0x64 -- and a slot with no handler jumps
    to `__bad_interrupt`, the same place every other unused slot jumps.

    So blink's TWI slot equals its SPM slot byte for byte, and the Wire
    build's does not. If the libraries ever became unconditional, the first
    assertion is the one that fails.
    """
    needs_toolchain()
    blink = compiler.build(BOARD, BLINK)
    wire = compiler.build(
        BOARD,
        "#include <Wire.h>\nvoid setup(){ Wire.begin(); } void loop(){}",
    )
    assert blink.ok, blink.diagnostics
    assert wire.ok, wire.diagnostics
    assert blink.image[0x60:0x64] == blink.image[0x64:0x68], (
        "blink grew a TWI handler; a library was compiled without being asked"
    )
    assert wire.image[0x60:0x64] != wire.image[0x64:0x68], (
        "the Wire build has no TWI handler; the library its sketch names was "
        "not compiled in"
    )


def test_a_library_neither_framework_ships_is_refused_in_the_compilers_words():
    """`Servo.h` lives in a separate arduino-libraries repository and neither
    framework bundles it, so neither recipe has a row -- and the refusal is
    the compiler's own "No such file", a result rather than an exception.
    The same asymmetry holds for `EEPROM.h` on the SAMD21: no EEPROM on the
    silicon, no such library in its core."""
    needs_toolchain()
    servo = compiler.build(
        BOARD, "#include <Servo.h>\nvoid setup(){} void loop(){}"
    )
    assert not servo.ok
    assert "Servo.h" in servo.diagnostics, servo.diagnostics
    needs_toolchain(SAMD_BOARD)
    eeprom = compiler.build(
        SAMD_BOARD, "#include <EEPROM.h>\nvoid setup(){} void loop(){}"
    )
    assert not eeprom.ok
    assert "EEPROM.h" in eeprom.diagnostics, eeprom.diagnostics


def test_an_analogwrite_sketch_built_at_the_front_door_reports_unknown():
    """**OH-71's answer, reachable from the IDE at last.**

    `tests/avr/test_arduino_sketch.py` proved the honest answer with an image
    it assembled by hand, because until OH-135 this service could not link
    `analogWrite` at all -- and OH-71's close note predicted this test by
    name. Source in at the same door the browser uses; the pad the timer took
    answers `unknown` while its neighbour on the same port still answers.
    """
    needs_toolchain()
    built = compiler.build(BOARD, """
void setup() {
  pinMode(7, OUTPUT);
  digitalWrite(7, HIGH);
  analogWrite(3, 128);
}
void loop() {}
""")
    assert built.ok, built.diagnostics
    with api.load_firmware(BOARD, built.image, base=0) as session:
        for _ in range(50_000):
            session.step()
        state = api.pin_levels(session.runtime, session.cpu)
    assert state["7"] == "high", "PD7 is driven by PORTD and answers"
    assert state["3"] == "unknown", (
        "PD3 is timer 2's compare output; the level PORTD holds is not what "
        "the pin is doing"
    )


# --- the hint under a refusal the recipe caused (OH-138) ---------------------


def test_the_samd21s_serial_refusal_names_the_uart_that_works():
    """**The obvious line at a page that shows a UART console is `Serial`,
    and this build refuses it on purpose** -- the USBCON choice the recipe
    documents at length. The refusal used to be gcc's bare "'Serial' was not
    declared ... did you mean 'Serial_'?", which sends a person to a USB
    type that is more wrong. The compiler's words stay first and intact --
    they carry the line number -- and the recipe's note lands under them."""
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(
        SAMD_BOARD, "void setup(){ Serial.begin(9600); } void loop(){}"
    )
    assert not built.ok
    assert "'Serial' was not declared" in built.diagnostics, built.diagnostics
    at_error = built.diagnostics.index("'Serial' was not declared")
    at_note = built.diagnostics.index("Serial1")
    assert at_error < at_note, "the note buried the compiler's own words"
    assert "USB-CDC" in built.diagnostics


def test_the_hint_does_not_fire_on_an_unrelated_error():
    """A note under every failure is a note nobody reads."""
    needs_toolchain(SAMD_BOARD)
    built = compiler.build(SAMD_BOARD, "void setup(){}\nvoid loop(){ int x = ; }")
    assert not built.ok
    assert "Serial1" not in built.diagnostics, (
        "the hint fired on a syntax error that has nothing to do with Serial"
    )


def test_the_unos_serial_still_just_works():
    """The hint is the SAMD21's, because the absence is the SAMD21's: on the
    Uno `Serial` is the hardware USART and compiles."""
    needs_toolchain()
    built = compiler.build(
        BOARD, "void setup(){ Serial.begin(9600); } void loop(){}"
    )
    assert built.ok, built.diagnostics


# --- the whole-build budget (OH-136) -----------------------------------------


def test_running_out_of_budget_is_a_result_on_the_failure_rail():
    """`TIMEOUT_SECONDS` was per INVOCATION and its comment claimed it
    stopped a hung compiler "holding the server's lock forever" -- a SAMD21
    build is ~24 invocations, so the real bound was the better part of an
    hour. The whole-build budget comes back as returncode 124 with the
    budget and the command named -- the same nonzero rail every real
    compiler failure rides, so each call site already knows what to do."""
    import sys
    import time
    slow = (sys.executable, "-c", "import time; time.sleep(5)")
    done = compiler._run(slow, deadline=time.monotonic() + 0.2)
    assert done.returncode == 124
    assert str(compiler.BUILD_BUDGET_SECONDS) in done.stderr
    assert sys.executable in done.stderr


def test_a_deadline_already_passed_runs_nothing_at_all():
    """The doomed command is refused before it starts: a budget already
    blown owes the caller an answer, not five more seconds of compiler."""
    import sys
    import time
    began = time.monotonic()
    done = compiler._run((sys.executable, "-c", "import time; time.sleep(5)"),
                         deadline=began - 1)
    assert done.returncode == 124
    assert time.monotonic() - began < 1, "the doomed command was still run"


# --- the error paths carry their reasons (OH-139) ----------------------------


def test_a_missing_tool_is_a_result_naming_it():
    """A toolchain whose gcc exists and whose objcopy does not is a broken
    INSTALL -- and it used to kill the whole request with no response: the
    FileNotFoundError was in nobody's except list. 127 is the shell's own
    "command not found", riding the same rail every compiler failure rides."""
    import time
    done = compiler._run(("definitely-no-such-tool-oh139",),
                         deadline=time.monotonic() + 10)
    assert done.returncode == 127
    assert "definitely-no-such-tool-oh139" in done.stderr
    assert "incomplete" in done.stderr


def test_link_diagnostics_scrub_the_machines_paths():
    """A link error used to lead with the temporary object path --
    `C:\\Users\\...\\Temp\\openhardware-build-xyz\\00.o` -- sixty
    characters that say nothing a caller can use about a directory that no
    longer exists. The compiler's words survive; the paths become labels."""
    needs_toolchain()
    built = compiler.build(
        BOARD,
        "void undefined_fn();\nvoid setup(){ undefined_fn(); }\nvoid loop(){}",
    )
    assert not built.ok
    assert "undefined_fn" in built.diagnostics, built.diagnostics
    assert "<build>" in built.diagnostics, (
        "the object path was not scrubbed to its label"
    )
    assert "Temp" not in built.diagnostics
    assert str(compiler.PACKAGES) not in built.diagnostics


# --- the openhardware core: a Build whose output runs (OH-148) ---------------
#
# The third recipe is the first whose framework is this repository's own,
# because the vendor's cannot execute on the described board -- see
# `webui/arduino/cores/openhardware/Arduino.h` for the whole argument. The
# tests below hold the three promises that make the Build button honest for
# a C3: the image RUNS on the emulated board, the pin names are the
# vendor's, and every absence a sketch can reach for names the modelling
# decision it stands on.

C3_BOARD = "XIAO-ESP32-C3-DIP"

#: The vendor's D10 is GPIO10 -- `pins_arduino.h` in Seeed's own variant,
#: which the recipe puts on the include path -- and the sketch deliberately
#: uses the NAME, so a wrong pin table shows up as the wrong bit toggling.
C3_BLINK = """
void setup() { pinMode(D10, OUTPUT); }
void loop() { digitalWrite(D10, HIGH); digitalWrite(D10, LOW); delay(1); }
"""


def c3_build(source: str) -> "compiler.Build":
    try:
        return compiler.build(C3_BOARD, source)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))


def c3_transitions(image: bytes, budget: int = 60_000) -> list[tuple[int, bool]]:
    """Every step at which the built image moves GPIO10, watched by name."""
    recipe = compiler.recipe_for(C3_BOARD)
    out = esp32c3.GPIO + esp32c3.GPIO_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    with api.load_firmware(C3_BOARD, image, base=recipe.base) as session:
        for step in range(budget):
            session.step()
            now = session.cpu.read_word(out) & (1 << 10)
            if now != last:
                transitions.append((step, bool(now)))
                last = now
    return transitions


def test_the_c3_recipe_builds_with_the_repositorys_own_core():
    """The build succeeds and the framework is the in-repo one -- asserted
    so a future edit cannot quietly point the row back at a vendor core
    whose output would load and then stop."""
    recipe = compiler.recipe_for(C3_BOARD)
    assert recipe.framework == "openhardware"
    assert recipe.base is esp32c3.IROM, "the flash origin has one home"
    built = c3_build(C3_BLINK)
    assert built.ok, built.diagnostics
    assert len(built.image) > 0


def test_a_built_c3_sketch_runs_on_the_described_board_and_toggles_its_pin():
    """The whole point of OH-148: the Build button's output EXECUTES.

    Loaded by board name at the recipe's own base, the sketch enables
    GPIO10 -- the vendor's D10 -- and toggles it. Two transitions is a
    blink; alternation says the toggle is a toggle."""
    built = c3_build(C3_BLINK)
    assert built.ok, built.diagnostics
    transitions = c3_transitions(built.image)
    assert len(transitions) >= 4, f"the bit changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_delay_scales_with_its_argument_and_the_period_is_steady():
    """delay's millisecond is a stated judgement (oh_board.h says what
    kind), but WHATEVER it costs must scale: delay(3) between toggles must
    take about three times delay(1), or the loop is not counting."""
    one = c3_build(C3_BLINK)
    three = c3_build(C3_BLINK.replace("delay(1)", "delay(3)"))
    assert one.ok and three.ok

    def period(image: bytes) -> int:
        highs = [step for step, state in c3_transitions(image, 200_000)
                 if state]
        gaps = {b - a for a, b in itertools.pairwise(highs[1:])}
        assert len(gaps) == 1, f"period varies: {sorted(gaps)}"
        return gaps.pop()

    ratio = period(three.image) / period(one.image)
    assert 2.5 < ratio < 3.5, f"delay(3)/delay(1) = {ratio:.2f}"


def test_each_absence_hints_the_model_decision_it_stands_on():
    """digitalRead and Serial are not in the core because they are not in
    the MODEL, and the person who reaches for one is told that in the pane
    they are looking at -- the OH-138 pattern, one hint per decision."""
    read = c3_build("void setup(){int x = digitalRead(D10);} void loop(){}")
    assert not read.ok
    assert "leaves GPIO_IN unmapped on purpose" in read.diagnostics

    serial = c3_build(
        "void setup(){Serial.begin(9600);} void loop(){}")
    assert not serial.ok
    assert "no UART is mapped" in serial.diagnostics


def test_the_oh_board_header_restates_the_descriptions_own_numbers():
    """`oh_board.h` is C and `esp32c3.py` is Python, and the register can
    only live in one language per artefact -- so the two spellings are held
    equal here, and a description change that forgets the variant header
    fails a test that names it."""
    variant = (pathlib.Path(compiler.ARDUINO_LITE)
               / "variants" / "xiao_esp32c3")
    header = (variant / "oh_board.h").read_text(encoding="utf-8")
    defines = {}
    for line in header.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "#define":
            defines[parts[1]] = parts[2].rstrip("u")
    gpio = esp32c3.GPIO
    assert int(defines["OH_GPIO_OUT_W1TS"], 16) == gpio + esp32c3.GPIO_OUT_W1TS
    assert int(defines["OH_GPIO_OUT_W1TC"], 16) == gpio + esp32c3.GPIO_OUT_W1TC
    assert int(defines["OH_GPIO_ENABLE_W1TS"], 16) == (
        gpio + esp32c3.GPIO_ENABLE_W1TS)
    assert int(defines["OH_GPIO_ENABLE_W1TC"], 16) == (
        gpio + esp32c3.GPIO_ENABLE_W1TC)
    assert int(defines["OH_STACK_TOP"], 16) == (
        esp32c3.DRAM + esp32c3.DRAM_SIZE - 16)

    script = (variant / "link.ld").read_text(encoding="utf-8")
    assert f"ORIGIN = 0x{esp32c3.IROM:08X}" in script
    assert f"ORIGIN = 0x{esp32c3.DRAM:08X}" in script
