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
#include <unordered_map>
#include <vector>

namespace riscv32 {

/// x0 through x31. x0 reads as zero and discards every write.
constexpr unsigned kRegisters = 32;

/// The optional extensions this core can be told a part has. RV32I is the
/// base and is always present, so it has no bit.
///
/// One bit per extension this core can be *told about*, which is not the same
/// as one bit per extension it implements. `kExtA` is classified and then
/// refused -- `Unimplemented` on a part that has it, `Illegal` on one that
/// does not (exec.cc's AMO case); every other bit here, `kExtM` included,
/// is implemented. Both kinds need a bit, because the
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
/// Zcb, Zcmp and Zcmt arrived at OH-146: the ESP32-C5's three groups, the
/// first two also the RP2350's. Zbb and Zbkb arrived at OH-208, the last two
/// groups of the RP2350's string; no ESP32-C part has either.
///
/// **Zbb and Zbkb are two bits and not one, although seven of their
/// instructions are the same encodings.** `andn`, `orn`, `xnor`, `rol`,
/// `ror`, `rori` and `rev8` are in both, so either bit opens them; the rest
/// belong to one group only, and a part with one of the two must still
/// refuse the other's -- `clz` on a Zbkb-only part, `zip` on a Zbb-only one.
/// The RP2350 has both, so no board here can tell the difference; the
/// gating tests can, and do.
enum Extension : uint32_t {
    kExtM = 1u << 0,
    kExtA = 1u << 1,
    kExtC = 1u << 2,
    kExtZba = 1u << 3,
    kExtZbs = 1u << 4,
    kExtZcb = 1u << 5,
    kExtZcmp = 1u << 6,
    kExtZcmt = 1u << 7,
    kExtZbb = 1u << 8,
    kExtZbkb = 1u << 9,
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

/// What a write to a mapped alias does to the register it names.
///
/// `Store` is an ordinary register. The other three are the ESP32's W1TS and
/// W1TC and the RP2040's atomic aliases: one address that modifies another
/// rather than holding a value of its own. Same set and same spelling as
/// `core/cortexm0`, because the behaviours are bus arrangements rather than
/// anything Arm or RISC-V.
enum class WriteOp : uint8_t { Store, Set, Clear, Xor };

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

    /// The Zcmt jump-vector table pointer -- the one CSR this core has,
    /// because `cm.jt` reads its target through it and a part with Zcmt
    /// cannot be modelled without it. Reachable from software only through
    /// the Zicsr encodings `exec.cc` opens for exactly this address.
    uint32_t jvt() const { return jvt_; }
    void set_jvt(uint32_t value) { jvt_ = value; }

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

    // --- memory-mapped registers -----------------------------------------
    //
    // ## Why a peripheral is not a region
    //
    // `add_region` gives back what was written. A peripheral does not: a
    // status bit is set by hardware, a W1TC register clears bits rather than
    // storing them, and a FIFO is not a word at all. Mapping peripheral space
    // as a plain region turns every wait-for-ready poll into an **infinite
    // loop** -- firmware that hangs instead of firmware that says what is
    // missing, which is the failure that wastes the most time.
    //
    // So an address is either a region, or mapped here, or neither -- and
    // neither faults, loudly, naming the address. That is the whole design:
    // the fault is what tells a person which peripheral the board description
    // is missing.
    //
    // ## Four of the six, and the last two arrived the way this comment said
    //
    // `core/cortexm0` grew six behaviours -- register, alias, mirror,
    // constant, stream, counter -- each when a real image faulted without it.
    // (This comment said five until the OH-161 review counted them:
    // `map_counter` is the sixth, and it is the one a timer needs.)
    // `map_register` and `map_alias` are what an ESP32-C3 GPIO blink needs,
    // and this comment used to end "the other three arrive when an image here
    // faults without them". `map_stream` is the first of them to arrive, on
    // exactly that trigger: OH-161 needed a sketch to print, an ESP32's
    // `UART_FIFO_REG` is a queue rather than a word, and a `map_register`
    // there keeps the last byte written -- so a program printing "hello"
    // leaves an `o` behind and a test reading it back sees a plausible single
    // letter instead of a wrong answer.
    //
    // **The counter arrived at OH-161's step 2, and not in cortexm0's
    // shape.** That one is a register whose read answers the count; an
    // ESP32's SYSTIMER is not read that way. Firmware writes UPDATE, waits
    // for VALUE_VALID, and reads two registers holding a COPY taken at the
    // write -- so a live read would answer the right number at the wrong
    // moment, and a program that took a snapshot and read it later would see
    // time it never asked for. `map_snapshot_counter` is that shape.
    // `map_mirror` and `map_constant` are still absent, on the same terms.

