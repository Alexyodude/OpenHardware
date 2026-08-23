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

/// The two repeat prefixes.
///
/// F3 is spelled REP before MOVS, STOS and LODS and REPE/REPZ before CMPS and
/// SCAS; F2 is REPNE/REPNZ before the compares and, confusingly, plain REP
/// before the others -- the corpus disassembles `F2 A4` as `rep movsb`. They
/// are one mechanism with two names, so this enum names the *condition*
/// rather than either mnemonic: on the instructions that set ZF the loop runs
/// while ZF matches, and on the ones that do not, both simply run CX times.
enum class Rep : std::uint8_t {
    kNone = 0,
    kWhileZero = 1,     ///< F3
    kWhileNotZero = 2,  ///< F2
};

/// The repeat prefix bytes.
constexpr std::uint8_t kPrefixRepNz = 0xF2;
constexpr std::uint8_t kPrefixRepZ = 0xF3;

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
    /// The repeat prefix, or kNone. Only the string instructions read it; on
    /// anything else the prefix is accepted, counted in `length`, and has no
    /// effect, which is what the part does.
    Rep repeat = Rep::kNone;
    /// Total length including prefixes. IP advances by exactly this, so an
    /// error here desynchronises every following instruction.
    std::uint8_t length = 0;
    /// The instruction's immediate operand, read according to its form.
    ///
    /// * kRel8, kRel16 -- **signed**, and relative to the END of this
    ///   instruction. `74 71` is "jump 0x71 bytes past the byte after the 71".
    /// * kImm8 -- the **unsigned** byte exactly as encoded, 0 to 255. A port
    ///   number is not negative and neither is an AAM divisor.
    /// * kGroup3 -- for `/0` and `/1` only, TEST's immediate at the
    ///   instruction's width. Read back masked: a 16-bit 0xFFFF is stored
    ///   here as -1 and is not one.
    ///
    /// One field rather than two because the bytes are the same bytes and a
    /// second field would be unused for every form but one. The sign lives in
    /// the reader, and the two readers are three lines apart in Decode.
    std::int16_t immediate = 0;
    /// For kRegInOpcode: the register the low three opcode bits name.
    std::uint8_t reg_in_opcode = 0;
    /// 16-bit operands, copied from the table so the executor need not look
    /// the opcode up a second time.
    bool wide = false;
    /// False when the prefix run exceeded kMaxLength and no opcode was ever
    /// reached. Execution must refuse an invalid instruction rather than run
    /// whatever byte the scan stopped on. See kMaxLength.
    bool valid = true;
};

/// The longest instruction this decoder will accept, in bytes.
///
/// The 8086 has no architectural limit -- its bus unit will consume prefixes
/// forever -- so a decoder needs one or a page of 0x2E bytes is an infinite
/// loop. 15 is the limit later x86 parts adopted, and is comfortably longer
/// than any real 8086 instruction (opcode + modrm + disp16 + imm16 is 6, plus
/// prefixes).
///
/// Exceeding it marks the instruction **invalid** rather than stopping and
/// treating the byte it stopped on as an opcode. The first version did the
/// latter: seven segment prefixes decoded as `opcode 2E, length 7`, silently
/// producing a wrong instruction instead of refusing one.
inline constexpr int kMaxLength = 15;

/// A computed memory operand.
struct Address {
    Segment segment = Segment::kDs;  ///< after any override is applied
    std::uint16_t offset = 0;
};

/// The shape of an instruction's operands, which is what decides its length.
enum class Form : std::uint8_t {
    kNone = 0,          ///< opcode only (NOP, RET)
    kModRm = 1,         ///< a modrm byte, and whatever displacement it implies
    kRel8 = 2,          ///< one signed byte, relative to the next instruction
    kRel16 = 3,         ///< two bytes, relative to the next instruction
    kRegInOpcode = 4,   ///< the low three bits name a register (PUSH/POP)
    kImm8 = 5,          ///< one unsigned byte (a port number, an AAM divisor)
    /// F6/F7: a modrm, plus an immediate for `/0` and `/1` only.
    ///
    /// The one form whose LENGTH depends on the modrm byte. TEST takes an
    /// immediate and the other six members of the group do not, so `Lookup`
    /// alone cannot say how long an F6 is -- only the decoder, after it has
    /// read the modrm, can. That is why this is its own form rather than a
    /// flag on kModRm.
    kGroup3 = 6,
    kImm16 = 7,      ///< two bytes, unsigned (ALU AX,imm16 and TEST AX,imm16)
    /// A modrm, then an immediate at the operand width. 80/81/82/83 and
    /// C6/C7. **0x83 is the exception**: it has 16-bit operands but an 8-bit
    /// immediate, sign-extended, which is how `ADD word ptr [bx], -1` fits in
    /// three bytes. Handled by name in Decode rather than by a form of its
    /// own, because a form with one member is a worse way to say "exception".
    kModRmImm = 8,
    /// The low three opcode bits name a register and an immediate follows,
    /// at the operand width. B0-BF.
    kRegImm = 9,
    /// A 16-bit direct address and no modrm, kept in `displacement`. A0-A3,
    /// the short forms of MOV to and from the accumulator.
    kMoffs = 10,
};

/// What the decoder and the executor both need to know about an opcode.
///
/// **One table, consulted by both.** These were two lists -- a switch in
/// `OpcodeHasModRm` and a switch in `Step` -- and nothing connected them. Add
/// an opcode to the executor and forget the decoder and it decodes at the
/// wrong length, so IP lands mid-instruction and everything after it is
/// garbage. Nothing would have failed at compile time, and the corpus case
/// for that opcode would fail in a way that looks like an arithmetic bug.
///
/// With ~200 opcodes still to add, that desync is a matter of when.
struct OpcodeInfo {
    bool implemented = false;
    Form form = Form::kNone;
    /// 16-bit operands. For most of the map this is opcode bit 0, but it is
    /// stated per entry rather than computed, because the exceptions (PUSH,
    /// the string ops, the far jumps) outnumber a rule worth trusting.
    bool wide = false;

    /// Whether a modrm byte follows the opcode.
    ///
    /// Three forms carry one, and this must name all three: kModRm, kGroup3
    /// (F6/F7) and kModRmImm (80-83, C6/C7). It listed only the first two
    /// when kModRmImm was added, so `i8086_opcode_info` reported 0x83 as
    /// having no modrm -- decoding was unaffected, because Decode switches on
    /// the form itself, but every caller of the ABI got a wrong answer. A
    /// disassembler is exactly such a caller.
    bool has_modrm() const {
        return form == Form::kModRm || form == Form::kGroup3 ||
               form == Form::kModRmImm;
    }
};

/// Properties of an opcode. Unknown opcodes report `implemented = false`.
OpcodeInfo Lookup(std::uint8_t opcode);

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
