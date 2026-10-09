# OpenHardware — the Olimex ESP32-C6-EVB runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the Olimex ESP32-C6-EVB
(rules/board-claims.md §7, §10 and §13, OH-198), made as the
ESP32-C3-DevKit-Lipo's is (`tests/webui/test_olimex_esp32c3_devkit_lipo_board.py`),
on the ESP32-C6.

The pin watched is `LED_BUILTIN`, which its variant numbers on the EXT1 pad
whose own net Olimex names for that GPIO and for the LED,
`/GPIO8\\USER_LED1`, and which no other table on the ESP32-C6 numbers alike:
the other rows in `tools/board_manifest.py` and the XIAO's table either
number it another GPIO or number no pin at all, each read from its own
variant (`siblings`). None of those other GPIOs is a pad of this board's
header, so a build against another table would move no pad here at all. A
sketch compiled for this board by name against its own variant,
`olimex_esp32c6_evb/evb_blink.bin` -- rebuilt here byte for byte where the
toolchain is installed -- loaded onto the described ESP32-C6 and stepped,
moves the pad whose `chip_index` is its own `LED_BUILTIN`, and never drives
a sibling's.
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
from webui.boards import esp32c6

BOARD = "Olimex ESP32-C6-EVB"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "olimex_esp32c6_evb" / "evb_blink.ino"
IMAGE = HERE / "olimex_esp32c6_evb" / "evb_blink.bin"

GPIO_OUT = esp32c6.GPIO + esp32c6.GPIO_OUT
GPIO_ENABLE = esp32c6.GPIO + esp32c6.GPIO_ENABLE

#: A millisecond in steps, read from the description and not written here:
#: `SYSTIMER_HZ // 1000` ticks of `SYSTIMER_INSTRUCTIONS_PER_TICK` steps.
#: delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), so each move of a delay(1)
#: blink comes a millisecond, and the write and the poll around it, after
#: the one before -- held to within `POLL`, as test_compile's delay tests
#: hold each delay(n).
MILLISECOND = esp32c6.SYSTIMER_INSTRUCTIONS_PER_TICK * (esp32c6.SYSTIMER_HZ // 1000)

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


def named(include: str, label: str) -> int | None:
    """The GPIO a variant's own `pins_arduino.h` numbers `label`, or None
    where it numbers none: no definition, or one that is not an integer, as
    the Thing Plus's `SOC_GPIO_PIN_COUNT + PIN_RGB_LED` is."""
    table = compiler.BOARD_SUPPORT / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_c_pin_constants(text).get(label)


def siblings(label: str) -> dict[str, int | None]:
    """`label` in every other row on this board's chip, each from its own
    variant, and in the chip's XIAO table: what a build against another
    table would drive instead, or None where it could drive nothing."""
    row = board_manifest.row(BOARD)
    found = {other.board: named(f"{other.package}/variants/{other.variant}", label)
             for other in board_manifest.ROWS
             if other.chip == row.chip and other.board != BOARD}
    (xiao,) = compiler.RECIPES[row.chip].bsp_includes
    found[xiao] = named(xiao, label)
    return found


def parts(label: str) -> list[str]:
    """A net's name in the parts Olimex writes it in: `/GPIO8\\USER_LED1` is
    the GPIO and what it is for."""
    return re.split(r"[/\\]", label)


def test_the_image_is_this_sketch_built_for_this_board_against_its_own_variant():
    needs_table()
    (include,) = compiler.recipe_for(BOARD).bsp_includes
    assert include == "arduino-esp32/variants/esp32c6-evb"
    try:
        built = compiler.build(BOARD, SKETCH.read_text(encoding="utf-8"))
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    assert built.image == IMAGE.read_bytes(), (
        f"{IMAGE.name} is not this sketch's build for {BOARD}; rebuild it with "
        f"webui.compile.build")


def test_a_build_against_a_sibling_table_that_numbers_no_led_builtin_is_refused():
    """What makes a sibling whose table numbers no `LED_BUILTIN` harmless:
    this sketch, built for that board, is refused, so no image of it could
    move another pad. The XIAO's table is built through any XIAO on the
    chip, since all of them share its recipe."""
    from webui.boards import catalogue

    needs_table()
    row = board_manifest.row(BOARD)
    sketch = SKETCH.read_text(encoding="utf-8")
    (xiao,) = compiler.RECIPES[row.chip].bsp_includes
    unnumbered = [board for board, gpio in siblings("LED_BUILTIN").items() if gpio is None]
    assert unnumbered, "every sibling numbers LED_BUILTIN, so this checks nothing"
    for board in unnumbered:
        if board == xiao:
            board = next(name for name in catalogue.board_names()
                         if catalogue.chip_for(name) == row.chip
                         and board_manifest.find(name) is None)
        try:
            built = compiler.build(board, sketch)
        except compiler.ToolchainMissing as exc:
            pytest.skip(str(exc))
        assert not built.ok, board
        assert "LED_BUILTIN" in built.diagnostics or "oh_pin_is_past" in built.diagnostics, (
            board, built.diagnostics)


def test_the_image_blinks_the_gpio_this_boards_led_builtin_names_on_its_own_pad():
    """The pad is the one whose `chip_index` is the GPIO this board's own
    variant calls `LED_BUILTIN`, which the KiCad 5 board file traced to the
    module, and whose net Olimex names for that GPIO and the LED. No
    sibling's `LED_BUILTIN` is a pad of this board's header, or is enabled
    or driven."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    gpio = named(own, "LED_BUILTIN")
    assert gpio is not None
    theirs = siblings("LED_BUILTIN")
    assert gpio not in theirs.values(), (gpio, theirs)
    not_gpio = {sibling for sibling in theirs.values() if sibling is not None}
    assert not_gpio, "no sibling numbers LED_BUILTIN, so nothing here is excluded"
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    (pad,) = [pad for pad in pads["pads"] if pad["chip_index"] == gpio]
    # A build against a sibling's table drives a GPIO no pad of EXT1 carries,
    # so it moves no pad here and this one stays still: the run below would
    # see nothing on it.
    assert not [one for one in pads["pads"] if one["chip_index"] in not_gpio], not_gpio
    # Olimex's own net names the GPIO and the LED, so a pad is not found by
    # the traced `chip_index` alone.
    assert {f"GPIO{gpio}", "USER_LED1"} <= set(parts(pad["label"])), pad["label"]
    # Why `LED_BUILTIN` and not `SDA`: this variant's `SDA` is the GPIO the
    # SparkFun Thing Plus ESP32-C6's numbers `SDA` too, and Olimex's net for
    # it reaches the surface-mount UEXT connectors and no pad of EXT1.
    sda = named(own, "SDA")
    assert theirs["SparkFun Thing Plus ESP32-C6"] != gpio
    assert siblings("SDA")["SparkFun Thing Plus ESP32-C6"] == sda
    assert not [one for one in pads["pads"] if one["chip_index"] == sda], sda
    # Nor `TX`, which is on EXT1: it is the XIAO's `TX`.
    (xiao,) = compiler.RECIPES[board_manifest.row(BOARD).chip].bsp_includes
    assert named(own, "TX") == siblings("TX")[xiao]
    assert [one["chip_index"] for one in pads["pads"]
            if "U0TXD" in parts(one["label"])] == [named(own, "TX")]

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
    assert enabled & (1 << gpio)
    for sibling in not_gpio:
        assert not enabled & (1 << sibling), f"GPIO{sibling} was enabled"
        assert not driven & (1 << sibling), f"GPIO{sibling}, a sibling's LED_BUILTIN, moved"
