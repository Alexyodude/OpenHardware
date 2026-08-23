// OpenHardware - 8086 arithmetic and the flags it produces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "alu.h"

namespace i8086 {

bool EvenParity(std::uint8_t value) {
    // Fold the byte down to one bit. Faster than a loop and, more usefully,
    // has no loop bound to get wrong.
    value ^= static_cast<std::uint8_t>(value >> 4);
    value ^= static_cast<std::uint8_t>(value >> 2);
    value ^= static_cast<std::uint8_t>(value >> 1);
    return (value & 1) == 0;
}

void SetResultFlags8(std::uint8_t result, std::uint16_t& flags) {
    SetFlag(flags, kZero, result == 0);
    SetFlag(flags, kSign, (result & 0x80) != 0);
    SetFlag(flags, kParity, EvenParity(result));
}

std::uint8_t Add8(std::uint8_t left, std::uint8_t right, std::uint16_t& flags) {
    const std::uint16_t wide = static_cast<std::uint16_t>(left) + right;
    const std::uint8_t result = static_cast<std::uint8_t>(wide);

    SetFlag(flags, kCarry, wide > 0xFF);
    // AF is the carry out of bit 3. XOR-ing the operands with the result
    // leaves exactly the bits where a carry entered, so bit 4 answers it.
    SetFlag(flags, kAuxCarry, ((left ^ right ^ result) & 0x10) != 0);
    // OF is signed overflow, which is a different question to CF: it happens
    // only when both operands share a sign and the result does not.
    SetFlag(flags, kOverflow, ((left ^ result) & (right ^ result) & 0x80) != 0);
    SetResultFlags8(result, flags);
    return result;
}

}  // namespace i8086
