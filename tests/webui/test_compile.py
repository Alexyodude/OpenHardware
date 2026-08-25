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

import pathlib

import pytest

from webui import api
from webui import compile as compiler
from webui.boards import atmega328p

BOARD = "Arduino Uno"

BLINK = """
void setup() { pinMode(13, OUTPUT); }
void loop() {
  digitalWrite(13, HIGH);
  delay(500);
  digitalWrite(13, LOW);
  delay(500);
}
"""


def needs_toolchain() -> None:
    """Skip with the reason, rather than failing, where nothing can build."""
    recipe = compiler.recipe_for(BOARD)
    try:
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))


# --- recipes, which need no compiler ----------------------------------------


def test_a_board_resolves_to_the_recipe_for_its_chip():
    """Keyed on the chip and not the board name, because four XIAO variants of
    one part build identically."""
    assert compiler.recipe_for(BOARD).toolchain == "toolchain-atmelavr"


def test_a_board_with_no_recipe_is_refused_and_names_its_chip():
    """"Unknown board" is not actionable; "carries an ESP32-C3 and nothing
    here knows how to build for one" is."""
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("XIAO-ESP32-C3-DIP")
    assert "ESP32-C3" in str(caught.value)


def test_a_board_that_is_not_in_the_catalogue_is_refused():
    with pytest.raises(compiler.UnknownBoard):
        compiler.recipe_for("not a board")


def test_the_recipe_carries_the_base_address_the_loader_needs():
    """A raw `.bin` has no address of its own, so somebody must supply one.
    That somebody is the recipe and not the request."""
    assert compiler.recipe_for(BOARD).base == 0


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
