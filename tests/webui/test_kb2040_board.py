# OpenHardware — the Adafruit KB2040 runs an image built against its own variant.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The evidence `BOARD_FIRMWARE_VERIFIED` names for the Adafruit KB2040
(rules/board-claims.md §11, OH-196).

The RP2040 has no compile recipe here, and an Arduino/pico-sdk image stops
at the boot ROM (`tests/cortexm0/test_blink.py`), so this board's image is
the chip's bare-metal blink with its pin taken from this board's own
variant: `rp2040_rows/blink.c`, built by arm-none-eabi-gcc with the chip
blink's flags and linker script and `-I` on arduino-pico's
`variants/adafruit_kb2040`, toggling what that variant calls `MOSI`.
`rp2040_rows/kb2040_blink.bin` is that build, rebuilt here byte for byte
where the toolchain is installed.

Loaded onto this board by name and stepped on the Cortex-M0+ core, it moves
the pad whose `chip_index` is the GPIO OH-181's reader gives for this
board's `MOSI`, read through the pin view, and never the `MOSI` of any other
RP2040 row in `tools/board_manifest.py` or of the XIAO RP2040's variant
(`sibling_variants`): the same source built against any of those moves
another pad.
"""

import functools
import itertools
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from tools import board_manifest, board_sources, eagle, import_pindefs
from webui import api, pinmap
from webui.boards import rp2040

BOARD = "Adafruit KB2040"
#: The name this board's image toggles, as its variant spells it.
LABEL = "MOSI"
HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / "rp2040_rows" / "blink.c"
IMAGE = HERE / "rp2040_rows" / "kb2040_blink.bin"
#: The chip blink's own linker script: the RP2040's flash, past boot2.
LINKER = HERE.parent / "cortexm0" / "blink" / "blink.ld"
PICO = import_pindefs.BSP_DIR / "arduino-pico"

#: Where `blink.ld` links the vector table: past boot2's 256 bytes.
LOAD = rp2040.FLASH + rp2040.BOOT2_BYTES
OUT = rp2040.SIO + rp2040.SIO_GPIO_OUT
OE = rp2040.SIO + rp2040.SIO_GPIO_OE

#: Several toggles at the chip blink's measured 453-instruction period.
BUDGET = 3_000


@functools.cache
def numbered(variant: str, labels: tuple[str, ...]) -> dict[str, int]:
    """Every `D<n>` arduino-pico's `variant` numbers, and each of `labels`,
    read as OH-181's reader reads a row: through the preprocessor, with the
    flags that variant's board is compiled with. Skips, naming the fetch or
    the install, where the checkout or the preprocessor is missing."""
    table = PICO / "variants" / variant / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")
    try:
        pins, _ = import_pindefs.read_pico_pins(
            (table.read_text(encoding="utf-8", errors="replace"),),
            checkout=PICO, variant=variant, extras=labels)
    except import_pindefs.PindefError as exc:
        if "only the preprocessor can say" not in str(exc):
            raise
        pytest.skip(f"SKIPPED: {exc}")
    return {label: pin.index for label, pin in pins.items()}


def sibling_variants() -> dict[str, str]:
    """Every other row on this board's chip, to its own variant, and the
    chip's XIAO boards, to the arduino-pico variant `tools/import_pindefs.py`
    registers for them: the tables this source could be built against
    instead of this board's."""
    row = board_manifest.row(BOARD)
    found = {}
    for other in board_manifest.ROWS:
        if other.chip == row.chip and other.board != BOARD:
            assert other.package == "arduino-pico", (other.board, other.package)
            found[other.board] = other.variant
    for name, board in import_pindefs.BOARDS.items():
        if board.chip != row.chip or board_manifest.find(name) is not None:
            continue
        (path,) = [path for source in board.sources if source.package == "arduino-pico"
                   for path in source.paths]
        found[name] = pathlib.PurePosixPath(path).parent.name
    assert any(board_manifest.find(name) for name in found), found
    assert any(not board_manifest.find(name) for name in found), found
    return found


def build(variant: str) -> bytes:
    """`blink.c` toggling `LABEL`, built against arduino-pico's `variant` by
    the toolchain `tests/cortexm0/test_blink.py` builds the chip blink with,
    and with its flags. Skips where there is none."""
    numbered(variant, ())  # skips, naming the fetch, where the table is missing
    found = shutil.which("arm-none-eabi-gcc")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        pathlib.Path.home(),
        ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe",
    )
    if not gcc.is_file():
        pytest.skip(f"SKIPPED: no arm-none-eabi-gcc on PATH or at {gcc}")
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    with tempfile.TemporaryDirectory() as tmp:
        elf, binary = pathlib.Path(tmp) / "blink.elf", pathlib.Path(tmp) / "blink.bin"
        for command in (
            [str(gcc), "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-ffreestanding",
             "-nostdlib", "-I", str(PICO / "variants" / variant), f"-DWATCHED={LABEL}",
             "-T", str(LINKER), "-o", str(elf), str(SOURCE)],
            [str(objcopy), "-O", "binary", str(elf), str(binary)],
        ):
            done = subprocess.run(command, capture_output=True, text=True, check=False)
            assert done.returncode == 0, (command, done.stderr)
        return binary.read_bytes()


def pads() -> list[dict]:
    return json.loads((pinmap.BOARDS_DIR / f"{BOARD}.json").read_text(encoding="utf-8"))["pads"]


