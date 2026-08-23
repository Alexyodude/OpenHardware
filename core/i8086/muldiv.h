// OpenHardware - the 8086 multiply and divide group.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Same shape as alu.h, shift.h and bcd.h: a pure function of the registers it
// reads and the flags, with no Cpu. These four are the only instructions on
// the part whose result is wider than their operands, and the only ones other
// than AAM that can trap.

#ifndef OPENHARDWARE_I8086_MULDIV_H
#define OPENHARDWARE_I8086_MULDIV_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// The four arithmetic members of the F6/F7 group, by their modrm reg value.
enum class MulDivKind : std::uint8_t {
    kMul = 4,   ///< unsigned multiply
    kImul = 5,  ///< signed multiply
    kDiv = 6,   ///< unsigned divide
    kIdiv = 7,  ///< signed divide
};

struct MulDivResult {
    std::uint16_t ax = 0;
    std::uint16_t dx = 0;
    /// The divisor was zero, or the quotient will not fit in its half of the
    /// result. `ax` and `dx` are then whatever the caller passed in -- the
    /// part does not write a partial answer -- and the caller raises
    /// interrupt 0.
    bool divide_error = false;
};

/// One multiply or divide.
///
/// The operand is the r/m value the instruction named: for a byte operation
/// only its low half is read. The other operand is implicit -- AL or AX for
/// the multiplies, AX or DX:AX for the divides -- which is why this takes the
/// registers rather than two values.
///
/// **CF and OF mean "the result did not fit in the narrow half"** for the
/// multiplies, and are the only flags the manual defines for any of the four.
/// SF, ZF, PF and AF are documented undefined for all of them; muldiv.cc
/// records what each actually leaves.
MulDivResult MulDiv(MulDivKind kind, std::uint16_t ax, std::uint16_t dx,
                    std::uint16_t operand, bool wide, std::uint16_t& flags);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_MULDIV_H
