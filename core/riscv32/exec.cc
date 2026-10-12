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

/// The M extension: one funct7, eight funct3 values, and four defined edges.
///
/// ## The arithmetic is the easy half
///
/// **RISC-V defines division by zero and signed overflow rather than leaving
/// them undefined**, which is the opposite of the host language. So the two
/// cases C++ calls undefined behaviour are answered *before* any divide
/// happens, not after: `INT_MIN / -1` overflows signed division and is UB in
/// C++, and on some hosts it raises rather than returning anything at all.
///
///     div  x / 0            -> -1            divu x / 0 -> 2^32 - 1
///     rem  x / 0            -> x             remu x / 0 -> x
///     div  INT_MIN / -1     -> INT_MIN       rem  INT_MIN / -1 -> 0
///
/// A model that inherited the host's behaviour would be right about six of
/// eight instructions and crash on the seventh.
///
/// ## And the high halves are where the easy defect is
///
/// `mulhsu` is signed times **unsigned** and is the one every implementation
/// gets wrong first, because it is the only place the two operands are
/// extended differently. Each product is formed in 64 bits where it fits
/// exactly, then the high word is taken with an *unsigned* shift -- right
/// shift of a negative signed value was implementation-defined until C++20,
/// the same reason `sign_extend` and `shift_right_arithmetic` above are
/// spelled out.
uint32_t multiply_or_divide(unsigned funct3, uint32_t a, uint32_t b) {
    const int32_t sa = static_cast<int32_t>(a);
    const int32_t sb = static_cast<int32_t>(b);
    //: The bit pattern the two operands multiply as. Casting a sign-extended
    //: int64 to uint64 is modular and well-defined, and the true product of
    //: two 32-bit values always fits in 64 bits -- so the low 64 bits the
    //: unsigned multiply produces *are* the exact product.
    const uint64_t wide_a = static_cast<uint64_t>(static_cast<int64_t>(sa));
    const uint64_t wide_b = static_cast<uint64_t>(static_cast<int64_t>(sb));

    switch (funct3) {
    case 0x0u:  // MUL -- the low word, and signedness cannot affect it
        return static_cast<uint32_t>(static_cast<uint64_t>(a) * b);
    case 0x1u:  // MULH   signed x signed
        return static_cast<uint32_t>((wide_a * wide_b) >> 32);
    case 0x2u:  // MULHSU signed x unsigned
        return static_cast<uint32_t>((wide_a * static_cast<uint64_t>(b)) >> 32);
    case 0x3u:  // MULHU  unsigned x unsigned
        return static_cast<uint32_t>(
            (static_cast<uint64_t>(a) * static_cast<uint64_t>(b)) >> 32);

    case 0x4u:  // DIV
        if (b == 0) {
            return 0xFFFFFFFFu;
        }
        if (a == 0x80000000u && b == 0xFFFFFFFFu) {
            return a;  // the quotient is not representable; the dividend is it
        }
        return static_cast<uint32_t>(sa / sb);
    case 0x5u:  // DIVU
        return b == 0 ? 0xFFFFFFFFu : a / b;

    case 0x6u:  // REM
        if (b == 0) {
            return a;
        }
        if (a == 0x80000000u && b == 0xFFFFFFFFu) {
            return 0;
        }
        return static_cast<uint32_t>(sa % sb);
    default:    // REMU
        return b == 0 ? a : a % b;
    }
}

// --- Zbb and Zbkb ------------------------------------------------------------
//
// The RP2350's last two groups (OH-208). Each operation below is the Sail on
// its instruction page in the ratified unprivileged ISA, 20240411, chapter 28
// ("B" Extension for Bit Manipulation, Version 1.0.0), whose `Zbb` and `Zbkb`
// sections list which instruction belongs to which group; Zbkb is also
// chapter 32's (Scalar Cryptography, Version 1.0.1).
//
// **Loops and masks, never compiler builtins.** `__builtin_clz` is undefined
// at zero under GCC and absent under MSVC, this file is built by three
// compilers, and rvcpp -- the oracle these are held to in lockstep -- uses
// exactly those builtins. A model and its oracle sharing one implementation
// would agree about its bugs.

/// `clz`: 32 for zero, which the spec defines and the builtin does not.
uint32_t count_leading_zeros(uint32_t value) {
    uint32_t count = 0;
    for (uint32_t bit = 0x80000000u; bit != 0 && (value & bit) == 0; bit >>= 1) {
        ++count;
    }
    return count;
}

/// `ctz`: 32 for zero, likewise.
uint32_t count_trailing_zeros(uint32_t value) {
    uint32_t count = 0;
    for (uint32_t bit = 1u; bit != 0 && (value & bit) == 0; bit <<= 1) {
        ++count;
    }
    return count;
}

/// `cpop`: each pass clears the lowest set bit.
uint32_t count_ones(uint32_t value) {
    uint32_t count = 0;
    for (; value != 0; value &= value - 1u) {
        ++count;
    }
    return count;
}

/// `ror` and `rori`, and `rol` as a rotate right by the complement. An amount
/// of zero is answered first because `value << 32` is undefined in C++.
uint32_t rotate_right(uint32_t value, unsigned amount) {
    amount &= 0x1Fu;
    return amount == 0 ? value : (value >> amount) | (value << (32u - amount));
}

/// `orc.b`: each byte becomes 0xFF if any bit of it is set, else stays 0.
uint32_t or_combine_bytes(uint32_t value) {
    uint32_t out = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) {
        if ((value >> shift) & 0xFFu) {
            out |= 0xFFu << shift;
        }
    }
    return out;
}

/// `rev8` on RV32: byte 0 swaps with byte 3 and byte 1 with byte 2.
uint32_t reverse_bytes(uint32_t value) {
    return (value >> 24) | ((value >> 8) & 0x0000FF00u) |
           ((value << 8) & 0x00FF0000u) | (value << 24);
}

/// `brev8` (chapter 28 spells it `rev.b`): bit 7 - i of each byte to bit i.
uint32_t reverse_bits_in_bytes(uint32_t value) {
    uint32_t out = 0;
    for (unsigned bit = 0; bit < 32; ++bit) {
        if (value & (1u << bit)) {
            out |= 1u << ((bit & ~7u) | (7u - (bit & 7u)));
        }
    }
    return out;
}

/// `zip`, RV32 only: the spec's `rd[2i] = rs1[i]`, `rd[2i+1] = rs1[i+16]`.
uint32_t zip(uint32_t value) {
    uint32_t out = 0;
    for (unsigned i = 0; i < 16; ++i) {
        out |= ((value >> i) & 1u) << (2u * i);
        out |= ((value >> (i + 16u)) & 1u) << (2u * i + 1u);
    }
    return out;
}

