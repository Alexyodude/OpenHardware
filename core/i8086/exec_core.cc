// OpenHardware - execute one instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "exec_core.h"

#include "alu.h"
#include "shift.h"

namespace i8086 {
namespace {

/// Where an operand lives, at either width.
struct Operand {
    bool is_register = false;
    std::uint8_t register_index = 0;
    Segment segment = Segment::kDs;
    std::uint16_t offset = 0;
    bool wide = false;
};

Operand ResolveRm(const Cpu& cpu, const Instruction& instruction) {
    Operand out;
    out.wide = instruction.wide;
    if (instruction.modrm.is_register()) {
        out.is_register = true;
        out.register_index = instruction.modrm.rm;
        return out;
    }
    const Address address = EffectiveAddress(cpu.regs(), instruction.modrm,
                                             instruction.displacement,
                                             instruction.segment_override);
    out.segment = address.segment;
    out.offset = address.offset;
    return out;
}

Operand RegOperand(const Instruction& instruction) {
    Operand out;
    out.is_register = true;
    out.register_index = instruction.modrm.reg;
    out.wide = instruction.wide;
    return out;
}

std::uint16_t Read(const Cpu& cpu, const Operand& operand) {
    if (operand.is_register) {
        return operand.wide ? ReadWordRegister(cpu.regs(), operand.register_index)
                            : ReadByteRegister(cpu.regs(), operand.register_index);
    }
    const std::uint16_t segment = SegmentValue(cpu.regs(), operand.segment);
    if (operand.wide) {
        // Segment-aware: a word at seg:FFFF takes its high byte from seg:0000,
        // not from the next paragraph.
        return cpu.ReadWordAt(segment, operand.offset);
    }
    return cpu.ReadByte(Physical(segment, operand.offset));
}

void Write(Cpu& cpu, const Operand& operand, std::uint16_t value) {
    if (operand.is_register) {
        if (operand.wide) {
            WriteWordRegister(cpu.regs(), operand.register_index, value);
        } else {
            WriteByteRegister(cpu.regs(), operand.register_index,
                              static_cast<std::uint8_t>(value));
        }
        return;
    }
    const std::uint16_t segment = SegmentValue(cpu.regs(), operand.segment);
    if (operand.wide) {
        cpu.WriteWordAt(segment, operand.offset, value);
    } else {
        cpu.WriteByte(Physical(segment, operand.offset), static_cast<std::uint8_t>(value));
    }
}

void Push(Cpu& cpu, std::uint16_t value) {
    // SP decrements by two, then the word lands at SS:SP. Through WriteWordAt
    // so a stack wrapping past offset 0 comes back at 0xFFFE rather than
    // spilling into the next segment.
    cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp - 2);
    cpu.WriteWordAt(cpu.regs().ss, cpu.regs().sp, value);
}

std::uint16_t Pop(Cpu& cpu) {
    const std::uint16_t value = cpu.ReadWordAt(cpu.regs().ss, cpu.regs().sp);
    cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp + 2);
    return value;
}

/// What an undriven 8088 data bus reads as.
///
/// The corpus was captured on a machine with **nothing attached to the I/O
/// bus**: all 40,000 IN cases across E4, E5, EC and ED read 0xFF, and all
/// 40,000 OUT cases change nothing but IP. That is not the harness
/// simplifying -- it is what an open bus does.
///
/// So there is no port map here, because there is no device to put in one.
/// A map with nothing in it would be machinery serving callers that want a
/// constant, and **the corpus could not tell the two apart** -- which is
/// worth saying out loud, because it means these four opcodes are the one
/// family in this core whose conformance score is not evidence of much. When
/// a board model arrives (OH-9), this constant is the seam it replaces.
constexpr std::uint8_t kOpenBus = 0xFF;
constexpr std::uint16_t kOpenBusWord = 0xFFFF;

/// The sixteen Jcc conditions, from the low four opcode bits.
///
/// Opcode bit 0 inverts, so there are only eight tests and the odd encodings
/// are their negation. Eight rows rather than sixteen, and a mispaired
/// condition is visible rather than buried.
bool Condition(std::uint8_t low_nibble, std::uint16_t flags) {
    const bool carry = HasFlag(flags, kCarry);
    const bool zero = HasFlag(flags, kZero);
    const bool sign = HasFlag(flags, kSign);
    const bool overflow = HasFlag(flags, kOverflow);
    const bool parity = HasFlag(flags, kParity);

    bool taken = false;
    switch (low_nibble >> 1) {
        case 0: taken = overflow; break;                    // JO  / JNO
        case 1: taken = carry; break;                       // JB  / JNB
        case 2: taken = zero; break;                        // JZ  / JNZ
        case 3: taken = carry || zero; break;               // JBE / JA
        case 4: taken = sign; break;                        // JS  / JNS
        case 5: taken = parity; break;                      // JP  / JNP
        case 6: taken = sign != overflow; break;            // JL  / JGE
        default: taken = zero || (sign != overflow); break; // JLE / JG
    }
    return (low_nibble & 1) ? !taken : taken;
}

}  // namespace

