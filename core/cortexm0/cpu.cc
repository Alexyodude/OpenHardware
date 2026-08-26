// OpenHardware — Cortex-M0+ registers, flags, and whatever memory a board gives it.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "cpu.h"

#include <cassert>

#include <algorithm>

namespace cortexm0 {
namespace {

/// One entry of the map. Kept local because the map is this file's business:
/// callers ask about addresses, never about regions.
struct Region {
    uint32_t base;
    uint32_t size;
};

/// True when `bytes` starting at `address` fits wholly inside `region`.
///
/// The remaining-space form, not `offset + bytes <= size`: that addition wraps
/// for an address near the top of the space and reports a wildly out-of-range
/// access as fitting.
bool contains(const Region& region, uint32_t address, uint32_t bytes, uint32_t& offset) {
    if (address < region.base) {
        return false;
    }
    offset = address - region.base;
    return offset < region.size && bytes <= region.size - offset;
}

}  // namespace

// No memory. A board adds it; see cpu.h for why the map is not here.
Cpu::Cpu() = default;

void Cpu::reset() {
    regs_.fill(0);
    apsr_ = 0;
    clear_memory();
    // Power-on, so the whole board goes: both the peripherals and the memory
    // map. Clearing only one leaves a machine with RAM and no registers, or
    // registers and no RAM -- half a board, which is exactly the
    // looks-reset-and-is-not state this is here to prevent. The call to
    // `clear_regions` was missing while this comment already claimed it,
    // which is how a reset machine kept its flash.
    clear_registers();
    clear_regions();
    // Virtual time restarts with the machine. A reset core whose timer kept
    // running would let firmware read a clock from before it existed.
    executed_ = 0;
}

void Cpu::clear_registers() {
    mmio_.clear();
    // Streams go with them. They are registered in both tables, so clearing
    // one and not the other would leave a stream whose address no longer
    // responds -- and, worse, would carry one board's captured output into the
    // next board installed over it.
    streams_.clear();
    counters_.clear();
    // The System Control Space is reset rather than removed: it is the
    // architecture's, not a board's, so no board can be installed without it
    // and none can take it away. See cpu.h -- an enabled SysTick surviving
    // into the next test is the same leak the two lines above prevent.
    scs_ = SystemControl{};
}

void Cpu::tick_systick() {
    if ((scs_.systick_csr & kSystEnable) == 0) {
        return;
    }
    if (scs_.systick_current == 0) {
        // Reload happens on the tick *after* the counter reads zero, so the
        // sequence for a reload of 3 is 3, 2, 1, 0, 3, 2, 1, 0 -- and the
        // **period is SYST_RVR plus one**, not SYST_RVR. That is the part's
        // own behaviour and not an off-by-one: it is exactly why
        // `SysTick_Config(n)` writes `n - 1`, and a model that fired every
        // SYST_RVR ticks would make every Arduino `delay` fractionally short
        // in a way no single test notices.
        //
        // A reload of zero leaves the counter stopped, which is what the
        // architecture says and what `SysTick_Config` relies on to refuse a
        // reload it cannot represent.
        scs_.systick_current = scs_.systick_reload;
        return;
    }
    --scs_.systick_current;
    if (scs_.systick_current != 0) {
        return;
    }
    scs_.countflag = true;
    if ((scs_.systick_csr & kSystTickInt) != 0) {
        // Pending, not taken. Taking it here would stack a frame in the middle
        // of `note_executed`, where the instruction that just retired has
        // already moved PC -- so the exception would return to the right place
        // by luck rather than by construction. `ServicePending` takes it at the
        // top of the next `step`, which is the only point where the machine is
        // between instructions.
        scs_.systick_pending = true;
    }
}

bool Cpu::in_system_control(uint32_t address) {
    switch (address & ~3u) {
        case kSystCsr:
        case kSystRvr:
        case kSystCvr:
        case kSystCalib:
        case kScbIcsr:
        case kScbVtor:
        case kScbShpr2:
        case kScbShpr3:
            return true;
        default:
            return false;
    }
}

bool Cpu::scs_read(uint32_t address, uint32_t& out) const {
    switch (address & ~3u) {
        case kSystCsr:
            out = scs_.systick_csr | (scs_.countflag ? kSystCountFlag : 0u);
            // The read is what clears it. See the `mutable` note in cpu.h.
            scs_.countflag = false;
            return true;
        case kSystRvr:
            out = scs_.systick_reload;
            return true;
        case kSystCvr:
            out = scs_.systick_current;
            return true;
        case kSystCalib:
            // **Zero is the answer, and it is not a shrug.** TENMS zero means
            // "the calibration value is unknown", which is exactly true of a
            // core whose clock is retired instructions. A made-up ten
            // milliseconds would let firmware compute a tick rate from it and
            // believe the result.
            out = 0;
            return true;
        case kScbIcsr:
            out = (scs_.systick_pending ? kIcsrPendstSet : 0u) |
                  (scs_.ipsr & kIcsrVectActive);
            return true;
        case kScbVtor:
            out = scs_.vector_table;
            return true;
        case kScbShpr2:
            out = scs_.handler_priority[0];
            return true;
        case kScbShpr3:
            out = scs_.handler_priority[1];
            return true;
        default:
            return false;
    }
}

bool Cpu::scs_write(uint32_t address, uint32_t value, uint32_t byte_mask) {
    // A byte or halfword write arrives already shifted into place with the
    // rest zero, exactly as `mmio_write` documents, so the mask is applied the
    // same way here: keep what this access does not address.
    const auto merge = [&](uint32_t stored) {
        return (stored & ~byte_mask) | (value & byte_mask);
    };
    switch (address & ~3u) {
        case kSystCsr:
            // COUNTFLAG is not writable, and is held outside the word anyway.
            scs_.systick_csr = merge(scs_.systick_csr) & ~kSystCountFlag;
            return true;
        case kSystRvr:
            scs_.systick_reload = merge(scs_.systick_reload) & 0x00FFFFFFu;
            return true;
        case kSystCvr:
            // **Any write clears it, whatever the value.** That is the
            // architecture, and it is what `SysTick_Config` depends on: it
            // writes zero and expects the first period to be a full one rather
            // than however far a previous count had got.
            scs_.systick_current = 0;
            scs_.countflag = false;
            return true;
        case kSystCalib:
            // Read-only on the part. Ignored rather than refused, as hardware
            // ignores it -- the same choice `map_constant` makes.
            return true;
        case kScbIcsr:
            if ((value & kIcsrPendstSet) != 0) {
                scs_.systick_pending = true;
            }
            // Clear is checked second and wins, because a write naming both is
            // architecturally UNPREDICTABLE and the safer of the two readings
            // is the one that does not leave an exception pending nobody asked
            // for. No firmware here writes both; this is which way it falls.
            if ((value & kIcsrPendstClr) != 0) {
                scs_.systick_pending = false;
            }
            return true;
        case kScbVtor:
            scs_.vector_table = merge(scs_.vector_table);
            return true;
        case kScbShpr2:
            scs_.handler_priority[0] = merge(scs_.handler_priority[0]);
            return true;
        case kScbShpr3:
            scs_.handler_priority[1] = merge(scs_.handler_priority[1]);
            return true;
        default:
            return false;
    }
}

bool Cpu::add_region(uint32_t base, uint32_t size, bool executable, uint8_t fill) {
    // An overlapping region is a mistake in a board description, not a
    // layering choice. Accepting it silently allocated a second buffer that
    // nothing could ever read, because the lookup returns the first match --
    // so the board would appear to work while half its writes went nowhere.
    for (const Extra& existing : regions_) {
        const bool disjoint =
            base + size <= existing.base || existing.base + existing.size <= base;
        if (!disjoint) {
            return false;
        }
    }
    Extra region;
    region.base = base;
    region.size = size;
    region.executable = executable;
    region.fill = fill;
    region.bytes.assign(size, fill);
    regions_.push_back(std::move(region));
    return true;
}

void Cpu::clear_regions() { regions_.clear(); }

void Cpu::clear_memory() {
    // Back to each region's own fill byte, not to zero: erased flash reads
    // 0xFF, and clearing it to zero would turn a region that stops the core
    // into one that executes a million no-ops.
    for (Extra& region : regions_) {
        std::fill(region.bytes.begin(), region.bytes.end(), region.fill);
    }
}

void Cpu::map_register(uint32_t address, uint32_t value) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.value = value;
    entry.target = at;
    entry.source = at;
    mmio_[at] = entry;
}