/// `unzip`, RV32 only, zip's inverse: `rd[i] = rs1[2i]`,
/// `rd[i+16] = rs1[2i+1]`.
uint32_t unzip(uint32_t value) {
    uint32_t out = 0;
    for (unsigned i = 0; i < 16; ++i) {
        out |= ((value >> (2u * i)) & 1u) << i;
        out |= ((value >> (2u * i + 1u)) & 1u) << (i + 16u);
    }
    return out;
}

/// The seven instructions Zbb and Zbkb share -- `andn`, `orn`, `xnor`,
/// `rol`, `ror`, `rori`, `rev8` -- are legal on a part with either.
bool has_zbb_or_zbkb(const Cpu& cpu) {
    return cpu.has(kExtZbb) || cpu.has(kExtZbkb);
}

// --- the compressed instructions -----------------------------------------
//
// ## Expanded, not re-implemented
//
// Every RVC encoding is defined by the specification as *exactly* one base
// instruction -- `c.add rd, rs2` is `add rd, rd, rs2` and not merely like it.
// So this turns a halfword into that 32-bit encoding and hands it to
// `execute`, and the arithmetic, the register writes, the alignment checks and
// the fault reporting are the ones already in lockstep with rvcpp.
//
// The alternative is a second switch executing `c.add` beside `add`, which is
// the two-things-that-must-agree arrangement `core/avr/cpu.h` refuses for the
// AVR register file, applied to thirty instructions instead of one array.
//
// ## Where this core and its oracle must disagree, by name
//
// The eight `C.F*` encodings below are Zcf and Zcd -- compressed float loads
// and stores. On RV32 with no F and no D they are **illegal**, and no part in
// this repository has an FPU. rvcpp answers otherwise, and
// `docs/architectures.md` 2.1b measures how at commit `8af9929`: its RVC
// decoder has no XLEN gate, so `C_LD`, `C_SD`, `C_LDSP` and `C_SDSP` execute
// as RV64 integer loads and stores whenever the register is **even**, and
// reject on odd registers only because the generated masks carry a spurious
// `rd[0] == 0` constraint. Half the register space rejects by coincidence.
//
// So lockstep is not the authority here and `tests/riscv32/test_rvc.py` says
// so at those encodings specifically. Everywhere else it is.

/// Bits `hi`..`lo` of a halfword, right-aligned. Named because every immediate
/// below is a permutation of these and one transposed pair decodes as a
/// different offset -- which does not fault, it jumps somewhere plausible.
uint32_t bits(uint16_t c, unsigned hi, unsigned lo) {
    return (static_cast<uint32_t>(c) >> lo) & ((1u << (hi - lo + 1)) - 1u);
}

/// A compressed register field, which names x8..x15 in three bits.
unsigned creg(uint32_t three) { return static_cast<unsigned>(three) + 8u; }

uint32_t r_type(uint32_t op, unsigned rd, uint32_t funct3, unsigned rs1,
                unsigned rs2, uint32_t funct7) {
    return op | (rd << 7) | (funct3 << 12) | (rs1 << 15) | (rs2 << 20) |
           (funct7 << 25);
}

uint32_t i_type(uint32_t op, unsigned rd, uint32_t funct3, unsigned rs1,
                uint32_t imm) {
    return op | (rd << 7) | (funct3 << 12) | (rs1 << 15) | ((imm & 0xFFFu) << 20);
}

uint32_t s_type(uint32_t op, uint32_t funct3, unsigned rs1, unsigned rs2,
                uint32_t imm) {
    return op | ((imm & 0x1Fu) << 7) | (funct3 << 12) | (rs1 << 15) |
           (rs2 << 20) | (((imm >> 5) & 0x7Fu) << 25);
}

uint32_t b_type(uint32_t op, uint32_t funct3, unsigned rs1, unsigned rs2,
                uint32_t imm) {
    return op | (((imm >> 11) & 0x1u) << 7) | (((imm >> 1) & 0xFu) << 8) |
           (funct3 << 12) | (rs1 << 15) | (rs2 << 20) |
           (((imm >> 5) & 0x3Fu) << 25) | (((imm >> 12) & 0x1u) << 31);
}

uint32_t u_type(uint32_t op, unsigned rd, uint32_t imm) {
    return op | (rd << 7) | (imm & 0xFFFFF000u);
}

uint32_t j_type(uint32_t op, unsigned rd, uint32_t imm) {
    return op | (rd << 7) | (((imm >> 12) & 0xFFu) << 12) |
           (((imm >> 11) & 0x1u) << 20) | (((imm >> 1) & 0x3FFu) << 21) |
           (((imm >> 20) & 0x1u) << 31);
}

//: The base opcodes an expansion targets.
constexpr uint32_t kOpImm = 0x13u;
constexpr uint32_t kOp = 0x33u;
constexpr uint32_t kLoad = 0x03u;
constexpr uint32_t kStore = 0x23u;
constexpr uint32_t kBranch = 0x63u;
constexpr uint32_t kJal = 0x6Fu;
constexpr uint32_t kJalr = 0x67u;
constexpr uint32_t kLui = 0x37u;
constexpr uint32_t kSystem = 0x73u;

/// What a halfword turned out to be.
enum class Expansion {
    Ok,       //< `out` holds the 32-bit instruction it means.
    Illegal,  //< Reserved, or an encoding this part must refuse.
};

/// The RVC branch offset: `c[12]` and `c[6:2]` scattered across imm[8:1].
uint32_t imm_cb(uint16_t c) {
    const uint32_t value = (bits(c, 12, 12) << 8) | (bits(c, 6, 5) << 6) |
                           (bits(c, 2, 2) << 5) | (bits(c, 11, 10) << 3) |
                           (bits(c, 4, 3) << 1);
    return sign_extend(value, 9);
}

/// The RVC jump offset, which is the same field in a different permutation.
uint32_t imm_cj(uint16_t c) {
    const uint32_t value = (bits(c, 12, 12) << 11) | (bits(c, 8, 8) << 10) |
                           (bits(c, 10, 9) << 8) | (bits(c, 6, 6) << 7) |
                           (bits(c, 7, 7) << 6) | (bits(c, 2, 2) << 5) |
                           (bits(c, 11, 11) << 4) | (bits(c, 5, 3) << 1);
    return sign_extend(value, 12);
}

/// `c[12]` and `c[6:2]` as a signed six-bit immediate -- ADDI, LI, ANDI, LUI.
uint32_t imm_ci(uint16_t c) {
    return sign_extend((bits(c, 12, 12) << 5) | bits(c, 6, 2), 6);
}

