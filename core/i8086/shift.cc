// OpenHardware - the 8086 shift and rotate group.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "shift.h"

#include "alu.h"

namespace i8086 {
namespace {

constexpr std::uint16_t SignBit(bool wide) { return wide ? 0x8000u : 0x0080u; }
constexpr std::uint16_t WidthMask(bool wide) { return wide ? 0xFFFFu : 0x00FFu; }

/// The bit below the sign, which is what OF compares against for the right
/// rotates: they are "did the top two bits stop agreeing".
constexpr std::uint16_t NextSignBit(bool wide) { return wide ? 0x4000u : 0x0040u; }

bool IsRotate(ShiftKind kind) {
    return kind == ShiftKind::kRol || kind == ShiftKind::kRor ||
           kind == ShiftKind::kRcl || kind == ShiftKind::kRcr;
}

}  // namespace

std::uint16_t Shift(ShiftKind kind, std::uint16_t value, std::uint8_t count,
                    bool wide, std::uint16_t& flags) {
    const std::uint16_t mask = WidthMask(wide);
    const std::uint16_t sign = SignBit(wide);
    const std::uint16_t next_sign = NextSignBit(wide);
    std::uint16_t result = static_cast<std::uint16_t>(value & mask);

    // Zero count, nothing happens -- see the header. This is checked before
    // anything else because every rule below assumes at least one iteration.
    if (count == 0) {
        return result;
    }

    if (kind == ShiftKind::kSetmo) {
        // Not a shift. The destination becomes all ones regardless of what it
        // held or how large the count was.
        result = mask;
        SetFlag(flags, kCarry, false);
        SetFlag(flags, kOverflow, false);
        SetFlag(flags, kAuxCarry, false);
        SetResultFlags(result, wide, flags);
        return result;
    }

    bool carry = HasFlag(flags, kCarry);
    bool overflow = HasFlag(flags, kOverflow);
    // AF is documented undefined for every operation here. It is not
    // undefined in the part -- see SetAuxCarry below for what was measured.
    bool aux = HasFlag(flags, kAuxCarry);

    // One bit at a time, `count` times. OF is recomputed every iteration
    // because that is what the microcode does -- the manual only defines it
    // for a count of 1, and what a longer count leaves behind is whatever the
    // last iteration computed.
    for (std::uint8_t i = 0; i < count; ++i) {
        const std::uint16_t before = result;
        switch (kind) {
            case ShiftKind::kRol: {
                const bool high = (before & sign) != 0;
                result = static_cast<std::uint16_t>(((before << 1) | (high ? 1u : 0u)) & mask);
                carry = high;
                overflow = ((result & sign) != 0) != carry;
                break;
            }
            case ShiftKind::kRor: {
                const bool low = (before & 1u) != 0;
                result = static_cast<std::uint16_t>(((before >> 1) | (low ? sign : 0u)) & mask);
                carry = low;
                overflow = ((result & sign) != 0) != ((result & next_sign) != 0);
                break;
            }
            case ShiftKind::kRcl: {
                const bool high = (before & sign) != 0;
                result = static_cast<std::uint16_t>(((before << 1) | (carry ? 1u : 0u)) & mask);
                carry = high;
                overflow = ((result & sign) != 0) != carry;
                break;
            }
            case ShiftKind::kRcr: {
                const bool low = (before & 1u) != 0;
                result = static_cast<std::uint16_t>(((before >> 1) | (carry ? sign : 0u)) & mask);
                carry = low;
                overflow = ((result & sign) != 0) != ((result & next_sign) != 0);
                break;
            }
            case ShiftKind::kShl: {
                carry = (before & sign) != 0;
                result = static_cast<std::uint16_t>((before << 1) & mask);
                overflow = ((result & sign) != 0) != carry;
                // SHL is ADD dest,dest -- a left shift by one IS the value
                // added to itself -- and it produces ADD's AF: the carry out
                // of bit 3. For equal operands `(a ^ a ^ result) & 0x10`
                // reduces to `result & 0x10`, so this is that rule, not a
                // different one that happens to agree.
                aux = (result & 0x10u) != 0;
                break;
            }
            case ShiftKind::kShr: {
                carry = (before & 1u) != 0;
                result = static_cast<std::uint16_t>(before >> 1);
                // SHR shifts a zero in, so OF is "was the sign bit lost",
                // which is the sign of the value entering this iteration.
                overflow = (before & sign) != 0;
                aux = false;
                break;
            }
            case ShiftKind::kSar: {
                carry = (before & 1u) != 0;
                result = static_cast<std::uint16_t>(((before >> 1) | (before & sign)) & mask);
                // SAR preserves the sign, so it can never overflow.
                overflow = false;
                aux = false;
                break;
            }
            case ShiftKind::kSetmo:
                break;  // handled above; unreachable
        }
    }

    SetFlag(flags, kCarry, carry);
    SetFlag(flags, kOverflow, overflow);
    if (!IsRotate(kind)) {
        // The rotates move bits without producing a "result" in the ALU
        // sense, and leave ZF, SF and PF exactly as they were. They leave AF
        // alone too, which is why `aux` starts from the incoming flag.
        SetResultFlags(result, wide, flags);
        SetFlag(flags, kAuxCarry, aux);
    }
    return result;
}

}  // namespace i8086
