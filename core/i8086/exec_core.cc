// OpenHardware - execute one instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "exec_core.h"

#include "alu.h"
#include "bcd.h"
#include "muldiv.h"
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

/// AL or AX, which is register index 0 at either width.
Operand AccumulatorOperand(bool wide) {
    Operand out;
    out.is_register = true;
    out.register_index = 0;
    out.wide = wide;
    return out;
}

/// The direct address carried by A0-A3, which has no modrm to resolve.
///
/// DS by default and overridable, like any other data access -- `2E A1 00 20`
/// really does read CS:2000.
Operand MoffsOperand(const Instruction& instruction) {
    Operand out;
    out.wide = instruction.wide;
    out.segment = instruction.segment_override == Segment::kNone ? Segment::kDs
                                                                 : instruction.segment_override;
    out.offset = static_cast<std::uint16_t>(instruction.displacement);
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

/// Take an interrupt vector: push FLAGS, CS and IP, then jump through the
/// table at the bottom of memory.
///
/// **`return_ip` is the address of the next instruction, not the faulting
/// one.** Measured: `D4 00` at IP 0x8573 pushes 0x8575. Later x86 parts push
/// the faulting address for a divide error, which is the difference between
/// it being a fault there and a trap here -- an 8086 handler cannot retry the
/// instruction, and was never meant to.
///
/// This lives here rather than in the `interrupt.*` that OH-5 claims. The
/// only thing that raises an interrupt today is AAM with a zero divisor, and
/// creating that file now to hold one function this ticket needs would leave
/// OH-5 inheriting a header it did not design. It moves when OH-5 arrives and
/// has INT n, INT3, INTO and the trap flag to put beside it.
void RaiseInterrupt(Cpu& cpu, std::uint8_t vector, std::uint16_t return_ip) {
    // FLAGS goes first, and it is the value the instruction has already
    // computed -- the corpus pushes the adjusted word, not the one the
    // instruction started with.
    Push(cpu, cpu.regs().flags);
    // Cleared after the push, so IRET restores them. A handler entered with
    // interrupts still enabled would be re-entered by the next one.
    SetFlag(cpu.regs().flags, kInterrupt, false);
    SetFlag(cpu.regs().flags, kTrap, false);
    Push(cpu, cpu.regs().cs);
    Push(cpu, return_ip);

    // The table is 256 entries of offset-then-segment at 0000:0000.
    const std::uint16_t entry = static_cast<std::uint16_t>(vector * 4);
    cpu.regs().ip = cpu.ReadWordAt(0x0000, entry);
    cpu.regs().cs = cpu.ReadWordAt(0x0000, static_cast<std::uint16_t>(entry + 2));
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

/// The ten string opcodes, A4-A7 and AA-AF.
///
/// A8 and A9 sit in the middle of that range and are TEST, not a string
/// operation -- which is why this is a list of families rather than a range
/// check.
bool IsStringOpcode(std::uint8_t opcode) {
    const std::uint8_t family = static_cast<std::uint8_t>(opcode & 0xFE);
    return family == 0xA4 || family == 0xA6 || family == 0xAA || family == 0xAC ||
           family == 0xAE;
}

/// Whether a string instruction sets ZF, and so whether a repeat prefix has a
/// condition to test. Only the two that compare.
bool StringSetsZero(std::uint8_t opcode) {
    const std::uint8_t family = static_cast<std::uint8_t>(opcode & 0xFE);
    return family == 0xA6 || family == 0xAE;  // CMPS, SCAS
}

/// One iteration of a string instruction, advancing SI and/or DI.
///
/// Two rules that are easy to state and easy to get wrong:
///
/// * **The source is DS:SI and is overridable; the destination is ES:DI and
///   is not.** A segment prefix on `MOVS` moves where it reads and never
///   where it writes. STOS and SCAS have no source at all, so a prefix on
///   them changes nothing -- and the corpus has cases of exactly that,
///   which a core applying the override to ES would fail.
///
/// * **DF chooses the direction, and the step is the operand width**, so a
///   word operation moves the pointers by two.
void StringIteration(Cpu& cpu, std::uint8_t opcode, bool wide, Segment source_override) {
    Registers& regs = cpu.regs();
    const std::uint16_t source = SegmentValue(
        regs, source_override == Segment::kNone ? Segment::kDs : source_override);
    const std::uint16_t width = wide ? 2 : 1;
    const std::uint16_t step = HasFlag(regs.flags, kDirection)
                                   ? static_cast<std::uint16_t>(0 - width)
                                   : width;

    const auto read_at = [&cpu, wide](std::uint16_t segment, std::uint16_t offset) {
        return wide ? cpu.ReadWordAt(segment, offset)
                    : static_cast<std::uint16_t>(cpu.ReadByte(Physical(segment, offset)));
    };
    const auto write_at = [&cpu, wide](std::uint16_t segment, std::uint16_t offset,
                                       std::uint16_t value) {
        if (wide) {
            cpu.WriteWordAt(segment, offset, value);
        } else {
            cpu.WriteByte(Physical(segment, offset), static_cast<std::uint8_t>(value));
        }
    };
    const auto accumulator = [&regs, wide]() {
        return wide ? regs.ax : static_cast<std::uint16_t>(regs.ax & 0xFF);
    };

    switch (static_cast<std::uint8_t>(opcode & 0xFE)) {
        case 0xA4:  // MOVS -- ES:DI <- DS:SI
            write_at(regs.es, regs.di, read_at(source, regs.si));
            regs.si = static_cast<std::uint16_t>(regs.si + step);
            regs.di = static_cast<std::uint16_t>(regs.di + step);
            break;

        case 0xA6: {  // CMPS -- the source MINUS the destination, result discarded
            const std::uint16_t left = read_at(source, regs.si);
            const std::uint16_t right = read_at(regs.es, regs.di);
            std::uint16_t flags = regs.flags;
            Alu(AluKind::kCmp, left, right, wide, flags);
            regs.flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            regs.si = static_cast<std::uint16_t>(regs.si + step);
            regs.di = static_cast<std::uint16_t>(regs.di + step);
            break;
        }

        case 0xAA:  // STOS -- ES:DI <- AL/AX. No source, so no override applies.
            write_at(regs.es, regs.di, accumulator());
            regs.di = static_cast<std::uint16_t>(regs.di + step);
            break;

        case 0xAC: {  // LODS -- AL/AX <- DS:SI
            const std::uint16_t value = read_at(source, regs.si);
            if (wide) {
                regs.ax = value;
            } else {
                WriteByteRegister(regs, 0, static_cast<std::uint8_t>(value));
            }
            regs.si = static_cast<std::uint16_t>(regs.si + step);
            break;
        }

        default: {  // 0xAE, SCAS -- AL/AX minus ES:DI
            const std::uint16_t right = read_at(regs.es, regs.di);
            std::uint16_t flags = regs.flags;
            Alu(AluKind::kCmp, accumulator(), right, wide, flags);
            regs.flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            regs.di = static_cast<std::uint16_t>(regs.di + step);
            break;
        }
    }
}

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

    // --- ALU accumulator,immediate -- forms 4 and 5 of the 0x00-0x3F group --
    if (opcode < 0x40 && ((opcode & 0x07) == 0x04 || (opcode & 0x07) == 0x05)) {
        const AluKind kind = static_cast<AluKind>((opcode >> 3) & 0x07);
        const Operand destination = AccumulatorOperand(instruction.wide);
        std::uint16_t flags = cpu.regs().flags;
        const std::uint16_t result =
            Alu(kind, Read(cpu, destination), static_cast<std::uint16_t>(instruction.immediate),
                instruction.wide, flags);
        if (kind != AluKind::kCmp) {
            Write(cpu, destination, result);
        }
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
        return StepStatus::kOk;
    }

    // --- group 1: ALU r/m,immediate, operation in the modrm reg field -------
    if (opcode >= 0x80 && opcode <= 0x83) {
        const AluKind kind = static_cast<AluKind>(instruction.modrm.reg);
        const Operand rm = ResolveRm(cpu, instruction);
        std::uint16_t flags = cpu.regs().flags;
        const std::uint16_t result =
            Alu(kind, Read(cpu, rm), static_cast<std::uint16_t>(instruction.immediate),
                instruction.wide, flags);
        if (kind != AluKind::kCmp) {
            Write(cpu, rm, result);
        }
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
        return StepStatus::kOk;
    }

    // --- MOV reg,imm -- B0-B7 byte, B8-BF word ------------------------------
    if (opcode >= 0xB0 && opcode <= 0xBF) {
        if (instruction.wide) {
            WriteWordRegister(cpu.regs(), instruction.reg_in_opcode,
                              static_cast<std::uint16_t>(instruction.immediate));
        } else {
            WriteByteRegister(cpu.regs(), instruction.reg_in_opcode,
                              static_cast<std::uint8_t>(instruction.immediate));
        }
        return StepStatus::kOk;
    }

    // --- INC r16 / DEC r16, and groups 4 and 5 -----------------------------
    // Split out because **INC and DEC do not touch CF**, and that is their
    // whole point: a loop can count with INC and still carry a multi-word
    // addition across iterations. Routing them through ADD/SUB and forgetting
    // to put CF back is the classic way to break exactly that.
    if ((opcode >= 0x40 && opcode <= 0x4F) || opcode == 0xFE ||
        (opcode == 0xFF && instruction.modrm.reg <= 1)) {
        const bool by_opcode = opcode <= 0x4F;
        const bool decrement = by_opcode ? (opcode & 0x08) != 0
                                         : instruction.modrm.reg == 1;
        Operand target;
        if (by_opcode) {
            target.is_register = true;
            target.register_index = instruction.reg_in_opcode;
            target.wide = true;
        } else {
            target = ResolveRm(cpu, instruction);
        }

        std::uint16_t flags = cpu.regs().flags;
        const bool carry = HasFlag(flags, kCarry);
        const std::uint16_t result =
            Alu(decrement ? AluKind::kSub : AluKind::kAdd, Read(cpu, target), 1,
                target.wide, flags);
        SetFlag(flags, kCarry, carry);
        Write(cpu, target, result);
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
        return StepStatus::kOk;
    }

    // --- the rest of group 5: indirect CALL, JMP and PUSH -------------------
    if (opcode == 0xFF) {
        const Operand rm = ResolveRm(cpu, instruction);
        switch (instruction.modrm.reg) {
            case 2: {  // CALL near, through a register or memory
                // The target is read BEFORE the return address is pushed.
                // `FF D4` is CALL SP, and the part jumps to the value SP held
                // on entry, not to the decremented one -- 328 of 328 cases.
                const std::uint16_t target = Read(cpu, rm);
                Push(cpu, next_ip);
                cpu.regs().ip = target;
                return StepStatus::kOk;
            }
            case 3: {  // CALL far, through a memory pair -- offset then segment
                if (rm.is_register) {
                    cpu.regs().ip = entry_ip;           // refuse cleanly
                    return StepStatus::kUnimplemented;  // m16:16 only
                }
                const std::uint16_t segment = SegmentValue(cpu.regs(), rm.segment);
                const std::uint16_t offset = cpu.ReadWordAt(segment, rm.offset);
                const std::uint16_t target =
                    cpu.ReadWordAt(segment, static_cast<std::uint16_t>(rm.offset + 2));
                Push(cpu, cpu.regs().cs);
                Push(cpu, next_ip);
                cpu.regs().cs = target;
                cpu.regs().ip = offset;
                return StepStatus::kOk;
            }
            case 4:  // JMP near, indirect
                cpu.regs().ip = Read(cpu, rm);
                return StepStatus::kOk;
            case 5: {  // JMP far, indirect
                if (rm.is_register) {
                    cpu.regs().ip = entry_ip;
                    return StepStatus::kUnimplemented;
                }
                const std::uint16_t segment = SegmentValue(cpu.regs(), rm.segment);
                const std::uint16_t offset = cpu.ReadWordAt(segment, rm.offset);
                const std::uint16_t target =
                    cpu.ReadWordAt(segment, static_cast<std::uint16_t>(rm.offset + 2));
                cpu.regs().cs = target;
                cpu.regs().ip = offset;
                return StepStatus::kOk;
            }
            case 7:
                // Group 5 has no eighth member. IP goes back, because a
                // refused instruction must leave the processor exactly where
                // it was -- that is what abi.h promises a caller.
                cpu.regs().ip = entry_ip;
                return StepStatus::kUnimplemented;
            case 6: {  // PUSH r/m16
                // Decrement, then read -- the same order as 50-57, and for
                // the same measured reason. `FF F4` (PUSH SP) stores the
                // decremented value in 277 of 277 cases.
                cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp - 2);
                cpu.WriteWordAt(cpu.regs().ss, cpu.regs().sp, Read(cpu, rm));
                return StepStatus::kOk;
            }
            default:
                cpu.regs().ip = entry_ip;
                return StepStatus::kUnimplemented;
        }
    }

    // --- PUSH r16 / POP r16 -----------------------------------------------
    if (opcode >= 0x50 && opcode <= 0x57) {
        // **SP decrements first, and only then is the operand read.** For
        // `PUSH SP` that means the DECREMENTED value reaches the stack.
        //
        // This comment used to say the opposite -- that the 8086 stores the
        // value SP held before its own decrement, "the classic way to tell an
        // 8086 from a 286 in software" -- and the code read the register
        // first to match. It is wrong on this part. Measured on the AMD D8088
        // the corpus was captured from: SP=DD10 pushes DD0E, in 10,000 cases
        // out of 10,000.
        //
        // Nothing caught it for two tickets because opcode 54 is the only
        // encoding where the two orders differ, and 54 was not among the
        // corpus files anyone had fetched -- 50, 51 and 52 push AX, CX and DX,
        // where the question does not arise. The whole opcode scored 0.00% the
        // moment its file was downloaded. `FF /6`, the other encoding of
        // PUSH SP, agrees: 277 of 277.
        cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp - 2);
        cpu.WriteWordAt(cpu.regs().ss, cpu.regs().sp,
                        ReadWordRegister(cpu.regs(), instruction.reg_in_opcode));
        return StepStatus::kOk;
    }
    if (opcode >= 0x58 && opcode <= 0x5F) {
        const std::uint16_t value = Pop(cpu);
        WriteWordRegister(cpu.regs(), instruction.reg_in_opcode, value);
        return StepStatus::kOk;
    }

    // --- Jcc rel8, and its undocumented second copy at 0x60-0x6F -----------
    if (opcode >= 0x60 && opcode <= 0x7F) {
        if (Condition(static_cast<std::uint8_t>(opcode & 0x0F), cpu.regs().flags)) {
            cpu.regs().ip = static_cast<std::uint16_t>(next_ip + instruction.immediate);
        }
        return StepStatus::kOk;
    }

    // --- the string instructions ------------------------------------------
    // A repeated string operation is ONE instruction that runs to completion:
    // `F3 A4` with CX=84 moves 84 bytes and advances IP by two. It is not 84
    // steps. (Real hardware can be interrupted mid-loop and resumes by
    // re-executing the prefix; nothing here can be interrupted yet, and OH-5
    // is where that matters.)
    if (IsStringOpcode(opcode)) {
        if (instruction.repeat == Rep::kNone) {
            StringIteration(cpu, opcode, instruction.wide, instruction.segment_override);
            return StepStatus::kOk;
        }
        const bool until = instruction.repeat == Rep::kWhileZero;
        while (cpu.regs().cx != 0) {
            StringIteration(cpu, opcode, instruction.wide, instruction.segment_override);
            cpu.regs().cx = static_cast<std::uint16_t>(cpu.regs().cx - 1);
            // The count comes down first, then the condition is tested. On
            // MOVS, STOS and LODS there is no condition and both prefixes
            // mean the same thing.
            if (StringSetsZero(opcode) && HasFlag(cpu.regs().flags, kZero) != until) {
                break;
            }
        }
        return StepStatus::kOk;
    }

    // --- group 3, 0xF6/0xF7 -----------------------------------------------
    // Seven instructions behind two opcodes. TEST, NOT and NEG are operand
    // shaped and stay here; the four that produce a double-width result go
    // through muldiv.cc.
    if (opcode == 0xF6 || opcode == 0xF7) {
        const Operand rm = ResolveRm(cpu, instruction);
        const std::uint16_t value = Read(cpu, rm);
        std::uint16_t flags = cpu.regs().flags;

        switch (instruction.modrm.reg) {
            case 0:
            case 1: {  // TEST r/m, imm -- AND with the result thrown away
                Alu(AluKind::kAnd, value,
                    static_cast<std::uint16_t>(instruction.immediate), instruction.wide, flags);
                break;
            }
            case 2:  // NOT -- the only member that touches no flag at all
                Write(cpu, rm, static_cast<std::uint16_t>(~value));
                return StepStatus::kOk;
            case 3: {  // NEG -- SUB from zero, and its flags are exactly that
                const std::uint16_t result = Alu(AluKind::kSub, 0, value, instruction.wide, flags);
                Write(cpu, rm, result);
                break;
            }
            default: {
                const MulDivResult result =
                    MulDiv(static_cast<MulDivKind>(instruction.modrm.reg), cpu.regs().ax,
                           cpu.regs().dx, value, instruction.wide, flags);
                cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
                if (result.divide_error) {
                    RaiseInterrupt(cpu, 0, next_ip);
                    return StepStatus::kOk;
                }
                cpu.regs().ax = result.ax;
                cpu.regs().dx = result.dx;
                return StepStatus::kOk;
            }
        }
        cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
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

    // --- PUSH/POP a segment register ---------------------------------------
    // Opcode bits 4:3 name the register in the same order Segment does, and
    // bit 0 is the direction.
    // `< 0x20` for the same reason as in Lookup: 27, 2F, 37 and 3F are the
    // BCD adjusts, not stack ops, and a wider test shadows them.
    if (opcode < 0x20 && (opcode & 0x07) >= 0x06) {
        const Segment which = static_cast<Segment>((opcode >> 3) & 0x03);
        if ((opcode & 0x01) == 0) {
            Push(cpu, SegmentValue(cpu.regs(), which));
            return StepStatus::kOk;
        }
        const std::uint16_t value = Pop(cpu);
        switch (which) {
            case Segment::kEs: cpu.regs().es = value; break;
            // 0x0F is POP CS. The part executes it -- it is not an invalid
            // opcode -- but **SST8088 has no file for it**, so this line is
            // the one instruction in the core with no hardware oracle behind
            // it. Written by symmetry with the other three and labelled as
            // such rather than left to refuse, because refusing would be an
            // equally unverified claim in the other direction.
            case Segment::kCs: cpu.regs().cs = value; break;
            case Segment::kSs: cpu.regs().ss = value; break;
            default: cpu.regs().ds = value; break;
        }
        return StepStatus::kOk;
    }

    // --- XCHG AX, r16 -------------------------------------------------------
    if (opcode >= 0x91 && opcode <= 0x97) {
        const std::uint16_t other = ReadWordRegister(cpu.regs(), instruction.reg_in_opcode);
        WriteWordRegister(cpu.regs(), instruction.reg_in_opcode, cpu.regs().ax);
        cpu.regs().ax = other;
        return StepStatus::kOk;
    }

    // --- LOOP and JCXZ ------------------------------------------------------
    // LOOP counts CX down and jumps while it is not zero; JCXZ jumps when it
    // already is and **does not decrement**. None of the four touches a flag.
    if (opcode >= 0xE0 && opcode <= 0xE3) {
        bool taken = false;
        if (opcode == 0xE3) {  // JCXZ
            taken = cpu.regs().cx == 0;
        } else {
            cpu.regs().cx = static_cast<std::uint16_t>(cpu.regs().cx - 1);
            const bool zero = HasFlag(cpu.regs().flags, kZero);
            taken = cpu.regs().cx != 0 &&
                    (opcode == 0xE2 ||                    // LOOP, no condition
                     (opcode == 0xE1 ? zero : !zero));    // LOOPZ / LOOPNZ
        }
        if (taken) {
            cpu.regs().ip = static_cast<std::uint16_t>(next_ip + instruction.immediate);
        }
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
        case 0x9B:  // WAIT -- waits for a coprocessor that is not fitted
            return StepStatus::kOk;
        case 0xF4:  // HLT
            // The one instruction with no corpus file: it cannot be
            // single-stepped on the capture rig, because the rig's next step
            // never arrives. Its behaviour is not in doubt, but this line is
            // checked by hand-written tests only, and says so.
            return StepStatus::kHalted;

        case 0x84:    // TEST r/m8, r8
        case 0x85: {  // TEST r/m16, r16
            std::uint16_t flags = cpu.regs().flags;
            Alu(AluKind::kAnd, Read(cpu, ResolveRm(cpu, instruction)),
                Read(cpu, RegOperand(instruction)), instruction.wide, flags);
            cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            return StepStatus::kOk;
        }

        case 0xC4:    // LES r16, m16:16
        case 0xC5: {  // LDS r16, m16:16
            // Loads a far pointer in one instruction: the offset into the
            // named register and the segment into ES or DS.
            const Operand rm = ResolveRm(cpu, instruction);
            if (rm.is_register) {
                cpu.regs().ip = entry_ip;
                return StepStatus::kUnimplemented;  // m16:16 only
            }
            const std::uint16_t from = SegmentValue(cpu.regs(), rm.segment);
            const std::uint16_t offset = cpu.ReadWordAt(from, rm.offset);
            const std::uint16_t segment =
                cpu.ReadWordAt(from, static_cast<std::uint16_t>(rm.offset + 2));
            WriteWordRegister(cpu.regs(), instruction.modrm.reg, offset);
            if (opcode == 0xC4) {
                cpu.regs().es = segment;
            } else {
                cpu.regs().ds = segment;
            }
            return StepStatus::kOk;
        }

        case 0xD6:  // SALC -- AL becomes 0xFF when CF is set, 0x00 when not
            WriteByteRegister(cpu.regs(), 0,
                              HasFlag(cpu.regs().flags, kCarry) ? 0xFF : 0x00);
            return StepStatus::kOk;

        // The coprocessor escapes. The effective address is computed -- and
        // on real hardware driven onto the bus for an 8087 to see -- and with
        // nothing fitted, that is the whole of it.
        case 0xD8: case 0xD9: case 0xDA: case 0xDB:
        case 0xDC: case 0xDD: case 0xDE: case 0xDF:
            return StepStatus::kOk;

        // Undocumented second encodings of the returns.
        case 0xC1:  // as C3
            cpu.regs().ip = Pop(cpu);
            return StepStatus::kOk;
        case 0xC0:  // as C2
            cpu.regs().ip = Pop(cpu);
            cpu.regs().sp =
                static_cast<std::uint16_t>(cpu.regs().sp + instruction.immediate);
            return StepStatus::kOk;
        case 0xC9:  // as CB
            cpu.regs().ip = Pop(cpu);
            cpu.regs().cs = Pop(cpu);
            return StepStatus::kOk;
        case 0xC8:  // as CA
            cpu.regs().ip = Pop(cpu);
            cpu.regs().cs = Pop(cpu);
            cpu.regs().sp =
                static_cast<std::uint16_t>(cpu.regs().sp + instruction.immediate);
            return StepStatus::kOk;

        // --- interrupts ------------------------------------------------------
        case 0xCC:  // INT3
            RaiseInterrupt(cpu, 3, next_ip);
            return StepStatus::kOk;
        case 0xCD:  // INT imm8
            RaiseInterrupt(cpu, static_cast<std::uint8_t>(instruction.immediate), next_ip);
            return StepStatus::kOk;
        case 0xCE:  // INTO -- a conditional trap, and the condition is OF
            if (HasFlag(cpu.regs().flags, kOverflow)) {
                RaiseInterrupt(cpu, 4, next_ip);
            }
            return StepStatus::kOk;
        case 0xCF:  // IRET
            cpu.regs().ip = Pop(cpu);
            cpu.regs().cs = Pop(cpu);
            cpu.regs().flags = static_cast<std::uint16_t>(Pop(cpu) | kFlagsAlwaysSet);
            return StepStatus::kOk;

        // --- far transfers and the returns that unwind arguments ------------
        case 0x9A:  // CALL far
            Push(cpu, cpu.regs().cs);
            Push(cpu, next_ip);
            cpu.regs().cs = static_cast<std::uint16_t>(instruction.displacement);
            cpu.regs().ip = static_cast<std::uint16_t>(instruction.immediate);
            return StepStatus::kOk;
        case 0xEA:  // JMP far
            cpu.regs().cs = static_cast<std::uint16_t>(instruction.displacement);
            cpu.regs().ip = static_cast<std::uint16_t>(instruction.immediate);
            return StepStatus::kOk;
        case 0xC2:  // RET imm16 -- return, then drop the caller's arguments
            cpu.regs().ip = Pop(cpu);
            cpu.regs().sp =
                static_cast<std::uint16_t>(cpu.regs().sp + instruction.immediate);
            return StepStatus::kOk;
        case 0xCB:  // RETF
            cpu.regs().ip = Pop(cpu);
            cpu.regs().cs = Pop(cpu);
            return StepStatus::kOk;
        case 0xCA:  // RETF imm16
            cpu.regs().ip = Pop(cpu);
            cpu.regs().cs = Pop(cpu);
            cpu.regs().sp =
                static_cast<std::uint16_t>(cpu.regs().sp + instruction.immediate);
            return StepStatus::kOk;

        // --- addresses and segment registers ---------------------------------
        case 0x8D: {  // LEA -- the ADDRESS, not what is at it
            const Address address =
                EffectiveAddress(cpu.regs(), instruction.modrm, instruction.displacement,
                                 instruction.segment_override);
            WriteWordRegister(cpu.regs(), instruction.modrm.reg, address.offset);
            return StepStatus::kOk;
        }
        case 0x8C: {  // MOV r/m16, sreg
            const Segment which = static_cast<Segment>(instruction.modrm.reg & 0x03);
            Write(cpu, ResolveRm(cpu, instruction), SegmentValue(cpu.regs(), which));
            return StepStatus::kOk;
        }
        case 0x8E: {  // MOV sreg, r/m16
            const std::uint16_t value = Read(cpu, ResolveRm(cpu, instruction));
            switch (static_cast<Segment>(instruction.modrm.reg & 0x03)) {
                case Segment::kEs: cpu.regs().es = value; break;
                case Segment::kCs: cpu.regs().cs = value; break;
                case Segment::kSs: cpu.regs().ss = value; break;
                default: cpu.regs().ds = value; break;
            }
            return StepStatus::kOk;
        }
        case 0x8F:  // POP r/m16
            Write(cpu, ResolveRm(cpu, instruction), Pop(cpu));
            return StepStatus::kOk;

        case 0x86:    // XCHG r/m8, r8
        case 0x87: {  // XCHG r/m16, r16
            const Operand rm = ResolveRm(cpu, instruction);
            const Operand reg = RegOperand(instruction);
            const std::uint16_t left = Read(cpu, rm);
            const std::uint16_t right = Read(cpu, reg);
            Write(cpu, rm, right);
            Write(cpu, reg, left);
            return StepStatus::kOk;
        }

        // --- sign extension, the flag byte, and the table lookup -------------
        case 0x98:  // CBW -- AL's sign fills AH
            cpu.regs().ax = static_cast<std::uint16_t>(
                static_cast<std::int16_t>(static_cast<std::int8_t>(cpu.regs().ax & 0xFF)));
            return StepStatus::kOk;
        case 0x99:  // CWD -- AX's sign fills DX
            cpu.regs().dx =
                (cpu.regs().ax & 0x8000) != 0 ? 0xFFFF : 0x0000;
            return StepStatus::kOk;

        case 0x9C:  // PUSHF
            Push(cpu, cpu.regs().flags);
            return StepStatus::kOk;
        case 0x9D:  // POPF
            cpu.regs().flags = static_cast<std::uint16_t>(Pop(cpu) | kFlagsAlwaysSet);
            return StepStatus::kOk;
        case 0x9E:  // SAHF -- AH replaces the low byte of FLAGS
            // Only the five flags that live below bit 8, and bit 1 stays high.
            cpu.regs().flags = static_cast<std::uint16_t>(
                (cpu.regs().flags & 0xFF00) |
                (ReadByteRegister(cpu.regs(), 4) & 0xD5) | 0x02);
            return StepStatus::kOk;
        case 0x9F:  // LAHF
            WriteByteRegister(cpu.regs(), 4,
                              static_cast<std::uint8_t>(cpu.regs().flags & 0xFF));
            return StepStatus::kOk;

        case 0xD7: {  // XLAT -- AL becomes the byte at [BX + AL]
            const Segment which = instruction.segment_override == Segment::kNone
                                      ? Segment::kDs
                                      : instruction.segment_override;
            const std::uint16_t offset = static_cast<std::uint16_t>(
                cpu.regs().bx + (cpu.regs().ax & 0xFF));
            WriteByteRegister(cpu.regs(), 0,
                              cpu.ReadByte(Physical(SegmentValue(cpu.regs(), which), offset)));
            return StepStatus::kOk;
        }

        // --- TEST accumulator,immediate -------------------------------------
        case 0xA8:
        case 0xA9: {
            std::uint16_t flags = cpu.regs().flags;
            Alu(AluKind::kAnd, Read(cpu, AccumulatorOperand(instruction.wide)),
                static_cast<std::uint16_t>(instruction.immediate), instruction.wide, flags);
            cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            return StepStatus::kOk;
        }

        // --- MOV between the accumulator and a direct address ---------------
        case 0xA0:  // MOV AL, [addr]
        case 0xA1:  // MOV AX, [addr]
            Write(cpu, AccumulatorOperand(instruction.wide),
                  Read(cpu, MoffsOperand(instruction)));
            return StepStatus::kOk;
        case 0xA2:  // MOV [addr], AL
        case 0xA3:  // MOV [addr], AX
            Write(cpu, MoffsOperand(instruction),
                  Read(cpu, AccumulatorOperand(instruction.wide)));
            return StepStatus::kOk;

        // --- MOV r/m,immediate ----------------------------------------------
        case 0xC6:
        case 0xC7:
            // Only `/0` is a defined encoding. The others are not refused
            // here: they decode at the same length and the part stores the
            // immediate regardless of what reg holds, so refusing would be a
            // claim the corpus does not support either way.
            Write(cpu, ResolveRm(cpu, instruction),
                  static_cast<std::uint16_t>(instruction.immediate));
            return StepStatus::kOk;

        // --- the decimal and ASCII adjusts ----------------------------------
        // All six touch AX and nothing else, so one arm serves them. The
        // immediate is read for every kind and ignored by four of them.
        case 0x27:    // DAA
        case 0x2F:    // DAS
        case 0x37:    // AAA
        case 0x3F:    // AAS
        case 0xD4:    // AAM imm8
        case 0xD5: {  // AAD imm8
            static constexpr BcdKind kKinds[] = {BcdKind::kDaa, BcdKind::kDas,
                                                 BcdKind::kAaa, BcdKind::kAas,
                                                 BcdKind::kAam, BcdKind::kAad};
            const std::size_t index = opcode == 0x27   ? 0
                                      : opcode == 0x2F ? 1
                                      : opcode == 0x37 ? 2
                                      : opcode == 0x3F ? 3
                                      : opcode == 0xD4 ? 4
                                                       : 5;
            std::uint16_t flags = cpu.regs().flags;
            const BcdResult result =
                Bcd(kKinds[index], cpu.regs().ax,
                    static_cast<std::uint8_t>(instruction.immediate & 0xFF), flags);
            cpu.regs().ax = result.ax;
            cpu.regs().flags = static_cast<std::uint16_t>(flags | kFlagsAlwaysSet);
            if (result.divide_error) {
                // Flags are already stored, because RaiseInterrupt pushes the
                // adjusted word rather than the one we arrived with.
                RaiseInterrupt(cpu, 0, next_ip);
            }
            return StepStatus::kOk;
        }

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
