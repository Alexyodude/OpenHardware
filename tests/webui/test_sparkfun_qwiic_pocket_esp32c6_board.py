# OpenHardware — the SparkFun Qwiic Pocket ESP32-C6 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the SparkFun Qwiic
Pocket ESP32-C6 (rules/board-claims.md §7, OH-188), made as the Thing
Plus's is (`tests/webui/test_sparkfun_esp32c6_board.py`), on another pin.

This board's `SDA` reaches no header pad, and its `TX` is the XIAO's too,
so the pin watched is `MOSI`: GPIO3 in its own variant, GPIO18 in the
XIAO's, and each a header pad here. A
sketch compiled for this board by name against its own variant,
`sparkfun_qwiic_pocket_esp32c6/pocket_blink.bin` -- rebuilt here byte for
byte where the toolchain is installed -- loaded onto the described ESP32-C6
and stepped, moves the pad whose `chip_index` is its own `MOSI`, and never
the pad whose `chip_index` is the XIAO's.
"""

import itertools
import json
import pathlib

import pytest

from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c6

BOARD = "SparkFun Qwiic Pocket ESP32-C6"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "sparkfun_qwiic_pocket_esp32c6" / "pocket_blink.ino"
IMAGE = HERE / "sparkfun_qwiic_pocket_esp32c6" / "pocket_blink.bin"

GPIO_OUT = esp32c6.GPIO + esp32c6.GPIO_OUT
GPIO_ENABLE = esp32c6.GPIO + esp32c6.GPIO_ENABLE

#: Three rises of a delay(1) blink, at ~24,000 steps a millisecond
#: (`webui/arduino/variants/xiao_esp32c6/oh_board.h`), and some to spare.
BUDGET = 110_000


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
    assert include == "arduino-esp32/variants/sparkfun_esp32c6_qwiic_pocket"
    try:
        built = compiler.build(BOARD, SKETCH.read_text(encoding="utf-8"))
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    assert built.image == IMAGE.read_bytes(), (
        f"{IMAGE.name} is not this sketch's build for {BOARD}; rebuild it with "
        f"webui.compile.build")


def test_the_image_blinks_the_gpio_this_boards_mosi_names_on_its_own_pad():
    """The pad is the one whose `chip_index` is the GPIO this board's own
    variant calls `MOSI`, which the board file traced to the module; the
    pad whose `chip_index` is the XIAO's `MOSI` reads `input` throughout."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    (xiao,) = compiler.RECIPES["ESP32-C6"].bsp_includes
    gpio, not_gpio = named(own, "MOSI"), named(xiao, "MOSI")
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    (pad,) = [pad for pad in pads["pads"] if pad["chip_index"] == gpio]
    (other,) = [pad for pad in pads["pads"] if pad["chip_index"] == not_gpio]
    # SparkFun's own net names the GPIO too, so the pad is not found by the
    # traced `chip_index` alone.
    assert f"IO{gpio}" in pad["label"].split("/"), pad["label"]
    assert f"IO{not_gpio}" in other["label"].split("/"), other["label"]
    assert gpio != not_gpio, "the XIAO's MOSI is this board's, so nothing here tells them apart"
    # Why not `SDA` or `TX`, as on the other rows: if either changes, so
    # should the pin this test watches.
    assert not [one for one in pads["pads"] if one["chip_index"] == named(own, "SDA")]
    assert named(own, "TX") == named(xiao, "TX")

    rises, levels, still, driven = [], [], set(), 0
    with api.load_firmware(BOARD, IMAGE.read_bytes(), base=recipe.base) as session:
        last = 0
        for step in range(BUDGET):
            session.step()
            out = session.cpu.read_word(GPIO_OUT)
            driven |= out
            now = out & (1 << gpio)
            if now != last:
                read = api.pin_levels(session.runtime, session.cpu)
                levels.append(read[pad["label"]])
                still.add(read[other["label"]])
                rises += [step] if now else []
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"{pad['label']} changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = {b - a for a, b in itertools.pairwise(rises)}
    assert len(gaps) == 1, f"the period varies: {sorted(gaps)}"
    assert enabled & (1 << gpio) and not enabled & (1 << not_gpio)
    assert not driven & (1 << not_gpio), "the XIAO's MOSI moved"
    assert still == {"input"}, (other["label"], still)
