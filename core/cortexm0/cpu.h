// OpenHardware — Cortex-M0+ registers, flags, and whatever memory a board gives it.
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

// --- the System Control Space -----------------------------------------------
//
// **The addresses below are the only ones in this file, and they are not an
// exception to the rule at the top of it.** "The core owns no memory map"
// means no address here names a *chip*: flash is where a board says, SIO is an
// RP2040's word for it. 0xE000E000 names none -- the System Control Space is
// Armv6-M itself, at the same address on an RP2040, a SAMD21 and every other
// Cortex-M0+ ever made. Pushing it into the board files would put one
// architectural constant into each of them and make two boards disagree about
// a register neither of them owns.
//
// Only what an image actually reaches is here. Measured on 2026-08-26 against
// a real Arduino-core SAMD21 sketch: it demands SYST_CSR, SYST_RVR, SYST_CVR,
// ICSR and SHPR3, and nothing else in the space.

/// SysTick's three registers, plus the calibration word.
constexpr uint32_t kSystCsr = 0xE000E010u;
constexpr uint32_t kSystRvr = 0xE000E014u;
constexpr uint32_t kSystCvr = 0xE000E018u;
constexpr uint32_t kSystCalib = 0xE000E01Cu;

/// SYST_CSR bits.
constexpr uint32_t kSystEnable = 1u << 0;
constexpr uint32_t kSystTickInt = 1u << 1;
constexpr uint32_t kSystClkSource = 1u << 2;
constexpr uint32_t kSystCountFlag = 1u << 16;

/// The System Control Block words a vectored core needs.
///
/// `VTOR` is on a Cortex-M0+ and not on a Cortex-M0, which this file's header
/// already records as the reason the two are not the same part.
constexpr uint32_t kScbIcsr = 0xE000ED04u;
constexpr uint32_t kScbVtor = 0xE000ED08u;
constexpr uint32_t kScbShpr2 = 0xE000ED1Cu;
constexpr uint32_t kScbShpr3 = 0xE000ED20u;

/// ICSR bits. `PENDSTSET` reads as whether SysTick is waiting to be taken and
/// writes as a request to make it so; `PENDSTCLR` only writes.
constexpr uint32_t kIcsrPendstClr = 1u << 25;
constexpr uint32_t kIcsrPendstSet = 1u << 26;
/// The exception number currently executing, which is IPSR.
constexpr uint32_t kIcsrVectActive = 0x1FFu;

/// SysTick's exception number. The vector table entry is at `4 * this`.
constexpr unsigned kExceptionSysTick = 15;

/// The lowest value that means "return from an exception" rather than "branch
/// here". Armv6-M reserves 0xF0000000 upwards for it, and every EXC_RETURN
/// this core produces is in the top sixteen bytes of the space.
constexpr uint32_t kExcReturnBase = 0xF0000000u;
/// Return to Thread mode on the main stack. The only frame this core stacks,
/// because it models no process stack -- see `exception.h`.
constexpr uint32_t kExcReturnThread = 0xFFFFFFF9u;
/// Return to Handler mode on the main stack: an exception taken while another
/// was already running. Not reachable with one exception source, and produced
/// anyway so the value a handler sees is the architecture's rather than this
/// core's simplification.
constexpr uint32_t kExcReturnHandler = 0xFFFFFFF1u;

/// EPSR.T, which is set in every xPSR an Armv6-M part stacks: there is no ARM
/// state to return to, so a cleared T on an exception return is a fault on
/// real silicon rather than a mode switch.
constexpr uint32_t kEpsrThumb = 1u << 24;
/// Bit 9 of a stacked xPSR: whether entry had to move SP down four bytes to
/// reach an eight-byte boundary. Return puts back exactly what entry took.
constexpr uint32_t kXpsrFrameAlign = 1u << 9;