void Cpu::map_alias(uint32_t address, uint32_t target, WriteOp op, bool readable) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.target = target & ~3u;
    entry.source = target & ~3u;
    entry.op = op;
    entry.readable = readable;
    mmio_[at] = entry;
}

void Cpu::map_mirror(uint32_t address, uint32_t source, bool invert, uint32_t mask) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.target = at;
    entry.source = source & ~3u;
    entry.invert = invert;
    entry.mask = mask;
    mmio_[at] = entry;
}

void Cpu::map_constant(uint32_t address, uint32_t value) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.value = value;
    entry.target = at;
    entry.source = at;
    entry.writable = false;
    mmio_[at] = entry;
}

void Cpu::map_stream(uint32_t address, uint32_t enable_address,
                     uint32_t enable_mask) {
    const uint32_t at = address & ~3u;
    // Registered in `mmio_` as well, so `is_mapped` sees it and a read answers
    // this entry's value, which stays zero. The stream table alone would make
    // the address respond to writes and fault on reads.
    Mapped entry;
    entry.target = at;
    entry.source = at;
    mmio_[at] = entry;

    Stream stream;
    stream.enable = enable_address & ~3u;
    stream.enable_mask = enable_mask;
    streams_[at] = stream;
}

void Cpu::map_counter(uint32_t address, uint32_t instructions_per_tick) {
    const uint32_t at = address & ~3u;
    // Registered in `mmio_` too, so `is_mapped` sees it and a write lands
    // somewhere harmless. TIMERAWL is "RO" per pico-sdk's timer.h, and a write
    // to it is ignored rather than refused, which is what the part does.
    //
    // **No `writable = false` here, and it was there until mutation testing
    // removed it.** A counter's read is served from `counters_` before the
    // stored-word path is reached, so the word a write lands in is never read
    // back -- the flag changed nothing observable. That is the same argument
    // `map_mirror` makes about itself, and the same conclusion the `read_only`
    // flag reached before it was deleted.
    Mapped entry;
    entry.target = at;
    entry.source = at;
    mmio_[at] = entry;

    // Zero would divide by zero on the first read. A board asking for a
    // counter that never advances has asked for the hang this exists to
    // prevent, so it is corrected to the fastest legal rate rather than
    // honoured.
    Counter counter;
    counter.instructions_per_tick =
        instructions_per_tick == 0 ? 1u : instructions_per_tick;
    counter.origin = executed_;
    counters_[at] = counter;
}

