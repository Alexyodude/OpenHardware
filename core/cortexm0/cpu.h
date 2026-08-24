// OpenHardware — Cortex-M0+ registers, flags and the SRAM window.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## The core owns no memory map
//
// Not one address in this file names a chip. Memory exists because a *board*
// called `add_region`, and a core with no board has no memory at all -- the
// first fetch faults, saying so.
//
// It was not always this way, and the reason it changed is worth keeping. An
// earlier version hardcoded flash at 0x10000000 and SRAM at 0x20000000 as
// `constexpr`, with a comment claiming every Armv6-M part this project targets
// puts them there. That comment was wrong: the SAMD21 -- which shares this
// very core, and which the board catalogue names as the proof that one core
// serves several boards -- puts its flash at 0x00000000. So the claim "RP2040
// and SAMD21 are both expressible over this core" was false while those
// constants existed, and no test noticed, because the tests all used an
// RP2040.
//
// **Anything outside every added region faults, and is never read as zero.**
// That deliberately includes peripheral space: firmware polls a clock's ready
// bit within its first few hundred instructions, and a zero answer spins
// forever, which looks like a hang rather than a missing feature.
//
// ## Cortex-M0+, not Cortex-M0
//
// The distinction is load-bearing and the previous handoff records why: M0 has
// no VTOR and no `CONTROL.nPRIV`, so an M0 corpus is a strict subset derivable
// from an M0+ one and never the reverse. QEMU cannot model M0+ at all -- its
// `arm_v7m_cpus[]` has m0, m3, m4, m7, m33 and m55 -- which is the reason the
// oracle here is rp2040js.
//
// Neither register is reachable from the 16-bit Thumb map, so nothing here
// depends on it yet. It is recorded because the choice of oracle already does.

#ifndef OPENHARDWARE_CORTEXM0_CPU_H
#define OPENHARDWARE_CORTEXM0_CPU_H

#include <stdint.h>

#include <array>
#include <unordered_map>
#include <vector>

namespace cortexm0 {

/// Bit positions of the flags inside APSR, as the architecture numbers them.
constexpr uint32_t kFlagN = 1u << 31;
constexpr uint32_t kFlagZ = 1u << 30;
constexpr uint32_t kFlagC = 1u << 29;
constexpr uint32_t kFlagV = 1u << 28;

/// What a write to a mapped address does to its target.
///
/// `Store` is the ordinary case. The other three exist because a peripheral
/// register that modifies another register is not a rarity to be special-cased
/// -- it is how every modern part offers an atomic bit change without a
/// read-modify-write the interrupt handler can tear.
enum class WriteOp : uint8_t { Store, Set, Clear, Xor };

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

    /// Whether an instruction may be fetched from `address`. See `add_region`.
    bool executable_at(uint32_t address) const;

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
    /// Three behaviours, and they are the three that hardware actually has.
    /// A register that clears on read, or counts, is a *modelled peripheral*
    /// rather than a mapped word, and belongs in the layer that owns the map.
    void map_register(uint32_t address, uint32_t value);

    /// An address whose write applies `op` to another address's word.
    ///
    /// This is the RP2040's atomic SET/CLR/XOR aliases, and equally STM32's
    /// BSRR: one register that modifies another rather than holding its own
    /// value. **The offsets are not here.** That +0x2000 means "set" on an
    /// RP2040 is a fact about that chip's bus; the caller passes both
    /// addresses, so this stays architecture-only.
    void map_alias(uint32_t address, uint32_t target, WriteOp op);

    /// An address whose read is derived from another's word.
    ///
    /// `RESET_DONE` on an RP2040 is `~RESET`: a block is done when its reset
    /// bit is clear. Driver code polls it in a loop, so a mirror that did not
    /// follow its source would spin forever -- the exact hang this module's
    /// fault-rather-than-zero rule exists to prevent, arriving by a different
    /// door.
    ///
    /// Writes to a mirror are inert, as hardware ignores writes to a
    /// read-only register. There is no flag for that: a mirror's write lands
    /// in its own word and its read comes from `source`, so the stored value
    /// is never read back. An explicit `read_only` branch was tried and
    /// removed -- mutation testing showed that deleting it changed no
    /// observable behaviour, which makes it a field that looks load-bearing
    /// and is not.
    void map_mirror(uint32_t address, uint32_t source, bool invert,
                    uint32_t mask = 0xFFFFFFFFu);