/// Everything the System Control Space holds, which is not everything it has.
///
/// A struct rather than five `map_register` calls because three of these are
/// not words: `SYST_CVR` counts, `SYST_CSR.COUNTFLAG` clears when it is read,
/// and `ICSR.PENDSTSET` is a request in one direction and a report in the
/// other. `map_register`'s own comment sends exactly those elsewhere.
struct SystemControl {
    uint32_t systick_csr = 0;
    uint32_t systick_reload = 0;
    uint32_t systick_current = 0;
    /// Where the vector table is. Zero at reset, which is where every image
    /// this repository runs links its own.
    uint32_t vector_table = 0;
    /// SHPR2 and SHPR3, stored and never consulted. **They are here so that
    /// writing them is not a fault, not because priority is modelled** --
    /// `NVIC_SetPriority(SysTick_IRQn, ...)` is the second line of Arduino's
    /// `init()`, and with one exception source there is nothing to arbitrate.
    /// The day a second source exists, this is the field that has to start
    /// meaning something.
    uint32_t handler_priority[2] = {0, 0};
    /// SysTick reached zero since this was last read. Cleared by the read.
    bool countflag = false;
    /// SysTick wrapped with TICKINT set and the exception has not been taken.
    bool systick_pending = false;
    /// PRIMASK: `CPSID i` sets it and `CPSIE i` clears it.
    bool primask = false;
    /// IPSR: 0 in Thread mode, the exception number in Handler mode.
    uint32_t ipsr = 0;
};

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
    /// A register that clears on read is a *modelled peripheral* rather than a
    /// mapped word, and has no home here yet.
    ///
    /// This paragraph used to send a register that *counts* to "the layer that
    /// owns the map" as well, and that layer is Python, which cannot serve a
    /// read -- so the sentence named a place that does not exist. `map_counter`
    /// below is where counting went, on this file's actual principle: the
    /// mechanism is architecture-neutral and belongs here, while the address
    /// and the rate are chip facts and stay in the board.
    void map_register(uint32_t address, uint32_t value);

    /// An address whose write applies `op` to another address's word.
    ///
    /// This is the RP2040's atomic SET/CLR/XOR aliases, and equally STM32's
    /// BSRR: one register that modifies another rather than holding its own
    /// value. **The offsets are not here.** That +0x2000 means "set" on an
    /// RP2040 is a fact about that chip's bus; the caller passes both
    /// addresses, so this stays architecture-only.
    ///
    /// `readable` separates two things that write identically and read
    /// differently, and conflating them gives a wrong answer rather than a
    /// loud one:
    ///
    ///  * A **bus alias window** is a second view of the register, so reading
    ///    it returns that register. The RP2040's +0x1000/+0x2000/+0x3000
    ///    windows are these, and the oracle agrees -- its read path masks the
    ///    offset back to the base register.
    ///  * A **dedicated write-only register** is its own address that happens
    ///    to modify another. SIO's `GPIO_OUT_SET` is one, and hardware reads
    ///    it as zero. Returning `GPIO_OUT` there is not a missing feature, it
    ///    is a wrong value, which is the failure this file otherwise refuses.
    ///
    /// Zero from a `readable == false` register is the *architecture's* answer,
    /// not this model shrugging -- the distinction the rest of this class
    /// spends its comments on.
    void map_alias(uint32_t address, uint32_t target, WriteOp op,
                   bool readable = true);

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

    /// A register whose reads answer `value` and whose writes are ignored.
    ///
    /// Hardware's read-only status register. `map_mirror` cannot stand in for
    /// it: a mirror reads from a *source register*, and a constant has none --
    /// pointing one at itself makes the write land where the read comes from,
    /// which is `map_register` with extra steps.
    ///
    /// The RP2040's `UARTFR` is the case that asked for it. In the model this
    /// core can express -- a TX that always accepts and an RX with nothing
    /// wired to it -- `TXFF`, `RXFE` and `BUSY` do not move, so a constant is
    /// the honest shape rather than a shortcut. What it cannot express is FIFO
    /// backpressure, and `webui/boards/rp2040.py` says so where it calls this.
    void map_constant(uint32_t address, uint32_t value);

    /// A register whose writes append a byte to a captured stream: a TX FIFO.
    ///
    /// The fourth behaviour, and the first that is not a word at all.
    /// `map_register` holds one value, so a second write destroys the first --
    /// which for a UART data register means every character but the last is
    /// lost. `docs/research/peripheral-layer/rp2040_v2/rp2040_uart.json` names
    /// this exactly: "Queue-op semantics, not a plain register store -- the
    /// canonical reason this whole peripheral is coded:".
    ///
    /// **Gated, and the gate is the load-bearing part.** Writes are captured
    /// only while `enable_address & enable_mask` is non-zero, which for a PL011
    /// is `UARTCR.UARTEN`. A disabled UART transmits nothing, and the same
    /// research file names the alternative as a silent lie: "A model letting
    /// TXFF/BUSY move before UARTEN==1 lets firmware appear to print
    /// successfully before the UART is enabled -- silently wrong the same way
    /// FUNCSEL errors are silently wrong." Answering wrongly rather than
    /// loudly is the one failure this file spends its comments refusing, so
    /// the gate is not an option on the primitive; it is the primitive.
    ///
    /// Reads answer zero. On a real PL011 a read pops the RX FIFO, and nothing
    /// in this project drives RX, so the board pairs this with an `RXFE` that
    /// reads empty forever -- a truthful model of a pin with no wire on it.
    void map_stream(uint32_t address, uint32_t enable_address,
                    uint32_t enable_mask);

    /// Everything written to a `map_stream` address so far, oldest first.
    /// Empty for an address that is not one, which is the same answer as a
    /// stream nothing has written to -- the caller registered it and knows.
    const std::vector<uint8_t>& stream(uint32_t address) const;

    /// A register whose read answers `executed() / instructions_per_tick`: a
    /// free-running counter.
    ///
    /// The fifth behaviour, and the one `map_register`'s own comment sends
    /// elsewhere -- "a register that clears on read, or counts, is a *modelled
    /// peripheral* rather than a mapped word, and belongs in the layer that
    /// owns the map". That layer is Python and cannot serve a read, so as
    /// written the sentence names a place that does not exist. It lands here
    /// on the same principle the rest of this class follows: **the mechanism
    /// is here and the map is not.** Counting is architecture-neutral; which
    /// address counts, and how fast, are chip facts and stay in the board.
    ///
    /// Why anything needs it: `timer_busy_wait_us_32()` in pico-sdk's timer.c
    /// spins `while (timer->timerawl - start < delay_us)`. A register that
    /// does not advance makes that loop run forever, which is the hang class
    /// `docs/architectures.md` §3 is about -- and unlike a missing register it
    /// cannot be made loud, because the address *is* modelled and the read
    /// *does* answer. Only the answer never changes.
    ///
    /// **`instructions_per_tick` is a stated approximation, not a
    /// measurement.** This core has no cycle model, so virtual time is counted
    /// in retired instructions. See `webui/boards/rp2040.py`, which picks the
    /// number and says what it does and does not claim.
    void map_counter(uint32_t address, uint32_t instructions_per_tick);

    /// Instructions retired since construction. The only source of virtual
    /// time, and deliberately an integer: `rules/determinism.md` §3 notes that
    /// accumulating simulated time in a float makes step size affect results.
    uint64_t executed() const { return executed_; }

    /// Called by `step` once an instruction has actually retired -- never on a
    /// fault, so a program stopped by one does not age while it is stopped.
    ///
    /// **SysTick advances here and nowhere else**, which is what makes the
    /// approximation a single visible line rather than a scattered one: this
    /// core has no cycle model, so a SysTick tick *is* a retired instruction.
    /// See `tick_systick`.
    void note_executed() {
        ++executed_;
        tick_systick();
    }

    /// The System Control Space: SysTick, IPSR, PRIMASK and the vector table.
    ///
    /// Exposed rather than private because `exception.cc` drives all of it and
    /// `exec.cc` reads PRIMASK and IPSR. A friend declaration would name two
    /// files instead, which is a longer way of saying the same thing.
    const SystemControl& scs() const { return scs_; }
    SystemControl& scs() { return scs_; }

    /// One SysTick tick. Counts down, reloads at zero, and raises the
    /// exception when TICKINT says to.
    ///
    /// **The rate is an approximation and this is where it is made.** rp2040js,
    /// which is this core's oracle, drives SysTick from simulated clock cycles;
    /// there is no cycle model here, so one retired instruction is one tick.
    /// The two therefore agree on *what happens at a wrap* and cannot agree on
    /// *when the wrap happens* -- so a lockstep must compare the former. Same
    /// trade, and the same wording, as `map_counter`.
    void tick_systick();

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
    /// There are no built-in regions to sit alongside. An earlier version of
    /// this comment said flash and SRAM were "still hardcoded because every
    /// Armv6-M part this project targets has them at the same addresses" --
    /// which was false when written, since the SAMD21 shares this core and
    /// puts flash at zero. The constants are gone; the sentence is kept
    /// inverted so the next person does not re-derive the same excuse.
    /// False when it overlaps a region already added, having added nothing.
    bool add_region(uint32_t base, uint32_t size, bool executable,
                    uint8_t fill = 0);

    /// Forget every region. Paired with `clear_registers` in `reset`, because
    /// a reset machine has no board.
    void clear_regions();

    /// Forget every mapped register, and reset the System Control Space.
    ///
    /// Separate from `clear_memory`, which clears memory *contents*. Which
    /// registers exist is configuration -- which board this is -- and a
    /// conformance run that zeroes RAM between cases must not also
    /// un-install the board.
    ///
    /// **The System Control Space is not un-installed, it is reset**, because
    /// it is not a board's and cannot be absent. It goes here rather than only
    /// in `reset` because a session-scoped core reused across tests would
    /// otherwise carry an enabled SysTick -- and a pending exception -- into
    /// the next test, which is the leak `streams_` and `counters_` each had
    /// before them.
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
    void note_fetch_fault(uint32_t address) { note_fault(address, true); }

