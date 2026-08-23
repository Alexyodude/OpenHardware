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

}  // namespace

OpcodeInfo Lookup(std::uint8_t opcode) {
    switch (opcode) {
        case 0x00: return {true, true};    // ADD r/m8, r8
        case 0x88: return {true, true};    // MOV r/m8, r8
        case 0x90: return {true, false};   // NOP
        default: return {false, false};
    }
}

bool OpcodeHasModRm(std::uint8_t opcode) { return Lookup(opcode).has_modrm; }

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

    if (OpcodeHasModRm(out.opcode)) {
        out.has_modrm = true;
        out.modrm = ModRm::From(FetchAt(cpu, cs, ip, at));
        ++at;

        if (out.modrm.mod == 1) {
            // Sign-extended. 0x9C is -100, not 156, and getting this wrong
            // puts the operand 256 bytes away from where hardware put it.
            out.displacement = static_cast<std::int8_t>(FetchAt(cpu, cs, ip, at));
            ++at;
        } else if (out.modrm.mod == 2) {
            const std::uint8_t low = FetchAt(cpu, cs, ip, at);
            const std::uint8_t high = FetchAt(cpu, cs, ip, at + 1);
            out.displacement = static_cast<std::int16_t>(low | (high << 8));
            at += 2;
        } else if (out.modrm.mod == 0 && out.modrm.rm == 6) {
            // The one exception in the table: mod 0 rm 6 is not [bp], it is a
            // direct 16-bit address. [bp] with no displacement is unreachable
            // and is encoded as mod 1 with a zero disp8.
            const std::uint8_t low = FetchAt(cpu, cs, ip, at);
            const std::uint8_t high = FetchAt(cpu, cs, ip, at + 1);
            out.displacement = static_cast<std::int16_t>(low | (high << 8));
            at += 2;
        }
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
