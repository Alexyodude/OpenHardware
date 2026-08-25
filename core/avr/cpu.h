// OpenHardware — ATmega328P-class AVR state, and its two address spaces.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Harvard, and why that is the whole shape of this file
//
// `core/i8086`, `core/cortexm0` and `core/riscv32` all have ONE address space:
// an instruction and a byte of data are fetched from the same place, and a
// core needs one `read` and one `write`. An AVR does not. Program memory and
// data memory are separate spaces with overlapping addresses, so 0x0100 is a
// flash word *and* a byte of SRAM, and which one you meant depends entirely on
// the instruction asking.
//
// So this core has `program_` and `data_` and no way to confuse them, and
// **the PC indexes words rather than bytes**. `rjmp .-22` moves the PC by 11,
// not 22, and getting that wrong lands halfway through an instruction — which
// on a variable-length encoding is not a fault but a different program.
//
// ## The registers ARE data memory
//
// R0-R31 live at data addresses 0x00-0x1F. Not "are copied to" — they are the
// same storage, and `lds r0, 0x0001` reads R1. So the registers are held in
// `data_` and `reg()` is an accessor rather than a second array, because two
// arrays that must agree are two arrays that will not.
//
// The IO registers sit above them, which is why `in`/`out` take an address 32
// lower than the one a data access uses: `PORTB` is `_SFR_IO8(0x05)` to `in`
// and `out`, and 0x25 to everything else. That +0x20 is the single most likely
// off-by-something in an AVR model, so it has a named constant and a test.
//
// ## What this deliberately is not
//
// A conformance-grade core. `docs/architectures.md` records that AVR's
// candidate oracles — simavr, avr-gdb — are neither of them hardware-captured,
// so this cannot reach the standard `core/i8086` meets against SST8088 and
// must not claim to. What it can do is what the RP2040 and SAMD21 did: run a
// real compiled image and be watched doing the right thing.

#ifndef OPENHARDWARE_AVR_CPU_H
#define OPENHARDWARE_AVR_CPU_H

#include <stdint.h>

#include <vector>

namespace avr {

/// SREG bit positions, as the datasheet numbers them.
constexpr uint8_t kFlagC = 1u << 0;
constexpr uint8_t kFlagZ = 1u << 1;
constexpr uint8_t kFlagN = 1u << 2;
constexpr uint8_t kFlagV = 1u << 3;
constexpr uint8_t kFlagS = 1u << 4;
constexpr uint8_t kFlagH = 1u << 5;
constexpr uint8_t kFlagT = 1u << 6;
constexpr uint8_t kFlagI = 1u << 7;

/// Where the register file, the IO window and the stack pointer live in the
/// data space. From the ATmega328P datasheet's register summary, and matching
/// the toolchain's own `iom328p.h`.
constexpr uint16_t kRegisterBase = 0x0000;
constexpr uint16_t kIoBase = 0x0020;   //< `in`/`out` address + this = data address
constexpr uint16_t kSpl = 0x005D;
constexpr uint16_t kSph = 0x005E;
constexpr uint16_t kSreg = 0x005F;

/// The X, Y and Z pointer pairs, by their low register number.
///
/// They are ordinary registers -- r26 through r31 -- and the only thing that
/// makes them pointers is that some encodings name them implicitly. Z is the
/// one that reaches the *other* address space: `lpm` reads program memory
/// through it, by byte address.
constexpr uint8_t kX = 26;
constexpr uint8_t kY = 28;
constexpr uint8_t kZ = 30;

/// What `step` did. Same three-valued contract the other cores keep, and for
/// the same reason: an unimplemented encoding must leave the machine untouched
/// rather than behave like a no-op that a test could pass through.
enum class StepResult : int {
    Ok = 0,
    Unimplemented = 1,
    MemoryFault = 2,
};

class Cpu {
public:
    Cpu();

    void reset();

    // --- the two address spaces ------------------------------------------

    /// Give the machine `words` of program memory and `bytes` of data.
    ///
    /// Both are sized rather than mapped, because unlike the Arm cores this
    /// one models a single part family whose spaces start at zero. A board
    /// description here chooses sizes, not bases.
    void configure(uint32_t program_words, uint32_t data_bytes);

    uint32_t program_words() const { return static_cast<uint32_t>(program_.size()); }
    uint32_t data_bytes() const { return static_cast<uint32_t>(data_.size()); }

    /// One 16-bit instruction word. `address` is a WORD index, as the PC is.
    bool read_program(uint32_t address, uint16_t& out) const;
    bool write_program(uint32_t address, uint16_t value);

    bool read_data(uint16_t address, uint8_t& out) const;
    bool write_data(uint16_t address, uint8_t value);

    // --- the register file, which is the bottom of the data space ---------

    uint8_t reg(uint8_t index) const { return data_[kRegisterBase + index]; }
    void set_reg(uint8_t index, uint8_t value) { data_[kRegisterBase + index] = value; }

    /// A register pair, low byte first — the shape `adiw` and the X/Y/Z
    /// pointers use.
    uint16_t reg_pair(uint8_t low) const {
        return static_cast<uint16_t>(reg(low)) |
               static_cast<uint16_t>(reg(low + 1)) << 8;
    }
    void set_reg_pair(uint8_t low, uint16_t value) {
        set_reg(low, static_cast<uint8_t>(value));
        set_reg(low + 1, static_cast<uint8_t>(value >> 8));
    }

    uint8_t sreg() const { return data_[kSreg]; }
    void set_sreg(uint8_t value) { data_[kSreg] = value; }
    bool flag(uint8_t mask) const { return (sreg() & mask) != 0; }
    void set_flag(uint8_t mask, bool on) {
        set_sreg(on ? (sreg() | mask) : static_cast<uint8_t>(sreg() & ~mask));
    }

    uint16_t sp() const {
        return static_cast<uint16_t>(data_[kSpl]) |
               static_cast<uint16_t>(data_[kSph]) << 8;
    }
    void set_sp(uint16_t value) {
        data_[kSpl] = static_cast<uint8_t>(value);
        data_[kSph] = static_cast<uint8_t>(value >> 8);
    }

    uint32_t pc() const { return pc_; }
    void set_pc(uint32_t value) { pc_ = value; }

    /// Instructions retired. The other cores grew this for a timer; here it is
    /// the only way a test can say how far a program got.
    uint64_t executed() const { return executed_; }
    void note_executed() { ++executed_; }

    /// The address of the most recent refused access, for the message.
    uint32_t fault_address() const { return fault_address_; }
    bool fault_was_program() const { return fault_was_program_; }
    void note_fault(uint32_t address, bool program) const {
        fault_address_ = address;
        fault_was_program_ = program;
    }

private:
    std::vector<uint16_t> program_;
    std::vector<uint8_t> data_;
    uint32_t pc_ = 0;
    uint64_t executed_ = 0;

    // `mutable` because the read path is const and a fault address is a
    // diagnostic rather than state the program can see — the same reasoning
    // core/cortexm0/cpu.h gives for its own.
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_program_ = false;
};

}  // namespace avr

#endif