    /// An address that holds a word: reads answer it, writes replace it.
    ///
    /// `value` is the register's reset value, which is a chip fact and comes
    /// from the board. **The address is masked to a word boundary**, so all
    /// four bytes of a register name the same entry and a byte-wide write
    /// reaches it.
    void map_register(uint32_t address, uint32_t value);

    /// An address whose write applies `op` to another address's word.
    ///
    /// This is the ESP32's W1TS/W1TC pairs -- `GPIO_OUT_W1TS` sets the bits
    /// written to it in `GPIO_OUT` and `GPIO_OUT_W1TC` clears them -- and
    /// equally the RP2040's atomic aliases and STM32's BSRR. **The offsets are
    /// not here**: which offset means "set" is a fact about the chip's bus, so
    /// the caller passes both addresses and this stays architecture-only.
    ///
    /// `readable` separates two things that write identically and read
    /// differently, and conflating them gives a wrong answer rather than a
    /// loud one:
    ///
    ///  * A **bus alias window** is a second view of the register, so reading
    ///    it returns that register.
    ///  * A **dedicated write-only register** is its own address that happens
    ///    to modify another, and hardware reads it as zero. The ESP32's W1TS
    ///    and W1TC are these. Returning `GPIO_OUT` there is not a missing
    ///    feature, it is a wrong value.
    ///
    /// Zero from a `readable == false` register is the *architecture's*
    /// answer, not this model shrugging.
    void map_alias(uint32_t address, uint32_t target, WriteOp op,
                   bool readable = true);

    /// An address whose writes append a byte to a captured stream.
    ///
    /// A transmit FIFO. `enable_address` and `enable_mask` name the bit that
    /// must be set for the bytes to be kept, because a transmitter whose
    /// clock is off sends nothing and a model without the gate lets firmware
    /// appear to print before it enabled the peripheral. On the three ESP32
    /// parts described here that bit is `UART_TX_SCLK_EN`, whose reset value
    /// the vendor sets to 1 -- so a bare-metal image transmits without
    /// touching it, and one that clears it goes quiet.
    ///
    /// **The gate must itself be mapped**, and a write through an unmapped
    /// gate faults rather than capturing: a board that named the wrong
    /// address would otherwise print bytes the part would have discarded.
    ///
    /// Only the low byte of each write is taken. A word-wide store to a FIFO
    /// whose data field is `[7:0]` transmits one character on this hardware,
    /// and taking four would invent three.
    void map_stream(uint32_t address, uint32_t enable_address,
                    uint32_t enable_mask);

    /// Everything written to a `map_stream` address so far, oldest first.
    ///
    /// Empty for an address that is not one, which is the same answer as a
    /// stream nothing has written to -- the caller registered it and knows.
    const std::vector<uint8_t>& stream(uint32_t address) const;

    /// A free-running counter that firmware reads through a snapshot.
    ///
    /// A write carrying `update_mask` to `op_address` copies the count into
    /// `low_address` (bits 31:0) and `high_address` (bits 63:32, kept to
    /// `high_mask`), and from then on `op_address` reads `valid_mask`. Both
    /// value registers answer that copy until the next write asks for
    /// another; writes to them are ignored, as a read-only register ignores
    /// them. Before the first snapshot all three read zero.
    ///
    /// The count advances once every `instructions_per_tick` retired
    /// instructions, and only while `enable_address & enable_mask` is
    /// non-zero -- a unit whose enable bit is clear holds its count, and
    /// resumes from it when the bit is set again.
    ///
    /// **`instructions_per_tick` is a stated approximation, not a
    /// measurement.** This core has no cycle model, so virtual time is
    /// retired instructions, and the board that picks the number says what
    /// it assumes -- `core/cortexm0`'s `map_counter` made the same trade for
    /// the RP2040's TIMER. Zero is corrected to one rather than dividing by
    /// it; `abi.py` refuses it before it gets here.
    ///
    /// **The gate must itself be mapped**, as a stream's must, and a snapshot
    /// asked for through an unmapped one faults naming `op_address`: a board
    /// that named the wrong enable register would otherwise describe a timer
    /// that silently never counts, which is the spin-forever hang this whole
    /// file is shaped against.
    ///
    /// **Nothing outside this repository's tests holds the behaviour.** rvcpp,
    /// the lockstep oracle, models no peripheral at these addresses, so the
    /// counter is held by the header lines each board cites and by the tests
    /// that read them -- not by an oracle. Lockstep is unaffected either way:
    /// a counter changes no architectural register.
    void map_snapshot_counter(uint32_t op_address, uint32_t update_mask,
                              uint32_t valid_mask, uint32_t low_address,
                              uint32_t high_address, uint32_t high_mask,
                              uint32_t enable_address, uint32_t enable_mask,
                              uint32_t instructions_per_tick);

