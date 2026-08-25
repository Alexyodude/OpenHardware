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
    timer_ticks_ = 0;
    inhibit_ = false;
    // A reset is a new run of the program, so what the last one printed is not
    // this one's output. The MAPPING survives -- a board wires the peripheral
    // once -- but the bytes do not.
    usart_output_.clear();
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
    // The counter is computed, never stored. One compare on the read path,
    // which is the cost of a register that answers something other than what
    // was last written to it.
    if (has_timer_ && address == timer_.counter) {
        out = timer_count();
        return true;
    }
    if (has_usart_) {
        // The status register reads back what was written, plus the bits that
        // are always true of a transmitter that has already finished. Storing
        // them instead would not survive `HardwareSerial::write`, which writes
        // the register back with only U2X0 and TXC0 preserved -- and would
        // therefore clear UDRE0 and drop the program into the interrupt path.
        if (address == usart_.status) {
            out = static_cast<uint8_t>(data_[address] | usart_.ready_mask);
            return true;
        }
        // Nothing is wired to the receiver, so there is nothing to read.
        if (address == usart_.data) {
            out = 0;
            return true;
        }
    }
    if (address >= data_.size()) {
        note_fault(address, false);
        return false;
    }
    out = data_[address];
    return true;
}

bool Cpu::write_data(uint16_t address, uint8_t value) {
    // **A write to the counter is refused, and the silicon allows it.**
    //
    // Deliberate. This model has nowhere to put the value: the count is
    // derived from `executed()`, so accepting a write would mean either
    // ignoring it or carrying an origin nothing has asked for. Ignoring it is
    // the load-and-report-success failure this repository ranks worst -- a
    // program that reset TCNT0 to zero would read back an unrelated number and
    // conclude its own arithmetic was wrong.
    //
    // Nothing in `framework-arduino-avr` writes TCNT0; `analogWrite` touches
    // OCR0A and OCR0B, and `Tone` uses timer 2. The day something does, this
    // faults and names the address, which is the loud answer.
    if (has_timer_ && address == timer_.counter) {
        note_fault(address, false);
        return false;
    }
    // **The flag register is write-one-to-clear.** Not a quirk of this model:
    // the datasheet says TOV0 "is cleared by writing a logic one to the flag",
    // and every AVR interrupt flag register works that way. A model that
    // stored the byte would let a program *set* a pending interrupt by writing
    // the bit it meant to acknowledge -- the exact inversion, and one that
    // would show up as a handler that fires forever.
    if (has_timer_ && address == timer_.flag) {
        data_[address] &= static_cast<uint8_t>(~value);
        return true;
    }
    // A write to the data register is a byte transmitted -- **but only while
    // the transmitter is enabled.** A write made before `Serial.begin()` is
    // discarded, which is what the silicon does and what
    // `webui/boards/rp2040.py` already models for its own UART: "the emulated
    // data register discards writes made while UARTEN is clear". Buffering
    // them instead would make a missing `begin()` invisible, and a missing
    // `begin()` is the commonest mistake there is in an Arduino sketch.
    if (has_usart_ && address == usart_.data) {
        if (data_[usart_.control] & (1u << usart_.enable_bit)) {
            usart_output_.push_back(value);
        }
        return true;
    }
    if (address >= data_.size()) {
        note_fault(address, false);
        return false;
    }
    data_[address] = value;
    return true;
}

// --- timer 0 -----------------------------------------------------------------

bool Cpu::map_timer(const Timer& timer) {
    // `note_executed` and `interrupt_pending` index `data_` without bounds
    // checks -- they run on every step and a check there would be paid a
    // hundred million times to catch a mistake that can only be made once.
    // So it is caught once, here, and refused rather than trusted.
    const uint32_t size = static_cast<uint32_t>(data_.size());
    if (timer.counter >= size || timer.flag >= size || timer.enable >= size ||
        timer.bit > 7 || timer.instructions_per_tick == 0 ||
        timer.vector >= program_.size()) {
        return false;
    }
    timer_ = timer;
    has_timer_ = true;
    timer_ticks_ = 0;
    return true;
}

uint8_t Cpu::timer_count() const {
    return static_cast<uint8_t>(executed_ / timer_.instructions_per_tick);
}

void Cpu::note_executed() {
    ++executed_;
    if (!has_timer_) {
        return;
    }
    // The overflow flag is set **whether or not the interrupt is enabled**,
    // because that is what makes `micros()` correct: it reads the flag
    // directly to notice an overflow that has happened but not yet been
    // serviced, and adds one to the count itself.
    const uint64_t now = executed_ / timer_.instructions_per_tick;
    if ((now >> 8) != (timer_ticks_ >> 8)) {
        data_[timer_.flag] |= static_cast<uint8_t>(1u << timer_.bit);
    }
    timer_ticks_ = now;
}

bool Cpu::interrupt_pending() const {
    if (!has_timer_ || !flag(kFlagI)) {
        return false;
    }
    const uint8_t mask = static_cast<uint8_t>(1u << timer_.bit);
    return (data_[timer_.enable] & mask) != 0 && (data_[timer_.flag] & mask) != 0;
}

void Cpu::acknowledge_interrupt() {
    data_[timer_.flag] &= static_cast<uint8_t>(~(1u << timer_.bit));
}

// --- the transmitter ---------------------------------------------------------

bool Cpu::map_usart(const Usart& usart) {
    // Checked once here rather than on every access, the same trade `map_timer`
    // makes: `write_data` indexes `data_[usart_.control]` without a bounds
    // check and is on the path of every store a program makes.
    const uint32_t size = static_cast<uint32_t>(data_.size());
    if (usart.data >= size || usart.status >= size || usart.control >= size ||
        usart.enable_bit > 7) {
        return false;
    }
    usart_ = usart;
    has_usart_ = true;
    usart_output_.clear();
    return true;
}

}  // namespace avr