Expansion expand_quadrant0(uint32_t extensions, uint16_t c, uint32_t& out) {
    const unsigned rd = creg(bits(c, 4, 2));
    const unsigned rs1 = creg(bits(c, 9, 7));

    switch (bits(c, 15, 13)) {
    case 0x0u: {  // C.ADDI4SPN -> addi rd', x2, nzuimm
        const uint32_t imm = (bits(c, 10, 7) << 6) | (bits(c, 12, 11) << 4) |
                             (bits(c, 5, 5) << 3) | (bits(c, 6, 6) << 2);
        // The all-zero immediate is the reserved encoding, and it is also the
        // all-zero halfword that `step` already answers before reaching here.
        if (imm == 0) {
            return Expansion::Illegal;
        }
        out = i_type(kOpImm, rd, 0x0u, 2, imm);
        return Expansion::Ok;
    }
    case 0x2u: {  // C.LW -> lw rd', offset(rs1')
        const uint32_t imm = (bits(c, 5, 5) << 6) | (bits(c, 12, 10) << 3) |
                             (bits(c, 6, 6) << 2);
        out = i_type(kLoad, rd, 0x2u, rs1, imm);
        return Expansion::Ok;
    }
    case 0x6u: {  // C.SW -> sw rs2', offset(rs1')
        const uint32_t imm = (bits(c, 5, 5) << 6) | (bits(c, 12, 10) << 3) |
                             (bits(c, 6, 6) << 2);
        out = s_type(kStore, 0x2u, rs1, rd, imm);
        return Expansion::Ok;
    }
    case 0x4u: {
        // The slot base RVC reserves and Zcb fills: byte and halfword loads
        // and stores, with a two-bit offset whose bits sit SWAPPED -- bit 6
        // is uimm[0] and bit 5 is uimm[1], the same low-bits-near-6 shape
        // C.LW uses for uimm[2]. Zc spec v1.0.4, tables 4-8.
        if (!(extensions & kExtZcb)) {
            return Expansion::Illegal;
        }
        switch (bits(c, 12, 10)) {
        case 0x0u: {  // C.LBU -> lbu rd', uimm(rs1')
            const uint32_t imm = (bits(c, 5, 5) << 1) | bits(c, 6, 6);
            out = i_type(kLoad, rd, 0x4u, rs1, imm);
            return Expansion::Ok;
        }
        case 0x1u: {  // bit 6 tells C.LH (signed) from C.LHU
            const uint32_t imm = bits(c, 5, 5) << 1;
            out = i_type(kLoad, rd, bits(c, 6, 6) ? 0x1u : 0x5u, rs1, imm);
            return Expansion::Ok;
        }
        case 0x2u: {  // C.SB -> sb rs2', uimm(rs1')
            const uint32_t imm = (bits(c, 5, 5) << 1) | bits(c, 6, 6);
            out = s_type(kStore, 0x0u, rs1, rd, imm);
            return Expansion::Ok;
        }
        case 0x3u:  // C.SH; bit 6 set is reserved
            if (bits(c, 6, 6) != 0) {
                return Expansion::Illegal;
            }
            out = s_type(kStore, 0x1u, rs1, rd, bits(c, 5, 5) << 1);
            return Expansion::Ok;
        default:  // 100..111 stay reserved even with Zcb
            return Expansion::Illegal;
        }
    }
    default:
        // 001 C.FLD, 011 C.FLW, 101 C.FSD, 111 C.FSW -- Zcd and Zcf, needing D
        // and F. No part here has an FPU.
        return Expansion::Illegal;
    }
}

