// OpenHardware — Cortex-M0+ registers, flags and the SRAM window.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why there is a window rather than an address space
//
// The i8086 core owns a flat megabyte, because a megabyte is the whole space
// and fits in a malloc. Armv6-M addresses four gigabytes and this core cannot
// allocate that, so it models **one window: the RP2040's SRAM**, 264 KB at
// 0x20000000, which is where the corpus puts both the instruction under test
// (0x20001000) and its scratch words (0x20002000).
//
// Anything outside that window is reported as a fault, never read as zero.
// A silent zero would make an out-of-range fetch decode as `MOVS r0, #0` and
// execute cleanly, which is precisely the accident conformance testing exists
// to catch.
//
// **This is a deliberate limit of the current slice, not a model of the part.**
// Real firmware needs flash at 0x10000000 and peripherals at 0x40000000, and
// adding them is a change to this file rather than to anything above it.
//
// ## Cortex-M0+, not Cortex-M0
//
// The distinction is load-bearing and the previous handoff records why: M0 has
// no VTOR and no `CONTROL.nPRIV`, so an M0 corpus is a strict subset derivable
// from an M0+ one and never the reverse. QEMU cannot model M0+ at all -- its
// `arm_v7m_cpus[]` has m0, m3, m4, m7, m33 and m55 -- which is the reason the
// oracle here is rp2040js.
//
// Neither register is reachable from Thumb formats 1-4, so nothing in this
// slice depends on it yet. It is recorded now because the choice of oracle
// already depends on it.

#ifndef OPENHARDWARE_CORTEXM0_CPU_H
#define OPENHARDWARE_CORTEXM0_CPU_H

#include <stdint.h>

#include <array>
#include <unordered_map>
#include <vector>

namespace cortexm0 {

/// The modelled address space, matching the RP2040 so that both the corpus's
/// addresses and a real firmware image land where they expect to.
///
/// **Two regions, not one.** The first slice modelled SRAM alone, which was
/// enough for a corpus that puts its instruction under test at 0x20001000 and
/// nothing else. It is not enough for firmware: a Pico image is linked to
/// execute *from flash* at 0x10000000 and to keep its variables in SRAM, so a
/// core with one window faults on the first instruction it fetches.
///
/// Anything outside both regions is still a fault rather than a zero. That
/// deliberately includes the peripheral space at 0x40000000 and the
/// single-cycle IO at 0xD0000000: firmware reaches them almost immediately,
/// and a core that answered zero would spin forever in a poll for a clock
/// that never becomes ready, looking like a hang rather than a missing
/// feature. See `docs/research/peripheral-layer/` for what modelling them
/// would take.
constexpr uint32_t kFlashBase = 0x10000000u;
constexpr uint32_t kFlashSize = 2u * 1024u * 1024u;

constexpr uint32_t kSramBase = 0x20000000u;
constexpr uint32_t kSramSize = 264u * 1024u;

/// Bit positions of the flags inside APSR, as the architecture numbers them.
constexpr uint32_t kFlagN = 1u << 31;
constexpr uint32_t kFlagZ = 1u << 30;
constexpr uint32_t kFlagC = 1u << 29;
constexpr uint32_t kFlagV = 1u << 28;

/// Register numbers that mean something beyond "general purpose".
constexpr unsigned kSp = 13;
constexpr unsigned kLr = 14;
constexpr unsigned kPc = 15;

/// What `step` did, and the only way a caller learns an instruction was not
/// executed.
///
/// `Unimplemented` leaves the processor **completely untouched, PC included**,
/// the same contract the i8086 core keeps. A core that advanced past an
/// encoding it did not know would let a conformance case pass by accident
/// whenever the unwritten instruction happened to behave like a NOP.
enum class StepResult : int {
    Ok = 0,
    Unimplemented = 1,
    MemoryFault = 2,
};

class Cpu {
public:
    Cpu();

    void reset();

    uint32_t reg(unsigned index) const { return regs_[index]; }
    void set_reg(unsigned index, uint32_t value) { regs_[index] = value; }

    uint32_t apsr() const { return apsr_; }
    void set_apsr(uint32_t value) {
        // Only NZCV are modelled, so the rest is dropped rather than stored.
        // Keeping unmodelled bits would let them round-trip through get/set
        // and look supported.
        apsr_ = value & (kFlagN | kFlagZ | kFlagC | kFlagV);
    }

