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

import concurrent.futures
import dataclasses
import itertools
import os
import pathlib

import pytest

from tools import board_manifest
from webui import api
from webui import compile as compiler
from webui.boards import atmega328p, esp32c3, esp32c5, esp32c6, samd21

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


def needs_table(board: str) -> None:
    """Skip, naming the fetch, where a row's variant was never fetched."""
    row = board_manifest.row(board)
    table = (compiler.BOARD_SUPPORT / row.package / "variants" / row.variant
             / "pins_arduino.h")
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")


def test_a_manifest_board_builds_against_its_own_variant_and_no_other():
    """rules/board-claims.md §6 (OH-179): the Feather's recipe is the
    ESP32-C6's with the row's own table as its only pin table -- the XIAO's
    is gone from it, not shadowed."""
    needs_table("Adafruit Feather ESP32-C6")
    recipe = compiler.recipe_for("Adafruit Feather ESP32-C6")
    assert recipe.bsp_includes == ("arduino-esp32/variants/adafruit_feather_esp32c6",)
    assert recipe.extra_includes == ()
    assert recipe == dataclasses.replace(
        compiler.RECIPES["ESP32-C6"], bsp_includes=recipe.bsp_includes)


def test_the_pilot_is_refused_naming_its_variant_and_what_its_table_lacks():
    """The ticket's own condition: compiled against
    `sparkfun_esp32c6_thing_plus`, or refused naming it -- by whichever of
    `unmet`'s two answerers this machine has."""
    needs_table("SparkFun Thing Plus ESP32-C6")
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("SparkFun Thing Plus ESP32-C6")
    message = str(caught.value)
    assert "arduino-esp32 variants/sparkfun_esp32c6_thing_plus/pins_arduino.h" in message
    assert "SOC_GPIO_PIN_COUNT" in message, message
    assert "XIAO" not in message, message


def test_the_qt_py_is_refused_naming_the_header_its_table_includes():
    needs_table("Adafruit QT Py ESP32-C3")
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("Adafruit QT Py ESP32-C3")
    message = str(caught.value)
    assert "arduino-esp32 variants/adafruit_qtpy_esp32c3/pins_arduino.h" in message
    assert "soc/soc_caps.h" in message, message


def test_a_refusal_says_the_compiler_answered_where_one_is_installed():
    needs_table("SparkFun Thing Plus ESP32-C6")
    try:
        compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("SparkFun Thing Plus ESP32-C6")
    message = str(caught.value)
    assert ("cannot be compiled here (asked of riscv32-esp-elf-g++ and "
            "riscv32-esp-elf-gcc -fsyntax-only): third_party/bsp/arduino-esp32/"
            "variants/sparkfun_esp32c6_thing_plus/pins_arduino.h:") in message, message
    assert "'SOC_GPIO_PIN_COUNT' was not declared in this scope" in message, message


def test_the_header_answers_where_no_compiler_is_installed_and_says_so(monkeypatch):
    needs_table("SparkFun Thing Plus ESP32-C6")
    needs_table("Adafruit QT Py ESP32-C3")

    def missing(recipe):
        raise compiler.ToolchainMissing(f"no {recipe.prefix}gcc on this machine")

    monkeypatch.setattr(compiler, "toolchain_root", missing)
    with pytest.raises(compiler.UnknownBoard) as pilot:
        compiler.recipe_for("SparkFun Thing Plus ESP32-C6")
    with pytest.raises(compiler.UnknownBoard) as qt_py:
        compiler.recipe_for("Adafruit QT Py ESP32-C3")
    assert ("(read from the header, with no riscv32-esp-elf-gcc here to ask): "
            "it uses SOC_GPIO_PIN_COUNT, which no header it reaches defines"
            ) in str(pilot.value), pilot.value
    assert ("it includes soc/soc_caps.h, which is in none of "
            "third_party/bsp/arduino-esp32/variants/adafruit_qtpy_esp32c3, "
            "webui/arduino/cores/openhardware, webui/arduino/variants/xiao_esp32c3"
            ) in str(qt_py.value), qt_py.value


def test_each_rows_verdict_is_the_compilers_own(monkeypatch):
    """Both of `unmet`'s answerers, held to a real build: built anyway with
    its own table, a row builds exactly when the compiler's syntax-only
    answer and the header reading each find nothing, and a refused row's
    build fails on the first thing each names."""
    sketch = "void setup() {} void loop() {}"
    seen = []
    for row in board_manifest.ROWS:
        needs_table(row.board)
        recipe = compiler.own_variant(row, compiler.RECIPES[row.chip])
        try:
            asked = compiler.compiled_gaps(recipe, compiler.toolchain_root(recipe))
        except compiler.ToolchainMissing as exc:
            pytest.skip(str(exc))
        read = compiler.read_gaps(recipe)
        monkeypatch.setattr(compiler, "recipe_for", lambda board, r=recipe: r)
        built = oh_build(row.board, sketch)
        assert built.ok is not bool(asked), (row.board, asked, built.diagnostics)
        assert built.ok is not bool(read), (row.board, read, built.diagnostics)
        named = [words.split(": ", 1)[1] for words in asked[:1]]
        named += [words.split()[2].rstrip(",") for words in read[:1]]
        assert all(name in built.diagnostics for name in named), (named, built.diagnostics)
        seen.append((row.board, built.ok))
    assert (True in dict(seen).values()) and (False in dict(seen).values()), seen