Expansion expand_quadrant1(uint32_t extensions, uint16_t c, uint32_t& out) {
    const unsigned rd = static_cast<unsigned>(bits(c, 11, 7));

    switch (bits(c, 15, 13)) {
    case 0x0u:  // C.NOP / C.ADDI -> addi rd, rd, imm
        // rd == 0 is C.NOP when the immediate is zero and a HINT when it is
        // not; both expand to a write of x0, which discards. No special case
        // is needed and inventing one would be inventing a behaviour.
        out = i_type(kOpImm, rd, 0x0u, rd, imm_ci(c));
        return Expansion::Ok;

    case 0x1u:  // C.JAL -> jal x1, offset  (RV32 only; RV64 makes this C.ADDIW)
        out = j_type(kJal, 1, imm_cj(c));
        return Expansion::Ok;

    case 0x2u:  // C.LI -> addi rd, x0, imm
        out = i_type(kOpImm, rd, 0x0u, 0, imm_ci(c));
        return Expansion::Ok;

    case 0x3u: {
        if (rd == 2) {  // C.ADDI16SP -> addi x2, x2, nzimm
            const uint32_t imm = sign_extend(
                (bits(c, 12, 12) << 9) | (bits(c, 4, 3) << 7) |
                    (bits(c, 5, 5) << 6) | (bits(c, 2, 2) << 5) |
                    (bits(c, 6, 6) << 4),
                10);
            if (imm == 0) {
                return Expansion::Illegal;
            }
            out = i_type(kOpImm, 2, 0x0u, 2, imm);
            return Expansion::Ok;
        }
        // C.LUI -> lui rd, nzimm. The immediate lands in bits 17:12 of the
        // result, which is `imm_ci` shifted up by twelve.
        const uint32_t imm = imm_ci(c) << 12;
        if (imm == 0) {
            return Expansion::Illegal;
        }
        out = u_type(kLui, rd, imm);
        return Expansion::Ok;
    }

    case 0x4u: {
        const unsigned rsd = creg(bits(c, 9, 7));
        const uint32_t shamt = (bits(c, 12, 12) << 5) | bits(c, 6, 2);
        switch (bits(c, 11, 10)) {
        case 0x0u:  // C.SRLI
        case 0x1u:  // C.SRAI
            // **Bit 12 set is RV64's six-bit shift amount and is reserved on
            // RV32, and this does not check for it.** An explicit refusal here
            // was written first and then deleted, because mutation showed no
            // input could tell the difference: a shift amount of 32 or more
            // puts a one in `imm[5]`, which is `funct7`'s low bit, and the
            // 32-bit shift already refuses any nonzero funct7 for exactly this
            // reason. Two checks of one fact, and the second one is the one
            // every 32-bit shift is checked by.
            //
            // `test_a_compressed_shift_of_thirty_two_or_more_is_refused` pins
            // the behaviour, so moving the enforcement does not lose it.
            out = i_type(kOpImm, rsd, 0x5u, rsd,
                         shamt | (bits(c, 11, 10) == 0x1u ? (0x20u << 5) : 0u));
            return Expansion::Ok;
        case 0x2u:  // C.ANDI -> andi rd', rd', imm
            out = i_type(kOpImm, rsd, 0x7u, rsd, imm_ci(c));
            return Expansion::Ok;
        default: {  // register-register
            const unsigned rs2 = creg(bits(c, 4, 2));
            if (bits(c, 12, 12) != 0) {
                // C.SUBW and C.ADDW (funct2 00 and 01) are RV64. Base RV32
                // reserved the rest; Zcb takes funct2 10 for C.MUL and 11
                // for its unary group.
                switch (bits(c, 6, 5)) {
                case 0x2u:  // C.MUL -> mul rd', rd', rs2'
                    // Zcb and M together: the expansion inherits the 32-bit
                    // mul's own M gate, so a part with Zcb and no M still
                    // refuses -- which is the spec's rule, not a shortcut.
                    if (!(extensions & kExtZcb)) {
                        return Expansion::Illegal;
                    }
                    out = r_type(kOp, rsd, 0x0u, rsd, rs2, 0x01u);
                    return Expansion::Ok;
                case 0x3u:
                    if (!(extensions & kExtZcb)) {
                        return Expansion::Illegal;
                    }
                    switch (bits(c, 4, 2)) {
                    case 0x0u:  // C.ZEXT.B -> andi rd', rd', 0xff
                        out = i_type(kOpImm, rsd, 0x7u, rsd, 0xFFu);
                        return Expansion::Ok;
                    case 0x5u:  // C.NOT -> xori rd', rd', -1
                        out = i_type(kOpImm, rsd, 0x4u, rsd, 0xFFFu);
                        return Expansion::Ok;
                    case 0x1u:  // C.SEXT.B -> sext.b rd', rd'
                    case 0x2u:  // C.ZEXT.H -> zext.h rd', rd'
                    case 0x3u:  // C.SEXT.H -> sext.h rd', rd'
                        // "Zbb is also required" -- each one's page in the
                        // Zc chapter (unprivileged ISA 20240411, ch. 27).
                        // Checked here and not left to the expansion's own
                        // gate, because C.ZEXT.H expands to `pack rd', rd',
                        // x0`, which Zbkb alone would open: a Zcb part with
                        // Zbkb and no Zbb must still refuse it. Of the parts
                        // here the C5 refuses all three (Zcb, no Zbb) and
                        // the RP2350 runs them (both).
                        if (!(extensions & kExtZbb)) {
                            return Expansion::Illegal;
                        }
                        out = bits(c, 4, 2) == 0x2u
                                  ? r_type(kOp, rsd, 0x4u, rsd, 0, 0x04u)
                                  : i_type(kOpImm, rsd, 0x1u, rsd,
                                           bits(c, 4, 2) == 0x1u ? 0x604u
                                                                 : 0x605u);
                        return Expansion::Ok;
                    default:
                        // 100 C.ZEXT.W is RV64-only; 110 and 111 are
                        // reserved. One answer covers all three.
                        return Expansion::Illegal;
                    }
                default:
                    return Expansion::Illegal;
                }
            }
            switch (bits(c, 6, 5)) {
            case 0x0u:  // C.SUB
                out = r_type(kOp, rsd, 0x0u, rsd, rs2, 0x20u);
                return Expansion::Ok;
            case 0x1u:  // C.XOR
                out = r_type(kOp, rsd, 0x4u, rsd, rs2, 0x0u);
                return Expansion::Ok;
            case 0x2u:  // C.OR
                out = r_type(kOp, rsd, 0x6u, rsd, rs2, 0x0u);
                return Expansion::Ok;
            default:  // C.AND
                out = r_type(kOp, rsd, 0x7u, rsd, rs2, 0x0u);
                return Expansion::Ok;
            }
        }
        }
    }

    case 0x5u:  // C.J -> jal x0, offset
        out = j_type(kJal, 0, imm_cj(c));
        return Expansion::Ok;

    case 0x6u:  // C.BEQZ -> beq rs1', x0, offset
        out = b_type(kBranch, 0x0u, creg(bits(c, 9, 7)), 0, imm_cb(c));
        return Expansion::Ok;

    default:  // C.BNEZ -> bne rs1', x0, offset
        out = b_type(kBranch, 0x1u, creg(bits(c, 9, 7)), 0, imm_cb(c));
        return Expansion::Ok;
    }
}

Expansion expand_quadrant2(uint16_t c, uint32_t& out) {
    const unsigned rd = static_cast<unsigned>(bits(c, 11, 7));
    const unsigned rs2 = static_cast<unsigned>(bits(c, 6, 2));

    switch (bits(c, 15, 13)) {
    case 0x0u:  // C.SLLI -> slli rd, rd, shamt
        // The whole six-bit amount, bit 12 included. An amount of 32 or more
        // lands in funct7 and is refused by the 32-bit shift; see C.SRLI above
        // for why that is one check rather than two.
        out = i_type(kOpImm, rd, 0x1u, rd,
                     (bits(c, 12, 12) << 5) | bits(c, 6, 2));
        return Expansion::Ok;

    case 0x2u: {  // C.LWSP -> lw rd, offset(x2)
        // rd == 0 is reserved rather than a hint: this one writes a loaded
        // value, and discarding it would make a reserved encoding look like a
        // working load of nothing.
        if (rd == 0) {
            return Expansion::Illegal;
        }
        const uint32_t imm = (bits(c, 3, 2) << 6) | (bits(c, 12, 12) << 5) |
                             (bits(c, 6, 4) << 2);
        out = i_type(kLoad, rd, 0x2u, 2, imm);
        return Expansion::Ok;
    }

    case 0x4u:
        if (bits(c, 12, 12) == 0) {
            if (rs2 == 0) {  // C.JR -> jalr x0, 0(rs1)
                if (rd == 0) {
                    return Expansion::Illegal;  // reserved
                }
                out = i_type(kJalr, 0, 0x0u, rd, 0);
                return Expansion::Ok;
            }
            // C.MV -> add rd, x0, rs2
            out = r_type(kOp, rd, 0x0u, 0, rs2, 0x0u);
            return Expansion::Ok;
        }
        if (rs2 == 0) {
            if (rd == 0) {  // C.EBREAK
                // Expands to `ebreak`, which `execute` answers Unimplemented
                // for -- this core has no traps. That is the same answer the
                // 32-bit encoding gets, which is the point of expanding.
                out = i_type(kSystem, 0, 0x0u, 0, 1);
                return Expansion::Ok;
            }
            // C.JALR -> jalr x1, 0(rs1)
            out = i_type(kJalr, 1, 0x0u, rd, 0);
            return Expansion::Ok;
        }
        // C.ADD -> add rd, rd, rs2
        out = r_type(kOp, rd, 0x0u, rd, rs2, 0x0u);
        return Expansion::Ok;

    case 0x6u: {  // C.SWSP -> sw rs2, offset(x2)
        const uint32_t imm = (bits(c, 8, 7) << 6) | (bits(c, 12, 9) << 2);
        out = s_type(kStore, 0x2u, 2, rs2, imm);
        return Expansion::Ok;
    }

    default:
        // 001 C.FLDSP, 011 C.FLWSP, 101 C.FSDSP, 111 C.FSWSP -- Zcd and Zcf.
        // These are the four encodings rvcpp gets wrong; see the note above.
        return Expansion::Illegal;
    }
}

