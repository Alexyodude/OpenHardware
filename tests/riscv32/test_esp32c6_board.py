# OpenHardware — an ESP32-C6 board, and what makes it not an ESP32-C3.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this file is for, given that test_esp32c3_board.py exists
#
# It is the evidence `webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` names
# for ESP32-C6, so it has to do the same headline thing: a board name and a
# file of bytes go into `webui/api.py`, and a GPIO register moves. That part is
# deliberately the C3's test with different constants, because it is the same
# claim about a different chip.
#
# **Everything after the headline is different on purpose.** Re-asserting that
# an RV32 board reports 33 registers and no flags would be testing
# `core/riscv32/machine.py` a second time under a new name -- the C3's file
# already pins that, and a copy of it here would pass on the day the C6 board
# was wrong. So the rest of this file asserts the three things that are true of
# a C6 and false of a C3:
#
#   * it has atomics, and this core answers `Unimplemented` rather than
#     `Illegal` -- two different words for two different facts
#   * SRAM has one address rather than two, so this board's memory map is
#     complete where the C3's is knowingly partial
#   * the instruction and data busses share one flash window, so there is no
#     separate rodata region
#
# plus the check that licensed the header tree these numbers come from at all.
#
# ## What it cannot claim
#
# **An ESP-IDF application will not run on this board.** An ESP32-C6 resets
# into Espressif mask ROM that sets up the cache, the clock and its own
# function table before `app_main`; that ROM is not redistributable and is not
# modelled. What runs is a bare-metal image, which is the standard the RP2040,
# SAMD21, ATmega328P and ESP32-C3 fixtures already meet.
#
# **This core executes no atomic.** The C6 board declares `A` so the core can
# tell "this part does not have it" from "this emulator has not written it",
# and the second is what it says. A blink contains none, which is why the
# headline passes; `test_the_image_this_runs_contains_no_atomic` is what keeps
# that an assertion rather than a coincidence.

import itertools
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from webui import api
from webui.boards import esp32c3, esp32c6

HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE / "c6blink" / "blink.bin"
SOURCE = HERE / "c6blink" / "blink.c"
SCRIPT = HERE / "c6blink" / "blink.ld"

#: One of the two XIAO ESP32-C6 boards in the catalogue. They differ in
#: footprint and not in silicon, so the description serves both.
BOARD = "XIAO-ESP32-C6-DIP"

LED = 1 << esp32c6.LED_PIN
GPIO_OUT = esp32c6.GPIO + esp32c6.GPIO_OUT
GPIO_ENABLE = esp32c6.GPIO + esp32c6.GPIO_ENABLE

#: Several toggles at the measured 606-instruction period.
BUDGET = 20_000

#: `amoor.w a0, a1, (a2)` — funct5 01000, aq 0, rl 0, rs2 a1, rs1 a2,
#: funct3 010, rd a0, opcode 0101111. Written out rather than assembled
#: because the riscv32-esp-elf GCC installed here is 8.4.0 and predates the
#: `_zicsr_zifencei` spelling its own toolchain file now uses, so driving `as`
#: from a test would couple this to a compiler version for no gain.
AMOOR_W = 0x40B6252F


def needs_core() -> None:
    pytest.importorskip("core.riscv32.abi")
    if not IMAGE.is_file():
        pytest.skip(f"{IMAGE} is missing")


def load() -> api.BoardSession:
    """A board name and a file of bytes. `base` because a raw `.bin` carries no
    address of its own, and this one is linked into the flash execute window."""
    return api.load_firmware(BOARD, IMAGE.read_bytes(), base=esp32c6.IROM)


