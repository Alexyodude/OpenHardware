// OpenHardware — Armv6-M shifts and their carry-out.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "shift.h"

namespace cortexm0 {
namespace {

/// Bit `n` of `value`, for `n` under 32. The shifts below never call this with
/// anything larger; each one range-checks first, because `1u << 32` is
/// undefined behaviour and not the zero it looks like.
inline bool bit(uint32_t value, uint32_t n) {
    return ((value >> n) & 1u) != 0;
}

}  // namespace

Shifted lsl(uint32_t value, uint32_t amount, bool carry_in) {
    if (amount == 0) {
        // Not `value << 0`. The distinction is the flag: a shift of zero must
        // leave the carry exactly as it was.
        return {value, carry_in};
    }
    if (amount > 32) {
        return {0, false};
    }
    if (amount == 32) {
        // Separated from the general case because `value << 32` is undefined
        // behaviour, and on x86 the shift count is masked to 5 bits, so it
        // evaluates to `value << 0` -- the value unchanged, which is the
        // opposite of the right answer.
        return {0, bit(value, 0)};
    }
    return {value << amount, bit(value, 32 - amount)};
}

Shifted lsr(uint32_t value, uint32_t amount, bool carry_in) {
    if (amount == 0) {
        return {value, carry_in};
    }
    if (amount > 32) {
        return {0, false};
    }
    if (amount == 32) {
        return {0, bit(value, 31)};
    }
    return {value >> amount, bit(value, amount - 1)};
}

Shifted asr(uint32_t value, uint32_t amount, bool carry_in) {
    if (amount == 0) {
        return {value, carry_in};
    }
    const bool sign = bit(value, 31);
    if (amount >= 32) {
        // Saturates rather than wrapping: shifting right by more than the
        // width leaves every bit equal to the sign, and the carry is that
        // same bit. Unlike LSL and LSR there is no "and beyond that, zero"
        // case, because the sign never shifts out.
        return {sign ? 0xFFFFFFFFu : 0u, sign};
    }
    // Arithmetic shift by hand. `>>` on a signed int is implementation-defined
    // before C++20, and this core is built as C++17 by three compilers.
    const uint32_t shifted = value >> amount;
    const uint32_t filled = sign ? (0xFFFFFFFFu << (32 - amount)) : 0u;
    return {shifted | filled, bit(value, amount - 1)};
}

Shifted ror(uint32_t value, uint32_t amount, bool carry_in) {
    if (amount == 0) {
        return {value, carry_in};
    }
    const uint32_t distance = amount % 32;
    // A non-zero multiple of 32 moves no bits and still sets the carry from
    // bit 31. Returning early on `distance == 0` as though nothing happened
    // is the bug this branch exists to avoid.
    const uint32_t rotated =
        distance == 0 ? value : (value >> distance) | (value << (32 - distance));
    return {rotated, bit(rotated, 31)};
}

Sum add_with_carry(uint32_t x, uint32_t y, bool carry_in) {
    const uint64_t unsigned_sum =
        static_cast<uint64_t>(x) + static_cast<uint64_t>(y) + (carry_in ? 1u : 0u);
    const int64_t signed_sum = static_cast<int64_t>(static_cast<int32_t>(x)) +
                               static_cast<int64_t>(static_cast<int32_t>(y)) +
                               (carry_in ? 1 : 0);
    const uint32_t result = static_cast<uint32_t>(unsigned_sum);

    // Straight from the ARM ARM's pseudocode, and deliberately not the
    // sign-comparison trick: carry is "the unsigned sum did not fit", and
    // overflow is "the signed sum did not fit". Computing both in 64 bits and
    // asking whether truncation changed the answer is the version that has no
    // edge cases to get wrong.
    return {result, unsigned_sum != static_cast<uint64_t>(result),
            signed_sum != static_cast<int64_t>(static_cast<int32_t>(result))};
}

}  // namespace cortexm0