def fake_table(tmp_path, monkeypatch, text: str) -> "compiler.Recipe":
    """The C6 recipe with `text` as its only pin table, under a `tmp_path`
    board-support root."""
    table = tmp_path / "pkg" / "variants" / "fake" / "pins_arduino.h"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(text, encoding="utf-8")
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path)
    return dataclasses.replace(compiler.RECIPES["ESP32-C6"], extra_includes=(),
                               bsp_includes=("pkg/variants/fake",))


def test_the_compiler_passes_the_tables_the_header_reading_refused(tmp_path, monkeypatch):
    """The two upstream variants the header reading misjudged (OH-183),
    `kodedot` and `wt32-eth01`, declare several constants on one line; the
    compiler is asked, so they are not refused."""
    try:
        tools = compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    recipe = fake_table(tmp_path, monkeypatch, (
        "#include <stdint.h>\n"
        "static const uint8_t TXD0 = 1, TX0 = 1;\n"))
    assert compiler.read_gaps(recipe) == ["it uses TX0, which no header it reaches defines"]
    assert compiler.unmet(recipe) == (
        [], "asked of riscv32-esp-elf-g++ and riscv32-esp-elf-gcc -fsyntax-only")
    assert compiler.compiled_gaps(recipe, tools) == []


def test_the_table_is_asked_of_in_both_languages_a_build_compiles_it_in(
        tmp_path, monkeypatch):
    """The sketch is C++ and `main.c` is C, and each includes the table:
    `bool` with no `<stdbool.h>` is C's error alone, `delete` C++'s."""
    try:
        tools = compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    as_c = fake_table(tmp_path / "c", monkeypatch, "static const bool FLAG = 1;\n")
    as_cxx = fake_table(tmp_path / "cxx", monkeypatch, "static const uint8_t delete = 1;\n")
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path / "c")
    (c_gap,) = compiler.compiled_gaps(as_c, tools)
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path / "cxx")
    (cxx_gap,) = compiler.compiled_gaps(as_cxx, tools)
    assert "'bool'" in c_gap, c_gap
    assert "'delete'" in cxx_gap, cxx_gap


def test_the_table_is_compiled_with_the_builds_own_cxx_flags(tmp_path, monkeypatch):
    """`-fno-exceptions` is the recipe's, so a `throw` fails the build."""
    try:
        tools = compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    recipe = fake_table(tmp_path, monkeypatch, "static inline void f(void) { throw 1; }\n")
    (gap,) = compiler.compiled_gaps(recipe, tools)
    assert "exception handling disabled" in gap, gap


def test_the_compiler_is_asked_once_per_table_and_again_when_it_changes(
        tmp_path, monkeypatch):
    """`/api/boards` asks of every board on every request."""
    try:
        compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    recipe = fake_table(tmp_path, monkeypatch, "static const uint8_t A = 1;\n")
    assert compiler.unmet(recipe)[0] == []
    run = compiler._run

    def refuse(command, deadline):
        raise AssertionError(f"asked again: {command}")

    monkeypatch.setattr(compiler, "_run", refuse)
    assert compiler.unmet(recipe)[0] == []
    monkeypatch.setattr(compiler, "_run", run)
    fake_table(tmp_path, monkeypatch, "static const uint8_t A = FROM_NOWHERE;\n")
    (gap,) = compiler.unmet(recipe)[0]
    assert "FROM_NOWHERE" in gap, gap


