# OpenHardware - the shift, rotate, muldiv, string, BCD and IO groups.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for core/i8086/shift.cc and its dispatch, per ticket OH-4.

The corpus is the real check here -- 240,000 hardware cases across the 32
files of the shift group, run by `test_the_fetched_corpus_passes_completely`
in test_conformance.py. What these tests add is a *named* record of the
handful of facts that were hard to establish, so a later change that breaks
one of them fails with a sentence rather than with "D2.4: 2610/5000".

Three of those facts are not in the Intel manual at all:

* `/6` is SETMO, an undocumented instruction that sets the destination to all
  ones. The manual lists `/4` twice (SHL and SAL) and omits `/6` entirely.
* SHL sets AF; SHR and SAR clear it. All three are documented undefined.
* The count is not masked to five bits. Later parts mask it, and every
  emulator written from a 286-era manual masks it too.
"""

from core.i8086 import abi

CF, PF, AF, ZF, SF, OF = 0x0001, 0x0004, 0x0010, 0x0040, 0x0080, 0x0800

#: modrm reg values for the D0-D3 group, in encoding order.
ROL, ROR, RCL, RCR, SHL, SHR, SETMO, SAR = range(8)


def shift_bl(cpu, operation: int, value: int, flags: int = 0, count: int | None = None):
    """`D0 /op BL` (count 1), or `D2 /op BL, CL` when a count is given.

    Returns (BL, flags). BL is rm=011 at either width, and mod=3 keeps the
    operand in a register so nothing here depends on the addressing table.
    """
    opcode = 0xD0 if count is None else 0xD2
    modrm = 0xC0 | (operation << 3) | 0x03
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=value & 0xFF,
                 cx=0 if count is None else count, flags=flags)
    cpu.write_block(0x00000, bytes([opcode, modrm]))
    cpu.step()
    return cpu.regs.bx & 0xFF, cpu.regs.flags


# --- a count of zero is not a shift by zero ------------------------------------


def test_a_zero_count_changes_no_flag_at_all(cpu):
    """`D2 /4` with CL=0 must leave every flag as it was.

    A core that computes flags from the unshifted value gets the right answer
    for ZF, SF and PF and the wrong one for CF -- it clears a carry the
    hardware preserved. 162 corpus cases land here per file.
    """
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=0x00FF, cx=0x0000, flags=CF | AF | OF)
    cpu.write_block(0x00000, bytes([0xD2, 0xC0 | (SHL << 3) | 0x03]))
    before = cpu.regs.flags
    cpu.step()
    assert cpu.regs.flags == before
    assert cpu.regs.bx & 0xFF == 0xFF


# --- SHL -----------------------------------------------------------------------


def test_shl_doubles_and_carries_the_top_bit_out(cpu):
    result, flags = shift_bl(cpu, SHL, 0x81)
    assert result == 0x02
    assert flags & CF


def test_shl_sets_the_auxiliary_carry_from_bit_four_of_the_result(cpu):
    """Documented undefined; measured set in ~50% of 10,000 D0.4 cases.

    SHL is ADD dest,dest, so it produces ADD's AF -- the carry out of bit 3,
    which for equal operands is just bit 4 of the result.
    """
    _, flags = shift_bl(cpu, SHL, 0x08)   # 0x08 << 1 == 0x10, bit 4 set
    assert flags & AF


def test_shl_clears_the_auxiliary_carry_when_bit_four_is_clear(cpu):
    _, flags = shift_bl(cpu, SHL, 0x04, flags=AF)   # 0x04 << 1 == 0x08
    assert not flags & AF


# --- SHR and SAR ---------------------------------------------------------------


def test_shr_shifts_a_zero_in_and_carries_the_low_bit_out(cpu):
    result, flags = shift_bl(cpu, SHR, 0x81)
    assert result == 0x40
    assert flags & CF


def test_shr_clears_the_auxiliary_carry(cpu):
    """Documented undefined; measured clear in all 10,000 D0.5 cases."""
    _, flags = shift_bl(cpu, SHR, 0xFF, flags=AF)
    assert not flags & AF


def test_sar_preserves_the_sign_bit(cpu):
    result, _ = shift_bl(cpu, SAR, 0x80)
    assert result == 0xC0


def test_sar_clears_the_auxiliary_carry(cpu):
    """Documented undefined; measured clear in all 10,000 D0.7 cases."""
    _, flags = shift_bl(cpu, SAR, 0xFF, flags=AF)
    assert not flags & AF


def test_sar_never_overflows(cpu):
    _, flags = shift_bl(cpu, SAR, 0x80, flags=OF)
    assert not flags & OF


# --- the rotates ---------------------------------------------------------------


def test_rol_brings_the_top_bit_round_to_the_bottom(cpu):
    result, flags = shift_bl(cpu, ROL, 0x81)
    assert result == 0x03
    assert flags & CF


def test_ror_brings_the_bottom_bit_round_to_the_top(cpu):
    result, flags = shift_bl(cpu, ROR, 0x81)
    assert result == 0xC0
    assert flags & CF


def test_a_rotate_leaves_zero_sign_and_parity_alone(cpu):
    """The rotates set only CF and OF. A core that runs them through the same
    result-flag path as the shifts clears ZF here, and nothing else notices
    until a conditional jump after a rotate goes the wrong way."""
    _, flags = shift_bl(cpu, ROL, 0x01, flags=ZF | SF | PF)
    assert flags & ZF and flags & SF and flags & PF


def test_rcl_rotates_through_carry_with_a_nine_bit_period(cpu):
    """A byte RCL is a 9-bit rotate, not an 8-bit one: the carry is part of
    the register. Nine iterations must return the value untouched."""
    result, flags = shift_bl(cpu, RCL, 0xA5, flags=0, count=9)
    assert result == 0xA5
    assert not flags & CF


def test_rcr_rotates_through_carry_with_a_nine_bit_period(cpu):
    result, flags = shift_bl(cpu, RCR, 0xA5, flags=0, count=9)
    assert result == 0xA5
    assert not flags & CF


# --- the count is not masked ------------------------------------------------------


def test_the_shift_count_is_not_masked_to_five_bits(cpu):
    """The 8086 does not mask; the 186 and later do.

    RCL is the only member that can tell the difference, because its period is
    9 rather than 8: CL=62 is 62 mod 9 == 8 rotations, and a core masking to
    five bits does 30 mod 9 == 3 instead. Every other member gives the same
    answer either way, which is why a core with this bug still passes SHL,
    SHR, SAR, ROL and ROR.

    The corpus reaches CL=62, so this is measured rather than argued.
    """
    result, flags = shift_bl(cpu, RCL, 0xA5, flags=0, count=62)
    assert (result, bool(flags & CF)) == (0x52, True), "0x2A would mean a 5-bit mask"


# --- SETMO, which the manual does not list ------------------------------------------


def test_setmo_sets_the_destination_to_all_ones(cpu):
    """`/6` is SETMO. The Intel manual lists `/4` as both SHL and SAL and says
    nothing about `/6`; the corpus names it and has 30,000 cases of it."""
    result, _ = shift_bl(cpu, SETMO, 0x00)
    assert result == 0xFF


def test_setmo_ignores_what_the_destination_held(cpu):
    result, _ = shift_bl(cpu, SETMO, 0x5A)
    assert result == 0xFF


def test_setmo_sets_sign_and_parity_from_the_result(cpu):
    _, flags = shift_bl(cpu, SETMO, 0x00)
    assert flags & SF and flags & PF
    assert not flags & ZF
    assert not (flags & CF or flags & OF or flags & AF)


def test_setmoc_does_nothing_when_cl_is_zero(cpu):
    """The CL-counted form is conditional -- the corpus calls it `setmoc`."""
    result, flags = shift_bl(cpu, SETMO, 0x5A, flags=CF, count=0)
    assert result == 0x5A
    assert flags & CF


# --- width and memory ----------------------------------------------------------------


def test_the_word_form_shifts_all_sixteen_bits(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=0x8001, flags=0)
    cpu.write_block(0x00000, bytes([0xD1, 0xC0 | (SHL << 3) | 0x03]))
    cpu.step()
    assert cpu.regs.bx == 0x0002
    assert cpu.regs.flags & CF


def test_a_shift_writes_through_to_memory(cpu):
    """mod=00 rm=111 is [BX], so this proves the group routes a memory operand
    the same way the ALU group does."""
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=0x0200, ds=0x0000, flags=0)
    cpu.write_block(0x00000, bytes([0xD0, (SHL << 3) | 0x07]))
    cpu.write_byte(0x00200, 0x41)
    cpu.step()
    assert cpu.read_byte(0x00200) == 0x82


def test_every_member_of_the_group_is_implemented(cpu):
    """All eight, at all four opcodes. A gap here decodes at the right length
    and then refuses, which reads as a core bug rather than a missing entry."""
    missing = []
    for opcode in (0xD0, 0xD1, 0xD2, 0xD3):
        for operation in range(8):
            cpu.set_regs(cs=0x0000, ip=0x0000, bx=0x0001, cx=0x0001, flags=0)
            cpu.write_block(0x00000, bytes([opcode, 0xC0 | (operation << 3) | 0x03]))
            try:
                cpu.step()
            except abi.Unimplemented:
                missing.append(f"{opcode:02X} /{operation}")
    assert not missing, f"unimplemented: {missing}"


def test_the_opcode_table_claims_the_whole_shift_group(library):
    unclaimed = [f"{op:02X}" for op in (0xD0, 0xD1, 0xD2, 0xD3)
                 if not abi.opcode_info(op)[0]]
    assert not unclaimed


def test_the_shift_group_takes_a_modrm_byte_at_both_widths(library):
    assert all(abi.opcode_info(op)[1] for op in (0xD0, 0xD1, 0xD2, 0xD3))
    widths = [abi.opcode_is_wide(op) for op in (0xD0, 0xD1, 0xD2, 0xD3)]
    assert widths == [False, True, False, True]


# ======================================================================================
# Port I/O
#
# These are the weakest tests in the file, and deliberately labelled as such.
# The machine the corpus was captured on had nothing attached to its I/O bus,
# so all 40,000 IN cases read 0xFF and all 40,000 OUT cases are invisible.
# A core that models ports properly and one that returns a constant score
# identically. What is actually pinned here is the *decode* -- lengths, widths,
# and which half of AX moves -- which the corpus does check.
# ======================================================================================


def run_bytes(cpu, code: bytes, **regs):
    """Execute one instruction at 0000:0000 with the given registers."""
    cpu.set_regs(cs=0x0000, ip=0x0000, **regs)
    cpu.write_block(0x00000, code)
    cpu.step()


def test_in_from_an_immediate_port_reads_the_open_bus(cpu):
    run_bytes(cpu, bytes([0xE4, 0x1B]), ax=0x9960)   # in al, 1Bh
    assert cpu.regs.ax & 0xFF == 0xFF


def test_in_leaves_the_high_half_of_ax_alone(cpu):
    """The byte form writes AL only. A core that assigns AX wholesale passes
    every conformance case where AH happened to be 0xFF and no other."""
    run_bytes(cpu, bytes([0xE4, 0x1B]), ax=0x9960)
    assert cpu.regs.ax == 0x99FF


def test_the_word_form_of_in_fills_all_of_ax(cpu):
    run_bytes(cpu, bytes([0xE5, 0x1B]), ax=0x0000)
    assert cpu.regs.ax == 0xFFFF


def test_in_from_dx_reads_the_open_bus_too(cpu):
    run_bytes(cpu, bytes([0xEC]), ax=0x1234, dx=0x03F8)
    assert cpu.regs.ax == 0x12FF


def test_an_immediate_port_is_two_bytes_and_a_dx_port_is_one(cpu):
    """`E4 FF` must be port 255, not a one-byte instruction followed by a
    stray FF. Getting the form wrong desynchronises everything after it."""
    cpu.set_regs(cs=0x0000, ip=0x0000)
    cpu.write_block(0x00000, bytes([0xE4, 0xFF]))
    assert cpu.decode().length == 2
    cpu.write_block(0x00000, bytes([0xEC]))
    assert cpu.decode().length == 1


def test_out_changes_nothing_but_ip(cpu):
    """Nothing is attached, so OUT is observable only in that it ran. It must
    still not be refused -- an unimplemented opcode leaves IP where it was."""
    cpu.set_regs(cs=0x0000, ip=0x0000, ax=0x1234, dx=0x03F8, flags=0)
    cpu.write_block(0x00000, bytes([0xEE]))
    before = cpu.regs.as_dict()
    cpu.step()
    after = cpu.regs.as_dict()
    assert after["ip"] == 1
    del before["ip"], after["ip"]
    assert before == after


# --- the single-byte flag instructions -------------------------------------------


def test_clc_clears_carry_and_stc_sets_it(cpu):
    run_bytes(cpu, bytes([0xF8]), flags=CF)
    assert not cpu.regs.flags & CF
    run_bytes(cpu, bytes([0xF9]), flags=0)
    assert cpu.regs.flags & CF


def test_cmc_complements_carry_in_both_directions(cpu):
    run_bytes(cpu, bytes([0xF5]), flags=0)
    assert cpu.regs.flags & CF
    run_bytes(cpu, bytes([0xF5]), flags=CF)
    assert not cpu.regs.flags & CF


def test_cld_clears_direction_and_std_sets_it(cpu):
    """DF is what makes the string operations count downwards."""
    run_bytes(cpu, bytes([0xFC]), flags=0x0400)
    assert not cpu.regs.flags & 0x0400
    run_bytes(cpu, bytes([0xFD]), flags=0)
    assert cpu.regs.flags & 0x0400


def test_cli_clears_the_interrupt_flag_and_sti_sets_it(cpu):
    run_bytes(cpu, bytes([0xFA]), flags=0x0200)
    assert not cpu.regs.flags & 0x0200
    run_bytes(cpu, bytes([0xFB]), flags=0)
    assert cpu.regs.flags & 0x0200


def test_a_flag_instruction_touches_only_its_own_bit(cpu):
    """CLC must not disturb ZF, SF, PF, AF, OF, DF or IF. A core reaching for
    a whole-flags assignment gets this wrong and nothing else notices."""
    everything = CF | PF | AF | ZF | SF | OF | 0x0200 | 0x0400
    run_bytes(cpu, bytes([0xF8]), flags=everything)
    assert cpu.regs.flags & (everything & ~CF) == (everything & ~CF)
    assert not cpu.regs.flags & CF
