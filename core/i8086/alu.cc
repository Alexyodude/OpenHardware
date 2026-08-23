// OpenHardware - 8086 arithmetic and the flags it produces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "alu.h"

namespace i8086 {
namespace {

constexpr std::uint16_t SignBit(bool wide) { return wide ? 0x8000u : 0x80u; }
constexpr std::uint32_t WidthMask(bool wide) { return wide ? 0xFFFFu : 0xFFu; }

/// CF, AF and OF for an addition. Shared by ADD and ADC, which differ only in
/// the carry that goes in.
void AddFlags(std::uint32_t left, std::uint32_t right, std::uint32_t carry_in,
              std::uint32_t result, bool wide, std::uint16_t& flags) {
    const std::uint32_t mask = WidthMask(wide);
    const std::uint16_t sign = SignBit(wide);

    SetFlag(flags, kCarry, (left + right + carry_in) > mask);
    // AF is the carry out of bit 3. XOR-ing the operands with the result
    // leaves exactly the bits a carry entered, so bit 4 answers it.
    SetFlag(flags, kAuxCarry, ((left ^ right ^ result) & 0x10u) != 0);
    // OF is signed overflow, a different question to CF: it happens only when
    // both operands share a sign and the result does not.
    SetFlag(flags, kOverflow, ((~(left ^ right) & (left ^ result)) & sign) != 0);
}

/// CF, AF and OF for a subtraction. Shared by SUB, SBB and CMP.
void SubFlags(std::uint32_t left, std::uint32_t right, std::uint32_t borrow_in,
              std::uint32_t result, bool wide, std::uint16_t& flags) {
    const std::uint16_t sign = SignBit(wide);

    SetFlag(flags, kCarry, (right + borrow_in) > left);
    SetFlag(flags, kAuxCarry, ((left ^ right ^ result) & 0x10u) != 0);
    // For subtraction the operands must DIFFER in sign for overflow to be
    // possible, which is the mirror of the addition rule above.
    SetFlag(flags, kOverflow, (((left ^ right) & (left ^ result)) & sign) != 0);
}

}  // namespace

bool EvenParity(std::uint8_t value) {
    // Fold the byte down to one bit. Faster than a loop and, more usefully,
    // has no loop bound to get wrong.
    value ^= static_cast<std::uint8_t>(value >> 4);
    value ^= static_cast<std::uint8_t>(value >> 2);
    value ^= static_cast<std::uint8_t>(value >> 1);
    return (value & 1) == 0;
}

void SetResultFlags(std::uint16_t result, bool wide, std::uint16_t& flags) {
    const std::uint16_t masked = wide ? result : static_cast<std::uint16_t>(result & 0xFF);
    SetFlag(flags, kZero, masked == 0);
    SetFlag(flags, kSign, (masked & SignBit(wide)) != 0);
    // PF is the parity of the LOW BYTE, at either width.
    SetFlag(flags, kParity, EvenParity(static_cast<std::uint8_t>(result & 0xFF)));
}

std::uint16_t Alu(AluKind kind, std::uint16_t left, std::uint16_t right, bool wide,
                  std::uint16_t& flags) {
    const std::uint32_t mask = WidthMask(wide);
    const std::uint32_t a = left & mask;
    const std::uint32_t b = right & mask;
    const std::uint32_t carry_in = HasFlag(flags, kCarry) ? 1u : 0u;
    std::uint32_t wide_result = 0;

    switch (kind) {
        case AluKind::kAdd:
            wide_result = (a + b) & mask;
            AddFlags(a, b, 0, wide_result, wide, flags);
            break;
        case AluKind::kAdc:
            wide_result = (a + b + carry_in) & mask;
            AddFlags(a, b, carry_in, wide_result, wide, flags);
            break;
        case AluKind::kSub:
        case AluKind::kCmp:
            wide_result = (a - b) & mask;
            SubFlags(a, b, 0, wide_result, wide, flags);
            break;
        case AluKind::kSbb:
            wide_result = (a - b - carry_in) & mask;
            SubFlags(a, b, carry_in, wide_result, wide, flags);
            break;
        case AluKind::kOr:
        case AluKind::kAnd:
        case AluKind::kXor:
            wide_result = kind == AluKind::kOr    ? (a | b)
                        : kind == AluKind::kAnd   ? (a & b)
                                                  : (a ^ b);
            // Logicals clear CF, OF **and AF**.
            //
            // The manual calls AF "undefined" after a logical operation, and
            // an implementation that takes that literally leaves it alone.
            // The silicon does not: across 60,000 corpus cases for OR, AND
            // and XOR, AF was set beforehand in roughly half and set
            // afterwards in **zero**. It is cleared, unconditionally.
            //
            // Leaving it carried cost 50% of every logical opcode -- passing
            // exactly the cases where AF happened to be clear already.
            // Undefined in the manual is not undefined in the part.
            SetFlag(flags, kCarry, false);
            SetFlag(flags, kOverflow, false);
            SetFlag(flags, kAuxCarry, false);
            break;
    }

    SetResultFlags(static_cast<std::uint16_t>(wide_result), wide, flags);
    return static_cast<std::uint16_t>(wide_result);
}

}  // namespace i8086