def test_every_upstream_variants_verdict_is_the_compilers(monkeypatch):
    """Both answerers against a real empty-sketch build of every
    arduino-esp32 variant, on the C6 and C3 recipes: the compiler agrees on
    every one; the header reading's disagreements are printed.

    Slow -- two builds and up to four syntax-only compiles a variant -- so
    run only with `OH_SLOW=1`."""
    if os.environ.get("OH_SLOW") != "1":
        pytest.skip("SKIPPED: slow; run it with OH_SLOW=1 pytest "
                    "tests/webui/test_compile.py -k every_upstream_variants -s")
    variants = compiler.BOARD_SUPPORT / "arduino-esp32" / "variants"
    if not variants.is_dir():
        pytest.skip(f"SKIPPED: no {variants}; python tools/import_pindefs.py --fetch")
    try:
        tools = compiler.toolchain_root(compiler.RECIPES["ESP32-C6"])
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    recipes = {
        f"{chip} {variant.name}": dataclasses.replace(
            compiler.RECIPES[chip], extra_includes=(),
            bsp_includes=(f"arduino-esp32/variants/{variant.name}",))
        for chip in ("ESP32-C6", "ESP32-C3")
        for variant in sorted(variants.iterdir())
        if (variant / "pins_arduino.h").is_file()
    }
    monkeypatch.setattr(compiler, "recipe_for", recipes.__getitem__)

    def verdicts(name: str) -> tuple[str, bool, bool, bool]:
        built = compiler.build(name, "void setup() {} void loop() {}")
        return (name, built.ok, not compiler.compiled_gaps(recipes[name], tools),
                not compiler.read_gaps(recipes[name]))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(verdicts, recipes))
    asked_wrong = [name for name, built, asked, _ in results if asked is not built]
    read_wrong = [(name, "builds" if built else "fails")
                  for name, built, _, read in results if read is not built]
    print(f"\n{len(results)} builds, {sum(r[1] for r in results)} of them ok; "
          f"the compiler disagrees on {len(asked_wrong)}, the header reading on "
          f"{len(read_wrong)}: {read_wrong}")
    assert asked_wrong == [], asked_wrong


def test_a_name_reached_through_a_macro_counts_and_an_unused_macro_does_not(
        tmp_path, monkeypatch):
    """What the header reading asks of a table, on a table written to say
    it: a `static const` compiles in every file, through the macros it
    names; a macro nothing uses compiles nowhere; comments are not code."""
    table = tmp_path / "pkg" / "variants" / "fake" / "pins_arduino.h"
    table.parent.mkdir(parents=True)
    table.write_text(
        "#define PIN_A (FROM_A + 1)  // FROM_LINE_COMMENT\n"
        "#define UNUSED (FROM_UNUSED + 1)\n"
        "static const uint8_t A = PIN_A;\n"
        "static const uint8_t B = 7;  /* FROM_BLOCK_COMMENT */\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path)
    recipe = dataclasses.replace(
        compiler.RECIPES["ESP32-C6"], bsp_includes=("pkg/variants/fake",))
    assert compiler.read_gaps(recipe) == ["it uses FROM_A, which no header it reaches defines"]


def test_a_row_never_fetched_is_refused_when_built_naming_the_fetch_as_a_xiao_is(
        tmp_path, monkeypatch):
    """One behaviour for both (OH-183): with nothing fetched, each resolves
    to its recipe -- the Build button stays on -- and the build is refused,
    naming the fetch, by `include_roots`."""
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path)
    xiao = compiler.recipe_for("XIAO-ESP32-C6-DIP")
    row = compiler.recipe_for("Adafruit Feather ESP32-C6")
    with pytest.raises(compiler.ToolchainMissing) as xiaos:
        compiler.include_roots(xiao)
    with pytest.raises(compiler.ToolchainMissing) as rows:
        compiler.include_roots(row)
    assert str(xiaos.value) == str(rows.value).replace(
        "adafruit_feather_esp32c6", "XIAO_ESP32C6"), (xiaos.value, rows.value)
    assert str(rows.value).endswith(
        "Fetch it with:\n  python tools/import_pindefs.py --fetch"), rows.value


def test_a_fetched_variant_with_no_table_is_refused_by_both_answerers(tmp_path, monkeypatch):
    """Fetched, so asked: a directory with no `pins_arduino.h` in it."""
    (tmp_path / "pkg" / "variants" / "fake").mkdir(parents=True)
    monkeypatch.setattr(compiler, "BOARD_SUPPORT", tmp_path)
    recipe = dataclasses.replace(compiler.RECIPES["ESP32-C6"], extra_includes=(),
                                 bsp_includes=("pkg/variants/fake",))
    assert compiler.read_gaps(recipe) == [
        f"there is no {tmp_path / 'pkg' / 'variants' / 'fake' / 'pins_arduino.h'}"]
    try:
        tools = compiler.toolchain_root(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    (gap,) = compiler.compiled_gaps(recipe, tools)
    assert "pins_arduino.h: No such file or directory" in gap, gap


def test_a_row_whose_chips_recipe_compiles_a_variant_of_its_own_is_refused(monkeypatch):
    """The SAMD21 recipe compiles Seeed's XIAO_m0 variant as sources, so a
    row on that chip cannot swap a pin table in: refused, never built as
    the XIAO."""
    row = dataclasses.replace(board_manifest.ROWS[0], board="Nowhere SAMD21",
                              chip="SAMD21")
    monkeypatch.setattr(board_manifest, "ROWS", (*board_manifest.ROWS, row))
    with pytest.raises(compiler.UnknownBoard) as caught:
        compiler.recipe_for("Nowhere SAMD21")
    message = str(caught.value)
    assert "compiles variants/XIAO_m0 from seeed-samd, which is another board's" in message
    assert f"nothing here builds against {row.package} variants/{row.variant}" in message


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


def oh_build(board: str, source: str) -> "compiler.Build":
    """Build for a board, or skip when the toolchain is not installed here."""
    try:
        return compiler.build(board, source)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))


