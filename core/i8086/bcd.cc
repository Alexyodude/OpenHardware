// OpenHardware - the 8086 decimal adjust and ASCII adjust instructions.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## One correction, computed then applied
//
// Every textbook writes DAA as two conditional additions: add 6 if the low
// digit is invalid, then add 0x60 if the high one is. This works out a single
// correction -- 0, 6, 0x60 or 0x66 -- and applies it once. Every flag comes
// from that one operation.
//
// **The corpus cannot tell the two apart, and this comment previously claimed
// it could.** The claim was that two additions get OF wrong 2.5% of the time
// where one gets it right. That measurement was real but misattributed: the
// sample had been selected with the wrong high-correction predicate (see
// below), so the cases it disagreed on were ones where hardware applied a
// different correction entirely. Re-run over all 512 (AL, AF) pairs, one
// addition of 0x66 and two of 6 and 0x60 produce identical OF **every time**,
// and identical AL, SF, ZF and PF by construction.
//
// So the single-correction form is chosen because it is simpler, not because
// it is more faithful. Recorded rather than quietly fixed, because a comment
// citing a number is exactly the kind that gets believed.
//
// ## Where the evidence actually is
//
// AAA and AAS are the same shape with a correction of 6 or 0, and their
// "undefined" SF, ZF, PF and OF are simply that operation's. Modelling the
// correction as *conditional* rather than as *sometimes zero* is what loses
// them -- 6% against 100% -- because with no adjustment due the part still
// runs the ALU with an operand of zero, and the flags say so.
//
// AAD is the same idea once more: it ends in a plain 8-bit ADD, so it is
// routed through Alu() below and its three undefined flags come out right.

#include "bcd.h"

#include "alu.h"

namespace i8086 {
namespace {

constexpr std::uint8_t Low(std::uint16_t ax) { return static_cast<std::uint8_t>(ax & 0xFF); }
constexpr std::uint8_t High(std::uint16_t ax) { return static_cast<std::uint8_t>(ax >> 8); }
constexpr std::uint16_t Join(std::uint8_t high, std::uint8_t low) {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(high) << 8) | low);
}

}  // namespace

BcdResult Bcd(BcdKind kind, std::uint16_t ax, std::uint8_t immediate,
              std::uint16_t& flags) {
    const std::uint8_t old_al = Low(ax);
    const bool old_carry = HasFlag(flags, kCarry);
    const bool old_aux = HasFlag(flags, kAuxCarry);
    // "The low digit is not a digit, or the last operation carried out of it."
    // Both halves matter: 0x0A needs correcting because it is not a decimal
    // digit, and 0x03 needs it when AF says a carry already took ten away.
    const bool low_invalid = (old_al & 0x0F) > 9 || old_aux;

    switch (kind) {
        case BcdKind::kDaa:
        case BcdKind::kDas: {
            const bool subtract = kind == BcdKind::kDas;

            // The high correction's threshold is 0x99 -- **except when AF
            // arrived set, where it is 0x9F.**
            //
            // Derived, not read anywhere: the correction hardware applied was
            // recovered from every case as `final AL - initial AL`, and
            // tabulated against AL's high nibble and AF. At a high nibble of
            // 9 the two columns disagree and nothing else does. AL=0x9E with
            // AF set corrects by 6 and stays 0xA4; the same AL with AF clear
            // corrects by 0x66. Every published version of this algorithm
            // gets those 64 cases wrong, in one direction or the other,
            // because none of them has AF in this test at all.
            //
            // DAA and DAS produce byte-identical correction tables.
            const bool high_invalid =
                old_carry || old_al > (old_aux ? 0x9F : 0x99);

            const std::uint16_t correction =
                static_cast<std::uint16_t>((low_invalid ? 0x06 : 0x00) +
                                           (high_invalid ? 0x60 : 0x00));

            // Through Alu so SF, ZF, PF and OF are the same code path the
            // arithmetic opcodes already pin. CF and AF are then overwritten:
            // this is a correction, not an addition, and what they report here
            // is which correction ran. CF = high_invalid is exact over 20,000
            // cases; "high_invalid, or a borrow out of the low correction",
            // which is how the manual words it, is wrong on 60 DAS cases.
            const std::uint16_t result =
                Alu(subtract ? AluKind::kSub : AluKind::kAdd, old_al, correction, false, flags);
            SetFlag(flags, kCarry, high_invalid);
            SetFlag(flags, kAuxCarry, low_invalid);
            return {Join(High(ax), static_cast<std::uint8_t>(result)), false};
        }

        case BcdKind::kAaa:
        case BcdKind::kAas: {
            const bool subtract = kind == BcdKind::kAas;
            // Zero when no adjustment is due, rather than skipping the
            // operation. The part runs the ALU either way, and the flags it
            // leaves are the difference between 100% and 6%.
            const std::uint16_t correction = low_invalid ? 0x06 : 0x00;
            const std::uint16_t result =
                Alu(subtract ? AluKind::kSub : AluKind::kAdd, old_al, correction, false, flags);
            SetFlag(flags, kCarry, low_invalid);
            SetFlag(flags, kAuxCarry, low_invalid);

            std::uint8_t ah = High(ax);
            if (low_invalid) {
                // A separate byte operation on AH, not a carry out of AL.
                // A 16-bit AX +/- 0x106 would move AH by two whenever AL
                // wrapped.
                ah = static_cast<std::uint8_t>(subtract ? ah - 1 : ah + 1);
            }
            // AL keeps only the digit -- but the flags above came from the
            // value before this mask, which is why SF can be set on a result
            // that is stored as 0x0F or less.
            return {Join(ah, static_cast<std::uint8_t>(result & 0x0F)), false};
        }

        case BcdKind::kAam: {
            if (immediate == 0) {
                // Measured over the 47 zero-divisor cases in D4: AX is
                // unchanged and the flags come out identical every time --
                // CF, AF and OF clear, ZF set, SF clear, PF set. That is
                // exactly SetResultFlags(0). The microcode zeroes its
                // quotient register and sets flags from it, then notices it
                // can never finish.
                SetFlag(flags, kCarry, false);
                SetFlag(flags, kOverflow, false);
                SetFlag(flags, kAuxCarry, false);
                SetResultFlags(0, false, flags);
                return {ax, true};
            }
            const std::uint8_t quotient = static_cast<std::uint8_t>(old_al / immediate);
            const std::uint8_t remainder = static_cast<std::uint8_t>(old_al % immediate);
            SetFlag(flags, kCarry, false);
            SetFlag(flags, kOverflow, false);
            SetFlag(flags, kAuxCarry, false);
            // From the remainder, which is what lands in AL.
            SetResultFlags(remainder, false, flags);
            return {Join(quotient, remainder), false};
        }

        case BcdKind::kAad: {
            // AAD ends in a plain 8-bit ADD, so every flag is that ADD's --
            // including CF, AF and OF, all three of which the manual calls
            // undefined. Routed through Alu rather than reimplemented.
            //
            // No trap here at any immediate: AAD multiplies, and a zero
            // multiplier is simply zero.
            const std::uint8_t tens = static_cast<std::uint8_t>(High(ax) * immediate);
            const std::uint16_t result = Alu(AluKind::kAdd, tens, old_al, false, flags);
            return {Join(0, static_cast<std::uint8_t>(result)), false};
        }
    }

    return {ax, false};
}

}  // namespace i8086
