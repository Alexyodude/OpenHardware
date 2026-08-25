# OpenHardware — multiply and divide, and the six answers RISC-V defines.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The arithmetic is not the interesting part
#
# `tests/rv32/corpus/rv32m_op.json` holds 128 cases generated from rvcpp's own
# table, and `tests/riscv32/test_lockstep.py` runs the whole ALU against the
# oracle. Between them the ordinary products and quotients are covered.
#
# What neither covers is the edge, because **RISC-V defines division by zero
# and signed overflow rather than leaving them undefined** — and the host
# language does the opposite. `INT_MIN / -1` is undefined behaviour in C++ and
# raises SIGFPE on x86 rather than returning a wrong answer, so a model that
# inherited the host's behaviour would not be subtly wrong here, it would take
# the process down.
#
#     div  x / 0         -> -1           divu x / 0 -> 2^32 - 1
#     rem  x / 0         -> x            remu x / 0 -> x
#     div  INT_MIN / -1  -> INT_MIN      rem  INT_MIN / -1 -> 0
#
# Those six rows are OH-55's acceptance criteria and each one is a test below.
#
# ## And `mulhsu`
#
# Signed times **unsigned**, and the only instruction here whose two operands
# are extended differently. It is the one every implementation gets wrong
# first, so it is asserted against a value where the three high-half variants
# genuinely disagree — a case where mulh, mulhsu and mulhu all returned the
# same number would pass over a decoder that ran any of the three.

import pytest

from core.riscv32 import abi

from . import encode as e
from .conftest import PC, load

INT_MIN = 0x80000000
MINUS_ONE = 0xFFFFFFFF


def run(cpu, encoding: int, rs1: int, rs2: int) -> int:
    """Execute one M instruction with `t1 = rs1`, `t2 = rs2`, and return `t0`."""
    load(cpu, [encoding])
    regs = [0] * 32
    regs[6], regs[7] = rs1, rs2          # t1, t2
    cpu.set_extensions(abi.ESP32_C3)
    cpu.set_regs(regs, pc=PC)
    cpu.step()
    return cpu.reg(5)                    # t0


# --- division by zero, which is an answer and not a trap --------------------


def test_signed_division_by_zero_is_all_ones(cpu):
    """Not a trap and not zero. RISC-V has no divide-by-zero exception, so the
    quotient is defined as -1 and software checks for it if it cares."""
    assert run(cpu, _m(0x4), 1234, 0) == MINUS_ONE


def test_unsigned_division_by_zero_is_the_largest_value(cpu):
    assert run(cpu, _m(0x5), 1234, 0) == 0xFFFFFFFF


def test_signed_remainder_by_zero_is_the_dividend(cpu):
    """The dividend, not zero. `rem x, 0` returns x so that a caller doing
    `div` and `rem` together gets a consistent pair."""
    assert run(cpu, _m(0x6), 1234, 0) == 1234


def test_unsigned_remainder_by_zero_is_the_dividend(cpu):
    assert run(cpu, _m(0x7), 1234, 0) == 1234


def test_the_dividend_comes_back_from_a_remainder_by_zero_even_when_negative(cpu):
    """A separate case because a model that returned `abs(x)` or zero would
    pass the positive one."""
    assert run(cpu, _m(0x6), MINUS_ONE, 0) == MINUS_ONE


# --- signed overflow, which is undefined behaviour in the host language -----


def test_the_one_signed_division_that_overflows_returns_the_dividend(cpu):
    """`INT_MIN / -1` has no representable quotient, and RISC-V defines the
    result as `INT_MIN` rather than trapping.

    **This is the case that must be answered before the divide happens.** In
    C++ it is undefined behaviour, and on x86 the hardware raises rather than
    returning anything at all — so a model that special-cased it *after*
    dividing would never reach the special case.
    """
    assert run(cpu, _m(0x4), INT_MIN, MINUS_ONE) == INT_MIN


def test_the_matching_remainder_is_zero(cpu):
    """`INT_MIN % -1` is mathematically zero, and is the other half of the same
    undefined-behaviour hazard."""
    assert run(cpu, _m(0x6), INT_MIN, MINUS_ONE) == 0