def c3_build(source: str) -> "compiler.Build":
    return oh_build(C3_BOARD, source)


def gpio_transitions(board: str, description, gpio: int, image: bytes,
                     budget: int) -> list[tuple[int, bool]]:
    """Every step at which `image`, run on `board`, moves one GPIO's OUT bit.

    Read through the description's own `GPIO_OUT`, which is the register the
    W1TS/W1TC writes land in, so a variant header pointing the core at a
    neighbour's register file shows up here as a bit that never moves.
    """
    recipe = compiler.recipe_for(board)
    out = description.GPIO + description.GPIO_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    with api.load_firmware(board, image, base=recipe.base) as session:
        for step in range(budget):
            session.step()
            now = session.cpu.read_word(out) & (1 << gpio)
            if now != last:
                transitions.append((step, bool(now)))
                last = now
    return transitions


def c3_transitions(image: bytes, budget: int = 60_000) -> list[tuple[int, bool]]:
    """Every step at which the built image moves GPIO10, watched by name."""
    return gpio_transitions(C3_BOARD, esp32c3, 10, image, budget)


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


def test_a_sketch_s_globals_survive_the_linker_script_having_no_crt0():
    """**The one thing `link.ld` gets to be unusual about, checked by
    running it.** A real Arduino image copies `.data` out of flash and
    zeroes `.bss` in its C runtime startup; this core has no crt0 at all,
    so the script puts `.data` IN the flash window -- readable in place,
    because this model's regions accept stores where real XIP flash would
    not -- and `.bss` NOLOAD in a RAM region the model fills with zero.

    Both halves are asserted through the pin, because that is the only
    place the difference shows:

      * an initialised global read on every pass proves `.data` arrived
        with its value. Were it wrong, the pin would never go high.

    **Both globals are `volatile`, and that is what makes this a test of
    the SCRIPT rather than of gcc**: without it, -Os folds `initialised`
    into a constant and keeps `counter` in a register across the inlined
    loop, so neither section is touched and breaking their placement
    changes nothing.

    **What this test does and does not catch, measured rather than
    assumed.** Pointing `dram` at an unmapped address fails it, which is
    what proves it exercises the RAM at all. Two other mutations do NOT
    fail it, and that is a fact about the linker rather than a hole here:
    deleting the explicit `*(.data .data.*)` line changes nothing because
    GNU ld places an orphan section anyway, and moving `.bss` into the
    flash region changes nothing because a NOLOAD section emits no bytes
    and lands where this model still reads zero. The region is the
    load-bearing part of the script; the section lines are documentation
    of intent.
      * a zero-initialised global that is incremented goes high exactly
        ONCE. Were `.bss` not zeroed it would never go high; were writes
        to it not persistent it would go high on every pass. One high
        rules out both.
    """
    initialised = c3_build("""
volatile int initialised = 7;
void setup() { pinMode(D10, OUTPUT); }
void loop() {
  if (initialised == 7) { digitalWrite(D10, HIGH); }
  delay(1);
  digitalWrite(D10, LOW);
  delay(1);
}
""")
    assert initialised.ok, initialised.diagnostics
    rises = [state for _, state in c3_transitions(initialised.image, 200_000)
             if state]
    assert len(rises) >= 3, (
        f"an initialised global read wrongly: the pin rose {len(rises)} "
        f"times, so `.data` did not arrive with its value"
    )

    zeroed = c3_build("""
volatile int counter;
void setup() { pinMode(D10, OUTPUT); }
void loop() {
  if (counter == 0) { digitalWrite(D10, HIGH); }
  counter = counter + 1;
  delay(1);
  digitalWrite(D10, LOW);
  delay(1);
}
""")
    assert zeroed.ok, zeroed.diagnostics
    rises = [state for _, state in c3_transitions(zeroed.image, 200_000)
             if state]
    assert len(rises) == 1, (
        f"the pin rose {len(rises)} times: 0 means `.bss` was not zeroed, "
        f"more than 1 means a write to it did not persist"
    )


