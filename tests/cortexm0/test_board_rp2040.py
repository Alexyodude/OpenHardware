# OpenHardware — the RP2040's registers over the Cortex-M0+ core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The core knows no addresses and this file is where the addresses are tested.
# Register facts come from `docs/research/peripheral-layer/rp2040_v2/`, which
# cites the datasheet and pico-sdk for each one.
#
# Measured effect of installing these: a real Arduino blink image runs 225,755
# instructions standalone, up from 225,723 and past the RESETS atomic-SET alias
# that used to stop it.

import pytest

from core.cortexm0.abi import AbiError, MemoryFault
from webui.boards import rp2040


@pytest.fixture
def board(cpu):
    """A whole RP2040, replacing the bare SRAM the conftest fixture installs.

    `clear_regions` first is not tidiness: the conftest gives every test a flat
    SRAM at 0x20000000 for the instruction suites, and the board adds its own
    there too. Overlapping regions are refused now, and before they were
    refused this silently allocated a second buffer nothing could read.
    """
    cpu.clear_memory()
    cpu.clear_regions()
    rp2040.install(cpu)
    return cpu


# --- the atomic aliases ----------------------------------------------------


def test_the_set_alias_sets_only_the_bits_written(board):
    """Datasheet §2.1.2: +0x2000 is SET. The point of it is that a driver can
    change one bit without a read-modify-write an interrupt can tear."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0b0100)
    board.write_word(target + rp2040.ALIAS_SET, 0b0001)
    assert board.read_word(target) == 0b0101


def test_the_clear_alias_clears_only_the_bits_written(board):
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0b1111)
    board.write_word(target + rp2040.ALIAS_CLR, 0b0110)
    assert board.read_word(target) == 0b1001


def test_the_xor_alias_toggles_the_bits_written(board):
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0b1010)
    board.write_word(target + rp2040.ALIAS_XOR, 0b0110)
    assert board.read_word(target) == 0b1100


def test_the_normal_window_still_writes_the_whole_word(board):
    """The base window is a plain store. A model that made every write a SET
    would pass the three tests above and never let a driver clear anything."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0xFFFF)
    board.write_word(target, 0x0001)
    assert board.read_word(target) == 0x0001


def test_an_alias_reads_back_its_target_rather_than_what_was_written(board):
    """Reading an alias window gives the register's value, not the last mask
    sent through it. The alias is a view, not a register of its own."""
    target = rp2040.RESETS + rp2040.RESETS_WDSEL
    board.write_word(target, 0b1000)
    board.write_word(target + rp2040.ALIAS_SET, 0b0001)
    assert board.read_word(target + rp2040.ALIAS_SET) == 0b1001


def test_the_alias_of_a_register_follows_that_registers_offset(board):
    """The SET view of `base + 0x08` is `base + 0x2008`, not `base + 0x2000`.
    Aliasing the peripheral rather than the register puts every register's
    alias on top of the first one."""
    reset = rp2040.RESETS + rp2040.RESETS_RESET
    wdsel = rp2040.RESETS + rp2040.RESETS_WDSEL
    assert board.is_mapped(reset + rp2040.ALIAS_SET)
    assert board.is_mapped(wdsel + rp2040.ALIAS_SET)
    assert reset + rp2040.ALIAS_SET != wdsel + rp2040.ALIAS_SET


# --- RESET_DONE, the register a driver spins on ----------------------------


def test_every_block_comes_up_held_in_reset(board):
    """All 25 resettable blocks are in reset at power-on. Coming up as zero
    would let firmware skip the unreset it is about to wait on."""
    assert board.read_word(rp2040.RESETS + rp2040.RESETS_RESET) == 0x01FFFFFF


def test_reset_done_is_the_inverse_of_reset(board):
    """`unreset_block_num_wait_blocking()` clears a bit in RESET then loops
    until it appears in RESET_DONE. If RESET_DONE were a stored register
    nothing would ever update it and the loop would spin forever -- a hang
    indistinguishable from a bad instruction."""
    reset = rp2040.RESETS + rp2040.RESETS_RESET
    done = rp2040.RESETS + rp2040.RESETS_RESET_DONE
    assert board.read_word(done) == 0
    board.write_word(reset + rp2040.ALIAS_CLR, 1 << 5)      # unreset IO_BANK0
    assert board.read_word(done) == (1 << 5)
    assert board.read_word(reset) == 0x01FFFFFF & ~(1 << 5)


def test_reset_done_reserved_bits_read_zero(board):
    """Bits 25-31 are reserved. Inverting a 25-bit register without masking
    puts 0xFE000000 in the top of every read."""
    board.write_word(rp2040.RESETS + rp2040.RESETS_RESET, 0)
    assert board.read_word(rp2040.RESETS + rp2040.RESETS_RESET_DONE) == 0x01FFFFFF


def test_writing_to_reset_done_is_ignored_rather_than_stored(board):
    """It is read-only on the part. Storing the write would decouple it from
    RESET and the spin loop would stop terminating."""
    done = rp2040.RESETS + rp2040.RESETS_RESET_DONE
    board.write_word(done, 0xFFFFFFFF)
    assert board.read_word(done) == 0


# --- the rule the whole design rests on ------------------------------------