def test_unsigned_division_has_no_overflow_case(cpu):
    """The same bit patterns, read as unsigned, are an ordinary division. If
    the overflow guard were keyed on the bits rather than on the signed
    instruction, this would come back wrong."""
    assert run(cpu, _m(0x5), INT_MIN, MINUS_ONE) == 0
    assert run(cpu, _m(0x7), INT_MIN, MINUS_ONE) == INT_MIN


# --- the three high halves, which differ in how they extend -----------------


def test_the_three_high_halves_disagree_on_the_same_operands(cpu):
    """The case that separates them, so running the wrong one is a wrong answer.

    -1 times -1 is 1, whose high word is 0. Read as unsigned, 0xFFFFFFFF times
    0xFFFFFFFF is 0xFFFFFFFE00000001, whose high word is 0xFFFFFFFE. And signed
    times unsigned is -(2^32 - 1), whose high word is 0xFFFFFFFF.

    Three different answers from one pair of registers. A test using operands
    where they agreed would pass over a decoder that ran any of the three.
    """
    assert run(cpu, _m(0x1), MINUS_ONE, MINUS_ONE) == 0x00000000, "mulh"
    assert run(cpu, _m(0x2), MINUS_ONE, MINUS_ONE) == 0xFFFFFFFF, "mulhsu"
    assert run(cpu, _m(0x3), MINUS_ONE, MINUS_ONE) == 0xFFFFFFFE, "mulhu"


def test_mulhsu_is_signed_times_unsigned_and_not_the_other_way_round(cpu):
    """Asymmetric, unlike the other two, so the operand order is load-bearing.

    -2 as rs1 and 3 as rs2 gives -6, high word 0xFFFFFFFF. Swapped, 3 times
    0xFFFFFFFE is a positive 64-bit number with high word 2. An implementation
    that extended the wrong operand gets the second answer.
    """
    assert run(cpu, _m(0x2), 0xFFFFFFFE, 3) == 0xFFFFFFFF
    assert run(cpu, _m(0x2), 3, 0xFFFFFFFE) == 0x00000002


def test_the_low_word_does_not_care_about_signedness(cpu):
    """`mul` has one form because the low 32 bits of a product are the same
    whichever way the operands are read. Worth pinning: it is the reason there
    is no `mulsu`, and a reader meeting three high halves may wonder."""
    assert run(cpu, _m(0x0), MINUS_ONE, MINUS_ONE) == 1
    assert run(cpu, _m(0x0), 0xFFFFFFFE, 3) == 0xFFFFFFFA


# --- ordinary arithmetic, so the edges above are not the only thing checked --


def test_the_ordinary_cases_still_work(cpu):
    assert run(cpu, _m(0x0), 6, 7) == 42
    assert run(cpu, _m(0x4), 100, 7) == 14
    assert run(cpu, _m(0x6), 100, 7) == 2
    assert run(cpu, _m(0x4), 0xFFFFFF9C, 7) == 0xFFFFFFF2, "-100 / 7 == -14"
    assert run(cpu, _m(0x6), 0xFFFFFF9C, 7) == 0xFFFFFFFE, "-100 %% 7 == -2"


def test_signed_division_truncates_toward_zero(cpu):
    """RISC-V truncates rather than flooring, which is what C++ does too — so
    this is the assertion that would catch a model written in a language whose
    division floors, and it is cheap to keep."""
    assert run(cpu, _m(0x4), 7, 0xFFFFFFFE) == 0xFFFFFFFD, "7 / -2 == -3"
    assert run(cpu, _m(0x6), 7, 0xFFFFFFFE) == 1, "7 %% -2 == 1"


def test_a_part_without_m_still_refuses_all_eight(cpu):
    """The gate, in the direction no ESP32-C board will ever take. A part told
    it has no M must trap every one of these, and `Illegal` is that — not
    `Unimplemented`, which would say this emulator is unfinished."""
    for funct3 in range(8):
        load(cpu, [_m(funct3)])
        cpu.set_extensions(abi.EXT_C)
        with pytest.raises(abi.Illegal):
            cpu.step()


def _m(funct3: int) -> int:
    """An M-extension encoding: funct7 0x01, `t0 = t1 op t2`."""
    return e.r_type(0x01, "t2", "t1", funct3, "t0", 0x33)
