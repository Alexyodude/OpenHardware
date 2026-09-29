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

from tools import import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c6

BOARD = "Adafruit Feather ESP32-C6"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "feather_esp32c6" / "blink.ino"
IMAGE = HERE / "feather_esp32c6" / "blink.bin"

GPIO_OUT = esp32c6.GPIO + esp32c6.GPIO_OUT
GPIO_ENABLE = esp32c6.GPIO + esp32c6.GPIO_ENABLE

#: Three rises of a delay(1) blink, at ~24,000 steps a millisecond
#: (`webui/arduino/variants/xiao_esp32c6/oh_board.h`), and some to spare.
BUDGET = 110_000


def needs_table() -> None:
    """Skip, naming the fetch, before anything asks for this board's recipe
    or reads its table (OH-183)."""
    table = (compiler.BOARD_SUPPORT / "arduino-esp32" / "variants"
             / "adafruit_feather_esp32c6" / "pins_arduino.h")
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")


def sda(include: str) -> int:
    """The GPIO a variant's own `pins_arduino.h` names `SDA`."""
    table = compiler.BOARD_SUPPORT / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_flat_pins((text,), extras=("SDA",))["SDA"].index


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
    gpio, not_gpio = sda(own), sda(xiao)
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    assert [pad["chip_index"] for pad in pads["pads"] if pad["label"] == "SDA"] == [gpio]
    assert gpio != not_gpio, "the XIAO's SDA is this board's, so nothing here tells them apart"

    rises, levels, driven = [], [], 0
    with api.load_firmware(BOARD, IMAGE.read_bytes(), base=recipe.base) as session:
        last = 0
        for step in range(BUDGET):
            session.step()
            out = session.cpu.read_word(GPIO_OUT)
            driven |= out
            now = out & (1 << gpio)
            if now != last:
                levels.append(api.pin_levels(session.runtime, session.cpu)["SDA"])
                rises += [step] if now else []
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"SDA changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = {b - a for a, b in itertools.pairwise(rises)}
    assert len(gaps) == 1, f"the period varies: {sorted(gaps)}"
    assert enabled & (1 << gpio) and not enabled & (1 << not_gpio)
    assert not driven & (1 << not_gpio), "the XIAO's SDA moved"
