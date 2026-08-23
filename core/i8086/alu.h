// OpenHardware - 8086 arithmetic and the flags it produces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Flags are where an x86 core is most often subtly wrong: the result of an
// operation can be right while the flags it sets are not, and nothing notices
// until a conditional jump goes the wrong way thousands of instructions later.
//
// Every rule here is checked against SST8088, which is hardware. Where this
// disagrees with a manual, the hardware wins.

#ifndef OPENHARDWARE_I8086_ALU_H
#define OPENHARDWARE_I8086_ALU_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// The eight operations in the 0x00-0x3F group, in encoding order. The opcode
/// names them in bits 5:3, so this enum's values are that field.
enum class AluKind : std::uint8_t {
    kAdd = 0, kOr = 1, kAdc = 2, kSbb = 3,
    kAnd = 4, kSub = 5, kXor = 6, kCmp = 7,
};

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

inline bool HasFlag(std::uint16_t flags, std::uint16_t mask) { return (flags & mask) != 0; }

/// ZF, SF and PF from a result. `wide` selects which bit is the sign.
void SetResultFlags(std::uint16_t result, bool wide, std::uint16_t& flags);

/// One ALU operation, at either width, setting the flags it defines.
///
/// Returns the result. CMP returns the difference like SUB does -- it is SUB
/// without the write-back, and deciding not to store it is the executor's job,
/// not this function's.
///
/// The logical operations (AND/OR/XOR/TEST) **clear CF and OF outright** and
/// leave AF undefined. That is not an accident of implementation: hardware
/// does it, and a core that carries CF through a logical op diverges on the
/// first conditional that follows one.
std::uint16_t Alu(AluKind kind, std::uint16_t left, std::uint16_t right, bool wide,
                  std::uint16_t& flags);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_ALU_H