std::uint8_t ReadByteRegister(const Registers& regs, std::uint8_t index) {
    switch (index & 0x07) {
        case 0: return static_cast<std::uint8_t>(regs.ax & 0xFF);         // AL
        case 1: return static_cast<std::uint8_t>(regs.cx & 0xFF);         // CL
        case 2: return static_cast<std::uint8_t>(regs.dx & 0xFF);         // DL
        case 3: return static_cast<std::uint8_t>(regs.bx & 0xFF);         // BL
        case 4: return static_cast<std::uint8_t>((regs.ax >> 8) & 0xFF);  // AH
        case 5: return static_cast<std::uint8_t>((regs.cx >> 8) & 0xFF);  // CH
        case 6: return static_cast<std::uint8_t>((regs.dx >> 8) & 0xFF);  // DH
        default: return static_cast<std::uint8_t>((regs.bx >> 8) & 0xFF); // BH
    }
}

void WriteByteRegister(Registers& regs, std::uint8_t index, std::uint8_t value) {
    const std::uint16_t low = value;
    const std::uint16_t high = static_cast<std::uint16_t>(value << 8);
    switch (index & 0x07) {
        case 0: regs.ax = static_cast<std::uint16_t>((regs.ax & 0xFF00) | low); break;
        case 1: regs.cx = static_cast<std::uint16_t>((regs.cx & 0xFF00) | low); break;
        case 2: regs.dx = static_cast<std::uint16_t>((regs.dx & 0xFF00) | low); break;
        case 3: regs.bx = static_cast<std::uint16_t>((regs.bx & 0xFF00) | low); break;
        case 4: regs.ax = static_cast<std::uint16_t>((regs.ax & 0x00FF) | high); break;
        case 5: regs.cx = static_cast<std::uint16_t>((regs.cx & 0x00FF) | high); break;
        case 6: regs.dx = static_cast<std::uint16_t>((regs.dx & 0x00FF) | high); break;
        default: regs.bx = static_cast<std::uint16_t>((regs.bx & 0x00FF) | high); break;
    }
}

std::uint16_t ReadWordRegister(const Registers& regs, std::uint8_t index) {
    switch (index & 0x07) {
        case 0: return regs.ax;
        case 1: return regs.cx;
        case 2: return regs.dx;
        case 3: return regs.bx;
        case 4: return regs.sp;
        case 5: return regs.bp;
        case 6: return regs.si;
        default: return regs.di;
    }
}

void WriteWordRegister(Registers& regs, std::uint8_t index, std::uint16_t value) {
    switch (index & 0x07) {
        case 0: regs.ax = value; break;
        case 1: regs.cx = value; break;
        case 2: regs.dx = value; break;
        case 3: regs.bx = value; break;
        case 4: regs.sp = value; break;
        case 5: regs.bp = value; break;
        case 6: regs.si = value; break;
        default: regs.di = value; break;
    }
}

