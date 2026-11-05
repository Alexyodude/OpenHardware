# OpenHardware — the two XIAO nRF52840 boards, run on the Armv7E-M core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this file is for
#
# It is the evidence `webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` names
# for the nRF52840, so it does the headline thing the RP2350's and the
# KB2040's do: a board name and a file of bytes go into `webui/api.py`, the
# image runs on `core/cortexm0` with the Armv7E-M profile selected, and the
# board's own pins move -- watched through the pin view, by the labels the
# page draws them under.
#
# The image is `nrf52840/blink.bin` beside this file, the same bytes
# `tests/cortexm0/test_thumb2_exec.py` holds to Unicorn and icicle-emu
# instruction by instruction. That test says the core executes the image the
# way two independent implementations do; this one says the board around the
# core turns that execution into the three LEDs the vendor wired, in the order
# the source walks them. Neither is enough alone: a core can be right and a
# board map wrong, and the pin view would show a quiet board either way.
#
# ## Why the LEDs and not a header pad
#
# Every other board's evidence blinks a header pad. This one blinks the RGB
# LED, because the nRF52840 is the first board here whose vendor code
# configures an output through `PIN_CNF[n]` rather than `DIRSET`, and the
# board has to make the two views of one DIR bit agree (`map_field`, OH-64).
# An image that only wrote `DIRSET` would pass whether or not that worked. The
# three LEDs are on-board pins with no pad on either board file, so they reach
# the pin view as `group: "on-board"` entries, which is how the page lists a
# pin it can read and has nowhere to draw.
#
# ## What it cannot claim
#
# **Levels, not light.** The pin view reports `low` and `high`. The LEDs are
# active low per Zephyr's `xiao_ble` devicetree, and Seeed's `variant.h`
# says `LED_STATE_ON (1)` against its own `initVariant`, which drives each
# pin high to turn it off -- `webui/boards/nrf52840.py` records the dispute.
# What is asserted here is that one pin at a time is driven low, in the
# source's order, and that is true whichever side of the dispute is right.
#
# Every oracle is software (rules/conformance-fixtures.md section 7): two
# emulators agree on the instruction stream, and the pin numbers are read
# from the vendor's variant and Zephyr's devicetree. Nothing here was
# measured on silicon, and no SDK image runs: CLOCK, POWER, the UICR and the
# rest of the peripheral space fault, as `webui/boards/nrf52840.py` says.

import itertools
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0 import disasm
from webui import api, pinmap
from webui.boards import nrf52840

HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE / "nrf52840" / "blink.bin"
SOURCE = HERE / "nrf52840" / "blink.c"
SCRIPT = HERE / "nrf52840" / "blink.ld"

BOARDS = ("XIAO-nRF52840-DIP", "XIAO-nRF52840-SMD")

#: In the order `blink.c`'s `leds[]` walks them: P0.26, P0.30, P0.06.
ORDER = ("LED_RED", "LED_GREEN", "LED_BLUE")

#: Enough for the setup loop and two whole turns of the three LEDs. A turn is
#: six calls of `wait(40)`, each of which costs some 290 instructions; the
#: number is a budget and not a claim about timing.
BUDGET = 4_000

#: The flags `blink.c` names. `-march=armv7e-m` emits the same bytes from
#: this compiler; `-mcpu` is what the source says, so it is what is checked.
FLAGS = ("-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=soft", "-Os",
         "-ffreestanding", "-nostdlib", "-nostartfiles")


def load(board: str) -> api.BoardSession:
    """A board name and a file of bytes. `base` because a raw `.bin` carries
    no address of its own, and this one is linked at the reset address."""
    return api.load_firmware(board, IMAGE.read_bytes(), base=nrf52840.FLASH)


def watch(session: api.BoardSession, board: str,
          budget: int = BUDGET) -> tuple[list[tuple[int, tuple[str, ...]]], int]:
    """Step, recording each change of the three LEDs' levels as the pin view
    reports them, and failing if any other pin the view can read moves.

    Also counts the steps whose instruction was a wide one, read at the PC
    before the step, so that a run which never left 16-bit Thumb cannot pass
    for an Armv7E-M one.
    """
    seen: list[tuple[int, tuple[str, ...]]] = []
    wide = 0
    for step in range(budget):
        pc = session.cpu.get_regs().r[15]
        halfword = session.cpu.read_word(pc & ~3) >> (16 if pc & 2 else 0) & 0xFFFF
        wide += disasm.is_wide(halfword, disasm.Profile.V7EM)
        session.step()
        view = api.pin_view(session.runtime, session.cpu, board)
        states = {pad["label"]: pad["state"] for pad in view["pads"]}
        moved = {label: state for label, state in states.items()
                 if label not in ORDER and state not in ("input", "unknown")}
        assert not moved, f"step {step}: pins other than the LEDs moved: {moved}"
        leds = tuple(states[label] for label in ORDER)
        if not seen or leds != seen[-1][1]:
            seen.append((step, leds))
    return seen, wide


