// OpenHardware — RV32 state and the memory a board gave it.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Memory only. Decode and execute are in exec.cc, so that the question "can
// this core reach this address" stays answerable without reading an
// instruction set.

#include "cpu.h"

#include <algorithm>

namespace riscv32 {

namespace {

/// Does the span [address, address + bytes) fit inside a region at `base` of
/// `size` bytes?
///
/// In 64-bit arithmetic throughout, because every part of this can wrap.
/// `address + bytes` wraps at the top of the address space, and a wrapped sum
/// compares as *smaller* than the base -- which turns a read off the end of
/// memory into a read that passes the range check. The C3 has a region ending
/// at 0x60000000 and firmware that walks off it, so this is reachable rather
/// than theoretical.
bool span_fits(uint32_t address, uint32_t bytes, uint32_t base, uint32_t size) {
    if (address < base) {
        return false;
    }
    const uint64_t offset = static_cast<uint64_t>(address) - base;
    return offset + bytes <= static_cast<uint64_t>(size);
}

}  // namespace

Cpu::Cpu() { reset(); }

void Cpu::reset() {
    x_.fill(0);
    pc_ = 0;
    jvt_ = 0;
    extensions_ = 0;
    regions_.clear();
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
    fault_address_ = 0;
    fault_was_fetch_ = false;
}

const Cpu::Region* Cpu::region_for(uint32_t address, uint32_t bytes) const {
    for (const Region& region : regions_) {
        if (span_fits(address, bytes, region.base, region.size)) {
            return &region;
        }
    }
    return nullptr;
}

Cpu::Region* Cpu::region_for(uint32_t address, uint32_t bytes) {
    const Cpu* self = this;
    return const_cast<Region*>(self->region_for(address, bytes));
}

bool Cpu::in_range(uint32_t address, uint32_t bytes) const {
    return region_for(address, bytes) != nullptr;
}

bool Cpu::executable_at(uint32_t address) const {
    // Two bytes, not four. With C enabled a 16-bit instruction may legally sit
    // in the last halfword of a region, and asking for four would refuse it.
    // Without C the fetch itself asks for four and fails there instead, which
    // is the same refusal reported against the access that actually needed the
    // width.
    const Region* region = region_for(address, 2);
    return region != nullptr && region->executable;
}

bool Cpu::read_byte_checked(uint32_t address, uint8_t& out) const {
    // **The sub-word paths consult MMIO too, and this is not decoration.**
    // ESP32 peripheral registers are word-accessed by convention, but nothing
    // stops a compiler emitting `lbu` against one -- and a byte read that fell
    // through to the region lookup would fault at an address the board
    // describes perfectly well. `core/cortexm0` shipped without this and had
    // to have it added.
    if (is_mapped(address)) {
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint8_t>(word >> ((address & 3u) * 8u));
        return true;
    }
    const Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    out = region->bytes[address - region->base];
    return true;
}

bool Cpu::write_byte_checked(uint32_t address, uint8_t value) {
    if (is_mapped(address)) {
        const unsigned shift = (address & 3u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          0xFFu << shift);
    }
    Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    region->bytes[address - region->base] = value;
    return true;
}

bool Cpu::read_halfword(uint32_t address, uint16_t& out) const {
    if (is_mapped(address)) {
        uint32_t word = 0;
        if (!mmio_read(address, word)) {
            return false;
        }
        out = static_cast<uint16_t>(word >> ((address & 2u) * 8u));
        return true;
    }
    const Region* region = region_for(address, 2);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    out = static_cast<uint16_t>(region->bytes[offset] |
                                (region->bytes[offset + 1] << 8));
    return true;
}

bool Cpu::write_halfword(uint32_t address, uint16_t value) {
    if (is_mapped(address)) {
        const unsigned shift = (address & 2u) * 8u;
        return mmio_write(address, static_cast<uint32_t>(value) << shift,
                          0xFFFFu << shift);
    }
    Region* region = region_for(address, 2);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    region->bytes[offset] = static_cast<uint8_t>(value);
    region->bytes[offset + 1] = static_cast<uint8_t>(value >> 8);
    return true;
}

bool Cpu::read_word(uint32_t address, uint32_t& out) const {
    if (is_mapped(address)) {
        return mmio_read(address, out);
    }
    const Region* region = region_for(address, 4);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    out = static_cast<uint32_t>(region->bytes[offset]) |
          (static_cast<uint32_t>(region->bytes[offset + 1]) << 8) |
          (static_cast<uint32_t>(region->bytes[offset + 2]) << 16) |
          (static_cast<uint32_t>(region->bytes[offset + 3]) << 24);
    return true;
}

bool Cpu::write_word(uint32_t address, uint32_t value) {
    if (is_mapped(address)) {
        return mmio_write(address, value, 0xFFFFFFFFu);
    }
    Region* region = region_for(address, 4);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    const uint32_t offset = address - region->base;
    region->bytes[offset] = static_cast<uint8_t>(value);
    region->bytes[offset + 1] = static_cast<uint8_t>(value >> 8);
    region->bytes[offset + 2] = static_cast<uint8_t>(value >> 16);
    region->bytes[offset + 3] = static_cast<uint8_t>(value >> 24);
    return true;
}

uint8_t Cpu::read_byte(uint32_t address) const {
    const Region* region = region_for(address, 1);
    return region == nullptr ? 0 : region->bytes[address - region->base];
}

void Cpu::write_byte(uint32_t address, uint8_t value) {
    Region* region = region_for(address, 1);
    if (region != nullptr) {
        region->bytes[address - region->base] = value;
    }
}

void Cpu::clear_memory() {
    // Back to each region's own fill byte, not to zero. A flash region reads
    // 0xFF when erased, and clearing it to zero would leave the core in a
    // state the part it models can never be in.
    for (Region& region : regions_) {
        std::fill(region.bytes.begin(), region.bytes.end(), region.fill);
    }
}

bool Cpu::add_region(uint32_t base, uint32_t size, bool executable,
                     uint8_t fill) {
    if (size == 0) {
        return false;
    }
    // The region must not wrap the address space, and must not overlap one
    // that already exists. Overlap is refused rather than merged: two boards
    // describing the same address differently is a bug in a board file, and
    // silently keeping one of them makes it a bug that only shows up as a
    // wrong value much later.
    if (static_cast<uint64_t>(base) + size > 0x100000000ull) {
        return false;
    }
    for (const Region& existing : regions_) {
        const uint64_t new_end = static_cast<uint64_t>(base) + size;
        const uint64_t old_end = static_cast<uint64_t>(existing.base) + existing.size;
        if (base < old_end && existing.base < new_end) {
            return false;
        }
    }
    Region region;
    region.base = base;
    region.size = size;
    region.executable = executable;
    region.fill = fill;
    region.bytes.assign(size, fill);
    regions_.push_back(std::move(region));
    return true;
}

void Cpu::clear_regions() {
    regions_.clear();
    // A machine with no board has no peripherals either. Leaving `mmio_`
    // behind would let a second board inherit the first one's registers, which
    // is the kind of state that makes one test pass only when another ran
    // first. A stream carries BYTES as well as a mapping, so leaving one
    // behind would also let a second board answer with what the first one
    // printed. A snapshot counter carries a COUNT, so leaving one behind
    // would start the next board's clock where the last board's stopped.
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
}

void Cpu::clear_mmio() {
    mmio_.clear();
    streams_.clear();
    snapshots_.clear();
}

void Cpu::map_register(uint32_t address, uint32_t value) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.value = value;
    entry.target = at;
    mmio_[at] = entry;
}