const std::vector<uint8_t>& Cpu::stream(uint32_t address) const {
    static const std::vector<uint8_t> none;
    const auto found = streams_.find(address & ~3u);
    return found == streams_.end() ? none : found->second.bytes;
}

bool Cpu::is_mapped(uint32_t address) const {
    // The System Control Space is checked first and is always present: it is
    // part of the processor rather than of the board, so there is no core
    // without it and no board that can install one over it.
    return in_system_control(address) || mmio_.find(address & ~3u) != mmio_.end();
}

bool Cpu::mmio_read(uint32_t address, uint32_t& out) const {
    if (in_system_control(address)) {
        return scs_read(address, out);
    }
    const auto found = mmio_.find(address & ~3u);
    if (found == mmio_.end()) {
        return false;
    }
    // A counter derives its answer rather than storing one, so it is checked
    // before the stored-value path below.
    const auto counter = counters_.find(address & ~3u);
    if (counter != counters_.end()) {
        out = static_cast<uint32_t>((executed_ - counter->second.origin) /
                                    counter->second.instructions_per_tick);
        return true;
    }

    const Mapped& entry = found->second;
    if (!entry.readable) {
        // The architecture's answer, not an absence. See `map_alias`.
        out = 0;
        return true;
    }
    // One hop only. A mirror of a mirror would need a loop, and a loop needs a
    // cycle check; nothing has asked for it, so the shape that cannot loop is
    // the one that ships.
    uint32_t value = entry.value;
    if (entry.source != (address & ~3u)) {
        const auto origin = mmio_.find(entry.source);
        if (origin == mmio_.end()) {
            // A mirror whose source was never mapped. Faulting is right: it is
            // a mistake in the board description, and answering zero would be
            // the silent-hang failure this whole design refuses.
            note_fault(address, false);
            return false;
        }
        value = origin->second.value;
    }
    if (entry.invert) {
        value = ~value;
    }
    out = value & entry.mask;
    return true;
}

