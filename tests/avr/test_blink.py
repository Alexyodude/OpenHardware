# OpenHardware — an AVR core running a real compiled Arduino Uno blink.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this can and cannot claim
#
# `docs/architectures.md` records AVR's candidate oracles — simavr, avr-gdb —
# as **neither of them hardware-captured**, and neither is installed here. So
# this core cannot reach the standard `core/i8086` meets against SST8088, and
# nothing below says it does.
#
# What it can do is exactly what the RP2040 and SAMD21 did: run a real compiled
# image and be watched doing the right thing. `blink/blink.c` is built by
# avr-gcc 7.3.0 at -Os, so nothing about it is hand-assembled, and it exercises
# the instruction set, both address spaces, the IO window and the stack in the
# combination a program actually uses.
#
# ## The two defects this fixture caught, both silent
#
# Neither crashed. Both ran and produced a plausible wrong answer, which is the
# failure class this repository ranks worst:
#
#   * the `ldd`/`std` mask included bit 9, which is the load/store selector
#     read inside the branch — so every load matched and no store ever did.
#   * `brbc`/`brbs` polarity was inverted. Bit 10 SET means branch-if-CLEAR,
#     which is the opposite of how the bit reads. The blink still ran 60,000
#     instructions without faulting; it just toggled every 10 instructions
#     instead of every 1,110, because the delay loop took its exit branch on
#     the first comparison every time.
#
# The period is what caught the second one, which is why it is asserted below
# rather than only the transition count.

import itertools
import pathlib
import shutil
import subprocess
import tempfile

import pytest

HERE = pathlib.Path(__file__).resolve().parent / "blink"
IMAGE = HERE / "blink.bin"

#: Data-space addresses, from the toolchain's own `iom328p.h`:
#: `DDRB _SFR_IO8(0x04)` and `PORTB _SFR_IO8(0x05)`, where `_SFR_IO8(x)` is
#: `x + 0x20`. The +0x20 is the likeliest off-by-something in an AVR model,
#: which is why `test_the_io_window_sits_above_the_registers` pins it.
DDRB = 0x24
PORTB = 0x25

#: PB5 is the Uno's LED. From Arduino's own variant file:
#: `framework-arduino-avr/variants/standard/pins_arduino.h` defines
#: `LED_BUILTIN 13`, and its pinout comment reads `PB5 (D 13)`.
LED = 1 << 5

#: RAMEND on this part, and where SP comes up.
RAMEND = 0x08FF

#: Long enough for several toggles at the measured 1,110-instruction period.
BUDGET = 20_000


def load(cpu) -> None:
    """Put the image in program memory and start at the reset vector.

    Which is word 0, and needs no vector table read: an AVR begins executing
    at address zero rather than loading a stack pointer and an entry point out
    of one, the way every Arm board in this repository does.
    """
    cpu.write_program_block(0, IMAGE.read_bytes())
    cpu.pc = 0