@functools.cache
def schematic_gpios() -> dict[str, set[int]]:
    """Net -> the GPIOs Adafruit's own schematic names the RP2040's pins on
    it. The pad's net is `MOSI`, the function and not the GPIO, so this is
    where the vendor's own words carry the number (rules/board-claims.md
    §10, §11). Skips, naming the fetch, where the schematic is not here."""
    row = board_manifest.row(BOARD)
    root = board_sources.source(row.source).dest(board_manifest.REPO)
    if not (root / row.schematic).is_file():
        pytest.skip(f"SKIPPED: no {root / row.schematic}; "
                    f"python tools/get_board_sources.py {row.source}")
    (chip,) = [element.name for element in eagle.read_board(board_manifest.cad_path(row)).elements
               if (element.package, element.value) == (row.pin_table.package, row.pin_table.value)]
    return {net.name: {int(found.group(1)) for ref in net.pins if ref.part == chip
                       for part in ref.pin.split("/")
                       if (found := re.fullmatch(r"GPIO(\d+)", part))}
            for net in eagle.read_schematic(root / row.schematic).nets}


def run(image: bytes) -> tuple[list[tuple[int, dict[str, str]]], int, int]:
    """Load `image` onto this board by name, step it, and read every pad's
    level through the pin view whenever SIO's output or output enable
    changes. Returns those readings, every GPIO ever driven high, and the
    output enable at the end."""
    readings, driven = [], 0
    with api.load_firmware(BOARD, image, base=LOAD) as session:
        last = None
        for step in range(BUDGET):
            session.step()
            words = (session.cpu.read_word(OE), session.cpu.read_word(OUT))
            driven |= words[1]
            if words != last:
                readings.append((step, api.pin_levels(session.runtime, session.cpu)))
                last = words
        enabled = session.cpu.read_word(OE)
    return readings, driven, enabled


def test_the_image_is_blink_c_built_against_this_boards_own_variant():
    built = build(board_manifest.row(BOARD).variant)
    assert built == IMAGE.read_bytes(), (
        f"{IMAGE.name} is not {SOURCE.name} built for {BOARD}; rebuild it with "
        f"this file's `build`")


def test_the_image_blinks_the_gpio_this_boards_mosi_names_on_its_own_pad():
    """The pad is the one whose `chip_index` is the GPIO this board's own
    variant calls `MOSI`; Adafruit's net there is `MOSI` too, and its
    schematic names the RP2040's pin on that net for the same GPIO. No
    sibling's `MOSI` is enabled or driven, and the pads whose `chip_index`
    is one read `input` throughout."""
    pytest.importorskip("core.cortexm0.abi")
    own = numbered(board_manifest.row(BOARD).variant, (LABEL, "LED"))
    theirs = {name: numbered(variant, (LABEL,))
              for name, variant in sibling_variants().items()}
    gpio = own[LABEL]
    not_gpio = {table[LABEL] for table in theirs.values()}
    assert gpio not in not_gpio, (gpio, theirs)
    board_pads = pads()
    (pad,) = [pad for pad in board_pads if pad["chip_index"] == gpio]
    assert LABEL in pad["label"].split("/"), pad["label"]
    others = [pad for pad in board_pads if pad["chip_index"] in not_gpio]
    assert others, f"no sibling's {LABEL} {sorted(not_gpio)} is a pad here to read"
    for each in (pad, *others):
        assert schematic_gpios()[each["label"]] == {each["chip_index"]}, each
    # Why not its LED: its variant numbers one no pad here reaches. Why not a
    # `D<n>`: another row's variant numbers every one of them the same, so a
    # `D<n>` blink would be that row's image too. If either stops being so,
    # that pin is the one to watch.
    assert own["LED"] not in {pad["chip_index"] for pad in board_pads}, own["LED"]
    rows = [table for name, table in theirs.items() if board_manifest.find(name)]
    assert all(any(table.get(label) == number for table in rows)
               for label, number in own.items() if re.fullmatch(r"D\d+", label)), own

    readings, driven, enabled = run(IMAGE.read_bytes())

    levels = [level for level, _ in itertools.groupby(
        levels[pad["label"]] for _, levels in readings)]
    assert levels[:3] == ["input", "low", "high"], levels
    assert set(levels[1:]) == {"low", "high"}, levels
    assert len(levels) >= 7, f"{pad['label']} changed {len(levels) - 1} times: {levels}"
    rises = [step for (_, before), (step, now) in itertools.pairwise(readings)
             if now[pad["label"]] == "high" != before[pad["label"]]]
    assert len({b - a for a, b in itertools.pairwise(rises)}) == 1, f"the period varies: {rises}"
    assert enabled & (1 << gpio)
    for sibling in not_gpio:
        assert not enabled & (1 << sibling), f"GPIO{sibling} was enabled"
        assert not driven & (1 << sibling), f"GPIO{sibling}, a sibling's {LABEL}, moved"
    still = {levels[other["label"]] for _, levels in readings for other in others}
    assert still == {"input"}, ([other["label"] for other in others], still)


def test_the_same_source_built_for_a_sibling_moves_that_boards_pin_and_not_this_one():
    """What the test above refuses: `blink.c` built against every sibling's
    variant, loaded onto this board, leaves this board's `MOSI` pad `input`
    throughout and moves the pad at that variant's `MOSI` instead."""
    pytest.importorskip("core.cortexm0.abi")
    gpio = numbered(board_manifest.row(BOARD).variant, (LABEL,))[LABEL]
    board_pads = pads()
    (pad,) = [pad for pad in board_pads if pad["chip_index"] == gpio]
    for variant in sorted(set(sibling_variants().values())):
        image = build(variant)
        assert image != IMAGE.read_bytes(), variant
        (theirs,) = [other for other in board_pads
                     if other["chip_index"] == numbered(variant, (LABEL,))[LABEL]]
        readings, _, _ = run(image)
        assert {levels[pad["label"]] for _, levels in readings} == {"input"}, variant
        assert "high" in {levels[theirs["label"]] for _, levels in readings}, (
            variant, theirs["label"])