def test_a_global_constructor_runs_and_runs_before_setup():
    """**The absence that did not fail loudly**, which is why OH-151 exists.

    Every other thing this core lacks is a compile error carrying a hint
    that names the modelling decision behind it. A global C++ constructor
    was different: the sketch built, reported ok, and the constructor
    silently never ran -- and not because it was merely unreached.
    `--gc-sections` COLLECTED it. The linker map showed the four bytes the
    sketch object contributed to `.init_array` while `readelf -S` on the
    linked ELF showed no such section at all, because nothing referenced
    `__init_array_start` and nothing KEEPt it.

    The witness is `volatile` for the reason the test above it is: at -Os,
    gcc will happily prove a plain global was set to 5 by a constructor it
    can see and fold the comparison away, and then this passes with the
    constructor deleted from the image entirely.

    Reading the witness into `at_setup` inside setup(), and testing THAT,
    is what makes this an ordering assertion rather than only an existence
    one -- a sketch expects its globals built before its setup() runs, and
    a walk placed after setup() would satisfy a weaker test.

    **Which mutations this catches, run rather than assumed.** Removing the
    `oh_init_array()` call from `oh_run`, dropping `KEEP` from either line
    of the `.init_array` section, and deleting that output section outright
    each fail it. So does moving the call to after `setup()`, which is the
    one a test that only asked "did it run" would miss.
    """
    built = c3_build("""
volatile int witness = 0;
volatile int at_setup = 0;
struct Marker { Marker() { witness = 5; } };
Marker m;
void setup() { pinMode(D10, OUTPUT); at_setup = witness; }
void loop() {
  if (at_setup == 5) { digitalWrite(D10, HIGH); }
  delay(1);
  digitalWrite(D10, LOW);
  delay(1);
}
""")
    assert built.ok, built.diagnostics
    rises = [state for _, state in c3_transitions(built.image, 200_000)
             if state]
    assert len(rises) >= 3, (
        f"the pin rose {len(rises)} times: the global's constructor did not "
        f"run before setup(), so `.init_array` was not walked (or was not "
        f"kept, which looks identical from here)"
    )


def test_each_absence_hints_the_model_decision_it_stands_on():
    """digitalRead and analogRead are not in the core because they are not in
    the MODEL, and the person who reaches for one is told that in the pane
    they are looking at -- the OH-138 pattern, one hint per decision.

    **`Serial` was the second example here until OH-161** and is now the
    opposite one: the three ESP32 descriptions map UART0's transmit FIFO, so
    the symbol exists, the sketch builds, and the hint is gone. A test still
    asserting that refusal would hold the model to a gap it no longer has --
    so it asserts the fill instead, and `analogRead` takes the place of the
    absence."""
    read = c3_build("void setup(){int x = digitalRead(D10);} void loop(){}")
    assert not read.ok
    assert "leaves GPIO_IN unmapped on purpose" in read.diagnostics

    analog = c3_build("void setup(){int x = analogRead(D10);} void loop(){}")
    assert not analog.ok
    assert "needs the ADC" in analog.diagnostics

    serial = c3_build('void setup(){Serial.println("ok");} void loop(){}')
    assert serial.ok, serial.diagnostics


#: variant -> (its description, the name that description gives the RAM the
#: stack lives in). The C3 maps a separate DRAM alias; the C5 and C6 have one
#: SRAM window and say so. **Three rows and no loop over a directory**, so a
#: variant added without a row here is a test failure rather than a silence.
VARIANT_DESCRIPTIONS = {
    "xiao_esp32c3": (esp32c3, "DRAM"),
    "xiao_esp32c5": (esp32c5, "SRAM"),
    "xiao_esp32c6": (esp32c6, "SRAM"),
}


def test_every_variant_has_a_row_above():
    variants = pathlib.Path(compiler.ARDUINO_LITE) / "variants"
    assert {p.name for p in variants.iterdir() if p.is_dir()} == set(
        VARIANT_DESCRIPTIONS)


@pytest.mark.parametrize("variant", sorted(VARIANT_DESCRIPTIONS))
def test_the_oh_board_header_restates_the_descriptions_own_numbers(variant):
    """`oh_board.h` is C and the description is Python, and the register can
    only live in one language per artefact -- so the two spellings are held
    equal here, and a description change that forgets the variant header
    fails a test that names it.

    Per variant against its OWN description (OH-156): the C5 shares the C6's
    GPIO base and not its ENABLE offsets, so a header copied from a
    neighbour would pass a test that only checked one of them."""
    description, ram = VARIANT_DESCRIPTIONS[variant]
    root = pathlib.Path(compiler.ARDUINO_LITE) / "variants" / variant
    header = (root / "oh_board.h").read_text(encoding="utf-8")
    defines = {}
    for line in header.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "#define":
            defines[parts[1]] = parts[2].rstrip("u")
    gpio = description.GPIO
    assert int(defines["OH_GPIO_OUT_W1TS"], 16) == gpio + description.GPIO_OUT_W1TS
    assert int(defines["OH_GPIO_OUT_W1TC"], 16) == gpio + description.GPIO_OUT_W1TC
    assert int(defines["OH_GPIO_ENABLE_W1TS"], 16) == (
        gpio + description.GPIO_ENABLE_W1TS)
    assert int(defines["OH_GPIO_ENABLE_W1TC"], 16) == (
        gpio + description.GPIO_ENABLE_W1TC)
    # The UART, on the same terms and for the same reason (OH-161): the C3
    # gates its transmitter at + 0x78 and these two at + 0x88, so a header
    # copied from a neighbour would write the enable bit into an address
    # that part does not map.
    assert int(defines["OH_UART_FIFO"], 16) == description.UART0 + description.UART_FIFO
    assert int(defines["OH_UART_CLK_CONF"], 16) == (
        description.UART0 + description.UART_CLK_CONF)
    assert int(defines["OH_UART_TX_SCLK_EN"], 16) == description.UART_TX_SCLK_EN, (
        "the gate bit. Written as a hex literal in the header rather than as "
        "`(1u << 24)`, because the parser above takes one whitespace-separated "
        "token and a shift is three -- it read `(1u` and this test could not "
        "have compared anything."
    )

    ram_base = getattr(description, ram)
    ram_size = getattr(description, f"{ram}_SIZE")
    assert int(defines["OH_STACK_TOP"], 16) == ram_base + ram_size - 16

    script = (root / "link.ld").read_text(encoding="utf-8")
    assert f"ORIGIN = 0x{description.IROM:08X}" in script
    assert f"ORIGIN = 0x{ram_base:08X}" in script
    assert f"LENGTH = {description.IROM_SIZE // (1 << 20)}M" in script
    assert f"LENGTH = {ram_size // (1 << 10)}K" in script


