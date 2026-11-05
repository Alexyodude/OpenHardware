// OpenHardware - the 8086 multiply and divide group.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The routines below are a C++ port of the 8088 microcode translation in
// MartyPC, crates/lib/marty_core/src/cpu_808x/muldiv.rs at commit
// f0ebca4e411e55685b661e9efe1d136a9c727a7c, whose notice follows. OH-11.
//
//     MartyPC
//     https://github.com/dbalsom/martypc
//
//     Copyright 2022-2026 Daniel Balsom
//
//     Permission is hereby granted, free of charge, to any person obtaining a
//     copy of this software and associated documentation files (the
//     "Software"), to deal in the Software without restriction, including
//     without limitation the rights to use, copy, modify, merge, publish,
//     distribute, sublicense, and/or sell copies of the Software, and to
//     permit persons to whom the Software is furnished to do so, subject to
//     the following conditions:
//
//     The above copyright notice and this permission notice shall be included
//     in all copies or substantial portions of the Software.
//
//     THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
//     OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
//     MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
//     IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
//     CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
//     TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
//     SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

#include "muldiv.h"

#include "alu.h"

namespace i8086 {
namespace {

// Why the microcode and not a C++ multiply and divide: the arithmetic was
// always right, and three things around it were not. The flags the manual
// calls undefined are what the last ALU step of the shift-and-add or
// shift-and-subtract loop left, and nothing simpler reproduces them (the
// ticket records the search). A REP prefix sets the F1 latch, which the
// microcode reads as "negate the result". And IDIV's range check is the
// magnitude's top bit, so a quotient of -128 or -32768 traps although it
// would fit.
//
// Every value is held in 16 bits, as the part's temporaries are, and an
// operation is done at the instruction's width only where the microcode does
// it at that width. Several steps are 16 bits wide even for a byte
// instruction -- the NEG in NEGATE, the ADC in IMULCOF -- and those widths
// are what make the byte form's flags come out right.

constexpr std::uint16_t Mask(bool wide) { return wide ? 0xFFFF : 0x00FF; }

constexpr bool Msb(std::uint16_t value, bool wide) {
    return (value & (wide ? 0x8000 : 0x0080)) != 0;
}

/// A subtraction at the instruction's width, with every flag it makes.
struct Difference {
    std::uint16_t value;
    bool carry;
    bool overflow;
    bool aux_carry;
};

Difference Sub(std::uint16_t left, std::uint16_t right, bool wide) {
    const std::uint16_t a = left & Mask(wide);
    const std::uint16_t b = right & Mask(wide);
    const std::uint16_t r = static_cast<std::uint16_t>((a - b) & Mask(wide));
    return {r, b > a, Msb(static_cast<std::uint16_t>((a ^ b) & (a ^ r)), wide),
            ((a ^ b ^ r) & 0x10) != 0};
}

/// NEG, always 16 bits wide. Carry is "the operand was not zero".
std::uint16_t Neg16(std::uint16_t value, bool& carry) {
    carry = value != 0;
    return static_cast<std::uint16_t>(0u - value);
}

std::uint16_t Rcl(std::uint16_t value, bool& carry, bool wide) {
    const bool out = Msb(value, wide);
    const std::uint16_t r =
        static_cast<std::uint16_t>(((value << 1) | (carry ? 1 : 0)) & Mask(wide));
    carry = out;
    return r;
}

std::uint16_t Rcr(std::uint16_t value, bool& carry, bool wide) {
    const std::uint16_t v = value & Mask(wide);
    const bool out = (v & 1) != 0;
    std::uint16_t r = static_cast<std::uint16_t>(v >> 1);
    if (carry) {
        r = static_cast<std::uint16_t>(r | (wide ? 0x8000 : 0x0080));
    }
    carry = out;
    return r;
}

void SetDifferenceFlags(const Difference& d, bool wide, std::uint16_t& flags) {
    SetFlag(flags, kAuxCarry, d.aux_carry);
    SetFlag(flags, kOverflow, d.overflow);
    SetFlag(flags, kCarry, d.carry);
    SetResultFlags(d.value, wide, flags);
}

/// The second half of NEGATE (1bb-1bf), which is where PREIMUL and PREIDIV
/// enter it: take the divisor or multiplier's magnitude, and flip F1 if it
/// was negative.
void NegateOperand(std::uint16_t& tmpb, bool& f1, bool& carry, bool wide) {
    carry = Msb(tmpb, wide);
    if (carry) {
        bool unused;
        tmpb = Neg16(tmpb, unused);
        f1 = !f1;
    }
}

/// The first half of NEGATE (1b6-1ba): negate the double-width value
/// tmpa:tmpc. Both NEGs are 16 bits wide, whatever the instruction's width.
void NegatePair(std::uint16_t& tmpa, std::uint16_t& tmpc, bool wide) {
    tmpa &= Mask(wide);
    bool borrow;
    tmpc = Neg16(tmpc, borrow);
    if (borrow) {
        tmpa = static_cast<std::uint16_t>(~tmpa);
    } else {
        bool unused;
        tmpa = Neg16(tmpa, unused);
    }
}

/// CORX (17f-187), the shift-and-add loop. Leaves the high half in tmpa and
/// the low half in tmpc.
void Corx(std::uint16_t tmpb, std::uint16_t& tmpa, std::uint16_t& tmpc, bool carry,
          bool wide) {
    tmpc = Rcr(tmpc, carry, wide);
    tmpa = 0;
    for (int counter = wide ? 15 : 7;; --counter) {
        if (carry) {
            const std::uint32_t sum = static_cast<std::uint32_t>(tmpa & Mask(wide)) +
                                      (tmpb & Mask(wide));
            carry = sum > Mask(wide);
            tmpa = static_cast<std::uint16_t>(sum & Mask(wide));
        }
        tmpa = Rcr(tmpa, carry, wide);
        tmpc = Rcr(tmpc, carry, wide);
        if (counter == 0) {
            break;
        }
    }
}

/// CORD (188-194), the shift-and-subtract loop. tmpa:tmpc is the dividend
/// on entry; on return tmpc is the quotient's complement and tmpa the
/// remainder. False means the first subtraction did not borrow -- the
/// divisor is zero or the quotient cannot fit -- and the part traps there.
///
/// Every flag it leaves is from the last SUB that set them, plus CF from the
/// final rotate, which is what makes DIV's and IDIV's undefined flags what
/// they are.
bool Cord(std::uint16_t& tmpa, std::uint16_t tmpb, std::uint16_t& tmpc, bool& carry, bool wide,
          std::uint16_t& flags) {
    Difference d = Sub(tmpa, tmpb, wide);  // 188: SUBT tmpa
    SetDifferenceFlags(d, wide, flags);
    carry = d.carry;
    if (!carry) {  // 18a: NCY INT0
        return false;
    }
    tmpa &= Mask(wide);
    tmpc &= Mask(wide);
    for (int counter = wide ? 16 : 8; counter > 0; --counter) {
        tmpc = Rcl(tmpc, carry, wide);  // 18c
        tmpa = Rcl(tmpa, carry, wide);  // 18d
        if (carry) {
            // Shifted out of the top: the divisor certainly goes. 195-196,
            // and this SUB does not touch the flags.
            carry = false;
            tmpa = Sub(tmpa, tmpb, wide).value;
            continue;
        }
        d = Sub(tmpa, tmpb, wide);  // 18f: SUB, flags
        SetDifferenceFlags(d, wide, flags);
        carry = d.carry;
        if (!carry) {
            tmpa = d.value;  // 196
        }
    }
    tmpc = Rcl(tmpc, carry, wide);  // 192-193
    Rcl(tmpc, carry, wide);         // 194: only the carry is kept
    SetFlag(flags, kCarry, carry);
    return true;
}

MulDivResult Multiply(bool is_signed, std::uint16_t ax, std::uint16_t dx, std::uint16_t operand,
                      bool wide, bool f1, std::uint16_t& flags) {
    std::uint16_t tmpc = ax & Mask(wide);  // 150/158: LRCY tmpc
    bool carry = Msb(tmpc, wide);
    std::uint16_t tmpb = operand & Mask(wide);

    if (is_signed) {
        // PREIMUL (1c0-1c3): multiply magnitudes, and count the signs in F1.
        bool unused;
        const std::uint16_t negated = Neg16(tmpc, unused);
        if (carry) {
            tmpc = negated;
            f1 = !f1;
        }
        NegateOperand(tmpb, f1, carry, wide);
    }

    std::uint16_t tmpa = 0;
    Corx(tmpb, tmpa, tmpc, carry, wide);

    // 153/15b: F1 NEGATE. For IMUL this restores the product's sign; for
    // either multiply, a REP prefix arrives here with F1 already set.
    if (f1) {
        NegatePair(tmpa, tmpc, wide);
    }

    if (is_signed) {
        // IMULCOF (1cd-1d1): an ADC of the high half and the low half's sign
        // bit, 16 bits wide even for a byte multiply. It is zero exactly when
        // the high half is only the low half's sign extension, which is what
        // CF and OF report, and SF, ZF, PF and AF are what that ADC leaves.
        const bool low_sign = Msb(tmpc, wide);
        const std::uint32_t sum = static_cast<std::uint32_t>(tmpa) + (low_sign ? 1 : 0);
        const std::uint16_t sigma = static_cast<std::uint16_t>(sum);
        SetFlag(flags, kAuxCarry, ((tmpa ^ sigma) & 0x10) != 0);
        SetResultFlags(sigma, true, flags);
        SetFlag(flags, kCarry, sigma != 0);
        SetFlag(flags, kOverflow, sigma != 0);
    } else {
        // MULCOF (1d2-1d3): CF and OF are "the high half is not empty". SF,
        // ZF and PF come from the high half as it reaches the register, and
        // AF is cleared -- measured exact over all 20,000 MUL cases at both
        // widths before this port, and unchanged by it.
        SetFlag(flags, kCarry, tmpa != 0);
        SetFlag(flags, kOverflow, tmpa != 0);
        SetResultFlags(static_cast<std::uint16_t>(tmpa & Mask(wide)), wide, flags);
        SetFlag(flags, kAuxCarry, false);
    }

    if (wide) {
        return {tmpc, tmpa, false};
    }
    return {static_cast<std::uint16_t>((tmpa << 8) | (tmpc & 0xFF)), dx, false};
}

MulDivResult Divide(bool is_signed, std::uint16_t ax, std::uint16_t dx, std::uint16_t operand,
                    bool wide, bool f1, std::uint16_t& flags) {
    const std::uint16_t high = wide ? dx : static_cast<std::uint16_t>(ax >> 8);
    std::uint16_t tmpa = high;
    std::uint16_t tmpc = ax & Mask(wide);
    std::uint16_t tmpb = operand & Mask(wide);
    bool carry = false;

    if (is_signed) {
        // PREIDIV (1b4-1b5): a negative dividend runs the whole of NEGATE,
        // a positive one enters it halfway, at the divisor.
        if (Msb(tmpa, wide)) {
            NegatePair(tmpa, tmpc, wide);
            f1 = !f1;
        }
        NegateOperand(tmpb, f1, carry, wide);
    }

    if (!Cord(tmpa, tmpb, tmpc, carry, wide, flags)) {
        return {ax, dx, true};
    }
    std::uint16_t quotient = static_cast<std::uint16_t>(~tmpc);  // 164/16c: COM1 tmpc
    std::uint16_t remainder = tmpa;

    if (is_signed) {
        // POSTIDIV (1c4-1cc). The carry out of CORD is the complemented
        // quotient's top bit, so a magnitude of 128 or 32768 traps here --
        // including the -128 and -32768 the register could have held.
        if (!carry) {
            return {ax, dx, true};
        }
        if (Msb(high, wide)) {  // the remainder takes the dividend's sign
            bool unused;
            remainder = Neg16(remainder, unused);
        }
        // F1 set means "negate": tmpc + 1 is -(~tmpc).
        quotient = f1 ? static_cast<std::uint16_t>(tmpc + 1) : static_cast<std::uint16_t>(~tmpc);
        SetFlag(flags, kCarry, false);  // 1cc: CCOF
        SetFlag(flags, kOverflow, false);
    }

    quotient &= Mask(wide);
    remainder &= Mask(wide);
    if (wide) {
        return {quotient, remainder, false};
    }
    return {static_cast<std::uint16_t>((remainder << 8) | quotient), dx, false};
}

}  // namespace

MulDivResult MulDiv(MulDivKind kind, std::uint16_t ax, std::uint16_t dx,
                    std::uint16_t operand, bool wide, bool negate, std::uint16_t& flags) {
    switch (kind) {
        case MulDivKind::kMul:
            return Multiply(false, ax, dx, operand, wide, negate, flags);
        case MulDivKind::kImul:
            return Multiply(true, ax, dx, operand, wide, negate, flags);
        case MulDivKind::kDiv:
            return Divide(false, ax, dx, operand, wide, negate, flags);
        default:  // kIdiv
            return Divide(true, ax, dx, operand, wide, negate, flags);
    }
}

}  // namespace i8086
