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


# ======================================================================================
# The decimal and ASCII adjusts
# ======================================================================================


def test_daa_corrects_a_low_digit(cpu):
    """0x0F is 15, which is not a decimal digit: add 6 to carry it."""
    run_bytes(cpu, bytes([0x27]), ax=0x000F, flags=0)
    assert cpu.regs.ax & 0xFF == 0x15


def test_daa_corrects_both_digits_and_carries(cpu):
    run_bytes(cpu, bytes([0x27]), ax=0x009B, flags=0)
    assert cpu.regs.ax & 0xFF == 0x01
    assert cpu.regs.flags & CF


def test_the_high_correction_threshold_rises_to_9f_when_af_arrives_set(cpu):
    """The one fact in this family that no published algorithm has.

    With AF clear, AL=0x9E takes both corrections: 0x9E + 0x66 = 0x04, carry
    out. With AF *already set* it takes only the low one: 0x9E + 6 = 0xA4, no
    carry. The Intel algorithm has no AF term in its second test and gets one
    of these two wrong whichever threshold it is written with.

    Derived by recovering `final AL - initial AL` from all 10,000 DAA cases
    and tabulating it against AL's high nibble and AF. 64 cases distinguish
    the two, which is 0.64% -- small enough to look like noise in a summary
    and quite large enough to be a bug.
    """
    run_bytes(cpu, bytes([0x27]), ax=0x009E, flags=0)
    assert (cpu.regs.ax & 0xFF, bool(cpu.regs.flags & CF)) == (0x04, True)

    run_bytes(cpu, bytes([0x27]), ax=0x009E, flags=AF)
    assert (cpu.regs.ax & 0xFF, bool(cpu.regs.flags & CF)) == (0xA4, False)


def test_das_uses_the_same_threshold_as_daa(cpu):
    """The two correction tables are byte-identical; only the sign differs."""
    run_bytes(cpu, bytes([0x2F]), ax=0x009E, flags=0)
    assert cpu.regs.ax & 0xFF == 0x38          # 0x9E - 0x66
    run_bytes(cpu, bytes([0x2F]), ax=0x009E, flags=AF)
    assert cpu.regs.ax & 0xFF == 0x98          # 0x9E - 6


def test_das_carry_is_which_correction_ran_not_a_borrow(cpu):
    """The manual says CF is the incoming carry OR a borrow out of the low
    correction. It is not: it is exactly whether the high correction ran.
    AL=0x01 with AF set borrows out of 0x01-6 and still leaves CF clear."""
    run_bytes(cpu, bytes([0x2F]), ax=0x0001, flags=AF)
    assert cpu.regs.ax & 0xFF == 0xFB
    assert not cpu.regs.flags & CF


def test_daa_leaves_the_high_half_of_ax_alone(cpu):
    run_bytes(cpu, bytes([0x27]), ax=0x5A0F, flags=0)
    assert cpu.regs.ax >> 8 == 0x5A


# --- AAA and AAS ------------------------------------------------------------------


def test_aaa_carries_the_tens_digit_into_ah(cpu):
    run_bytes(cpu, bytes([0x37]), ax=0x000B, flags=0)
    assert cpu.regs.ax == 0x0101
    assert cpu.regs.flags & CF and cpu.regs.flags & AF


def test_aas_borrows_the_tens_digit_from_ah(cpu):
    run_bytes(cpu, bytes([0x3F]), ax=0x020B, flags=0)
    assert cpu.regs.ax == 0x0105
    assert cpu.regs.flags & CF and cpu.regs.flags & AF


def test_aaa_masks_al_to_one_digit_even_with_nothing_to_correct(cpu):
    run_bytes(cpu, bytes([0x37]), ax=0x0005, flags=0)
    assert cpu.regs.ax == 0x0005
    assert not cpu.regs.flags & CF


def test_the_sign_flag_comes_from_before_the_mask(cpu):
    """AAA runs the ALU whether or not a correction is due, and the flags are
    that operation's -- taken before AL is masked to its low digit.

    AL=0x85 needs no correction, so the operation is `0x85 + 0`, which is
    negative. AL is then stored as 0x05. A core that computes flags from the
    stored value reports SF clear and loses 94% of this opcode: the corpus
    scores 6.15% for exactly this mistake.
    """
    run_bytes(cpu, bytes([0x37]), ax=0x0085, flags=0)
    assert cpu.regs.ax & 0xFF == 0x05
    assert cpu.regs.flags & SF


# --- AAM and AAD ---------------------------------------------------------------------


