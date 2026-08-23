// OpenHardware - the 8086 multiply and divide group.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "muldiv.h"

#include "alu.h"

namespace i8086 {
namespace {

constexpr std::uint16_t Low(std::uint16_t value) { return value & 0x00FF; }

std::int32_t SignExtend(std::uint16_t value, bool wide) {
    return wide ? static_cast<std::int32_t>(static_cast<std::int16_t>(value))
                : static_cast<std::int32_t>(static_cast<std::int8_t>(value & 0xFF));
}

}  // namespace

MulDivResult MulDiv(MulDivKind kind, std::uint16_t ax, std::uint16_t dx,
                    std::uint16_t operand, bool wide, std::uint16_t& flags) {
    switch (kind) {
        case MulDivKind::kMul: {
            const std::uint32_t left = wide ? ax : Low(ax);
            const std::uint32_t right = wide ? operand : Low(operand);
            const std::uint32_t product = left * right;
            const std::uint16_t high = static_cast<std::uint16_t>(
                wide ? (product >> 16) : ((product >> 8) & 0xFF));

            // CF and OF are both "the high half is not empty", which is the
            // question a caller asks to find out whether the narrow result
            // was enough.
            const bool overflowed = high != 0;
            SetFlag(flags, kCarry, overflowed);
            SetFlag(flags, kOverflow, overflowed);
            // SF, ZF and PF are documented undefined and are not: they come
            // from the HIGH half, which is the last thing the shift-and-add
            // loop produces. AF is cleared. Measured exact over all 20,000
            // MUL cases at both widths -- from the low half instead, or left
            // carried, and the opcode scores about 6%.
            SetResultFlags(high, wide, flags);
            SetFlag(flags, kAuxCarry, false);
            if (wide) {
                return {static_cast<std::uint16_t>(product & 0xFFFF), high, false};
            }
            return {static_cast<std::uint16_t>(product & 0xFFFF), dx, false};
        }

        case MulDivKind::kImul: {
            const std::int32_t product = SignExtend(ax, wide) * SignExtend(operand, wide);
            const std::uint32_t bits = static_cast<std::uint32_t>(product);
            const std::uint16_t high = static_cast<std::uint16_t>(
                wide ? (bits >> 16) : ((bits >> 8) & 0xFF));

            // For a signed multiply the high half is redundant when it is
            // only the sign extension of the low one, so CF and OF ask
            // whether the product still fits in the narrow half.
            const std::int32_t narrow = wide
                ? static_cast<std::int32_t>(static_cast<std::int16_t>(bits & 0xFFFF))
                : static_cast<std::int32_t>(static_cast<std::int8_t>(bits & 0xFF));
            const bool overflowed = narrow != product;
            SetFlag(flags, kCarry, overflowed);
            SetFlag(flags, kOverflow, overflowed);
            if (wide) {
                return {static_cast<std::uint16_t>(bits & 0xFFFF), high, false};
            }
            return {static_cast<std::uint16_t>(bits & 0xFFFF), dx, false};
        }

        case MulDivKind::kDiv: {
            const std::uint32_t divisor = wide ? operand : Low(operand);
            if (divisor == 0) {
                return {ax, dx, true};
            }
            const std::uint32_t dividend =
                wide ? ((static_cast<std::uint32_t>(dx) << 16) | ax) : ax;
            const std::uint32_t quotient = dividend / divisor;
            const std::uint32_t remainder = dividend % divisor;
            // The quotient goes in the narrow half, so one that does not fit
            // traps rather than truncating. `DIV` by 1 on a large dividend is
            // the usual way to meet this.
            if (quotient > (wide ? 0xFFFFu : 0xFFu)) {
                return {ax, dx, true};
            }
            if (wide) {
                return {static_cast<std::uint16_t>(quotient),
                        static_cast<std::uint16_t>(remainder), false};
            }
            return {static_cast<std::uint16_t>((remainder << 8) | quotient), dx, false};
        }

        default: {  // kIdiv
            const std::int32_t divisor = SignExtend(operand, wide);
            if (divisor == 0) {
                return {ax, dx, true};
            }
            const std::int32_t dividend =
                wide ? static_cast<std::int32_t>((static_cast<std::uint32_t>(dx) << 16) | ax)
                     : static_cast<std::int32_t>(static_cast<std::int16_t>(ax));
            // C++ truncates towards zero and so does the part, so the
            // remainder takes the dividend's sign in both.
            const std::int32_t quotient = dividend / divisor;
            const std::int32_t remainder = dividend % divisor;
            const std::int32_t low = wide ? -32768 : -128;
            const std::int32_t high = wide ? 32767 : 127;
            if (quotient < low || quotient > high) {
                return {ax, dx, true};
            }
            if (wide) {
                return {static_cast<std::uint16_t>(quotient & 0xFFFF),
                        static_cast<std::uint16_t>(remainder & 0xFFFF), false};
            }
            return {static_cast<std::uint16_t>(((remainder & 0xFF) << 8) | (quotient & 0xFF)),
                    dx, false};
        }
    }
}

}  // namespace i8086
