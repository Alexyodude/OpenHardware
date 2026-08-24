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
}

void Cpu::clear_registers() { mmio_.clear(); }

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

bool Cpu::is_mapped(uint32_t address) const {
    return mmio_.find(address & ~3u) != mmio_.end();
}

bool Cpu::mmio_read(uint32_t address, uint32_t& out) const {
    const auto found = mmio_.find(address & ~3u);
    if (found == mmio_.end()) {
        return false;
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

bool Cpu::mmio_write(uint32_t address, uint32_t value) {
    const auto found = mmio_.find(address & ~3u);
    if (found == mmio_.end()) {
        return false;
    }
    const Mapped& entry = found->second;
    const auto target = mmio_.find(entry.target);
    if (target == mmio_.end()) {
        note_fault(address, false);
        return false;
    }
    uint32_t& stored = target->second.value;
    switch (entry.op) {
        case WriteOp::Store: stored = value; break;
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

bool Cpu::read_halfword(uint32_t address, uint16_t& out) const {
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
    uint32_t offset = 0;
    const std::vector<uint8_t>* region = region_for(address, 1, offset);
    if (region == nullptr) {
        return false;
    }
    out = (*region)[offset];
    return true;
}

bool Cpu::write_byte_checked(uint32_t address, uint8_t value) {
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
