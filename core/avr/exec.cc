// OpenHardware — the AVR instructions a compiled blink actually uses.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Which instructions, and why these
//
// Fourteen, and the list was not chosen — it was read off the disassembly of
// `tests/avr/blink/blink.c` built by avr-gcc 7.3.0 at -Os. Every one of them
// appears in that image and nothing here does not, which is the same rule
// `webui/boards/rp2040.py` follows for registers: a thing is modelled when a
// real image reaches it.
//
// Everything else returns `Unimplemented` and leaves the machine untouched.
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
// byte alone, and the blink's `i < 100` would exit at the wrong count.
//
// **`V` on `adiw` is signed overflow of the 16-bit result**, taken from the
// old and new sign bits of the HIGH byte, not from a carry out.
//
// **`S` is always `N xor V`.** It is a derived flag and never assigned
// independently, so it is computed in one place.

#include "exec.h"

#include "cpu.h"

namespace avr {
namespace {

/// `S = N ^ V`, per the datasheet. Derived rather than stored separately.
void set_sign(Cpu& cpu) {
    cpu.set_flag(kFlagS, cpu.flag(kFlagN) != cpu.flag(kFlagV));
}

/// N, Z and S from an 8-bit result, which every logic operation sets alike.
void set_logic_flags(Cpu& cpu, uint8_t result) {
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0);
    cpu.set_flag(kFlagV, false);
    set_sign(cpu);
}

/// The flags a `cp`-family subtraction sets. `borrow_in` is the C flag for
/// `cpc` and false for `cpi`.
///
/// `carry_z` is what makes `cpc` different: it is the Z flag before the
/// operation, and Z ends up `previous && result == 0`. Passing `true` gives
/// the ordinary "Z is exactly result == 0" that `cpi` wants.
void set_compare_flags(Cpu& cpu, uint8_t left, uint8_t right, bool borrow_in,
                       bool carry_z) {
    const uint16_t wide =
        static_cast<uint16_t>(left) - right - (borrow_in ? 1u : 0u);
    const uint8_t result = static_cast<uint8_t>(wide);

    cpu.set_flag(kFlagC, (wide & 0x100) != 0);
    cpu.set_flag(kFlagN, (result & 0x80) != 0);
    // Half-carry: borrow out of bit 3.
    cpu.set_flag(kFlagH, ((~left & 0x08) & (right & 0x08)) != 0 ||
                             ((right & 0x08) & (result & 0x08)) != 0 ||
                             ((result & 0x08) & (~left & 0x08)) != 0);
    // Signed overflow: the operands differed in sign and the result took the
    // subtrahend's.
    cpu.set_flag(kFlagV, (((left ^ right) & (left ^ result)) & 0x80) != 0);
    cpu.set_flag(kFlagZ, result == 0 && carry_z);
    set_sign(cpu);
}

}  // namespace

StepResult step(Cpu& cpu) {
    const uint32_t at = cpu.pc();
    uint16_t encoding = 0;
    if (!cpu.read_program(at, encoding)) {
        return StepResult::MemoryFault;
    }

    // Advance first; a branch overwrites it. The same order core/cortexm0's
    // exec.cc uses, and for the reason recorded there: "advance only if the PC
    // changed" cannot see a branch to self, which `rjmp .-2` is.
    cpu.set_pc(at + 1);

    // --- ldi Rd, K -- 1110 KKKK dddd KKKK, d in 16..31 --------------------
    if ((encoding & 0xF000) == 0xE000) {
        const uint8_t rd = 16 + ((encoding >> 4) & 0x0F);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 4) & 0xF0) |
                                               (encoding & 0x0F));
        cpu.set_reg(rd, k);
        return StepResult::Ok;
    }

    // --- cpi Rd, K -- 0011 KKKK dddd KKKK, d in 16..31 --------------------
    if ((encoding & 0xF000) == 0x3000) {
        const uint8_t rd = 16 + ((encoding >> 4) & 0x0F);
        const uint8_t k = static_cast<uint8_t>(((encoding >> 4) & 0xF0) |
                                               (encoding & 0x0F));
        set_compare_flags(cpu, cpu.reg(rd), k, false, true);
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
        const uint16_t sp = cpu.sp();
        if (!cpu.write_data(sp, static_cast<uint8_t>(ret)) ||
            !cpu.write_data(static_cast<uint16_t>(sp - 1),
                            static_cast<uint8_t>(ret >> 8))) {
            return StepResult::MemoryFault;
        }
        cpu.set_sp(static_cast<uint16_t>(sp - 2));
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

    // --- eor Rd, Rr -- 0010 01rd dddd rrrr --------------------------------
    if ((encoding & 0xFC00) == 0x2400) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t rr = static_cast<uint8_t>(((encoding >> 5) & 0x10) |
                                                (encoding & 0x0F));
        const uint8_t result = static_cast<uint8_t>(cpu.reg(rd) ^ cpu.reg(rr));
        cpu.set_reg(rd, result);
        set_logic_flags(cpu, result);
        return StepResult::Ok;
    }

    // --- cpc Rd, Rr -- 0000 01rd dddd rrrr --------------------------------
    if ((encoding & 0xFC00) == 0x0400) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t rr = static_cast<uint8_t>(((encoding >> 5) & 0x10) |
                                                (encoding & 0x0F));
        // Z is carried in: `cpc` may only ever clear it. See the header.
        set_compare_flags(cpu, cpu.reg(rd), cpu.reg(rr), cpu.flag(kFlagC),
                          cpu.flag(kFlagZ));
        return StepResult::Ok;
    }

    // --- push Rr -- 1001 001r rrrr 1111 -----------------------------------
    if ((encoding & 0xFE0F) == 0x920F) {
        const uint8_t rr = (encoding >> 4) & 0x1F;
        const uint16_t sp = cpu.sp();
        if (!cpu.write_data(sp, cpu.reg(rr))) {
            return StepResult::MemoryFault;
        }
        cpu.set_sp(static_cast<uint16_t>(sp - 1));
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

    // --- ldd/std Rd, Y+q -- 10q0 qq0d dddd 1qqq / 10q0 qq1d dddd 1qqq -----
    //
    // The Y-pointer displacement forms. Bit 9 chooses store over load, and the
    // displacement is scattered across three fields, which is why it is
    // assembled here rather than inline.
    //
    // **The mask must not include bit 9.** It was 0xD208, which tests bit 9 as
    // part of the shape and then compares against a value with it clear -- so
    // every load matched and no store ever did, and the blink stopped on its
    // first `std`. Bit 9 is the operation, not the shape: it is read below.
    //
    // Bit 3 set selects the Y pointer. The Z-pointer forms are the same
    // encoding with it clear, and they fall through to Unimplemented rather
    // than being quietly treated as Y -- nothing here has needed Z yet.
    if ((encoding & 0xD008) == 0x8008) {
        const uint8_t rd = (encoding >> 4) & 0x1F;
        const uint8_t q = static_cast<uint8_t>(((encoding >> 8) & 0x20) |
                                               ((encoding >> 7) & 0x18) |
                                               (encoding & 0x07));
        const uint16_t address = static_cast<uint16_t>(cpu.reg_pair(kY) + q);
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
