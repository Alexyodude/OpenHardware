// OpenHardware — execute one 32-bit Thumb-2 instruction, Armv7E-M (OH-64).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this is the counterpart of
//
// `disasm.py`'s `_wide` tree, group for group and bit for bit. The decoder was
// written first (OH-50) and held to objdump across the whole 32-bit space; this
// file executes what that one names, and declines what that one declines. The
// split is the same one -- `op1 = hw1[12:11]` and then a few bits of each half
// -- so a reader holding the two side by side can check one against the other
// line by line, and a disagreement between them is a bug in one of the two.
//
// What it is held to is not the decoder, though: it is
// `tests/cortexm0/m4/vectors.json.gz`, which `tools/m4_oracle.py` produced by
// running every case in Unicorn 2.1.4 and icicle-emu 0.0.11 and keeping only
// what both agreed on. See that tool's docstring for why it is those two.
//
// ## What is refused, and why refusing is the right answer
//
// `Unimplemented`, for three different reasons that look the same from
// outside:
//
//   * **UNPREDICTABLE encodings** -- PC as a data-processing destination, a
//     writeback onto a register the same instruction loads, `MLS` with no
//     accumulator. The architecture says nothing about what they do, so any
//     behaviour here would be invented, and the oracle filtered them out for
//     the same reason (see `_unpredictable_pc` in `tools/m4_oracle.py`).
//   * **Groups this slice does not cover** -- the DSP extension's saturating
//     and SIMD arithmetic, the exclusives, the table branches, `BLX`
//     immediate (which would change to Arm state, which an M-profile part does
//     not have), the coprocessor and FPU space, and the system group
//     (`MSR`, `MRS`, the barriers). Each would need vectors of its own before
//     it could be trusted, and `m4_oracle.REFUSED` lists what it never
//     generated.
//   * **PC-relative loads** (`LDR.W Rt, [PC, #imm12]`), which the oracle could
//     not vector: its code page is execute-only, and the two emulators
//     disagree about reading one.
//
// A program that reaches any of them stops, naming the address, rather than
// running on past an instruction that did not happen -- the contract in
// cpu.h's `StepResult`.
//
// ## Flags, again
//
// Thumb-2 makes setting the flags a choice, the `S` bit, where Thumb-16 made
// it a property of the encoding. Three rules, each of which the vectors caught
// at least one emulator breaking (see the ticket's notes):
//
//   * A logical operation with `S` sets N and Z from the result and **C from
//     the operand's shifter** -- from `ThumbExpandImm_C` for an immediate, from
//     the shift for a register. V is never touched.
//   * An arithmetic operation with `S` sets all four from `AddWithCarry`.
//   * Without `S` nothing is written, including by `MUL`, which in its narrow
//     form always sets N and Z.

#include "thumb2.h"

#include "exec.h"
#include "shift.h"

