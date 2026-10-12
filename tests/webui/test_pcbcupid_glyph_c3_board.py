# OpenHardware — the PCBCUPID Glyph C3 runs a sketch built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the PCBCUPID Glyph C3
(rules/board-claims.md §7 and §13, OH-194), made as the Pro Micro
ESP32-C3's is (`tests/webui/test_sparkfun_pro_micro_esp32c3_board.py`), on
another pin.

The pin watched is `LED_BUILTIN`, the one its variant numbers on a pad whose
own net carries the GPIO (`/GPIO_1`) and that no other table on the
ESP32-C3 numbers alike: the other rows in `tools/board_manifest.py` and the
XIAO's table either number it another GPIO or number no pin at all, each
read from its own variant (`siblings`). A sketch compiled for this board by
name against its own variant, `pcbcupid_glyph_c3/glyph_c3_blink.bin` --
rebuilt here byte for byte where the toolchain is installed -- loaded onto
the described ESP32-C3 and stepped, moves the pads whose `chip_index` is
its own `LED_BUILTIN`, and never a sibling's.
"""

import itertools
import json
import pathlib

import pytest

from tests.webui.esp32_timing import POLL, steps_per_millisecond
from tools import board_manifest, import_pindefs
from webui import api, pinmap
from webui import compile as compiler
from webui.boards import esp32c3

BOARD = "PCBCUPID Glyph C3"
HERE = pathlib.Path(__file__).resolve().parent
SKETCH = HERE / "pcbcupid_glyph_c3" / "glyph_c3_blink.ino"
IMAGE = HERE / "pcbcupid_glyph_c3" / "glyph_c3_blink.bin"

GPIO_OUT = esp32c3.GPIO + esp32c3.GPIO_OUT
GPIO_ENABLE = esp32c3.GPIO + esp32c3.GPIO_ENABLE

#: A millisecond in steps, read from the description by
#: `esp32_timing.steps_per_millisecond` and not written here.
#: delay() waits on SYSTIMER since OH-161
#: (`webui/arduino/cores/openhardware/wiring.c`), so each move of a delay(1)
#: blink comes a millisecond, and the write and the poll around it, after
#: the one before -- held to within `POLL`, as test_compile's delay tests
#: hold each delay(n).
MILLISECOND = steps_per_millisecond(esp32c3)

#: Five moves of this image, measured 2026-10-12, after OH-161's step 3
#: gave `pinMode` its pad writes: the fifth lands at step 640,247, so
#: 650,000 watches four gaps -- 160,043, 160,061, 160,043 and 160,049
#: steps -- with about 9,750 to spare. Those are the three lengths the gaps
#: take over fifty moves of the QT Py's and the SparkFun Thing Plus C6's
#: images, whose first six moves are this image's. That this board sees
#: each is a fact about today's wiring.c and not what the budget is for:
#: `POLL` holds each gap to the millisecond whatever its length, so whether
#: the longest is within it is asked once per clock and not once per board
#: -- tests/webui/test_qtpy_esp32c3_board.py watches ten moves.
BUDGET = 650_000


def needs_table() -> None:
    """Skip, naming the fetch, before anything asks for this board's recipe
    or reads its table."""
    row = board_manifest.row(BOARD)
    table = (compiler.BOARD_SUPPORT / row.package / "variants" / row.variant
             / "pins_arduino.h")
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")


def named(root: pathlib.Path, include: str, label: str) -> int | None:
    """The GPIO the `pins_arduino.h` under `root / include` numbers `label`,
    or None where it numbers none: no definition, or one that is not an
    integer, as the QT Py's `SOC_GPIO_PIN_COUNT + PIN_NEOPIXEL` is.

    Two roots, because the XIAO ESP32-C3's table comes from PlatformIO's
    framework (`extra_includes`) and the rows' from the board-support
    checkout (`bsp_includes`)."""
    table = root / include / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}")
    text = table.read_text(encoding="utf-8", errors="replace")
    return import_pindefs.read_c_pin_constants(text).get(label)


def siblings(label: str) -> dict[str, int | None]:
    """`label` in every other row on this board's chip, each from its own
    variant, and in the chip's XIAO table: what a build against another
    table would drive instead, or None where it could drive nothing."""
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
    assert include == "arduino-esp32/variants/Pcbcupid_GLYPH_C3"
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
    (xiao,) = compiler.RECIPES[row.chip].extra_includes
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


def test_the_image_blinks_the_gpio_this_boards_led_builtin_names_on_its_own_pads():
    """The pads are the ones whose `chip_index` is the GPIO this board's own
    variant calls `LED_BUILTIN`, which the board file traced to the module,
    and whose net PCBCUPID names for that GPIO. No sibling's `LED_BUILTIN`
    is enabled or driven, and the pads whose `chip_index` is one read
    `input` throughout."""
    pytest.importorskip("core.riscv32.abi")
    needs_table()
    recipe = compiler.recipe_for(BOARD)
    (own,) = recipe.bsp_includes
    gpio = named(compiler.BOARD_SUPPORT, own, "LED_BUILTIN")
    assert gpio is not None
    theirs = siblings("LED_BUILTIN")
    assert gpio not in theirs.values(), (gpio, theirs)
    not_gpio = {sibling for sibling in theirs.values() if sibling is not None}
    pads = json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))
    mine = [pad for pad in pads["pads"] if pad["chip_index"] == gpio]
    others = [pad for pad in pads["pads"] if pad["chip_index"] in not_gpio]
    assert mine, f"no pad here is GPIO{gpio}"
    assert others, f"no sibling's LED_BUILTIN {sorted(not_gpio)} is a pad here to read"
    # PCBCUPID's own net names the GPIO too, so a pad is not found by the
    # traced `chip_index` alone. Both of its headers carry this one.
    (label,) = {pad["label"] for pad in mine}
    assert f"GPIO_{gpio}" in label.split("/"), label
    # Why not `SDA`, as on the QT Py: PCBCUPID's net for it carries no GPIO,
    # so its pad would be found by the trace alone.
    sda = {pad["label"] for pad in pads["pads"]
           if pad["chip_index"] == named(compiler.BOARD_SUPPORT, own, "SDA")}
    assert sda == {"/SDA"}, sda

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
                levels.append(read[label])
                still |= {read[other["label"]] for other in others}
                moves.append(step)
                last = now
        enabled = session.cpu.read_word(GPIO_ENABLE)

    assert len(levels) >= 5, f"{label} changed {len(levels)} times"
    assert all(a != b for a, b in itertools.pairwise(levels)), levels
    assert levels[0] == "high", levels
    gaps = [b - a for a, b in itertools.pairwise(moves)]
    assert all(abs(gap - MILLISECOND) < POLL for gap in gaps), (
        f"a delay(1) is {MILLISECOND} steps here, and {label} moved {gaps} apart")
    assert enabled & (1 << gpio)
    for sibling in not_gpio:
        assert not enabled & (1 << sibling), f"GPIO{sibling} was enabled"
        assert not driven & (1 << sibling), f"GPIO{sibling}, a sibling's LED_BUILTIN, moved"
    assert still == {"input"}, ([other["label"] for other in others], still)
