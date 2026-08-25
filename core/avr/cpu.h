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

/// An 8-bit timer in the data space, and the one interrupt it raises.
///
/// ## Why this is one struct and not a general interrupt table
///
/// There is exactly one interrupt source on this part today, and
/// `.claude/CLAUDE.md`'s rule 6 says to build the concrete thing. A second
/// source is a second ticket, and splitting this then is cheaper than
/// un-generalising a table that only ever held one row.
///
/// It is also one struct rather than three calls — a counter, a flag, an
/// interrupt — because those three are one mechanism. **The flag byte is what
/// couples them**: the counter sets it on wrap and the interrupt reads it, so
/// a `map_counter` that did not own the flag could not raise anything and a
/// `map_interrupt` that did not own the counter could never be raised.
///
/// `webui/boards/rp2040.py` records the same shape from the other side. Its
/// ALARM registers are deliberately unmapped, because "modelling ALARM0-3
/// needs an IRQ to deliver, and this core has no exceptions". This is that
/// IRQ, sized to the one peripheral that needs it.
///
/// ## What it does not model
///
/// A prescaler that can be changed, the compare-match interrupts, the PWM
/// output modes, and any timer but 0. `TCCR0A` and `TCCR0B` are ordinary
/// bytes: Arduino's `init()` writes them and nothing reads them back, so the
/// *number* below is what the prescaler means here and the register is not
/// consulted. That is an approximation and it is stated rather than implied —
/// a sketch that set a different prescaler would be believed and ignored.
struct Timer {
    uint16_t counter = 0;             //< TCNT0, as a DATA address
    uint16_t flag = 0;                //< TIFR0, holding the overflow flag
    uint16_t enable = 0;              //< TIMSK0, holding the interrupt enable
    uint8_t bit = 0;                  //< TOV0 in `flag`; TOIE0 in `enable`
    uint32_t vector = 0;              //< the handler, as a WORD address
    uint32_t instructions_per_tick = 1;
};

/// A transmitter: somewhere for a program's bytes to go.
///
/// One struct and one call, for the reason `Timer` gives above -- the data
/// register, the status register and the enable are one peripheral, and a
/// mapping that owned only one of them could not answer for the others.
///
/// ## The whole model is "transmission finishes before the next instruction"
///
/// `ready_mask` is what makes that true. Arduino's `HardwareSerial::write`
/// takes a fast path when `UDRE0` is set -- it puts the byte straight in the
/// data register and returns -- and falls back to a ring buffer drained by the
/// USART_UDRE interrupt when it is clear. **Measured 2026-08-26**: with `UDRE0`
/// reading clear, a `Serial.println` sketch queued its byte, set `UDRIE0`, and
/// waited forever for an interrupt this core does not raise. With `UDRE0`
/// reading set, the byte arrives here and no USART interrupt is needed at all.
///
/// `TXC0` reads set for the same reason, and `flush()` is what needs it: it
/// spins until transmission completes, and here it already has.
///
/// So this models a UART with an infinitely fast sink. That is an
/// approximation and it is stated rather than implied: nothing here takes any
/// time, so a program timing its own output would measure zero.
///
/// ## What is not modelled
///
/// Reception. `UDR0` reads as zero and `RXC0` is not in `ready_mask`, so
/// `Serial.available()` answers false forever -- which is the truth, because
/// nothing is wired to the other end. The three USART interrupts are likewise
/// absent, and the fast path above is the reason none is needed.
struct Usart {
    uint16_t data = 0;        //< UDR0: a write is a byte of output
    uint16_t status = 0;      //< UCSR0A
    uint16_t control = 0;     //< UCSR0B, holding the transmit enable
    uint8_t enable_bit = 0;   //< TXEN0 in `control`
    uint8_t ready_mask = 0;   //< bits of `status` that always read set
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

    // --- timer 0, and the interrupt it raises -----------------------------

    /// Give this machine a timer. Call after `configure`, which resets.
    ///
    /// Returns false and maps nothing if any address is outside the sized
    /// space, the bit is not a bit, the tick is zero, or the vector is outside
    /// program memory. Checked here because the step path indexes `data_`
    /// without bounds checks and cannot afford to.
    bool map_timer(const Timer& timer);

    bool has_timer() const { return has_timer_; }
    const Timer& timer() const { return timer_; }

    /// What `TCNT0` reads: retired instructions divided by the tick, low eight
    /// bits. Computed rather than stored, so it cannot drift from `executed()`.
    uint8_t timer_count() const;

    /// True when the next step must take the vector instead of the next
    /// instruction: the overflow flag is set, the overflow interrupt is
    /// enabled, and SREG's I is set. All three, which is the ordering a
    /// program relies on when it clears I around a read of a shared counter.
    bool interrupt_pending() const;

    /// Clear the overflow flag, as the hardware does when the vector is taken.
    /// **Not the enable and not I** — those are the program's business, and
    /// `reti` is what restores I.
    void acknowledge_interrupt();

    /// `sei` and `reti` protect exactly one following instruction from an
    /// interrupt. A datasheet rule, and the one that stops a handler which
    /// re-enables early from re-entering before it has made any progress.
    void inhibit_interrupts() { inhibit_ = true; }
    bool interrupt_inhibited() const { return inhibit_; }
    void allow_interrupts() { inhibit_ = false; }

    // --- the transmitter --------------------------------------------------

    /// Give this machine a USART. Call after `configure`, which resets.
    ///
    /// Returns false and maps nothing if any address is outside the sized
    /// space or the enable bit is not a bit -- same contract as `map_timer`
    /// and for the same reason.
    bool map_usart(const Usart& usart);

    bool has_usart() const { return has_usart_; }

    /// Every byte transmitted, oldest first. Cumulative and never drained:
    /// `webui/api.py`'s `uart_view` reports what is true rather than a delta,
    /// because two browser tabs polling a delta would each consume bytes the
    /// other never saw.
    const std::vector<uint8_t>& usart_output() const { return usart_output_; }

    /// Instructions retired. The other cores grew this for a timer; here it is
    /// the only way a test can say how far a program got — and, with a timer
    /// mapped, it is also the clock.
    uint64_t executed() const { return executed_; }
    void note_executed();

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

    Timer timer_;
    bool has_timer_ = false;
    /// The counter's last value, so a wrap can be seen. `executed_` rises by
    /// one per step and the tick divides it, so at most one wrap can happen
    /// between two observations — which is why comparing the high bits is
    /// enough and no modular arithmetic is needed.
    uint64_t timer_ticks_ = 0;
    bool inhibit_ = false;

    Usart usart_;
    bool has_usart_ = false;
    std::vector<uint8_t> usart_output_;

    // `mutable` because the read path is const and a fault address is a
    // diagnostic rather than state the program can see — the same reasoning
    // core/cortexm0/cpu.h gives for its own.
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_program_ = false;
};

}  // namespace avr

#endif
