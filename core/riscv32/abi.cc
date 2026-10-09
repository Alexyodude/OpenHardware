// OpenHardware — the RV32 core behind a C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Translation only. Every function here is a cast and a call: any behaviour
// that appeared in this file would be behaviour the C++ tests cannot reach and
// only the Python side exercises.

#include <algorithm>

#include "abi.h"

#include "cpu.h"
#include "exec.h"

namespace {

riscv32::Cpu* as_cpu(Riscv32Cpu* handle) {
    return reinterpret_cast<riscv32::Cpu*>(handle);
}

const riscv32::Cpu* as_cpu(const Riscv32Cpu* handle) {
    return reinterpret_cast<const riscv32::Cpu*>(handle);
}

}  // namespace

extern "C" {

int riscv32_abi_version(void) { return RISCV32_ABI_VERSION; }

uint32_t riscv32_regs_size(void) {
    return static_cast<uint32_t>(sizeof(Riscv32Registers));
}

Riscv32Cpu* riscv32_new(void) {
    return reinterpret_cast<Riscv32Cpu*>(new riscv32::Cpu());
}

void riscv32_free(Riscv32Cpu* cpu) { delete as_cpu(cpu); }

void riscv32_reset(Riscv32Cpu* cpu) { as_cpu(cpu)->reset(); }

void riscv32_get_regs(const Riscv32Cpu* cpu, Riscv32Registers* out) {
    const riscv32::Cpu* core = as_cpu(cpu);
    for (unsigned index = 0; index < riscv32::kRegisters; ++index) {
        out->x[index] = core->reg(index);
    }
    out->pc = core->pc();
}

void riscv32_set_regs(Riscv32Cpu* cpu, const Riscv32Registers* in) {
    riscv32::Cpu* core = as_cpu(cpu);
    // From 1, not 0. x0 is hardwired and `set_reg` discards it anyway; naming
    // the range here says why rather than relying on that.
    for (unsigned index = 1; index < riscv32::kRegisters; ++index) {
        core->set_reg(index, in->x[index]);
    }
    core->set_pc(in->pc);
}

uint32_t riscv32_extensions(const Riscv32Cpu* cpu) {
    return as_cpu(cpu)->extensions();
}

void riscv32_set_extensions(Riscv32Cpu* cpu, uint32_t mask) {
    as_cpu(cpu)->set_extensions(mask);
}

int riscv32_read_word(const Riscv32Cpu* cpu, uint32_t address, uint32_t* out) {
    return as_cpu(cpu)->read_word(address, *out) ? 1 : 0;
}

int riscv32_write_word(Riscv32Cpu* cpu, uint32_t address, uint32_t value) {
    return as_cpu(cpu)->write_word(address, value) ? 1 : 0;
}

int riscv32_write_block(Riscv32Cpu* cpu, uint32_t address, const uint8_t* data,
                        uint32_t length) {
    riscv32::Cpu* core = as_cpu(cpu);
    // The whole span first, so an image that overruns its region writes none
    // of it. A half-written image runs for a while and then does something
    // inexplicable, which costs far more to diagnose than a refused load.
    if (length != 0 && !core->in_range(address, length)) {
        return 0;
    }
    for (uint32_t offset = 0; offset < length; ++offset) {
        core->write_byte(address + offset, data[offset]);
    }
    return 1;
}

int riscv32_read_block(const Riscv32Cpu* cpu, uint32_t address, uint8_t* out,
                       uint32_t length) {
    const riscv32::Cpu* core = as_cpu(cpu);
    if (length != 0 && !core->in_range(address, length)) {
        return 0;
    }
    for (uint32_t offset = 0; offset < length; ++offset) {
        out[offset] = core->read_byte(address + offset);
    }
    return 1;
}

void riscv32_clear_memory(Riscv32Cpu* cpu) { as_cpu(cpu)->clear_memory(); }

int riscv32_add_region(Riscv32Cpu* cpu, uint32_t base, uint32_t size,
                       int executable, uint8_t fill) {
    return as_cpu(cpu)->add_region(base, size, executable != 0, fill) ? 1 : 0;
}

void riscv32_clear_regions(Riscv32Cpu* cpu) { as_cpu(cpu)->clear_regions(); }

void riscv32_map_register(Riscv32Cpu* cpu, uint32_t address, uint32_t value) {
    as_cpu(cpu)->map_register(address, value);
}

void riscv32_map_alias(Riscv32Cpu* cpu, uint32_t address, uint32_t target,
                       int op, int readable) {
    // An out-of-range `op` becomes Store rather than reinterpreting whatever
    // integer arrived as an enumerator, which is undefined behaviour and would
    // pick a behaviour at the compiler's discretion.
    riscv32::WriteOp write_op = riscv32::WriteOp::Store;
    switch (op) {
    case 1: write_op = riscv32::WriteOp::Set; break;
    case 2: write_op = riscv32::WriteOp::Clear; break;
    case 3: write_op = riscv32::WriteOp::Xor; break;
    default: break;
    }
    as_cpu(cpu)->map_alias(address, target, write_op, readable != 0);
}

void riscv32_map_stream(Riscv32Cpu* cpu, uint32_t address,
                        uint32_t enable_address, uint32_t enable_mask) {
    as_cpu(cpu)->map_stream(address, enable_address, enable_mask);
}

uint32_t riscv32_stream(const Riscv32Cpu* cpu, uint32_t address, uint8_t* out,
                        uint32_t capacity) {
    const std::vector<uint8_t>& bytes = as_cpu(cpu)->stream(address);
    const uint32_t length = static_cast<uint32_t>(bytes.size());
    // Copy what fits and report what there is. A caller that sized its buffer
    // from a previous call can tell the stream grew, rather than reading a
    // prefix and believing it complete.
    if (out != nullptr && capacity != 0) {
        const uint32_t copied = length < capacity ? length : capacity;
        std::copy(bytes.begin(), bytes.begin() + copied, out);
    }
    return length;
}

void riscv32_map_snapshot_counter(Riscv32Cpu* cpu, uint32_t op_address,
                                  uint32_t update_mask, uint32_t valid_mask,
                                  uint32_t low_address, uint32_t high_address,
                                  uint32_t high_mask, uint32_t enable_address,
                                  uint32_t enable_mask,
                                  uint32_t instructions_per_tick) {
    as_cpu(cpu)->map_snapshot_counter(op_address, update_mask, valid_mask,
                                      low_address, high_address, high_mask,
                                      enable_address, enable_mask,
                                      instructions_per_tick);
}

void riscv32_map_input(Riscv32Cpu* cpu, uint32_t address, uint32_t out_address,
                       uint32_t enable_address, uint32_t pad_base,
                       uint32_t pad_stride, uint32_t pads,
                       uint32_t input_enable_mask, uint32_t pull_up_mask,
                       uint32_t pull_down_mask) {
    as_cpu(cpu)->map_input(address, out_address, enable_address, pad_base,
                           pad_stride, pads, input_enable_mask, pull_up_mask,
                           pull_down_mask);
}

int riscv32_drive_input(Riscv32Cpu* cpu, uint32_t address, uint32_t driven,
                        uint32_t levels) {
    return as_cpu(cpu)->drive_input(address, driven, levels) ? 1 : 0;
}

int riscv32_is_mapped(const Riscv32Cpu* cpu, uint32_t address) {
    return as_cpu(cpu)->is_mapped(address) ? 1 : 0;
}

void riscv32_clear_mmio(Riscv32Cpu* cpu) { as_cpu(cpu)->clear_mmio(); }

int riscv32_step(Riscv32Cpu* cpu) {
    return static_cast<int>(riscv32::step(*as_cpu(cpu)));
}

uint32_t riscv32_fault_address(const Riscv32Cpu* cpu) {
    return as_cpu(cpu)->fault_address();
}

int riscv32_fault_was_fetch(const Riscv32Cpu* cpu) {
    return as_cpu(cpu)->fault_was_fetch() ? 1 : 0;
}

int riscv32_in_range(const Riscv32Cpu* cpu, uint32_t address, uint32_t bytes) {
    return as_cpu(cpu)->in_range(address, bytes) ? 1 : 0;
}

}  // extern "C"
