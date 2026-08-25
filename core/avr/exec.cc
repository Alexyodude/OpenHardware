// OpenHardware — the AVR instruction set an Arduino sketch actually needs.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What changed, and why the old rule stopped working
//
// This file used to hold fourteen instructions, and the list was not chosen —
// it was read off the disassembly of `tests/avr/blink/blink.c`. That is the
// same growth rule `webui/boards/rp2040.py` follows for registers, and on a
// peripheral it is right: a register is modelled when a real image reaches it.
//
// **On an instruction set it is not.** Measured 2026-08-26, a real sketch
// compiled against `framework-arduino-avr` uses 246 distinct encodings and
// stopped on its *first* — `0x940C`, the `JMP` in the reset vector. Sizing a
// core to one image produces a core that runs one image, and only a second
// image finds out. OH-58 is the correction.
//
// So the rule here is now the datasheet's own tables: an encoding is decoded
// because the AVR Instruction Set Manual lists it, and every one of them is
// checked against an independent oracle in `tests/avr/test_conformance.py`.
// What is still absent is absent on purpose — see the bottom of this comment.
//
// ## Everything else still returns Unimplemented
//
// That is the loud answer, and on a variable-length encoding it matters more
// than on Arm: a core that skipped an unknown word would resume decoding from
// the middle of the next instruction and run a program nobody wrote.
//
// ## The flag rules that are easy to get wrong
//
// **`cpc` clears Z only when the result is non-zero; it never sets it.** That
// is not a quirk, it is what makes a multi-byte compare work: `cp` on the low
// byte then `cpc` on the high byte leaves Z set only if BOTH were equal. A
// model that assigned Z from its own result would report equality on the high
// byte alone, and the blink's `i < 100` would exit at the wrong count. `sbc`
// and `sbci` carry Z in the same way, for the same reason.
//
// **`V` on `adiw`/`sbiw` is signed overflow of the 16-bit result**, taken from
// the old and new sign bits of the HIGH byte, not from a carry out.
//
// **`V` after a right shift is `N ^ C` using the C the shift just set**, not
// the one `ror` consumed. `set_shift_flags` takes the new carry as a parameter
// so a caller cannot read the wrong one back out of SREG.
//
// **`S` is always `N xor V`.** It is a derived flag and never assigned
// independently, so it is computed in one place.
//
// ## Two places the oracle is wrong and this file is right
//
// **The half-carry.** avr8js 0.21.0 masks its H boolean with `1` where the
// datasheet reads bit **3** — all eleven of its H expressions. `add 0x08,
// 0x08` is 0x10, which plainly carries out of the low nibble, and the oracle
// says H = 0. `tools/gen_avr_corpus.mjs` carries the manual's own expression
// beside the oracle's answer so the two are never blended.
//
// **`neg` of 0x80.** `instruction.js:523` tests `128 === R` where `R` is
// `0 - value`, a *negative* JavaScript number that is never 128, so avr8js
// never sets V for `neg`. The datasheet says V is set exactly when the result
// is 0x80, which is the one input that cannot be negated in eight bits. No
// corpus case draws 0x80 into a `neg` operand, so this disagreement is not
// exercised there; `tests/avr/test_datasheet_edges.py` asserts it directly
// against the manual instead.
//
// ## What is deliberately still absent
//
// `bld`, `bst`, `eijmp`, `eicall`, `elpm`, `spm`, `des`, `sleep`, `wdr`,
// `break`, `xch`, `las`, `lac`, `lat` and the fractional multiplies. Each
// would be a claim without a test behind it, so they refuse.
//
// **`sbrc`, `sbrs`, `ijmp` and `icall` were on that list until OH-63.** They
// came off it the way everything here does: a real image reached them. A
// sketch calling `Serial.println` dispatches through `Print`'s vtable, and
// gcc compiles that to `ijmp`; `sbrc`/`sbrs` appear five times in the same
// image. Measured, not guessed -- stepping every distinct word of a 1,724-byte
// Serial sketch left 23 refused, of which 14 are `.word` to objdump and are
// the pin tables read as code.

#include "exec.h"

#include "cpu.h"

namespace avr {
namespace {

/// `S = N ^ V`, per the datasheet. Derived rather than stored separately.
void set_sign(Cpu& cpu) {
    cpu.set_flag(kFlagS, cpu.flag(kFlagN) != cpu.flag(kFlagV));
}

/// N, Z, S and a V the caller has already decided.
///
/// Every arithmetic instruction here sets these four; they differ only in how
/// V is reached and in whether they also touch C or H. `inc` overflows at
/// 0x7F, `dec` at 0x80, `neg` at 0x80, a logic operation never — one boolean
/// rather than four near-copies of three assignments.
void set_result_flags(Cpu& cpu, uint8_t result, bool overflow) {
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0);
    cpu.set_flag(kFlagV, overflow);
    set_sign(cpu);
}

/// A logic operation clears V. Named because that is a datasheet rule and not
/// an implementation detail of the five instructions that share it.
void set_logic_flags(Cpu& cpu, uint8_t result) {
    set_result_flags(cpu, result, false);
}

/// N, Z, V and S after a one-bit right shift, and the carry it shifted out.
///
/// **V is `N ^ C` with the C this shift produced.** `ror` consumes the old
/// carry and produces a new one in the same instruction, so a caller that
/// wrote the result and then read C back out of SREG would get whichever the
/// order happened to leave. It is a parameter for that reason.
void set_shift_flags(Cpu& cpu, uint8_t result, bool carry_out) {
    cpu.set_flag(kFlagC, carry_out);
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0);
    cpu.set_flag(kFlagV, ((result & 0x80) != 0) != carry_out);
    set_sign(cpu);
}

