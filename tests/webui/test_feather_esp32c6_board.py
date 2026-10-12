# OpenHardware — the Adafruit Feather ESP32-C6 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the Adafruit Feather
ESP32-C6 (rules/board-claims.md §7, OH-179).

`FIRMWARE_VERIFIED`'s ESP32-C6 entry watched an image with a XIAO's pins,
and a board built against another board's variant does not inherit that
(§6). So this board's own: a sketch compiled for it by name against its own
variant, `feather_esp32c6/blink.bin` -- rebuilt here byte for byte where the
toolchain is installed -- loaded onto the described ESP32-C6 and stepped,
moving the GPIO its own `SDA` names, through the pad its board file labels
`SDA`, and never the GPIO the XIAO's `SDA` names.
"""

import itertools
import json
import pathlib

import pytest

from tests.webui.esp32_timing import POLL, steps_per_millisecond
from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c6

BOARD = "Adafruit Feather ESP32-C6"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "feather_esp32c6" / "blink.ino"
IMAGE = HERE / "feather_esp32c6" / "blink.bin"

GPIO_OUT = esp32c6.GPIO + esp32c6.GPIO_OUT
GPIO_ENABLE = esp32c6.GPIO + esp32c6.GPIO_ENABLE

#: A millisecond in steps, read from the description by
#: `esp32_timing.steps_per_millisecond` and not written here.
#: delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), so each move of a delay(1)
#: blink comes a millisecond, and the write and the poll around it, after
#: the one before -- held to within `POLL`, as test_compile's delay tests
#: hold each delay(n).
MILLISECOND = steps_per_millisecond(esp32c6)

#: Five moves of this image and of the stock Blink below, measured
#: 2026-10-12, after OH-161's step 3 gave `pinMode` its pad writes: the
#: fifth lands at step 640,247 in both, so 650,000 watches four gaps --
#: 160,043, 160,061, 160,043 and 160,049 steps -- with about 9,750 to
#: spare. Those are the three lengths the gaps take over fifty moves of the
#: QT Py's and the SparkFun Thing Plus C6's images, whose first six moves
#: are this image's. That this board sees each is a fact about today's
#: wiring.c and not what the budget is for: `POLL` holds each gap to the
#: millisecond whatever its length, so whether the longest is within it is
#: asked once per clock and not once per board --
#: tests/webui/test_qtpy_esp32c3_board.py watches ten moves.
BUDGET = 650_000


def needs_table() -> None:
    """Skip, naming the fetch, before anything asks for this board's recipe
    or reads its table (OH-183)."""
    row = board_manifest.row(BOARD)
    table = (compiler.BOARD_SUPPORT / row.package / "variants" / row.variant
             / "pins_arduino.h")
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")


def named(include: str, label: str) -> int:
    """The GPIO a variant's own `pins_arduino.h` names `label`."""
    table = compiler.BOARD_SUPPORT / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_flat_pins((text,), extras=(label,))[label].index


def test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant():
    needs_table()
    (include,) = compiler.recipe_for(BOARD).bsp_includes
    assert include == "arduino-esp32/variants/adafruit_feather_esp32c6"
    try:
        built = compiler.build(BOARD, SKETCH.read_text(encoding="utf-8"))
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    assert built.image == IMAGE.read_bytes(), (
        f"{IMAGE.name} is not this sketch's build for {BOARD}; rebuild it with "
        f"webui.compile.build")


def test_the_image_blinks_the_gpio_this_boards_sda_names_on_its_sda_pad():
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    (xiao,) = compiler.RECIPES["ESP32-C6"].bsp_includes
    gpio, not_gpio = named(own, "SDA"), named(xiao, "SDA")
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    assert [pad["chip_index"] for pad in pads["pads"] if pad["label"] == "SDA"] == [gpio]
    assert gpio != not_gpio, "the XIAO's SDA is this board's, so nothing here tells them apart"

    moves, levels, driven = [], [], 0
    with api.load_firmware(BOARD, IMAGE.read_bytes(), base=recipe.base) as session:
        last = 0
        for step in range(BUDGET):
            session.step()
            out = session.cpu.read_word(GPIO_OUT)
            driven |= out
            now = out & (1 << gpio)
            if now != last:
                levels.append(api.pin_levels(session.runtime, session.cpu)["SDA"])
                moves.append(step)
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"SDA changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = [b - a for a, b in itertools.pairwise(moves)]
    assert all(abs(gap - MILLISECOND) < POLL for gap in gaps), (
        f"a delay(1) is {MILLISECOND} steps here, and SDA moved {gaps} apart")
    assert enabled & (1 << gpio) and not enabled & (1 << not_gpio)
    assert not driven & (1 << not_gpio), "the XIAO's SDA moved"


#: Arduino's stock Blink (File > Examples > 01.Basics > Blink), by
#: `LED_BUILTIN`, with `delay(1)` for its `delay(1000)` so that `BUDGET`
#: covers it.
STOCK_BLINK = """
void setup() { pinMode(LED_BUILTIN, OUTPUT); }

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(1);
  digitalWrite(LED_BUILTIN, LOW);
  delay(1);
}
"""


def test_a_stock_blink_moves_the_pad_its_led_builtin_reaches():
    """OH-183 item 5. `LED_BUILTIN`, read from this board's own variant, is
    the `chip_index` of one pad, `IO15` (OH-178), and a stock Blink compiled
    for this board by name moves that pad on the page's own path:
    `api.pin_view`, whose levels a manifest board reads at each pad's
    `chip_index` (`api.row_levels`). High first, then alternating, each move
    a delay(1) after the one before."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    assert own == "arduino-esp32/variants/adafruit_feather_esp32c6", own
    led = named(own, "LED_BUILTIN")
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    assert [pad["label"] for pad in pads["pads"] if pad["chip_index"] == led] == ["IO15"]
    try:
        built = compiler.build(BOARD, STOCK_BLINK)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics

    moves, levels = [], []
    with api.load_firmware(BOARD, built.image, base=recipe.base) as session:
        view = api.pin_view(session.runtime, session.cpu, BOARD)
        before = next(pad["state"] for pad in view["pads"] if pad["label"] == "IO15")
        last = 0
        for step in range(BUDGET):
            session.step()
            now = session.cpu.read_word(GPIO_OUT) & (1 << led)
            if now != last:
                view = api.pin_view(session.runtime, session.cpu, BOARD)
                levels.append(next(pad["state"] for pad in view["pads"]
                                   if pad["label"] == "IO15"))
                moves.append(step)
                last = now

    assert before == "input", before
    assert len(levels) >= 5, f"IO15 changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = [b - a for a, b in itertools.pairwise(moves)]
    assert all(abs(gap - MILLISECOND) < POLL for gap in gaps), (
        f"a delay(1) is {MILLISECOND} steps here, and IO15 moved {gaps} apart")