    bool n() const { return (apsr_ & kFlagN) != 0; }
    bool z() const { return (apsr_ & kFlagZ) != 0; }
    bool c() const { return (apsr_ & kFlagC) != 0; }
    bool v() const { return (apsr_ & kFlagV) != 0; }

    void set_n(bool on) { set_flag(kFlagN, on); }
    void set_z(bool on) { set_flag(kFlagZ, on); }
    void set_c(bool on) { set_flag(kFlagC, on); }
    void set_v(bool on) { set_flag(kFlagV, on); }

    /// N and Z from a result, which every flag-setting instruction here does
    /// identically. C and V are the ones that differ, so they are never
    /// touched by this.
    void set_nz(uint32_t result) {
        set_n((result & 0x80000000u) != 0);
        set_z(result == 0);
    }

    bool in_range(uint32_t address, uint32_t bytes) const;

    /// False on a fault, having read or written nothing. The caller turns that
    /// into `StepResult::MemoryFault`.
    bool read_word(uint32_t address, uint32_t& out) const;
    bool write_word(uint32_t address, uint32_t value);
    bool read_halfword(uint32_t address, uint16_t& out) const;
    bool write_halfword(uint32_t address, uint16_t value);
    bool read_byte_checked(uint32_t address, uint8_t& out) const;
    bool write_byte_checked(uint32_t address, uint8_t value);

    /// Byte access for bulk transfer. Unchecked on purpose: the only callers
    /// are the ABI's block functions, which range-check the whole span first
    /// so that a block overrunning a region writes none of it rather than half
    /// of it. Checking again per byte would make a partial write the failure
    /// mode instead.
    uint8_t read_byte(uint32_t address) const;
    void write_byte(uint32_t address, uint8_t value);

    void clear_memory();

    /// Make one word of memory-mapped IO respond, at `address`.
    ///
    /// **The mechanism is here; the map is not.** Which addresses an RP2040
    /// calls SIO or RESETS is a fact about a board, and this directory is the
    /// architecture. A caller registers the registers it wants modelled, so
    /// `core/cortexm0` never learns a chip's memory map.
    ///
    /// **Only registered addresses respond. Everything else still faults**,
    /// and that is the whole point. A peripheral window that read as zero
    /// would turn every "wait until this clock is ready" poll into an infinite
    /// loop -- firmware that hangs rather than firmware that says what is
    /// missing. `docs/research/peripheral-layer/design.md` calls this out as
    /// the failure mode that wastes the most time.
    ///
    /// Reads-as-written is the only behaviour offered. A register that clears
    /// on read, follows another bit, or counts is a *modelled peripheral*, not
    /// a mapped word, and belongs in the layer that owns the map.
    void map_register(uint32_t address, uint32_t value);
    bool is_mapped(uint32_t address) const;

    /// The address of the most recent failed access, and whether it was an
    /// instruction fetch.
    ///
    /// Diagnostics, not architecture -- a real part raises a HardFault and
    /// this core has no exceptions yet. It exists because "MemoryFault" alone
    /// is nearly useless when bringing up firmware: the address is what says
    /// *which peripheral is missing*, and 0xD0000000 versus 0x40034000 is the
    /// difference between SIO and a UART.
    uint32_t fault_address() const { return fault_address_; }
    bool fault_was_fetch() const { return fault_was_fetch_; }
    void note_fetch_fault() { fault_was_fetch_ = true; }

private:
    void set_flag(uint32_t mask, bool on) {
        apsr_ = on ? (apsr_ | mask) : (apsr_ & ~mask);
    }

    /// The region a given address falls in, or nullptr. One lookup used by
    /// every access, so the map is stated once rather than repeated in each
    /// read and write.
    const std::vector<uint8_t>* region_for(uint32_t address, uint32_t bytes,
                                           uint32_t& offset) const;
    std::vector<uint8_t>* region_for(uint32_t address, uint32_t bytes,
                                     uint32_t& offset);

    std::array<uint32_t, 16> regs_{};
    uint32_t apsr_ = 0;
    std::vector<uint8_t> flash_;
    std::vector<uint8_t> sram_;

    // `mutable` because the read path is const and this is a diagnostic, not
    // state the program can observe. Recorded at the single choke point where
    // an address fails to resolve, so no individual read or write has to
    // remember to set it.
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_fetch_ = false;

    /// Word-aligned address to value. A map rather than a range, so an
    /// unmodelled register inside a modelled peripheral still faults.
    std::unordered_map<uint32_t, uint32_t> mmio_;
};

}  // namespace cortexm0

#endif
