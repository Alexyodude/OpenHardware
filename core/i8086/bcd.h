// OpenHardware - the 8086 decimal adjust and ASCII adjust instructions.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Same shape as alu.h and shift.h: a pure function of AX, an immediate and
// the flags. No Cpu, no memory. These six touch only AX, which is what makes
// that shape fit -- and what makes them the easiest family in the ISA to get
// subtly wrong, because nothing else moves to disagree with.

#ifndef OPENHARDWARE_I8086_BCD_H
#define OPENHARDWARE_I8086_BCD_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// The six adjust instructions.
///
/// DAA/DAS fix up a *packed* BCD byte after an add or subtract -- two digits
/// in one byte. AAA/AAS fix up an *unpacked* one -- one digit per byte, with
/// the tens digit carried into AH. AAM and AAD convert between the two, and
/// are the only pair that takes an operand.
enum class BcdKind : std::uint8_t {
    kDaa = 0,  ///< 27, decimal adjust after addition
    kDas = 1,  ///< 2F, decimal adjust after subtraction
    kAaa = 2,  ///< 37, ASCII adjust after addition
    kAas = 3,  ///< 3F, ASCII adjust after subtraction
    kAam = 4,  ///< D4 imm8, "multiply" -- actually AL / imm8 into AH:AL
    kAad = 5,  ///< D5 imm8, "divide" -- actually AH * imm8 + AL into AL
};

struct BcdResult {
    std::uint16_t ax = 0;
    /// AAM with a zero divisor.
    ///
    /// `ax` and `flags` are still meaningful when this is set: hardware
    /// computes both **before** it traps, leaving AX untouched and the flags
    /// as though the result had been zero. The caller raises interrupt 0
    /// afterwards, because dispatching one needs a Cpu and this file has none.
    bool divide_error = false;
};

/// One adjust, updating `flags`. `immediate` is read only by AAM and AAD.
///
/// ## What the manual leaves undefined here
///
/// A great deal. AAA and AAS define only CF and AF; DAA and DAS leave OF
/// undefined; AAM and AAD leave CF, OF and AF undefined. Every one of those
/// is pinned against the corpus instead -- see bcd.cc, where each rule cites
/// what was measured.
BcdResult Bcd(BcdKind kind, std::uint16_t ax, std::uint8_t immediate,
              std::uint16_t& flags);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_BCD_H