# --- the ESP32-C5 and C6, on the same core (OH-156) ---------------------------
#
# The C3 block above is the pattern and is left as written. These two boards
# joined it on the same three promises -- the image RUNS on the described
# board, the pin names are the vendor's, every absence carries a hint -- and
# what differs between them is exactly what their variant headers state:
# which register file the writes land in, and which GPIO the vendor's D10
# reaches.

#: board -> (its description, the GPIO its vendor's D10 names). The numbers
#: are read off `third_party/bsp/arduino-esp32/variants/XIAO_ESP32C{5,6}/
#: pins_arduino.h` at 2787dab -- Seeed's own tables via Espressif's core, the
#: checkout `Recipe.bsp_includes` compiles against -- and written here AS
#: NUMBERS on purpose: the sketch uses the name, so a wrong table shows up as
#: the wrong bit toggling, which it could not if this test read the file the
#: sketch does. The C5's D10 is GPIO10; the C6's is GPIO18.
OPENHARDWARE_BOARDS = {
    "XIAO-ESP32-C5-DIP": (esp32c5, 10),
    "XIAO-ESP32-C6-DIP": (esp32c6, 18),
}


@pytest.mark.parametrize("board", sorted(OPENHARDWARE_BOARDS))
def test_the_c5_and_c6_recipes_build_with_the_repositorys_own_core(board):
    description, _gpio = OPENHARDWARE_BOARDS[board]
    recipe = compiler.recipe_for(board)
    assert recipe.framework == "openhardware"
    assert recipe.base is description.IROM, "the flash origin has one home"
    assert recipe.bsp_includes, "the vendor's pin table comes from the checkout"
    built = oh_build(board, C3_BLINK)
    assert built.ok, built.diagnostics
    assert len(built.image) > 0


@pytest.mark.parametrize("board", sorted(OPENHARDWARE_BOARDS))
def test_a_built_sketch_runs_on_the_described_c5_or_c6_and_toggles_its_pin(board):
    """The OH-148 shape for each new board: loaded by name at the recipe's
    own base, the sketch enables the vendor's D10 and toggles it, watched on
    the bit that board's table says D10 is. **Which mutations this catches,
    run rather than assumed** (2026-09-04): giving the C5 header the C6's
    ENABLE offsets, or either header the other's D10 GPIO in this table,
    fails it -- the first because ENABLE_W1TS at +0x24 is nothing the C5
    description maps, the second because the wrong bit is watched."""
    description, gpio = OPENHARDWARE_BOARDS[board]
    built = oh_build(board, C3_BLINK)
    assert built.ok, built.diagnostics
    transitions = gpio_transitions(board, description, gpio, built.image,
                                   60_000)
    assert len(transitions) >= 4, f"the bit changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


@pytest.mark.parametrize("board", sorted(OPENHARDWARE_BOARDS))
def test_the_c5_and_c6_delay_is_steady_and_scales(board):
    """The C3's delay test, on each new part: whatever a millisecond costs
    here (its `oh_board.h` says, and says what kind of number it is), the
    period must be steady and delay(3) must cost about three delay(1)s.

    **What this does not catch, run rather than assumed** (2026-09-04):
    dividing a header's OH_DELAY_LOOPS_PER_MS by a hundred passes it, because
    the VALUE is the judgement the header labels it as and only the scaling
    is a claim. The measured period lives in that header's comment, beside
    the date it was taken."""
    description, gpio = OPENHARDWARE_BOARDS[board]
    one = oh_build(board, C3_BLINK)
    three = oh_build(board, C3_BLINK.replace("delay(1)", "delay(3)"))
    assert one.ok and three.ok

    def period(image: bytes) -> int:
        highs = [step for step, state in gpio_transitions(
            board, description, gpio, image, 200_000) if state]
        gaps = {b - a for a, b in itertools.pairwise(highs[1:])}
        assert len(gaps) == 1, f"period varies: {sorted(gaps)}"
        return gaps.pop()

    ratio = period(three.image) / period(one.image)
    assert 2.5 < ratio < 3.5, f"delay(3)/delay(1) = {ratio:.2f}"


