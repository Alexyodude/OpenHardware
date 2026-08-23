// OpenHardware - 8086 arithmetic and the flags it produces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Flags are where an x86 core is most often subtly wrong, because the result
// of an operation can be right while the flags it sets are not, and nothing
// notices until a conditional jump goes the wrong way thousands of
// instructions later.
//
// Every rule here is checked against SST8088, which is hardware. Where this
// disagrees with a manual, the hardware wins.

#ifndef OPENHARDWARE_I8086_ALU_H
#define OPENHARDWARE_I8086_ALU_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// True when the low byte has an even number of set bits.
///
/// PF is set on EVEN parity, which reads backwards to anyone expecting a
/// "parity error" flag, and it considers only the low 8 bits even for 16-bit
/// operations.
bool EvenParity(std::uint8_t value);

/// Set or clear one flag.
inline void SetFlag(std::uint16_t& flags, std::uint16_t mask, bool value) {
    flags = value ? static_cast<std::uint16_t>(flags | mask)
                  : static_cast<std::uint16_t>(flags & ~mask);
}

inline bool GetFlag(std::uint16_t flags, std::uint16_t mask) { return (flags & mask) != 0; }

/// ZF, SF and PF from an 8-bit result. Shared by every operation that sets
/// them the same way, which is most of them.
void SetResultFlags8(std::uint8_t result, std::uint16_t& flags);

/// 8-bit addition, setting CF, PF, AF, ZF, SF and OF.
///
/// CF is the unsigned carry out of bit 7; OF is the signed overflow, which is
/// a different question and a different answer -- 0x7F + 0x01 overflows
/// signed and does not carry unsigned. A core that conflates them passes
/// every test using small positive numbers.
std::uint8_t Add8(std::uint8_t left, std::uint8_t right, std::uint16_t& flags);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_ALU_H
