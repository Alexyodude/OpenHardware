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
    extensions_ = 0;
    regions_.clear();
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
    const Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    out = region->bytes[address - region->base];
    return true;
}

bool Cpu::write_byte_checked(uint32_t address, uint8_t value) {
    Region* region = region_for(address, 1);
    if (region == nullptr) {
        note_fault(address, false);
        return false;
    }
    region->bytes[address - region->base] = value;
    return true;
}

bool Cpu::read_halfword(uint32_t address, uint16_t& out) const {
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

void Cpu::clear_regions() { regions_.clear(); }

}  // namespace riscv32