def watch(session: api.BoardSession, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which GPIO8 changes state."""
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        session.step()
        now = session.cpu.read_word(GPIO_OUT) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


def idf_root() -> pathlib.Path | None:
    """The ESP-IDF checkout these numbers were read from, or None.

    Resolved rather than hard-coded, in the order `webui/picsimlab.py` resolves
    its own reference tree and for the same reason: an environment variable so
    a machine can put it anywhere, then the sibling name
    `docs/esp-idf-reference.md` tells people to clone.

    Returns None rather than raising. A checker that cannot find its source
    **skips and says so**; it never passes quietly. That is this repository's
    standing contract for reference trees, and the only test that wants this
    one says `pytest.skip` when it gets None.
    """
    named = os.environ.get("ESP_IDF_ROOT")
    candidates = [pathlib.Path(named)] if named else []
    candidates += [
        HERE.parents[1].parent / "esp-idf-reference",
        HERE.parents[1].parent / "esp-idf",
    ]
    for path in candidates:
        if (path / "components" / "soc" / "esp32c6").is_dir():
            return path
    return None


def defines(header: pathlib.Path) -> dict[str, str]:
    """Every `#define NAME VALUE` in `header`, as text.

    Text rather than evaluated integers, because half of what these headers
    define is written in terms of the other half -- `SOC_DROM_LOW  SOC_IROM_LOW`
    is the fact one test below is *about*, and evaluating it would erase it.
    """
    out: dict[str, str] = {}
    for line in header.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "#define":
            out[parts[1]] = parts[2].split("/*")[0].split("//")[0].strip()
    return out


# --- the headline -----------------------------------------------------------


def test_a_board_name_and_a_compiled_image_drive_a_gpio_register():
    """The evidence for ESP32-C6, and two more of the seven-board unlock.

    Two transitions is a blink. One is a bit that came on and stayed on, which
    is what a broken toggle looks like from the outside.
    """
    needs_core()
    with load() as session:
        transitions = watch(session)
    assert len(transitions) >= 2, f"the bit changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_pin_is_configured_as_an_output_and_the_period_is_steady():
    """A toggle on a pin still configured as an input is a lie the output
    register alone cannot catch, and a wandering period means the delay loop is
    wrong. The period is what caught the AVR's inverted branch."""
    needs_core()
    with load() as session:
        steps = [step for step, _ in watch(session)]
        assert session.cpu.read_word(GPIO_ENABLE) & LED, "GPIO8 is an output"
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"
    assert periods.pop() > 100, "a loop counting to 100 costs more than 100 steps"


# --- the letter that makes this a different part ----------------------------


def test_the_same_encoding_is_illegal_on_a_c3_and_unimplemented_here():
    """The single strongest reason this board is not `esp32c3.py` with new
    numbers, and the reason `install` sets the ISA before it maps anything.

    An ESP32-C3 is RV32IMC and **must trap** `amoor.w`: the silicon does not
    have the A extension, so refusing it is the part behaving correctly. An
    ESP32-C6 is RV32IMAC and **must execute** it. This core implements no
    atomic on either, so the two answers it can give are:

        Illegal        the part does not have this instruction
        Unimplemented  the part has it and this emulator has not written it

    The first is a claim about silicon and the second is a claim about this
    repository, and telling them apart is the whole of what `ISA` buys. No
    lockstep run could distinguish them -- rvcpp runs both.
    """
    needs_core()
    from core.riscv32 import abi

    def verdict(board) -> type[Exception]:
        with abi.Cpu() as cpu:
            board.install(cpu)
            cpu.write_block(esp32c6.IROM, AMOOR_W.to_bytes(4, "little"))
            cpu.set_regs([0] * 32, pc=esp32c6.IROM)
            with pytest.raises(abi.AbiError) as caught:
                cpu.step()
            return type(caught.value)

    assert verdict(esp32c6) is abi.Unimplemented, (
        "an ESP32-C6 has atomics; refusing one as illegal would be a wrong "
        "claim about the silicon rather than an admission about this core"
    )
    assert verdict(esp32c3) is abi.Illegal, (
        "an ESP32-C3 does not have atomics, so trapping one is the part "
        "behaving correctly"
    )


def test_the_image_this_runs_contains_no_atomic():
    """The other half of the statement above, and what keeps the headline an
    assertion rather than a coincidence.

    `-march=rv32imac` puts the `a` in the *compiler's* string; plain C with no
    `__atomic_*` puts none in the image. If one ever appears here the blink
    stops with `Unimplemented` and the headline fails with a confusing message,
    so this fails first and says why.

    Read with this repository's own disassembler rather than objdump: the
    question is what `core/riscv32` sees, and objdump would answer for a
    different decoder.
    """
    needs_core()
    from core.riscv32 import disasm

    text = [line.text for line in disasm.disassemble(IMAGE.read_bytes(), esp32c6.IROM)]
    atomics = [line for line in text
               if line.startswith(("amo", "lr.", "sc."))]
    assert not atomics, f"the fixture image contains atomics: {atomics}"


# --- the two ways this memory map is not the C3's ---------------------------


def test_sram_has_one_address_here_and_two_on_a_c3():
    """The difference that makes this board's memory map *complete*.

    On a C3 the same 384 KB is at 0x3FC80000 on the data bus and 0x4037C000 on
    the instruction bus. `add_region` cannot express an alias, so mapping both
    would make two independent arrays and a program writing through one and
    reading through the other would see zeros -- `esp32c3.py` therefore maps
    the data view and lets the instruction view fault, and
    `test_the_instruction_bus_view_of_sram_faults_and_the_data_view_does_not`
    pins that limitation.

    Here `soc.h:162-165` gives IRAM and DRAM the same base and the same top,
    and `soc_caps.h:302` says why: `SOC_MMU_DI_VADDR_SHARED`. So there is no
    second view to drop, and a word written through this board's SRAM is
    readable at the only address that names it.
    """
    needs_core()
    assert esp32c3.DRAM != esp32c3.IRAM, "the C3 really does have two"
    assert esp32c6.SRAM == 0x40800000
    assert esp32c6.SRAM_SIZE == 0x80000, "512 KB, not the C3's 384"

    with load() as session:
        session.cpu.write_word(esp32c6.SRAM, 0xC0FFEE)
        assert session.cpu.read_word(esp32c6.SRAM) == 0xC0FFEE
        top = esp32c6.SRAM + esp32c6.SRAM_SIZE - 4
        session.cpu.write_word(top, 0x5EED)
        assert session.cpu.read_word(top) == 0x5EED


def test_there_is_no_separate_rodata_window_on_this_part():
    """A C3 has flash mapped twice -- 0x3C000000 for data, 0x42000000 for code
    -- and `esp32c3.py` maps both. On a C6 `soc.h:156-157` writes DROM as
    `SOC_IROM_LOW`, one window for both busses, so this board maps two regions
    where the C3 maps three.

    Asserted as an absence rather than left to the diff: a reader comparing the
    two files sees a missing region and cannot tell an omission from a fact.
    """
    assert not hasattr(esp32c6, "DROM"), (
        "the C6 has no separate rodata window; a DROM constant here would be "
        "inventing one"
    )
    assert esp32c3.DROM != esp32c3.IROM, "the C3 really does have two windows"

    needs_core()
    from core.riscv32 import abi

    with load() as session, pytest.raises(abi.MemoryFault):
        # The C3's rodata window, which is nothing at all on this part.
        session.cpu.read_word(esp32c3.DROM)


def test_the_only_address_these_two_boards_share_is_the_flash_window():
    """Stated as a measurement because "a C6 is a C3 with a different name" is
    the assumption this whole ticket was filed against.

    Of the six base addresses the two descriptions carry between them, exactly
    one is the same number -- and even that one is a different size.
    """
    c3 = {esp32c3.IROM, esp32c3.DROM, esp32c3.DRAM, esp32c3.IRAM, esp32c3.GPIO}
    c6 = {esp32c6.IROM, esp32c6.SRAM, esp32c6.GPIO}
    assert c3 & c6 == {esp32c6.IROM}, f"shared: {[hex(a) for a in sorted(c3 & c6)]}"
    assert esp32c6.IROM_SIZE != esp32c3.IROM_SIZE, "16 MB against 8"
    assert esp32c6.GPIO != esp32c3.GPIO, "the peripheral bus was renumbered"


# --- the board description's own claims -------------------------------------


def test_the_board_agrees_with_the_catalogue_about_the_isa():
    """One fact, one home. The board declares `RV32IMAC` because that is what
    the datasheet prints; `catalogue.CHIPS` records the same string for the
    same reason, and a board that drifted from it would configure a part the
    catalogue describes differently."""
    from webui.boards import catalogue

    assert esp32c6.ISA == "RV32IMAC"
    assert catalogue.CHIPS["ESP32-C6"][0] == esp32c6.ISA


def test_the_board_configures_the_part_and_not_some_other_one():
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        assert cpu.extensions() == abi.ESP32_C6
        assert cpu.extensions() != abi.ESP32_C3, "an ESP32-C3 has no A and this does"


def test_the_flash_window_top_is_a_build_option_and_the_board_says_so():
    """`soc.h:155` writes `SOC_IROM_HIGH` as a formula over `SOC_MMU_PAGE_SIZE`
    rather than as a number, and `soc_caps.h:298` marks that size configurable
    with 8 KB among the choices. So 16 MB is *this build's* window, not the
    chip's.

    Pinned as two named constants multiplied, because a bare `IROM_SIZE =
    0x1000000` would read as a datasheet constant and is not one. The C3's
    genuinely is: its `soc.h` prints both ends as literals.
    """
    assert esp32c6.IROM_SIZE == esp32c6.MMU_PAGE_SIZE * esp32c6.MMU_ENTRY_NUM
    assert esp32c6.MMU_ENTRY_NUM == 256, "soc.h:155's `<<8`"
    assert esp32c6.IROM_SIZE == 0x1000000, "at the header's default page size"


GPIO_IN = esp32c6.GPIO + esp32c6.GPIO_IN


def test_the_input_register_reads_back_the_pin_the_blink_drives():
    """`GPIO_IN` reads the electrical level on the pins, so GPIO8 driven
    high reads high and driven low reads low: `IN` follows `OUT`. This
    address faulted until OH-161's step 3. GPIO8's pad comes out of reset
    with its input on here (TRM Table 7.12-1, Reset "1"), as on a C3 and
    unlike a C5's."""
    needs_core()
    seen: list[tuple[bool, bool]] = []
    with load() as session:
        last = None
        for _ in range(BUDGET):
            session.step()
            out = bool(session.cpu.read_word(GPIO_OUT) & LED)
            if out != last:
                seen.append((out, bool(session.cpu.read_word(GPIO_IN) & LED)))
                last = out
    assert (True, True) in seen and (False, False) in seen, seen
    assert all(out == read for out, read in seen), seen


def test_an_undescribed_peripheral_faults_rather_than_reading_zero():
    """The whole reason MMIO is not a region. Firmware polling a clock or reset
    status bit that answered zero would spin forever, which reads as a hang
    rather than as a missing feature -- and the fault names the address, which
    is what says which peripheral to describe next."""
    needs_core()
    from core.riscv32 import abi

    with load() as session, pytest.raises(abi.MemoryFault) as caught:
        # PCR, `register/soc/reg_base.h:53` -- the power, clock and reset
        # block, which is exactly the "clock or reset status bit" this test
        # is named for. It was UART0 until OH-161 described UART0's transmit
        # half, at which point the address stopped being undescribed and this
        # test stopped testing anything. OH-161's step 4 maps two of PCR's
        # registers, the ADC's clocks at + 0x80 and + 0x84; its base is not
        # one of them.
        session.cpu.read_word(0x60096000)
    assert "60096000" in str(caught.value).lower()


# --- the header tree, and what licensed using a new one ---------------------


def test_the_new_header_tree_reproduces_the_board_this_repository_already_had():
    """The check that made ESP-IDF v5.5 admissible as a source for two parts
    whose numbers nothing here could otherwise cite.

    `webui/boards/esp32c3.py` reads `framework-arduinoespressif32`, which ships
    ESP-IDF 4.4.7 and has **no `esp32c6` directory at all** -- measured
    2026-08-25, `tools/sdk/` holds `esp32 esp32c3 esp32s2 esp32s3` and nothing
    else. So describing a C6 meant reading a different tree, and a different
    tree is a different claim until something ties them together.

    This is that tie: v5.5's own `esp32c3` headers are asked for every number
    `esp32c3.py` already carries from the older tree, and must give the same
    answers. If they ever diverge, the C6 and C5 boards are citing a source
    that disagrees with the one the C3 was written from, and that is worth a
    red test rather than a paragraph.

    Skips where the tree is absent -- see `idf_root`.
    """
    root = idf_root()
    if root is None:
        pytest.skip(
            "no ESP-IDF checkout; see docs/esp-idf-reference.md:\n"
            "  git clone --filter=blob:none --depth 1 --branch v5.5 "
            "https://github.com/espressif/esp-idf ../esp-idf-reference"
        )
    soc = defines(root / "components/soc/esp32c3/include/soc/soc.h")
    base = defines(root / "components/soc/esp32c3/register/soc/reg_base.h")

    for name, expected in (
        ("SOC_IROM_LOW", esp32c3.IROM),
        ("SOC_IROM_HIGH", esp32c3.IROM + esp32c3.IROM_SIZE),
        ("SOC_DROM_LOW", esp32c3.DROM),
        ("SOC_DROM_HIGH", esp32c3.DROM + esp32c3.DROM_SIZE),
        ("SOC_DRAM_LOW", esp32c3.DRAM),
        ("SOC_DRAM_HIGH", esp32c3.DRAM + esp32c3.DRAM_SIZE),
        ("SOC_IRAM_LOW", esp32c3.IRAM),
        ("SOC_IRAM_HIGH", esp32c3.IRAM + esp32c3.IRAM_SIZE),
    ):
        assert int(soc[name], 16) == expected, (
            f"{name} is {soc[name]} in ESP-IDF v5.5 and 0x{expected:08x} in "
            f"webui/boards/esp32c3.py, which was written from ESP-IDF 4.4.7"
        )
    assert int(base["DR_REG_GPIO_BASE"], 16) == esp32c3.GPIO


def test_the_c6_numbers_this_board_carries_are_the_ones_in_the_header():
    """The forward direction of the test above. Every constant in
    `webui/boards/esp32c6.py` read back out of the header it cites, so a
    transcription error is a failure rather than a wrong emulator.
    """
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    soc = defines(root / "components/soc/esp32c6/include/soc/soc.h")
    caps = defines(root / "components/soc/esp32c6/include/soc/soc_caps.h")
    memory = defines(root / "components/soc/esp32c6/include/soc/ext_mem_defs.h")
    base = defines(root / "components/soc/esp32c6/register/soc/reg_base.h")
    gpio = defines(root / "components/soc/esp32c6/register/soc/gpio_reg.h")

    assert int(soc["SOC_IROM_LOW"], 16) == esp32c6.IROM
    assert int(soc["SOC_IRAM_LOW"], 16) == esp32c6.SRAM
    assert int(soc["SOC_IRAM_HIGH"], 16) == esp32c6.SRAM + esp32c6.SRAM_SIZE
    assert int(base["DR_REG_GPIO_BASE"], 16) == esp32c6.GPIO

    # The two facts the board's docstring makes claims about, read rather than
    # remembered: one flash window for both busses, one address for SRAM.
    assert soc["SOC_DROM_LOW"] == "SOC_IROM_LOW"
    assert soc["SOC_DRAM_LOW"] == soc["SOC_IRAM_LOW"]
    assert soc["SOC_DRAM_HIGH"] == soc["SOC_IRAM_HIGH"]

    # And the window whose size is a build option rather than a constant.
    assert caps["SOC_MMU_PAGE_SIZE_CONFIGURABLE"] == "(1)"
    assert int(memory["SOC_MMU_PAGE_SIZE"], 16) == esp32c6.MMU_PAGE_SIZE
    assert int(memory["SOC_MMU_ENTRY_NUM"]) == esp32c6.MMU_ENTRY_NUM

    for name, offset in (
        ("GPIO_OUT_REG", esp32c6.GPIO_OUT),
        ("GPIO_OUT_W1TS_REG", esp32c6.GPIO_OUT_W1TS),
        ("GPIO_OUT_W1TC_REG", esp32c6.GPIO_OUT_W1TC),
        ("GPIO_ENABLE_REG", esp32c6.GPIO_ENABLE),
        ("GPIO_ENABLE_W1TS_REG", esp32c6.GPIO_ENABLE_W1TS),
        ("GPIO_ENABLE_W1TC_REG", esp32c6.GPIO_ENABLE_W1TC),
        ("GPIO_IN_REG", esp32c6.GPIO_IN),
    ):
        written = gpio[name].strip("()").replace("DR_REG_GPIO_BASE + ", "")
        assert int(written, 16) == offset, f"{name} is {gpio[name]}"


# --- the fixture cannot drift from its source -------------------------------


def test_the_committed_binary_matches_its_source():
    """Skipped where no toolchain exists rather than failing, the same contract
    `tests/riscv32/test_esp32c3_board.py` keeps.

    `-march=rv32imac` and not the C3's `rv32imc`: that is what
    `tools/cmake/toolchain-esp32c6.cmake:10` compiles this part with, less the
    `_zicsr_zifencei` this GCC 8.4 is too old to name.
    """
    home = pathlib.Path.home() / ".platformio/packages/toolchain-riscv32-esp/bin"
    compiler = shutil.which("riscv32-esp-elf-gcc") or home / "riscv32-esp-elf-gcc.exe"
    objcopy = shutil.which("riscv32-esp-elf-objcopy") or home / "riscv32-esp-elf-objcopy.exe"
    if not pathlib.Path(compiler).is_file() or not pathlib.Path(objcopy).is_file():
        pytest.skip("no riscv32-esp-elf toolchain")

    import tempfile

    with tempfile.TemporaryDirectory() as work:
        elf = pathlib.Path(work) / "blink.elf"
        rebuilt = pathlib.Path(work) / "blink.bin"
        subprocess.run(
            [str(compiler), "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
             "-nostdlib", "-nostartfiles", "-T", str(SCRIPT), "-o", str(elf),
             str(SOURCE)],
            check=True, capture_output=True,
        )
        subprocess.run([str(objcopy), "-O", "binary", str(elf), str(rebuilt)],
                       check=True, capture_output=True)
        assert rebuilt.read_bytes() == IMAGE.read_bytes()


def test_the_image_begins_with_its_startup_and_not_with_main():
    """The defect the linker script exists to prevent, pinned.

    Without a script the linker placed `main` first and `_start` after it, so
    the stack setup was skipped and the first push faulted. An image that links
    cleanly and runs the wrong instruction first is exactly the silent class --
    so the first instruction is asserted to be the one that loads `sp`.

    `lui sp, 0x40880` is `0x40880137`: opcode 0x37 (LUI), rd 2 (sp). The
    immediate is this part's SRAM top and not the C3's, which is the other
    thing that would be silently wrong.
    """
    needs_core()
    first = int.from_bytes(IMAGE.read_bytes()[:4], "little")
    assert first & 0x7F == 0x37, "the first instruction is a LUI"
    assert (first >> 7) & 0x1F == 2, "and its destination is sp"
    assert (first & 0xFFFFF000) == esp32c6.SRAM + esp32c6.SRAM_SIZE, (
        "the stack starts at the top of this part's SRAM"
    )


# --- UART0: what a program printed (OH-161) ---------------------------------


def test_the_transmit_gate_holds_the_vendors_reset_value():
    """`register/soc/uart_reg.h:1481` gives `UART_TX_SCLK_EN` as `BIT(24)`
    with `default: 1`, and this part documents only bits 24-27 in that
    register.

    A bare-metal image transmits without touching the clock register, because
    the vendor sets the bit out of reset -- so this is a fact about the part
    that the model must not quietly improve on.
    """
    needs_core()
    from core.riscv32 import abi

    assert esp32c6.UART_CLK_CONF_AT_RESET & esp32c6.UART_TX_SCLK_EN, "bit 24 is set at reset"
    assert esp32c6.UART_CLK_CONF_AT_RESET == (1 << 24) | (1 << 25)
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        assert cpu.read_word(esp32c6.UART0 + esp32c6.UART_CLK_CONF) == (
            esp32c6.UART_CLK_CONF_AT_RESET
        )


def test_every_byte_written_to_the_fifo_comes_back_and_not_just_the_last():
    """The reason the FIFO is a stream rather than a register: a register
    there would answer `o` after a program printed `hello`, which reads as a
    plausible letter rather than as a wrong answer."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        for byte in b"hello":
            cpu.write_word(esp32c6.UART0 + esp32c6.UART_FIFO, byte)
        assert esp32c6.uart0_output(cpu) == b"hello"


def test_nothing_is_transmitted_while_the_clock_bit_is_clear():
    """The clear-air case: firmware that switched the transmitter off is
    silent, which is what the part does and the whole reason the stream takes
    a gate."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        cpu.write_word(esp32c6.UART0 + esp32c6.UART_CLK_CONF, 0)
        for byte in b"lost":
            cpu.write_word(esp32c6.UART0 + esp32c6.UART_FIFO, byte)
        assert esp32c6.uart0_output(cpu) == b""


def test_a_board_that_has_run_nothing_has_printed_nothing():
    """Empty, and it is the truth rather than a missing feature: `uart_view`
    tells this apart from a board that models no UART at all by whether
    `uart0_output` exists, which is why the callable is asserted too."""
    needs_core()
    from core.riscv32 import abi

    assert callable(esp32c6.uart0_output)
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        assert esp32c6.uart0_output(cpu) == b""


def test_the_status_register_this_uart_does_not_model_faults_by_name():
    """`UART_TXFIFO_CNT` lives in `UART_STATUS_REG` (+ 0x1c) and is what
    firmware polls for room in the FIFO. Unmapped on purpose, so that wait
    faults at a named address instead of spinning on a zero that never
    changes. `docs/research/peripheral-layer/design.md` states that
    failure mode generally and `core/cortexm0/cpu.h:246-249` cites it for
    the same reason; this said `docs/architectures.md` 3 until the OH-161
    review pointed out that section 3 is Arm Cortex-M and these are not
    Arm parts."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        with pytest.raises(abi.MemoryFault) as caught:
            cpu.read_word(esp32c6.UART0 + 0x1C)
    assert "0x6000001c" in str(caught.value)


# --- SYSTIMER unit 0: what a program reads the time from (OH-161 step 2) ----


#: `jal x0, 0`: a jump to itself, so a test can retire any number of
#: instructions from one word of flash.
SPIN = 0x0000006F


def field_defaults(header: pathlib.Path, register: str, after: str) -> dict[str, tuple[int, int]]:
    """Every field ESP-IDF documents between `#define <register>` and
    `#define <after>`, as name -> (lowest bit, default).

    Read from the field comments the header generator writes --
    `/** SYSTIMER_CLK_EN : R/W; bitpos: [31]; default: 0;` -- because they
    are where the defaults live; no `#define` carries one.
    """
    text = header.read_text(encoding="utf-8", errors="replace")
    start = text.index(f"#define {register} ")
    block = text[start:text.index(f"#define {after} ", start)]
    # `[hi:lo]` or `[bit]`: the LOW bit is the field's position. Every
    # field this read until OH-161's step 4 was one bit wide, where the two
    # are the same number; `SAR_CLK_DIV`'s `[14:7]` is where they are not.
    found = re.findall(
        r"/\*\* (\w+) : [\w/]+; bitpos: \[(\d+)(?::(\d+))?\]; default: (\d+);", block)
    if not found:
        raise AssertionError(f"no field comments between {register} and {after} in {header}")
    return {name: (int(low or high), int(default)) for name, high, low, default in found}


def test_the_systimer_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every SYSTIMER constant in `esp32c6.py` read back out of the header it
    cites, by define name: the base, the four offsets, and the four bit
    patterns. A transcription error is then a failure here rather than a
    clock that reads the wrong register."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    base = defines(root / "components/soc/esp32c6/register/soc/reg_base.h")
    timer = defines(root / "components/soc/esp32c6/register/soc/systimer_reg.h")

    assert int(base["DR_REG_SYSTIMER_BASE"], 16) == esp32c6.SYSTIMER
    for name, offset in (
        ("SYSTIMER_CONF_REG", esp32c6.SYSTIMER_CONF),
        ("SYSTIMER_UNIT0_OP_REG", esp32c6.SYSTIMER_UNIT0_OP),
        ("SYSTIMER_UNIT0_VALUE_HI_REG", esp32c6.SYSTIMER_UNIT0_VALUE_HI),
        ("SYSTIMER_UNIT0_VALUE_LO_REG", esp32c6.SYSTIMER_UNIT0_VALUE_LO),
    ):
        written = timer[name].strip("()").replace("DR_REG_SYSTIMER_BASE + ", "")
        assert int(written, 16) == offset, f"{name} is {timer[name]}"
    for name, bit in (
        ("SYSTIMER_TIMER_UNIT0_WORK_EN", esp32c6.SYSTIMER_TIMER_UNIT0_WORK_EN),
        ("SYSTIMER_TIMER_UNIT0_UPDATE", esp32c6.SYSTIMER_TIMER_UNIT0_UPDATE),
        ("SYSTIMER_TIMER_UNIT0_VALUE_VALID", esp32c6.SYSTIMER_TIMER_UNIT0_VALUE_VALID),
    ):
        assert timer[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {timer[name]}"
    assert int(timer["SYSTIMER_TIMER_UNIT0_VALUE_HI"].rstrip("U"), 16) == (
        esp32c6.SYSTIMER_TIMER_UNIT0_VALUE_HI)


def test_the_conf_reset_value_is_every_default_the_header_states():
    """`SYSTIMER_CONF_AT_RESET` composed from the header's own field
    defaults, not from the one bit the model reads: firmware reading the
    register back gets every field the part gives it."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    fields = field_defaults(root / "components/soc/esp32c6/register/soc/systimer_reg.h",
                            "SYSTIMER_CONF_REG", "SYSTIMER_UNIT0_OP_REG")
    composed = sum(default << low for low, default in fields.values())
    assert composed == esp32c6.SYSTIMER_CONF_AT_RESET, (
        f"the header's defaults compose to {composed:#010x}, the board says "
        f"{esp32c6.SYSTIMER_CONF_AT_RESET:#010x}: {fields}")