def lit(seen: list[tuple[int, tuple[str, ...]]]) -> list[str | None]:
    """Each recorded state after setup as the one LED driven low, or None
    when all three are high. Setup ends at the first all-high state, which
    is the end of the source's first loop."""
    start = next(i for i, (_, leds) in enumerate(seen) if leds == ("high",) * 3)
    out: list[str | None] = []
    for _, leds in seen[start:]:
        low = [label for label, state in zip(ORDER, leds) if state == "low"]
        assert len(low) <= 1 and all(s in ("low", "high") for s in leds), leds
        out.append(low[0] if low else None)
    return out


def compiler() -> tuple[pathlib.Path, pathlib.Path] | None:
    """arm-none-eabi gcc and objcopy, on PATH or in PlatformIO's package
    directory, where `tests/cortexm0/test_thumb2_disasm.py` looks too."""
    home = pathlib.Path.home() / ".platformio/packages/toolchain-gccarmnoneeabi/bin"
    gcc = shutil.which("arm-none-eabi-gcc") or home / "arm-none-eabi-gcc.exe"
    objcopy = shutil.which("arm-none-eabi-objcopy") or home / "arm-none-eabi-objcopy.exe"
    if pathlib.Path(gcc).is_file() and pathlib.Path(objcopy).is_file():
        return pathlib.Path(gcc), pathlib.Path(objcopy)
    return None


# --- the headline -----------------------------------------------------------


def test_a_board_name_and_a_compiled_image_light_the_xiaos_three_leds_in_turn():
    """The evidence for the nRF52840.

    Before the image runs, all three LEDs read `input`: PIN_CNF's DIR is
    clear. The setup loop then makes each an output -- reading `low` for the
    one instruction between its PIN_CNF write and its OUTSET, because OUT
    resets to zero -- and drives it high. From there exactly one LED at a
    time is driven low, red then green then blue, with all three high
    between, which is `blink.c`'s second loop seen from the page.

    And the instructions that did it include wide ones. The image's first
    write is a `str.w`; a core that ran it in Armv6-M would have stopped
    there, and the pin view would have read `input` throughout.
    """
    board = BOARDS[0]
    with load(board) as session:
        seen, wide = watch(session, board)
    assert seen[0][1] == ("input",) * 3, seen[:4]
    turns = lit(seen)
    assert turns[:7] == [None, "LED_RED", None, "LED_GREEN", None, "LED_BLUE", None], seen
    assert turns[1::2] == [ORDER[i % 3] for i in range(len(turns[1::2]))], seen
    assert all(t is None for t in turns[0::2]), seen
    assert wide > 0, "no wide instruction executed"


def test_each_led_is_lit_for_as_long_as_it_is_dark():
    """`wait(40)` on each side of the toggle, so the low and high spans after
    the first are one length. A wandering span means a loop's branch or its
    count is wrong; the AVR's inverted branch was found that way."""
    with load(BOARDS[0]) as session:
        seen, _ = watch(session, BOARDS[0])
    start = next(i for i, (_, leds) in enumerate(seen) if leds == ("high",) * 3)
    steps = [step for step, _ in seen[start + 1:]]
    spans = {b - a for a, b in itertools.pairwise(steps)}
    assert len(spans) <= 2 and max(spans) - min(spans) <= 8, (
        f"spans vary: {sorted(spans)} over {seen}")
    assert min(spans) > 100


def test_the_smd_board_runs_the_same_image_on_the_same_three_leds():
    """`FIRMWARE_VERIFIED` is keyed by chip because the DIP and the SMD build
    one image from one variant (rules/board-claims.md section 1). That is a
    claim about both files, so the SMD's own view is asked too."""
    board = BOARDS[1]
    with load(board) as session:
        seen, wide = watch(session, board)
    assert lit(seen)[:7] == [None, "LED_RED", None, "LED_GREEN", None, "LED_BLUE", None]
    assert wide > 0


def test_the_leds_are_on_board_pins_named_by_their_gpio():
    """No pad on either board file is an LED, so the view lists them after the
    placed pads with no coordinates, and captions each with the port and pin
    the vendor's variant gives it."""
    want = {"LED_RED": "P0.26", "LED_GREEN": "P0.30", "LED_BLUE": "P0.06"}
    for board in BOARDS:
        labels = {pad.label for pad in pinmap.load(board).pads}
        assert not labels & set(ORDER), f"{board}: an LED is a pad: {labels & set(ORDER)}"
        with load(board) as session:
            view = api.pin_view(session.runtime, session.cpu, board)
        leds = {pad["label"]: pad for pad in view["pads"] if pad["label"] in ORDER}
        assert set(leds) == set(ORDER), board
        for label, pad in leds.items():
            assert (pad["group"], pad["x"], pad["y"]) == ("on-board", None, None), pad
            assert pad["chip_pin"] == want[label], (board, pad)
            assert pad["modelled"] and pad["state"] == "input", (board, pad)


