// OpenHardware — how long an 8088 instruction can possibly take.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "timing.h"

namespace i8086 {

std::uint32_t MinimumCycles(std::uint8_t length, std::uint8_t queued) {
    const std::uint8_t held = queued < kQueueBytes ? queued : kQueueBytes;
    const std::uint8_t fetch = length > held
                                   ? static_cast<std::uint8_t>(length - held)
                                   : 0;
    return static_cast<std::uint32_t>(fetch) * kClocksPerBusCycle;
}

namespace {

/// One row of Intel's Table 2-21: its `Clocks` and its `Bytes`.
struct Row {
    std::uint8_t clocks;
    std::uint8_t length;
};

constexpr Row kNoClaim = {0, 0};

/// Each return cites its row; pages are of the 9800722-03 manual.
Row Lookup(std::uint8_t opcode, std::uint8_t modrm) {
    const bool reg_form = (modrm >> 6) == 3;
    const std::uint8_t reg = (modrm >> 3) & 7;

    // ADD OR ADC SBB AND SUB XOR CMP, pp. 2-52 to 2-68. The low three bits
    // pick the form; 6 and 7 in this block are segment pushes, prefixes and
    // the BCD adjusts, handled below or not at all.
    if (opcode < 0x40 && (opcode & 7) < 6) {
        switch (opcode & 7) {
            case 4: return {4, 2};                                // accumulator, immediate
            case 5: return {4, 3};
            default: return reg_form ? Row{3, 2} : kNoClaim;      // register, register
        }
    }
    if (opcode >= 0x40 && opcode <= 0x4F) return {2, 1};          // INC/DEC reg16, pp. 2-54, 2-55
    if (opcode >= 0x90 && opcode <= 0x97) return {3, 1};          // XCHG reg16, AX, p. 2-67; NOP, p. 2-62
    if (opcode >= 0xB0 && opcode <= 0xB7) return {4, 2};          // MOV register, immediate, p. 2-61
    if (opcode >= 0xB8 && opcode <= 0xBF) return {4, 3};
    if (opcode >= 0xD8 && opcode <= 0xDF) {                       // ESC immediate, register, p. 2-54
        return reg_form ? Row{2, 2} : kNoClaim;
    }

    switch (opcode) {
        case 0x27:                                                // DAA, p. 2-54
        case 0x2F: return {4, 1};                                 // DAS, p. 2-54
        case 0x80: return reg_form ? Row{4, 3} : kNoClaim;        // register, immediate
        case 0x81: return reg_form ? Row{4, 4} : kNoClaim;
        case 0x83: {
            // Table 4-13: /1, /4 and /6 are "not used".
            const bool used = reg != 1 && reg != 4 && reg != 6;
            return reg_form && used ? Row{4, 3} : kNoClaim;
        }
        case 0x84:                                                // TEST register, register, p. 2-67
        case 0x85: return reg_form ? Row{3, 2} : kNoClaim;
        case 0x86:                                                // XCHG register, register, p. 2-67
        case 0x87: return reg_form ? Row{4, 2} : kNoClaim;
        case 0x88: case 0x89: case 0x8A: case 0x8B:               // MOV register, register, p. 2-61
            return reg_form ? Row{2, 2} : kNoClaim;
        case 0x8C:                                                // MOV reg16, seg-reg, p. 2-61
            return reg_form && reg < 4 ? Row{2, 2} : kNoClaim;
        case 0x8E:                                                // MOV seg-reg, reg16; not CS
            return reg_form && reg < 4 && reg != 1 ? Row{2, 2} : kNoClaim;
        case 0x98: return {2, 1};                                 // CBW, p. 2-52
        case 0x9E: return {4, 1};                                 // SAHF, p. 2-64
        case 0xA8: return {4, 2};                                 // TEST accumulator, immediate, p. 2-67
        case 0xA9: return {4, 3};
        case 0xD0:                                                // shifts and rotates register, 1
        case 0xD1: return reg_form && reg != 6 ? Row{2, 2} : kNoClaim;   // pp. 2-63 to 2-66
        case 0xF5:                                                // CMC, p. 2-53
        case 0xF8: case 0xF9: case 0xFA: case 0xFB:               // CLC STC CLI STI
        case 0xFC: case 0xFD: return {2, 1};                      // CLD STD, pp. 2-53, 2-66
        case 0xF6:
        case 0xF7:
            if (!reg_form) return kNoClaim;
            if (reg == 0) return {5, static_cast<std::uint8_t>(opcode == 0xF6 ? 3 : 4)};  // TEST register, immediate
            if (reg == 2 || reg == 3) return {3, 2};              // NOT, NEG register, p. 2-62
            return kNoClaim;
        case 0xFE:                                                // INC/DEC reg8, pp. 2-54, 2-55
            return reg_form && reg < 2 ? Row{3, 2} : kNoClaim;
        default: return kNoClaim;
    }
}

}  // namespace

std::uint8_t RegisterFormClocks(std::uint8_t opcode, std::uint8_t modrm) {
    return Lookup(opcode, modrm).clocks;
}

std::uint32_t RegisterFormCycles(const std::uint8_t* bytes, std::uint8_t length,
                                 std::uint8_t queued) {
    if (bytes == nullptr || length == 0) {
        return 0;
    }
    const Row row = Lookup(bytes[0], length > 1 ? bytes[1] : 0);
    if (row.clocks == 0 || row.length != length) {
        return 0;
    }
    const std::uint8_t held = queued < kQueueBytes ? queued : kQueueBytes;
    if (held == 0) {
        const std::uint32_t bus = MinimumCycles(length, 0);
        return row.clocks > bus ? row.clocks : bus;
    }
    if (held > length) {
        return row.clocks;
    }
    return 0;
}

}  // namespace i8086