def test_the_rate_is_the_crystal_over_the_divider_the_header_states():
    """16 MHz, as `soc.h`'s `XTAL_CLK_FREQ` over the 2.5 `soc_caps.h`
    gives `SOC_SYSTIMER_FIXED_DIVIDER` in its comment -- the arithmetic
    ESP-IDF's own `systimer.c` writes out, read here from the two lines it
    rests on. The divider is in a comment and not a value, so the raw line
    is read."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    soc = defines(root / "components/soc/esp32c6/include/soc/soc.h")
    factors = soc["XTAL_CLK_FREQ"].strip("() ").split("*")  # "(40*1000000)"
    crystal = int(factors[0]) * int(factors[1])
    caps =(root / "components/soc/esp32c6/include/soc/soc_caps.h").read_text(encoding="utf-8")
    (divider,) = re.findall(r"#define SOC_SYSTIMER_FIXED_DIVIDER .*fixed: ([\d.]+)", caps)
    assert crystal / float(divider) == esp32c6.SYSTIMER_HZ, (crystal, divider)


def test_every_c6_boards_arduino_build_declares_the_clock_the_rate_assumes():
    """The rate is per chip -- `SYSTIMER_INSTRUCTIONS_PER_TICK` is
    `CPU_HZ` over the counter's -- and a board is built against its own
    variant, so every ESP32-C6 board this repository builds must declare the
    same `build.f_cpu` in arduino-esp32's `boards.txt`. A row at another
    clock would have its `millis()` timed by a rate that is not its own.
    Skips, naming the fetch, where the checkout is absent."""
    from tools import board_manifest
    from webui import compile as compiler

    boards_txt = compiler.BOARD_SUPPORT / "arduino-esp32" / "boards.txt"
    if not boards_txt.is_file():
        pytest.skip(f"SKIPPED: no {boards_txt}; python tools/import_pindefs.py --fetch")
    text = boards_txt.read_text(encoding="utf-8", errors="replace")
    (xiao,) = compiler.RECIPES["ESP32-C6"].bsp_includes
    variants = {xiao.rsplit("/", 1)[1]} | {
        row.variant for row in board_manifest.ROWS if row.chip == "ESP32-C6"}
    for variant in sorted(variants):
        keys = re.findall(rf"^([\w.-]+)\.build\.variant={re.escape(variant)}\s*$", text, re.M)
        assert keys, f"no boards.txt entry builds variant {variant}"
        for key in keys:
            (clock,) = re.findall(rf"^{re.escape(key)}\.build\.f_cpu=(\d+)L\s*$", text, re.M)
            assert int(clock) == esp32c6.CPU_HZ, f"{key} ({variant}) runs at {clock}"


def test_the_installed_unit_reads_the_vendors_reset_values():
    """Out of reset `CONF` is its composed default, and unit 0 has given no
    copy: `VALUE_VALID` is `default: 0` (:107) and both value fields too
    (:343, :355)."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c6.SYSTIMER
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        assert cpu.read_word(timer + esp32c6.SYSTIMER_CONF) == esp32c6.SYSTIMER_CONF_AT_RESET
        assert cpu.read_word(timer + esp32c6.SYSTIMER_UNIT0_OP) == 0
        assert cpu.read_word(timer + esp32c6.SYSTIMER_UNIT0_VALUE_HI) == 0
        assert cpu.read_word(timer + esp32c6.SYSTIMER_UNIT0_VALUE_LO) == 0


