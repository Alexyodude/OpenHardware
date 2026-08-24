# OpenHardware — the Armv6-M shift edges, from the architecture not the oracle.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file exists, and what found the hole
#
# The corpus does not cover these. It draws its operands from a PRNG, so a
# shift amount is a uniform random byte and each specific amount appears in
# roughly one case in 256 -- measured: **1 of 500** `asrs_reg` cases shifts by
# zero, and none shift by exactly 32.
#
# Worse, at those amounts the corpus *cannot* settle the question, because they
# are exactly where rp2040js is wrong (see test_conformance.py). Breaking the
# core to clear the carry on a shift of zero, instead of preserving it, was
# caught by nothing: the one ASRS case has bit 31 clear, so the mutant's wrong
# answer and the oracle's wrong answer coincide, and the case flipped from
# "predicted divergence" to "agrees" without any test noticing.
#
# **Where the oracle is buggy, agreeing with it is not evidence.** So these
# cases are pinned to ARM DDI0419 `Shift_C` directly, with concrete values, and
# they are what actually holds the shift-by-zero and shift-by-32 rules in
# place. Found by mutation testing, not by reading.
#
# A follow-up worth doing on the generator instead of here: bias the shift
# amount toward 0, 1, 31, 32, 33 and 255 rather than sampling a uniform byte.
# That is `tools/gen_armv6m_tests.mjs`'s business and a separate change.

from core.cortexm0.abi import Cpu
from tests.cortexm0.conftest import PC

C_FLAG = 1 << 29

#: Format-4 ALU opcodes, in encoding order.
LSL_REG, LSR_REG, ASR_REG, ROR_REG = 2, 3, 4, 7


def alu(op: int, rm: int, rdn: int) -> int:
    return 0x4000 | (op << 6) | (rm << 3) | rdn


def shift_imm(op: int, imm5: int, rm: int, rd: int) -> int:
    """Format 1: op 0 = LSL, 1 = LSR, 2 = ASR."""
    return (op << 11) | (imm5 << 6) | (rm << 3) | rd


def run(cpu: Cpu, encoding: int, *, r0: int, r1: int, carry: bool) -> tuple[int, bool]:
    """Execute one encoding with r0 and r1 set. Returns (r0, carry)."""
    cpu.clear_memory()
    regs = [0] * 16
    regs[0] = r0
    regs[1] = r1
    regs[15] = PC
    cpu.set_regs(regs, apsr=C_FLAG if carry else 0)
    cpu.write_halfword(PC, encoding)
    cpu.step()
    out = cpu.get_regs()
    return out.r[0], bool(out.apsr & C_FLAG)


# --- a shift of zero leaves the carry alone --------------------------------
#
# `Shift_C(value, type, 0, carry_in)` returns `(value, carry_in)` for every
# type. Each of these is checked with the carry both set and clear, because a
# core that hardcoded either one would pass the other half.


def test_lsl_by_zero_preserves_a_set_carry(cpu):
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0x0000FFFF, r1=0, carry=True)
    assert (value, carry) == (0x0000FFFF, True)


def test_lsl_by_zero_preserves_a_clear_carry(cpu):
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0xFFFF0000, r1=0, carry=False)
    assert (value, carry) == (0xFFFF0000, False)


def test_lsr_by_zero_preserves_a_set_carry(cpu):
    value, carry = run(cpu, alu(LSR_REG, 1, 0), r0=0x0000FFFF, r1=0, carry=True)
    assert (value, carry) == (0x0000FFFF, True)


def test_asr_by_zero_preserves_a_set_carry_even_when_bit31_is_clear(cpu):
    """The exact case the corpus could not settle. Bit 31 is clear and the
    carry is set, so 'preserve' and 'read bit 31' give different answers."""
    value, carry = run(cpu, alu(ASR_REG, 1, 0), r0=0x4D054B31, r1=0, carry=True)
    assert (value, carry) == (0x4D054B31, True)


def test_asr_by_zero_preserves_a_clear_carry_even_when_bit31_is_set(cpu):
    """The mirror image, so neither 'always preserve' nor 'always read bit 31'
    can pass both."""
    value, carry = run(cpu, alu(ASR_REG, 1, 0), r0=0x80000001, r1=0, carry=False)
    assert (value, carry) == (0x80000001, False)


def test_ror_by_zero_preserves_a_set_carry_when_bit31_is_clear(cpu):
    value, carry = run(cpu, alu(ROR_REG, 1, 0), r0=0x00000001, r1=0, carry=True)
    assert (value, carry) == (0x00000001, True)


def test_ror_by_zero_preserves_a_clear_carry_when_bit31_is_set(cpu):
    value, carry = run(cpu, alu(ROR_REG, 1, 0), r0=0x80000000, r1=0, carry=False)
    assert (value, carry) == (0x80000000, False)