    /// Called by `step` once an instruction has actually retired -- never on
    /// an Unimplemented, Illegal or MemoryFault, so a program stopped by one
    /// does not age while it is stopped. Advances every snapshot counter
    /// whose gate is open, and is the one line where this core's virtual
    /// time passes.
    void note_executed();

    /// Whether `address` is a mapped register rather than bulk memory.
    ///
    /// False for a region. The two are exclusive by construction: `map_*`
    /// refuses nothing, but a board that maps a register inside a region has
    /// described one address twice, and `in_range` and this both answering
    /// true is how that shows up.
    bool is_mapped(uint32_t address) const;

    /// Forget every mapped register. Called by `clear_regions`, because a
    /// machine with no board has no peripherals either.
    void clear_mmio();

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

    /// One mapped word. `target` names the address whose storage a write
    /// changes; for a plain register it is the address itself, which is what
    /// keeps the lookup uniform and needs no "is this an alias" flag.
    struct Mapped {
        uint32_t value = 0;
        uint32_t target = 0;
        WriteOp op = WriteOp::Store;
        bool readable = true;
    };

    /// A mapped read, or false if `address` is not mapped.
    ///
    /// Separate from `read_word` so the sub-word accessors can consult it too.
    /// **That matters more here than it looks.** ESP32 peripheral registers
    /// are word-accessed by convention, but nothing stops a compiler emitting
    /// `lbu` against one, and a byte read that skipped this would fall through
    /// to the region lookup, find nothing, and fault at an address the board
    /// describes perfectly well.
    bool mmio_read(uint32_t address, uint32_t& out) const;

    /// A mapped write, or false if `address` is not mapped.
    ///
    /// `byte_mask` is which bytes of the word the access actually carries, so
    /// a byte-wide store to a register leaves the other three alone. It is
    /// applied to `Store` only: for Set, Clear and Xor the value has already
    /// been positioned by the caller, and masking it again would clear bits
    /// the write never named.
    bool mmio_write(uint32_t address, uint32_t value, uint32_t byte_mask);

    /// A `map_stream` address: what gates it, and what has been written.
    ///
    /// Held beside `mmio_` rather than inside `Mapped` because a stream is
    /// the one behaviour that is not a word. Three more fields on every
    /// mapped register to serve one of them would be the tail wagging the
    /// dog, and `Mapped` is copied on every lookup.
    struct Stream {
        uint32_t enable = 0;
        uint32_t enable_mask = 0;
        std::vector<uint8_t> bytes;
    };

    /// A `map_snapshot_counter`: its three addresses, its gate, its rate,
    /// the instructions it has counted and the copy firmware last asked for.
    ///
    /// Beside `mmio_` rather than inside `Mapped`, for the reason `Stream`
    /// is: three addresses share one count, and a word per address cannot
    /// say that. The three are registered in `mmio_` as well, so `is_mapped`
    /// answers for them and their reads and writes reach the paths that
    /// check this table first.
    ///
    /// **`instructions` and not a start point**, because the gate can close:
    /// a count derived from "retired since mapping" would jump forward by
    /// every instruction the unit was stopped for the moment it restarted.
    struct Snapshot {
        uint32_t op = 0;
        uint32_t update_mask = 0;
        uint32_t valid_mask = 0;
        uint32_t low = 0;
        uint32_t high = 0;
        uint32_t high_mask = 0;
        uint32_t enable = 0;
        uint32_t enable_mask = 0;
        uint32_t instructions_per_tick = 1;
        uint64_t instructions = 0;
        uint64_t latched = 0;
        bool valid = false;
    };

    std::array<uint32_t, kRegisters> x_{};
    uint32_t pc_ = 0;
    uint32_t jvt_ = 0;
    uint32_t extensions_ = 0;
    std::vector<Region> regions_;
    std::unordered_map<uint32_t, Mapped> mmio_;
    std::unordered_map<uint32_t, Stream> streams_;
    std::vector<Snapshot> snapshots_;
    mutable uint32_t fault_address_ = 0;
    mutable bool fault_was_fetch_ = false;
};

}  // namespace riscv32

#endif
