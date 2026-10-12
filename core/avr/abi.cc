// OpenHardware — the AVR core's C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "abi.h"

#include "cpu.h"
#include "exec.h"

namespace {

struct Handle {
    avr::Cpu cpu;
    // The word the most recent avr_step began at, for avr_step_entry
    // (OH-223). Kept here rather than in avr::Cpu: it is a fact about the
    // ABI's calls, not about the part.
    uint32_t step_pc = 0;
};

inline Handle* as_handle(AvrCpu* cpu) { return reinterpret_cast<Handle*>(cpu); }
inline const Handle* as_handle(const AvrCpu* cpu) {
    return reinterpret_cast<const Handle*>(cpu);
}

}  // namespace

extern "C" {

int avr_abi_version(void) { return AVR_ABI_VERSION; }

AvrCpu* avr_new(void) { return reinterpret_cast<AvrCpu*>(new Handle()); }
void avr_free(AvrCpu* cpu) { delete as_handle(cpu); }
void avr_reset(AvrCpu* cpu) { as_handle(cpu)->cpu.reset(); }

void avr_configure(AvrCpu* cpu, uint32_t program_words, uint32_t data_bytes) {
    as_handle(cpu)->cpu.configure(program_words, data_bytes);
}
uint32_t avr_program_words(const AvrCpu* cpu) {
    return as_handle(cpu)->cpu.program_words();
}
uint32_t avr_data_bytes(const AvrCpu* cpu) {
    return as_handle(cpu)->cpu.data_bytes();
}

int avr_read_program(const AvrCpu* cpu, uint32_t address, uint16_t* out) {
    return as_handle(cpu)->cpu.read_program(address, *out) ? 1 : 0;
}
int avr_write_program(AvrCpu* cpu, uint32_t address, uint16_t value) {
    return as_handle(cpu)->cpu.write_program(address, value) ? 1 : 0;
}
int avr_read_data(const AvrCpu* cpu, uint16_t address, uint8_t* out) {
    return as_handle(cpu)->cpu.read_data(address, *out) ? 1 : 0;
}
int avr_write_data(AvrCpu* cpu, uint16_t address, uint8_t value) {
    return as_handle(cpu)->cpu.write_data(address, value) ? 1 : 0;
}

int avr_write_program_block(AvrCpu* cpu, uint32_t address, const uint8_t* data,
                            uint32_t length) {
    // Odd lengths are refused rather than rounded. Program memory is words,
    // and half a word is a question about what the other half holds that the
    // caller has to answer.
    if ((length & 1u) != 0) {
        return 0;
    }
    avr::Cpu& core = as_handle(cpu)->cpu;
    const uint32_t words = length / 2;
    // Checked whole before anything is written, so an image that overruns the
    // space leaves flash untouched rather than half-loaded.
    if (address > core.program_words() || words > core.program_words() - address) {
        return 0;
    }
    for (uint32_t i = 0; i < words; ++i) {
        core.write_program(address + i,
                           static_cast<uint16_t>(data[i * 2] |
                                                 (data[i * 2 + 1] << 8)));
    }
    return 1;
}

uint8_t avr_reg(const AvrCpu* cpu, uint8_t index) {
    return as_handle(cpu)->cpu.reg(index);
}
void avr_set_reg(AvrCpu* cpu, uint8_t index, uint8_t value) {
    as_handle(cpu)->cpu.set_reg(index, value);
}
uint8_t avr_sreg(const AvrCpu* cpu) { return as_handle(cpu)->cpu.sreg(); }
uint16_t avr_sp(const AvrCpu* cpu) { return as_handle(cpu)->cpu.sp(); }
uint32_t avr_pc(const AvrCpu* cpu) { return as_handle(cpu)->cpu.pc(); }
void avr_set_pc(AvrCpu* cpu, uint32_t value) { as_handle(cpu)->cpu.set_pc(value); }
uint64_t avr_executed(const AvrCpu* cpu) { return as_handle(cpu)->cpu.executed(); }

int avr_map_timer(AvrCpu* cpu, uint16_t counter, uint16_t flag, uint16_t enable,
                  uint8_t bit, uint32_t vector, uint32_t instructions_per_tick) {
    avr::Timer timer;
    timer.counter = counter;
    timer.flag = flag;
    timer.enable = enable;
    timer.bit = bit;
    timer.vector = vector;
    timer.instructions_per_tick = instructions_per_tick;
    return as_handle(cpu)->cpu.map_timer(timer) ? 1 : 0;
}

int avr_map_usart(AvrCpu* cpu, uint16_t data, uint16_t status, uint16_t control,
                  uint8_t enable_bit, uint8_t ready_mask) {
    avr::Usart usart;
    usart.data = data;
    usart.status = status;
    usart.control = control;
    usart.enable_bit = enable_bit;
    usart.ready_mask = ready_mask;
    return as_handle(cpu)->cpu.map_usart(usart) ? 1 : 0;
}

uint32_t avr_usart_output(const AvrCpu* cpu, uint8_t* out, uint32_t max) {
    const std::vector<uint8_t>& sent = as_handle(cpu)->cpu.usart_output();
    const uint32_t length = static_cast<uint32_t>(sent.size());
    if (out != nullptr) {
        const uint32_t take = length < max ? length : max;
        for (uint32_t i = 0; i < take; ++i) {
            out[i] = sent[i];
        }
    }
    return length;
}

int avr_interrupt_inhibited(const AvrCpu* cpu) {
    return as_handle(cpu)->cpu.interrupt_inhibited() ? 1 : 0;
}

uint8_t avr_timer_count(const AvrCpu* cpu) {
    const avr::Cpu& core = as_handle(cpu)->cpu;
    return core.has_timer() ? core.timer_count() : 0;
}

int avr_step(AvrCpu* cpu) {
    Handle* handle = as_handle(cpu);
    avr::Cpu& core = handle->cpu;
    // Recorded before stepping, which advances the PC before it executes: if
    // the core then faults on the host, the PC no longer says which
    // instruction it was, and this does.
    handle->step_pc = core.pc();
    const avr::StepResult result = avr::step(core);
    if (result == avr::StepResult::Ok) {
        core.note_executed();
    }
    return static_cast<int>(result);
}

uint32_t avr_step_entry(const AvrCpu* cpu) { return as_handle(cpu)->step_pc; }

uint32_t avr_fault_address(const AvrCpu* cpu) {
    return as_handle(cpu)->cpu.fault_address();
}
int avr_fault_was_program(const AvrCpu* cpu) {
    return as_handle(cpu)->cpu.fault_was_program() ? 1 : 0;
}

}  // extern "C"
