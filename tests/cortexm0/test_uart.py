# OpenHardware — an emulated RP2040 UART, and a real compiled image printing.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this adds that the blink tests do not
#
# A blink proves a pin changed. This proves a *byte stream* survived, which is
# a different kind of claim: every character has to arrive, in order, and none
# of them may arrive before the peripheral was enabled.
#
# It is also the first peripheral that needed something new in the core. The
# three mapping primitives all describe a word — hold one, modify another's,
# derive from another's — and a UART data register is a queue. A `map_register`
# there keeps only the last character written, so a test would read back a
# plausible single letter instead of an empty buffer: wrong rather than loud,
# which is the failure this project ranks worst.
#
# ## The gate is the interesting half
#
# `docs/research/peripheral-layer/rp2040_v2/rp2040_uart.json` names the trap
# directly: "A model letting TXFF/BUSY move before UARTEN==1 lets firmware
# appear to print successfully before the UART is enabled -- silently wrong the
# same way FUNCSEL errors are silently wrong." So `map_stream` takes the enable
# bit and discards what is written while it is clear, and
# `test_nothing_is_transmitted_before_the_uart_is_enabled` is what holds it
# there.

import pathlib
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0.abi import Cpu
from webui.boards import rp2040

HERE = pathlib.Path(__file__).resolve().parent / "uart"
IMAGE = HERE / "hello.bin"

#: Past boot2, where `hello.ld` links the vector table.
LOAD = 0x10000100

#: What `hello.c` prints. Spelled here rather than read out of the source, so
#: that changing one without the other fails instead of agreeing with itself.
MESSAGE = b"hello, world\n"

#: Long enough for the reset wait, the configuration and thirteen characters.
BUDGET = 20_000


@pytest.fixture
def board(cpu):
    """A whole RP2040, replacing the bare SRAM the conftest fixture installs."""
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    return cpu


def start(cpu: Cpu) -> None:
    """Install the board, load the image, and enter at its reset vector."""
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    cpu.write_block(LOAD, IMAGE.read_bytes())
    sp = cpu.read_word(LOAD)
    entry = cpu.read_word(LOAD + 4)
    cpu.set_regs([0] * 13 + [sp, 0, entry & ~1], apsr=0)


def run(cpu: Cpu, budget: int = BUDGET) -> None:
    for _ in range(budget):
        cpu.step()


# --- the whole thing at once -----------------------------------------------


def test_a_real_compiled_image_prints_its_message(cpu):
    """The point of the ticket: a printf arrives. 130 bytes of
    arm-none-eabi-gcc output, driving a PL011 the way pico-sdk's
    `uart_putc_raw` does — spin on TXFF, store to UARTDR."""
    start(cpu)
    run(cpu)
    assert rp2040.uart0_output(cpu) == MESSAGE


def test_every_character_arrives_rather_than_only_the_last(cpu):
    """The failure a plain register would produce, named separately because it
    is the one that looks like success. `map_register` at UARTDR would hold
    `\\n` and nothing else, and a test asserting "some output" would pass."""
    start(cpu)
    run(cpu)
    assert len(rp2040.uart0_output(cpu)) == len(MESSAGE)


def test_the_image_enabled_the_uart_before_printing(cpu):
    """`UARTCR` afterwards carries UARTEN and TXE. Checked because the gate
    below makes enabling load-bearing: an image that never set it would print
    nothing, and this says which of the two happened."""
    start(cpu)
    run(cpu)
    control = cpu.read_word(rp2040.UART0 + rp2040.UART_CR)
    assert control & rp2040.UART_CR_UARTEN
    assert control & (1 << 8), "TXE"


def test_the_image_configured_a_real_baud_rate(cpu):
    """67 and 52 are 115200 from a 125 MHz peripheral clock. The model does not
    time anything, so these are checked to show the fixture is a plausible
    configuration rather than a register-poke that happens to work."""
    start(cpu)
    run(cpu)
    assert cpu.read_word(rp2040.UART0 + rp2040.UART_IBRD) == 67
    assert cpu.read_word(rp2040.UART0 + rp2040.UART_FBRD) == 52


# --- the gate ---------------------------------------------------------------


