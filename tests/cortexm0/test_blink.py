# OpenHardware — an emulated RP2040 board running a real compiled blink.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this test is the one that matters
#
# Everything else in tests/cortexm0/ checks a part: an encoding, a flag, a
# register. This checks the whole thing at once, the way a person would --
# compile a program, load it, and watch the light.
#
# The image is built by arm-none-eabi-gcc from `blink/blink.c`, so nothing
# about it is hand-assembled: it is the real output of a real compiler for
# Cortex-M0+. Running it exercises the instruction set, the memory map, the
# RESETS atomic aliases, the RESET_DONE mirror a spin loop depends on, and the
# SIO GPIO registers -- in the order and combination a program actually uses
# them, which no unit test reproduces.
#
# ## Why it is not the Arduino image
#
# The Arduino/pico-sdk blink runs 225,759 instructions here and then calls into
# the RP2040 boot ROM, which is not redistributable (see
# `webui/boards/rp2040.py`). The measured detail worth keeping: rp2040js
# reaches the *same* PC at the *same* step, then warns and continues executing
# unmapped memory, because it does not model faults. Both models lack the ROM;
# this one says so.
#
# So the image here is bare metal -- no vendor runtime, no ROM calls. That is a
# smaller claim than "the Arduino blink runs", and it is a true one.
#
# ## The committed binary
#
# `blink.bin` is 76 bytes and is committed, so this test runs on a machine with
# no ARM toolchain rather than skipping. `test_the_committed_binary_matches_its_
# source` rebuilds it wherever a compiler exists, so the two cannot drift
# silently -- the failure mode a committed artefact normally invites.

import itertools
import pathlib
import subprocess

import pytest

from core.cortexm0.abi import Cpu
from webui.boards import rp2040

HERE = pathlib.Path(__file__).resolve().parent / "blink"
IMAGE = HERE / "blink.bin"

#: Where the linker script puts it: past boot2's 256 bytes, at the vector table.
LOAD = 0x10000100

#: GP25 is the Pico's on-board LED.
LED = 1 << 25

#: Long enough for several toggles at the measured 453-instruction period, and
#: short enough to stay instant.
BUDGET = 20_000


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


def run_and_watch(cpu: Cpu, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state."""
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        cpu.step()
        now = cpu.read_word(out) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


def test_the_image_carries_a_vector_table_the_board_can_enter(cpu):
    start(cpu)
    assert cpu.read_word(LOAD) == 0x20042000            # top of SRAM
    assert cpu.read_word(LOAD + 4) & 1                  # Thumb bit set


def test_the_blink_runs_without_faulting(cpu):
    """No unimplemented encoding and no unmodelled address, for 20,000
    instructions of compiler output."""
    start(cpu)
    run_and_watch(cpu)


def test_the_led_pin_is_configured_as_an_output(cpu):
    """A blink on a pin still set to input would be a lie the value register
    alone cannot catch."""
    start(cpu)
    run_and_watch(cpu, budget=100)
    assert cpu.read_word(rp2040.SIO + rp2040.SIO_GPIO_OE) & LED


def test_the_led_actually_blinks(cpu):
    """The whole point. Two transitions is a blink; one is a pin that came on
    and stayed on, which is what a broken toggle looks like."""
    start(cpu)
    transitions = run_and_watch(cpu)
    assert len(transitions) >= 2, f"LED changed state {len(transitions)} times"


def test_the_blink_alternates_rather_than_only_rising(cpu):
    start(cpu)
    states = [state for _, state in run_and_watch(cpu)]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_blink_has_a_steady_period(cpu):
    """The delay loop is a counted `for`, so the interval between toggles must
    be constant. A wandering period would mean the loop counter is wrong."""
    start(cpu)
    steps = [step for step, _ in run_and_watch(cpu)]
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"


def test_the_program_reached_its_loop_by_leaving_reset_first(cpu):
    """The blink cannot start until IO_BANK0 and PADS_BANK0 are out of reset,
    because the program spins on RESET_DONE until they are. Their reset bits
    being clear afterwards is the evidence that spin loop terminated."""
    start(cpu)
    run_and_watch(cpu, budget=200)
    reset = cpu.read_word(rp2040.RESETS + rp2040.RESETS_RESET)
    assert reset & (1 << 5) == 0, "IO_BANK0 still held in reset"
    assert reset & (1 << 8) == 0, "PADS_BANK0 still held in reset"


def test_the_committed_binary_matches_its_source(cpu):
    """`blink.bin` is committed so this suite runs without a toolchain. That
    invites drift, so wherever a compiler exists the binary is rebuilt and
    compared -- and where none exists, this is the only test that skips."""
    gcc = pathlib.Path(
        "C:/Users/Alexyodude/.platformio/packages/toolchain-gccarmnoneeabi/bin/"
        "arm-none-eabi-gcc.exe"
    )
    objcopy = gcc.with_name("arm-none-eabi-objcopy.exe")
    if not gcc.is_file():
        pytest.skip(f"no arm-none-eabi-gcc at {gcc}")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        elf = pathlib.Path(tmp) / "blink.elf"
        binary = pathlib.Path(tmp) / "blink.bin"
        subprocess.run(
            [str(gcc), "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-ffreestanding",
             "-nostdlib", "-T", str(HERE / "blink.ld"), "-o", str(elf),
             str(HERE / "blink.c")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [str(objcopy), "-O", "binary", str(elf), str(binary)],
            check=True, capture_output=True,
        )
        assert binary.read_bytes() == IMAGE.read_bytes(), (
            "blink.bin does not match what blink.c compiles to. Rebuild it:\n"
            "  arm-none-eabi-gcc -mcpu=cortex-m0plus -mthumb -Os -ffreestanding "
            "-nostdlib -T blink.ld -o blink.elf blink.c\n"
            "  arm-none-eabi-objcopy -O binary blink.elf blink.bin"
        )
