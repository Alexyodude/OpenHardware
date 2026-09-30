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
`variants/adafruit_kb2040`, selecting SIO on the pin that variant numbers
`MISO` and toggling it. `rp2040_rows/kb2040_blink.bin` is that build,
rebuilt here byte for byte where the toolchain is installed.

Loaded onto this board by name and stepped on the Cortex-M0+ core, it moves
the pad whose `chip_index` is the GPIO OH-181's reader gives for this
board's `MISO`, read through the pin view, and never the `MISO` of any other
RP2040 row in `tools/board_manifest.py`, of the XIAO RP2040s' variant, or of
arduino-pico's own default table (`sibling_variants`): the same source built
against any of those drives another pin.

Every test here reads a GPIO through the preprocessor, so where no
arm-none-eabi-g++ is installed, as on CI, every one of them skips.
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
LABEL = "MISO"
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
def reading(variant: str, labels: tuple[str, ...]) -> tuple[dict[str, int], tuple[str, ...]]:
    """Every `D<n>` arduino-pico's `variant` numbers, and each of `labels`,
    read as OH-181's reader reads a row: through the preprocessor, with the
    flags that variant's board is compiled with; and the checkout's files it
    read them from. Skips, naming the fetch or the install, where the
    checkout or the preprocessor is missing: by hand the reader refuses a
    header that `#include`s, as this board's does."""
    table = PICO / "variants" / variant / "pins_arduino.h"
    if not table.is_file():
        pytest.skip(f"SKIPPED: no {table}; python tools/import_pindefs.py --fetch")
    try:
        pins, files = import_pindefs.read_pico_pins(
            (table.read_text(encoding="utf-8", errors="replace"),),
            checkout=PICO, variant=variant, extras=labels)
    except import_pindefs.PindefError as exc:
        if "only the preprocessor can say" not in str(exc):
            raise
        pytest.skip(f"SKIPPED: {exc}")
    return {label: pin.index for label, pin in pins.items()}, files


def numbered(variant: str, labels: tuple[str, ...]) -> dict[str, int]:
    return reading(variant, labels)[0]


def sibling_variants() -> dict[str, str]:
    """Every other row on this board's chip, to its own variant; the chip's
    XIAO boards, to the arduino-pico variant `tools/import_pindefs.py`
    registers for them; and arduino-pico's own default table, the variant
    whose `common.h` this board's variant includes, as the reader says it
    read it. The tables this source could be built against instead of this
    board's, and the one a pin keeps where a variant sets nothing."""
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
    _, files = reading(row.variant, ())
    (default,) = {pathlib.PurePosixPath(path).parent.name for path in files} - {row.variant}
    found[f"arduino-pico {default}"] = default
    assert any(board_manifest.find(name) for name in found), found
    assert any(name in import_pindefs.BOARDS and not board_manifest.find(name)
               for name in found), found
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
        # Named with no image suffix: tools/check_board_claims.py reads one as
        # this test naming its image.
        elf, binary = pathlib.Path(tmp) / "linked", pathlib.Path(tmp) / "flat"
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


def test_the_image_blinks_the_gpio_this_boards_miso_names_on_its_own_pad():
    """The pad is the one whose `chip_index` is the GPIO this board's own
    variant calls `MISO`, and Adafruit's net there is `MISO` too. No
    sibling's `MISO` is enabled or driven, and the pads whose `chip_index`
    is one read `input` throughout."""
    pytest.importorskip("core.cortexm0.abi")
    own = numbered(board_manifest.row(BOARD).variant, (LABEL, "MOSI", "LED"))
    theirs = {name: numbered(variant, (LABEL, "MOSI"))
              for name, variant in sibling_variants().items()}
    gpio = own[LABEL]
    not_gpio = {table[LABEL] for table in theirs.values()}
    assert gpio not in not_gpio, (gpio, theirs)
    board_pads = pads()
    (pad,) = [pad for pad in board_pads if pad["chip_index"] == gpio]
    assert LABEL in pad["label"].split("/"), pad["label"]
    others = [pad for pad in board_pads if pad["chip_index"] in not_gpio]
    assert others, f"no sibling's {LABEL} {sorted(not_gpio)} is a pad here to read"
    # Why not its LED: its variant numbers one no pad here reaches. Why not
    # `MOSI`: arduino-pico's default table numbers it the same, so a table
    # that set nothing would pass. Why not a `D<n>`: another row's variant
    # numbers every one of them the same. If any stops being so, that pin
    # is one to watch.
    assert own["LED"] not in {pad["chip_index"] for pad in board_pads}, own["LED"]
    defaults = [table for name, table in theirs.items()
                if not board_manifest.find(name) and name not in import_pindefs.BOARDS]
    assert own["MOSI"] in {table["MOSI"] for table in defaults}, (own, defaults)
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


def test_adafruits_schematic_names_the_gpio_on_the_watched_pad_and_its_siblings_pads():
    """Adafruit names these nets for the function -- `MISO`, `D4` -- and not
    the GPIO, so the vendor's own statement of the pin is its schematic's
    name for the RP2040's pin on each net (rules/board-claims.md §10, §11).
    Apart from the run, so a schematic not fetched skips only this."""
    row = board_manifest.row(BOARD)
    root = board_sources.source(row.source).dest(board_manifest.REPO)
    if not (root / row.schematic).is_file():
        pytest.skip(f"SKIPPED: no {root / row.schematic}; "
                    f"python tools/get_board_sources.py {row.source}")
    gpio = numbered(row.variant, (LABEL,))[LABEL]
    not_gpio = {numbered(variant, (LABEL,))[LABEL] for variant in sibling_variants().values()}
    (chip,) = [element.name for element in eagle.read_board(board_manifest.cad_path(row)).elements
               if (element.package, element.value) == (row.pin_table.package, row.pin_table.value)]
    named = {net.name: {int(found.group(1)) for ref in net.pins if ref.part == chip
                        for part in ref.pin.split("/")
                        if (found := re.fullmatch(r"GPIO(\d+)", part))}
             for net in eagle.read_schematic(root / row.schematic).nets}
    checked = [pad for pad in pads() if pad["chip_index"] in {gpio, *not_gpio}]
    assert [pad["chip_index"] for pad in checked].count(gpio) == 1, checked
    for pad in checked:
        assert named[pad["label"]] == {pad["chip_index"]}, (pad, named.get(pad["label"]))


def test_the_same_source_built_for_a_sibling_drives_that_boards_pin_and_not_this_one():
    """What the image test refuses: `blink.c` built against every sibling's
    variant, loaded onto this board, leaves this board's `MISO` pad `input`
    throughout and drives that variant's `MISO` instead, moving its pad
    where this board has one."""
    pytest.importorskip("core.cortexm0.abi")
    gpio = numbered(board_manifest.row(BOARD).variant, (LABEL,))[LABEL]
    board_pads = pads()
    (pad,) = [pad for pad in board_pads if pad["chip_index"] == gpio]
    for variant in sorted(set(sibling_variants().values())):
        image = build(variant)
        assert image != IMAGE.read_bytes(), variant
        theirs = numbered(variant, (LABEL,))[LABEL]
        readings, driven, _ = run(image)
        assert {levels[pad["label"]] for _, levels in readings} == {"input"}, variant
        assert driven & (1 << theirs), (variant, theirs)
        for other in [other for other in board_pads if other["chip_index"] == theirs]:
            assert "high" in {levels[other["label"]] for _, levels in readings}, (
                variant, other["label"])