def test_the_unit_counts_at_the_stated_rate_and_holds_while_its_enable_is_clear():
    """1,005 instructions at ten a tick is 100 ticks. Then `WORK_EN` alone is
    cleared -- the other bits of `CONF` left at reset, so an enable read from
    the wrong bit would keep counting -- and 1,000 more count nothing; set
    again, 1,000 more are another 100."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c6.SYSTIMER
    conf = timer + esp32c6.SYSTIMER_CONF
    op = timer + esp32c6.SYSTIMER_UNIT0_OP
    low = timer + esp32c6.SYSTIMER_UNIT0_VALUE_LO
    assert esp32c6.SYSTIMER_INSTRUCTIONS_PER_TICK == 10, "160 MHz over 16"
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        cpu.write_block(esp32c6.IROM, SPIN.to_bytes(4, "little"))
        cpu.set_regs([0] * 32, pc=esp32c6.IROM)
        for _ in range(1_005):
            cpu.step()
        cpu.write_word(op, esp32c6.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(op) == esp32c6.SYSTIMER_TIMER_UNIT0_VALUE_VALID
        assert cpu.read_word(low) == 100

        cpu.write_word(conf, esp32c6.SYSTIMER_CONF_AT_RESET & ~esp32c6.SYSTIMER_TIMER_UNIT0_WORK_EN)
        for _ in range(1_000):
            cpu.step()
        cpu.write_word(op, esp32c6.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 100, "a disabled unit holds its count"

        cpu.write_word(conf, esp32c6.SYSTIMER_CONF_AT_RESET)
        for _ in range(1_000):
            cpu.step()
        cpu.write_word(op, esp32c6.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 200


def test_the_systimer_registers_this_board_does_not_model_fault_by_name():
    """`UNIT0_LOAD_LO` would set the count and `UNIT1_OP` would ask the other
    unit for a copy. Neither is modelled, so each faults at its own address
    rather than answering a zero a program would take for the time."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        for offset in (0x10, 0x08):
            address = esp32c6.SYSTIMER + offset
            with pytest.raises(abi.MemoryFault) as caught:
                cpu.read_word(address)
            assert f"0x{address:08x}" in str(caught.value)