bool Cpu::mmio_write(uint32_t address, uint32_t value, uint32_t byte_mask) {
    if (in_system_control(address)) {
        return scs_write(address, value, byte_mask);
    }
    const uint32_t at = address & ~3u;
    const auto found = mmio_.find(at);
    if (found == mmio_.end()) {
        return false;
    }

    // A stream is checked before the word behaviours, because it is not one:
    // its write appends rather than stores, and falling through would latch
    // the byte into a register nobody reads.
    const auto stream = streams_.find(at);
    if (stream != streams_.end()) {
        const auto gate = mmio_.find(stream->second.enable);
        if (gate == mmio_.end()) {
            // The gate register was never mapped. A board description mistake,
            // and faulting says so; capturing regardless would print bytes a
            // real part would have discarded.
            note_fault(address, false);
            return false;
        }
        if ((gate->second.value & stream->second.enable_mask) != 0) {
            stream->second.bytes.push_back(static_cast<uint8_t>(value >> 0));
        }
        // Writing to a disabled transmitter is not an error on the part, so
        // the access succeeds and the byte goes nowhere -- which is what the
        // hardware does with it.
        return true;
    }

    const Mapped& entry = found->second;
    if (!entry.writable) {
        // A read-only register ignores the write, as hardware does. See
        // `map_constant`.
        return true;
    }
    const auto target = mmio_.find(entry.target);
    if (target == mmio_.end()) {
        note_fault(address, false);
        return false;
    }
    // `value` always arrives already confined to `byte_mask`: the sub-word
    // accessors shift the byte or halfword into place and leave the rest zero,
    // and the word path passes a full mask. So set, clear and xor need no
    // masking of their own -- a byte contributing zero is the identity for all
    // three, which is the property that makes a partial write to an atomic
    // alias mean what it says.
    //
    // **Store is the exception, and the only reason the mask is a parameter.**
    // It has to preserve the bytes it does not address; without the mask a
    // `STRB` would zero the other three. Masking the other three ops as well
    // was written first and mutation testing found it dead -- deleting it
    // changed nothing observable, the same way the `read_only` flag on
    // `map_mirror` did before it was removed.
    uint32_t& stored = target->second.value;
    switch (entry.op) {
        case WriteOp::Store:
            stored = (stored & ~byte_mask) | (value & byte_mask);
            break;
        case WriteOp::Set: stored |= value; break;
        case WriteOp::Clear: stored &= ~value; break;
        case WriteOp::Xor: stored ^= value; break;
    }
    return true;
}

const std::vector<uint8_t>* Cpu::region_for(uint32_t address, uint32_t bytes,
                                            uint32_t& offset) const {
    for (const Extra& region : regions_) {
        if (contains(Region{region.base, region.size}, address, bytes, offset)) {
            return &region.bytes;
        }
    }
    note_fault(address, false);
    return nullptr;
}

bool Cpu::executable_at(uint32_t address) const {
    for (const Extra& region : regions_) {
        uint32_t offset = 0;
        if (contains(Region{region.base, region.size}, address, 2, offset)) {
            return region.executable;
        }
    }
    // Not in any region. The fetch will fault on the read anyway; saying
    // "executable" here keeps this function about permission rather than
    // about existence.
    return true;
}

std::vector<uint8_t>* Cpu::region_for(uint32_t address, uint32_t bytes,
                                      uint32_t& offset) {
    // The const overload holds the logic; this one casts its result rather
    // than repeating the map, so the two cannot drift.
    const Cpu* self = this;
    return const_cast<std::vector<uint8_t>*>(self->region_for(address, bytes, offset));
}

bool Cpu::in_range(uint32_t address, uint32_t bytes) const {
    uint32_t offset = 0;
    return region_for(address, bytes, offset) != nullptr;
}