namespace cortexm0 {
namespace {

inline uint32_t bits(uint32_t value, unsigned high, unsigned low) {
    return (value >> low) & ((1u << (high - low + 1)) - 1u);
}

inline bool bit(uint32_t value, unsigned n) { return ((value >> n) & 1u) != 0; }

/// The low `width` bits set. `width` 32 is the whole word, which `1u << 32`
/// would not give: shifting by the width of the type is undefined in C++.
inline uint32_t low_mask(unsigned width) {
    return width >= 32 ? 0xFFFFFFFFu : (1u << width) - 1u;
}

inline uint32_t sign_extend_bits(uint32_t value, unsigned width) {
    const uint32_t sign = 1u << (width - 1);
    value &= low_mask(width);
    return (value ^ sign) - sign;
}

/// `ThumbExpandImm_C`, DDI0403 A5.3.2, with the carry it produces.
///
/// The value half is `disasm._expand_immediate`'s and that function's comment
/// is the one to read for the four repeat patterns. The half that matters
/// here is the carry, because it is where icicle-emu is wrong: **a rotated
/// constant sets C to bit 31 of the constant**, and a repeated one leaves C
/// alone. icicle keeps C in both cases, Unicorn does not, and the manual is
/// on Unicorn's side -- `ROR_C` returns the result's top bit as its carry, and
/// only the `00` patterns skip it. The vectors keep only the cases where the
/// two happen to agree (C already equal to bit 31), so the rule itself is held
/// by a hand-written test in `test_thumb2_exec.py` rather than by them.
///
/// A repeat pattern of a zero byte is UNPREDICTABLE, and returns false.
bool expand_immediate(uint32_t imm12, bool carry_in, Shifted& out) {
    if ((imm12 >> 10) == 0) {
        const uint32_t byte = imm12 & 0xFFu;
        const unsigned kind = (imm12 >> 8) & 3u;
        if (kind != 0 && byte == 0) {
            return false;
        }
        switch (kind) {
            case 0: out = {byte, carry_in}; break;
            case 1: out = {byte | (byte << 16), carry_in}; break;
            case 2: out = {(byte << 8) | (byte << 24), carry_in}; break;
            default: out = {byte * 0x01010101u, carry_in}; break;
        }
        return true;
    }
    out = ror(0x80u | (imm12 & 0x7Fu), (imm12 >> 7) & 0x1Fu, carry_in);
    return true;
}

/// `DecodeImmShift` then `Shift_C`, the shifted-register operand.
///
/// The three readings of a zero amount that `disasm._shift_suffix` describes
/// are all here: `LSL #0` is no shift and keeps C; `LSR #0` and `ASR #0` are
/// shifts by 32; and `ROR #0` is `RRX`, a one-bit rotate *through* carry,
/// whose carry out is the bit that fell off the bottom.
Shifted shift_immediate(uint32_t value, unsigned type, unsigned amount, bool carry_in) {
    switch (type) {
        case 0: return lsl(value, amount, carry_in);
        case 1: return lsr(value, amount == 0 ? 32u : amount, carry_in);
        case 2: return asr(value, amount == 0 ? 32u : amount, carry_in);
        default:
            if (amount == 0) {
                return {(carry_in ? 0x80000000u : 0u) | (value >> 1), bit(value, 0)};
            }
            return ror(value, amount, carry_in);
    }
}

/// `Shift_C` by a register amount: the bottom byte only, zero meaning none.
Shifted shift_register(uint32_t value, unsigned type, uint32_t amount, bool carry_in) {
    amount &= 0xFFu;
    switch (type) {
        case 0: return lsl(value, amount, carry_in);
        case 1: return lsr(value, amount, carry_in);
        case 2: return asr(value, amount, carry_in);
        default: return ror(value, amount, carry_in);
    }
}

// --- data processing --------------------------------------------------------
//
// The modified-immediate and shifted-register groups share one table of
// sixteen operations, `disasm.DP_OPS`, and differ only in where the second
// operand comes from. So both decode their operand and hand it here.

StepResult data_processing(Cpu& cpu, unsigned op, bool setflags, unsigned rn,
                           unsigned rd, Shifted operand) {
    const bool compare = rd == kPc && setflags;
    if (rd == kPc && !compare) {
        return StepResult::Unimplemented;   // a branch by arithmetic: UNPREDICTABLE
    }
    // Two operations read no Rn at all when it is PC: ORR becomes MOV and ORN
    // becomes MVN. Everywhere else, Rn = PC is UNPREDICTABLE (`ADR` is the
    // plain-immediate group's, not this one's).
    const bool from_pc = rn == kPc && (op == 2 || op == 3);
    if (rn == kPc && !from_pc) {
        return StepResult::Unimplemented;
    }
    // The compare forms exist only for AND, EOR, ADD and SUB. Rd = PC with S
    // on any other operation is UNPREDICTABLE.
    if (compare && op != 0 && op != 4 && op != 8 && op != 13) {
        return StepResult::Unimplemented;
    }
    const uint32_t left = from_pc ? 0u : cpu.reg(rn);
    const uint32_t right = operand.value;

    uint32_t logical = 0;
    switch (op) {
        case 0: logical = left & right; break;                        // AND, TST
        case 1: logical = left & ~right; break;                       // BIC
        case 2: logical = from_pc ? right : (left | right); break;    // ORR, MOV
        case 3: logical = from_pc ? ~right : (left | ~right); break;  // ORN, MVN
        case 4: logical = left ^ right; break;                        // EOR, TEQ
        default: {
            Sum sum{};
            switch (op) {
                case 8: sum = add_with_carry(left, right, false); break;       // ADD, CMN
                case 10: sum = add_with_carry(left, right, cpu.c()); break;    // ADC
                case 11: sum = add_with_carry(left, ~right, cpu.c()); break;   // SBC
                case 13: sum = add_with_carry(left, ~right, true); break;      // SUB, CMP
                case 14: sum = add_with_carry(~left, right, true); break;      // RSB
                default: return StepResult::Unimplemented;  // PKH and the holes
            }
            if (!compare) {
                cpu.set_reg(rd, sum.value);
            }
            if (setflags) {
                cpu.set_nz(sum.value);
                cpu.set_c(sum.carry);
                cpu.set_v(sum.overflow);
            }
            return StepResult::Ok;
        }
    }
    if (!compare) {
        cpu.set_reg(rd, logical);
    }
    if (setflags) {
        cpu.set_nz(logical);
        cpu.set_c(operand.carry);
    }
    return StepResult::Ok;
}

StepResult modified_immediate(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const uint32_t imm12 = (bits(hw1, 10, 10) << 11) | (bits(hw2, 14, 12) << 8) | bits(hw2, 7, 0);
    Shifted operand{};
    if (!expand_immediate(imm12, cpu.c(), operand)) {
        return StepResult::Unimplemented;
    }
    return data_processing(cpu, bits(hw1, 8, 5), bit(hw1, 4), bits(hw1, 3, 0),
                           bits(hw2, 11, 8), operand);
}

StepResult shifted_register(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    if (bit(hw2, 15)) {
        return StepResult::Unimplemented;
    }
    const unsigned rm = bits(hw2, 3, 0);
    if (rm == kPc) {
        return StepResult::Unimplemented;
    }
    const unsigned amount = (bits(hw2, 14, 12) << 2) | bits(hw2, 7, 6);
    const Shifted operand = shift_immediate(cpu.reg(rm), bits(hw2, 5, 4), amount, cpu.c());
    return data_processing(cpu, bits(hw1, 8, 5), bit(hw1, 4), bits(hw1, 3, 0),
                           bits(hw2, 11, 8), operand);
}

/// The plain-binary-immediate group: `ADDW`, `SUBW`, `MOVW`, `MOVT` and the
/// bitfield operations. None of them sets flags.
StepResult plain_immediate(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const unsigned op = bits(hw1, 8, 4);
    const unsigned rn = bits(hw1, 3, 0);
    const unsigned rd = bits(hw2, 11, 8);
    if (rd == kPc) {
        return StepResult::Unimplemented;
    }
    const uint32_t imm12 = (bits(hw1, 10, 10) << 11) | (bits(hw2, 14, 12) << 8) | bits(hw2, 7, 0);
    switch (op) {
        case 0b00000:                                                   // ADDW
        case 0b01010:                                                   // SUBW
            if (rn == kPc) {
                return StepResult::Unimplemented;   // ADR, PC-relative; see the file note
            }
            cpu.set_reg(rd, op == 0 ? cpu.reg(rn) + imm12 : cpu.reg(rn) - imm12);
            return StepResult::Ok;
        case 0b00100:                                                   // MOVW
            cpu.set_reg(rd, (rn << 12) | imm12);
            return StepResult::Ok;
        case 0b01100:                                                   // MOVT
            cpu.set_reg(rd, (cpu.reg(rd) & 0xFFFFu) | (((rn << 12) | imm12) << 16));
            return StepResult::Ok;
        default:
            break;
    }
    // The bitfields leave two bits of the encoding that must be zero, the
    // same two `disasm._wide_plain_immediate` checks before naming one.
    if ((hw2 & 0x8020u) != 0 || bit(hw1, 10)) {
        return StepResult::Unimplemented;
    }
    const unsigned lsb = (bits(hw2, 14, 12) << 2) | bits(hw2, 7, 6);
    const unsigned tail = bits(hw2, 4, 0);
    if (op == 0b10100 || op == 0b11100) {                               // SBFX, UBFX
        const unsigned width = tail + 1;
        if (rn == kPc || lsb + width > 32) {
            return StepResult::Unimplemented;
        }
        const uint32_t field = (cpu.reg(rn) >> lsb) & low_mask(width);
        cpu.set_reg(rd, op == 0b10100 ? sign_extend_bits(field, width) : field);
        return StepResult::Ok;
    }
    if (op == 0b10110) {                                                // BFI, BFC
        // `tail` is the msb here, not a width: the one bitfield encoding that
        // names both ends of the field rather than one end and a length.
        if (tail < lsb) {
            return StepResult::Unimplemented;
        }
        const uint32_t mask = low_mask(tail - lsb + 1) << lsb;
        const uint32_t insert = rn == kPc ? 0u : (cpu.reg(rn) << lsb);
        cpu.set_reg(rd, (cpu.reg(rd) & ~mask) | (insert & mask));
        return StepResult::Ok;
    }
    return StepResult::Unimplemented;  // SSAT, USAT and the halfword forms: DSP
}

// --- branches ---------------------------------------------------------------

StepResult branch(Cpu& cpu, uint16_t hw1, uint16_t hw2, uint32_t address,
                  bool in_it, bool last_in_it) {
    const uint32_t s = bit(hw1, 10);
    const uint32_t j1 = bit(hw2, 13);
    const uint32_t j2 = bit(hw2, 11);
    const uint32_t imm11 = bits(hw2, 10, 0);
    const bool link = bit(hw2, 14);
    const bool wide_form = bit(hw2, 12);
    const uint32_t base = address + 4;

    if (!link && !wide_form) {
        // B<c>.W, T3 -- or, with a condition of 1110 or 1111, the
        // miscellaneous-control group (MSR, MRS, the hints and barriers),
        // which this slice does not execute.
        const unsigned condition = bits(hw1, 9, 6);
        if (condition >= 0xE || in_it) {
            return StepResult::Unimplemented;
        }
        if (condition_holds(cpu, condition)) {
            const uint32_t offset = sign_extend_bits(
                (s << 20) | (j2 << 19) | (j1 << 18) | (bits(hw1, 5, 0) << 12) | (imm11 << 1), 21);
            cpu.set_reg(kPc, base + offset);
        }
        return StepResult::Ok;
    }
    if (link && !wide_form) {
        return StepResult::Unimplemented;   // BLX immediate: to Arm state, which M-profile lacks
    }
    // B.W and BL. Both are allowed inside an IT block only as its last
    // instruction; anywhere earlier they are UNPREDICTABLE.
    if (in_it && !last_in_it) {
        return StepResult::Unimplemented;
    }
    // `I = NOT(J EOR S)`; see `disasm._wide_branch` for why it is not J.
    const uint32_t i1 = 1u - (j1 ^ s);
    const uint32_t i2 = 1u - (j2 ^ s);
    const uint32_t offset = sign_extend_bits(
        (s << 24) | (i1 << 23) | (i2 << 22) | (bits(hw1, 9, 0) << 12) | (imm11 << 1), 25);
    if (link) {
        cpu.set_reg(kLr, base | 1u);
    }
    cpu.set_reg(kPc, base + offset);
    return StepResult::Ok;
}

// --- memory ---------------------------------------------------------------
//
// **No alignment checks**, which is the V6M core's memory model and is
// deliberate there for the reason cpu.h gives: `read_word` and its kin are
// byte-wise and work at any offset. On an M4 that is right for the single
// loads and stores, which are permitted unaligned, and wrong for `LDM`,
// `STM`, `LDRD` and `STRD`, which take a UsageFault -- a fault this core does
// not model. A compiler never emits one unaligned, so the difference shows
// only in a program that is already broken.

/// Every word read before any register is written, so a fault partway down
/// the list leaves the register file as it was -- the `StepResult` contract.
StepResult load_store_multiple(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const unsigned op = bits(hw1, 8, 7);
    const bool writeback = bit(hw1, 5);
    const bool load = bit(hw1, 4);
    const unsigned rn = bits(hw1, 3, 0);
    const uint32_t list = hw2;
    if ((op != 0b01 && op != 0b10) || rn == kPc || list == 0) {
        return StepResult::Unimplemented;
    }
    if (writeback && (list & (1u << rn))) {
        return StepResult::Unimplemented;   // UNPREDICTABLE, and filtered from the vectors
    }
    if (!load && (list & (1u << kPc))) {
        return StepResult::Unimplemented;   // storing PC is UNPREDICTABLE
    }
    unsigned count = 0;
    for (unsigned i = 0; i < 16; ++i) {
        count += (list >> i) & 1u;
    }
    const uint32_t start = cpu.reg(rn);
    const uint32_t lowest = op == 0b01 ? start : start - 4u * count;
    const uint32_t after = op == 0b01 ? start + 4u * count : start - 4u * count;

    if (!load) {
        uint32_t at = lowest;
        for (unsigned i = 0; i < 16; ++i) {
            if (list & (1u << i)) {
                if (!cpu.write_word(at, cpu.reg(i))) return StepResult::MemoryFault;
                at += 4;
            }
        }
        if (writeback) {
            cpu.set_reg(rn, after);
        }
        return StepResult::Ok;
    }

    uint32_t words[16] = {};
    uint32_t at = lowest;
    for (unsigned i = 0; i < 16; ++i) {
        if (list & (1u << i)) {
            if (!cpu.read_word(at, words[i])) return StepResult::MemoryFault;
            at += 4;
        }
    }
    for (unsigned i = 0; i < 15; ++i) {
        if (list & (1u << i)) {
            cpu.set_reg(i, words[i]);
        }
    }
    // The base before PC, as `POP {pc}` does in exec.cc: a `POP.W` that
    // returns from an exception unstacks from SP, and has to unstack from the
    // SP that is past the words it just popped.
    if (writeback) {
        cpu.set_reg(rn, after);
    }
    if (list & (1u << kPc)) {
        return write_pc_or_return(cpu, words[kPc]);
    }
    return StepResult::Ok;
}

StepResult load_store_dual(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const bool pre = bit(hw1, 8);
    const bool up = bit(hw1, 7);
    const bool writeback = bit(hw1, 5);
    const bool load = bit(hw1, 4);
    const unsigned rn = bits(hw1, 3, 0);
    const unsigned rt = bits(hw2, 15, 12);
    const unsigned rt2 = bits(hw2, 11, 8);
    if (!pre && !writeback) {
        return StepResult::Unimplemented;   // the exclusives and the table branches
    }
    if (rn == kPc || rt == kPc || rt2 == kPc || (load && rt == rt2)) {
        return StepResult::Unimplemented;
    }
    if (writeback && (rn == rt || rn == rt2)) {
        return StepResult::Unimplemented;
    }
    const uint32_t offset = bits(hw2, 7, 0) << 2;
    const uint32_t base = cpu.reg(rn);
    const uint32_t moved = up ? base + offset : base - offset;
    const uint32_t at = pre ? moved : base;
    if (load) {
        uint32_t first = 0;
        uint32_t second = 0;
        if (!cpu.read_word(at, first) || !cpu.read_word(at + 4, second)) {
            return StepResult::MemoryFault;
        }
        cpu.set_reg(rt, first);
        cpu.set_reg(rt2, second);
    } else {
        if (!cpu.write_word(at, cpu.reg(rt)) || !cpu.write_word(at + 4, cpu.reg(rt2))) {
            return StepResult::MemoryFault;
        }
    }
    if (writeback) {
        cpu.set_reg(rn, moved);
    }
    return StepResult::Ok;
}

/// LDR/STR, byte, halfword and word, signed and not, in their three shapes.
/// See `disasm._wide_load_store_single` for the shapes.
StepResult load_store_single(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const bool sign = bit(hw1, 8);
    const bool imm12_form = bit(hw1, 7);
    const unsigned size = bits(hw1, 6, 5);  // 0 byte, 1 halfword, 2 word
    const bool load = bit(hw1, 4);
    const unsigned rn = bits(hw1, 3, 0);
    const unsigned rt = bits(hw2, 15, 12);
    if (size == 3 || (sign && (!load || size == 2))) {
        return StepResult::Unimplemented;
    }
    if (rn == kPc) {
        return StepResult::Unimplemented;   // PC-relative; see the file note
    }
    // A byte or halfword "load" into PC is a preload hint (PLD, PLI), and a
    // store of PC is UNPREDICTABLE.
    if (rt == kPc && (!load || size != 2)) {
        return StepResult::Unimplemented;
    }

    const uint32_t base = cpu.reg(rn);
    uint32_t at = base;
    uint32_t moved = base;
    bool writeback = false;
    if (imm12_form) {
        at = base + bits(hw2, 11, 0);
    } else if (bit(hw2, 11)) {
        const bool pre = bit(hw2, 10);
        const bool up = bit(hw2, 9);
        writeback = bit(hw2, 8);
        if (!pre && !writeback) {
            return StepResult::Unimplemented;
        }
        const uint32_t offset = bits(hw2, 7, 0);
        moved = up ? base + offset : base - offset;
        at = pre ? moved : base;
    } else {
        if (bits(hw2, 11, 6) != 0) {
            return StepResult::Unimplemented;
        }
        const unsigned rm = bits(hw2, 3, 0);
        if (rm == kPc) {
            return StepResult::Unimplemented;
        }
        at = base + (cpu.reg(rm) << bits(hw2, 5, 4));
    }
    if (writeback && rn == rt) {
        return StepResult::Unimplemented;   // UNPREDICTABLE
    }

    if (!load) {
        const uint32_t value = cpu.reg(rt);
        bool ok = false;
        switch (size) {
            case 0: ok = cpu.write_byte_checked(at, static_cast<uint8_t>(value)); break;
            case 1: ok = cpu.write_halfword(at, static_cast<uint16_t>(value)); break;
            default: ok = cpu.write_word(at, value); break;
        }
        if (!ok) return StepResult::MemoryFault;
        if (writeback) cpu.set_reg(rn, moved);
        return StepResult::Ok;
    }

    uint32_t value = 0;
    switch (size) {
        case 0: {
            uint8_t byte = 0;
            if (!cpu.read_byte_checked(at, byte)) return StepResult::MemoryFault;
            value = sign ? sign_extend_bits(byte, 8) : byte;
            break;
        }
        case 1: {
            uint16_t half = 0;
            if (!cpu.read_halfword(at, half)) return StepResult::MemoryFault;
            value = sign ? sign_extend_bits(half, 16) : half;
            break;
        }
        default:
            if (!cpu.read_word(at, value)) return StepResult::MemoryFault;
            break;
    }
    if (writeback) cpu.set_reg(rn, moved);
    if (rt == kPc) {
        return write_pc_or_return(cpu, value);
    }
    cpu.set_reg(rt, value);
    return StepResult::Ok;
}

// --- the register group: shifts by register, extends, CLZ, REV -----------

/// `sxtb16`/`uxtb16`'s operation, and the accumulating forms', per halfword.
uint32_t per_halfword(uint32_t accumulate, uint32_t rotated, bool is_signed) {
    const uint32_t low = is_signed ? sign_extend_bits(rotated & 0xFFu, 8) : (rotated & 0xFFu);
    const uint32_t high = is_signed ? sign_extend_bits((rotated >> 16) & 0xFFu, 8)
                                    : ((rotated >> 16) & 0xFFu);
    const uint32_t lo16 = ((accumulate & 0xFFFFu) + low) & 0xFFFFu;
    const uint32_t hi16 = ((accumulate >> 16) + high) & 0xFFFFu;
    return lo16 | (hi16 << 16);
}

uint32_t reverse_bits(uint32_t value) {
    uint32_t out = 0;
    for (unsigned i = 0; i < 32; ++i) {
        out = (out << 1) | ((value >> i) & 1u);
    }
    return out;
}

StepResult register_group(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    if (bits(hw2, 15, 12) != 0xF) {
        return StepResult::Unimplemented;
    }
    const unsigned rn = bits(hw1, 3, 0);
    const unsigned rd = bits(hw2, 11, 8);
    const unsigned rm = bits(hw2, 3, 0);
    const unsigned kind = bits(hw2, 7, 4);
    const unsigned op = bits(hw1, 6, 4);
    if (rd == kPc || rm == kPc) {
        return StepResult::Unimplemented;
    }

    if (!bit(hw1, 7) && kind == 0) {                       // LSL/LSR/ASR/ROR.W Rd, Rn, Rm
        if (rn == kPc) return StepResult::Unimplemented;
        const Shifted shifted =
            shift_register(cpu.reg(rn), bits(hw1, 6, 5), cpu.reg(rm), cpu.c());
        cpu.set_reg(rd, shifted.value);
        if (bit(hw1, 4)) {
            cpu.set_nz(shifted.value);
            cpu.set_c(shifted.carry);
        }
        return StepResult::Ok;
    }
    if (!bit(hw1, 7) && (kind >> 2) == 0b10) {             // the extends
        if (op > 5) return StepResult::Unimplemented;
        const uint32_t rotated = ror(cpu.reg(rm), bits(hw2, 5, 4) * 8u, false).value;
        const bool accumulate = rn != kPc;
        const uint32_t base = accumulate ? cpu.reg(rn) : 0u;
        uint32_t result = 0;
        switch (op) {
            case 0: result = base + sign_extend_bits(rotated, 16); break;    // SXT(A)H
            case 1: result = base + (rotated & 0xFFFFu); break;              // UXT(A)H
            case 2: result = per_halfword(base, rotated, true); break;       // SXT(A)B16
            case 3: result = per_halfword(base, rotated, false); break;      // UXT(A)B16
            case 4: result = base + sign_extend_bits(rotated, 8); break;     // SXT(A)B
            default: result = base + (rotated & 0xFFu); break;               // UXT(A)B
        }
        cpu.set_reg(rd, result);
        return StepResult::Ok;
    }
    // CLZ and the REV family name their one operand twice, in hw1[3:0] and
    // hw2[3:0]. The two must agree; where they do not the encoding is
    // UNPREDICTABLE, and the generator dropped every such case.
    if (bit(hw1, 7) && kind == 0b1000 && op == 0b011) {    // CLZ
        if (rn != rm) return StepResult::Unimplemented;
        const uint32_t value = cpu.reg(rm);
        unsigned zeros = 0;
        while (zeros < 32 && !bit(value, 31 - zeros)) {
            ++zeros;
        }
        cpu.set_reg(rd, zeros);
        return StepResult::Ok;
    }
    if (bit(hw1, 7) && op == 0b001 && (kind >> 2) == 0b10) {
        if (rn != rm) return StepResult::Unimplemented;
        const uint32_t v = cpu.reg(rm);
        uint32_t result = 0;
        switch (kind & 3u) {
            case 0:                                                           // REV
                result = (v >> 24) | ((v >> 8) & 0xFF00u) | ((v << 8) & 0xFF0000u) | (v << 24);
                break;
            case 1:                                                           // REV16
                result = ((v >> 8) & 0x00FF00FFu) | ((v << 8) & 0xFF00FF00u);
                break;
            case 2: result = reverse_bits(v); break;                          // RBIT
            default:                                                          // REVSH
                result = sign_extend_bits(((v & 0xFFu) << 8) | ((v >> 8) & 0xFFu), 16);
                break;
        }
        cpu.set_reg(rd, result);
        return StepResult::Ok;
    }
    return StepResult::Unimplemented;  // the DSP parallel and saturating arithmetic
}

// --- multiply and divide ------------------------------------------------------

StepResult multiply(Cpu& cpu, uint16_t hw1, uint16_t hw2) {
    const bool long_form = bit(hw1, 7);
    const unsigned op = bits(hw1, 6, 4);
    const unsigned rn = bits(hw1, 3, 0);
    const unsigned ra = bits(hw2, 15, 12);
    const unsigned rd = bits(hw2, 11, 8);
    const unsigned rm = bits(hw2, 3, 0);
    const unsigned kind = bits(hw2, 7, 4);
    if (rn == kPc || rm == kPc || rd == kPc) {
        return StepResult::Unimplemented;
    }
    const uint32_t left = cpu.reg(rn);
    const uint32_t right = cpu.reg(rm);

    if (!long_form) {
        if (op != 0 || bits(hw2, 7, 6) != 0) return StepResult::Unimplemented;
        const uint32_t product = left * right;
        if (kind == 0) {                                     // MUL, MLA
            cpu.set_reg(rd, ra == kPc ? product : product + cpu.reg(ra));
            return StepResult::Ok;
        }
        if (kind == 1 && ra != kPc) {                        // MLS
            cpu.set_reg(rd, cpu.reg(ra) - product);
            return StepResult::Ok;
        }
        return StepResult::Unimplemented;  // the DSP halfword multiplies
    }

    const unsigned low = ra;
    const unsigned high = rd;
    if (kind == 0 && (op == 0 || op == 2 || op == 4 || op == 6)) {
        if (low == kPc || low == high) return StepResult::Unimplemented;
        const bool is_signed = op == 0 || op == 4;
        uint64_t result = is_signed
            ? static_cast<uint64_t>(static_cast<int64_t>(static_cast<int32_t>(left)) *
                                    static_cast<int64_t>(static_cast<int32_t>(right)))
            : static_cast<uint64_t>(left) * static_cast<uint64_t>(right);
        if (op >= 4) {                                       // SMLAL, UMLAL
            result += (static_cast<uint64_t>(cpu.reg(high)) << 32) | cpu.reg(low);
        }
        cpu.set_reg(low, static_cast<uint32_t>(result));
        cpu.set_reg(high, static_cast<uint32_t>(result >> 32));
        return StepResult::Ok;
    }
    if (kind == 0xF && (op == 1 || op == 3) && low == kPc) {
        // **Divide by zero is zero**, because CCR.DIV_0_TRP resets clear and
        // this core does not model setting it. INT_MIN / -1 overflows, and the
        // architecture defines that result as INT_MIN rather than trapping --
        // which C++ would not do for us: in C++ it is undefined behaviour.
        uint32_t quotient = 0;
        if (right != 0) {
            if (op == 3) {
                quotient = left / right;
            } else if (left == 0x80000000u && right == 0xFFFFFFFFu) {
                quotient = 0x80000000u;
            } else {
                quotient = static_cast<uint32_t>(static_cast<int32_t>(left) /
                                                 static_cast<int32_t>(right));
            }
        }
        cpu.set_reg(high, quotient);
        return StepResult::Ok;
    }
    return StepResult::Unimplemented;  // UMAAL and the DSP long multiplies
}

}  // namespace

StepResult execute_thumb2(Cpu& cpu, uint16_t first, uint16_t second,
                          uint32_t address, bool in_it, bool last_in_it) {
    const unsigned op1 = bits(first, 12, 11);
    if (op1 == 0b10) {
        if (bit(second, 15)) {
            return branch(cpu, first, second, address, in_it, last_in_it);
        }
        return bit(first, 9) ? plain_immediate(cpu, first, second)
                             : modified_immediate(cpu, first, second);
    }
    if (op1 == 0b01 && bits(first, 10, 9) == 0b00) {
        return bit(first, 6) ? load_store_dual(cpu, first, second)
                             : load_store_multiple(cpu, first, second);
    }
    if (op1 == 0b01 && bits(first, 10, 9) == 0b01) {
        return shifted_register(cpu, first, second);
    }
    if (op1 == 0b11) {
        if (bits(first, 10, 9) == 0b00) {
            return load_store_single(cpu, first, second);
        }
        if (bits(first, 10, 8) == 0b010) {
            return register_group(cpu, first, second);
        }
        const unsigned group = bits(first, 10, 7);
        if (group == 0b0110 || group == 0b0111) {
            return multiply(cpu, first, second);
        }
    }
    // op1 = 01 with hw1[10] set is the coprocessor space, which on an M4F is
    // the FPU; op1 = 11 with hw1[10] set is the same. Neither is in this slice.
    return StepResult::Unimplemented;
}

}  // namespace cortexm0