def test_aam_splits_al_into_two_digits(cpu):
    run_bytes(cpu, bytes([0xD4, 0x0A]), ax=0x004D, flags=0)   # 77 -> 7, 7
    assert cpu.regs.ax == 0x0707


def test_aam_takes_the_divisor_from_the_operand_not_from_ten(cpu):
    """`D4 0A` is the assembler's default and the only form most code uses;
    the opcode takes any byte, and the corpus exercises all of them."""
    run_bytes(cpu, bytes([0xD4, 0x10]), ax=0x00FF, flags=0)   # 255 = 15*16 + 15
    assert cpu.regs.ax == 0x0F0F


def test_aad_combines_two_digits_into_al(cpu):
    run_bytes(cpu, bytes([0xD5, 0x0A]), ax=0x0307, flags=0)   # 3*10 + 7
    assert cpu.regs.ax == 0x0025


def test_aad_sets_the_flags_its_final_addition_produces(cpu):
    """CF, AF and OF are all documented undefined and all three are simply
    the last ADD's. 0x80 + 0x80 overflows, carries, and comes out zero."""
    run_bytes(cpu, bytes([0xD5, 0x02]), ax=0x4080, flags=0)   # 0x40*2 = 0x80, + 0x80
    assert cpu.regs.ax == 0x0000
    assert cpu.regs.flags & CF and cpu.regs.flags & OF and cpu.regs.flags & ZF


def test_aad_does_not_trap_on_a_zero_operand(cpu):
    """AAM divides and AAM traps; AAD multiplies, and multiplying by zero is
    an answer. Treating the pair symmetrically is the obvious mistake."""
    run_bytes(cpu, bytes([0xD5, 0x00]), ax=0x1234, flags=0)
    assert cpu.regs.ax == 0x0034
    assert cpu.regs.ip == 2


# --- the divide error, which is the first interrupt this core takes ------------------


def set_up_vector_zero(cpu, handler_cs: int, handler_ip: int) -> None:
    """Point interrupt 0 at a handler and give the processor a stack."""
    cpu.write_word(0x00000, handler_ip)
    cpu.write_word(0x00002, handler_cs)


def test_aam_by_zero_jumps_through_vector_zero(cpu):
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0xE837, flags=0)
    cpu.write_block(0x00100, bytes([0xD4, 0x00]))
    cpu.step()
    assert (cpu.regs.cs, cpu.regs.ip) == (0xB000, 0x1234)


def test_the_divide_error_pushes_the_address_after_the_instruction(cpu):
    """Not the faulting address. Measured: `D4 00` at IP 0x8573 pushes 0x8575.

    Later x86 parts push the faulting address so a handler can fix up and
    retry; an 8086 cannot, and was never meant to.
    """
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x7983, ip=0x0100, ss=0x0000, sp=0x0200, ax=0xE837, flags=0)
    cpu.write_block(0x79930, bytes([0xD4, 0x00]))   # 7983:0100
    cpu.step()
    assert cpu.regs.sp == 0x01FA
    assert cpu.read_word(0x001FA) == 0x0102        # IP after the instruction
    assert cpu.read_word(0x001FC) == 0x7983        # CS


def test_the_divide_error_pushes_the_flags_the_instruction_computed(cpu):
    """AAM sets flags from a zero result *before* it traps, and it is that
    word which reaches the stack -- not the one the instruction started with."""
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0xE837,
                 flags=CF | AF | SF | OF)
    cpu.write_block(0x00100, bytes([0xD4, 0x00]))
    cpu.step()
    pushed = cpu.read_word(0x001FE)
    assert not pushed & (CF | AF | SF | OF)
    assert pushed & ZF and pushed & PF


def test_the_divide_error_leaves_ax_untouched(cpu):
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0xE837, flags=0)
    cpu.write_block(0x00100, bytes([0xD4, 0x00]))
    cpu.step()
    assert cpu.regs.ax == 0xE837


# ======================================================================================
# The string instructions
# ======================================================================================


def test_movsb_copies_from_ds_si_to_es_di(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, si=0x0200, es=0x0000, di=0x0300, flags=0)
    cpu.write_block(0x00000, bytes([0xA4]))
    cpu.write_byte(0x00200, 0x5A)
    cpu.step()
    assert cpu.read_byte(0x00300) == 0x5A
    assert (cpu.regs.si, cpu.regs.di) == (0x0201, 0x0301)


def test_the_direction_flag_counts_the_pointers_down(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, si=0x0200, es=0x0000, di=0x0300,
                 flags=0x0400)
    cpu.write_block(0x00000, bytes([0xA4]))
    cpu.step()
    assert (cpu.regs.si, cpu.regs.di) == (0x01FF, 0x02FF)


