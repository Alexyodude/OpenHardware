# OpenHardware — the Adafruit QT Py ESP32-C3 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the Adafruit QT Py
ESP32-C3 (rules/board-claims.md §7, OH-185), made as the Feather's is
(`tests/webui/test_feather_esp32c6_board.py`).

A sketch compiled for this board by name against its own variant,
`qtpy_esp32c3/qtpy_blink.bin` -- rebuilt here byte for byte where the
toolchain is installed -- loaded onto the described ESP32-C3 and stepped,
moving the GPIO its own `SDA` names, through the pad its board file labels
`SDA`, and never the GPIO the XIAO's `SDA` names.
"""

import itertools
import json
import pathlib

import pytest

from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c3

BOARD = "Adafruit QT Py ESP32-C3"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "qtpy_esp32c3" / "qtpy_blink.ino"
IMAGE = HERE / "qtpy_esp32c3" / "qtpy_blink.bin"

GPIO_OUT = esp32c3.GPIO + esp32c3.GPIO_OUT
GPIO_ENABLE = esp32c3.GPIO + esp32c3.GPIO_ENABLE

#: Three rises of a delay(1) blink. delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), and a millisecond of it is
#: 16,000 ticks of ten steps, so each half of the blink is 160,000 steps and
#: the toggle around it. Measured 2026-10-09 on this image, the pin moves at
#: steps 38, 160,081, 320,130, 480,173 and 640,222: 650,000 leaves about
#: 9,800 to spare. Both periods in that window are 320,092 steps; the fifth
#: is 320,104, one twelve-step poll longer, as wiring.c says a period can be.
BUDGET = 650_000


def needs_table() -> None:
    """Skip, naming the fetch, before anything asks for this board's recipe
    or reads its table."""
    row = board_manifest.row(BOARD)
    table = (compiler.BOARD_SUPPORT / row.package / "variants" / row.variant
             / "pins_arduino.h")
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")


def named(root: pathlib.Path, include: str, label: str) -> int:
    """The GPIO the `pins_arduino.h` under `root / include` names `label`.

    Two roots, because the XIAO ESP32-C3's table comes from PlatformIO's
    framework (`extra_includes`) and this board's from the board-support
    checkout (`bsp_includes`)."""
    table = root / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_flat_pins((text,), extras=(label,))[label].index


def test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant():
    needs_table()
    (include,) = compiler.recipe_for(BOARD).bsp_includes
    assert include == "arduino-esp32/variants/adafruit_qtpy_esp32c3"
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
    (xiao,) = compiler.RECIPES["ESP32-C3"].extra_includes
    gpio = named(compiler.BOARD_SUPPORT, own, "SDA")
    not_gpio = named(compiler.PACKAGES, xiao, "SDA")
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
