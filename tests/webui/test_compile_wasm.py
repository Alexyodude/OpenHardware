# OpenHardware — the browser's compiler builds what the server builds (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What is compared
#
# Each sketch here is built twice: by `webui/compile.py`, with PlatformIO's
# avr-gcc, arm-none-eabi GCC or riscv32-esp-elf GCC, which is what the local
# server's Build button
# runs; and by `webui/static/compiler/build.js`, the module the static page's
# Worker runs, over the bundle `tools/build_compiler.py` makes -- the same GCC
# compiled to WebAssembly from the sources PlatformIO's was built from. The
# images must be the same bytes. Not "both run": the same bytes, so the
# browser build needs no emulator test of its own to be trusted. The Uno's
# samples come first, then the XIAO SAMD21's, then the XIAO ESP32s'.
#
# The samples are the ones that would show a difference if there were one:
# Blink at two delays (the verification the owner asked for edits that
# number), every OH-135 idiom with all three libraries -- which also holds
# that a library precompiled with only its own include root is the object
# the server compiles with all of them -- and Serial and float, which reach
# into libgcc and libm.
#
# ## The one known difference
#
# A file of a core compiled with an `assert` puts its own path in the image,
# as `__FILE__`, wherever the assert is linked. The server's path is
# PlatformIO's install directory on the machine it runs on -- a user's home
# directory -- so no other build can be its bytes. One file of the SAMD core
# does it, SPI.cpp's SPIClassSAMD constructor, which the global `SPI` inlines
# and a sketch building a bus of its own links;
# `test_a_samd21_sketch_with_its_own_spi_bus_names_spi_cpp_by_each_sides_own_path`
# holds what each side names, so it fails, and says so, the day the server
# maps its paths. The Uno's core has no assert.
#
# ## Where it skips
#
# Loudly, each with its fix: without node, without the bundle, without the
# server's toolchain. Nothing here is committed -- an image links Arduino's
# LGPL core, for the reason `tests/webui/test_compile.py` gives.

import base64
import json
import pathlib
import re
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

#: The bundle's second chip, the SAMD21, by arm-none-eabi GCC 12.3.1.
SAMD_BOARD = "XIAO-SAMD21-DIP"

#: tests/webui/test_compile.py's SAMD_BLINK, at the Uno's two delays:
#: LED_BUILTIN, because Seeed's variant is what maps it.
SAMD_BLINK_500 = """void setup() { pinMode(LED_BUILTIN, OUTPUT); }
void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
  delay(500);
}
"""
SAMD_BLINK_250 = SAMD_BLINK_500.replace("delay(500)", "delay(250)")

#: tests/webui/test_compile.py's SAMD_IDIOMS: the SAMD21 has no EEPROM, and
#: its core no such library.
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

#: SERIAL on the UART, `Serial1`: on a XIAO `Serial` is USB CDC, which the
#: server's recipe builds without on purpose (webui/compile.py), so a sketch
#: printing to it does not compile on either side.
SAMD_SERIAL = SERIAL.replace("Serial.", "Serial1.")

#: A second SPI bus, the usual SAMD pattern: it links SPIClassSAMD's own
#: constructor, and with it the assert that names SPI.cpp's path.
SAMD_OWN_SPI = """#include <SPI.h>
SPIClassSAMD mySPI(&sercom1, 12, 13, 11, SPI_PAD_0_SCK_1, SERCOM_RX_PAD_3);
void setup() { mySPI.begin(); mySPI.transfer(0x55); }
void loop() {}
"""

#: The bundle's third toolchain, riscv32-esp-elf GCC 8.4.0, for three chips.
ESP_BOARD = "XIAO-ESP32-C3-DIP"
ESP_C5_BOARD = "XIAO-ESP32-C5-DIP"
ESP_C6_BOARD = "XIAO-ESP32-C6-DIP"

#: Blink on D10, a pin every XIAO's vendor table names: the ESP32 rows build
#: the repository's own core, whose LED_BUILTIN is the vendor's, and on these
#: boards that is no GPIO the model drives (webui/compile.py's hint says why).
ESP_BLINK_500 = """void setup() { pinMode(D10, OUTPUT); }
void loop() {
  digitalWrite(D10, HIGH);
  delay(500);
  digitalWrite(D10, LOW);
  delay(500);
}
"""
ESP_BLINK_250 = ESP_BLINK_500.replace("delay(500)", "delay(250)")