/// `left + right + carry_in`, with every flag an AVR add sets.
///
/// Returns the result because `add` and `adc` write it back. Nothing compares
/// by adding, so unlike `sub_with_flags` this has no discarding caller.
uint8_t add_with_flags(Cpu& cpu, uint8_t left, uint8_t right, bool carry_in) {
    const uint16_t wide =
        static_cast<uint16_t>(left) + right + (carry_in ? 1u : 0u);
    const uint8_t result = static_cast<uint8_t>(wide);

    cpu.set_flag(kFlagC, (wide & 0x100) != 0);
    // Half-carry, the manual's `Rd3.Rr3 + Rr3./R3 + /R3.Rd3` — carry out of
    // bit 3, which is the majority of the three bits.
    cpu.set_flag(kFlagH,
                 (((left & right) | (right & ~result) | (~result & left)) &
                  0x08) != 0);
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    // Signed overflow: the operands agreed in sign and the result did not.
    cpu.set_flag(kFlagV, ((~(left ^ right) & (left ^ result)) & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0);
    set_sign(cpu);
    return result;
}

/// `left - right - borrow_in`, with every flag an AVR subtract sets.
///
/// **A compare is a subtract that discards its result**, which is why `cp`,
/// `cpc` and `cpi` call this and ignore the return value rather than having a
/// flags-only twin that would have to be kept in step with it.
///
/// `carry_z` is what makes the `-c` forms different: it is the Z flag before
/// the operation, and Z ends up `previous && result == 0`. Passing `true`
/// gives the ordinary "Z is exactly result == 0" that `sub` and `cp` want.
uint8_t sub_with_flags(Cpu& cpu, uint8_t left, uint8_t right, bool borrow_in,
                       bool carry_z) {
    const uint16_t wide =
        static_cast<uint16_t>(left) - right - (borrow_in ? 1u : 0u);
    const uint8_t result = static_cast<uint8_t>(wide);

    cpu.set_flag(kFlagC, (wide & 0x100) != 0);
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    // Half-carry: borrow out of bit 3, `/Rd3.Rr3 + Rr3.R3 + R3./Rd3`.
    cpu.set_flag(kFlagH, ((~left & 0x08) & (right & 0x08)) != 0 ||
                             ((right & 0x08) & (result & 0x08)) != 0 ||
                             ((result & 0x08) & (~left & 0x08)) != 0);
    // Signed overflow: the operands differed in sign and the result took the
    // subtrahend's.
    cpu.set_flag(kFlagV, (((left ^ right) & (left ^ result)) & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0 && carry_z);
    set_sign(cpu);
    return result;
}

/// R1:R0 and the two flags a multiply sets: C is bit 15 of the product, Z is
/// all sixteen bits. Nothing else in SREG moves, which is why this does not go
/// through `set_result_flags` — a multiply does not set N or S at all.
void set_product(Cpu& cpu, uint16_t product) {
    cpu.set_reg_pair(0, product);
    cpu.set_flag(kFlagC, (product & 0x8000) != 0);
    cpu.set_flag(kFlagZ, product == 0);
}

/// Write at SP, then decrement — the order the datasheet specifies, and the
/// order `ret` reads back in.
bool push_byte(Cpu& cpu, uint8_t value) {
    const uint16_t at = cpu.sp();
    if (!cpu.write_data(at, value)) {
        return false;
    }
    cpu.set_sp(static_cast<uint16_t>(at - 1));
    return true;
}

/// Read at SP+1, then commit the increment. In that order so a pop off the top
/// of the data space faults without having moved SP.
bool pop_byte(Cpu& cpu, uint8_t& out) {
    const uint16_t at = static_cast<uint16_t>(cpu.sp() + 1);
    if (!cpu.read_data(at, out)) {
        return false;
    }
    cpu.set_sp(at);
    return true;
}

/// One byte of PROGRAM memory by BYTE address, which is what Z holds for
/// `lpm`. The word is `at >> 1` and the half is `at & 1`, little-endian —
/// this is the one instruction that crosses between the two address spaces
/// `cpu.h` keeps apart.
bool read_program_byte(Cpu& cpu, uint32_t at, uint8_t& out) {
    uint16_t word = 0;
    if (!cpu.read_program(at >> 1, word)) {
        return false;
    }
    out = static_cast<uint8_t>((at & 1) ? (word >> 8) : word);
    return true;
}

/// True when `encoding` is the FIRST word of a 32-bit instruction.
///
/// `cpse`, `sbic` and `sbis` skip *over* the next instruction, and how far
/// that is depends on what the next instruction is. Land one word short of a
/// `jmp` and the PC sits on its second word — a plain 16-bit target address
/// that decodes as whatever it happens to look like, so the machine keeps
/// running, executing a program nobody wrote. avr8js has
/// `isTwoWordInstruction` for exactly this (`instruction.js:6`); these are the
/// same four encodings, and they are the only wide ones this part has.
bool is_two_word(uint16_t encoding) {
    return (encoding & 0xFE0F) == 0x9000 ||   // lds
           (encoding & 0xFE0F) == 0x9200 ||   // sts
           (encoding & 0xFE0E) == 0x940C ||   // jmp
           (encoding & 0xFE0E) == 0x940E;     // call
}

/// Take the pending interrupt: push the return address, clear I, clear the
/// source's flag, and jump to the vector.
///
/// **This happens INSTEAD of an instruction, not before one.** The step it
/// occupies is the step the interrupted instruction would have had, which is
/// why `step` returns straight afterwards rather than falling through to the
/// fetch. On the silicon that entry costs four cycles; this core does not
/// model cycles and charges it one.
///
/// I is cleared by the hardware and restored by `reti`. The overflow flag is
/// cleared here for the same reason the silicon clears it: otherwise the
/// handler would be re-entered the instant it returned.
StepResult enter_interrupt(Cpu& cpu) {
    const uint32_t ret = cpu.pc();
    if (!push_byte(cpu, static_cast<uint8_t>(ret)) ||
        !push_byte(cpu, static_cast<uint8_t>(ret >> 8))) {
        return StepResult::MemoryFault;
    }
    cpu.acknowledge_interrupt();
    cpu.set_flag(kFlagI, false);
    cpu.set_pc(cpu.timer().vector);
    return StepResult::Ok;
}

/// Move the PC past the next instruction, whether that is one word or two.
StepResult skip_next(Cpu& cpu) {
    uint16_t next = 0;
    if (!cpu.read_program(cpu.pc(), next)) {
        return StepResult::MemoryFault;
    }
    cpu.set_pc(cpu.pc() + (is_two_word(next) ? 2u : 1u));
    return StepResult::Ok;
}

}  // namespace

StepResult step(Cpu& cpu) {
    // --- an interrupt, if one is due ---------------------------------------
    //
    // Before the fetch, because an interrupt is taken *instead of* the next
    // instruction rather than between two of them.
    //
    // **`sei` and `reti` protect exactly one following instruction.** The
    // datasheet says so, and the reason is a handler that re-enables early: a
    // source still asserting would re-enter it before the interrupted code
    // advanced a single word, and the machine would make no progress while
    // looking perfectly busy. So the step after either instruction spends the
    // inhibit rather than testing for a vector.
    if (cpu.interrupt_inhibited()) {
        cpu.allow_interrupts();
    } else if (cpu.interrupt_pending()) {
        return enter_interrupt(cpu);
    }

    const uint32_t at = cpu.pc();
    uint16_t encoding = 0;
    if (!cpu.read_program(at, encoding)) {
        return StepResult::MemoryFault;
    }

    // Advance first; a branch overwrites it. The same order core/cortexm0's
    // exec.cc uses, and for the reason recorded there: "advance only if the PC
    // changed" cannot see a branch to self, which `rjmp .-2` is.
    cpu.set_pc(at + 1);

    // =====================================================================
    // The 1001 010x space, most-specific first.
    //
    // This is the crowded quarter of the map: whole-word instructions, the
    // one-operand arithmetic table, the SREG bit setters and the two 32-bit
    // control transfers all live in 0x9400-0x95FF. **Order is load-bearing
    // here** — `ret` is 0x9508 and would be caught by a `1001 010d dddd 1000`
    // shape if one came first, so the exact matches are tested before the
    // table-shaped ones.
    // =====================================================================

    // --- ret / reti -- 1001 0101 0000 1000 / 1001 0101 0001 1000 ----------
    //
    // One decode because `reti` is `ret` plus one flag, which is how the
    // datasheet presents it too. The high byte comes off the stack first: a
    // call wrote the low byte at SP and the high byte at SP-1, so after the
    // call SP+1 holds the high byte. Reading them the other way round returns
    // to a byte-swapped address, which is a real address and does not fault.
    if (encoding == 0x9508 || encoding == 0x9518) {
        uint8_t high = 0;
        uint8_t low = 0;
        if (!pop_byte(cpu, high) || !pop_byte(cpu, low)) {
            return StepResult::MemoryFault;
        }
        cpu.set_pc(static_cast<uint32_t>(high) << 8 | low);
        if (encoding == 0x9518) {
            cpu.set_flag(kFlagI, true);
            // One instruction of the interrupted code runs before another
            // interrupt can be taken. See the top of `step`.
            cpu.inhibit_interrupts();
        }
        return StepResult::Ok;
    }

    // --- lpm -- 1001 0101 1100 1000, the implied form -----------------------
    //
    // R0 gets the byte, Z is unchanged. The `lpm Rd, Z` forms are in the
    // 1001 00xx block below, which is where the datasheet puts them.
    if (encoding == 0x95C8) {
        uint8_t value = 0;
        if (!read_program_byte(cpu, cpu.reg_pair(kZ), value)) {
            return StepResult::MemoryFault;
        }
        cpu.set_reg(0, value);
        return StepResult::Ok;
    }

    // --- ijmp / icall -- 1001 0100 0000 1001 / 1001 0101 0000 1001 --------
    //
    // Jump to where Z points. **Z is a WORD address here**, unlike `lpm`,
    // which reads program memory through the same register pair by BYTE
    // address. One register, two meanings, decided by the instruction -- the
    // reason `cpu.h` keeps the two spaces apart and makes every accessor say
    // which one it means.
    //
    // Reached by a real image and not by inspection: `Serial.println` dispatches
    // through `Print`'s vtable, and gcc compiles that tail call to `ijmp`.
    // `eijmp` and `eicall` are the same encodings with bit 4 set; they need
    // EIND, which this part does not have, so they still refuse.
    if (encoding == 0x9409 || encoding == 0x9509) {
        if (encoding == 0x9509) {   // icall pushes, ijmp does not
            const uint32_t ret = cpu.pc();
            if (!push_byte(cpu, static_cast<uint8_t>(ret)) ||
                !push_byte(cpu, static_cast<uint8_t>(ret >> 8))) {
                return StepResult::MemoryFault;
            }
        }
        cpu.set_pc(cpu.reg_pair(kZ));
        return StepResult::Ok;
    }

    // --- bset s / bclr s -- 1001 0100 0sss 1000 / 1001 0100 1sss 1000 -----
    //
    // `sec`, `sez`, `sen`, `sev`, `ses`, `seh`, `set`, `sei` and their eight
    // clearing partners are all this one encoding with `sss` naming the SREG
    // bit. Sixteen mnemonics, one decode; the assembler treats them as
    // aliases too, and writing them out would be sixteen chances to transpose
    // a bit number.
    if ((encoding & 0xFF0F) == 0x9408) {
        const uint8_t bit = (encoding >> 4) & 0x07;
        const bool setting = (encoding & 0x0080) == 0;
        cpu.set_flag(static_cast<uint8_t>(1u << bit), setting);
        // `sei` is `bset 7`, and it protects the next instruction. `cli` does
        // not need to: clearing I stops interrupts immediately.
        if (setting && bit == 7) {
            cpu.inhibit_interrupts();
        }
        return StepResult::Ok;
    }

    // --- jmp k -- 1001 010k kkkk 110k + kkkk kkkk kkkk kkkk ---------------
    //
    // 22 bits of WORD address, scattered: bits 21..17 in the first word's
    // register field, bit 16 in its low bit, and the low sixteen in the word
    // after. The ATmega328P only has 14 of them, but the encoding is the
    // encoding and masking the target to the part's flash would turn a wild
    // jump into a plausible one.
    if ((encoding & 0xFE0E) == 0x940C) {
        uint16_t low = 0;
        if (!cpu.read_program(cpu.pc(), low)) {
            return StepResult::MemoryFault;
        }
        cpu.set_pc((static_cast<uint32_t>(encoding & 0x01F0) << 13) |
                   (static_cast<uint32_t>(encoding & 0x0001) << 16) | low);
        return StepResult::Ok;
    }

    // --- call k -- 1001 010k kkkk 111k + kkkk kkkk kkkk kkkk --------------
    //
    // The return address is the word AFTER both halves, so `cpu.pc() + 1`
    // here — the fetch above already advanced past the first word. Two bytes
    // are pushed because this part's PC fits in sixteen bits; a part with
    // more than 128 KB of flash pushes three, and this core does not model
    // one.
    if ((encoding & 0xFE0E) == 0x940E) {
        uint16_t low = 0;
        if (!cpu.read_program(cpu.pc(), low)) {
            return StepResult::MemoryFault;
        }
        const uint32_t ret = cpu.pc() + 1;
        if (!push_byte(cpu, static_cast<uint8_t>(ret)) ||
            !push_byte(cpu, static_cast<uint8_t>(ret >> 8))) {
            return StepResult::MemoryFault;
        }
        cpu.set_pc((static_cast<uint32_t>(encoding & 0x01F0) << 13) |
                   (static_cast<uint32_t>(encoding & 0x0001) << 16) | low);
        return StepResult::Ok;
    }

    // --- the one-operand table -- 1001 010d dddd tttt ---------------------
    //
    // Eight instructions over one register, listed as a table in the manual
    // and written as one here. They agree on N, Z and S and disagree on
    // everything else, which is what `set_result_flags`' one boolean is for.
    //
    // The tails NOT listed are 0100 (nothing), 1000 and 1001 (the whole-word
    // instructions above, plus `ijmp`/`icall` which this core does not have),
    // 1011 (`des`) and 1100-1111 (`jmp`/`call`, decoded above). They reach
    // `default` and refuse.
    if ((encoding & 0xFE00) == 0x9400) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t value = cpu.reg(rd);
        switch (encoding & 0x000F) {
            case 0x0: {  // com Rd -- one's complement. **C is set, not
                         // cleared**: the datasheet defines `com` as
                         // 0xFF - Rd, and a subtract from 0xFF never borrows.
                const uint8_t result = static_cast<uint8_t>(~value);
                cpu.set_reg(rd, result);
                set_result_flags(cpu, result, false);
                cpu.set_flag(kFlagC, true);
                return StepResult::Ok;
            }
            case 0x1: {  // neg Rd -- two's complement.
                const uint8_t result = static_cast<uint8_t>(0 - value);
                cpu.set_reg(rd, result);
                // V is set for exactly one input: 0x80, whose negation is
                // itself. See the header -- avr8js never sets this.
                set_result_flags(cpu, result, result == 0x80);
                cpu.set_flag(kFlagC, result != 0);
                // H is `R3 + Rd3`, an OR rather than the majority the add and
                // subtract rules use.
                cpu.set_flag(kFlagH, ((result | value) & 0x08) != 0);
                return StepResult::Ok;
            }
            case 0x2:  // swap Rd -- nibbles, and no flag at all.
                cpu.set_reg(rd, static_cast<uint8_t>((value << 4) | (value >> 4)));
                return StepResult::Ok;
            case 0x3: {  // inc Rd -- no carry, no half-carry.
                const uint8_t result = static_cast<uint8_t>(value + 1);
                cpu.set_reg(rd, result);
                set_result_flags(cpu, result, value == 0x7F);
                return StepResult::Ok;
            }
            case 0x5: {  // asr Rd -- arithmetic shift right, sign preserved.
                const uint8_t result =
                    static_cast<uint8_t>((value >> 1) | (value & 0x80));
                cpu.set_reg(rd, result);
                set_shift_flags(cpu, result, (value & 1) != 0);
                return StepResult::Ok;
            }
            case 0x6: {  // lsr Rd -- N is always clear, so V is the carry.
                const uint8_t result = static_cast<uint8_t>(value >> 1);
                cpu.set_reg(rd, result);
                set_shift_flags(cpu, result, (value & 1) != 0);
                return StepResult::Ok;
            }
            case 0x7: {  // ror Rd -- through the carry.
                const uint8_t result = static_cast<uint8_t>(
                    (value >> 1) | (cpu.flag(kFlagC) ? 0x80 : 0x00));
                cpu.set_reg(rd, result);
                set_shift_flags(cpu, result, (value & 1) != 0);
                return StepResult::Ok;
            }
            case 0xA: {  // dec Rd -- overflows at 0x80, where `inc` does at 0x7F.
                const uint8_t result = static_cast<uint8_t>(value - 1);
                cpu.set_reg(rd, result);
                set_result_flags(cpu, result, value == 0x80);
                return StepResult::Ok;
            }
            default:
                cpu.set_pc(at);
                return StepResult::Unimplemented;
        }
    }

    // --- adiw Rd, K -- 1001 0110 KKdd KKKK, d in {24,26,28,30} ------------
    if ((encoding & 0xFF00) == 0x9600) {
        const uint8_t rd = static_cast<uint8_t>(24 + ((encoding >> 4) & 0x03) * 2);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 2) & 0x30) |
                                               (encoding & 0x0F));
        const uint16_t before = cpu.reg_pair(rd);
        const uint32_t wide = static_cast<uint32_t>(before) + k;
        const uint16_t result = static_cast<uint16_t>(wide);
        cpu.set_reg_pair(rd, result);

        cpu.set_flag(kFlagC, (wide & 0x10000) != 0);
        cpu.set_flag(kFlagZ, result == 0);
        cpu.set_flag(kFlagN, (result & 0x8000) != 0);
        // Signed overflow from the high byte's sign bits, not from the carry.
        cpu.set_flag(kFlagV, ((~before & result) & 0x8000) != 0);
        set_sign(cpu);
        return StepResult::Ok;
    }

    // --- sbiw Rd, K -- 1001 0111 KKdd KKKK --------------------------------
    //
    // `adiw`'s partner, and every flag is its mirror: C is a borrow rather
    // than a carry, and V is the old sign set with the new one clear rather
    // than the other way round. Written out rather than shared with `adiw`
    // behind a subtract flag, because the two differ in four of five flags —
    // a shared body would be four branches wearing one name.
    if ((encoding & 0xFF00) == 0x9700) {
        const uint8_t rd = static_cast<uint8_t>(24 + ((encoding >> 4) & 0x03) * 2);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 2) & 0x30) |
                                               (encoding & 0x0F));
        const uint16_t before = cpu.reg_pair(rd);
        const uint16_t result = static_cast<uint16_t>(before - k);
        cpu.set_reg_pair(rd, result);

        cpu.set_flag(kFlagC, k > before);
        cpu.set_flag(kFlagZ, result == 0);
        cpu.set_flag(kFlagN, (result & 0x8000) != 0);
        cpu.set_flag(kFlagV, ((before & ~result) & 0x8000) != 0);
        set_sign(cpu);
        return StepResult::Ok;
    }

    // --- sbi A, b -- 1001 1010 AAAA Abbb ----------------------------------
    if ((encoding & 0xFF00) == 0x9A00) {
        const uint8_t a = (encoding >> 3) & 0x1F;
        const uint8_t bit = encoding & 0x07;
        uint8_t value = 0;
        if (!cpu.read_data(static_cast<uint16_t>(kIoBase + a), value)) {
            return StepResult::MemoryFault;
        }
        if (!cpu.write_data(static_cast<uint16_t>(kIoBase + a),
                            static_cast<uint8_t>(value | (1u << bit)))) {
            return StepResult::MemoryFault;
        }
        return StepResult::Ok;
    }

    // --- cbi A, b -- 1001 1000 AAAA Abbb ----------------------------------
    //
    // Not in the blink, and here anyway: it is the same decode with one bit
    // different, and a `sbi` implemented without it invites the next reader to
    // add `cbi` by copying and inverting -- which is where the bit gets lost.
    if ((encoding & 0xFF00) == 0x9800) {
        const uint8_t a = (encoding >> 3) & 0x1F;
        const uint8_t bit = encoding & 0x07;
        uint8_t value = 0;
        if (!cpu.read_data(static_cast<uint16_t>(kIoBase + a), value)) {
            return StepResult::MemoryFault;
        }
        if (!cpu.write_data(static_cast<uint16_t>(kIoBase + a),
                            static_cast<uint8_t>(value & ~(1u << bit)))) {
            return StepResult::MemoryFault;
        }
        return StepResult::Ok;
    }

    // --- sbic / sbis A, b -- 1001 1001 / 1001 1011 AAAA Abbb --------------
    //
    // Bit 9 chooses the polarity, which is why the mask is 0xFD00 and not
    // 0xFF00: `sbic` skips when the IO bit is CLEAR and `sbis` when it is
    // set. They sit next to `sbi`/`cbi` in the map and are a different family
    // — 1001 10x0 writes a bit, 1001 10x1 tests one.
    if ((encoding & 0xFD00) == 0x9900) {
        const bool skip_if_set = (encoding & 0x0200) != 0;
        const uint8_t a = (encoding >> 3) & 0x1F;
        const uint8_t bit = encoding & 0x07;
        uint8_t value = 0;
        if (!cpu.read_data(static_cast<uint16_t>(kIoBase + a), value)) {
            return StepResult::MemoryFault;
        }
        if (((value >> bit) & 1) == (skip_if_set ? 1u : 0u)) {
            return skip_next(cpu);
        }
        return StepResult::Ok;
    }

    // --- mul Rd, Rr -- 1001 11rd dddd rrrr --------------------------------
    if ((encoding & 0xFC00) == 0x9C00) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t rr = static_cast<uint8_t>(((encoding >> 5) & 0x10) |
                                                (encoding & 0x0F));
        set_product(cpu, static_cast<uint16_t>(cpu.reg(rd) * cpu.reg(rr)));
        return StepResult::Ok;
    }

    // --- the 1001 00xx block: everything that moves a byte ----------------
    //
    // One decode for what the manual also presents as a table. Bit 9 chooses
    // store over load and the low nibble chooses the addressing mode, so
    // `ld r16, X+` and `st X+, r16` are four lines apart instead of in
    // different halves of the file — which is where a post-increment gets
    // applied to one of them and not the other.
    //
    //   tail   load  1001 000d dddd tttt   store  1001 001r rrrr tttt
    //   0000   lds Rd, k   (32-bit)        sts k, Rr   (32-bit)
    //   0001   ld Rd, Z+                   st Z+, Rr
    //   0010   ld Rd, -Z                   st -Z, Rr
    //   0100   lpm Rd, Z                   xch  -- absent
    //   0101   lpm Rd, Z+                  las  -- absent
    //   0110   elpm -- absent              lac  -- absent
    //   0111   elpm -- absent              lat  -- absent
    //   1001   ld Rd, Y+                   st Y+, Rr
    //   1010   ld Rd, -Y                   st -Y, Rr
    //   1100   ld Rd, X                    st X, Rr
    //   1101   ld Rd, X+                   st X+, Rr
    //   1110   ld Rd, -X                   st -X, Rr
    //   1111   pop Rd                      push Rr
    //
    // The `ld Rd, Y` and `ld Rd, Z` forms with no displacement are NOT here —
    // they are `ldd` with q = 0, in the 10q0 block further down. That is the
    // manual's arrangement and not a choice made here.
    if ((encoding & 0xFC00) == 0x9000) {
        const bool store = (encoding & 0x0200) != 0;
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t tail = encoding & 0x000F;

        // lds / sts: the word after is a 16-bit DATA address, so the PC moves
        // twice and the second word is not an instruction.
        if (tail == 0x0) {
            uint16_t address = 0;
            if (!cpu.read_program(cpu.pc(), address)) {
                return StepResult::MemoryFault;
            }
            cpu.set_pc(cpu.pc() + 1);
            if (store) {
                if (!cpu.write_data(address, cpu.reg(rd))) {
                    return StepResult::MemoryFault;
                }
                return StepResult::Ok;
            }
            uint8_t value = 0;
            if (!cpu.read_data(address, value)) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(rd, value);
            return StepResult::Ok;
        }

        // push / pop.
        if (tail == 0xF) {
            if (store) {
                return push_byte(cpu, cpu.reg(rd)) ? StepResult::Ok
                                                   : StepResult::MemoryFault;
            }
            uint8_t value = 0;
            if (!pop_byte(cpu, value)) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(rd, value);
            return StepResult::Ok;
        }

        // lpm Rd, Z and lpm Rd, Z+ — the other address space, by byte address.
        if (!store && (tail == 0x4 || tail == 0x5)) {
            uint8_t value = 0;
            if (!read_program_byte(cpu, cpu.reg_pair(kZ), value)) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(rd, value);
            if (tail == 0x5) {
                cpu.set_reg_pair(kZ, static_cast<uint16_t>(cpu.reg_pair(kZ) + 1));
            }
            return StepResult::Ok;
        }

        // The pointer forms. **Pre-decrement happens before the access and
        // post-increment after it**, which is the whole difference between
        // `-X` and `X+` and the reason the pointer is written back in two
        // different places rather than once at the end.
        uint8_t pointer = 0;
        int step_by = 0;
        switch (tail) {
            case 0x1: pointer = kZ; step_by = +1; break;
            case 0x2: pointer = kZ; step_by = -1; break;
            case 0x9: pointer = kY; step_by = +1; break;
            case 0xA: pointer = kY; step_by = -1; break;
            case 0xC: pointer = kX; step_by = 0; break;
            case 0xD: pointer = kX; step_by = +1; break;
            case 0xE: pointer = kX; step_by = -1; break;
            default:
                // elpm, xch, las, lac, lat and the reserved tails.
                cpu.set_pc(at);
                return StepResult::Unimplemented;
        }

        uint16_t address = cpu.reg_pair(pointer);
        if (step_by < 0) {
            address = static_cast<uint16_t>(address - 1);
            cpu.set_reg_pair(pointer, address);
        }
        if (store) {
            if (!cpu.write_data(address, cpu.reg(rd))) {
                return StepResult::MemoryFault;
            }
        } else {
            uint8_t value = 0;
            if (!cpu.read_data(address, value)) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(rd, value);
        }
        if (step_by > 0) {
            cpu.set_reg_pair(pointer, static_cast<uint16_t>(address + 1));
        }
        return StepResult::Ok;
    }

    // =====================================================================
    // The 0000-0011 space: four encodings of their own, then eleven that
    // share one operand layout.
    // =====================================================================

    // --- nop -- 0000 0000 0000 0000 ---------------------------------------
    if (encoding == 0x0000) {
        return StepResult::Ok;
    }

    // --- movw Rd+1:Rd, Rr+1:Rr -- 0000 0001 dddd rrrr ---------------------
    //
    // The fields are pair numbers, so they double. Touches no flag.
    if ((encoding & 0xFF00) == 0x0100) {
        const uint8_t rd = static_cast<uint8_t>(((encoding >> 4) & 0x0F) * 2);
        const uint8_t rr = static_cast<uint8_t>((encoding & 0x0F) * 2);
        cpu.set_reg_pair(rd, cpu.reg_pair(rr));
        return StepResult::Ok;
    }

    // --- muls Rd, Rr -- 0000 0010 dddd rrrr, both operands SIGNED ---------
    //
    // Four-bit register fields meaning r16..r31, unlike `mul`'s five-bit ones.
    if ((encoding & 0xFF00) == 0x0200) {
        const int8_t left = static_cast<int8_t>(cpu.reg(16 + ((encoding >> 4) & 0x0F)));
        const int8_t right = static_cast<int8_t>(cpu.reg(16 + (encoding & 0x0F)));
        set_product(cpu, static_cast<uint16_t>(left * right));
        return StepResult::Ok;
    }

    // --- mulsu Rd, Rr -- 0000 0011 0ddd 0rrr, Rd signed and Rr not --------
    //
    // Three-bit fields meaning r16..r23. The mask keeps bits 7 and 3 clear so
    // `fmul`, `fmuls` and `fmulsu` — which share these eight bits and differ
    // only in those two — refuse rather than being silently treated as this.
    if ((encoding & 0xFF88) == 0x0300) {
        const int8_t left = static_cast<int8_t>(cpu.reg(16 + ((encoding >> 4) & 0x07)));
        const uint8_t right = cpu.reg(16 + (encoding & 0x07));
        set_product(cpu, static_cast<uint16_t>(left * right));
        return StepResult::Ok;
    }

    // --- the register-register block -- 00xx xxrd dddd rrrr ---------------
    //
    // Eleven instructions with one operand layout: Rd at bits 8..4, Rr at bits
    // 3..0 with its fifth bit up at 9. **Extracted once**, because eleven
    // copies of those two lines is eleven places for the `>> 5` to become a
    // `>> 4` — and a wrong Rr reads a real register and produces a plausible
    // answer.
    //
    // The mask reaches 0x3FFF, which is one block wider than the eleven: the
    // four encodings above have already returned, and `cpi` at 0x3000 falls
    // out of the switch to the decode further down.
    if ((encoding & 0xC000) == 0x0000) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t rr = static_cast<uint8_t>(((encoding >> 5) & 0x10) |
                                                (encoding & 0x0F));
        const uint8_t left = cpu.reg(rd);
        const uint8_t right = cpu.reg(rr);
        switch (encoding & 0xFC00) {
            case 0x0400:  // cpc -- Z is carried in, so it may only ever clear.
                sub_with_flags(cpu, left, right, cpu.flag(kFlagC),
                               cpu.flag(kFlagZ));
                return StepResult::Ok;
            case 0x0800:  // sbc -- `cpc` that keeps its result.
                cpu.set_reg(rd, sub_with_flags(cpu, left, right,
                                               cpu.flag(kFlagC),
                                               cpu.flag(kFlagZ)));
                return StepResult::Ok;
            case 0x0C00:  // add -- and `lsl Rd` when d == r.
                cpu.set_reg(rd, add_with_flags(cpu, left, right, false));
                return StepResult::Ok;
            case 0x1000:  // cpse -- skip the next instruction if equal.
                if (left == right) {
                    return skip_next(cpu);
                }
                return StepResult::Ok;
            case 0x1400:  // cp -- a subtract that discards its result.
                sub_with_flags(cpu, left, right, false, true);
                return StepResult::Ok;
            case 0x1800:  // sub
                cpu.set_reg(rd, sub_with_flags(cpu, left, right, false, true));
                return StepResult::Ok;
            case 0x1C00:  // adc -- and `rol Rd` when d == r.
                cpu.set_reg(rd,
                            add_with_flags(cpu, left, right, cpu.flag(kFlagC)));
                return StepResult::Ok;
            case 0x2000: {  // and
                const uint8_t result = static_cast<uint8_t>(left & right);
                cpu.set_reg(rd, result);
                set_logic_flags(cpu, result);
                return StepResult::Ok;
            }
            case 0x2400: {  // eor
                const uint8_t result = static_cast<uint8_t>(left ^ right);
                cpu.set_reg(rd, result);
                set_logic_flags(cpu, result);
                return StepResult::Ok;
            }
            case 0x2800: {  // or
                const uint8_t result = static_cast<uint8_t>(left | right);
                cpu.set_reg(rd, result);
                set_logic_flags(cpu, result);
                return StepResult::Ok;
            }
            case 0x2C00:  // mov -- no flag, and the only one that reads Rr
                          // without arithmetic.
                cpu.set_reg(rd, right);
                return StepResult::Ok;
            default:
                break;  // 0x0000-0x03FF and 0x3000: decoded elsewhere.
        }
    }

    // --- cpi Rd, K -- 0011 KKKK dddd KKKK, d in 16..31 --------------------
    if ((encoding & 0xF000) == 0x3000) {
        const uint8_t rd = 16 + ((encoding >> 4) & 0x0F);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 4) & 0xF0) |
                                               (encoding & 0x0F));
        sub_with_flags(cpu, cpu.reg(rd), k, false, true);
        return StepResult::Ok;
    }

    // --- the register-immediate block -- 01xx KKKK dddd KKKK --------------
    //
    // `sbci`, `subi`, `ori` and `andi`: a four-bit register number meaning
    // r16..r31 and an eight-bit constant split either side of it. The mask
    // covers 0x4000-0x7FFF exactly, which is these four and nothing else, so
    // the switch is exhaustive and has no fall-out.
    //
    // `cpi` above and `ldi` below share the layout and not the block — the
    // manual puts them at 0x3000 and 0xE000.
    if ((encoding & 0xC000) == 0x4000) {
        const uint8_t rd = 16 + ((encoding >> 4) & 0x0F);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 4) & 0xF0) |
                                               (encoding & 0x0F));
        const uint8_t left = cpu.reg(rd);
        switch (encoding & 0xF000) {
            case 0x4000:  // sbci -- Z carried in, exactly as `sbc`.
                cpu.set_reg(rd, sub_with_flags(cpu, left, k, cpu.flag(kFlagC),
                                               cpu.flag(kFlagZ)));
                return StepResult::Ok;
            case 0x5000:  // subi
                cpu.set_reg(rd, sub_with_flags(cpu, left, k, false, true));
                return StepResult::Ok;
            case 0x6000: {  // ori -- `sbr` under its other name.
                const uint8_t result = static_cast<uint8_t>(left | k);
                cpu.set_reg(rd, result);
                set_logic_flags(cpu, result);
                return StepResult::Ok;
            }
            default: {  // 0x7000, andi -- `cbr` under its other name.
                const uint8_t result = static_cast<uint8_t>(left & k);
                cpu.set_reg(rd, result);
                set_logic_flags(cpu, result);
                return StepResult::Ok;
            }
        }
    }

    // --- ldi Rd, K -- 1110 KKKK dddd KKKK, d in 16..31 --------------------
    if ((encoding & 0xF000) == 0xE000) {
        const uint8_t rd = 16 + ((encoding >> 4) & 0x0F);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 4) & 0xF0) |
                                               (encoding & 0x0F));
        cpu.set_reg(rd, k);
        return StepResult::Ok;
    }

    // --- rjmp k -- 1100 kkkk kkkk kkkk, k a signed WORD displacement ------
    if ((encoding & 0xF000) == 0xC000) {
        int16_t offset = static_cast<int16_t>(encoding & 0x0FFF);
        if (offset & 0x0800) {
            offset = static_cast<int16_t>(offset | 0xF000);
        }
        cpu.set_pc(static_cast<uint32_t>(cpu.pc() + offset));
        return StepResult::Ok;
    }

    // --- rcall k -- 1101 kkkk kkkk kkkk -----------------------------------
    //
    // Pushes the return address LOW byte first and decrements SP past it, the
    // order the datasheet specifies. gcc emits `rcall .+0` purely to open two
    // bytes of stack frame, so the pushed value is never returned to -- but it
    // is written, and a model that skipped the write would leave the frame
    // uninitialised where the program expects its own return address.
    if ((encoding & 0xF000) == 0xD000) {
        int16_t offset = static_cast<int16_t>(encoding & 0x0FFF);
        if (offset & 0x0800) {
            offset = static_cast<int16_t>(offset | 0xF000);
        }
        const uint32_t ret = cpu.pc();
        if (!push_byte(cpu, static_cast<uint8_t>(ret)) ||
            !push_byte(cpu, static_cast<uint8_t>(ret >> 8))) {
            return StepResult::MemoryFault;
        }
        cpu.set_pc(static_cast<uint32_t>(cpu.pc() + offset));
        return StepResult::Ok;
    }

    // --- in Rd, A -- 1011 0AAd dddd AAAA ----------------------------------
    if ((encoding & 0xF800) == 0xB000) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t a = static_cast<uint8_t>(((encoding >> 5) & 0x30) |
                                               (encoding & 0x0F));
        uint8_t value = 0;
        if (!cpu.read_data(static_cast<uint16_t>(kIoBase + a), value)) {
            return StepResult::MemoryFault;
        }
        cpu.set_reg(rd, value);
        return StepResult::Ok;
    }

    // --- out A, Rr -- 1011 1AAr rrrr AAAA ---------------------------------
    if ((encoding & 0xF800) == 0xB800) {
        const uint8_t rr = (encoding >> 4) & 0x1F;
        const uint8_t a = static_cast<uint8_t>(((encoding >> 5) & 0x30) |
                                               (encoding & 0x0F));
        if (!cpu.write_data(static_cast<uint16_t>(kIoBase + a), cpu.reg(rr))) {
            return StepResult::MemoryFault;
        }
        return StepResult::Ok;
    }

    // --- brbc/brbs -- 1111 0Skk kkkk ksss ---------------------------------
    //
    // One decode for the whole branch family. The blink uses `brcc`, which is
    // `brbc` with s == 0; naming only that case would have meant a second
    // decode for `brne` the first time a loop counted down instead of up.
    if ((encoding & 0xF800) == 0xF000) {
        // **Bit 10 set means BRBC -- branch if the bit is CLEAR.** BRBS is
        // `1111 00kk kkkk ksss` and BRBC is `1111 01kk kkkk ksss`, so the
        // obvious reading of the bit is the wrong way round. Inverted, the
        // blink still ran 60,000 instructions without faulting and toggled at
        // a period of 10 instead of about 800: the delay loop took its exit
        // branch on the first comparison every time. A wrong flag polarity
        // does not crash, it just runs a different program.
        const bool branch_if_set = (encoding & 0x0400) == 0;
        const uint8_t bit = encoding & 0x07;
        int8_t offset = static_cast<int8_t>((encoding >> 3) & 0x7F);
        if (offset & 0x40) {
            offset = static_cast<int8_t>(offset | 0x80);
        }
        const bool set = (cpu.sreg() & (1u << bit)) != 0;
        if (set == branch_if_set) {
            cpu.set_pc(static_cast<uint32_t>(cpu.pc() + offset));
        }
        return StepResult::Ok;
    }

    // --- sbrc / sbrs Rr, b -- 1111 110r rrrr 0bbb / 1111 111r rrrr 0bbb ---
    //
    // Skip the next instruction on a bit of a REGISTER, where `sbic`/`sbis`
    // test a bit of the IO space. Same skip rule and the same two-word trap:
    // how far to skip is a property of the instruction being skipped.
    //
    // Bit 9 chooses the polarity, so the mask is 0xFC08 and not 0xFE08 -- and
    // **bit 3 must be clear**, which is what keeps `bld` and `bst` out. They
    // share these eight bits and differ only there, so a mask that ignored it
    // would execute a bit-copy as a conditional skip.
    if ((encoding & 0xFC08) == 0xFC00) {
        const bool skip_if_set = (encoding & 0x0200) != 0;
        const uint8_t rr = (encoding >> 4) & 0x1F;
        const uint8_t bit = encoding & 0x07;
        if (((cpu.reg(rr) >> bit) & 1) == (skip_if_set ? 1u : 0u)) {
            return skip_next(cpu);
        }
        return StepResult::Ok;
    }

    // --- ldd/std Rd, Y+q and Z+q -- 10q0 qq0d dddd yqqq -------------------
    //
    // The pointer displacement forms, and the q = 0 cases are how `ld Rd, Y`
    // and `ld Rd, Z` are encoded — there is no separate encoding for them.
    // Bit 9 chooses store over load; **bit 3 chooses Y over Z**, and the
    // displacement is scattered across three fields, which is why it is
    // assembled here rather than inline.
    //
    // **The mask must not include bit 9.** It was 0xD208, which tests bit 9 as
    // part of the shape and then compares against a value with it clear -- so
    // every load matched and no store ever did, and the blink stopped on its
    // first `std`. Bit 9 is the operation, not the shape: it is read below.
    if ((encoding & 0xD000) == 0x8000) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t q = static_cast<uint8_t>(((encoding >> 8) & 0x20) |
                                               ((encoding >> 7) & 0x18) |
                                               (encoding & 0x07));
        const uint8_t pointer = (encoding & 0x0008) ? kY : kZ;
        const uint16_t address = static_cast<uint16_t>(cpu.reg_pair(pointer) + q);
        if (encoding & 0x0200) {
            if (!cpu.write_data(address, cpu.reg(rd))) {
                return StepResult::MemoryFault;
            }
        } else {
            uint8_t value = 0;
            if (!cpu.read_data(address, value)) {
                return StepResult::MemoryFault;
            }
            cpu.set_reg(rd, value);
        }
        return StepResult::Ok;
    }

    // Nothing matched. Put the PC back: an unimplemented encoding leaves the
    // machine exactly as it was, so a caller can say which word stopped it.
    cpu.set_pc(at);
    return StepResult::Unimplemented;
}

}  // namespace avr
