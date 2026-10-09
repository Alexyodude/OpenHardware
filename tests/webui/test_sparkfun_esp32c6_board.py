# OpenHardware — the SparkFun Thing Plus ESP32-C6 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the SparkFun Thing Plus
ESP32-C6 (rules/board-claims.md §7, OH-185), made as the Feather's is
(`tests/webui/test_feather_esp32c6_board.py`).

A sketch compiled for this board by name against its own variant,
`sparkfun_esp32c6/sparkfun_blink.bin` -- rebuilt here byte for byte where
the toolchain is installed -- loaded onto the described ESP32-C6 and
stepped, moving the GPIO its own `SDA` names, through the pad its board
file labels `SDA`, and never the GPIO the XIAO's `SDA` names.
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

BOARD = "SparkFun Thing Plus ESP32-C6"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "sparkfun_esp32c6" / "sparkfun_blink.ino"
IMAGE = HERE / "sparkfun_esp32c6" / "sparkfun_blink.bin"

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

#: Measured 2026-10-09: this image moves at the same steps as the QT Py
#: ESP32-C3's, and its gaps take the same three lengths, 160,043, 160,049
#: and 160,055 steps, the longest first ending at step 1,440,461, the tenth
#: move. 1,450,000 watches a gap of each length, with about 9,500 to spare.
#:
#: Every length is watched here as well as on the QT Py because the clock
#: is one but the description is not: the C6 has its own module and its
#: own SYSTIMER base (`webui/boards/esp32c6.py`), so a fault only the C6's
#: description had, showing only from the tenth move, would otherwise be
#: watched by no test. The other C6 board tests watch five moves.
BUDGET = 1_450_000


def needs_table() -> None:
    """Skip, naming the fetch, before anything asks for this board's recipe
    or reads its table."""
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
    assert include == "arduino-esp32/variants/sparkfun_esp32c6_thing_plus"
    try:
        built = compiler.build(BOARD, SKETCH.read_text(encoding="utf-8"))
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    assert built.image == IMAGE.read_bytes(), (
        f"{IMAGE.name} is not this sketch's build for {BOARD}; rebuild it with "
        f"webui.compile.build")


def test_the_image_blinks_the_gpio_this_boards_sda_names_on_its_sda_pad():
    """The pad is the one whose label names `SDA` (`IO6/SDA`), and its
    `chip_index` is the GPIO this board's own variant calls `SDA`."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    (xiao,) = compiler.RECIPES["ESP32-C6"].bsp_includes
    gpio, not_gpio = named(own, "SDA"), named(xiao, "SDA")
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    (pad,) = [pad for pad in pads["pads"] if "SDA" in pad["label"].split("/")]
    assert pad["chip_index"] == gpio, (pad, gpio)
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
                levels.append(api.pin_levels(session.runtime, session.cpu)[pad["label"]])
                moves.append(step)
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"{pad['label']} changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = [b - a for a, b in itertools.pairwise(moves)]
    assert all(abs(gap - MILLISECOND) < POLL for gap in gaps), (
        f"a delay(1) is {MILLISECOND} steps here, and {pad['label']} moved {gaps} apart")
    assert enabled & (1 << gpio) and not enabled & (1 << not_gpio)
    assert not driven & (1 << not_gpio), "the XIAO's SDA moved"