# --- PIN_CNF and DIR are one bit --------------------------------------------


def test_a_pin_cnf_write_sets_dir_and_a_dirclr_write_clears_pin_cnf():
    """nRF52840 PS v1.7 section 6.9.2: DIR "is the same as" PIN_CNF[n].DIR.
    Each address sees what the other wrote, and the rest of PIN_CNF -- its
    INPUT, PULL, DRIVE and SENSE fields -- is the register's own."""
    pin = nrf52840.LEDS["LED_RED"]
    base, bit = nrf52840.port_of(pin)
    cnf = base + nrf52840.GPIO_PIN_CNF + 4 * bit
    with load(BOARDS[0]) as session:
        cpu = session.cpu
        cpu.write_word(cnf, 0x0003_0703)
        assert cpu.read_word(base + nrf52840.GPIO_DIR) == 1 << bit
        cpu.write_word(base + nrf52840.GPIO_DIRCLR, 1 << bit)
        assert cpu.read_word(cnf) == 0x0003_0702, "DIRCLR did not reach PIN_CNF"
        cpu.write_word(base + nrf52840.GPIO_DIRSET, 1 << bit)
        assert cpu.read_word(cnf) == 0x0003_0703, "DIRSET did not reach PIN_CNF"
        assert cpu.read_word(base + nrf52840.GPIO_DIR) == 1 << bit, "no other pin moves"


def test_a_write_to_pin_cnfs_upper_half_leaves_dir_alone():
    """DIR is bit 0, so a store that does not reach byte 0 cannot change it.
    A first draft copied bit 0 of whatever value arrived, which a halfword
    store to the DRIVE and SENSE half would have turned into a DIR write."""
    pin = nrf52840.LEDS["LED_GREEN"]
    base, bit = nrf52840.port_of(pin)
    cnf = base + nrf52840.GPIO_PIN_CNF + 4 * bit
    with load(BOARDS[0]) as session:
        cpu = session.cpu
        cpu.write_word(cnf, 1)
        cpu.write_halfword(cnf + 2, 0x0003)
        assert cpu.read_word(base + nrf52840.GPIO_DIR) == 1 << bit
        assert cpu.read_word(cnf) == 0x0003_0001
        cpu.write_word(base + nrf52840.GPIO_DIRCLR, 1 << bit)
        cpu.write_halfword(cnf + 2, 0x0001)
        assert cpu.read_word(base + nrf52840.GPIO_DIR) == 0


def test_port_1_has_sixteen_pins_and_a_seventeenth_is_refused():
    """P1 stops at P1.15 (PS v1.7 section 6.9), and D6..D10 live on it. A pin
    number past either port is a typo in a table, and is refused by name
    rather than wrapped onto another port."""
    assert nrf52840.port_of(32 + 15) == (nrf52840.P1, 15)
    assert {nrf52840.port_of(nrf52840.HEADER[f"D{n}"])[0] for n in range(6, 11)} == {nrf52840.P1}
    with pytest.raises(ValueError):
        nrf52840.port_of(32 + 16)


# --- the image --------------------------------------------------------------


def test_the_committed_blink_matches_its_source():
    """Skipped where no toolchain exists rather than failing, the contract the
    other compiled fixtures keep."""
    tools = compiler()
    if tools is None:
        pytest.skip("no arm-none-eabi toolchain on PATH or in ~/.platformio")
    gcc, objcopy = tools
    with tempfile.TemporaryDirectory() as work:
        elf, rebuilt = pathlib.Path(work) / "blink.elf", pathlib.Path(work) / "blink.bin"
        subprocess.run([str(gcc), *FLAGS, "-T", str(SCRIPT), "-o", str(elf), str(SOURCE)],
                       check=True, capture_output=True)
        subprocess.run([str(objcopy), "-O", "binary", str(elf), str(rebuilt)],
                       check=True, capture_output=True)
        assert rebuilt.read_bytes() == IMAGE.read_bytes()


def test_the_image_drives_the_pins_the_board_module_names():
    """`blink.c` types its three pins, because a C file cannot import a Python
    table. So this reads them back out of the source and holds them to
    `nrf52840.LEDS`, in the order the source walks them."""
    text = SOURCE.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "leds[3]" in line)
    pins = [int(n.rstrip("u")) for n in line.split("{")[1].split("}")[0].split(",")]
    assert pins == [nrf52840.LEDS[label] for label in ORDER]
