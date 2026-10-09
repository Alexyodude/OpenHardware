# OpenHardware — the SparkFun Pro Micro ESP32-C3 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the SparkFun Pro Micro
ESP32-C3 (rules/board-claims.md §7, OH-188), made as the QT Py ESP32-C3's
is (`tests/webui/test_qtpy_esp32c3_board.py`), on another pin.

Its `SDA` is a sibling's -- the QT Py's GPIO5 -- so an `SDA` blink built
for it would be that sibling's image byte for byte. The pin watched is
`MOSI` instead, which differs from the `MOSI` of every other row on the
ESP32-C3 in `tools/board_manifest.py` and of the XIAO's table, each read
from its own variant (`siblings`). A sketch compiled for this board by name
against its own variant, `sparkfun_pro_micro_esp32c3/promicro_blink.bin` --
rebuilt here byte for byte where the toolchain is installed -- loaded onto
the described ESP32-C3 and stepped, moves the pad whose `chip_index` is its
own `MOSI`, and never a sibling's `MOSI`.
"""

import itertools
import json
import pathlib

import pytest

from tests.webui.test_compile import POLL
from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c3

BOARD = "SparkFun Pro Micro ESP32-C3"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "sparkfun_pro_micro_esp32c3" / "promicro_blink.ino"
IMAGE = HERE / "sparkfun_pro_micro_esp32c3" / "promicro_blink.bin"

GPIO_OUT = esp32c3.GPIO + esp32c3.GPIO_OUT
GPIO_ENABLE = esp32c3.GPIO + esp32c3.GPIO_ENABLE

#: A millisecond in steps, read from the description and not written here:
#: `SYSTIMER_HZ // 1000` ticks of `SYSTIMER_INSTRUCTIONS_PER_TICK` steps.
#: delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), so each move of a delay(1)
#: blink comes a millisecond, and the write and the poll around it, after
#: the one before -- held to within `POLL`, as test_compile's delay tests
#: hold each delay(n).
MILLISECOND = esp32c3.SYSTIMER_INSTRUCTIONS_PER_TICK * (esp32c3.SYSTIMER_HZ // 1000)

#: Measured 2026-10-09 over fifty moves of this image: the gaps between them
#: take three lengths, 160,043, 160,049 and 160,055 steps, and the longest
#: first ends at step 1,440,461, the tenth move. It is half of the one period
#: in four that is a twelve-step poll longer, 320,104 against 320,092, as
#: wiring.c says a period can be. 1,450,000 watches a gap of each length,
#: with about 9,500 to spare.
BUDGET = 1_450_000


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
    framework (`extra_includes`) and this board's and the QT Py's from the
    board-support checkout (`bsp_includes`)."""
    table = root / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_flat_pins((text,), extras=(label,))[label].index


def siblings(label: str) -> dict[str, int]:
    """`label` in every other row on this board's chip, each from its own
    variant, and in the chip's XIAO table: what a build against another
    table would drive instead."""
    row = board_manifest.row(BOARD)
    found = {other.board: named(compiler.BOARD_SUPPORT,
                                f"{other.package}/variants/{other.variant}", label)
             for other in board_manifest.ROWS
             if other.chip == row.chip and other.board != BOARD}
    (xiao,) = compiler.RECIPES[row.chip].extra_includes
    found[xiao] = named(compiler.PACKAGES, xiao, label)
    return found


def test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant():
    needs_table()
    (include,) = compiler.recipe_for(BOARD).bsp_includes
    assert include == "arduino-esp32/variants/sparkfun_pro_micro_esp32c3"
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
    variant calls `MOSI`, and SparkFun's net names that GPIO as its module
    symbol does: `IOA3/PICO`. No sibling's `MOSI` is enabled or driven, and
    the pads whose `chip_index` is one read `input` throughout."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    gpio = named(compiler.BOARD_SUPPORT, own, "MOSI")
    theirs = siblings("MOSI")
    assert gpio not in theirs.values(), (gpio, theirs)
    not_gpio = set(theirs.values())
    # Why not `SDA`: a sibling shares it. If none does, watch it again.
    assert named(compiler.BOARD_SUPPORT, own, "SDA") in siblings("SDA").values()
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    (pad,) = [pad for pad in pads["pads"] if pad["chip_index"] == gpio]
    assert f"IOA{gpio}" in pad["label"].split("/"), pad["label"]
    others = [pad for pad in pads["pads"] if pad["chip_index"] in not_gpio]
    assert others, f"no sibling's MOSI {sorted(not_gpio)} is a pad here to read"

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