# --- shifting by exactly 32 ------------------------------------------------
#
# `x << 32` and `x >> 32` are undefined behaviour on a uint32_t in C, and on
# x86 the shift count is masked to five bits, so the natural expression
# evaluates to `x << 0` -- the value unchanged, which is the opposite of the
# right answer. Zero corpus cases cover this.


def test_lsl_by_32_gives_zero_and_carries_bit_0(cpu):
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0x00000003, r1=32, carry=False)
    assert (value, carry) == (0, True)


def test_lsr_by_32_gives_zero_and_carries_bit_31(cpu):
    value, carry = run(cpu, alu(LSR_REG, 1, 0), r0=0x80000000, r1=32, carry=False)
    assert (value, carry) == (0, True)


def test_asr_by_32_of_a_negative_value_is_all_ones(cpu):
    value, carry = run(cpu, alu(ASR_REG, 1, 0), r0=0x80000000, r1=32, carry=False)
    assert (value, carry) == (0xFFFFFFFF, True)


def test_asr_by_32_of_a_positive_value_is_zero(cpu):
    value, carry = run(cpu, alu(ASR_REG, 1, 0), r0=0x7FFFFFFF, r1=32, carry=True)
    assert (value, carry) == (0, False)


# --- shifting by more than 32 ----------------------------------------------
#
# The register forms take the whole low byte of Rm, so 33 to 255 are legal.
# LSL and LSR saturate to zero with no carry; ASR saturates to the sign.


def test_lsl_by_more_than_32_gives_zero_and_no_carry(cpu):
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0xFFFFFFFF, r1=33, carry=True)
    assert (value, carry) == (0, False)


def test_lsr_by_the_largest_legal_amount_gives_zero_and_no_carry(cpu):
    value, carry = run(cpu, alu(LSR_REG, 1, 0), r0=0xFFFFFFFF, r1=255, carry=True)
    assert (value, carry) == (0, False)


def test_asr_by_more_than_32_keeps_the_sign(cpu):
    value, carry = run(cpu, alu(ASR_REG, 1, 0), r0=0x80000000, r1=255, carry=False)
    assert (value, carry) == (0xFFFFFFFF, True)


def test_only_the_low_byte_of_the_shift_register_is_used(cpu):
    """0x100 is 256, whose low byte is zero -- so this is a shift of nothing,
    not a shift of 256. A core masking to 5 bits instead would also give zero
    here, so the companion test below separates them."""
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0xDEADBEEF, r1=0x100, carry=True)
    assert (value, carry) == (0xDEADBEEF, True)


def test_the_shift_amount_is_not_masked_to_five_bits(cpu):
    """0x21 is 33. Masked to five bits it would be 1, giving a shift of one
    and a completely different answer."""
    value, carry = run(cpu, alu(LSL_REG, 1, 0), r0=0xFFFFFFFF, r1=0x21, carry=True)
    assert (value, carry) == (0, False)


# --- rotate ----------------------------------------------------------------


def test_ror_by_a_non_zero_multiple_of_32_moves_nothing_but_sets_the_carry(cpu):
    """The value is unchanged, so an implementation that returns early here
    looks right. The carry is what catches it: it must become bit 31."""
    value, carry = run(cpu, alu(ROR_REG, 1, 0), r0=0x80000000, r1=32, carry=False)
    assert (value, carry) == (0x80000000, True)


def test_ror_by_32_of_a_positive_value_clears_the_carry(cpu):
    value, carry = run(cpu, alu(ROR_REG, 1, 0), r0=0x00000001, r1=32, carry=True)
    assert (value, carry) == (0x00000001, False)


def test_ror_wraps_the_low_bits_to_the_top(cpu):
    value, carry = run(cpu, alu(ROR_REG, 1, 0), r0=0x00000001, r1=1, carry=False)
    assert (value, carry) == (0x80000000, True)


# --- the immediate forms encode 32 as zero ---------------------------------


def test_lsr_immediate_zero_means_a_shift_of_32(cpu):
    """imm5 == 0 encodes 32 for LSR, not 0. A core taking it literally would
    return the value unchanged."""
    value, carry = run(cpu, shift_imm(1, 0, 1, 0), r0=0, r1=0x80000000, carry=False)
    assert (value, carry) == (0, True)


def test_asr_immediate_zero_means_a_shift_of_32(cpu):
    value, carry = run(cpu, shift_imm(2, 0, 1, 0), r0=0, r1=0x80000000, carry=False)
    assert (value, carry) == (0xFFFFFFFF, True)


def test_lsl_immediate_zero_really_does_mean_zero(cpu):
    """LSL is the exception: imm5 == 0 is a genuine shift of nothing, and the
    carry survives. Encoding it as 32 like its neighbours would be wrong."""
    value, carry = run(cpu, shift_imm(0, 0, 1, 0), r0=0, r1=0xDEADBEEF, carry=True)
    assert (value, carry) == (0xDEADBEEF, True)
