// OpenHardware — Cortex-M0+ registers, flags and the memory map.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "cpu.h"

#include <algorithm>

namespace cortexm0 {
namespace {

/// One entry of the map. Kept local because the map is this file's business:
/// callers ask about addresses, never about regions.
struct Region {
    uint32_t base;
    uint32_t size;
};

constexpr Region kFlash{kFlashBase, kFlashSize};
constexpr Region kSram{kSramBase, kSramSize};

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

Cpu::Cpu() : flash_(kFlashSize, 0), sram_(kSramSize, 0) {}

void Cpu::reset() {
    regs_.fill(0);
    apsr_ = 0;
    clear_memory();
}

void Cpu::clear_memory() {
    std::fill(flash_.begin(), flash_.end(), static_cast<uint8_t>(0));
    std::fill(sram_.begin(), sram_.end(), static_cast<uint8_t>(0));
}

void Cpu::map_register(uint32_t address, uint32_t value) {
    mmio_[address & ~3u] = value;
}

bool Cpu::is_mapped(uint32_t address) const {
    return mmio_.find(address & ~3u) != mmio_.end();
}

const std::vector<uint8_t>* Cpu::region_for(uint32_t address, uint32_t bytes,
                                            uint32_t& offset) const {
    if (contains(kSram, address, bytes, offset)) {
        // SRAM first: it is where a running program spends almost every
        // access, and where the corpus puts everything.
        return &sram_;
    }
    if (contains(kFlash, address, bytes, offset)) {
        return &flash_;
    }
    fault_address_ = address;
    fault_was_fetch_ = false;
    return nullptr;
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
    const auto mapped = mmio_.find(address & ~3u);
    if (mapped != mmio_.end()) {
        out = mapped->second;
        return true;
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
    const auto mapped = mmio_.find(address & ~3u);
    if (mapped != mmio_.end()) {
        mapped->second = value;
        return true;
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
    read_byte_checked(address, value);
    return value;
}

void Cpu::write_byte(uint32_t address, uint8_t value) {
    write_byte_checked(address, value);
}

}  // namespace cortexm0
