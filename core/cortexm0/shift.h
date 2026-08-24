// OpenHardware — Armv6-M shifts and their carry-out.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Its own module because six instruction forms share it -- LSLS/LSRS/ASRS in
// both the immediate and the register encodings, plus RORS -- and because this
// is where an Armv6-M core is hardest to get right. Three of the four bugs
// gdbdiff found in rp2040js against real silicon were here: ADCS overflow, CMP
// carry, and LSRS edges.
//
// The rules below are ARM DDI0419 A6.3.1 (`Shift_C`), and every one of the
// special cases is a place where the obvious implementation is wrong:
//
//   * **A shift of zero leaves the carry alone.** It does not clear it. `x >>
//     0` is a no-op in C and the flag update is not, so writing this as a
//     single expression silently corrupts C for every `LSLS Rd, Rm, #0`.
//   * **`imm5 == 0` does not mean "shift by zero" for LSR and ASR.** It
//     encodes a shift of *32*, which C cannot express: `x >> 32` on a uint32_t
//     is undefined behaviour, and on x86 it commonly compiles to `x >> 0`,
//     which returns `x` instead of 0. That is the classic silent-wrong case,
//     and it is why `amount` here is a full uint32_t that this code range-
//     checks rather than a shift the compiler is trusted with.
//   * **The register forms take the whole low byte of Rs**, so amounts up to
//     255 are legal and must saturate rather than wrap.
//   * **ROR by a non-zero multiple of 32 is not a no-op**: the result is
//     unchanged but the carry becomes bit 31.

#ifndef OPENHARDWARE_CORTEXM0_SHIFT_H
#define OPENHARDWARE_CORTEXM0_SHIFT_H

#include <stdint.h>

namespace cortexm0 {

/// A shifted value and the carry it produced.
///
/// `carry` is returned rather than written through a pointer so a caller
/// cannot forget it. An earlier design in the i8086 core made the flag an
/// out-parameter and the compiler was happy to let callers ignore it.
struct Shifted {
    uint32_t value;
    bool carry;
};

/// Logical left. `amount` may be any value; 32 and above give zero.
Shifted lsl(uint32_t value, uint32_t amount, bool carry_in);

/// Logical right. `amount` of 32 gives zero with carry from bit 31.
Shifted lsr(uint32_t value, uint32_t amount, bool carry_in);

/// Arithmetic right. Saturates at 32: the result is all sign bits.
Shifted asr(uint32_t value, uint32_t amount, bool carry_in);

/// Rotate right. Only the low five bits of `amount` move bits, but a non-zero
/// `amount` always sets the carry from bit 31 of the result.
Shifted ror(uint32_t value, uint32_t amount, bool carry_in);

/// One 32-bit add with carry in and both flags out.
///
/// Every add, subtract and compare in the instruction set goes through this,
/// because subtraction on Arm *is* `x + ~y + 1` and implementing it any other
/// way makes the borrow and the overflow disagree with the hardware at the
/// edges. `CMP` is a `SUBS` that discards its result, and `NEGS Rd, Rn` is
/// `0 + ~Rn + 1`.
struct Sum {
    uint32_t value;
    bool carry;
    bool overflow;
};

Sum add_with_carry(uint32_t x, uint32_t y, bool carry_in);

}  // namespace cortexm0

#endif