@pytest.mark.parametrize("board", sorted(OPENHARDWARE_BOARDS))
def test_each_absence_hints_its_own_variant_header(board):
    """The hint for a missing timer names the header of the board being
    built, not the C3's -- the reason `_openhardware` is a function."""
    recipe = compiler.recipe_for(board)
    built = oh_build(board, "void setup(){} void loop(){ millis(); }")
    assert not built.ok
    assert recipe.variant in built.diagnostics, built.diagnostics
    assert "xiao_esp32c3" not in built.diagnostics


# --- a sketch can print, and the hint that said it could not is gone (OH-161)


#: Every kind of thing `Serial` can be handed, in one sketch, so a formatting
#: bug shows up as the wrong text rather than as a missing line. The negative
#: is deliberate: it is the one path with a branch in it. Eighteen bytes,
#: measured, and the assertions below spell all eighteen.
PRINTING_SKETCH = """
void setup() {
  Serial.begin(115200);
  Serial.println("hello");
  Serial.print("n=");
  Serial.println(-42);
  Serial.print('x');
  Serial.println(7u);
}
void loop() { }
"""

#: Measured on the C3 rather than estimated (2026-09-04): the sketch's first
#: byte arrives at step 39 and its last at step 189. 200,000 is three orders
#: of margin, and the loop below stops when the output stands still rather
#: than running the budget out.
#:
#: This comment said "a few hundred instructions per character" and "22 of
#: them" until the OH-161 review traced the arrivals: 18 bytes, and the whole
#: sketch finishes in 189 steps.
PRINT_BUDGET = 200_000

#: How long the output must stand still before a sketch counts as finished
#: printing. **Measured, because this constant is what decides whether the
#: helper can return a prefix**: the largest gap between two bytes of that
#: sketch on the C3 is 29 steps (2026-09-04, every arrival traced), so 20,000
#: is nearly three orders of margin -- and the budget above still bounds the
#: whole run. The first draft said "a few hundred instructions", which was a
#: guess standing where the measurement belonged.
STALL_STEPS = 20_000


def printed(board: str, description, source: str, budget: int = PRINT_BUDGET) -> bytes:
    """Build `source` for `board`, run it, and return what reached the PANE.

    **Through `session.state()`, not through the board module**, which is the
    precedent `tests/webui/test_board_run.py:936` set for the RP2040 in its
    own words: "because the browser has no other way to reach it and the
    point of this ticket is that the wire carries it". That path runs
    `uart_view`'s `getattr(description, "uart0_output")` -- the seam all three
    new module docstrings claim works -- and its decode, neither of which
    reading `uart0_output` directly touches. **Not the byte cap**: these
    sketches print 18 bytes against a 64 KiB limit, so `dropped` is never
    non-zero here, and `tests/webui/test_board_run.py` is where that case is
    covered. This docstring claimed the cap until the OH-161 review pointed
    out that no sketch here can reach it, and this helper read `uart0_output`
    directly until the same review.

    The module's own reader still drives the stopping condition, because it is
    the cheap call in a loop that may run 200,000 times; the two are asserted
    equal at the end, so the layer this returns cannot silently disagree with
    the layer it watched.

    Stops when the output stops growing, so a sketch that prints nothing costs
    the whole budget and says so by returning empty.
    """
    built = oh_build(board, source)
    assert built.ok, built.diagnostics
    recipe = compiler.recipe_for(board)
    with api.load_firmware(board, built.image, base=recipe.base) as session:
        # Stops when the output STOPS GROWING, not at the first line
        # ending: stopping on a line ending returned after `hello` and
        # every assertion below would have been comparing a prefix.
        # `loop()` is empty in these sketches, so a stall means setup()
        # has finished printing.
        stalled = 0
        seen = b""
        for _ in range(budget):
            session.step()
            now = description.uart0_output(session.cpu)
            stalled = 0 if now != seen else stalled + 1
            seen = now
            if seen and stalled >= STALL_STEPS:
                break
        view = session.state()["uart"]
        assert view["present"], f"{board}: the pane says this board models no UART"
        assert view["bytes"] == len(seen), (
            f"{board}: the pane counted {view['bytes']} bytes and the board "
            f"module transmitted {len(seen)}"
        )
        assert view["text"] == seen.decode("utf-8", "backslashreplace")
        return seen


