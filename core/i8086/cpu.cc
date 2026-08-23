// OpenHardware - Intel 8086/8088 processor state.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "cpu.h"

#include <algorithm>

namespace i8086 {

Cpu::Cpu() : memory_(kMemorySize, 0) { Reset(); }

void Cpu::Reset() {
    regs_ = Registers{};
    // The 8086 fetches its first instruction from 0xFFFF:0000, sixteen bytes
    // below the top of the space -- which is why a reset vector is a jump.
    regs_.cs = 0xFFFF;
    regs_.ip = 0x0000;
    regs_.flags = kFlagsAlwaysSet;
}

void Cpu::set_regs(const Registers& value) {
    regs_ = value;
    regs_.flags |= kFlagsAlwaysSet;
}

std::uint8_t Cpu::ReadByte(std::uint32_t address) const {
    return memory_[address & 0xFFFFFu];
}

void Cpu::WriteByte(std::uint32_t address, std::uint8_t value) {
    memory_[address & 0xFFFFFu] = value;
}

std::uint16_t Cpu::ReadWord(std::uint32_t address) const {
    const std::uint16_t low = ReadByte(address);
    const std::uint16_t high = ReadByte(address + 1);
    return static_cast<std::uint16_t>(low | (high << 8));
}

void Cpu::WriteWord(std::uint32_t address, std::uint16_t value) {
    WriteByte(address, static_cast<std::uint8_t>(value & 0xFF));
    WriteByte(address + 1, static_cast<std::uint8_t>(value >> 8));
}

std::uint16_t Cpu::ReadWordAt(std::uint16_t segment, std::uint16_t offset) const {
    const std::uint16_t low = ReadByte(Physical(segment, offset));
    const std::uint16_t high =
        ReadByte(Physical(segment, static_cast<std::uint16_t>(offset + 1)));
    return static_cast<std::uint16_t>(low | (high << 8));
}

void Cpu::WriteWordAt(std::uint16_t segment, std::uint16_t offset, std::uint16_t value) {
    WriteByte(Physical(segment, offset), static_cast<std::uint8_t>(value & 0xFF));
    WriteByte(Physical(segment, static_cast<std::uint16_t>(offset + 1)),
              static_cast<std::uint8_t>(value >> 8));
}

void Cpu::ClearMemory() { std::fill(memory_.begin(), memory_.end(), std::uint8_t{0}); }

}  // namespace i8086