/// The 32-bit instruction a compressed halfword means, or Illegal.
Expansion expand_compressed(uint32_t extensions, uint16_t c, uint32_t& out) {
    switch (c & 0x3u) {
    case 0x0u:
        return expand_quadrant0(extensions, c, out);
    case 0x1u:
        return expand_quadrant1(extensions, c, out);
    default:
        return expand_quadrant2(c, out);
    }
}

/// Declared here and defined below `step`, so that reading this file top to
/// bottom is fetch, then decode, then execute.
StepResult execute(Cpu& cpu, uint32_t pc, uint32_t instr, uint32_t width);

/// Zcmp and Zcmt, which do not expand: a push writes several words and
/// several registers, and a table jump reads its target through JVT. Defined
/// beside `execute` below.
StepResult execute_zc(Cpu& cpu, uint32_t pc, uint16_t c);

/// Fetch, decode and execute the instruction at PC: everything `step` does
/// except age the machine, which `step` does only on what this returns.
StepResult fetch_and_execute(Cpu& cpu);

}  // namespace

StepResult step(Cpu& cpu) {
    const StepResult result = fetch_and_execute(cpu);
    // Only a retired instruction ages the machine. On anything else the
    // processor is untouched, PC included, so a program stopped by one must
    // not go on accruing virtual time -- a caller stepping a halted core in
    // a loop would otherwise watch its timer advance. `core/cortexm0` makes
    // the same cut in its abi.cc; here it is in the core, so a C++ caller of
    // `step` gets the machine the ABI does.
    if (result == StepResult::Ok) {
        cpu.note_executed();
    }
    return result;
}

namespace {

StepResult fetch_and_execute(Cpu& cpu) {
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
        // A part told it has no C must refuse the encoding; one that has it
        // executes. `refuse` keeps those two answers from being transposed,
        // and this is the branch the whole `Extension` mask exists for after
        // the atomics.
        if (!cpu.has(kExtC)) {
            return StepResult::Illegal;
        }
        // Quadrant 2's funct3=101 -- the c.fsdsp slot, dead on every
        // FPU-less part -- is where Zcmp and Zcmt live, and they are the two
        // compressed groups that do not expand to one base instruction. A
        // part with neither falls through to the expansion, whose answer for
        // that slot is the Illegal it always was.
        if ((low & 0x3u) == 0x2u && bits(low, 15, 13) == 0x5u &&
            (cpu.has(kExtZcmp) || cpu.has(kExtZcmt))) {
            return execute_zc(cpu, pc, low);
        }
        uint32_t expanded = 0;
        if (expand_compressed(cpu.extensions(), low, expanded) != Expansion::Ok) {
            // Reserved on RV32, or a compressed float access on a part with no
            // FPU. Illegal rather than Unimplemented: nothing here is waiting
            // to be written, the architecture refuses it.
            return StepResult::Illegal;
        }
        return execute(cpu, pc, expanded, 2);
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

    return execute(cpu, pc, instr, 4);
}

}  // namespace