def test_a_sketch_that_prints_reaches_the_console_on_every_esp32_board():
    """The watched test OH-161 step 1 is done when. Three tables have to
    agree for this to pass and none of them is this test's: the sketch names
    `Serial`, the core writes `OH_UART_FIFO` from the variant header, and the
    board description maps that address as a stream gated by a bit the vendor
    sets at reset. A header pointing at a neighbour's offset, or a FIFO
    mapped as a register, shows up here as the wrong text.
    """
    needs_toolchain(C3_BOARD)
    expected = b"hello\r\nn=-42\r\nx7\r\n"
    assert printed(C3_BOARD, esp32c3, PRINTING_SKETCH) == expected
    for board, (description, _gpio) in sorted(OPENHARDWARE_BOARDS.items()):
        needs_toolchain(board)
        assert printed(board, description, PRINTING_SKETCH) == expected, board


#: The bounds of both integer paths, and the zero neither of them reaches by
#: accident. `LONG_MIN` is spelled as a subtraction because the literal cannot
#: be written directly: -2147483648 does not fit a 32-bit `long`, so C++ makes
#: it `long long` and the call is ambiguous across the print overloads. Found
#: while writing this test, and `serial.cpp` says the same at its negation.
BOUNDS_SKETCH = """
void setup() {
  Serial.println(-2147483647L - 1L);
  Serial.println(4294967295UL);
  Serial.println(0);
  Serial.println(0u);
  Serial.println(2147483647L);
  Serial.print('|');
  Serial.println(-1);
}
void loop() { }
"""


def test_the_integer_formatter_is_right_at_both_types_bounds():
    """`-42` and `7u` exercise one branch each and neither bound.

    A regression in the sign branch, in the negate-as-unsigned that keeps
    `LONG_MIN` from overflowing, or in the do-while that makes zero print at
    all would be invisible to the sketch above -- so the bounds are their own
    test. `kDigits` is 11, which is exactly what `4294967295` needs.
    """
    needs_toolchain(C3_BOARD)
    assert printed(C3_BOARD, esp32c3, BOUNDS_SKETCH) == (
        b"-2147483648\r\n4294967295\r\n0\r\n0\r\n2147483647\r\n|-1\r\n"
    )


def test_a_sketch_that_never_calls_begin_still_prints():
    """Because the vendor sets `UART_TX_SCLK_EN` at reset on all three parts,
    and this model must not require what the silicon does not. `begin` exists
    for the sketch that writes it, not because the transmitter needs it."""
    needs_toolchain(C3_BOARD)
    source = 'void setup() { Serial.println("no begin"); }\nvoid loop() { }'
    assert printed(C3_BOARD, esp32c3, source) == b"no begin\r\n"


def test_a_sketch_that_ends_the_port_goes_quiet():
    """`Serial.end` clears the same bit the description gates its stream on,
    so the bytes after it are discarded rather than queued -- which is what
    the part does. The two halves are asserted in one run so the second
    cannot pass by the first never having printed."""
    needs_toolchain(C3_BOARD)
    source = (
        'void setup() { Serial.println("before"); Serial.end();'
        ' Serial.println("after"); }\nvoid loop() { }'
    )
    assert printed(C3_BOARD, esp32c3, source) == b"before\r\n"


def test_begin_reopens_a_port_that_end_closed():
    """The one thing `begin` does, and until this test nothing held it: it
    sets the transmit clock bit. On a fresh part that is invisible, because
    the vendor sets the bit at reset and a sketch prints without calling
    `begin` at all -- so the only way to see `begin` work is to close the
    port first, which is what `end` does to the same bit.

    Found by mutation: clearing the gate at the top of `begin` changed
    nothing, because the next line set it again. That said the assertion set
    could not see `begin` at all.
    """
    needs_toolchain(C3_BOARD)
    source = (
        'void setup() { Serial.println("one"); Serial.end();'
        ' Serial.println("lost"); Serial.begin(9600); Serial.println("two"); }'
        "\nvoid loop() { }"
    )
    assert printed(C3_BOARD, esp32c3, source) == b"one\r\ntwo\r\n"


def test_the_serial_hint_is_gone_where_the_uart_is_modelled():
    """A hint names a modelling decision, and this one named an absence that
    has been filled. What is still absent of that peripheral is unmapped
    rather than hinted, so it faults at a named address instead."""
    for board in (C3_BOARD, *OPENHARDWARE_BOARDS):
        hints = dict(compiler.recipe_for(board).hints)
        assert "Serial" not in hints, board
        assert "digitalRead" in hints, f"{board}: the unfilled absences still speak"
        assert "millis" in hints and "analogRead" in hints, board


def test_a_sketch_reading_the_serial_port_still_fails_to_build():
    """The receive half is not modelled, so `Serial.read` is a missing symbol
    at the moment gcc says so -- which is where this core prefers to have the
    conversation. A `read` answering zero would be a wrong value, which is
    the one failure this project treats as worse than a loud one."""
    needs_toolchain(C3_BOARD)
    built = oh_build(C3_BOARD, "void setup(){ Serial.read(); }\nvoid loop(){}")
    assert not built.ok
    assert "read" in built.diagnostics