void Cpu::map_alias(uint32_t address, uint32_t target, WriteOp op,
                    bool readable) {
    const uint32_t at = address & ~3u;
    Mapped entry;
    entry.target = target & ~3u;
    entry.op = op;
    entry.readable = readable;
    mmio_[at] = entry;
}

void Cpu::map_stream(uint32_t address, uint32_t enable_address,
                     uint32_t enable_mask) {
    const uint32_t at = address & ~3u;
    // Registered in `mmio_` as well, so `is_mapped` sees it and a READ answers
    // this entry's value, which stays zero. The stream table alone would make
    // the address respond to writes and fault on reads -- and a UART data
    // register that faults on read is a board that cannot be probed.
    Mapped entry;
    entry.target = at;
    mmio_[at] = entry;

    Stream stream;
    stream.enable = enable_address & ~3u;
    stream.enable_mask = enable_mask;
    streams_[at] = stream;
}

void Cpu::map_snapshot_counter(uint32_t op_address, uint32_t update_mask,
                               uint32_t valid_mask, uint32_t low_address,
                               uint32_t high_address, uint32_t high_mask,
                               uint32_t enable_address, uint32_t enable_mask,
                               uint32_t instructions_per_tick) {
    Snapshot counter;
    counter.op = op_address & ~3u;
    counter.update_mask = update_mask;
    counter.valid_mask = valid_mask;
    counter.low = low_address & ~3u;
    counter.high = high_address & ~3u;
    counter.high_mask = high_mask;
    counter.enable = enable_address & ~3u;
    counter.enable_mask = enable_mask;
    // Zero would divide by zero at the first snapshot. A board asking for a
    // counter that never advances has asked for the hang this exists to
    // prevent, so it is corrected to the fastest legal rate -- the answer
    // `core/cortexm0`'s `map_counter` gives -- and `abi.py` refuses it first.
    counter.instructions_per_tick =
        instructions_per_tick == 0 ? 1u : instructions_per_tick;

    // Registered in `mmio_` too, so `is_mapped` sees all three and their
    // accesses reach `mmio_read`/`mmio_write`, which consult `snapshots_`
    // before the stored word -- so the word these entries hold is never read.
    for (const uint32_t at : {counter.op, counter.low, counter.high}) {
        Mapped entry;
        entry.target = at;
        mmio_[at] = entry;
    }
    // Mapping the same unit twice replaces it, rather than leaving two
    // counters answering one address in whichever order the scan meets them.
    snapshots_.erase(
        std::remove_if(snapshots_.begin(), snapshots_.end(),
                       [&](const Snapshot& existing) {
                           return existing.op == counter.op;
                       }),
        snapshots_.end());
    snapshots_.push_back(counter);
}

