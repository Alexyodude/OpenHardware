// OpenHardware - the 8086 shift and rotate group, and the flags it produces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Same shape as alu.h and for the same reason: a pure function of a value, a
// count and the flags, with no Cpu and no memory in sight. Operand resolution
// is exec_core.cc's job. That split is what lets these be checked against
// every operand pair without an addressing mode anywhere near the test.
//
// Flags here are worse than the ALU's. The manual leaves OF undefined for any
// count but 1 and AF undefined always, and hardware still produces something
// for both. Every rule below is measured against SST8088; where a comment
// says "measured", it means the corpus was queried, not that a manual was
// read.

#ifndef OPENHARDWARE_I8086_SHIFT_H
#define OPENHARDWARE_I8086_SHIFT_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// The eight members of the D0-D3 group, in modrm-reg order.
///
/// `/6` is **SETMO**, which sets the destination to all ones. It is
/// undocumented -- the Intel manual lists `/4` twice, as SHL and SAL, and says
/// nothing about `/6`. The SST8088 corpus names it `setmo` (and `setmoc` for
/// the CL-counted forms, which do nothing when CL is zero) across 30,000
/// hardware-captured cases, which is the entire argument for having an oracle
/// that is silicon rather than a document.
enum class ShiftKind : std::uint8_t {
    kRol = 0, kRor = 1, kRcl = 2, kRcr = 3,
    kShl = 4, kShr = 5, kSetmo = 6, kSar = 7,
};

/// One shift or rotate, at either width, setting the flags it defines.
///
/// **A count of zero does nothing at all**, including to the flags. That is
/// not a shortcut: `D2 /4` with CL=0 leaves every flag as it was, and a core
/// that computes flags from an unshifted value clears CF where hardware
/// preserved it.
///
/// The count is **not masked**. Later x86 parts take it modulo 32; the 8086
/// does not. This loops rather than reducing modulo the period, because the
/// loop is what the microcode does and because a closed form has to get OF --
/// which is recomputed every iteration -- right by argument rather than by
/// construction.
///
/// Measured, not assumed: the corpus reaches CL=62, and RCL is the one member
/// that can tell the two apart. Its period is 9 rather than 8, so 62 is 8
/// rotations and a masked 30 would be 3. SHL, SHR, SAR, ROL and ROR all give
/// the same answer either way, which is why a core with a 5-bit mask still
/// passes five of the eight.
///
/// ## What the corpus does not reach
///
/// D2/D3 use **even CL values only, 0 to 62** -- 32 distinct counts out of
/// 256. So odd counts above 1 and every count above 62 are unverified here.
/// The one-bit-at-a-time loop is what makes that acceptable: it has no
/// special case that could distinguish 63 from 62 in the first place.
///
/// ## AF, which the manual calls undefined for all eight
///
/// It is not undefined in the part, and it is not one rule either:
///
/// * SHL **sets** it, from bit 4 of the result -- measured set in 4982 of
///   10,000 D0.4 cases. SHL is ADD dest,dest and produces ADD's AF.
/// * SHR and SAR **clear** it -- measured clear in 10,000 of 10,000 each.
/// * SETMO clears it.
/// * The four rotates leave it alone, along with ZF, SF and PF.
///
/// Assuming one rule for all eight, in either direction, costs about half of
/// three files. See `docs/HANDOFF_2026-08-23_i8086-core.md` section 2.1 for
/// the same shape of divergence on the logical operations.
std::uint16_t Shift(ShiftKind kind, std::uint16_t value, std::uint8_t count,
                    bool wide, std::uint16_t& flags);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_SHIFT_H
