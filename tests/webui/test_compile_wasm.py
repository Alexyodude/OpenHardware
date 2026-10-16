# OpenHardware — the browser's compiler builds what the server builds (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What is compared
#
# Each sketch here is built twice: by `webui/compile.py`, with PlatformIO's
# avr-gcc, which is what the local server's Build button runs; and by
# `webui/static/compiler/build.js`, the module the static page's Worker runs,
# over the bundle `tools/build_compiler.py` makes -- avr-gcc compiled to
# WebAssembly from the sources PlatformIO's was built from. The images must be
# the same bytes. Not "both run": the same bytes, so the browser build needs no
# emulator test of its own to be trusted.
#
# The samples are the ones that would show a difference if there were one:
# Blink at two delays (the verification the owner asked for edits that
# number), every OH-135 idiom with all three libraries -- which also holds
# that a library precompiled with only its own include root is the object
# the server compiles with all of them -- and Serial and float, which reach
# into libgcc and libm.
#
# ## Where it skips
#
# Loudly, each with its fix: without node, without the bundle, without the
# server's toolchain. Nothing here is committed -- an image links Arduino's
# LGPL core, for the reason `tests/webui/test_compile.py` gives.

import base64
import json
import pathlib
import shutil
import subprocess

import pytest

from webui import compile as compiler

REPO = pathlib.Path(__file__).resolve().parents[2]
BUNDLE = REPO / "build" / "compiler"
RUNNER = pathlib.Path(__file__).with_name("compile_wasm_runner.mjs")
BOARD = "Arduino Uno"

BLINK_500 = """void setup() { pinMode(13, OUTPUT); }
void loop() {
  digitalWrite(13, HIGH);
  delay(500);
  digitalWrite(13, LOW);
  delay(500);
}
"""

#: Blink with its delay edited: the browser verification's own edit.
BLINK_250 = BLINK_500.replace("delay(500)", "delay(250)")

#: OH-135's every idiom, as tests/webui/test_compile.py's IDIOMS.
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

#: HardwareSerial, Print's float formatting, String and placement new: the
#: C++ runtime. `<new>` is the core's own header, with no suffix.
SERIAL = """#include <new>
static char slot[sizeof(String)];
void setup() {
  Serial.begin(9600);
  Serial.println(*new (slot) String("placed"));
  Serial.println("hello, world");
  Serial.println(3.14159, 4);
}
void loop() {
  Serial.print(millis());
  String s = String(analogRead(A0)) + "x";
  Serial.println(s);
  delay(100);
}
"""

#: Soft float and sinf: libgcc's and libm's members.
FLOAT = """volatile float f = 1.5f;
void setup() { pinMode(9, OUTPUT); }
void loop() { f = f * 1.0001f + sinf(f); analogWrite(9, (int)(f * 10) & 255); }
"""

#: A syntax error on line 2 of what the person typed.
SYNTAX_ERROR = """void setup() { pinMode(13, OUTPUT); }
void loop() { int x = ; }
"""

#: The same error in a sketch that includes Arduino.h itself, so it is given
#: no preamble and no #line, and gcc names the file by its own path.
OWN_HEADER_ERROR = """#include <Arduino.h>
void setup() {}
void loop() { int x = ; }
"""

#: An error whose note points into the core's Arduino.h.
HEADER_NOTE = """void setup() { digitalWrite(13); }
void loop() {}
"""

#: A link error, which names the sketch's object in the build directory.
LINK_ERROR = """void nothere();
void setup() { nothere(); }
void loop() {}
"""

#: A board the server builds and this bundle does not.
OTHER_BOARD = "XIAO-SAMD21-DIP"


def server(source: str) -> compiler.Build:
    """What the local server's Build button gets for `source`."""
    try:
        recipe = compiler.recipe_for(BOARD)
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    return compiler.build(BOARD, source)


