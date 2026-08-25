# OpenHardware — the flag rules the oracle cannot be asked about.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why these are not in the corpus
#
# `tests/avr/test_conformance.py` checks 570 cases against avr8js, and that is
# the right shape for almost everything. It cannot be the shape for a rule the
# oracle gets **wrong**, because there the corpus would pin the bug.
#
# Two such rules were measured on 2026-08-26, both in avr8js 0.21.0:
#
#   * **The half-carry**, in all eleven of its H expressions. It masks its
#     boolean with `1` where the datasheet's `Rd3.Rr3 + Rr3./R3 + /R3.Rd3`
#     reads bit **3**. `tools/gen_avr_corpus.mjs` works around this by
#     carrying the manual's answer beside the oracle's, so the corpus does
#     cover H — but only for operand draws the LCG happens to produce.
#
#   * **`neg` of 0x80**, at `dist/cjs/cpu/instruction.js:523`, which tests
#     `128 === R` where `R` is `0 - value` — a negative JavaScript number that
#     is never 128. So avr8js never sets V for `neg`, and the corpus cannot
#     say so because no seed draws 0x80 into a `neg` operand.
#
# So these are asserted against the AVR Instruction Set Manual directly, on
# operands chosen because they are the ones where the two sources part company.
# **Every value below is one where a bit-0 reading and a bit-3 reading give
# different answers**, which is the whole reason each case is here.
#
# ## And one that needs no formula at all
#
# `0x08 + 0x08 = 0x10`. That carries out of the low nibble whatever any
# simulator says, and it is the case worth reaching for first when this file
# and a datasheet appear to disagree.

H = "H"
V = "V"
C = "C"

#: `1001 010d dddd 0001`, with d = 16.
NEG_R16 = 0x9401 | (16 << 4)

#: `0000 11rd dddd rrrr` — add r0, r1.
ADD_R0_R1 = 0x0C01

#: `0001 10rd dddd rrrr` — sub r0, r1.
SUB_R0_R1 = 0x1801


def step_once(cpu, encoding: int) -> None:
    """Load one instruction at word 0 and execute it."""
    cpu.write_program(0, encoding)
    cpu.pc = 0
    cpu.step()


def test_negating_the_one_value_that_cannot_be_negated_sets_overflow(cpu):
    """`neg 0x80` is 0x80, and the datasheet sets V for exactly that input.

    Eight bits hold -128 but not +128, so the negation of 0x80 is the only one
    that cannot be represented — which is what signed overflow means. avr8js
    never sets this flag for `neg`; see the header.
    """
    cpu.set_reg(16, 0x80)
    step_once(cpu, NEG_R16)

    assert cpu.reg(16) == 0x80, "negating 0x80 gives 0x80 back"
    assert cpu.flag(V), "the one input whose negation does not fit"


def test_negating_anything_else_clears_overflow(cpu):
    """The other direction, so the test above cannot pass on a core that sets
    V unconditionally."""
    cpu.set_reg(16, 0x7F)
    step_once(cpu, NEG_R16)

    assert cpu.reg(16) == 0x81
    assert not cpu.flag(V)


def test_negating_zero_clears_carry(cpu):
    """`neg` sets C for every input except zero — it is `R != 0`, not a borrow
    computed from the operands."""
    cpu.set_reg(16, 0x00)
    step_once(cpu, NEG_R16)

    assert cpu.reg(16) == 0x00
    assert not cpu.flag(C)
    assert not cpu.flag(H), "H is R3 | Rd3, and both are clear here"


def test_the_add_half_carry_is_a_carry_out_of_bit_three(cpu):
    """`0x08 + 0x08 = 0x10`. The case that needs no formula."""
    cpu.set_reg(0, 0x08)
    cpu.set_reg(1, 0x08)
    step_once(cpu, ADD_R0_R1)

    assert cpu.reg(0) == 0x10
    assert cpu.flag(H)


def test_the_add_half_carry_ignores_bit_zero(cpu):
    """`0x01 + 0x01 = 0x02`, which carries out of bit 0 and out of nothing
    else.

    This is the case that separates the two readings in the other direction: a
    core computing H from bit 0 would set it here, and the datasheet's rule
    over bit 3 clears it. Without this, a core that always set H would pass the
    test above.
    """
    cpu.set_reg(0, 0x01)
    cpu.set_reg(1, 0x01)
    step_once(cpu, ADD_R0_R1)

    assert cpu.reg(0) == 0x02
    assert not cpu.flag(H)


def test_the_subtract_half_carry_is_a_borrow_out_of_bit_three(cpu):
    """`0x10 - 0x01 = 0x0F`, which borrows into the high nibble."""
    cpu.set_reg(0, 0x10)
    cpu.set_reg(1, 0x01)
    step_once(cpu, SUB_R0_R1)

    assert cpu.reg(0) == 0x0F
    assert cpu.flag(H)


def test_the_subtract_half_carry_ignores_bit_zero(cpu):
    """`0x0F - 0x01 = 0x0E`: bit 0 borrows in a bit-0 reading, and the low
    nibble does not borrow at all."""
    cpu.set_reg(0, 0x0F)
    cpu.set_reg(1, 0x01)
    step_once(cpu, SUB_R0_R1)

    assert cpu.reg(0) == 0x0E
    assert not cpu.flag(H)


def test_subtracting_a_value_from_itself_does_not_borrow(cpu):
    """`sub` does not read the carry, and this is where forgetting that shows.

    `tools/gen_avr_corpus.mjs` fed the seeded carry to every arithmetic
    mnemonic, so the manual's H expectation for `sub r5, r5` was computed for
    `x - x - 1` — bit 3 set — while the machine computes `x - x` and clears it.
    The oracle agreed with the core and only the second source was wrong.
    """
    cpu.write_data(0x5F, 0x01)      # SREG with C set
    cpu.set_reg(0, 0x18)
    cpu.set_reg(1, 0x18)
    step_once(cpu, SUB_R0_R1)

    assert cpu.reg(0) == 0x00, "sub ignores the carry; sbc would give 0xFF"
    assert not cpu.flag(H)
    assert not cpu.flag(C)
