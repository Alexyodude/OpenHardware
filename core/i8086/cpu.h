// OpenHardware - Intel 8086/8088 processor state.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// State and memory only. Decode belongs to OH-2 and execution to OH-3; this
// slice exists to prove the build and the ABI before any of that is written.
//
// The register set and its member order are taken from the SST8088 corpus
// (`tests/fixtures/sst8088/*.json`), not from a manual, because that corpus is
// the oracle every later slice is checked against. A case reads:
//
//     "regs": { "ax":22348, "bx":20994, ..., "ip":37865, "flags":64646 }
//
// Matching that shape here means the conformance harness in OH-6 can fill the
// struct field by field with no translation layer to get wrong.

#ifndef OPENHARDWARE_I8086_CPU_H
#define OPENHARDWARE_I8086_CPU_H

#include <cstdint>
#include <vector>

namespace i8086 {

/// 1 MB. The 8086 drives 20 address lines, so this is the whole space.
inline constexpr std::uint32_t kMemorySize = 1u << 20;

/// Physical address from a segment:offset pair.
///
/// The `& 0xFFFFF` is load-bearing rather than defensive. `0xFFFF:0xFFFF`
/// computes to 0x10FFEF, which is past the top of the address space, and a
/// real 8086 has no 21st address line to carry it -- so it wraps to 0x0FFEF.
/// Later parts do not wrap, which is where the A20 gate came from. Getting
/// this wrong is invisible until a test lands near the top of memory.
inline constexpr std::uint32_t Physical(std::uint16_t segment, std::uint16_t offset) {
    return ((static_cast<std::uint32_t>(segment) << 4) + offset) & 0xFFFFFu;
}

/// Bit positions in FLAGS.
enum Flag : std::uint16_t {
    kCarry = 1u << 0,
    kParity = 1u << 2,
    kAuxCarry = 1u << 4,
    kZero = 1u << 6,
    kSign = 1u << 7,
    kTrap = 1u << 8,
    kInterrupt = 1u << 9,
    kDirection = 1u << 10,
    kOverflow = 1u << 11,
};

/// Bits 1 and 12-15 read as 1 on an 8086/8088 and cannot be cleared.
///
/// Confirmed against the corpus rather than assumed: every `flags` value in
/// `tests/fixtures/sst8088/` has them set -- 64646 is 0xFC86, whose top nibble
/// is 0xF and whose bit 1 is set. A core that lets them clear disagrees with
/// hardware on the first case it runs.
inline constexpr std::uint16_t kFlagsAlwaysSet = 0xF002u;

/// Registers, in the corpus's own order.
struct Registers {
    std::uint16_t ax = 0, bx = 0, cx = 0, dx = 0;
    std::uint16_t si = 0, di = 0, bp = 0, sp = 0;
    std::uint16_t cs = 0, ds = 0, es = 0, ss = 0;
    std::uint16_t ip = 0;
    std::uint16_t flags = 0;
};

class Cpu {
  public:
    Cpu();

    /// Power-on state: CS:IP at 0xFFFF:0000, everything else clear.
    ///
    /// Memory is **not** cleared. Reset on real hardware does not touch DRAM,
    /// and a conformance case sets memory before reset in some orderings --
    /// zeroing here would quietly discard it.
    void Reset();

    const Registers& regs() const { return regs_; }
    Registers& regs() { return regs_; }

    /// Assign registers, forcing the bits hardware holds high.
    void set_regs(const Registers& value);

    std::uint8_t ReadByte(std::uint32_t address) const;
    void WriteByte(std::uint32_t address, std::uint8_t value);

    /// Little-endian, and wrapping at the top of the space like the address
    /// adder does -- a word read at 0xFFFFF takes its high byte from 0x00000.
    std::uint16_t ReadWord(std::uint32_t address) const;
    void WriteWord(std::uint32_t address, std::uint16_t value);

    void ClearMemory();

  private:
    Registers regs_;
    std::vector<std::uint8_t> memory_;
};

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_CPU_H
