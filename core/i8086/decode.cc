// OpenHardware - 8086 instruction decode.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "decode.h"

namespace i8086 {
namespace {

/// Fetch a byte at cs:(ip + n), wrapping the offset inside the segment.
std::uint8_t FetchAt(const Cpu& cpu, std::uint16_t cs, std::uint16_t ip, int n) {
    const std::uint16_t offset = static_cast<std::uint16_t>(ip + n);
    return cpu.ReadByte(Physical(cs, offset));
}

/// The ALU group fills 0x00-0x3F in a regular pattern, and describing it as a
/// pattern rather than sixty-four table rows is what keeps the table readable
/// as the map fills in.
///
///   bits 5:3  operation:  ADD OR ADC SBB AND SUB XOR CMP
///   bits 2:0  form:       0 r/m8,r8   1 r/m16,r16   2 r8,r/m8   3 r16,r/m16
///                         4 AL,imm8   5 AX,imm16    6,7 segment PUSH/POP
///
/// Only forms 0-3 are claimed here. 4 and 5 take an immediate, 6 and 7 are
/// segment-register stack ops; all four report unimplemented and are refused
/// rather than decoded at the wrong length.
bool IsAluModRmForm(std::uint8_t opcode) {
    return opcode < 0x40 && (opcode & 0x07) <= 0x03;
}

}  // namespace

OpcodeInfo Lookup(std::uint8_t opcode) {
    if (IsAluModRmForm(opcode)) {
        return {true, Form::kModRm, (opcode & 0x01) != 0};
    }
    // PUSH r16 (50-57) and POP r16 (58-5F). Always 16-bit: this part has no
    // byte form of either.
    if (opcode >= 0x50 && opcode <= 0x5F) {
        return {true, Form::kRegInOpcode, true};
    }
    // Jcc rel8, all sixteen conditions.
    if (opcode >= 0x70 && opcode <= 0x7F) {
        return {true, Form::kRel8, false};
    }
    // The shift/rotate group. D0/D1 shift by one, D2/D3 by CL, and in both
    // cases the count is implicit -- there is no immediate byte, so the form
    // is a plain modrm and the modrm's `reg` field picks the operation. See
    // ShiftKind in shift.h.
    if (opcode >= 0xD0 && opcode <= 0xD3) {
        return {true, Form::kModRm, (opcode & 0x01) != 0};
    }

    switch (opcode) {
        // MOV, following the same direction/width pattern as the ALU group.
        case 0x88: return {true, Form::kModRm, false};
        case 0x89: return {true, Form::kModRm, true};
        case 0x8A: return {true, Form::kModRm, false};
        case 0x8B: return {true, Form::kModRm, true};

        // Port I/O. The `imm8` forms carry the port number as a byte, so they
        // reach only ports 0-255; the DX forms reach all 65,536.
        case 0xE4: return {true, Form::kImm8, false};   // IN  AL, imm8
        case 0xE5: return {true, Form::kImm8, true};    // IN  AX, imm8
        case 0xE6: return {true, Form::kImm8, false};   // OUT imm8, AL
        case 0xE7: return {true, Form::kImm8, true};    // OUT imm8, AX
        case 0xEC: return {true, Form::kNone, false};   // IN  AL, DX
        case 0xED: return {true, Form::kNone, true};    // IN  AX, DX
        case 0xEE: return {true, Form::kNone, false};   // OUT DX, AL
        case 0xEF: return {true, Form::kNone, true};    // OUT DX, AX

        // The single-byte flag instructions. `wide` is meaningless for these
        // and is left false rather than guessed at.
        case 0xF5: return {true, Form::kNone, false};   // CMC
        case 0xF8: return {true, Form::kNone, false};   // CLC
        case 0xF9: return {true, Form::kNone, false};   // STC
        case 0xFA: return {true, Form::kNone, false};   // CLI
        case 0xFB: return {true, Form::kNone, false};   // STI
        case 0xFC: return {true, Form::kNone, false};   // CLD
        case 0xFD: return {true, Form::kNone, false};   // STD

        case 0x90: return {true, Form::kNone, false};   // NOP
        case 0xC3: return {true, Form::kNone, true};    // RET near
        case 0xE8: return {true, Form::kRel16, true};   // CALL near
        case 0xE9: return {true, Form::kRel16, true};   // JMP near
        case 0xEB: return {true, Form::kRel8, true};    // JMP short

        default: return {false, Form::kNone, false};
    }
}

bool OpcodeHasModRm(std::uint8_t opcode) { return Lookup(opcode).has_modrm(); }

Instruction Decode(const Cpu& cpu, std::uint16_t cs, std::uint16_t ip) {
    Instruction out;
    int at = 0;

    // Prefixes first. The hardware allows several, and the last segment
    // override wins -- so this loops rather than checking once.
    for (;;) {
        const std::uint8_t byte = FetchAt(cpu, cs, ip, at);
        const Segment segment = SegmentForPrefix(byte);
        if (segment == Segment::kNone) {
            break;
        }
        out.segment_override = segment;
        ++at;
        if (at >= kMaxLength) {
            // Do not stop and read the next byte as an opcode -- it is a
            // prefix, and calling it an opcode is a silently wrong decode.
            out.length = static_cast<std::uint8_t>(at);
            out.valid = false;
            return out;
        }
    }

    out.opcode = FetchAt(cpu, cs, ip, at);
    ++at;

    const OpcodeInfo info = Lookup(out.opcode);
    out.wide = info.wide;

    switch (info.form) {
        case Form::kModRm: {
            out.has_modrm = true;
            out.modrm = ModRm::From(FetchAt(cpu, cs, ip, at));
            ++at;

            if (out.modrm.mod == 1) {
                // Sign-extended. 0x9C is -100, not 156, and getting this wrong
                // puts the operand 256 bytes away from where hardware put it.
                out.displacement = static_cast<std::int8_t>(FetchAt(cpu, cs, ip, at));
                ++at;
            } else if (out.modrm.mod == 2 || (out.modrm.mod == 0 && out.modrm.rm == 6)) {
                // mod 2 is disp16. mod 0 rm 6 is the table's one exception: a
                // direct 16-bit address, not [bp]. [bp] with no displacement
                // is unreachable and encodes as mod 1 with a zero disp8.
                const std::uint8_t low = FetchAt(cpu, cs, ip, at);
                const std::uint8_t high = FetchAt(cpu, cs, ip, at + 1);
                out.displacement = static_cast<std::int16_t>(low | (high << 8));
                at += 2;
            }
            break;
        }

        case Form::kRel8:
            out.immediate = static_cast<std::int8_t>(FetchAt(cpu, cs, ip, at));
            ++at;
            break;

        case Form::kImm8:
            // Zero-extended, not sign-extended. `E4 FF` is port 255, not
            // port -1, and `D4 FF` is a divisor of 255.
            out.immediate = static_cast<std::int16_t>(FetchAt(cpu, cs, ip, at));
            ++at;
            break;

        case Form::kRel16: {
            const std::uint8_t low = FetchAt(cpu, cs, ip, at);
            const std::uint8_t high = FetchAt(cpu, cs, ip, at + 1);
            out.immediate = static_cast<std::int16_t>(low | (high << 8));
            at += 2;
            break;
        }

        case Form::kRegInOpcode:
            out.reg_in_opcode = static_cast<std::uint8_t>(out.opcode & 0x07);
            break;

        case Form::kNone:
            break;
    }

    out.length = static_cast<std::uint8_t>(at);
    return out;
}

std::uint16_t SegmentValue(const Registers& regs, Segment segment) {
    switch (segment) {
        case Segment::kEs: return regs.es;
        case Segment::kCs: return regs.cs;
        case Segment::kSs: return regs.ss;
        case Segment::kDs: return regs.ds;
        case Segment::kNone: return regs.ds;
    }
    return regs.ds;
}

Address EffectiveAddress(const Registers& regs, const ModRm& modrm,
                         std::int16_t displacement, Segment override_segment) {
    Address out;
    std::uint16_t base = 0;
    bool uses_bp = false;

    switch (modrm.rm) {
        case 0: base = static_cast<std::uint16_t>(regs.bx + regs.si); break;
        case 1: base = static_cast<std::uint16_t>(regs.bx + regs.di); break;
        case 2: base = static_cast<std::uint16_t>(regs.bp + regs.si); uses_bp = true; break;
        case 3: base = static_cast<std::uint16_t>(regs.bp + regs.di); uses_bp = true; break;
        case 4: base = regs.si; break;
        case 5: base = regs.di; break;
        case 6:
            if (modrm.mod == 0) {
                base = 0;  // direct address; the displacement is the whole of it
            } else {
                base = regs.bp;
                uses_bp = true;
            }
            break;
        case 7: base = regs.bx; break;
        default: break;
    }

    out.offset = static_cast<std::uint16_t>(base + displacement);
    // A BP-relative access is assumed to be a stack frame, so it defaults to
    // SS. Every other mode defaults to DS.
    out.segment = uses_bp ? Segment::kSs : Segment::kDs;
    if (override_segment != Segment::kNone) {
        out.segment = override_segment;
    }
    return out;
}

}  // namespace i8086