private:
    void note_fault(uint32_t address, bool fetch) const {
        fault_address_ = address;
        fault_was_fetch_ = fetch;
    }

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

    /// `mutable` for exactly one field of it: **`SYST_CSR.COUNTFLAG` clears
    /// when it is read.** That is genuinely a read that changes state, so it
    /// cannot be served from a `const` path without it -- and the alternative,
    /// a COUNTFLAG that never clears, reports a wrap that already happened as
    /// if it were new. This class spends its comments refusing wrong answers
    /// in favour of loud ones, and there is no loud option here: the address is
    /// modelled and the read does answer. Nothing else in here is written by a
    /// read.
    mutable SystemControl scs_;

    /// Whether `address` is one of the System Control Space words modelled
    /// above. Consulted by `is_mapped`, so every accessor -- word, halfword
    /// and byte alike -- reaches the SCS by the path it already takes to
    /// reach a peripheral.
    static bool in_system_control(uint32_t address);
    bool scs_read(uint32_t address, uint32_t& out) const;
    bool scs_write(uint32_t address, uint32_t value, uint32_t byte_mask);

    /// One mapped word. `target` and `source` name the address whose storage
    /// a write changes and a read derives from; for a plain register both are
    /// the address itself, which is what keeps the lookup uniform.
    struct Mapped {
        uint32_t value = 0;
        uint32_t target = 0;
        uint32_t source = 0;
        WriteOp op = WriteOp::Store;
        bool invert = false;
        bool readable = true;
        /// False for `map_constant`. A mirror does not need it -- its write
        /// lands in its own word while its read comes from `source`, so the
        /// stored value is never read back. A constant reads its own word, so
        /// for it the difference is observable.
        bool writable = true;
        uint32_t mask = 0xFFFFFFFFu;
    };

    /// A `map_stream` address: what gates it, and what has been written.
    ///
    /// Held beside `mmio_` rather than inside `Mapped` because a stream is the
    /// one behaviour that is not a word. Three fields on every mapped register
    /// to serve one of them would be the tail wagging the dog, and `Mapped` is
    /// copied on every lookup.
    struct Stream {
        uint32_t enable = 0;
        uint32_t enable_mask = 0;
        std::vector<uint8_t> bytes;
    };
    std::unordered_map<uint32_t, Stream> streams_;

    /// A `map_counter` address: its rate, and where it started counting.
    ///
    /// **`origin` is what makes a board's timer start at zero.** Without it a
    /// counter reads the machine's whole lifetime, so installing a board on a
    /// core that has already run gives its timer a head start -- and a test
    /// suite sharing one core watches each test's clock carry into the next.
    /// That is the same leak `streams_` had, arriving by a different door.
    /// Installing a board is this model's power-on, so counting from the map
    /// call is both the fix and the more accurate reading.
    struct Counter {
        uint32_t instructions_per_tick = 1;
        uint64_t origin = 0;
    };
    std::unordered_map<uint32_t, Counter> counters_;

    /// Retired instructions. Virtual time's only source; see `executed()`.
    uint64_t executed_ = 0;

    /// Word-aligned address to behaviour. A map rather than a range, so an
    /// unmodelled register inside a modelled peripheral still faults.
    std::unordered_map<uint32_t, Mapped> mmio_;

    bool mmio_read(uint32_t address, uint32_t& out) const;

    /// `byte_mask` selects which bytes of the word the write touches, so a
    /// `STRB` reaches a mapped register without disturbing its neighbours.
    ///
    /// **A mask rather than a read-modify-write, and the difference is not
    /// cosmetic.** RMW would read the word, replace one byte and store the
    /// result -- and storing a whole word through a `Set` alias sets every bit
    /// that happened to be in the value read, rather than the eight the
    /// instruction addressed. The mask keeps the untouched bytes contributing
    /// zero, which is the identity for set, clear and xor alike.
    bool mmio_write(uint32_t address, uint32_t value,
                    uint32_t byte_mask = 0xFFFFFFFFu);
};

}  // namespace cortexm0

#endif