def test_the_word_form_steps_by_two(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, si=0x0200, es=0x0000, di=0x0300, flags=0)
    cpu.write_block(0x00000, bytes([0xA5]))
    cpu.write_word(0x00200, 0xBEEF)
    cpu.step()
    assert cpu.read_word(0x00300) == 0xBEEF
    assert (cpu.regs.si, cpu.regs.di) == (0x0202, 0x0302)


def test_a_segment_override_moves_the_source_and_never_the_destination(cpu):
    """`36 A4` reads from SS:SI and still writes to ES:DI.

    The override deliberately names a **third** segment, different from both
    DS and ES. An earlier version of this test used the ES prefix, so the
    overridden source segment and the fixed destination segment were the same
    register -- and a core that wrongly applied the override to the
    destination as well produced identical output and passed. It was caught by
    mutating the core and finding this test still green.
    """
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x3000, ss=0x2000, es=0x1000,
                 si=0x0200, di=0x0300, flags=0)
    cpu.write_block(0x00000, bytes([0x36, 0xA4]))     # SS override on the source
    cpu.write_byte(0x20200, 0x77)                     # SS:0200 -- what must be read
    cpu.write_byte(0x30200, 0x11)                     # DS:0200 -- must not be
    cpu.step()
    assert cpu.read_byte(0x10300) == 0x77, "the destination is ES:DI, always"
    assert cpu.read_byte(0x20300) == 0x00, "nothing may be written to SS:DI"


def test_stos_has_no_source_so_an_override_changes_nothing(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000, di=0x0300, ax=0x1234, flags=0)
    cpu.write_block(0x00000, bytes([0x2E, 0xAA]))     # CS override, and no source
    cpu.step()
    assert cpu.read_byte(0x00300) == 0x34
    assert cpu.regs.di == 0x0301


def test_lods_loads_al_and_leaves_ah(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, si=0x0200, ax=0xAB00, flags=0)
    cpu.write_block(0x00000, bytes([0xAC]))
    cpu.write_byte(0x00200, 0x5A)
    cpu.step()
    assert cpu.regs.ax == 0xAB5A


def test_cmps_subtracts_the_destination_from_the_source(cpu):
    """The operand order is not symmetric and CF says which way round it is:
    5 - 9 borrows, 9 - 5 does not."""
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000, si=0x0200, di=0x0300, flags=0)
    cpu.write_block(0x00000, bytes([0xA6]))
    cpu.write_byte(0x00200, 0x05)
    cpu.write_byte(0x00300, 0x09)
    cpu.step()
    assert cpu.regs.flags & CF


# --- REP, which runs the whole loop inside one step ---------------------------------


def test_a_repeated_move_runs_to_completion_in_one_step(cpu):
    """`F3 A4` with CX=4 moves four bytes and advances IP by two. It is one
    instruction, not four steps -- CX comes out zero and IP past the prefix."""
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000,
                 si=0x0200, di=0x0300, cx=4, flags=0)
    cpu.write_block(0x00000, bytes([0xF3, 0xA4]))
    cpu.write_block(0x00200, bytes([1, 2, 3, 4]))
    cpu.step()
    assert cpu.read_block(0x00300, 4) == bytes([1, 2, 3, 4])
    assert (cpu.regs.cx, cpu.regs.si, cpu.regs.di, cpu.regs.ip) == (0, 0x0204, 0x0304, 2)


def test_a_repeat_with_a_zero_count_does_nothing_but_advance_ip(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000,
                 si=0x0200, di=0x0300, cx=0, flags=0)
    cpu.write_block(0x00000, bytes([0xF3, 0xA4]))
    cpu.write_byte(0x00200, 0x99)
    cpu.step()
    assert cpu.read_byte(0x00300) == 0x00
    assert (cpu.regs.si, cpu.regs.di, cpu.regs.ip) == (0x0200, 0x0300, 2)


def test_repe_cmps_stops_at_the_first_difference(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000,
                 si=0x0200, di=0x0300, cx=4, flags=0)
    cpu.write_block(0x00000, bytes([0xF3, 0xA6]))
    cpu.write_block(0x00200, bytes([1, 2, 9, 4]))
    cpu.write_block(0x00300, bytes([1, 2, 3, 4]))
    cpu.step()
    assert cpu.regs.cx == 1, "stopped after comparing the third byte"
    assert not cpu.regs.flags & ZF