#: Everything the ESP32 rows' core carries: Wire, its one library; the UART's
#: transmit half; SYSTIMER's millis and micros; GPIO_IN; ADC1.
ESP_IDIOMS = """
#include <Wire.h>
void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.beginTransmission(0x3C);
  Wire.write(0x00);
  Wire.endTransmission();
  pinMode(D2, INPUT_PULLUP);
  Serial.println(digitalRead(D2));
  Serial.println(analogRead(A0));
  Serial.println(millis());
  Serial.println(micros());
  delayMicroseconds(10);
}
void loop() {}
"""

#: A board the server builds and this bundle does not: a row of
#: tools/board_manifest.py, whose recipe is its own -- the C3's with the
#: board's own pin table -- and not the chip's this bundle carries.
OTHER_BOARD = "Adafruit QT Py ESP32-C3"


def server(source: str, board: str = BOARD) -> compiler.Build:
    """What the local server's Build button gets for `source` on `board`."""
    try:
        recipe = compiler.recipe_for(board)
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
        compiler.variant_root(recipe)
        compiler.include_roots(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    return compiler.build(board, source)


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
        "samd_blink_500": (SAMD_BOARD, SAMD_BLINK_500),
        "samd_blink_250": (SAMD_BOARD, SAMD_BLINK_250),
        "samd_idioms": (SAMD_BOARD, SAMD_IDIOMS),
        "samd_serial": (SAMD_BOARD, SAMD_SERIAL),
        "samd_float": (SAMD_BOARD, FLOAT),
        "samd_syntax_error": (SAMD_BOARD, SYNTAX_ERROR),
        "samd_header_note": (SAMD_BOARD, HEADER_NOTE),
        "samd_link_error": (SAMD_BOARD, LINK_ERROR),
        "samd_own_spi": (SAMD_BOARD, SAMD_OWN_SPI),
        "esp_blink_500": (ESP_BOARD, ESP_BLINK_500),
        "esp_blink_250": (ESP_BOARD, ESP_BLINK_250),
        "esp_idioms": (ESP_BOARD, ESP_IDIOMS),
        "esp_syntax_error": (ESP_BOARD, SYNTAX_ERROR),
        "esp_header_note": (ESP_BOARD, HEADER_NOTE),
        "esp_link_error": (ESP_BOARD, LINK_ERROR),
        "esp_c5_blink": (ESP_C5_BOARD, ESP_BLINK_500),
        "esp_c5_idioms": (ESP_C5_BOARD, ESP_IDIOMS),
        "esp_c6_blink": (ESP_C6_BOARD, ESP_BLINK_500),
        "esp_c6_idioms": (ESP_C6_BOARD, ESP_IDIOMS),
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


def test_every_uno_sample_meant_to_build_builds(wasm):
    """So no comparison of images below is of two empty ones."""
    samples = ("blink_500", "blink_250", "idioms", "serial", "float")
    assert {name: wasm[name]["ok"] for name in samples} == dict.fromkeys(samples, True)


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


def test_every_samd21_sample_meant_to_build_builds(wasm):
    """So no comparison of images below is of two empty ones."""
    samples = ("samd_blink_500", "samd_blink_250", "samd_idioms", "samd_serial", "samd_float",
               "samd_own_spi")
    assert {name: wasm[name]["ok"] for name in samples} == dict.fromkeys(samples, True)


def test_samd21_blink_is_the_servers_bytes(wasm):
    assert image(wasm["samd_blink_500"]) == server(SAMD_BLINK_500, SAMD_BOARD).image


def test_samd21_blink_with_its_delay_edited_is_the_servers_bytes(wasm):
    assert image(wasm["samd_blink_250"]) == server(SAMD_BLINK_250, SAMD_BOARD).image


def test_samd21_blink_edited_is_a_different_image_from_blink(wasm):
    assert image(wasm["samd_blink_250"]) != image(wasm["samd_blink_500"])


def test_samd21_every_idiom_with_wire_and_spi_is_the_servers_bytes(wasm):
    assert image(wasm["samd_idioms"]) == server(SAMD_IDIOMS, SAMD_BOARD).image


def test_samd21_serial_print_and_string_are_the_servers_bytes(wasm):
    """Uart and SERCOM, Print's float formatting and String, on newlib-nano."""
    assert image(wasm["samd_serial"]) == server(SAMD_SERIAL, SAMD_BOARD).image


def test_samd21_float_and_libm_are_the_servers_bytes(wasm):
    assert image(wasm["samd_float"]) == server(FLOAT, SAMD_BOARD).image


def test_a_samd21_syntax_error_fails_with_no_image(wasm):
    assert (wasm["samd_syntax_error"]["ok"], image(wasm["samd_syntax_error"])) == (False, b"")


def test_a_samd21_syntax_errors_diagnostics_are_the_servers_words(wasm):
    assert (wasm["samd_syntax_error"]["diagnostics"]
            == server(SYNTAX_ERROR, SAMD_BOARD).diagnostics)


def test_a_samd21_note_in_a_core_header_names_the_header_as_the_server_does(wasm):
    assert (wasm["samd_header_note"]["diagnostics"]
            == server(HEADER_NOTE, SAMD_BOARD).diagnostics.replace("\\", "/"))


def test_a_samd21_link_error_is_the_servers_but_for_how_each_spells_the_toolchain(wasm):
    """Every line the server prints but its last, collect2's, as on the Uno,
    with three spellings of one toolchain read as one:

    - binutils 2.40 opens each line with the path ld was run as, which the
      Uno's 2.26 does not: the server's is collect2's `ld` under PlatformIO,
      the tab's its own `arm-none-eabi-ld`. Both are taken off.
    - On Windows this ld prints the server's paths lowercased, `c:/users/...`,
      so compile.py's `<toolchain>` label, spelled as PACKAGES is, misses
      them; they are read here as the label would have had them.
    - The server's driver found its libraries from its bin/, as `bin/../lib`;
      the tab's ran where it was configured, so `lib`.

    What is left -- each archive member, function, warning and the undefined
    reference, in order -- is compared exactly."""
    server_text = (server(LINK_ERROR, SAMD_BOARD).diagnostics.replace("\\", "/")
                   .replace(str(compiler.PACKAGES).replace("\\", "/").lower(), "<toolchain>")
                   .replace("/bin/../lib/", "/lib/"))
    server_lines = re.sub(r"^\S*/bin/ld(\.exe)?: ", "", server_text, flags=re.M).splitlines()
    wasm_lines = re.sub(r"^\S*/arm-none-eabi-ld: ", "",
                        wasm["samd_link_error"]["diagnostics"], flags=re.M).splitlines()
    assert wasm_lines == server_lines[:-1]


def test_a_samd21_link_error_names_the_function_it_could_not_find(wasm):
    """So the comparison above is of two link errors, and not of two builds
    that stopped somewhere else."""
    assert "undefined reference to `nothere()'" in wasm["samd_link_error"]["diagnostics"]


def test_a_samd21_sketch_with_its_own_spi_bus_names_spi_cpp_by_each_sides_own_path(wasm):
    """THE KNOWN DIFFERENCE, held so that it is seen (this file's header).

    SPIClassSAMD's constructor asserts, so `__FILE__` is in the image: the
    server's, its own install path under PACKAGES; the tab's, the core's path
    in the bundle. The two images differ by that string and whatever its
    length moves. compile.py is not changed by this ticket; giving both sides
    one path for the core is OH-247, and when it lands all three of these
    turn over -- neither image holds its own path any more, and the two are
    one -- and this becomes a same-bytes test."""
    tab, there = image(wasm["samd_own_spi"]), server(SAMD_OWN_SPI, SAMD_BOARD).image
    spi = compiler.PACKAGES / "framework-arduino-samd" / "libraries" / "SPI" / "SPI.cpp"
    assert ((b"/framework-arduino-samd/libraries/SPI/SPI.cpp" in tab),
            (str(spi).encode() in there), (tab == there)) == (True, True, False)


def test_every_esp32_sample_meant_to_build_builds(wasm):
    """So no comparison of images below is of two empty ones."""
    samples = ("esp_blink_500", "esp_blink_250", "esp_idioms", "esp_c5_blink", "esp_c5_idioms",
               "esp_c6_blink", "esp_c6_idioms")
    assert {name: wasm[name]["ok"] for name in samples} == dict.fromkeys(samples, True)


def test_esp32_c3_blink_is_the_servers_bytes(wasm):
    assert image(wasm["esp_blink_500"]) == server(ESP_BLINK_500, ESP_BOARD).image


def test_esp32_c3_blink_with_its_delay_edited_is_the_servers_bytes(wasm):
    assert image(wasm["esp_blink_250"]) == server(ESP_BLINK_250, ESP_BOARD).image


def test_esp32_c3_blink_edited_is_a_different_image_from_blink(wasm):
    assert image(wasm["esp_blink_250"]) != image(wasm["esp_blink_500"])


def test_esp32_c3_every_idiom_with_wire_is_the_servers_bytes(wasm):
    assert image(wasm["esp_idioms"]) == server(ESP_IDIOMS, ESP_BOARD).image


def test_esp32_c5_blink_is_the_servers_bytes(wasm):
    """rv32imac, and the C5's own pin table from third_party/bsp."""
    assert image(wasm["esp_c5_blink"]) == server(ESP_BLINK_500, ESP_C5_BOARD).image


def test_esp32_c5_every_idiom_with_wire_is_the_servers_bytes(wasm):
    assert image(wasm["esp_c5_idioms"]) == server(ESP_IDIOMS, ESP_C5_BOARD).image


def test_esp32_c6_blink_is_the_servers_bytes(wasm):
    """rv32imac, and the C6's pin table, which includes the variant's own
    soc/soc_caps.h."""
    assert image(wasm["esp_c6_blink"]) == server(ESP_BLINK_500, ESP_C6_BOARD).image


def test_esp32_c6_every_idiom_with_wire_is_the_servers_bytes(wasm):
    assert image(wasm["esp_c6_idioms"]) == server(ESP_IDIOMS, ESP_C6_BOARD).image


def test_the_three_esp32s_build_three_different_images_of_one_sketch(wasm):
    """One sketch, three images: D10 is a different GPIO on each board and
    each links its own variant's script. That each chip's objects are its
    own is what the per-chip same-bytes tests above hold."""
    images = {image(wasm[name]) for name in ("esp_blink_500", "esp_c5_blink", "esp_c6_blink")}
    assert len(images) == 3


def test_an_esp32_syntax_error_fails_with_no_image(wasm):
    assert (wasm["esp_syntax_error"]["ok"], image(wasm["esp_syntax_error"])) == (False, b"")


def test_an_esp32_syntax_errors_diagnostics_are_the_servers_words(wasm):
    assert wasm["esp_syntax_error"]["diagnostics"] == server(SYNTAX_ERROR, ESP_BOARD).diagnostics


def test_an_esp32_note_in_the_core_names_it_from_the_checkout_as_the_server_does(wasm):
    """The server names webui/arduino by its whole path on the machine, which
    says nothing in a tab; the tab names it from the checkout's root. Read
    so, and with the server's separators made the tab's, the words, the
    quoted line and its caret are the same."""
    lite = str(compiler.ARDUINO_LITE).replace("\\", "/")
    there = (server(HEADER_NOTE, ESP_BOARD).diagnostics.replace("\\", "/")
             .replace(lite, "webui/arduino"))
    assert wasm["esp_header_note"]["diagnostics"] == there


def test_an_esp32_link_error_is_the_servers_but_for_how_each_spells_the_toolchain(wasm):
    """As the SAMD21's: binutils 2.35 also opens each line with the path ld
    ran as, which differs, and the server's last line is collect2's. The
    build directory is `<build>` on both sides once the server's separator is
    the tab's."""
    there = re.sub(r"^\S*/bin/ld(\.exe)?: ", "",
                   server(LINK_ERROR, ESP_BOARD).diagnostics.replace("\\", "/"), flags=re.M)
    tab = re.sub(r"^\S*/riscv32-esp-elf-ld: ", "", wasm["esp_link_error"]["diagnostics"],
                 flags=re.M)
    assert tab.splitlines() == there.splitlines()[:-1]


def test_an_esp32_link_error_names_the_function_it_could_not_find(wasm):
    assert "undefined reference to `nothere()'" in wasm["esp_link_error"]["diagnostics"]