def test_nothing_is_transmitted_before_the_uart_is_enabled(board):
    """A disabled transmitter sends nothing, and modelling it otherwise is the
    silent lie the research file names. Writes land, the access succeeds — the
    part does not fault on this — and the bytes go nowhere."""
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("x"))
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("y"))
    assert rp2040.uart0_output(board) == b""


def test_the_same_writes_are_transmitted_once_it_is_enabled(board):
    """The other half of the pair. Without this, a gate stuck permanently shut
    would pass the test above and print nothing ever."""
    board.write_word(rp2040.UART0 + rp2040.UART_CR, rp2040.UART_CR_UARTEN)
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("x"))
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("y"))
    assert rp2040.uart0_output(board) == b"xy"


def test_disabling_the_uart_again_stops_the_stream(board):
    """The gate is read at each write, not latched at the first one."""
    board.write_word(rp2040.UART0 + rp2040.UART_CR, rp2040.UART_CR_UARTEN)
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("a"))
    board.write_word(rp2040.UART0 + rp2040.UART_CR, 0)
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("b"))
    assert rp2040.uart0_output(board) == b"a"


def test_only_the_low_byte_of_a_word_write_is_transmitted(board):
    """UARTDR's data is bits 7-0; the rest are receive error flags. A model
    storing the whole word would put 0x341 on the wire as three bytes or one
    wrong one."""
    board.write_word(rp2040.UART0 + rp2040.UART_CR, rp2040.UART_CR_UARTEN)
    board.write_word(rp2040.UART0 + rp2040.UART_DR, 0xFFFFFF41)
    assert rp2040.uart0_output(board) == b"A"


# --- UARTFR, the register firmware spins on ---------------------------------


def test_the_flag_register_says_the_transmitter_has_room(board):
    """`uart_putc_raw` spins `while (!uart_is_writable(uart))`. The research
    file spells out both ways to get this wrong: a TXFF stuck set hangs the
    first character, and one that never clears hangs the second."""
    flags = board.read_word(rp2040.UART0 + rp2040.UART_FR)
    assert not flags & rp2040.UART_FR_TXFF
    assert not flags & rp2040.UART_FR_BUSY


def test_the_flag_register_says_the_receiver_is_empty(board):
    """`RXFE` resets to 1 on the part, and nothing in this project drives RX,
    so empty forever is the truth rather than a gap."""
    assert board.read_word(rp2040.UART0 + rp2040.UART_FR) & rp2040.UART_FR_RXFE


def test_the_flag_register_ignores_writes(board):
    """It is read-only on the part. `map_register` would let firmware set TXFF
    and hang itself in a loop the hardware would have exited."""
    board.write_word(rp2040.UART0 + rp2040.UART_FR, 0xFFFFFFFF)
    assert board.read_word(rp2040.UART0 + rp2040.UART_FR) == rp2040.UART_FR_AT_REST


# --- sub-word access to mapped registers ------------------------------------
#
# Driven by real instructions rather than through a Python helper, and that is
# deliberate. The defect being fixed is that `STRB` and `LDRB` never consulted
# the register map, so the thing to prove is that the *instruction* reaches a
# mapped address — a Python-side byte accessor would be a second path that
# could pass while the one firmware uses still faulted.

#: Where the fragments below are assembled and run, inside the board's SRAM.
CODE = rp2040.SRAM + 0x1000

#: Thumb format 9, `011 B L Offset5 Rb Rd`, and format 10, `1000 L ...`.
#: Spelled out because a bare hex constant in a test is a fact nobody can
#: check. `Rb` is r0 (the address) and the data register is named per line.
STRB_R1_R0 = 0x7001   # STRB r1, [r0, #0]
LDRB_R2_R0 = 0x7802   # LDRB r2, [r0, #0]
STRB_R1_R0_1 = 0x7041  # STRB r1, [r0, #1]
LDRB_R2_R0_2 = 0x7882  # LDRB r2, [r0, #2]
STRH_R1_R0_2 = 0x8041  # STRH r1, [r0, #2] -- offset is in halfwords