def test_repne_scas_stops_when_it_finds_the_byte(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, es=0x0000, di=0x0300, cx=4, ax=0x0003, flags=0)
    cpu.write_block(0x00000, bytes([0xF2, 0xAE]))
    cpu.write_block(0x00300, bytes([1, 2, 3, 4]))
    cpu.step()
    assert cpu.regs.cx == 1
    assert cpu.regs.flags & ZF


def test_both_repeat_prefixes_mean_the_same_thing_on_a_move(cpu):
    """MOVS sets no flags, so there is no condition for F2 and F3 to differ
    on -- the corpus disassembles `F2 A4` as `rep movsb`, not `repne`."""
    for prefix in (0xF2, 0xF3):
        cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x0000, es=0x0000,
                     si=0x0200, di=0x0300, cx=3, flags=0)
        cpu.write_block(0x00000, bytes([prefix, 0xA4]))
        cpu.write_block(0x00200, bytes([7, 7, 7]))
        cpu.step()
        assert cpu.regs.cx == 0, f"prefix {prefix:02X} did not run to completion"


# ======================================================================================
# Group 3: TEST, NOT, NEG, MUL, IMUL, DIV, IDIV
# ======================================================================================

TEST_, TEST_ALT, NOT_, NEG_, MUL_, IMUL_, DIV_, IDIV_ = range(8)


def group3(cpu, operation: int, value: int, immediate: bytes = b"",
           wide: bool = False, **regs):
    """`F6`/`F7` /op on BL or BX, at mod=3."""
    opcode = 0xF7 if wide else 0xF6
    modrm = 0xC0 | (operation << 3) | 0x03
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=value, flags=0, **regs)
    cpu.write_block(0x00000, bytes([opcode, modrm]) + immediate)
    cpu.step()


def test_test_sets_flags_without_storing_a_result(cpu):
    group3(cpu, TEST_, 0x0FF0, immediate=bytes([0x0F]))
    assert cpu.regs.bx == 0x0FF0, "the operand must be unchanged"
    assert cpu.regs.flags & ZF, "0xF0 AND 0x0F is zero"


def test_the_length_of_a_group_three_instruction_depends_on_the_reg_field(cpu):
    """`F6 /0` carries an immediate and `F6 /2` does not, so `Lookup` alone
    cannot say how long an F6 is. A decoder that guesses one length for the
    whole group puts IP one byte out on half of it."""
    cpu.set_regs(cs=0x0000, ip=0x0000)
    cpu.write_block(0x00000, bytes([0xF6, 0xC3, 0x0F]))     # TEST BL, 0Fh
    assert cpu.decode().length == 3
    cpu.write_block(0x00000, bytes([0xF6, 0xD3]))           # NOT BL
    assert cpu.decode().length == 2
    cpu.write_block(0x00000, bytes([0xF7, 0xC3, 0x34, 0x12]))  # TEST BX, 1234h
    assert cpu.decode().length == 4


def test_reg_one_is_a_second_encoding_of_test(cpu):
    """Undocumented, and the corpus has 10,000 cases of it per width."""
    group3(cpu, TEST_ALT, 0x0FF0, immediate=bytes([0x0F]))
    assert cpu.regs.bx == 0x0FF0
    assert cpu.regs.flags & ZF


def test_not_touches_no_flag_at_all(cpu):
    everything = CF | PF | AF | ZF | SF | OF
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=0x00F0, flags=everything)
    cpu.write_block(0x00000, bytes([0xF6, 0xC0 | (NOT_ << 3) | 0x03]))
    cpu.step()
    assert cpu.regs.bx & 0xFF == 0x0F
    assert cpu.regs.flags & everything == everything


def test_neg_subtracts_from_zero_and_carries_unless_the_operand_was_zero(cpu):
    group3(cpu, NEG_, 0x0001)
    assert cpu.regs.bx & 0xFF == 0xFF
    assert cpu.regs.flags & CF

    group3(cpu, NEG_, 0x0000)
    assert cpu.regs.bx & 0xFF == 0x00
    assert not cpu.regs.flags & CF


# --- the multiplies -------------------------------------------------------------------


def test_mul_byte_puts_the_product_in_ax(cpu):
    group3(cpu, MUL_, 0x0010, ax=0x0010)      # 16 * 16
    assert cpu.regs.ax == 0x0100


def test_mul_word_puts_the_high_half_in_dx(cpu):
    group3(cpu, MUL_, 0x1000, wide=True, ax=0x1000)
    assert (cpu.regs.dx, cpu.regs.ax) == (0x0100, 0x0000)


