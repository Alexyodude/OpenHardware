# OpenHardware — the SparkFun Qwiic Pocket ESP32-C6 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the SparkFun Qwiic
Pocket ESP32-C6 (rules/board-claims.md §7, OH-188), made as the Thing
Plus's is (`tests/webui/test_sparkfun_esp32c6_board.py`), on another pin.

This board's `SDA` reaches no header pad, and its `TX` is a sibling's, so
the pin watched is `MOSI`, which differs from the `MOSI` of every other row
on the ESP32-C6 in `tools/board_manifest.py` and of the XIAO's table, each
read from its own variant (`siblings`). A sketch compiled for this board by
name against its own variant, `sparkfun_qwiic_pocket_esp32c6/pocket_blink.bin`
-- rebuilt here byte for byte where the toolchain is installed -- loaded
onto the described ESP32-C6 and stepped, moves the pad whose `chip_index` is
its own `MOSI`, and never a sibling's `MOSI`.
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

BOARD = "SparkFun Qwiic Pocket ESP32-C6"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "sparkfun_qwiic_pocket_esp32c6" / "pocket_blink.ino"
IMAGE = HERE / "sparkfun_qwiic_pocket_esp32c6" / "pocket_blink.bin"

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

#: Five moves of this image, measured 2026-10-09: the fifth lands at step
#: 640,222, so 650,000 watches four gaps, 160,043 and 160,049 steps by
#: turns, with about 9,800 to spare. The third length, 160,055, first ends
#: at the tenth move and is not watched here. It need not be: the gaps are
#: delay()'s on this clock, measured the same on every C3 and C6 image, and
#: `POLL` holds each one to the millisecond whatever its length, so whether
#: the longest is within it is asked once per clock and not once per board
#: -- tests/webui/test_qtpy_esp32c3_board.py watches every length.
BUDGET = 650_000


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


def siblings(label: str) -> dict[str, int]:
    """`label` in every other row on this board's chip, each from its own
    variant, and in the chip's XIAO table: what a build against another
    table would drive instead."""
    row = board_manifest.row(BOARD)
    found = {other.board: named(f"{other.package}/variants/{other.variant}", label)
             for other in board_manifest.ROWS
             if other.chip == row.chip and other.board != BOARD}
    (xiao,) = compiler.RECIPES[row.chip].bsp_includes
    found[xiao] = named(xiao, label)
    return found


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
    variant calls `MOSI`, which the board file traced to the module. No
    sibling's `MOSI` is enabled or driven, and the pads whose `chip_index`
    is one read `input` throughout."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    gpio = named(own, "MOSI")
    theirs = siblings("MOSI")
    assert gpio not in theirs.values(), (gpio, theirs)
    not_gpio = set(theirs.values())
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    (pad,) = [pad for pad in pads["pads"] if pad["chip_index"] == gpio]
    others = [pad for pad in pads["pads"] if pad["chip_index"] in not_gpio]
    assert others, f"no sibling's MOSI {sorted(not_gpio)} is a pad here to read"
    # SparkFun's own net names the GPIO too, so a pad is not found by the
    # traced `chip_index` alone.
    for one in (pad, *others):
        assert f"IO{one['chip_index']}" in one["label"].split("/"), one["label"]
    # Why not `SDA` or `TX`, as on the other rows: if either changes, so
    # should the pin this test watches.
    assert not [one for one in pads["pads"] if one["chip_index"] == named(own, "SDA")]
    assert named(own, "TX") in siblings("TX").values()

    moves, levels, still, driven = [], [], set(), 0
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
                still |= {read[other["label"]] for other in others}
                moves.append(step)
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"{pad['label']} changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = [b - a for a, b in itertools.pairwise(moves)]
    assert all(abs(gap - MILLISECOND) < POLL for gap in gaps), (
        f"a delay(1) is {MILLISECOND} steps here, and {pad['label']} moved {gaps} apart")
    assert enabled & (1 << gpio)
    for sibling in not_gpio:
        assert not enabled & (1 << sibling), f"GPIO{sibling} was enabled"
        assert not driven & (1 << sibling), f"GPIO{sibling}, a sibling's MOSI, moved"
    assert still == {"input"}, ([other["label"] for other in others], still)