def execute(board, encodings, r0, r1=0):
    """Assemble `encodings` into SRAM, run them, and return r2 afterwards."""
    for index, encoding in enumerate(encodings):
        board.write_halfword(CODE + index * 2, encoding)
    board.set_regs([r0, r1] + [0] * 11 + [rp2040.SRAM + 0x2000, 0, CODE], apsr=0)
    for _ in encodings:
        board.step()
    return board.get_regs().as_list()[2]


def test_a_byte_store_reaches_a_mapped_register(board):
    """`STRB` to MMIO faulted until this ticket: the word accessors consulted
    the register map and the sub-word ones did not, so a mapped address
    reported that it left the modelled memory. Every peripheral modelled up to
    now was word-accessed, which is why nothing caught it."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0)
    execute(board, [STRB_R1_R0], r0=target, r1=0xAB)
    assert board.read_word(target) == 0xAB


def test_a_byte_store_leaves_the_other_bytes_of_the_word_alone(board):
    """Why the write is byte-masked rather than read-modify-write."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0x11223344)
    execute(board, [STRB_R1_R0_1], r0=target, r1=0xFF)
    assert board.read_word(target) == 0x1122FF44


def test_a_byte_load_returns_that_byte_of_the_register(board):
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0x11223344)
    assert execute(board, [LDRB_R2_R0], r0=target) == 0x44
    assert execute(board, [LDRB_R2_R0_2], r0=target) == 0x22


def test_a_byte_store_through_a_set_alias_sets_only_that_bytes_bits(board):
    """The case read-modify-write gets wrong and a byte mask gets right. RMW
    would read the whole word, replace one byte and store the result back
    through a SET alias — setting every bit that happened to be in the value
    read, rather than the eight the instruction addressed."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0x11223344)
    execute(board, [STRB_R1_R0], r0=target + rp2040.ALIAS_SET, r1=0x0F)
    assert board.read_word(target) == 0x1122334F


def test_a_halfword_store_reaches_a_mapped_register(board):
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0x11223344)
    execute(board, [STRH_R1_R0_2], r0=target, r1=0xBEEF)
    assert board.read_word(target) == 0xBEEF3344


# --- housekeeping -----------------------------------------------------------


def test_uninstalling_the_board_takes_the_captured_output_with_it(board):
    """Streams live in a table beside the register map, so `clear_registers`
    has to empty both or a board that no longer exists keeps reporting output.

    **Asserted without reinstalling, and that is the whole test.** The first
    version installed a fresh board before looking, which cannot fail:
    `map_stream` overwrites its entry, so the output is empty whether or not
    the table was cleared. Mutation testing found it — deleting
    `streams_.clear()` left all eighteen tests green. Reading the stream while
    nothing is mapped is the only moment the leak is visible.
    """
    board.write_word(rp2040.UART0 + rp2040.UART_CR, rp2040.UART_CR_UARTEN)
    board.write_word(rp2040.UART0 + rp2040.UART_DR, ord("z"))
    assert rp2040.uart0_output(board) == b"z"

    board.clear_registers()
    assert not board.is_mapped(rp2040.UART0 + rp2040.UART_DR)
    assert rp2040.uart0_output(board) == b""


def test_the_committed_binary_matches_its_source(cpu):
    """`hello.bin` is committed so this suite runs without a toolchain, and is
    rebuilt and compared wherever a compiler exists."""
    found = shutil.which("arm-none-eabi-gcc")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        pathlib.Path.home(),
        ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe",
    )
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    if not gcc.is_file():
        pytest.skip(f"no arm-none-eabi-gcc on PATH or at {gcc}")

    with tempfile.TemporaryDirectory() as tmp:
        elf = pathlib.Path(tmp) / "hello.elf"
        binary = pathlib.Path(tmp) / "hello.bin"
        subprocess.run(
            [str(gcc), "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-ffreestanding",
             "-nostdlib", "-T", str(HERE / "hello.ld"), "-o", str(elf),
             str(HERE / "hello.c")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [str(objcopy), "-O", "binary", str(elf), str(binary)],
            check=True, capture_output=True,
        )
        assert binary.read_bytes() == IMAGE.read_bytes(), (
            "uart/hello.bin does not match what uart/hello.c compiles to."
        )