bool Cpu::read_word(uint32_t address, uint32_t& out) const {
    // MMIO is checked before the regions, not after, so a mapped register
    // cannot be shadowed by a region that happens to cover it.
    if (is_mapped(address)) {
        return mmio_read(address, out);
    }
    uint32_t offset = 0;
    const std::vector<uint8_t>* region = region_for(address, 4, offset);
    if (region == nullptr) {
        return false;
    }
    // Byte at a time, little-endian, rather than casting to a uint32_t*. The
    // cast is an alignment fault on some targets and a strict-aliasing
    // violation on all of them.
    out = static_cast<uint32_t>((*region)[offset]) |
          (static_cast<uint32_t>((*region)[offset + 1]) << 8) |
          (static_cast<uint32_t>((*region)[offset + 2]) << 16) |
          (static_cast<uint32_t>((*region)[offset + 3]) << 24);
    return true;
}

bool Cpu::write_word(uint32_t address, uint32_t value) {
    if (is_mapped(address)) {
        return mmio_write(address, value);
    }
    uint32_t offset = 0;
    std::vector<uint8_t>* region = region_for(address, 4, offset);
    if (region == nullptr) {
        return false;
    }
    (*region)[offset] = static_cast<uint8_t>(value);
    (*region)[offset + 1] = static_cast<uint8_t>(value >> 8);
    (*region)[offset + 2] = static_cast<uint8_t>(value >> 16);
    (*region)[offset + 3] = static_cast<uint8_t>(value >> 24);
    return true;
}

// The four sub-word accessors below check `is_mapped` first, exactly as the
// word pair does. They did not, and the gap was invisible for as long as
// nothing needed it: every peripheral modelled here was word-accessed, so
// `LDRB` from a mapped register faulted with a message about leaving the
// modelled memory -- for an address the board had explicitly mapped. A UART
// data register is the first one firmware reaches a byte at a time.

bool Cpu::read_halfword(uint32_t address, uint16_t& out) const {
    if (is_mapped(address)) {
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint16_t>(word >> ((address & 2u) * 8u));
        return true;
    }
    uint32_t offset = 0;
    const std::vector<uint8_t>* region = region_for(address, 2, offset);
    if (region == nullptr) {
        return false;
    }
    out = static_cast<uint16_t>((*region)[offset] |
                                (static_cast<uint16_t>((*region)[offset + 1]) << 8));
    return true;
}

bool Cpu::write_halfword(uint32_t address, uint16_t value) {
    if (is_mapped(address)) {
        const uint32_t shift = (address & 2u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          static_cast<uint32_t>(0xFFFFu) << shift);
    }
    uint32_t offset = 0;
    std::vector<uint8_t>* region = region_for(address, 2, offset);
    if (region == nullptr) {
        return false;
    }
    (*region)[offset] = static_cast<uint8_t>(value);
    (*region)[offset + 1] = static_cast<uint8_t>(value >> 8);
    return true;
}

bool Cpu::read_byte_checked(uint32_t address, uint8_t& out) const {
    if (is_mapped(address)) {
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint8_t>(word >> ((address & 3u) * 8u));
        return true;
    }
    uint32_t offset = 0;
    const std::vector<uint8_t>* region = region_for(address, 1, offset);
    if (region == nullptr) {
        return false;
    }
    out = (*region)[offset];
    return true;
}

bool Cpu::write_byte_checked(uint32_t address, uint8_t value) {
    if (is_mapped(address)) {
        const uint32_t shift = (address & 3u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          static_cast<uint32_t>(0xFFu) << shift);
    }
    uint32_t offset = 0;
    std::vector<uint8_t>* region = region_for(address, 1, offset);
    if (region == nullptr) {
        return false;
    }
    (*region)[offset] = value;
    return true;
}

uint8_t Cpu::read_byte(uint32_t address) const {
    uint8_t value = 0;
    // The return value is dropped deliberately, and the assert is why that is
    // safe rather than the zero-on-failure this file otherwise refuses. Both
    // callers -- the ABI's block functions -- range-check the whole span
    // first, so reaching here out of range is a bug in this file, not bad
    // input. Returning a silent zero would make it look like data.
    const bool present = read_byte_checked(address, value);
    assert(present && "read_byte is unchecked; callers must range-check first");
    (void)present;
    return value;
}

void Cpu::write_byte(uint32_t address, uint8_t value) {
    const bool present = write_byte_checked(address, value);
    assert(present && "write_byte is unchecked; callers must range-check first");
    (void)present;
}

}  // namespace cortexm0