# --- the pins read: GPIO_IN and IO_MUX (OH-161 step 3) -----------------------


def offset_of(text: str, base: str) -> int:
    """`(BASE + 0x24)` as the integer after the plus."""
    inner = text.strip("()").replace(" ", "")
    assert inner.startswith(base + "+"), f"{text!r} is not an offset from {base}"
    return int(inner[len(base) + 1:], 16)


def test_the_io_mux_numbers_this_board_carries_are_the_ones_in_the_header():
    """The base (`reg_base.h`), every GPIO's pad register through the
    `PERIPHS_IO_MUX_*_U` its `IO_MUX_GPIOn_REG` names -- GPIO0's at + 0x4,
    a C3's offset at a C5's base -- the pad bits and the drive field
    (`io_mux_reg.h`), and the GPIO count (`soc_caps.h`)."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    base = defines(root / "components/soc/esp32c6/register/soc/reg_base.h")
    mux = defines(root / "components/soc/esp32c6/register/soc/io_mux_reg.h")
    caps = defines(root / "components/soc/esp32c6/include/soc/soc_caps.h")

    assert int(base["DR_REG_IO_MUX_BASE"], 16) == esp32c6.IO_MUX
    pads = {int(name[len("IO_MUX_GPIO"):-len("_REG")]): value
            for name, value in mux.items()
            if re.fullmatch(r"IO_MUX_GPIO\d+_REG", name)}
    assert set(pads) == set(esp32c6.IO_MUX_PADS), sorted(pads)
    assert len(pads) == int(caps["SOC_GPIO_PIN_COUNT"].strip("()")), (
        "every GPIO this part counts has a pad")
    for gpio, periphs in pads.items():
        assert offset_of(mux[periphs], "REG_IO_MUX_BASE") == (
            esp32c6.IO_MUX_GPIO0 + gpio * esp32c6.IO_MUX_STRIDE), (
            f"IO_MUX_GPIO{gpio}_REG is {periphs}, {mux[periphs]}")
    for name, bit in (("FUN_PD", esp32c6.IO_MUX_FUN_PD),
                      ("FUN_PU", esp32c6.IO_MUX_FUN_PU),
                      ("FUN_IE", esp32c6.IO_MUX_FUN_IE)):
        assert mux[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {mux[name]}"
    assert int(mux["FUN_DRV_S"]) == esp32c6.IO_MUX_FUN_DRV_SHIFT


def test_each_pad_comes_out_of_reset_as_its_row_of_the_table_says():
    """Installed, every pad register reads its composed reset word, and
    `GPIO_IN` with nothing driven reads exactly the pads Table 7.12-1 pulls
    up with their input on: "3", and MTCK's "1*" at the eFuse's default.
    GPIO16's "4" pulls up with its input off, and reads 0."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        for gpio, word in esp32c6.IO_MUX_AT_RESET.items():
            address = esp32c6.IO_MUX + esp32c6.IO_MUX_GPIO0 + gpio * esp32c6.IO_MUX_STRIDE
            assert cpu.read_word(address) == word, f"GPIO{gpio} at 0x{address:08x}"
        pulled_up = {6, 9, 13, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30}
        assert cpu.read_word(GPIO_IN) == sum(1 << gpio for gpio in pulled_up), (
            f"{cpu.read_word(GPIO_IN):#010x}")