@pytest.fixture(scope="module")
def wasm(tmp_path_factory) -> dict[str, dict]:
    """Every sample through build.js under node, by name, in one process --
    each tool's WebAssembly compiled once, as the page's Worker does."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("SKIPPED: no node on PATH, which runs the browser's compiler here")
    if not (BUNDLE / "plan.json").is_file():
        pytest.skip(f"SKIPPED: no {BUNDLE.relative_to(REPO)}; python tools/build_compiler.py")
    builds = {
        "blink_500": (BOARD, BLINK_500),
        "blink_250": (BOARD, BLINK_250),
        "idioms": (BOARD, IDIOMS),
        "serial": (BOARD, SERIAL),
        "float": (BOARD, FLOAT),
        "syntax_error": (BOARD, SYNTAX_ERROR),
        "own_header_error": (BOARD, OWN_HEADER_ERROR),
        "header_note": (BOARD, HEADER_NOTE),
        "link_error": (BOARD, LINK_ERROR),
        "other_board": (OTHER_BOARD, BLINK_500),
    }
    work = tmp_path_factory.mktemp("compile-wasm")
    job = {"bundle": str(BUNDLE), "result": str(work / "result.json"),
           "builds": [{"board": board, "source": source} for board, source in builds.values()]}
    (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
    done = subprocess.run([node, str(RUNNER), str(work / "job.json")],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr
    results = json.loads((work / "result.json").read_text(encoding="utf-8"))
    return dict(zip(builds, results))


def image(result: dict) -> bytes:
    return base64.b64decode(result["image"])


def test_blink_is_the_servers_bytes(wasm):
    assert image(wasm["blink_500"]) == server(BLINK_500).image


def test_blink_with_its_delay_edited_is_the_servers_bytes(wasm):
    assert image(wasm["blink_250"]) == server(BLINK_250).image


def test_blink_edited_is_a_different_image_from_blink(wasm):
    """So the two comparisons above are two facts, not one twice."""
    assert image(wasm["blink_250"]) != image(wasm["blink_500"])


def test_every_idiom_with_all_three_libraries_is_the_servers_bytes(wasm):
    assert image(wasm["idioms"]) == server(IDIOMS).image


def test_serial_print_and_string_are_the_servers_bytes(wasm):
    assert image(wasm["serial"]) == server(SERIAL).image


def test_float_and_libm_are_the_servers_bytes(wasm):
    assert image(wasm["float"]) == server(FLOAT).image


def test_a_built_sketch_says_ok_with_nothing_to_report(wasm):
    assert (wasm["blink_500"]["ok"], wasm["blink_500"]["diagnostics"]) == (True, "")


def test_a_syntax_error_fails_with_no_image(wasm):
    """No image is what keeps the board as it was: the page loads only an ok build."""
    assert (wasm["syntax_error"]["ok"], image(wasm["syntax_error"])) == (False, b"")


def test_a_syntax_error_is_reported_on_the_line_it_was_typed_on(wasm):
    assert "sketch.cpp:2:23: error: expected primary-expression" in wasm["syntax_error"]["diagnostics"]


def test_a_syntax_errors_diagnostics_are_the_servers_words(wasm):
    assert wasm["syntax_error"]["diagnostics"] == server(SYNTAX_ERROR).diagnostics


def test_a_sketch_including_arduino_h_itself_names_its_errors_as_the_server_does(wasm):
    assert wasm["own_header_error"]["diagnostics"] == server(OWN_HEADER_ERROR).diagnostics


def test_a_note_in_a_core_header_names_the_header_as_the_server_does(wasm):
    """The server prints its own host's separators, and this always prints
    `/`: on Windows the server writes `<toolchain>`, `framework-arduino-avr`
    and `cores` with backslashes between them."""
    assert (wasm["header_note"]["diagnostics"]
            == server(HEADER_NOTE).diagnostics.replace("\\", "/"))


def test_a_link_error_names_the_build_directory_as_the_server_does(wasm):
    """All but the server's last line, collect2's `error: ld returned 1 exit
    status`: the server's driver runs ld through collect2, and this runs ld
    itself."""
    server_lines = server(LINK_ERROR).diagnostics.replace("\\", "/").splitlines()
    assert wasm["link_error"]["diagnostics"].splitlines() == server_lines[:-1]


def test_a_failed_compile_names_the_compiler_that_failed(wasm):
    assert wasm["syntax_error"]["command"][0] == "cc1plus"


def test_a_board_whose_compiler_is_not_bundled_is_refused_naming_the_local_server(wasm):
    assert "python webui/emulator_server.py" in wasm["other_board"]["refused"]
