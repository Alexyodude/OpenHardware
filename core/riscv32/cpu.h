// OpenHardware — RV32 registers, and whatever memory a board gives it.
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
// This is not a preference, it is a lesson already paid for: commit cd9f8c8
// took hardcoded flash and SRAM addresses back out of the Cortex-M0 core after
// they turned out to be wrong for the SAMD21, which shares that core. The trap
// is wider here. The seven RV32 boards are three different parts, and the C3,
// C5 and C6 do not agree on where anything is -- the C3 alone puts its flash
// execute window at 0x42000000 and its rodata window at 0x3C000000. A constant
// here would be wrong for two parts out of three on the day it was written.
//
// **Anything outside every added region faults, and is never read as zero.**
// That deliberately includes peripheral space: firmware polls a clock or reset
// status bit within its first few hundred instructions, and a zero answer
// spins forever, which reads as a hang rather than as a missing feature.
//
// ## What the core does know: which extensions the part has
//
// That is architecture rather than a memory map, and it has to live here
// because it is the one thing this core must get right that its oracle cannot
// check. rvcpp executes every extension unconditionally, so lockstep against
// it cannot tell an RV32IMC part from an RV32IMAC one -- see OH-35, and
// docs/architectures.md 2.1b, which measured that hole rather than inferring
// it. The ESP32-C3 is RV32IMC and must trap an atomic; the C6 is RV32IMAC and
// must execute it. A core with no `Extension` mask would have to pick one and
// be silently wrong for the other family.
//
// Nothing is enabled by default. A core that arrived believing it had M and C
// would be making a claim about a part before any board had said which part.

#ifndef OPENHARDWARE_RISCV32_CPU_H
#define OPENHARDWARE_RISCV32_CPU_H

#include <stdint.h>

#include <array>
#include <vector>

namespace riscv32 {

/// x0 through x31. x0 reads as zero and discards every write.
constexpr unsigned kRegisters = 32;

/// The optional extensions this core can be told a part has. RV32I is the
/// base and is always present, so it has no bit.
///
/// One bit per extension this core can be *told about*, which is not the same
/// as one bit per extension it implements. `kExtM` and `kExtA` are classified
/// and then refused; `kExtZba` is implemented. Both need a bit, because the
/// question a bit answers is "does this part have it", and that has to be
/// answerable before the encoding is written or every instruction added later
/// inherits the wrong default.
///
/// **`kExtC` is not Zca, and the difference is not academic.** The RP2350's
/// ISA string is `..._zca_zcb_zcmp` with no plain `c`. On an RV32 part with no
/// F and no D the two describe the same set of legal encodings, because `C` is
/// exactly `Zca` plus `Zcf` (needs F) plus `Zcd` (needs D). Neither the
/// RP2350 nor any ESP32-C part has an FPU, so reusing `kExtC` for them happens
/// to give the right answers today -- by a coincidence about those parts, not
/// because the names mean the same thing. A separate `kExtZca` belongs here
/// before any part with an FPU arrives, and `tests/rv32/corpus/
/// absent_extension.json` already holds the encodings that would separate them.
///
/// Zbb, Zbs, Zbkb, Zcb and Zcmp are still absent: the RP2350 has them and this
/// core does not implement them yet, which `tests/rv32/conftest.py` records as
/// a gap in `MODELLED` rather than by pretending the part lacks them.
enum Extension : uint32_t {
    kExtM = 1u << 0,
    kExtA = 1u << 1,
    kExtC = 1u << 2,
    kExtZba = 1u << 3,
};

/// What `step` did.
///
/// Four outcomes rather than three, and the fourth is the one this core exists
/// to get right.
///
///  * `Unimplemented` is a hole in *this emulator*: an encoding the part would
///    execute and nobody here has written yet.
///  * `Illegal` is a fact about the *architecture*: an encoding this part must
///    refuse, because the extension it belongs to is not enabled.
///
/// Collapsing them would destroy the only distinction separating an ESP32-C3
/// from an ESP32-C6, and it would do it quietly. "We do not implement atomics
/// yet" and "this part traps atomics" produce the same stopped core and mean
/// opposite things about whether the model is finished.
///
/// Both leave the processor **completely untouched, PC included**, which is
/// the contract the i8086 and Cortex-M0 cores keep. A core that advanced past
/// an encoding it did not know would let a conformance case pass by accident
/// whenever the unwritten instruction happened to behave like a NOP.
enum class StepResult : int {
    Ok = 0,
    Unimplemented = 1,
    MemoryFault = 2,
    Illegal = 3,
};

class Cpu {
public:
    Cpu();

    /// Zero every register, forget every region, and disable every extension.
    /// A reset machine has no board, so it has no memory and no ISA beyond the
    /// base -- both are things a board supplies.
    void reset();

    uint32_t reg(unsigned index) const {
        return index < kRegisters ? x_[index] : 0;
    }

