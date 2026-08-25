// OpenHardware — ATmega328P-class AVR state.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "cpu.h"

#include <algorithm>

namespace avr {

Cpu::Cpu() { reset(); }

void Cpu::reset() {
    pc_ = 0;
    executed_ = 0;
    fault_address_ = 0;
    fault_was_program_ = false;
    std::fill(data_.begin(), data_.end(), static_cast<uint8_t>(0));
    std::fill(program_.begin(), program_.end(), static_cast<uint16_t>(0xFFFF));
    // The stack pointer comes up at the top of data memory, which on this part
    // is RAMEND. avr-libc's startup code writes it again, and a bare-metal
    // image built with -nostartfiles does not -- so a model that left SP at
    // zero would push the first `push` off the bottom of the space and fault
    // on an image the silicon runs.
    if (!data_.empty()) {
        set_sp(static_cast<uint16_t>(data_.size() - 1));
    }
}

void Cpu::configure(uint32_t program_words, uint32_t data_bytes) {
    // 0xFFFF is an erased flash word AND is not a defined AVR opcode, so a
    // program that runs off the end of its image stops rather than executing
    // something plausible. The same argument core/cortexm0 makes for filling
    // flash with 0xFF, arriving here as a word rather than a byte.
    program_.assign(program_words, 0xFFFF);
    data_.assign(data_bytes, 0);
    reset();
}

bool Cpu::read_program(uint32_t address, uint16_t& out) const {
    if (address >= program_.size()) {
        note_fault(address, true);
        return false;
    }
    out = program_[address];
    return true;
}

bool Cpu::write_program(uint32_t address, uint16_t value) {
    if (address >= program_.size()) {
        note_fault(address, true);
        return false;
    }
    program_[address] = value;
    return true;
}

bool Cpu::read_data(uint16_t address, uint8_t& out) const {
    if (address >= data_.size()) {
        note_fault(address, false);
        return false;
    }
    out = data_[address];
    return true;
}

bool Cpu::write_data(uint16_t address, uint8_t value) {
    if (address >= data_.size()) {
        note_fault(address, false);
        return false;
    }
    data_[address] = value;
    return true;
}

}  // namespace avr
