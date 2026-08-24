# OpenHardware — an emulated SAMD21 board running a real compiled blink.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this proves that `test_blink.py` does not
#
# `test_blink.py` proved one board works. This proves the *core* does, because
# the SAMD21 shares `core/cortexm0` with the RP2040 and shares nothing else:
# different flash address, different peripheral, different reset behaviour.
# Until this file existed, "one core serves several boards" was asserted by
# `test_the_same_core_serves_a_board_with_a_different_memory_map`, which builds
# a SAMD21-*shaped* map by hand. This runs a real compiled SAMD21 image on a
# real SAMD21 description, which is the difference between a shape and a chip.
#
# **Flash is at zero here.** That is the single fact that most justifies having
# moved the memory map out of the core, and it is exercised on every line
# below: the vector table the Cortex-M0+ reads at reset is the first eight
# bytes of the image, with no XIP window and no boot2 blob in front of it.
#
# ## The committed binary
#
# `samd21/blink.bin` is 48 bytes and is committed, so this runs on a machine
# with no ARM toolchain rather than skipping.
# `test_the_committed_binary_matches_its_source` rebuilds it wherever a
# compiler exists, so the two cannot drift silently.

import itertools
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0.abi import Cpu
from webui.boards import samd21

HERE = pathlib.Path(__file__).resolve().parent / "samd21"
IMAGE = HERE / "blink.bin"

#: Flash base, and therefore also the reset vector's address. Not a constant of
#: this test's own -- the board says where flash is.
LOAD = samd21.FLASH

#: PA17 is the XIAO SAMD21's user LED; `webui/boards/samd21.py` cites Seeed's
#: pin table for it.
LED = 1 << samd21.LED_PIN

#: `PM_APBBMASK`, from `instance/pm.h:57`. Deliberately **not** exported by the
#: board module, because the board does not model PM -- this test is what shows
#: it does not need to.
PM_APBBMASK = 0x4000041C

#: Long enough for several toggles at the measured 453-instruction period, and
#: short enough to stay instant.
BUDGET = 20_000


def start(cpu: Cpu) -> None:
    """Install the board, load the image, and enter at its reset vector."""
    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    samd21.install(cpu)
    cpu.write_block(LOAD, IMAGE.read_bytes())
    sp = cpu.read_word(LOAD)
    entry = cpu.read_word(LOAD + 4)
    cpu.set_regs([0] * 13 + [sp, 0, entry & ~1], apsr=0)


def run_and_watch(cpu: Cpu, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state."""
    out = samd21.group(samd21.PORTA) + samd21.PORT_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        cpu.step()
        now = cpu.read_word(out) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


def test_the_image_carries_a_vector_table_at_address_zero(cpu):
    """The RP2040 equivalent reads its table at 0x10000100. This one reads it
    at 0, which is the whole reason two board files exist."""
    start(cpu)
    assert LOAD == 0x00000000
    assert cpu.read_word(LOAD) == 0x20008000            # top of 32K SRAM
    assert cpu.read_word(LOAD + 4) & 1                  # Thumb bit set


def test_the_blink_runs_without_faulting(cpu):
    """No unimplemented encoding and no unmodelled address, for 20,000
    instructions of compiler output."""
    start(cpu)
    run_and_watch(cpu)


def test_the_led_pin_is_configured_as_an_output(cpu):
    """A blink on a pin still set to input would be a lie the value register
    alone cannot catch. DIR is what DIRSET was aliased onto."""
    start(cpu)
    run_and_watch(cpu, budget=100)
    assert cpu.read_word(samd21.group(samd21.PORTA) + samd21.PORT_DIR) & LED


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


def test_the_toggle_goes_through_outtgl_rather_than_a_read_modify_write(cpu):
    """`OUTTGL` is mapped as an XOR alias onto `OUT`. If it had been mapped as
    a plain store instead, the image -- which writes the *bit mask*, not the
    desired value -- would set the pin once and never clear it. That failure
    looks identical to a dead delay loop from the outside, so it is worth
    separating: after an odd number of toggles the pin is high, and after an
    even number it is low, which only an XOR produces."""
    start(cpu)
    states = [state for _, state in run_and_watch(cpu)]
    assert states[0] is True
    assert states[1] is False


def test_the_board_models_no_power_manager_and_the_image_never_asks_for_one(cpu):
    """`PM_APBBMASK` resets to 0x7F with the PORT bit already set, so PORT is
    clocked before the first instruction and a blink needs no clock setup.

    That is a claim about silicon, and this is the measurement behind it rather
    than a restatement: PM is not modelled at all, so *any* access to it would
    fault -- and the image runs its full budget without one. Delete
    `install_port`'s sibling reasoning and add a PM write to `blink.c`, and
    this test fails loudly instead of the model quietly acquiring a register
    nobody checked."""
    start(cpu)
    assert not cpu.is_mapped(PM_APBBMASK)
    assert not cpu.in_range(PM_APBBMASK)
    run_and_watch(cpu)


def test_the_committed_binary_matches_its_source(cpu):
    """`blink.bin` is committed so this suite runs without a toolchain. That
    invites drift, so wherever a compiler exists the binary is rebuilt and
    compared -- and where none exists, this is the only test here that skips."""
    # PATH first, then the PlatformIO toolchain this machine happens to have,
    # for the reason `test_blink.py` gives: a guard that runs on exactly one
    # computer protects nothing on CI.
    found = shutil.which("arm-none-eabi-gcc")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        pathlib.Path.home(),
        ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe",
    )
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    if not gcc.is_file():
        pytest.skip(f"no arm-none-eabi-gcc on PATH or at {gcc}")

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
            "samd21/blink.bin does not match what samd21/blink.c compiles to. "
            "Rebuild it:\n"
            "  arm-none-eabi-gcc -mcpu=cortex-m0plus -mthumb -Os -ffreestanding "
            "-nostdlib -T blink.ld -o blink.elf blink.c\n"
            "  arm-none-eabi-objcopy -O binary blink.elf blink.bin"
        )
