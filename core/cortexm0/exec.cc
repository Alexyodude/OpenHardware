// OpenHardware — execute one Thumb instruction, formats 1 to 4.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this covers, and why that slice
//
// Encodings 0x0000 to 0x43FF: the shift-by-immediate group, add/subtract,
// the 8-bit immediate group, and the 16-entry ALU group. Every one of them is
// register-only and every one of them writes flags.
//
// That is the first slice deliberately. There is no memory access to model, no
// branch, and no exception -- so the whole surface under test is *arithmetic
// and flags*, which is where an Armv6-M core is hardest to get right and where
// an oracle pays for itself. It is also exactly the set
// `tools/gen_armv6m_tests.mjs` generates, so every instruction here is checked
// against rp2040js rather than against this file's own reading of the manual.
//
// ## Decode lives here rather than in its own module
//
// The i8086 core has a `decode.cc` because its disassembler and its executor
// both consume decoded instructions, and because x86 decoding is genuinely
// hard -- prefixes, modrm, variable length. Thumb-16 decoding is a handful of
// bit extractions with exactly one consumer, so a `Decoded` struct here would
// be an interface more complicated than the thing it hides. When a
// disassembler arrives it will be the second consumer, and that is the change
// that earns the split.
//
// ## What flags each group writes
//
// This is the part worth reading twice, because the groups differ and the
// differences are invisible in the mnemonics:
//
//   * `ADDS` `SUBS` `ADCS` `SBCS` `NEGS` `CMP` `CMN` — all four of NZCV.
//   * `LSLS` `LSRS` `ASRS` `RORS` — N, Z and C. **V is untouched.**
//   * `ANDS` `EORS` `ORRS` `BICS` `MVNS` `TST` — N and Z only. C and V keep
//     their previous values, because these encodings have no shifted operand
//     to produce a carry.
//   * `MOVS #imm8` — N and Z only, same reason.
//   * `MULS` — N and Z only. On Armv6-M C and V are explicitly preserved;
//     older Arm architectures left C UNPREDICTABLE here, so code written from
//     an ARM7 reference gets this wrong.

#include "exec.h"

#include "exception.h"
#include "shift.h"