    bool is_mapped(uint32_t address) const;

    /// Add a readable, writable region of `size` bytes at `base`.
    ///
    /// **This is the only way memory comes to exist.** The core ships with
    /// none, so a board describes its whole map and two boards over the same
    /// core can differ -- which is what an RP2040 and a SAMD21 do, one putting
    /// flash at 0x10000000 and the other at zero.
    ///
    /// `fill` is the byte an untouched location reads. It defaults to zero,
    /// and flash should pass 0xFF: that is what erased flash reads on real
    /// parts, and it is also the loud answer, because 0xFFFF is not a valid
    /// Thumb encoding and stops the core. Zero-filled flash executes as a
    /// million `MOVS r0, r0` and looks like progress.
    ///
    /// `executable` is the field that earns this API. A stub region -- one
    /// standing in for contents this project cannot ship, like the RP2040 boot
    /// ROM -- must answer *data* reads, because firmware reads its function
    /// table and the oracle answers zero there too. But a *jump* into it would
    /// execute zeros, which decode as `MOVS r0, r0` and run quietly off the
    /// end. Marking it non-executable turns the one dangerous case loud while
    /// leaving the harmless one working.
    ///
    /// Regions added here sit alongside the built-in flash and SRAM. Those two
    /// are still hardcoded because every Armv6-M part this project targets has
    /// them at the same addresses; the moment one does not, they move out here
    /// too.
    void add_region(uint32_t base, uint32_t size, bool executable,
                    uint8_t fill = 0);

    /// Forget every region. Paired with `clear_registers` in `reset`, because
    /// a reset machine has no board.
    void clear_regions();

    /// Forget every mapped register.
    ///
    /// Separate from `clear_memory`, which clears memory *contents*. Which
    /// registers exist is configuration -- which board this is -- and a
    /// conformance run that zeroes RAM between cases must not also
    /// un-install the board.
    void clear_registers();

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
    /// Record that a *fetch* failed at `address`.
    ///
    /// Takes the address rather than only setting the flag, because the two
    /// ways a fetch can fail reach here differently: an absent address is
    /// recorded by the read that failed, but a *present but non-executable*
    /// one has no failed read to record it -- the read succeeded. Setting only
    /// the flag left that case reporting whatever address had faulted last,
    /// which for a freshly-installed board is zero. The diagnostic that exists
    /// to say which address a program wanted was naming a different one.
    void note_fetch_fault(uint32_t address) {
        fault_address_ = address;
        fault_was_fetch_ = true;
    }

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
    /// Every region there is. A vector rather than a map because there are a
    /// handful and every access scans them; a hash lookup per byte would cost
    /// more than the scan saves.
    struct Extra {
        uint32_t base;
        uint32_t size;
        bool executable;
        uint8_t fill;
        std::vector<uint8_t> bytes;
    };
    std::vector<Extra> regions_;

    // `mutable` because the read path is const and this is a diagnostic, not
    // state the program can observe. Recorded at the single choke point where
    // an address fails to resolve, so no individual read or write has to
    // remember to set it.
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_fetch_ = false;

    /// One mapped word. `target` and `source` name the address whose storage
    /// a write changes and a read derives from; for a plain register both are
    /// the address itself, which is what keeps the lookup uniform.
    struct Mapped {
        uint32_t value = 0;
        uint32_t target = 0;
        uint32_t source = 0;
        WriteOp op = WriteOp::Store;
        bool invert = false;
        uint32_t mask = 0xFFFFFFFFu;
    };

    /// Word-aligned address to behaviour. A map rather than a range, so an
    /// unmodelled register inside a modelled peripheral still faults.
    std::unordered_map<uint32_t, Mapped> mmio_;

    bool mmio_read(uint32_t address, uint32_t& out) const;
    bool mmio_write(uint32_t address, uint32_t value);
};

}  // namespace cortexm0

#endif