    /// x0 is hardwired to zero in the architecture, so a write to it is
    /// discarded here rather than at each of the dozen call sites that can
    /// name it as a destination. `add x0, x1, x2` is a legal instruction whose
    /// entire effect is nothing, and every RISC-V program contains some.
    void set_reg(unsigned index, uint32_t value) {
        if (index == 0 || index >= kRegisters) {
            return;
        }
        x_[index] = value;
    }

    uint32_t pc() const { return pc_; }
    void set_pc(uint32_t value) { pc_ = value; }

    uint32_t extensions() const { return extensions_; }
    void set_extensions(uint32_t mask) { extensions_ = mask; }
    bool has(Extension extension) const { return (extensions_ & extension) != 0; }

    /// How far apart instructions may legally start.
    ///
    /// Four without C, two with it. A jump to a target that does not satisfy
    /// this is an instruction-address-misaligned trap on real silicon, and the
    /// requirement genuinely changes with the extension -- which is why it is
    /// derived rather than a constant.
    uint32_t instruction_alignment() const { return has(kExtC) ? 2u : 4u; }

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
    /// are the ABI block functions, which range-check the whole span first, so
    /// a block overrunning a region writes none of it rather than half of it.
    /// Checking again per byte would make a partial write the failure mode
    /// instead.
    uint8_t read_byte(uint32_t address) const;
    void write_byte(uint32_t address, uint8_t value);

    void clear_memory();

    /// Add a readable, writable region of `size` bytes at `base`.
    ///
    /// **This is the only way memory comes to exist.** The core ships with
    /// none, so a board describes its whole map, and two boards over this same
    /// core can differ completely -- which the C3 and C6 do.
    ///
    /// `fill` is the byte an untouched location reads. Zero by default; flash
    /// should pass 0xFF, which is what erased flash reads on real parts. On
    /// RV32 both fills are loud, which is a mercy the Thumb cores do not get:
    /// a word of 0x00000000 and a word of 0xFFFFFFFF are both illegal
    /// encodings, so a program that runs off the end stops either way.
    ///
    /// `executable` false makes a fetch fault while data reads still answer:
    /// what a stub standing in for contents this project cannot ship needs.
    /// An ESP32 mask ROM is exactly that -- firmware reads its function table,
    /// and a jump into a table of zeros would fault at the wrong address and
    /// send the reader looking for a decoder bug.
    ///
    /// False when it overlaps a region already added, having added nothing.
    bool add_region(uint32_t base, uint32_t size, bool executable,
                    uint8_t fill = 0);

    /// Forget every region. A reset machine has no board.
    void clear_regions();

    /// The address of the most recent failed access, and whether it was a
    /// fetch.
    ///
    /// Diagnostics, not architecture -- this core has no traps yet, so it
    /// stops where hardware would vector. It exists because "MemoryFault"
    /// alone is nearly useless when bringing firmware up: the address is what
    /// says *which peripheral is missing*, and on a C3 the difference between
    /// 0x3FF00000 and 0x60000000 is the difference between two subsystems.
    uint32_t fault_address() const { return fault_address_; }
    bool fault_was_fetch() const { return fault_was_fetch_; }

    /// Record that a *fetch* failed at `address`.
    ///
    /// Takes the address rather than only setting a flag, because the two ways
    /// a fetch can fail arrive here differently: an absent address is recorded
    /// by the read that failed, but a present-but-not-executable one has no
    /// failed read to record it, since that read succeeded.
    void note_fetch_fault(uint32_t address) { note_fault(address, true); }

    /// Record a data fault the memory helpers cannot see, at `address`.
    ///
    /// A misaligned load has a perfectly valid address that this core refuses
    /// anyway, so no read fails and nothing would otherwise be recorded. The
    /// diagnostic would then name whatever faulted last, which on a freshly
    /// installed board is zero.
    void note_data_fault(uint32_t address) { note_fault(address, false); }

private:
    void note_fault(uint32_t address, bool fetch) const {
        fault_address_ = address;
        fault_was_fetch_ = fetch;
    }

    /// One region and its contents. A vector rather than a map because there
    /// are a handful of regions and a linear scan over three beats hashing.
    struct Region {
        uint32_t base = 0;
        uint32_t size = 0;
        bool executable = true;
        /// The byte an untouched location reads, kept so `clear_memory` can
        /// restore it. Clearing flash to zero rather than to its fill would
        /// leave the core in a state the part it models can never be in.
        uint8_t fill = 0;
        std::vector<uint8_t> bytes;
    };

    /// The region a given span falls in, or nullptr. One lookup used by every
    /// access, so the rule is stated once rather than repeated in each read
    /// and write.
    const Region* region_for(uint32_t address, uint32_t bytes) const;
    Region* region_for(uint32_t address, uint32_t bytes);

    std::array<uint32_t, kRegisters> x_{};
    uint32_t pc_ = 0;
    uint32_t extensions_ = 0;
    std::vector<Region> regions_;
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_fetch_ = false;
};

}  // namespace riscv32

#endif