def test_mul_carries_and_overflows_together_when_the_high_half_is_used(cpu):
    group3(cpu, MUL_, 0x0010, ax=0x0010)
    assert cpu.regs.flags & CF and cpu.regs.flags & OF
    group3(cpu, MUL_, 0x0002, ax=0x0003)      # fits in AL
    assert not (cpu.regs.flags & CF or cpu.regs.flags & OF)


def test_mul_takes_its_sign_zero_and_parity_from_the_high_half(cpu):
    """All three are documented undefined and all three are the high half's.
    Measured exact over 20,000 cases; from the low half instead, MUL scores
    about 6%."""
    group3(cpu, MUL_, 0x0002, ax=0x0003)      # AX = 6, so AH = 0
    assert cpu.regs.flags & ZF, "ZF follows AH, which is zero, not AX"
    group3(cpu, MUL_, 0x0080, ax=0x0002)      # AX = 0x0100, AH = 1
    assert not cpu.regs.flags & ZF


def test_imul_multiplies_signed(cpu):
    group3(cpu, IMUL_, 0x00FF, ax=0x0002)     # 2 * -1
    assert cpu.regs.ax == 0xFFFE


def test_imul_does_not_overflow_when_the_high_half_is_only_a_sign_extension(cpu):
    group3(cpu, IMUL_, 0x00FF, ax=0x0002)     # -2 fits in a byte
    assert not (cpu.regs.flags & CF or cpu.regs.flags & OF)


# --- the divides ----------------------------------------------------------------------


def test_div_byte_puts_the_quotient_in_al_and_the_remainder_in_ah(cpu):
    group3(cpu, DIV_, 0x0007, ax=0x0011)      # 17 / 7 = 2 remainder 3
    assert cpu.regs.ax == 0x0302


def test_div_word_puts_the_remainder_in_dx(cpu):
    group3(cpu, DIV_, 0x0007, wide=True, ax=0x0011, dx=0x0000)
    assert (cpu.regs.ax, cpu.regs.dx) == (0x0002, 0x0003)


def test_idiv_divides_signed(cpu):
    group3(cpu, IDIV_, 0x0007, ax=0xFFEF)     # -17 / 7 = -2 remainder -3
    assert cpu.regs.ax & 0xFF == 0xFE


def test_dividing_by_zero_traps(cpu):
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0x0011, bx=0x0000, flags=0)
    cpu.write_block(0x00100, bytes([0xF6, 0xC0 | (DIV_ << 3) | 0x03]))
    cpu.step()
    assert (cpu.regs.cs, cpu.regs.ip) == (0xB000, 0x1234)
    assert cpu.regs.ax == 0x0011, "AX must be untouched -- no partial answer"


def test_a_quotient_too_large_for_its_half_traps_rather_than_truncating(cpu):
    """`DIV` by 1 on a dividend above 255 is the usual way to meet this: the
    quotient has nowhere to go. Truncating instead would return a plausible
    wrong answer and never say so."""
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0x0100, bx=0x0001, flags=0)
    cpu.write_block(0x00100, bytes([0xF6, 0xC0 | (DIV_ << 3) | 0x03]))
    cpu.step()
    assert (cpu.regs.cs, cpu.regs.ip) == (0xB000, 0x1234)


def test_a_divide_that_fits_does_not_trap(cpu):
    """The other half of the check above: a core that traps too eagerly passes
    every test that only looks for traps."""
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0x00FF, bx=0x0001, flags=0)
    cpu.write_block(0x00100, bytes([0xF6, 0xC0 | (DIV_ << 3) | 0x03]))
    cpu.step()
    assert (cpu.regs.cs, cpu.regs.ip) == (0x0000, 0x0102)
    assert cpu.regs.sp == 0x0200, "nothing was pushed"


def test_the_divide_error_disables_interrupts_for_the_handler(cpu):
    """IF and TF are cleared after the push, so IRET restores them. A handler
    entered with interrupts still on would be re-entered by the next one."""
    set_up_vector_zero(cpu, 0xB000, 0x1234)
    cpu.set_regs(cs=0x0000, ip=0x0100, ss=0x0000, sp=0x0200, ax=0xE837,
                 flags=0x0200 | 0x0100)
    cpu.write_block(0x00100, bytes([0xD4, 0x00]))
    cpu.step()
    assert not cpu.regs.flags & 0x0200      # IF
    assert not cpu.regs.flags & 0x0100      # TF
    assert cpu.read_word(0x001FE) & 0x0300 == 0x0300, "both were pushed set"