def run_and_watch(cpu, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state."""
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        cpu.step()
        now = cpu.read_data(PORTB) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


# --- the machine before anything runs ----------------------------------------


def test_the_stack_pointer_comes_up_at_ramend(cpu):
    """A bare-metal image built with -nostartfiles never writes SP, because
    avr-libc's startup code is what normally does. Left at zero, the first
    `push` would run off the bottom of the data space and fault on an image
    the silicon runs happily."""
    assert cpu.sp == RAMEND


def test_the_registers_are_the_bottom_of_the_data_space(cpu):
    """Not a copy of it. `lds r0, 0x0001` reads R1 on this machine, so the
    model holds one storage and `reg()` is a view onto it — two arrays that
    must agree being two arrays that will not."""
    cpu.set_reg(5, 0xA5)
    assert cpu.read_data(0x05) == 0xA5
    cpu.write_data(0x06, 0x3C)
    assert cpu.reg(6) == 0x3C


def test_the_io_window_sits_above_the_registers(cpu):
    """`in`/`out` take an address 0x20 lower than a data access to the same
    register. PORTB is 0x05 to `out` and 0x25 to everything else."""
    cpu.write_io(0x05, 0x20)
    assert cpu.read_data(PORTB) == 0x20


def test_the_two_address_spaces_do_not_overlap(cpu):
    """0x0100 is a flash word *and* a byte of SRAM, and which one is meant is
    decided by the instruction asking. A model with one space would have the
    image overwrite its own variables."""
    cpu.write_program(0x0100, 0xBEEF)
    cpu.write_data(0x0100, 0x42)
    assert cpu.read_program(0x0100) == 0xBEEF
    assert cpu.read_data(0x0100) == 0x42


def test_untouched_flash_reads_as_erased(cpu):
    """0xFFFF is what erased flash holds and is not a defined AVR opcode, so a
    program running off the end of its image stops rather than executing
    something plausible — the same argument `core/cortexm0` makes for 0xFF."""
    assert cpu.read_program(0x2000) == 0xFFFF


# --- the compiled image -------------------------------------------------------


def test_the_blink_runs_without_faulting(cpu):
    """No unimplemented encoding and no refused access, for 20,000
    instructions of compiler output."""
    load(cpu)
    run_and_watch(cpu)


def test_the_led_pin_is_configured_as_an_output(cpu):
    """A blink on a pin still set to input would be a lie the value register
    alone cannot catch. This is the `sbi` that reached DDRB."""
    load(cpu)
    run_and_watch(cpu, budget=100)
    assert cpu.read_data(DDRB) & LED


def test_the_led_actually_blinks(cpu):
    """Two transitions is a blink; one is a pin that came on and stayed on."""
    load(cpu)
    transitions = run_and_watch(cpu)
    assert len(transitions) >= 2, f"PB5 changed state {len(transitions)} times"


def test_the_blink_alternates_rather_than_only_rising(cpu):
    load(cpu)
    states = [state for _, state in run_and_watch(cpu)]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_delay_loop_actually_delays(cpu):
    """**The assertion that caught the branch-polarity bug.** With `brbc` and
    `brbs` swapped the blink still ran its full budget and still alternated —
    it simply toggled every 10 instructions instead of every 1,110, because
    the delay loop took its exit branch on the first comparison.

    A counted `for` to 100 cannot cost ten instructions, so the floor is what
    makes the wrong answer visible; the exact figure is left to the period test
    below."""
    load(cpu)
    steps = [step for step, _ in run_and_watch(cpu)]
    periods = [b - a for a, b in itertools.pairwise(steps[1:])]
    assert periods, "not enough toggles to measure a period"
    assert min(periods) > 500, (
        f"a toggle every {min(periods)} instructions is too fast for a loop "
        f"counting to 100; the delay is being skipped"
    )


def test_the_blink_has_a_steady_period(cpu):
    """The delay is a counted `for`, so the interval between toggles must be
    constant. A wandering period would mean the loop counter is wrong."""
    load(cpu)
    steps = [step for step, _ in run_and_watch(cpu)]
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"


# --- the rule the blink cannot reach ------------------------------------------


def test_a_sixteen_bit_compare_reports_inequality(cpu):
    """`cpc` may only ever CLEAR Z; it never sets it.

    That is what makes a multi-byte compare work: `cpi` on the low byte then
    `cpc` on the high leaves Z set only if *both* were equal. A model that
    assigned Z from its own result would report equality whenever the high
    bytes matched, whatever the low ones did.

    **Written as its own test because the blink cannot catch it.** That image
    branches on C after its `cpc` and never on Z, so mutation testing found
    the rule could be deleted with all sixteen tests still passing. The
    behaviour is correct AVR and a future counted loop will need it, so it is
    pinned here rather than removed as unexercised.

    256 against 100 is the discriminating case: the low bytes differ, the
    subtraction of the high bytes lands on zero, and only the carried-in Z
    distinguishes "not equal" from "equal".
    """
    cpu.write_program(0, 0x3684)      # cpi r24, 0x64
    cpu.write_program(1, 0x0591)      # cpc r25, r1
    cpu.set_reg(24, 0x00)             # r25:r24 = 0x0100 = 256
    cpu.set_reg(25, 0x01)
    cpu.set_reg(1, 0x00)              # r1 is __zero_reg__
    cpu.pc = 0

    cpu.step()
    assert not cpu.flag("Z"), "the low bytes differ, so this compare is not equal"
    cpu.step()
    assert not cpu.flag("Z"), (
        "256 and 100 are not equal, but Z ended set -- cpc assigned Z from its "
        "own zero result instead of carrying the previous one in"
    )


def test_a_sixteen_bit_compare_reports_equality(cpu):
    """The other half. A `cpc` that only ever cleared Z, whatever happened,
    would pass the test above and never report a match."""
    cpu.write_program(0, 0x3684)      # cpi r24, 0x64
    cpu.write_program(1, 0x0591)      # cpc r25, r1
    cpu.set_reg(24, 0x64)             # r25:r24 = 100
    cpu.set_reg(25, 0x00)
    cpu.set_reg(1, 0x00)
    cpu.pc = 0

    cpu.step()
    cpu.step()
    assert cpu.flag("Z"), "100 equals 100"


# --- the loud failures --------------------------------------------------------


def test_an_unimplemented_encoding_leaves_the_machine_untouched(cpu):
    """It matters more here than on Arm. A core that skipped an unknown word
    would resume decoding from the middle of the next instruction, and on a
    variable-length encoding that is not a fault — it is a different program
    that runs to completion.

    **The example is 0xFFFF and that is not an arbitrary choice.** This test
    used to use `lpm` (0x95C8), which OH-58 implemented — and then it failed,
    because its example had come from live data and was on a countdown, the
    same shape `tests/webui/test_board_run.py` was caught by. 0xFFFF cannot go
    the same way: it is the erased flash word, `core/avr/cpu.cc` fills program
    memory with it for exactly this reason, and it is not an AVR instruction —
    `sbrs` is the nearest encoding and it needs bit 3 clear. Nothing can
    implement it, so nothing will.
    """
    from core.avr.abi import Unimplemented

    cpu.write_program(0, 0xFFFF)
    cpu.pc = 0
    with pytest.raises(Unimplemented) as caught:
        cpu.step()
    assert cpu.pc == 0, "the PC moved past an instruction that did not execute"
    assert "0xffff" in str(caught.value)


def test_running_off_the_end_of_program_memory_faults(cpu):
    from core.avr.abi import MemoryFault

    cpu.pc = cpu.program_words
    with pytest.raises(MemoryFault):
        cpu.step()


def test_an_odd_length_image_is_refused_rather_than_rounded(cpu):
    """Program memory is words. Half a word is a question about what the other
    half holds, and the caller has to answer it."""
    from core.avr.abi import AbiError

    with pytest.raises(AbiError):
        cpu.write_program_block(0, b"\x01\x02\x03")


def test_an_image_that_does_not_fit_loads_none_of_itself(cpu):
    """Checked whole before anything is written, so an overrun leaves flash
    untouched rather than half-loaded — the failure that reports an error and
    has already changed state."""
    from core.avr.abi import MemoryFault

    with pytest.raises(MemoryFault):
        cpu.write_program_block(cpu.program_words - 1, b"\x01\x02\x03\x04")
    assert cpu.read_program(cpu.program_words - 1) == 0xFFFF


# --- the committed binary -----------------------------------------------------


def test_the_committed_binary_matches_its_source(cpu):
    """`blink.bin` is 46 bytes and committed, so this suite runs on a machine
    with no AVR toolchain rather than skipping. That invites drift, so wherever
    a compiler exists the binary is rebuilt and compared."""
    import os

    found = shutil.which("avr-gcc")
    gcc = pathlib.Path(found) if found else pathlib.Path(
        os.environ.get("USERPROFILE", pathlib.Path.home()),
        ".platformio/packages/toolchain-atmelavr/bin/avr-gcc.exe",
    )
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    if not gcc.is_file():
        pytest.skip(f"no avr-gcc on PATH or at {gcc}")

    with tempfile.TemporaryDirectory() as tmp:
        elf = pathlib.Path(tmp) / "blink.elf"
        binary = pathlib.Path(tmp) / "blink.bin"
        subprocess.run(
            [str(gcc), "-mmcu=atmega328p", "-Os", "-ffreestanding", "-nostdlib",
             "-nostartfiles", "-o", str(elf), str(HERE / "blink.c")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [str(objcopy), "-O", "binary", str(elf), str(binary)],
            check=True, capture_output=True,
        )
        assert binary.read_bytes() == IMAGE.read_bytes(), (
            "blink.bin does not match what blink.c compiles to. Rebuild it:\n"
            "  avr-gcc -mmcu=atmega328p -Os -ffreestanding -nostdlib "
            "-nostartfiles -o blink.elf blink.c\n"
            "  avr-objcopy -O binary blink.elf blink.bin"
        )