void Cpu::note_executed() {
    for (Snapshot& counter : snapshots_) {
        // An unmapped gate counts nothing here, and is NOT silently a timer
        // that never moves: the first snapshot asked for through it faults,
        // naming the unit. This runs between instructions, where there is
        // no access to fault.
        uint32_t gate = 0;
        if (mmio_read(counter.enable, gate) && (gate & counter.enable_mask) != 0) {
            ++counter.instructions;
        }
    }
}

const std::vector<uint8_t>& Cpu::stream(uint32_t address) const {
    static const std::vector<uint8_t> none;
    const auto found = streams_.find(address & ~3u);
    return found == streams_.end() ? none : found->second.bytes;
}

bool Cpu::is_mapped(uint32_t address) const {
    return mmio_.find(address & ~3u) != mmio_.end();
}

bool Cpu::mmio_read(uint32_t address, uint32_t& out) const {
    const auto found = mmio_.find(address & ~3u);
    if (found == mmio_.end()) {
        return false;
    }
    // A snapshot counter's three registers answer its state rather than a
    // stored word, so they are checked before the stored-value path below.
    const uint32_t at = address & ~3u;
    for (const Snapshot& counter : snapshots_) {
        if (at == counter.op) {
            // UPDATE is a write trigger and reads zero; only VALID is held.
            out = counter.valid ? counter.valid_mask : 0u;
            return true;
        }
        if (at == counter.low) {
            out = static_cast<uint32_t>(counter.latched);
            return true;
        }
        if (at == counter.high) {
            out = static_cast<uint32_t>(counter.latched >> 32) & counter.high_mask;
            return true;
        }
    }

    const Mapped& entry = found->second;
    if (!entry.readable) {
        // The architecture's answer and not an absence: a W1TS register reads
        // as zero on the part. See `map_alias`.
        out = 0;
        return true;
    }
    if (entry.target == (address & ~3u)) {
        out = entry.value;
        return true;
    }
    // A readable alias is a second view of its target, so it answers what the
    // target holds. One hop only -- an alias of an alias would need a loop,
    // and a loop needs a cycle check that nothing has asked for.
    const auto origin = mmio_.find(entry.target);
    if (origin == mmio_.end()) {
        // An alias whose target was never mapped is a mistake in the board
        // description. Faulting says so; answering zero would be the silent
        // hang this whole design refuses.
        note_fault(address, false);
        return false;
    }
    out = origin->second.value;
    return true;
}

