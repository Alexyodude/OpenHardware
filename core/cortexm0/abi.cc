// OpenHardware — the Cortex-M0+ core's C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "abi.h"

#include "cpu.h"
#include "exec.h"

namespace {

/// The opaque handle is this, so the C surface never exposes a C++ type.
struct Handle {
    cortexm0::Cpu cpu;
    // The PC the most recent cortexm0_step began at, for cortexm0_step_entry
    // (OH-225). Kept here rather than in cortexm0::Cpu: it is a fact about the
    // ABI's calls, not about the processor.
    uint32_t step_pc = 0;
};

inline Handle* as_handle(CortexM0Cpu* cpu) { return reinterpret_cast<Handle*>(cpu); }
inline const Handle* as_handle(const CortexM0Cpu* cpu) {
    return reinterpret_cast<const Handle*>(cpu);
}

}  // namespace

extern "C" {

int cortexm0_abi_version(void) { return CORTEXM0_ABI_VERSION; }

uint32_t cortexm0_regs_size(void) {
    return static_cast<uint32_t>(sizeof(CortexM0Registers));
}

CortexM0Cpu* cortexm0_new(void) {
    return reinterpret_cast<CortexM0Cpu*>(new Handle());
}

void cortexm0_free(CortexM0Cpu* cpu) {
    delete as_handle(cpu);
}

void cortexm0_reset(CortexM0Cpu* cpu) { as_handle(cpu)->cpu.reset(); }

void cortexm0_get_regs(const CortexM0Cpu* cpu, CortexM0Registers* out) {
    const cortexm0::Cpu& core = as_handle(cpu)->cpu;
    for (unsigned i = 0; i < 16; ++i) {
        out->r[i] = core.reg(i);
    }
    out->apsr = core.apsr();
}

void cortexm0_set_regs(CortexM0Cpu* cpu, const CortexM0Registers* in) {
    cortexm0::Cpu& core = as_handle(cpu)->cpu;
    for (unsigned i = 0; i < 16; ++i) {
        core.set_reg(i, in->r[i]);
    }
    core.set_apsr(in->apsr);
}

int cortexm0_read_word(const CortexM0Cpu* cpu, uint32_t address, uint32_t* out) {
    return as_handle(cpu)->cpu.read_word(address, *out) ? 1 : 0;
}

int cortexm0_write_word(CortexM0Cpu* cpu, uint32_t address, uint32_t value) {
    return as_handle(cpu)->cpu.write_word(address, value) ? 1 : 0;
}

int cortexm0_write_halfword(CortexM0Cpu* cpu, uint32_t address, uint16_t value) {
    return as_handle(cpu)->cpu.write_halfword(address, value) ? 1 : 0;
}

int cortexm0_write_block(CortexM0Cpu* cpu, uint32_t address, const uint8_t* data,
                         uint32_t length) {
    cortexm0::Cpu& core = as_handle(cpu)->cpu;
    // Range-checked as a whole before writing any of it, so a block that runs
    // off the end of the window leaves memory untouched rather than
    // half-written. A partial write is the worst of the three outcomes: it
    // reports failure and has already changed state.
    if (!core.in_range(address, length)) {
        return 0;
    }
    for (uint32_t i = 0; i < length; ++i) {
        core.write_byte(address + i, data[i]);
    }
    return 1;
}

int cortexm0_read_block(const CortexM0Cpu* cpu, uint32_t address, uint8_t* out,
                        uint32_t length) {
    const cortexm0::Cpu& core = as_handle(cpu)->cpu;
    if (!core.in_range(address, length)) {
        return 0;
    }
    for (uint32_t i = 0; i < length; ++i) {
        out[i] = core.read_byte(address + i);
    }
    return 1;
}

void cortexm0_clear_memory(CortexM0Cpu* cpu) { as_handle(cpu)->cpu.clear_memory(); }

void cortexm0_clear_registers(CortexM0Cpu* cpu) {
    as_handle(cpu)->cpu.clear_registers();
}

int cortexm0_add_region(CortexM0Cpu* cpu, uint32_t base, uint32_t size,
                        int executable, uint8_t fill) {
    return as_handle(cpu)->cpu.add_region(base, size, executable != 0, fill) ? 1 : 0;
}

void cortexm0_clear_regions(CortexM0Cpu* cpu) {
    as_handle(cpu)->cpu.clear_regions();
}

void cortexm0_map_register(CortexM0Cpu* cpu, uint32_t address, uint32_t value) {
    as_handle(cpu)->cpu.map_register(address, value);
}

void cortexm0_map_alias(CortexM0Cpu* cpu, uint32_t address, uint32_t target,
                        int op, int readable) {
    as_handle(cpu)->cpu.map_alias(address, target,
                                  static_cast<cortexm0::WriteOp>(op),
                                  readable != 0);
}

void cortexm0_map_mirror(CortexM0Cpu* cpu, uint32_t address, uint32_t source,
                         int invert, uint32_t mask) {
    as_handle(cpu)->cpu.map_mirror(address, source, invert != 0, mask);
}

void cortexm0_map_constant(CortexM0Cpu* cpu, uint32_t address, uint32_t value) {
    as_handle(cpu)->cpu.map_constant(address, value);
}

void cortexm0_map_stream(CortexM0Cpu* cpu, uint32_t address,
                         uint32_t enable_address, uint32_t enable_mask) {
    as_handle(cpu)->cpu.map_stream(address, enable_address, enable_mask);
}

uint32_t cortexm0_stream(const CortexM0Cpu* cpu, uint32_t address, uint8_t* out,
                         uint32_t capacity) {
    const std::vector<uint8_t>& bytes = as_handle(cpu)->cpu.stream(address);
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

void cortexm0_map_counter(CortexM0Cpu* cpu, uint32_t address,
                          uint32_t instructions_per_tick) {
    as_handle(cpu)->cpu.map_counter(address, instructions_per_tick);
}

uint64_t cortexm0_executed(const CortexM0Cpu* cpu) {
    return as_handle(cpu)->cpu.executed();
}

int cortexm0_is_mapped(const CortexM0Cpu* cpu, uint32_t address) {
    return as_handle(cpu)->cpu.is_mapped(address) ? 1 : 0;
}

uint32_t cortexm0_fault_address(const CortexM0Cpu* cpu) {
    return as_handle(cpu)->cpu.fault_address();
}

int cortexm0_in_range(const CortexM0Cpu* cpu, uint32_t address, uint32_t bytes) {
    return as_handle(cpu)->cpu.in_range(address, bytes) ? 1 : 0;
}

int cortexm0_fault_was_fetch(const CortexM0Cpu* cpu) {
    return as_handle(cpu)->cpu.fault_was_fetch() ? 1 : 0;
}

int cortexm0_step(CortexM0Cpu* cpu) {
    Handle* handle = as_handle(cpu);
    cortexm0::Cpu& processor = handle->cpu;
    // Recorded before stepping, so before the exception entry a due SysTick
    // makes of a step and before the fetch: the step advances PC before it
    // executes, so if the core then faults on the host the PC no longer says
    // which step it was, and this does.
    handle->step_pc = processor.reg(cortexm0::kPc);
    const cortexm0::StepResult result = cortexm0::step(processor);
    // Only a retired instruction ages the machine. On Unimplemented or
    // MemoryFault the processor is untouched, PC included, so a program
    // stopped by one must not go on accruing virtual time -- a caller that
    // steps a halted core in a loop would otherwise watch its timer advance.
    if (result == cortexm0::StepResult::Ok) {
        processor.note_executed();
    }
    return static_cast<int>(result);
}

uint32_t cortexm0_step_entry(const CortexM0Cpu* cpu) {
    return cpu == nullptr ? 0u : as_handle(cpu)->step_pc;
}

}  // extern "C"