# --- ADC1's one-time sample (OH-161 step 4) -----------------------------------

ADC_ONETIME = esp32c6.APB_SARADC + esp32c6.APB_SARADC_ONETIME_SAMPLE


def onetime(channel: int, atten: int = 3) -> int:
    """ADC1's control word for `channel` at `atten`, START clear."""
    return (esp32c6.ONETIME_SAR1 | channel << esp32c6.ONETIME_CHANNEL_SHIFT
            | atten << esp32c6.ONETIME_ATTEN_SHIFT)


def convert(cpu, word: int) -> tuple[int, bool]:
    """Clear done, start `word` as ESP-IDF does -- the word, then with START
    -- and answer the result and whether done was set."""
    adc = esp32c6.APB_SARADC
    cpu.write_word(adc + esp32c6.APB_SARADC_INT_CLR, esp32c6.ADC1_DONE)
    cpu.write_word(ADC_ONETIME, word)
    cpu.write_word(ADC_ONETIME, word | esp32c6.ONETIME_START)
    done = bool(cpu.read_word(adc + esp32c6.APB_SARADC_INT_RAW) & esp32c6.ADC1_DONE)
    return cpu.read_word(adc + esp32c6.APB_SARADC_SAR1_DATA), done


def test_the_adc_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every ADC constant in `esp32c6.py` read back, by define name, out of
    this part's own headers: the block's base and PCR's (`reg_base.h`), the
    five offsets and every bit (`apb_saradc_reg.h`), the two PCR registers
    and their bits (`pcr_reg.h`) -- at + 0x80 and + 0x84, where a C5's are at
    + 0x88 and + 0x8c -- and ADC1's channels (`adc_channel.h`), GPIO0 to
    GPIO6."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    soc = root / "components/soc/esp32c6"
    base = defines(soc / "register/soc/reg_base.h")
    adc = defines(soc / "register/soc/apb_saradc_reg.h")
    pcr = defines(soc / "register/soc/pcr_reg.h")
    channels = defines(soc / "include/soc/adc_channel.h")

    assert int(base["DR_REG_APB_SARADC_BASE"], 16) == esp32c6.APB_SARADC
    assert int(base["DR_REG_PCR_BASE"], 16) == esp32c6.PCR
    for name, offset in (
        ("APB_SARADC_CTRL_REG", esp32c6.APB_SARADC_CTRL),
        ("APB_SARADC_ONETIME_SAMPLE_REG", esp32c6.APB_SARADC_ONETIME_SAMPLE),
        ("APB_SARADC_SAR1DATA_STATUS_REG", esp32c6.APB_SARADC_SAR1_DATA),
        ("APB_SARADC_INT_RAW_REG", esp32c6.APB_SARADC_INT_RAW),
        ("APB_SARADC_INT_CLR_REG", esp32c6.APB_SARADC_INT_CLR),
    ):
        assert offset_of(adc[name], "DR_REG_APB_SARADC_BASE") == offset, f"{name} is {adc[name]}"
    for name, offset in (("PCR_SARADC_CONF_REG", esp32c6.PCR_SARADC_CONF),
                         ("PCR_SARADC_CLKM_CONF_REG", esp32c6.PCR_SARADC_CLKM_CONF)):
        assert offset_of(pcr[name], "DR_REG_PCR_BASE") == offset, f"{name} is {pcr[name]}"
    for table, name, bit in (
        (adc, "APB_SARADC_SARADC_SAR_CLK_GATED", esp32c6.APB_SARADC_SAR_CLK_GATED),
        (adc, "APB_SARADC_SARADC1_ONETIME_SAMPLE", esp32c6.ONETIME_SAR1),
        (adc, "APB_SARADC_SARADC2_ONETIME_SAMPLE", esp32c6.ONETIME_SAR2),
        (adc, "APB_SARADC_SARADC_ONETIME_START", esp32c6.ONETIME_START),
        (adc, "APB_SARADC_APB_SARADC1_DONE_INT_RAW", esp32c6.ADC1_DONE),
        (adc, "APB_SARADC_APB_SARADC1_DONE_INT_CLR", esp32c6.ADC1_DONE),
        (pcr, "PCR_SARADC_REG_CLK_EN", esp32c6.PCR_SARADC_REG_CLK_EN),
        (pcr, "PCR_SARADC_CLKM_EN", esp32c6.PCR_SARADC_CLKM_EN),
    ):
        assert table[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {table[name]}"
    assert int(adc["APB_SARADC_SARADC_ONETIME_CHANNEL_S"]) == esp32c6.ONETIME_CHANNEL_SHIFT
    assert int(adc["APB_SARADC_SARADC_ONETIME_ATTEN_S"]) == esp32c6.ONETIME_ATTEN_SHIFT
    assert esp32c6.ONETIME_CONVERSION == (
        esp32c6.ONETIME_SAR1 | esp32c6.ONETIME_SAR2
        | int(adc["APB_SARADC_SARADC_ONETIME_CHANNEL_V"].rstrip("U"), 16)
        << esp32c6.ONETIME_CHANNEL_SHIFT
        | int(adc["APB_SARADC_SARADC_ONETIME_ATTEN_V"].rstrip("U"), 16)
        << esp32c6.ONETIME_ATTEN_SHIFT)
    adc1 = {int(channels[f"ADC1_CHANNEL_{n}_GPIO_NUM"]): n
            for n in range(8) if f"ADC1_CHANNEL_{n}_GPIO_NUM" in channels}
    assert adc1 == esp32c6.ADC1_CHANNELS
    assert esp32c6.ADC_GATE == (esp32c6.PCR + esp32c6.PCR_SARADC_CLKM_CONF,
                                esp32c6.PCR_SARADC_CLKM_EN)


def test_the_adc_reset_values_are_every_default_the_header_states():
    """`CTRL`, `ONETIME_SAMPLE` and the two PCR registers out of reset,
    composed from this part's own field comments -- `PCR_SARADC_CLKM_EN`
    and `PCR_SARADC_REG_CLK_EN` both `default: 1` here."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    regs = root / "components/soc/esp32c6/register/soc"
    for header, register, after, board in (
        ("apb_saradc_reg.h", "APB_SARADC_CTRL_REG", "APB_SARADC_CTRL2_REG",
         esp32c6.APB_SARADC_CTRL_AT_RESET),
        ("apb_saradc_reg.h", "APB_SARADC_ONETIME_SAMPLE_REG", "APB_SARADC_ARB_CTRL_REG",
         esp32c6.ONETIME_SAMPLE_AT_RESET),
        ("pcr_reg.h", "PCR_SARADC_CONF_REG", "PCR_SARADC_CLKM_CONF_REG",
         esp32c6.PCR_SARADC_CONF_AT_RESET),
        ("pcr_reg.h", "PCR_SARADC_CLKM_CONF_REG", "PCR_TSENS_CLK_CONF_REG",
         esp32c6.PCR_SARADC_CLKM_CONF_AT_RESET),
    ):
        fields = field_defaults(regs / header, register, after)
        composed = sum(default << low for low, default in fields.values())
        assert composed == board, (
            f"{register}: the header's defaults compose to {composed:#010x}, the "
            f"board says {board:#010x}: {fields}")


def test_each_channel_converts_its_own_pin_out_of_reset():
    """The C6's ADC clock resets on, so a start converts without touching
    it: GPIO0 and GPIO1, channels 0 and 1, held at 1.65 V and 1.1 V. Clear
    the clock and a start is never done."""
    needs_core()
    from core.riscv32 import abi

    gate, bit = esp32c6.ADC_GATE
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        esp32c6.hold_volts(cpu, {0: 1.65, 1: 1.1})
        assert cpu.read_word(gate) & bit
        assert convert(cpu, onetime(0)) == (1536, True)
        assert convert(cpu, onetime(1)) == (1024, True)
        assert convert(cpu, onetime(6)) == (0, True), "GPIO6 holds nothing"
        cpu.write_word(gate, cpu.read_word(gate) & ~bit)
        assert convert(cpu, onetime(1)) == (0, False), "no conversion, no done"


def test_the_code_refuses_a_bool_and_an_integer_no_float_can_hold():
    """`True` would convert as 1 V, and 10 ** 400 -- an integer `json.loads`
    accepts -- raised `OverflowError` out of `math.isfinite` rather than say
    what it was given, until the step 4 review."""
    for volts in (True, 10 ** 400):
        with pytest.raises(ValueError) as caught:
            esp32c6.adc_code(volts, 3)
        assert repr(volts) in str(caught.value), str(caught.value)


def test_a_start_on_adc2_or_on_no_channel_faults_and_a_gpio_with_no_pad_is_refused():
    """ADC2's bit, the reset channel 13 and channel 7 -- the part has seven,
    0 to 6 -- are held at nothing and fault; a voltage on GPIO31, which this
    part has no pad for, is refused by name."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        for word in (esp32c6.ONETIME_SAR2, esp32c6.ONETIME_SAR1 | esp32c6.ONETIME_SAMPLE_AT_RESET,
                     onetime(7)):
            cpu.write_word(ADC_ONETIME, word)
            with pytest.raises(abi.MemoryFault):
                cpu.write_word(ADC_ONETIME, word | esp32c6.ONETIME_START)
        with pytest.raises(ValueError) as caught:
            esp32c6.hold_volts(cpu, {31: 1.0})
        assert "GPIO31" in str(caught.value), str(caught.value)
