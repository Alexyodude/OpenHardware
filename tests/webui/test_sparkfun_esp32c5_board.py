# OpenHardware — the SparkFun Thing Plus ESP32-C5 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the SparkFun Thing Plus
ESP32-C5 (rules/board-claims.md §7, §10 and §13, OH-194), made as the Qwiic
Pocket's is (`tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py`).

This board's `SDA` and `TX` are the XIAO ESP32-C5's, so the pin watched is
`MOSI`, which differs from the `MOSI` of every other row on the ESP32-C5 in
`tools/board_manifest.py` and of the XIAO's table, each read from its own
variant (`siblings`). A sketch compiled for this board by name against its
own variant, `sparkfun_esp32c5/sparkfun_c5_blink.bin` -- rebuilt here byte
for byte where the toolchain is installed -- loaded onto the described
ESP32-C5 and stepped, moves the pad whose `chip_index` is its own `MOSI`,
and never a sibling's `MOSI`.
"""

import itertools
import json
import pathlib
import re

import pytest

from tests.webui.test_compile import POLL
from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c5

BOARD = "SparkFun Thing Plus ESP32-C5"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "sparkfun_esp32c5" / "sparkfun_c5_blink.ino"
IMAGE = HERE / "sparkfun_esp32c5" / "sparkfun_c5_blink.bin"

GPIO_OUT = esp32c5.GPIO + esp32c5.GPIO_OUT
GPIO_ENABLE = esp32c5.GPIO + esp32c5.GPIO_ENABLE

#: A millisecond in steps, read from the description and not written here:
#: `SYSTIMER_HZ // 1000` ticks of `SYSTIMER_INSTRUCTIONS_PER_TICK` steps,
#: more of them a tick than on a C3 or a C6 at this board's 240 MHz.
#: delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), so each move of a delay(1)
#: blink comes a millisecond, and the write and the poll around it, after
#: the one before -- held to within `POLL`, as test_compile's delay tests
#: hold each delay(n).
MILLISECOND = esp32c5.SYSTIMER_INSTRUCTIONS_PER_TICK * (esp32c5.SYSTIMER_HZ // 1000)

#: Measured 2026-10-09 over fifty moves of this image: the gaps between them
#: take four lengths, 240,035, 240,041, 240,047 and 240,053 steps, and the
#: last of them to appear, 240,035, first ends at step 1,680,349, the eighth
#: move. The one period in six that is a twelve-step poll longer, 480,100
#: against 480,088, as wiring.c says a period can be, ends at the seventh.
#: 1,690,000 watches a gap of each length, with about 9,600 to spare.
BUDGET = 1_690_000


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


def parts(label: str) -> list[str]:
    """A net's name in its parts: KiCad writes SparkFun's `IO8/PICO` as
    `IO8{slash}PICO`."""
    return re.split(r"/|\{slash\}", label)


def test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant():
    needs_table()
    (include,) = compiler.recipe_for(BOARD).bsp_includes
    assert include == "arduino-esp32/variants/sparkfun_esp32c5_thing_plus"
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
        assert f"IO{one['chip_index']}" in parts(one["label"]), one["label"]
    # Why not `SDA` or `TX`, as on other rows: both are the XIAO's.
    assert named(own, "SDA") in siblings("SDA").values()
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