namespace cortexm0 {
namespace {

/// A write to PC that might be an exception return rather than a branch.
///
/// **Only in Handler mode**, and that half is load-bearing: in Thread mode
/// 0xFFFFFFF9 is an ordinary wild branch, and it should fault on the fetch
/// saying so rather than unstack a frame nothing stacked. Both encodings that
/// can write PC from a register go through here -- `BX` and `POP` with PC in
/// the list -- because a handler written by a compiler returns through
/// whichever of the two its prologue chose.
StepResult write_pc_or_return(Cpu& cpu, uint32_t value) {
    if (cpu.scs().ipsr != 0 && value >= kExcReturnBase) {
        return ReturnFromException(cpu, value) ? StepResult::Ok
                                               : StepResult::MemoryFault;
    }
    cpu.set_reg(kPc, value & ~1u);
    return StepResult::Ok;
}

/// Low three bits at `position`. Formats 1-4 address only r0-r7.
inline unsigned reg3(uint16_t encoding, unsigned position) {
    return (encoding >> position) & 0x7u;
}

/// The 16 opcodes of the format-4 ALU group, in encoding order.
enum class Alu : uint16_t {
    And = 0, Eor = 1, Lsl = 2, Lsr = 3, Asr = 4, Adc = 5, Sbc = 6, Ror = 7,
    Tst = 8, Rsb = 9, Cmp = 10, Cmn = 11, Orr = 12, Mul = 13, Bic = 14, Mvn = 15,
};

/// Apply a shift result: N, Z and C move, V does not.
void write_shift(Cpu& cpu, unsigned rd, Shifted shifted) {
    cpu.set_reg(rd, shifted.value);
    cpu.set_nz(shifted.value);
    cpu.set_c(shifted.carry);
}

/// Apply an arithmetic result: all four flags move.
void write_sum(Cpu& cpu, unsigned rd, Sum sum) {
    cpu.set_reg(rd, sum.value);
    cpu.set_nz(sum.value);
    cpu.set_c(sum.carry);
    cpu.set_v(sum.overflow);
}

/// Apply a logical result: N and Z only.
void write_logical(Cpu& cpu, unsigned rd, uint32_t value) {
    cpu.set_reg(rd, value);
    cpu.set_nz(value);
}

StepResult execute_alu(Cpu& cpu, uint16_t encoding) {
    const unsigned rdn = reg3(encoding, 0);
    const unsigned rm = reg3(encoding, 3);
    const auto op = static_cast<Alu>((encoding >> 6) & 0xFu);

    const uint32_t left = cpu.reg(rdn);
    const uint32_t right = cpu.reg(rm);
    // Only the low byte of the shift register is used, and it is used whole:
    // amounts above 31 are legal and the shift helpers saturate on them.
    const uint32_t amount = right & 0xFFu;

    switch (op) {
        case Alu::And: write_logical(cpu, rdn, left & right); break;
        case Alu::Eor: write_logical(cpu, rdn, left ^ right); break;
        case Alu::Orr: write_logical(cpu, rdn, left | right); break;
        case Alu::Bic: write_logical(cpu, rdn, left & ~right); break;
        case Alu::Mvn: write_logical(cpu, rdn, ~right); break;

        case Alu::Lsl: write_shift(cpu, rdn, lsl(left, amount, cpu.c())); break;
        case Alu::Lsr: write_shift(cpu, rdn, lsr(left, amount, cpu.c())); break;
        case Alu::Asr: write_shift(cpu, rdn, asr(left, amount, cpu.c())); break;
        case Alu::Ror: write_shift(cpu, rdn, ror(left, amount, cpu.c())); break;

        case Alu::Adc: write_sum(cpu, rdn, add_with_carry(left, right, cpu.c())); break;
        // Subtraction is `x + ~y + carry`. Writing it as `left - right - !c`
        // gives the same value and the wrong borrow at the edges.
        case Alu::Sbc: write_sum(cpu, rdn, add_with_carry(left, ~right, cpu.c())); break;
        // NEGS Rd, Rm is RSBS Rd, Rm, #0 -- note it negates *Rm*, the source,
        // not the destination register that names it.
        case Alu::Rsb: write_sum(cpu, rdn, add_with_carry(0, ~right, true)); break;

        case Alu::Mul: {
            // Truncating 32x32 multiply. Both operands are read before the
            // write because Rd is also an operand.
            const uint32_t product = left * right;
            write_logical(cpu, rdn, product);
            break;
        }

        // The three that compute a result and throw it away. Discarding the
        // value is the whole difference between CMP and SUBS, so these must
        // not go through the `write_*` helpers.
        case Alu::Tst: cpu.set_nz(left & right); break;
        case Alu::Cmp: {
            const Sum sum = add_with_carry(left, ~right, true);
            cpu.set_nz(sum.value);
            cpu.set_c(sum.carry);
            cpu.set_v(sum.overflow);
            break;
        }
        case Alu::Cmn: {
            const Sum sum = add_with_carry(left, right, false);
            cpu.set_nz(sum.value);
            cpu.set_c(sum.carry);
            cpu.set_v(sum.overflow);
            break;
        }
    }
    return StepResult::Ok;
}

// --- formats 5 to 19 -------------------------------------------------------
//
// Everything a program actually needs: memory, branches, the stack and the
// high registers. Formats 1-4 above are arithmetic on r0-r7 and cannot express
// a single line of real firmware.
//
// Two rules govern the whole group and both are easy to get wrong:
//
//   * **PC reads as the instruction's address plus 4**, always, because the
//     architecture defines it relative to a three-stage pipeline that this
//     core does not otherwise model. Every PC-relative form below adds 4.
//   * **PC-relative addressing aligns down to a word first.** `LDR Rd, [PC,
//     #imm]` and `ADD Rd, PC, #imm` both clear bit 1 of the base. Omitting
//     that reads the wrong word for every instruction sitting at an odd
//     halfword, which is half of them.
//
// None of these write flags. That is not an oversight: on Armv6-M only the
// format 1-4 group and a handful of others set them, and a load that quietly
// updated N and Z would corrupt the condition a following branch tests.

/// PC as the instruction sees it: the address of the *next* halfword plus 2.
/// `pc` here is already advanced past the current instruction by the caller.
inline uint32_t pc_for_reads(uint32_t instruction_address) {
    return instruction_address + 4;
}

/// Sign-extend the low `bits` of `value`.
inline uint32_t sign_extend(uint32_t value, unsigned bits) {
    const uint32_t mask = 1u << (bits - 1);
    return (value ^ mask) - mask;
}

bool condition_holds(const Cpu& cpu, unsigned code) {
    switch (code) {
        case 0x0: return cpu.z();                              // EQ
        case 0x1: return !cpu.z();                             // NE
        case 0x2: return cpu.c();                              // CS/HS
        case 0x3: return !cpu.c();                             // CC/LO
        case 0x4: return cpu.n();                              // MI
        case 0x5: return !cpu.n();                             // PL
        case 0x6: return cpu.v();                              // VS
        case 0x7: return !cpu.v();                             // VC
        case 0x8: return cpu.c() && !cpu.z();                  // HI
        case 0x9: return !cpu.c() || cpu.z();                  // LS
        case 0xA: return cpu.n() == cpu.v();                   // GE
        case 0xB: return cpu.n() != cpu.v();                   // LT
        case 0xC: return !cpu.z() && cpu.n() == cpu.v();       // GT
        case 0xD: return cpu.z() || cpu.n() != cpu.v();        // LE
        default: return true;                                  // AL
    }
}

/// Write a register, treating r15 as a branch.
///
/// Writes to PC clear bit 0. Thumb state is the only state this part has, so
/// the bit carries no information and leaving it set makes every subsequent
/// fetch land on an odd address.
void write_reg(Cpu& cpu, unsigned index, uint32_t value) {
    cpu.set_reg(index, index == kPc ? (value & ~1u) : value);
}

StepResult execute_wide(Cpu& cpu, uint16_t first, uint32_t address);

StepResult execute(Cpu& cpu, uint16_t encoding) {
    // Format 4: the ALU group, 0x4000-0x43FF. Tested first because its
    // top bits overlap nothing below it.
    if ((encoding & 0xFC00u) == 0x4000u) {
        return execute_alu(cpu, encoding);
    }

    // Format 3: MOVS/CMP/ADDS/SUBS Rdn, #imm8 -- 0x2000-0x3FFF.
    if ((encoding & 0xE000u) == 0x2000u) {
        const unsigned rdn = (encoding >> 8) & 0x7u;
        const uint32_t imm = encoding & 0xFFu;
        const uint32_t left = cpu.reg(rdn);
        switch ((encoding >> 11) & 0x3u) {
            case 0: write_logical(cpu, rdn, imm); break;               // MOVS
            case 1: {                                                  // CMP
                const Sum sum = add_with_carry(left, ~imm, true);
                cpu.set_nz(sum.value);
                cpu.set_c(sum.carry);
                cpu.set_v(sum.overflow);
                break;
            }
            case 2: write_sum(cpu, rdn, add_with_carry(left, imm, false)); break;
            case 3: write_sum(cpu, rdn, add_with_carry(left, ~imm, true)); break;
        }
        return StepResult::Ok;
    }

    // Format 2: ADDS/SUBS with a register or a 3-bit immediate --
    // 0x1800-0x1FFF. Bit 10 chooses immediate, bit 9 chooses subtract.
    if ((encoding & 0xF800u) == 0x1800u) {
        const unsigned rd = reg3(encoding, 0);
        const unsigned rn = reg3(encoding, 3);
        const bool immediate = (encoding & 0x0400u) != 0;
        const bool subtract = (encoding & 0x0200u) != 0;
        const uint32_t operand = immediate ? ((encoding >> 6) & 0x7u) : cpu.reg(reg3(encoding, 6));
        const uint32_t left = cpu.reg(rn);
        write_sum(cpu, rd,
                  subtract ? add_with_carry(left, ~operand, true)
                           : add_with_carry(left, operand, false));
        return StepResult::Ok;
    }

    // Format 1: shift by immediate -- 0x0000-0x17FF. The `0x1800` case above
    // has already claimed the encodings where op == 3, which is what stops
    // this from swallowing add/subtract.
    if ((encoding & 0xE000u) == 0x0000u) {
        const unsigned rd = reg3(encoding, 0);
        const unsigned rm = reg3(encoding, 3);
        const uint32_t imm5 = (encoding >> 6) & 0x1Fu;
        const uint32_t value = cpu.reg(rm);
        switch ((encoding >> 11) & 0x3u) {
            case 0:
                // LSL takes imm5 literally, so 0 really is a shift of zero and
                // the carry survives. LSR and ASR below do not.
                write_shift(cpu, rd, lsl(value, imm5, cpu.c()));
                break;
            case 1:
                write_shift(cpu, rd, lsr(value, imm5 == 0 ? 32u : imm5, cpu.c()));
                break;
            case 2:
                write_shift(cpu, rd, asr(value, imm5 == 0 ? 32u : imm5, cpu.c()));
                break;
            default:
                // op == 3 is add/subtract, already handled. Unreachable, and
                // reported rather than fallen through.
                return StepResult::Unimplemented;
        }
        return StepResult::Ok;
    }

    return StepResult::Unimplemented;
}

/// Everything from 0x4400 up: memory, branches, the stack, the high registers.
///
/// Split from `execute` so that function stays the formats-1-to-4 decoder it
/// was. `address` is where this instruction sits; PC in the register file has
/// not moved yet.
StepResult execute_rest(Cpu& cpu, uint16_t encoding, uint32_t address) {
    const uint32_t pc = pc_for_reads(address);

    // Format 5: high-register ADD/CMP/MOV and BX/BLX, 0x4400-0x47FF. The only
    // group that can name r8-r15, which is why BX lives here.
    if ((encoding & 0xFC00u) == 0x4400u) {
        const unsigned op = (encoding >> 8) & 0x3u;
        const unsigned rm = (encoding >> 3) & 0xFu;
        const unsigned rdn = ((encoding >> 4) & 0x8u) | (encoding & 0x7u);
        const uint32_t right = rm == kPc ? pc : cpu.reg(rm);
        if (op == 3) {
            // BX and BLX. BLX sets LR to the address *after* this instruction
            // with bit 0 set for Thumb -- the return address, not this one.
            if ((encoding & 0x0080u) != 0) {
                cpu.set_reg(kLr, (address + 2) | 1u);
                // BLX with an EXC_RETURN is architecturally UNPREDICTABLE, so
                // it is a branch here and not a return: LR has already been
                // overwritten, which is not a state any return could undo.
                cpu.set_reg(kPc, right & ~1u);
                return StepResult::Ok;
            }
            return write_pc_or_return(cpu, right);
        }
        const uint32_t left = rdn == kPc ? pc : cpu.reg(rdn);
        if (op == 0) {                       // ADD, and it sets no flags
            write_reg(cpu, rdn, left + right);
        } else if (op == 1) {                // CMP, flags only
            const Sum sum = add_with_carry(left, ~right, true);
            cpu.set_nz(sum.value);
            cpu.set_c(sum.carry);
            cpu.set_v(sum.overflow);
        } else {                             // MOV, and it sets no flags
            write_reg(cpu, rdn, right);
        }
        return StepResult::Ok;
    }

    // Format 6: LDR Rd, [PC, #imm8*4] -- how every literal reaches a register.
    if ((encoding & 0xF800u) == 0x4800u) {
        const uint32_t base = pc & ~3u;  // aligned down; see the section note
        uint32_t value = 0;
        if (!cpu.read_word(base + ((encoding & 0xFFu) << 2), value)) {
            return StepResult::MemoryFault;
        }
        cpu.set_reg((encoding >> 8) & 0x7u, value);
        return StepResult::Ok;
    }

    // Formats 7 and 8: load and store with a register offset, 0x5000-0x5FFF.
    // The three-bit opcode names the width and the signedness together.
    if ((encoding & 0xF000u) == 0x5000u) {
        const unsigned rd = encoding & 0x7u;
        const uint32_t addr = cpu.reg((encoding >> 3) & 0x7u) +
                              cpu.reg((encoding >> 6) & 0x7u);
        uint32_t word = 0;
        uint16_t half = 0;
        uint8_t byte = 0;
        switch ((encoding >> 9) & 0x7u) {
            case 0:
                if (!cpu.write_word(addr, cpu.reg(rd))) return StepResult::MemoryFault;
                break;
            case 1:
                if (!cpu.write_halfword(addr, static_cast<uint16_t>(cpu.reg(rd))))
                    return StepResult::MemoryFault;
                break;
            case 2:
                if (!cpu.write_byte_checked(addr, static_cast<uint8_t>(cpu.reg(rd))))
                    return StepResult::MemoryFault;
                break;
            case 3:  // LDRSB -- sign-extended, unlike LDRB below
                if (!cpu.read_byte_checked(addr, byte)) return StepResult::MemoryFault;
                cpu.set_reg(rd, sign_extend(byte, 8));
                break;
            case 4:
                if (!cpu.read_word(addr, word)) return StepResult::MemoryFault;
                cpu.set_reg(rd, word);
                break;
            case 5:
                if (!cpu.read_halfword(addr, half)) return StepResult::MemoryFault;
                cpu.set_reg(rd, half);
                break;
            case 6:
                if (!cpu.read_byte_checked(addr, byte)) return StepResult::MemoryFault;
                cpu.set_reg(rd, byte);
                break;
            default:  // LDRSH
                if (!cpu.read_halfword(addr, half)) return StepResult::MemoryFault;
                cpu.set_reg(rd, sign_extend(half, 16));
                break;
        }
        return StepResult::Ok;
    }

    // Format 9: load and store with a 5-bit immediate, 0x6000-0x7FFF.
    // **The immediate is scaled by the access width**, so the same five bits
    // reach 124 bytes for a word and 31 for a byte. Forgetting to scale is a
    // silently four-times-wrong address.
    if ((encoding & 0xE000u) == 0x6000u) {
        const unsigned rd = encoding & 0x7u;
        const uint32_t imm5 = (encoding >> 6) & 0x1Fu;
        const bool byte_access = (encoding & 0x1000u) != 0;
        const bool load = (encoding & 0x0800u) != 0;
        const uint32_t addr =
            cpu.reg((encoding >> 3) & 0x7u) + (byte_access ? imm5 : imm5 << 2);
        if (byte_access) {
            uint8_t byte = 0;
            if (load) {
                if (!cpu.read_byte_checked(addr, byte)) return StepResult::MemoryFault;
                cpu.set_reg(rd, byte);
            } else if (!cpu.write_byte_checked(addr,
                                               static_cast<uint8_t>(cpu.reg(rd)))) {
                return StepResult::MemoryFault;
            }
        } else {
            uint32_t word = 0;
            if (load) {
                if (!cpu.read_word(addr, word)) return StepResult::MemoryFault;
                cpu.set_reg(rd, word);
            } else if (!cpu.write_word(addr, cpu.reg(rd))) {
                return StepResult::MemoryFault;
            }
        }
        return StepResult::Ok;
    }

    // Format 10: halfword load and store, 0x8000-0x8FFF. Scaled by two.
    if ((encoding & 0xF000u) == 0x8000u) {
        const unsigned rd = encoding & 0x7u;
        const uint32_t addr =
            cpu.reg((encoding >> 3) & 0x7u) + (((encoding >> 6) & 0x1Fu) << 1);
        if ((encoding & 0x0800u) != 0) {
            uint16_t half = 0;
            if (!cpu.read_halfword(addr, half)) return StepResult::MemoryFault;
            cpu.set_reg(rd, half);
        } else if (!cpu.write_halfword(addr, static_cast<uint16_t>(cpu.reg(rd)))) {
            return StepResult::MemoryFault;
        }
        return StepResult::Ok;
    }

    // Format 11: SP-relative load and store, 0x9000-0x9FFF. Scaled by four.
    if ((encoding & 0xF000u) == 0x9000u) {
        const unsigned rd = (encoding >> 8) & 0x7u;
        const uint32_t addr = cpu.reg(kSp) + ((encoding & 0xFFu) << 2);
        if ((encoding & 0x0800u) != 0) {
            uint32_t word = 0;
            if (!cpu.read_word(addr, word)) return StepResult::MemoryFault;
            cpu.set_reg(rd, word);
        } else if (!cpu.write_word(addr, cpu.reg(rd))) {
            return StepResult::MemoryFault;
        }
        return StepResult::Ok;
    }

    // Format 12: ADD Rd, PC|SP, #imm8*4 -- taking an address, not loading one.
    if ((encoding & 0xF000u) == 0xA000u) {
        const uint32_t offset = (encoding & 0xFFu) << 2;
        const bool from_sp = (encoding & 0x0800u) != 0;
        cpu.set_reg((encoding >> 8) & 0x7u,
                    from_sp ? cpu.reg(kSp) + offset : (pc & ~3u) + offset);
        return StepResult::Ok;
    }

    // Format 13: ADD/SUB SP, #imm7*4 -- how a function opens and closes its
    // frame. Sets no flags, unlike every other add in the instruction set.
    if ((encoding & 0xFF00u) == 0xB000u) {
        const uint32_t offset = (encoding & 0x7Fu) << 2;
        const uint32_t sp = cpu.reg(kSp);
        cpu.set_reg(kSp, (encoding & 0x0080u) ? sp - offset : sp + offset);
        return StepResult::Ok;
    }

    // Armv6-M extras inside the 0xB000 block: sign and zero extension, and
    // byte reversal. Absent from the classic Thumb format list, and a compiler
    // emits them constantly.
    if ((encoding & 0xFF00u) == 0xB200u) {
        const unsigned rd = encoding & 0x7u;
        const uint32_t value = cpu.reg((encoding >> 3) & 0x7u);
        switch ((encoding >> 6) & 0x3u) {
            case 0: cpu.set_reg(rd, sign_extend(value & 0xFFFFu, 16)); break;  // SXTH
            case 1: cpu.set_reg(rd, sign_extend(value & 0xFFu, 8)); break;     // SXTB
            case 2: cpu.set_reg(rd, value & 0xFFFFu); break;                   // UXTH
            default: cpu.set_reg(rd, value & 0xFFu); break;                    // UXTB
        }
        return StepResult::Ok;
    }
    if ((encoding & 0xFF00u) == 0xBA00u) {
        const unsigned rd = encoding & 0x7u;
        const uint32_t v = cpu.reg((encoding >> 3) & 0x7u);
        switch ((encoding >> 6) & 0x3u) {
            case 0:  // REV
                cpu.set_reg(rd, ((v & 0xFFu) << 24) | ((v & 0xFF00u) << 8) |
                                    ((v >> 8) & 0xFF00u) | ((v >> 24) & 0xFFu));
                break;
            case 1:  // REV16
                cpu.set_reg(rd, ((v & 0x00FF00FFu) << 8) | ((v >> 8) & 0x00FF00FFu));
                break;
            case 3:  // REVSH -- reverses the low halfword, then sign-extends
                cpu.set_reg(rd,
                            sign_extend(((v & 0xFFu) << 8) | ((v >> 8) & 0xFFu), 16));
                break;
            default:
                return StepResult::Unimplemented;
        }
        return StepResult::Ok;
    }

    // Format 14: PUSH and POP, 0xB400-0xBDFF.
    //
    // **Registers move in address order -- lowest register to lowest address
    // -- whichever way SP travels.** Pushing in register order while
    // decrementing gives a stack that pops back reversed, and the bug only
    // shows when more than one register is in the list.
    if ((encoding & 0xF600u) == 0xB400u) {
        const bool pop = (encoding & 0x0800u) != 0;
        const bool extra = (encoding & 0x0100u) != 0;  // LR on push, PC on pop
        const uint16_t list = encoding & 0xFFu;
        unsigned count = extra ? 1u : 0u;
        for (unsigned i = 0; i < 8; ++i) {
            count += (list >> i) & 1u;
        }
        if (pop) {
            uint32_t addr = cpu.reg(kSp);
            for (unsigned i = 0; i < 8; ++i) {
                if (((list >> i) & 1u) == 0) continue;
                uint32_t word = 0;
                if (!cpu.read_word(addr, word)) return StepResult::MemoryFault;
                cpu.set_reg(i, word);
                addr += 4;
            }
            uint32_t popped_pc = 0;
            if (extra) {
                if (!cpu.read_word(addr, popped_pc)) return StepResult::MemoryFault;
                addr += 4;
            }
            // **SP is written before PC, and that ordering is what makes
            // `pop {r4, pc}` work as an exception return.** A compiler-written
            // handler pushes LR -- which holds EXC_RETURN -- and pops it into
            // PC, and the exception frame sits immediately above what it just
            // popped. So the unstack has to read from where SP ends up, not
            // from where it started.
            cpu.set_reg(kSp, addr);
            if (extra) {
                return write_pc_or_return(cpu, popped_pc);
            }
        } else {
            const uint32_t base = cpu.reg(kSp) - 4u * count;
            uint32_t addr = base;
            for (unsigned i = 0; i < 8; ++i) {
                if (((list >> i) & 1u) == 0) continue;
                if (!cpu.write_word(addr, cpu.reg(i))) return StepResult::MemoryFault;
                addr += 4;
            }
            if (extra && !cpu.write_word(addr, cpu.reg(kLr))) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(kSp, base);
        }
        return StepResult::Ok;
    }

    // CPSIE i and CPSID i, 0xB662 and 0xB672. The low nibble is fixed at
    // 0b0010 on Armv6-M: PRIMASK is the only mask there is, so `a` and `f`
    // must be clear and an encoding with either set is not this instruction.
    //
    // **This exists because exception delivery without it would be wrong
    // rather than incomplete.** A critical section that this core kept
    // interrupting is a corrupted program with no message; the previous
    // behaviour -- Unimplemented, stopping loudly -- was safe only while
    // nothing could interrupt. Five of these are in the SAMD21 Arduino image
    // measured on 2026-08-26, in the USB path and in the core's own
    // interrupt-safe helpers.
    if ((encoding & 0xFFEFu) == 0xB662u) {
        cpu.scs().primask = (encoding & 0x0010u) != 0;
        return StepResult::Ok;
    }

    // The hint space: NOP, YIELD, WFE, WFI, SEV. All behave as NOP here.
    //
    // WFI is the one worth a second look now that SysTick exists: a real part
    // sleeps until an exception arrives, and this core has exactly one source
    // whose tick is counted in retired instructions. So a WFI that slept would
    // stop the clock it is waiting for -- it would hang for a reason the
    // architecture does not have. Retiring as a NOP keeps the tick coming and
    // the wait ends, which is the behaviour firmware expects even though the
    // mechanism is not the part's.
    if ((encoding & 0xFF0Fu) == 0xBF00u) {
        return StepResult::Ok;
    }

    // Format 15: STMIA/LDMIA with writeback, 0xC000-0xCFFF.
    if ((encoding & 0xF000u) == 0xC000u) {
        const unsigned rn = (encoding >> 8) & 0x7u;
        const uint16_t list = encoding & 0xFFu;
        const bool load = (encoding & 0x0800u) != 0;
        uint32_t addr = cpu.reg(rn);
        for (unsigned i = 0; i < 8; ++i) {
            if (((list >> i) & 1u) == 0) continue;
            if (load) {
                uint32_t word = 0;
                if (!cpu.read_word(addr, word)) return StepResult::MemoryFault;
                cpu.set_reg(i, word);
            } else if (!cpu.write_word(addr, cpu.reg(i))) {
                return StepResult::MemoryFault;
            }
            addr += 4;
        }
        // Writeback is suppressed on a load whose list already holds the base
        // register: the loaded value wins. Writing back would overwrite what
        // was just loaded, which is the opposite of the intent.
        if (!load || ((list >> rn) & 1u) == 0) {
            cpu.set_reg(rn, addr);
        }
        return StepResult::Ok;
    }

    // Format 17: SVC, 0xDF00-0xDFFF. Reported, not executed.
    //
    // This core does now take exceptions, so the old reason -- "models no
    // exceptions" -- has stopped being the reason. The remaining one is
    // narrower and still decisive: taking an SVC needs a handler, and the
    // vector table entry for it belongs to an operating system this project
    // does not run. Entering exception 11 to land on whatever byte happens to
    // sit at VTOR+0x2C would be worse than stopping, and pretending an SVC
    // returned would let a program continue past a call that never happened.
    if ((encoding & 0xFF00u) == 0xDF00u) {
        return StepResult::Unimplemented;
    }

    // Format 16: conditional branch, 0xD000-0xDEFF. The offset counts
    // halfwords, so it doubles.
    if ((encoding & 0xF000u) == 0xD000u) {
        if (condition_holds(cpu, (encoding >> 8) & 0xFu)) {
            cpu.set_reg(kPc, pc + (sign_extend(encoding & 0xFFu, 8) << 1));
        }
        return StepResult::Ok;
    }

    // Format 18: unconditional branch, 0xE000-0xE7FF.
    if ((encoding & 0xF800u) == 0xE000u) {
        cpu.set_reg(kPc, pc + (sign_extend(encoding & 0x7FFu, 11) << 1));
        return StepResult::Ok;
    }

    return StepResult::Unimplemented;
}

/// Format 19: BL, the one 32-bit instruction Armv6-M has.
///
/// Its two halfwords are fetched and decoded together. The second is not a
/// valid instruction on its own, so a core that stepped over the first would
/// then execute garbage -- which is why this takes both rather than being two
/// passes through the decoder.
StepResult execute_wide(Cpu& cpu, uint16_t first, uint32_t address) {
    uint16_t second = 0;
    if (!cpu.read_halfword(address + 2, second)) {
        return StepResult::MemoryFault;
    }
    if ((second & 0xC000u) != 0xC000u) {
        // 0xF000-prefixed encodings that are not BL belong to Armv7-M, not to
        // this part. Reported rather than guessed at.
        return StepResult::Unimplemented;
    }

    // The offset is assembled from five fields across both halfwords, and the
    // two J bits are stored *inverted relative to S*. That is the encoding's
    // real shape rather than an obfuscation: it keeps the branch range
    // contiguous across the sign boundary.
    const uint32_t s = (first >> 10) & 1u;
    const uint32_t imm10 = first & 0x3FFu;
    const uint32_t j1 = (second >> 13) & 1u;
    const uint32_t j2 = (second >> 11) & 1u;
    const uint32_t imm11 = second & 0x7FFu;
    const uint32_t i1 = 1u - (j1 ^ s);
    const uint32_t i2 = 1u - (j2 ^ s);
    const uint32_t offset = sign_extend(
        (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1), 25);

    cpu.set_reg(kLr, (address + 4) | 1u);
    cpu.set_reg(kPc, pc_for_reads(address) + offset);
    return StepResult::Ok;
}

}  // namespace

StepResult step(Cpu& cpu) {
    // **An exception is taken between instructions, before the fetch.**
    //
    // Not inside `note_executed`, where the tick happens: by then the
    // instruction that just retired has already moved PC, so an entry there
    // would stack a return address that is right by luck. And not after the
    // execute either -- the frame has to hold the address of the instruction
    // that will run *next*, which is exactly what PC holds here.
    //
    // The step costs one instruction of virtual time and executes none. That
    // is not free on real silicon either: entry stacks eight words.
    if (ServicePending(cpu)) {
        return StepResult::Ok;
    }

    const uint32_t address = cpu.reg(kPc);
    uint16_t encoding = 0;
    if (!cpu.read_halfword(address, encoding) || !cpu.executable_at(address)) {
        // The executability check is deliberately *after* the read, so an
        // address that is simply absent and one that is present but not
        // executable both arrive here with the faulting address recorded.
        cpu.note_fetch_fault(address);
        return StepResult::MemoryFault;
    }

    // BL is the only 32-bit encoding on this part, and it is recognised before
    // anything else so its second halfword is never decoded on its own.
    const bool wide = (encoding & 0xF800u) == 0xF000u;

    // **PC advances first, and a branch overwrites it.**
    //
    // The obvious alternative -- execute, then advance only if PC changed --
    // has one encoding it cannot see: `B .`, a branch to itself. Its target
    // equals the address it came from, so "PC is unchanged" is true both when
    // nothing branched and when a self-branch did, and the core steps straight
    // past it. That is not an exotic case: `B .` is the idle loop at the end
    // of most firmware and the body of the default fault handler, so the bug
    // means never noticing that a program has stopped or crashed.
    //
    // Advancing first has no such blind spot, because a branch writes PC
    // whether or not the value differs. The formats that read PC take it from
    // `address` rather than from the register file, so moving it early cannot
    // disturb them.
    const uint32_t next = address + (wide ? 4u : 2u);
    cpu.set_reg(kPc, next);

    const StepResult result =
        wide ? execute_wide(cpu, encoding, address)
             : (encoding < 0x4400u ? execute(cpu, encoding)
                                   : execute_rest(cpu, encoding, address));
    if (result != StepResult::Ok) {
        // Put PC back, so an unimplemented encoding or a faulting access
        // leaves it naming the instruction that stopped -- the contract in
        // cpu.h that a conformance case depends on.
        cpu.set_reg(kPc, address);
        return result;
    }
    return StepResult::Ok;
}

}  // namespace cortexm0
