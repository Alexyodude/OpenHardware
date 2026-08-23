// OpenHardware - 8086 instruction decode: prefixes, modrm, displacement.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Decode only. Nothing here reads or writes memory through an operand or
// touches flags -- that is execution, and it lives in exec_core.cc. Keeping
// the split means the addressing-mode table can be tested exhaustively
// against the Intel table without an executable instruction in sight.

#ifndef OPENHARDWARE_I8086_DECODE_H
#define OPENHARDWARE_I8086_DECODE_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// Which segment register an access uses.
enum class Segment : std::uint8_t { kEs = 0, kCs = 1, kSs = 2, kDs = 3, kNone = 4 };

/// The four segment-override prefixes, by opcode byte.
constexpr std::uint8_t kPrefixEs = 0x26;
constexpr std::uint8_t kPrefixCs = 0x2E;
constexpr std::uint8_t kPrefixSs = 0x36;
constexpr std::uint8_t kPrefixDs = 0x3E;

/// Segment for a prefix byte, or kNone if the byte is not one.
constexpr Segment SegmentForPrefix(std::uint8_t byte) {
    switch (byte) {
        case kPrefixEs: return Segment::kEs;
        case kPrefixCs: return Segment::kCs;
        case kPrefixSs: return Segment::kSs;
        case kPrefixDs: return Segment::kDs;
        default: return Segment::kNone;
    }
}

/// The mod-reg-rm byte, split.
struct ModRm {
    std::uint8_t mod = 0;  ///< 0 memory, 1 memory+disp8, 2 memory+disp16, 3 register
    std::uint8_t reg = 0;  ///< the register operand, or an opcode extension
    std::uint8_t rm = 0;   ///< the register-or-memory operand

    static constexpr ModRm From(std::uint8_t byte) {
        return ModRm{static_cast<std::uint8_t>((byte >> 6) & 0x03),
                     static_cast<std::uint8_t>((byte >> 3) & 0x07),
                     static_cast<std::uint8_t>(byte & 0x07)};
    }

    /// mod 3 means both operands are registers and no address is computed.
    constexpr bool is_register() const { return mod == 3; }
};

/// One decoded instruction, and how many bytes it occupied.
struct Instruction {
    std::uint8_t opcode = 0;
    bool has_modrm = false;
    ModRm modrm;
    std::int16_t displacement = 0;
    /// The override a prefix asked for, or kNone. Not the segment finally
    /// used -- that also depends on the addressing mode. See EffectiveAddress.
    Segment segment_override = Segment::kNone;
    /// Total length including prefixes. IP advances by exactly this, so an
    /// error here desynchronises every following instruction.
    std::uint8_t length = 0;
};

/// A computed memory operand.
struct Address {
    Segment segment = Segment::kDs;  ///< after any override is applied
    std::uint16_t offset = 0;
};

/// Whether an instruction's opcode takes a modrm byte.
bool OpcodeHasModRm(std::uint8_t opcode);

/// Read one instruction starting at cs:ip.
///
/// Fetches wrap inside the segment: the 8086 adds to IP as a 16-bit quantity,
/// so an instruction beginning at 0xFFFF continues at offset 0 of the same
/// segment rather than running into the next one.
Instruction Decode(const Cpu& cpu, std::uint16_t cs, std::uint16_t ip);

/// Segment and offset for a memory operand.
///
/// The default segment is SS for any mode that uses BP and DS otherwise --
/// the 8086 assumes a BP-relative access is a stack frame. An override
/// replaces that default, which is what makes `3E 88 02` meaningful: [bp+si]
/// would use SS, and the 3E prefix forces DS.
Address EffectiveAddress(const Registers& regs, const ModRm& modrm,
                         std::int16_t displacement, Segment override_segment);

/// The value held in a segment register.
std::uint16_t SegmentValue(const Registers& regs, Segment segment);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_DECODE_H
