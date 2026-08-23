// OpenHardware - execute one instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "exec_core.h"

#include "alu.h"

namespace i8086 {
namespace {

/// Where an 8-bit operand lives, once the modrm byte has been read.
struct ByteOperand {
    bool is_register = false;
    std::uint8_t register_index = 0;
    std::uint32_t address = 0;
};

ByteOperand ResolveRm(const Cpu& cpu, const Instruction& instruction) {
    ByteOperand out;
    if (instruction.modrm.is_register()) {
        out.is_register = true;
        out.register_index = instruction.modrm.rm;
        return out;
    }
    const Address address = EffectiveAddress(cpu.regs(), instruction.modrm,
                                             instruction.displacement,
                                             instruction.segment_override);
    out.address = Physical(SegmentValue(cpu.regs(), address.segment), address.offset);
    return out;
}

std::uint8_t ReadOperand(const Cpu& cpu, const ByteOperand& operand) {
    return operand.is_register ? ReadByteRegister(cpu.regs(), operand.register_index)
                               : cpu.ReadByte(operand.address);
}

void WriteOperand(Cpu& cpu, const ByteOperand& operand, std::uint8_t value) {
    if (operand.is_register) {
        WriteByteRegister(cpu.regs(), operand.register_index, value);
    } else {
        cpu.WriteByte(operand.address, value);
    }
}

}  // namespace

std::uint8_t ReadByteRegister(const Registers& regs, std::uint8_t index) {
    switch (index & 0x07) {
        case 0: return static_cast<std::uint8_t>(regs.ax & 0xFF);        // AL
        case 1: return static_cast<std::uint8_t>(regs.cx & 0xFF);        // CL
        case 2: return static_cast<std::uint8_t>(regs.dx & 0xFF);        // DL
        case 3: return static_cast<std::uint8_t>(regs.bx & 0xFF);        // BL
        case 4: return static_cast<std::uint8_t>((regs.ax >> 8) & 0xFF); // AH
        case 5: return static_cast<std::uint8_t>((regs.cx >> 8) & 0xFF); // CH
        case 6: return static_cast<std::uint8_t>((regs.dx >> 8) & 0xFF); // DH
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

StepStatus Step(Cpu& cpu) {
    const Instruction instruction = Decode(cpu, cpu.regs().cs, cpu.regs().ip);

    switch (instruction.opcode) {
        case 0x90:  // NOP, which is XCHG AX,AX and touches nothing.
            break;

        case 0x88: {  // MOV r/m8, r8
            const ByteOperand destination = ResolveRm(cpu, instruction);
            WriteOperand(cpu, destination, ReadByteRegister(cpu.regs(), instruction.modrm.reg));
            break;
        }

        case 0x00: {  // ADD r/m8, r8
            const ByteOperand destination = ResolveRm(cpu, instruction);
            std::uint16_t flags = cpu.regs().flags;
            const std::uint8_t result =
                Add8(ReadOperand(cpu, destination),
                     ReadByteRegister(cpu.regs(), instruction.modrm.reg), flags);
            WriteOperand(cpu, destination, result);
            cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            break;
        }

        default:
            // IP is deliberately not advanced. See StepStatus.
            return StepStatus::kUnimplemented;
    }

    // Within the segment: an instruction ending at 0xFFFF continues at 0.
    cpu.regs().ip = static_cast<std::uint16_t>(cpu.regs().ip + instruction.length);
    return StepStatus::kOk;
}

}  // namespace i8086
