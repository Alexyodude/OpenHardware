// OpenHardware — the RV32I base integer instruction set.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Scope: RV32I, and a deliberate refusal of everything else
//
// All 37 base integer instructions after the fetch, and nothing beyond them.
// M, A and C are decoded far enough to be *classified* and then refused, which
// is not the same as being unimplemented -- see `StepResult` in cpu.h. That
// classification is the whole point of doing it this way round: the ESP32-C3
// must trap an atomic and the ESP32-C6 must execute one, and no amount of
// lockstep against rvcpp will ever tell those apart, because rvcpp runs both.
//
// ## Two ways to say no, and they are not interchangeable
//
//  * `Illegal` -- the extension is not enabled for this part. Hardware raises
//    illegal-instruction here, and a model that executed it anyway would
//    diverge from silicon in a way no lockstep run can catch.
//  * `Unimplemented` -- the extension IS enabled and the encoding is one
//    nobody here has written. A hole in this emulator, and honest about it.
//
// ## What is not here yet, and is not pretended
//
// No traps and no CSRs, so ECALL, EBREAK and every Zicsr encoding return
// `Unimplemented` rather than a plausible-looking vector. A misaligned jump
// target reports `MemoryFault` with the target address, because that is the
// diagnostic a person wants; on silicon it is an
// instruction-address-misaligned trap, and when traps land it should become
// one. Saying so here is cheaper than a reader assuming the trap exists.

#include "exec.h"