def test_an_unmodelled_register_inside_a_modelled_peripheral_still_faults(board):
    """Registering one register must not open the whole 4 KB window. A
    peripheral that read as zero everywhere turns every wait-for-ready poll
    into a silent infinite loop."""
    with pytest.raises(MemoryFault):
        board.read_word(rp2040.RESETS + 0x0C)


def test_a_peripheral_this_board_does_not_model_still_faults(board):
    """CLOCKS at 0x40008000 is real and not modelled here. It must say so."""
    with pytest.raises(MemoryFault):
        board.read_word(0x40008000)


# --- SIO -------------------------------------------------------------------


def test_sio_has_no_bus_level_atomic_aliases(board):
    """SIO is the chip's only peripheral without them -- datasheet §2.1.2,
    quoted in rp2040_v2/rp2040.json. Its GPIO registers carry their own
    dedicated SET/CLR/XOR registers instead, which is a different mechanism.
    Applying the +0x1000 windows here would invent registers the part lacks."""
    assert not board.is_mapped(rp2040.SIO + rp2040.SIO_GPIO_OUT + rp2040.ALIAS_SET)
    assert board.is_mapped(rp2040.SIO + rp2040.SIO_GPIO_OUT_SET)


def test_cpuid_reads_zero_for_core_zero(board):
    """The first peripheral access a Pico image makes: the runtime reads it to
    tell the two cores apart."""
    assert board.read_word(rp2040.SIO + rp2040.SIO_CPUID) == 0


def test_gpio_out_set_and_clr_drive_individual_pins(board):
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    board.write_word(rp2040.SIO + rp2040.SIO_GPIO_OUT_SET, 1 << 25)
    assert board.read_word(out) == (1 << 25)
    board.write_word(rp2040.SIO + rp2040.SIO_GPIO_OUT_CLR, 1 << 25)
    assert board.read_word(out) == 0


def test_gpio_out_xor_is_how_a_blink_toggles(board):
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    xor = rp2040.SIO + rp2040.SIO_GPIO_OUT_XOR
    board.write_word(xor, 1 << 25)
    assert board.read_word(out) == (1 << 25)
    board.write_word(xor, 1 << 25)
    assert board.read_word(out) == 0


def test_output_enable_is_a_separate_register_from_output_value(board):
    """Driving a pin needs both. A model that conflated them would show a
    blink on a pin still configured as an input."""
    board.write_word(rp2040.SIO + rp2040.SIO_GPIO_OE_SET, 1 << 25)
    assert board.read_word(rp2040.SIO + rp2040.SIO_GPIO_OE) == (1 << 25)
    assert board.read_word(rp2040.SIO + rp2040.SIO_GPIO_OUT) == 0


# --- the boot ROM stub -----------------------------------------------------


def test_the_bootrom_answers_data_reads_with_zero(board):
    """Firmware reads a function table here, and the oracle answers zero too:
    rp2040js leaves its bootrom array zeroed unless `loadBootrom()` is called.
    Faulting on the read would diverge from the model the core is compared
    against, for no gain."""
    assert board.read_word(rp2040.BOOTROM + 0x14) == 0


def test_executing_the_bootrom_stub_faults_rather_than_running_zeros(board):
    """The half that earns the non-executable flag.

    A zero halfword decodes as `MOVS r0, r0`, so a jump into a zeroed ROM runs
    quietly off the end of it looking like progress. Measured on the real
    Arduino image: `rom_func_lookup` returns 0 and the firmware calls it, so
    this is the path a real program actually takes.
    """
    board.set_regs([0] * 15 + [rp2040.BOOTROM], apsr=0)
    with pytest.raises(MemoryFault):
        board.step()


def test_the_bootrom_fault_names_the_faulting_address_not_just_any_address(board):
    """The message carries two addresses -- what faulted, and the instruction
    that did it -- and a substring check cannot tell them apart.

    `BOOTROM` is 0, so asserting `"0x00000000" in message` passed even when the
    *faulting* address was reported wrongly, because the "(instruction at
    0x00000000)" half satisfied it. Both halves are checked separately now, and
    against an address that is not zero, so neither can stand in for the other.
    """
    probe = rp2040.BOOTROM + 0x200
    board.set_regs([0] * 15 + [probe], apsr=0)
    with pytest.raises(MemoryFault) as caught:
        board.step()
    message = str(caught.value)
    assert message.startswith(f"fetch at 0x{probe:08x}")
    # And it says *why*: the boot ROM exists, so "outside the modelled memory"
    # would send the reader looking for a missing region that is right there.
    assert "not executable" in message
    assert f"(instruction at 0x{probe:08x})" in message


def test_flash_stays_executable_while_the_stub_does_not(board):
    """The flag is per-region, so marking one non-executable must not make
    everything non-executable."""
    board.write_halfword(0x10000200, 0x2042)          # MOVS r0, #0x42
    board.set_regs([0] * 15 + [0x10000200], apsr=0)
    board.step()
    assert board.get_regs().r[0] == 0x42


# --- the mapping API itself ------------------------------------------------


def test_an_unknown_write_op_is_refused_by_name(cpu):
    """Ops are spelled, not numbered: a bare 2 at a call site is unreadable
    and the difference between clear and xor is a silent wrong answer."""
    with pytest.raises(AbiError):
        cpu.map_alias(0x40000000, 0x40001000, "toggle")