/// One already-fetched 32-bit instruction, at `pc`, `width` bytes wide.
///
/// **`width` is a parameter and not the constant 4 because a compressed
/// instruction executes through here too.** Every RVC encoding is defined by
/// the specification as expanding to exactly one base instruction, so
/// `expand_compressed` turns the halfword into the 32-bit encoding it means
/// and this runs it -- which is why `c.add` cannot drift away from `add`.
/// They are the same code.
///
/// What the expansion cannot carry is how far PC moves: `c.jal` links to
/// `pc + 2` and `jal` links to `pc + 4`, and the encodings are otherwise
/// identical. So the width comes in beside the instruction rather than being
/// recovered from it.
namespace {

StepResult execute(Cpu& cpu, uint32_t pc, uint32_t instr, uint32_t width) {
    const uint32_t next = pc + width;
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
        case 0x1u: {  // SLLI, and Zbs's three single-bit immediates
            // On RV32 the shift amount is five bits and bit 25 must be zero.
            // A one there is the RV64 encoding of a six-bit shift, and an
            // RV32 part raises illegal-instruction rather than shifting by a
            // masked amount. This is the same class of hole rvcpp has in its
            // compressed decoder (docs/architectures.md 2.1b): an RV64 meaning
            // silently accepted on a 32-bit part.
            //
            // **Zbs shares this funct3 and does not weaken that.** Its three
            // funct7 values here are 0b0010100, 0b0100100 and 0b0110100, and
            // every one of them has bit 25 clear -- so opening them leaves the
            // RV64 six-bit shift exactly as illegal as it was. That is why
            // this is a switch over named funct7 values and not a test for
            // "nonzero", which would have opened the case this paragraph
            // exists to close.
            //
            // **Zbb's unaries and Zbkb's zip are here too, and they are
            // where the rs2 field stops being a shift amount.** Under funct7
            // 0b0110000 it names the operation -- the 12-bit immediates
            // 0x600 clz, 0x601 ctz, 0x602 cpop, 0x604 sext.b, 0x605 sext.h
            // -- and under 0b0000100 only 0b01111 means anything (0x08F,
            // zip). So each is matched on its whole immediate, and every
            // other value of the field stays illegal.
            const uint32_t seven = funct7_of(instr);
            const uint32_t bit = 1u << (rs2 & 0x1Fu);
            if (seven == 0x00u) {
                result = a << (rs2 & 0x1Fu);                            // SLLI
            } else if (seven == 0x14u || seven == 0x24u || seven == 0x34u) {
                if (!cpu.has(kExtZbs)) {
                    return StepResult::Illegal;
                }
                result = seven == 0x14u ? (a | bit)                     // BSETI
                       : seven == 0x24u ? (a & ~bit)                    // BCLRI
                       :                  (a ^ bit);                    // BINVI
            } else if (seven == 0x30u) {
                if (!cpu.has(kExtZbb)) {
                    return StepResult::Illegal;
                }
                switch (rs2) {
                case 0x0u: result = count_leading_zeros(a); break;      // CLZ
                case 0x1u: result = count_trailing_zeros(a); break;     // CTZ
                case 0x2u: result = count_ones(a); break;               // CPOP
                case 0x4u: result = sign_extend(a, 8); break;           // SEXT.B
                case 0x5u: result = sign_extend(a, 16); break;          // SEXT.H
                default: return StepResult::Illegal;
                }
            } else if (seven == 0x04u && rs2 == 0x0Fu) {
                // ZIP, rs2 = 0b01111. The 20240411 release's figures in
                // chapters 28 and 32 drew this field as 0x1e (unzip's as
                // 0x1f), and riscv-isa-manual 698e64ae7 (2024-09-09, "Fix
                // descriptions/encodings of zip/unzip instructions
                // (#1635)") put both back to the ratified 0xf. sail-riscv's
                // `model/extensions/K/zbkb_insts.sail:66-67` (at 549e723),
                // riscv-opcodes' `rv32_zbkb`, rvcpp's `RVOPC_ZIP_BITS`
                // (Hazard3's author's own table) and GNU as 2.43 all say
                // 0b01111, and `tests/riscv32/test_zbb_zbkb.py` holds it.
                if (!cpu.has(kExtZbkb)) {
                    return StepResult::Illegal;
                }
                result = zip(a);
            } else {
                return StepResult::Illegal;
            }
            break;
        }
        case 0x5u: {  // SRLI, SRAI, Zbs's BEXTI, and five Zbb/Zbkb forms
            const uint32_t seven = funct7_of(instr);
            if (seven == 0x00u) {
                result = a >> (rs2 & 0x1Fu);                            // SRLI
            } else if (seven == 0x20u) {
                result = shift_right_arithmetic(a, rs2 & 0x1Fu);        // SRAI
            } else if (seven == 0x24u) {
                // Only BEXTI lives under this funct3. The other two Zbs
                // funct7 values belong to funct3 001, so a gate keyed on the
                // extension alone -- without the funct3 -- would execute
                // encodings Zbs does not define.
                if (!cpu.has(kExtZbs)) {
                    return StepResult::Illegal;
                }
                result = (a >> (rs2 & 0x1Fu)) & 1u;                     // BEXTI
            } else if (seven == 0x30u) {
                // RORI, in both groups. funct7 exactly 0b0110000: a one in
                // bit 25 is RV64's sixth shift-amount bit, and stays illegal
                // here for the reason SLLI's does.
                if (!has_zbb_or_zbkb(cpu)) {
                    return StepResult::Illegal;
                }
                result = rotate_right(a, rs2 & 0x1Fu);                  // RORI
            } else if (seven == 0x14u && rs2 == 0x07u) {
                // ORC.B, 0x287 -- Zbb only. funct7 0b0010100 is BSETI's, but
                // BSETI is funct3 001; here only this one immediate exists.
                if (!cpu.has(kExtZbb)) {
                    return StepResult::Illegal;
                }
                result = or_combine_bytes(a);                           // ORC.B
            } else if (seven == 0x34u && rs2 == 0x18u) {
                // REV8, 0x698 -- RV32's encoding (RV64's is 0x6b8), in both
                // groups.
                if (!has_zbb_or_zbkb(cpu)) {
                    return StepResult::Illegal;
                }
                result = reverse_bytes(a);                              // REV8
            } else if (seven == 0x34u && rs2 == 0x07u) {
                // BREV8, 0x687 -- Zbkb only.
                if (!cpu.has(kExtZbkb)) {
                    return StepResult::Illegal;
                }
                result = reverse_bits_in_bytes(a);                      // BREV8
            } else if (seven == 0x04u && rs2 == 0x0Fu) {
                // UNZIP, 0x08F -- Zbkb, RV32 only; sail-riscv's
                // `zbkb_insts.sail:89-90`. See ZIP above for the 20240411
                // figure that drew this field as 0x1f, since corrected.
                if (!cpu.has(kExtZbkb)) {
                    return StepResult::Illegal;
                }
                result = unzip(a);                                      // UNZIP
            } else {
                return StepResult::Illegal;
            }
            break;
        }
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
            //
            // `Illegal` and not `refuse` now that all eight are written: a
            // part told it has no M must trap here, and there is no longer a
            // third answer where the extension is on and the encoding is
            // unwritten. All eight funct3 values are covered, so nothing falls
            // through.
            if (!cpu.has(kExtM)) {
                return StepResult::Illegal;
            }
            cpu.set_reg(rd, multiply_or_divide(funct3, cpu.reg(rs1), cpu.reg(rs2)));
            cpu.set_pc(next);
            return StepResult::Ok;
        }
        const uint32_t a = cpu.reg(rs1);
        const uint32_t b = cpu.reg(rs2);
        const unsigned amount = b & 0x1Fu;
        uint32_t result = 0;
        if (funct7 == 0x00u) {
            // SLT to x0 is also the Hazard3's h3.block (`slt x0, x0, x0`) and
            // h3.unblock (`slt x0, x0, x1`), Xh3power's hints, and they answer
            // Ok here where WFI answers Unimplemented. Ok is right for them. A
            // WFI may complete at any time -- "a legal implementation is to
            // simply implement the WFI instruction as a NOP" (privileged ISA,
            // "Wait for Interrupt"); Hazard3's doc says h3.block falls
            // through as a nop once an unblock has been received, which may
            // come "for some other platform-defined reason"
            // (custom_extensions.adoc:72-74); rvcpp runs both as slt; and
            // refusing them would need an RP2350-only branch on a base-ISA
            // hint every other part must run (OH-219).
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
            case 0x4u:                                                    // XNOR
            case 0x6u:                                                    // ORN
            case 0x7u:                                                    // ANDN
                // The logical-with-negate three, in both Zbb and Zbkb.
                if (!has_zbb_or_zbkb(cpu)) {
                    return StepResult::Illegal;
                }
                result = funct3 == 0x4u ? ~(a ^ b)
                       : funct3 == 0x6u ? (a | ~b)
                       :                  (a & ~b);
                break;
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x05u) {
            // MIN, MINU, MAX, MAXU -- Zbb only. funct3 001, 010 and 011
            // under this funct7 are Zbc's clmul, clmulr and clmulh, which the
            // RP2350's string does not name, so they are refused on every
            // part here. rvcpp executes them (rv_core.cpp:289), so lockstep
            // cannot see that refusal; test_zbb_zbkb.py asserts it instead.
            if (!cpu.has(kExtZbb)) {
                return StepResult::Illegal;
            }
            switch (funct3) {
            case 0x4u: result = less_than_signed(a, b) ? a : b; break;   // MIN
            case 0x5u: result = a < b ? a : b; break;                    // MINU
            case 0x6u: result = less_than_signed(a, b) ? b : a; break;   // MAX
            case 0x7u: result = a < b ? b : a; break;                    // MAXU
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x30u) {
            // ROL and ROR, in both groups; the other six funct3 values of
            // this funct7 name nothing on RV32.
            if (!has_zbb_or_zbkb(cpu)) {
                return StepResult::Illegal;
            }
            switch (funct3) {
            case 0x1u: result = rotate_right(a, (32u - amount) & 0x1Fu); break;  // ROL
            case 0x5u: result = rotate_right(a, amount); break;                  // ROR
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x04u) {
            if (funct3 == 0x4u) {
                // PACK, Zbkb -- and with rs2 = x0 the same word is Zbb's
                // ZEXT.H, whose RV32 encoding is defined as exactly that
                // (chapter 28, zext.h's page). So either group opens that
                // one encoding and only Zbkb opens the rest.
                if (!cpu.has(kExtZbkb) && !(rs2 == 0 && cpu.has(kExtZbb))) {
                    return StepResult::Illegal;
                }
                result = (a & 0xFFFFu) | (b << 16);                       // PACK
            } else if (funct3 == 0x7u) {
                if (!cpu.has(kExtZbkb)) {
                    return StepResult::Illegal;
                }
                result = (a & 0xFFu) | ((b & 0xFFu) << 8);                // PACKH
            } else {
                return StepResult::Illegal;
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
            // Zba. This comment used to say some were Zbs's and Zbkb's;
            // neither group has an encoding under funct7 0b0010000 (riscv-
            // opcodes' `rv_zbs`, `rv_zbkb`), so all five name nothing.
            default: return StepResult::Illegal;
            }
        } else if (funct7 == 0x14u || funct7 == 0x24u || funct7 == 0x34u) {
            // Zbs single-bit register forms. The funct7 alone does not decide
            // which: set, clear and invert share funct3 001 and are told apart
            // by funct7, while extract is funct3 101 and exists for 0x24 only.
            // So `0x24` with funct3 001 is BCLR and with 101 is BEXT, and the
            // other two funct7 values have no funct3 101 meaning at all -- a
            // gate that opened a whole funct7 would execute an encoding Zbs
            // does not define, and rvcpp, which implements Zbs, would agree.
            if (!cpu.has(kExtZbs)) {
                return StepResult::Illegal;
            }
            const uint32_t bit = 1u << amount;
            if (funct3 == 0x1u) {
                result = funct7 == 0x14u ? (a | bit)                     // BSET
                       : funct7 == 0x24u ? (a & ~bit)                    // BCLR
                       :                   (a ^ bit);                    // BINV
            } else if (funct3 == 0x5u && funct7 == 0x24u) {
                result = (a >> amount) & 1u;                             // BEXT
            } else {
                return StepResult::Illegal;
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

    case 0x73u: {
        // SYSTEM: ECALL, EBREAK, and the Zicsr encodings.
        //
        // Unimplemented rather than Illegal, and not faked. All of these
        // either enter a trap or touch a CSR, and this core has neither. A
        // model that answered a CSR read with a plausible value would be
        // inventing machine state, and ESP-IDF reads mstatus and mtvec within
        // its first hundred instructions -- so a wrong answer here is not a
        // small wrong answer.
        //
        // **Narrowed exactly once (OH-146): JVT, and only under Zcmt.** A
        // table jump's semantics ARE that register -- `cm.jt` reads its
        // target through it -- so a part with Zcmt cannot be modelled
        // without it, and unlike mstatus it holds nothing this core would
        // have to invent: software writes it, `execute_zc` reads it back.
        const uint32_t csr = instr >> 20;
        if (csr == 0x017u && cpu.has(kExtZcmt) && funct3 != 0x0u &&
            funct3 != 0x4u) {
            const uint32_t old = cpu.jvt();
            // Immediate forms carry a five-bit zimm where rs1 sits.
            const uint32_t operand = (funct3 & 0x4u) ? rs1 : cpu.reg(rs1);
            uint32_t value = old;
            switch (funct3 & 0x3u) {
            case 0x1u: value = operand; break;                      // CSRRW(I)
            case 0x2u: if (rs1 != 0) value = old | operand; break;  // CSRRS(I)
            case 0x3u: if (rs1 != 0) value = old & ~operand; break; // CSRRC(I)
            }
            // WARL: bits 5:0 are the table mode, mode zero is the only one
            // defined, so writes force it and reads answer it.
            cpu.set_jvt(value & ~0x3Fu);
            cpu.set_reg(rd, old);
            cpu.set_pc(next);
            return StepResult::Ok;
        }
        return StepResult::Unimplemented;
    }

    case 0x2Fu:
        // AMO: the A extension. **This is the case the whole `Extension` mask
        // exists for.** The ESP32-C3 is RV32IMC and must trap here; the C6 is
        // RV32IMAC and must execute. rvcpp executes both unconditionally, so
        // lockstep can never check this branch -- see OH-35.
        return refuse(cpu, kExtA);

    case 0x0Bu: {
        // custom-0: the Hazard3's Xh3bextm (OH-219). h3.bextm at funct3 000
        // and h3.bextmi at 100 shift rs1 right -- by rs2[4:0], or by the
        // five-bit field where rs2 sits -- and keep 1 to 8 low bits, the
        // width less one in bits 28:26 (Hazard3's
        // doc/sections/custom_extensions.adoc; RP2350 datasheet 3.8.6.4).
        // Bits 31:29 and 25 are RES0, and a word with any of them set, or
        // with another funct3, is illegal on the RP2350 as well: Hazard3's
        // decoder matches only these two shapes (hdl/rv_opcodes.vh:156-157)
        // and rvcpp traps the rest (rv_core.cpp:646-656). A part without
        // the bit refuses all of custom-0.
        if (!cpu.has(kExtXh3bextm) || (instr & 0xE2000000u) != 0 ||
            (funct3 != 0x0u && funct3 != 0x4u)) {
            return StepResult::Illegal;
        }
        // `nbits`, the doc's word, and not `width`, which is this function's
        // instruction width. The `& 0x1Fu` is the doc's `rs2[4:0]`, and no
        // test here can see it go: a C++ shift by 32 or more is undefined,
        // and x86 and ARM64 hosts mask the count to five bits themselves, so
        // test_xh3.py's amounts of 32 and up pass without it. It is kept
        // because the language does not promise what those hosts do.
        const unsigned nbits = ((instr >> 26) & 0x7u) + 1u;
        const unsigned amount = funct3 == 0x0u ? (cpu.reg(rs2) & 0x1Fu)  // H3.BEXTM
                                               : rs2;                     // H3.BEXTMI
        cpu.set_reg(rd, (cpu.reg(rs1) >> amount) & ((1u << nbits) - 1u));
        cpu.set_pc(next);
        return StepResult::Ok;
    }

    default:
        // Every undefined opcode, including the all-zeros and all-ones words a
        // program that has run off the end of memory reads.
        return StepResult::Illegal;
    }
}

/// The x-register a Zcmp list position names: 0 is ra, then s0..s11 --
/// s0 and s1 are x8 and x9 and the rest are x18..x27, the same split
/// `creg` exists for.
unsigned saved(unsigned index) {
    if (index == 0) {
        return 1;
    }
    if (index <= 2) {
        return 7u + index;
    }
    return 15u + index;
}

/// The Zcmp saved-register operand: 0..1 name s0..s1 (x8, x9) and 2..7 name
/// s2..s7 (x18..x23).
unsigned sreg(uint32_t three) {
    return three < 2 ? 8u + three : 16u + three;
}

StepResult execute_zc(Cpu& cpu, uint32_t pc, uint16_t c) {
    const uint32_t kind = bits(c, 12, 10);

    if (kind == 0x0u) {  // cm.jt / cm.jalt -- Zcmt
        if (!cpu.has(kExtZcmt)) {
            return StepResult::Illegal;
        }
        const uint32_t index = bits(c, 9, 2);
        const uint32_t slot = (cpu.jvt() & ~0x3Fu) + index * 4u;
        uint32_t target = 0;
        if (slot % 4u != 0 || !cpu.read_word(slot, target)) {
            cpu.note_data_fault(slot);
            return StepResult::MemoryFault;
        }
        // The table holds jump targets, so bit 0 clears the way jalr's does.
        target &= ~1u;
        if (!aligned(cpu, target)) {
            cpu.note_fetch_fault(target);
            return StepResult::MemoryFault;
        }
        if (index >= 32u) {  // cm.jalt links; cm.jt does not
            cpu.set_reg(1, pc + 2u);
        }
        cpu.set_pc(target);
        return StepResult::Ok;
    }

    if (kind == 0x3u) {  // cm.mvsa01 / cm.mva01s -- Zcmp
        const uint32_t pair = bits(c, 6, 5);
        if ((pair != 0x1u && pair != 0x3u) || !cpu.has(kExtZcmp)) {
            return StepResult::Illegal;
        }
        const unsigned first = sreg(bits(c, 9, 7));
        const unsigned second = sreg(bits(c, 4, 2));
        if (pair == 0x1u) {  // cm.mvsa01: two saved registers from a0, a1
            if (first == second) {
                return StepResult::Illegal;  // reserved
            }
            cpu.set_reg(first, cpu.reg(10));
            cpu.set_reg(second, cpu.reg(11));
        } else {  // cm.mva01s: a0, a1 from two saved registers
            cpu.set_reg(10, cpu.reg(first));
            cpu.set_reg(11, cpu.reg(second));
        }
        cpu.set_pc(pc + 2u);
        return StepResult::Ok;
    }

    if (kind == 0x6u || kind == 0x7u) {  // cm.push / cm.pop / cm.popret(z)
        if (bits(c, 8, 8) != 0 || !cpu.has(kExtZcmp)) {
            return StepResult::Illegal;  // the odd [12:8] rows are reserved
        }
        const uint32_t which = bits(c, 12, 9);  // 1100 push, 1101 pop,
                                                // 1110 popretz, 1111 popret
        const uint32_t rlist = bits(c, 7, 4);
        if (rlist < 4u) {
            return StepResult::Illegal;  // reserved
        }
        // rlist 15 jumps to the full {ra, s0-s11}: there is no 12-register
        // set, the spec skips from {ra, s0-s9} straight to everything.
        const unsigned count = rlist == 15u ? 13u : rlist - 3u;
        const uint32_t adjust =
            ((count * 4u + 15u) / 16u) * 16u + bits(c, 3, 2) * 16u;
        const uint32_t sp = cpu.reg(2);

        if (which == 0xCu) {  // cm.push
            // Highest saved register nearest the old sp, ra at the bottom --
            // the spec's own expansion order. Addresses are preflighted so an
            // unmapped stack stores nothing rather than half a frame; a
            // mapped register refusing a write can still stop it midway,
            // which a stack pointed into MMIO has earned.
            for (unsigned i = 0; i < count; ++i) {
                const uint32_t address = sp - 4u * (i + 1u);
                if (address % 4u != 0 || !cpu.in_range(address, 4)) {
                    cpu.note_data_fault(address);
                    return StepResult::MemoryFault;
                }
            }
            for (unsigned i = 0; i < count; ++i) {
                const uint32_t address = sp - 4u * (i + 1u);
                if (!cpu.write_word(address, cpu.reg(saved(count - 1u - i)))) {
                    cpu.note_data_fault(address);
                    return StepResult::MemoryFault;
                }
            }
            cpu.set_reg(2, sp - adjust);
            cpu.set_pc(pc + 2u);
            return StepResult::Ok;
        }

        // The three pops load into temporaries first, so a fault leaves
        // every register untouched -- the same all-or-nothing the StepResult
        // contract promises for refusals.
        uint32_t loaded[13] = {};
        for (unsigned i = 0; i < count; ++i) {
            const uint32_t address = sp + adjust - 4u * (i + 1u);
            if (address % 4u != 0 || !cpu.read_word(address, loaded[i])) {
                cpu.note_data_fault(address);
                return StepResult::MemoryFault;
            }
        }
        for (unsigned i = 0; i < count; ++i) {
            cpu.set_reg(saved(count - 1u - i), loaded[i]);
        }
        if (which == 0xEu) {  // cm.popretz zeroes a0 before returning
            cpu.set_reg(10, 0);
        }
        cpu.set_reg(2, sp + adjust);
        if (which == 0xDu) {  // cm.pop stays
            cpu.set_pc(pc + 2u);
            return StepResult::Ok;
        }
        // cm.popret / cm.popretz return through the ra just reloaded. The
        // frame is already committed when a misaligned target faults, which
        // is where real silicon would be when the jump traps.
        const uint32_t target = cpu.reg(1) & ~1u;
        if (!aligned(cpu, target)) {
            cpu.note_fetch_fault(target);
            return StepResult::MemoryFault;
        }
        cpu.set_pc(target);
        return StepResult::Ok;
    }

    // [12:10] of 001, 010, 100 and the unused mv pairs: reserved.
    return StepResult::Illegal;
}

}  // namespace

}  // namespace riscv32