namespace riscv32 {

namespace {

/// The seven fixed fields every RV32 encoding is cut from. Named rather than
/// shifted inline, because `(instr >> 15) & 0x1F` appears in nine cases and
/// one transposed digit in any of them is a bug that decodes as a different
/// register and produces a merely-wrong answer.
uint32_t opcode_of(uint32_t instr) { return instr & 0x7Fu; }
unsigned rd_of(uint32_t instr) { return (instr >> 7) & 0x1Fu; }
unsigned funct3_of(uint32_t instr) { return (instr >> 12) & 0x7u; }
unsigned rs1_of(uint32_t instr) { return (instr >> 15) & 0x1Fu; }
unsigned rs2_of(uint32_t instr) { return (instr >> 20) & 0x1Fu; }
uint32_t funct7_of(uint32_t instr) { return (instr >> 25) & 0x7Fu; }

/// Sign-extend the low `bits` of `value` to 32.
///
/// Through uint32_t and an explicit sign bit rather than a signed shift: right
/// shift of a negative signed integer was implementation-defined until C++20,
/// and this file is compiled as C++17 by three different compilers.
uint32_t sign_extend(uint32_t value, unsigned bits) {
    const uint32_t mask = (bits >= 32) ? 0xFFFFFFFFu : ((1u << bits) - 1u);
    value &= mask;
    const uint32_t sign = 1u << (bits - 1);
    return (value & sign) ? (value | ~mask) : value;
}

uint32_t imm_i(uint32_t instr) { return sign_extend(instr >> 20, 12); }

uint32_t imm_s(uint32_t instr) {
    return sign_extend(((instr >> 25) << 5) | ((instr >> 7) & 0x1Fu), 12);
}

uint32_t imm_b(uint32_t instr) {
    const uint32_t bits = (((instr >> 31) & 0x1u) << 12) |
                          (((instr >> 7) & 0x1u) << 11) |
                          (((instr >> 25) & 0x3Fu) << 5) |
                          (((instr >> 8) & 0xFu) << 1);
    return sign_extend(bits, 13);
}

uint32_t imm_u(uint32_t instr) { return instr & 0xFFFFF000u; }

uint32_t imm_j(uint32_t instr) {
    const uint32_t bits = (((instr >> 31) & 0x1u) << 20) |
                          (((instr >> 12) & 0xFFu) << 12) |
                          (((instr >> 20) & 0x1u) << 11) |
                          (((instr >> 21) & 0x3FFu) << 1);
    return sign_extend(bits, 21);
}

/// Signed comparison without ever forming a signed overflow.
bool less_than_signed(uint32_t a, uint32_t b) {
    return static_cast<int32_t>(a) < static_cast<int32_t>(b);
}

/// Arithmetic right shift, spelled out for the same C++17 reason as
/// `sign_extend`.
uint32_t shift_right_arithmetic(uint32_t value, unsigned amount) {
    const uint32_t shifted = value >> amount;
    if ((value & 0x80000000u) == 0 || amount == 0) {
        return shifted;
    }
    return shifted | (0xFFFFFFFFu << (32 - amount));
}

}  // namespace

namespace {

/// Say no to an encoding belonging to an optional extension, in whichever of
/// the two ways is true.
///
/// One helper rather than the same ternary at four call sites, because the two
/// outcomes are easy to transpose and transposing them is exactly the bug this
/// core exists to avoid.
StepResult refuse(const Cpu& cpu, Extension extension) {
    return cpu.has(extension) ? StepResult::Unimplemented : StepResult::Illegal;
}

/// Jump and branch targets must satisfy the part's instruction alignment.
bool aligned(const Cpu& cpu, uint32_t target) {
    return target % cpu.instruction_alignment() == 0;
}

}  // namespace

StepResult step(Cpu& cpu) {
    const uint32_t pc = cpu.pc();

    if (!aligned(cpu, pc)) {
        cpu.note_fetch_fault(pc);
        return StepResult::MemoryFault;
    }
    if (!cpu.executable_at(pc)) {
        cpu.note_fetch_fault(pc);
        return StepResult::MemoryFault;
    }

    // The first halfword decides the width, which is why the fetch is two
    // reads rather than one. Reading four bytes up front would fault on a
    // legal 16-bit instruction sitting in the last halfword of a region.
    uint16_t low = 0;
    if (!cpu.read_halfword(pc, low)) {
        cpu.note_fetch_fault(pc);
        return StepResult::MemoryFault;
    }

    if ((low & 0x3u) != 0x3u) {
        // The all-zero halfword is a *defined* illegal encoding in RVC rather
        // than an unassigned one, so it is illegal whether or not C is
        // enabled. Routing it through `refuse` reported it as merely
        // unimplemented on a part that has C, which is the wrong half of the
        // distinction this core exists to keep -- and it is not a corner case:
        // zeros are what a program reads the instant it runs off the end of
        // anything, so this is the encoding that has to be loudest.
        if (low == 0) {
            return StepResult::Illegal;
        }
        return refuse(cpu, kExtC);
    }

    if (!cpu.executable_at(pc + 2)) {
        cpu.note_fetch_fault(pc + 2);
        return StepResult::MemoryFault;
    }
    uint32_t instr = 0;
    if (!cpu.read_word(pc, instr)) {
        cpu.note_fetch_fault(pc);
        return StepResult::MemoryFault;
    }

    const uint32_t next = pc + 4;
    const unsigned rd = rd_of(instr);
    const unsigned rs1 = rs1_of(instr);
    const unsigned rs2 = rs2_of(instr);
    const unsigned funct3 = funct3_of(instr);

    switch (opcode_of(instr)) {
    case 0x37u:  // LUI
        cpu.set_reg(rd, imm_u(instr));
        cpu.set_pc(next);
        return StepResult::Ok;

    case 0x17u:  // AUIPC
        cpu.set_reg(rd, pc + imm_u(instr));
        cpu.set_pc(next);
        return StepResult::Ok;

    case 0x6Fu: {  // JAL
        const uint32_t target = pc + imm_j(instr);
        if (!aligned(cpu, target)) {
            cpu.note_fetch_fault(target);
            return StepResult::MemoryFault;
        }
        cpu.set_reg(rd, next);
        cpu.set_pc(target);
        return StepResult::Ok;
    }

    case 0x67u: {  // JALR
        if (funct3 != 0) {
            return StepResult::Illegal;
        }
        // The target is computed from rs1 before rd is written, because they
        // are frequently the same register -- `jalr ra, ra, 0` is how a
        // compiler returns through a saved pointer. Writing the link first
        // would jump to the link.
        //
        // Bit 0 is cleared rather than checked. The architecture says so, and
        // it is what makes a function pointer with a stray low bit work
        // instead of trapping.
        const uint32_t target = (cpu.reg(rs1) + imm_i(instr)) & ~1u;
        if (!aligned(cpu, target)) {
            cpu.note_fetch_fault(target);
            return StepResult::MemoryFault;
        }
        cpu.set_reg(rd, next);
        cpu.set_pc(target);
        return StepResult::Ok;
    }

    case 0x63u: {  // BRANCH
        const uint32_t a = cpu.reg(rs1);
        const uint32_t b = cpu.reg(rs2);
        bool taken = false;
        switch (funct3) {
        case 0x0u: taken = a == b; break;                        // BEQ
        case 0x1u: taken = a != b; break;                        // BNE
        case 0x4u: taken = less_than_signed(a, b); break;        // BLT
        case 0x5u: taken = !less_than_signed(a, b); break;       // BGE
        case 0x6u: taken = a < b; break;                         // BLTU
        case 0x7u: taken = a >= b; break;                        // BGEU
        default: return StepResult::Illegal;                     // 010, 011
        }
        if (!taken) {
            cpu.set_pc(next);
            return StepResult::Ok;
        }
        // Only a *taken* branch can raise the misaligned-fetch condition. A
        // not-taken branch to a misaligned target is architecturally fine, and
        // compilers emit them: the target is a label whose alignment only
        // matters on the path that reaches it.
        const uint32_t target = pc + imm_b(instr);
        if (!aligned(cpu, target)) {
            cpu.note_fetch_fault(target);
            return StepResult::MemoryFault;
        }
        cpu.set_pc(target);
        return StepResult::Ok;
    }

    case 0x03u: {  // LOAD
        const uint32_t address = cpu.reg(rs1) + imm_i(instr);
        uint32_t width = 0;
        switch (funct3) {
        case 0x0u: case 0x4u: width = 1; break;   // LB, LBU
        case 0x1u: case 0x5u: width = 2; break;   // LH, LHU
        case 0x2u: width = 4; break;              // LW
        default: return StepResult::Illegal;      // 011, 110, 111
        }
        // Naturally-aligned only. The architecture permits an implementation
        // to support misaligned access or to trap, and Hazard3 traps -- which
        // matters because rvcpp is the oracle, and a core that quietly
        // succeeded where the oracle traps would diverge on the first packed
        // struct. This reports MemoryFault rather than a load-align trap only
        // because there are no traps yet.
        if (address % width != 0) {
            cpu.note_data_fault(address);
            return StepResult::MemoryFault;
        }
        uint32_t value = 0;
        if (width == 1) {
            uint8_t byte = 0;
            if (!cpu.read_byte_checked(address, byte)) {
                return StepResult::MemoryFault;
            }
            value = funct3 == 0x0u ? sign_extend(byte, 8) : byte;
        } else if (width == 2) {
            uint16_t half = 0;
            if (!cpu.read_halfword(address, half)) {
                return StepResult::MemoryFault;
            }
            value = funct3 == 0x1u ? sign_extend(half, 16) : half;
        } else {
            if (!cpu.read_word(address, value)) {
                return StepResult::MemoryFault;
            }
        }
        cpu.set_reg(rd, value);
        cpu.set_pc(next);
        return StepResult::Ok;
    }

    case 0x23u: {  // STORE
        const uint32_t address = cpu.reg(rs1) + imm_s(instr);
        const uint32_t value = cpu.reg(rs2);
        uint32_t width = 0;
        switch (funct3) {
        case 0x0u: width = 1; break;              // SB
        case 0x1u: width = 2; break;              // SH
        case 0x2u: width = 4; break;              // SW
        default: return StepResult::Illegal;
        }
        if (address % width != 0) {
            cpu.note_data_fault(address);
            return StepResult::MemoryFault;
        }
        bool stored = false;
        if (width == 1) {
            stored = cpu.write_byte_checked(address, static_cast<uint8_t>(value));
        } else if (width == 2) {
            stored = cpu.write_halfword(address, static_cast<uint16_t>(value));
        } else {
            stored = cpu.write_word(address, value);
        }
        if (!stored) {
            return StepResult::MemoryFault;
        }
        cpu.set_pc(next);
        return StepResult::Ok;
    }

    case 0x13u: {  // OP-IMM
        const uint32_t a = cpu.reg(rs1);
        const uint32_t imm = imm_i(instr);
        uint32_t result = 0;
        switch (funct3) {
        case 0x0u: result = a + imm; break;                              // ADDI
        case 0x2u: result = less_than_signed(a, imm) ? 1u : 0u; break;   // SLTI
        case 0x3u: result = a < imm ? 1u : 0u; break;                    // SLTIU
        case 0x4u: result = a ^ imm; break;                              // XORI
        case 0x6u: result = a | imm; break;                              // ORI
        case 0x7u: result = a & imm; break;                              // ANDI
        case 0x1u:  // SLLI
            // On RV32 the shift amount is five bits and bit 25 must be zero.
            // A one there is the RV64 encoding of a six-bit shift, and an
            // RV32 part raises illegal-instruction rather than shifting by a
            // masked amount. This is the same class of hole rvcpp has in its
            // compressed decoder (docs/architectures.md 2.1b): an RV64 meaning
            // silently accepted on a 32-bit part.
            if (funct7_of(instr) != 0x00u) {
                return StepResult::Illegal;
            }
            result = a << (rs2 & 0x1Fu);
            break;
        case 0x5u:  // SRLI, SRAI
            if (funct7_of(instr) == 0x00u) {
                result = a >> (rs2 & 0x1Fu);
            } else if (funct7_of(instr) == 0x20u) {
                result = shift_right_arithmetic(a, rs2 & 0x1Fu);
            } else {
                return StepResult::Illegal;
            }
            break;
        default:
            return StepResult::Illegal;
        }
        cpu.set_reg(rd, result);
        cpu.set_pc(next);
        return StepResult::Ok;
    }

    case 0x33u: {  // OP
        const uint32_t funct7 = funct7_of(instr);
        if (funct7 == 0x01u) {
            // MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU.
            return refuse(cpu, kExtM);
        }
        const uint32_t a = cpu.reg(rs1);
        const uint32_t b = cpu.reg(rs2);
        const unsigned amount = b & 0x1Fu;
        uint32_t result = 0;
        if (funct7 == 0x00u) {
            switch (funct3) {
            case 0x0u: result = a + b; break;                             // ADD
            case 0x1u: result = a << amount; break;                       // SLL
            case 0x2u: result = less_than_signed(a, b) ? 1u : 0u; break;  // SLT
            case 0x3u: result = a < b ? 1u : 0u; break;                   // SLTU
            case 0x4u: result = a ^ b; break;                             // XOR
            case 0x5u: result = a >> amount; break;                       // SRL
            case 0x6u: result = a | b; break;                             // OR
            case 0x7u: result = a & b; break;                             // AND
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x20u) {
            switch (funct3) {
            case 0x0u: result = a - b; break;                             // SUB
            case 0x5u: result = shift_right_arithmetic(a, amount); break; // SRA
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x10u) {
            // Zba address generation. `refuse` is deliberately not used here:
            // it answers Unimplemented when the extension is present, and
            // these three are implemented. A part without Zba must raise
            // illegal-instruction, and that is the whole verdict rvcpp cannot
            // give -- it executes SH1ADD for every part, gated or not
            // (rv_core.cpp:265). Encodings from its own table:
            // RVOPC_SH1ADD_BITS = 0b0010000_00000_00000_010_00000_0110011.
            if (!cpu.has(kExtZba)) {
                return StepResult::Illegal;
            }
            switch (funct3) {
            case 0x2u: result = (a << 1) + b; break;                   // SH1ADD
            case 0x4u: result = (a << 2) + b; break;                   // SH2ADD
            case 0x6u: result = (a << 3) + b; break;                   // SH3ADD
            // funct3 000, 001, 011, 101 and 111 under this funct7 are not
            // Zba. Some belong to Zbs and Zbkb, which this core does not
            // model; unassigned and not-modelled both read as Illegal here,
            // and `MODELLED` in tests/rv32/conftest.py is what keeps a
            // not-modelled encoding from being asserted against a real part.
            default: return StepResult::Illegal;
            }
        } else {
            return StepResult::Illegal;
        }
        cpu.set_reg(rd, result);
        cpu.set_pc(next);
        return StepResult::Ok;
    }

    case 0x0Fu:  // MISC-MEM
        // FENCE orders memory for other harts and devices. This core is one
        // in-order hart with no cache and no observers, so ordering it against
        // nothing is genuinely a no-op -- not a stub. Executing it as one is
        // correct, and it has to be, because every compiled RISC-V program
        // that touches a lock contains some.
        //
        // FENCE.I (funct3 = 1) is Zifencei, a separate extension with no bit
        // in `Extension` because no board here has needed it yet. Refusing it
        // as Unimplemented rather than Illegal is the honest half: this core
        // has not decided about it, which is different from a part refusing.
        if (funct3 == 0x0u) {
            cpu.set_pc(next);
            return StepResult::Ok;
        }
        if (funct3 == 0x1u) {
            return StepResult::Unimplemented;
        }
        return StepResult::Illegal;

    case 0x73u:
        // SYSTEM: ECALL, EBREAK, and the Zicsr encodings.
        //
        // Unimplemented rather than Illegal, and not faked. All of these
        // either enter a trap or touch a CSR, and this core has neither. A
        // model that answered a CSR read with a plausible value would be
        // inventing machine state, and ESP-IDF reads mstatus and mtvec within
        // its first hundred instructions -- so a wrong answer here is not a
        // small wrong answer.
        return StepResult::Unimplemented;

    case 0x2Fu:
        // AMO: the A extension. **This is the case the whole `Extension` mask
        // exists for.** The ESP32-C3 is RV32IMC and must trap here; the C6 is
        // RV32IMAC and must execute. rvcpp executes both unconditionally, so
        // lockstep can never check this branch -- see OH-35.
        return refuse(cpu, kExtA);

    default:
        // Every undefined opcode, including the all-zeros and all-ones words a
        // program that has run off the end of memory reads.
        return StepResult::Illegal;
    }
}

}  // namespace riscv32