StepStatus Step(Cpu& cpu) {
    const Instruction instruction = Decode(cpu, cpu.regs().cs, cpu.regs().ip);
    if (!instruction.valid || !Lookup(instruction.opcode).implemented) {
        return StepStatus::kUnimplemented;
    }

    const std::uint8_t opcode = instruction.opcode;
    const std::uint16_t entry_ip = cpu.regs().ip;
    // IP advances past the instruction BEFORE execution, because every
    // relative branch is measured from the following instruction and CALL
    // pushes that address. Advancing afterwards makes each of those a special
    // case that has to remember the length.
    const std::uint16_t next_ip = static_cast<std::uint16_t>(entry_ip + instruction.length);
    cpu.regs().ip = next_ip;

    // --- the ALU group, 0x00-0x3F, forms 0-3 -----------------------------
    if (opcode < 0x40 && (opcode & 0x07) <= 0x03) {
        const AluKind kind = static_cast<AluKind>((opcode >> 3) & 0x07);
        const bool reg_is_destination = (opcode & 0x02) != 0;

        const Operand rm = ResolveRm(cpu, instruction);
        const Operand reg = RegOperand(instruction);
        const Operand& destination = reg_is_destination ? reg : rm;
        const Operand& source = reg_is_destination ? rm : reg;

        std::uint16_t flags = cpu.regs().flags;
        const std::uint16_t result =
            Alu(kind, Read(cpu, destination), Read(cpu, source), instruction.wide, flags);
        // CMP is SUB that throws the result away: the flags are the point.
        if (kind != AluKind::kCmp) {
            Write(cpu, destination, result);
        }
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
        return StepStatus::kOk;
    }

    // --- PUSH r16 / POP r16 -----------------------------------------------
    if (opcode >= 0x50 && opcode <= 0x57) {
        // PUSH SP stores the value SP held BEFORE its own decrement on this
        // part. Later x86 changed that, and it is the classic way to tell an
        // 8086 from a 286 in software -- so the read happens first.
        const std::uint16_t value = ReadWordRegister(cpu.regs(), instruction.reg_in_opcode);
        Push(cpu, value);
        return StepStatus::kOk;
    }
    if (opcode >= 0x58 && opcode <= 0x5F) {
        const std::uint16_t value = Pop(cpu);
        WriteWordRegister(cpu.regs(), instruction.reg_in_opcode, value);
        return StepStatus::kOk;
    }

    // --- Jcc rel8 ----------------------------------------------------------
    if (opcode >= 0x70 && opcode <= 0x7F) {
        if (Condition(static_cast<std::uint8_t>(opcode & 0x0F), cpu.regs().flags)) {
            cpu.regs().ip = static_cast<std::uint16_t>(next_ip + instruction.immediate);
        }
        return StepStatus::kOk;
    }

    // --- shift and rotate, 0xD0-0xD3 --------------------------------------
    if (opcode >= 0xD0 && opcode <= 0xD3) {
        const Operand rm = ResolveRm(cpu, instruction);
        // Bit 1 selects the count: clear means one, set means CL. CL is byte
        // register 1 -- read through ReadByteRegister rather than masking
        // cpu.regs().cx, so the one encoding table stays the only one.
        const std::uint8_t count = (opcode & 0x02) != 0
                                       ? ReadByteRegister(cpu.regs(), 1)
                                       : 1;
        std::uint16_t flags = cpu.regs().flags;
        const std::uint16_t result =
            Shift(static_cast<ShiftKind>(instruction.modrm.reg), Read(cpu, rm), count,
                  instruction.wide, flags);
        // Written back even when the count was zero, which stores the value
        // that was already there. Harmless, and it keeps the zero case from
        // being a second path through this branch.
        Write(cpu, rm, result);
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
        return StepStatus::kOk;
    }

    switch (opcode) {
        case 0x88:
        case 0x89:
        case 0x8A:
        case 0x8B: {
            const Operand rm = ResolveRm(cpu, instruction);
            const Operand reg = RegOperand(instruction);
            if ((opcode & 0x02) != 0) {
                Write(cpu, reg, Read(cpu, rm));
            } else {
                Write(cpu, rm, Read(cpu, reg));
            }
            return StepStatus::kOk;
        }

        case 0x90:  // NOP, which is XCHG AX,AX and touches nothing.
            return StepStatus::kOk;

        // --- port I/O ------------------------------------------------------
        // The port number is deliberately not computed: nothing consumes it.
        // E4/E5 carry it as an immediate and EC/ED take it from DX, and both
        // read the same open bus. See kOpenBus.
        case 0xE4:  // IN AL, imm8
        case 0xE5:  // IN AX, imm8
        case 0xEC:  // IN AL, DX
        case 0xED:  // IN AX, DX
            if (instruction.wide) {
                cpu.regs().ax = kOpenBusWord;
            } else {
                WriteByteRegister(cpu.regs(), 0, kOpenBus);  // AL
            }
            return StepStatus::kOk;

        case 0xE6:  // OUT imm8, AL
        case 0xE7:  // OUT imm8, AX
        case 0xEE:  // OUT DX, AL
        case 0xEF:  // OUT DX, AX
            // Nothing latches what is driven. Written as an explicit case
            // rather than left to the default, because "ran, and had no
            // observable effect" is a different fact from "not implemented" --
            // and the corpus separates them, since an unimplemented OUT would
            // leave IP where it started.
            return StepStatus::kOk;

        // --- the single-byte flag instructions ------------------------------
        case 0xF5:  // CMC -- the only one of the seven that reads a flag first
            SetFlag(cpu.regs().flags, kCarry, !HasFlag(cpu.regs().flags, kCarry));
            return StepStatus::kOk;
        case 0xF8:  // CLC
            SetFlag(cpu.regs().flags, kCarry, false);
            return StepStatus::kOk;
        case 0xF9:  // STC
            SetFlag(cpu.regs().flags, kCarry, true);
            return StepStatus::kOk;
        case 0xFA:  // CLI
            SetFlag(cpu.regs().flags, kInterrupt, false);
            return StepStatus::kOk;
        case 0xFB:  // STI
            SetFlag(cpu.regs().flags, kInterrupt, true);
            return StepStatus::kOk;
        case 0xFC:  // CLD -- string operations count upwards
            SetFlag(cpu.regs().flags, kDirection, false);
            return StepStatus::kOk;
        case 0xFD:  // STD -- and downwards
            SetFlag(cpu.regs().flags, kDirection, true);
            return StepStatus::kOk;

        case 0xC3:  // RET near
            cpu.regs().ip = Pop(cpu);
            return StepStatus::kOk;

        case 0xE8:  // CALL near
            Push(cpu, next_ip);
            cpu.regs().ip = static_cast<std::uint16_t>(next_ip + instruction.immediate);
            return StepStatus::kOk;

        case 0xE9:  // JMP near
        case 0xEB:  // JMP short
            cpu.regs().ip = static_cast<std::uint16_t>(next_ip + instruction.immediate);
            return StepStatus::kOk;

        default:
            // Unreachable: Lookup already refused anything unimplemented. Kept
            // so a table entry added without a case here refuses cleanly --
            // and puts IP back, since it was advanced above.
            cpu.regs().ip = entry_ip;
            return StepStatus::kUnimplemented;
    }
}

}  // namespace i8086