bool Cpu::mmio_write(uint32_t address, uint32_t value, uint32_t byte_mask) {
    const uint32_t at = address & ~3u;
    const auto found = mmio_.find(at);
    if (found == mmio_.end()) {
        return false;
    }
    // **Before the word behaviours, because a stream is not one**: its write
    // appends rather than stores, and falling through would latch the byte
    // into a register nobody reads.
    const auto stream = streams_.find(at);
    if (stream != streams_.end()) {
        uint32_t gate_bits = 0;
        if (!mmio_read(stream->second.enable, gate_bits)) {
            // The gate register was never mapped: a board description
            // mistake, and faulting says so. Capturing regardless would
            // print bytes a real part would have discarded.
            //
            // **`note_fault` explicitly, and it was dropped once.** The
            // first version of this branch said `mmio_read` had already
            // recorded the address; it has not, and cannot -- its
            // `mmio_.find` miss returns false WITHOUT noting, because every
            // other caller falls through to the region lookup after it. So
            // the fault kept its reset value and an executed store reported
            // `access at 0x00000000` instead of naming the FIFO, which is a
            // wrong address rather than a missing one. Found by review;
            // `test_an_executed_store_through_an_unmapped_gate_names_the_fifo`
            // is what holds it, and it has to go through `step()` because
            // `write_word` formats the address the caller passed rather than
            // the one the core recorded.
            //
            // **Through `mmio_read` rather than off `Mapped::value`**, which
            // is what this did until the OH-161 review: reading the stored
            // word directly ignores `Mapped::target`, so a gate mapped as a
            // readable ALIAS answered its own zero forever and the stream
            // went silent while `read_word` on the same address gave the bit
            // correctly. No board here aliases a clock register, so nothing
            // was wrong on the three described parts -- and the next board
            // that does would have found a peripheral that reads right and
            // transmits nothing.
            note_fault(address, false);
            return false;
        }
        // **The access must actually carry byte 0.** A FIFO's data field is
        // `[7:0]` on all three parts described here, so a byte store to
        // FIFO+1 lands in a reserved lane and transmits nothing; taking the
        // low byte of that access regardless would append a zero the part
        // never sent. `byte_mask` is the one thing that can tell them apart,
        // because `at` has already been rounded to the word.
        const bool carries_data = (byte_mask & 0xFFu) != 0;
        if (carries_data && (gate_bits & stream->second.enable_mask) != 0) {
            // The low byte only, whatever the width of the access. See
            // `map_stream`.
            stream->second.bytes.push_back(static_cast<uint8_t>(value));
        }
        return true;
    }

    // **Before the word behaviours too**: a write to a snapshot counter's
    // operation register takes a copy or does nothing, and falling through
    // would store it in a word nobody reads. A write to one of its value
    // registers does fall through, into a word `mmio_read` never answers
    // from -- which is how a read-only register ignores it.
    for (Snapshot& counter : snapshots_) {
        if (at != counter.op) {
            continue;
        }
        // `value` arrives positioned in its lane by the sub-word paths, so a
        // byte store to the register's top byte carries the bit and one to
        // its bottom byte cannot.
        if ((value & counter.update_mask) == 0) {
            return true;
        }
        if (!is_mapped(counter.enable)) {
            // The board named an enable register it never mapped: a counter
            // that could never have counted. Faulting here names the unit
            // where the reader is looking, which a zero copy would not.
            note_fault(address, false);
            return false;
        }
        counter.latched = counter.instructions / counter.instructions_per_tick;
        counter.valid = true;
        return true;
    }

    const Mapped& entry = found->second;
    const auto target = mmio_.find(entry.target);
    if (target == mmio_.end()) {
        note_fault(address, false);
        return false;
    }

    uint32_t& stored = target->second.value;
    switch (entry.op) {
    case WriteOp::Store:
        // The byte mask applies to a store and to nothing else. For the other
        // three the value has already been positioned by the caller, and
        // masking again would clear bits the write never named.
        stored = (stored & ~byte_mask) | (value & byte_mask);
        break;
    case WriteOp::Set:
        stored |= value;
        break;
    case WriteOp::Clear:
        stored &= ~value;
        break;
    case WriteOp::Xor:
        stored ^= value;
        break;
    }
    return true;
}

}  // namespace riscv32
