// OpenHardware — the AVR core's C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The same contract the other three cores keep. The one shape difference is
// that every accessor names WHICH address space it means, because this machine
// has two and they overlap -- see cpu.h.

#ifndef OPENHARDWARE_AVR_ABI_H
#define OPENHARDWARE_AVR_ABI_H

#include <stdint.h>

#if defined(_WIN32)
#define AVR_API __declspec(dllexport)
#else
#define AVR_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// Bumped whenever this header's shape changes.
#define AVR_ABI_VERSION 4

typedef struct AvrCpu AvrCpu;

AVR_API int avr_abi_version(void);

AVR_API AvrCpu* avr_new(void);
AVR_API void avr_free(AvrCpu* cpu);
AVR_API void avr_reset(AvrCpu* cpu);

/// Size the two spaces. `program_words` is in 16-bit WORDS, because that is
/// what the PC counts; `data_bytes` is in bytes.
AVR_API void avr_configure(AvrCpu* cpu, uint32_t program_words, uint32_t data_bytes);
AVR_API uint32_t avr_program_words(const AvrCpu* cpu);
AVR_API uint32_t avr_data_bytes(const AvrCpu* cpu);

/// Give the machine timer 0. Call AFTER `avr_configure`, which resets.
///
/// Flat parameters rather than a struct pointer, so the Python binding is
/// ctypes scalars and nothing has to agree about a layout across the boundary
/// -- the same reason every other call here takes its arguments this way.
///
/// `counter`, `flag` and `enable` are DATA addresses; `vector` is a WORD
/// address. Those two spaces overlap on this machine, which is why each is
/// named. Returns 0 and maps nothing if any of them is out of range, if `bit`
/// is not 0-7, or if `instructions_per_tick` is zero.
AVR_API int avr_map_timer(AvrCpu* cpu, uint16_t counter, uint16_t flag,
                          uint16_t enable, uint8_t bit, uint32_t vector,
                          uint32_t instructions_per_tick);

/// What `counter` reads. 0 with no timer mapped.
AVR_API uint8_t avr_timer_count(const AvrCpu* cpu);

/// Give the machine a USART. Call AFTER `avr_configure`, which resets.
///
/// `data`, `status` and `control` are DATA addresses. `ready_mask` is the bits
/// of `status` that always read set -- UDRE0 and TXC0, which is what makes
/// Arduino's fast path fire and its `flush()` return. Returns 0 and maps
/// nothing if any address is out of range or `enable_bit` is not 0-7.
AVR_API int avr_map_usart(AvrCpu* cpu, uint16_t data, uint16_t status,
                          uint16_t control, uint8_t enable_bit,
                          uint8_t ready_mask);

/// Everything the USART has transmitted, oldest byte first.
///
/// Returns the true length whether or not `out` is null, so a caller asks for
/// the length first and reads second rather than guessing a buffer size --
/// the arrangement `cortexm0_stream` already uses.
AVR_API uint32_t avr_usart_output(const AvrCpu* cpu, uint8_t* out, uint32_t max);

/// 1 while an interrupt cannot be taken on the next step because `sei` or
/// `reti` just ran. A property of the machine and not an implementation
/// detail: it is the difference between the next step being an instruction
/// and the next step being a vector.
AVR_API int avr_interrupt_inhibited(const AvrCpu* cpu);

/// 0 on a refused access, having read or written nothing.
AVR_API int avr_read_program(const AvrCpu* cpu, uint32_t address, uint16_t* out);
AVR_API int avr_write_program(AvrCpu* cpu, uint32_t address, uint16_t value);
AVR_API int avr_read_data(const AvrCpu* cpu, uint16_t address, uint8_t* out);
AVR_API int avr_write_data(AvrCpu* cpu, uint16_t address, uint8_t value);

/// Load a compiled image into program memory. `length` is in BYTES and must be
/// even; the image is little-endian words, which is what avr-objcopy emits.
AVR_API int avr_write_program_block(AvrCpu* cpu, uint32_t address,
                                    const uint8_t* data, uint32_t length);

AVR_API uint8_t avr_reg(const AvrCpu* cpu, uint8_t index);
AVR_API void avr_set_reg(AvrCpu* cpu, uint8_t index, uint8_t value);
AVR_API uint8_t avr_sreg(const AvrCpu* cpu);
AVR_API uint16_t avr_sp(const AvrCpu* cpu);
AVR_API uint32_t avr_pc(const AvrCpu* cpu);
AVR_API void avr_set_pc(AvrCpu* cpu, uint32_t value);
AVR_API uint64_t avr_executed(const AvrCpu* cpu);

/// 0 ok, 1 an encoding this core does not implement, 2 a refused access.
AVR_API int avr_step(AvrCpu* cpu);

/// The word the most recent avr_step began at; zero before the first.
///
/// For when the core faults on the host part-way through an instruction
/// (OH-223): avr_step advances the PC before executing, so afterwards the PC
/// names the next instruction rather than the one that faulted. Every step
/// records it, at the cost of one store, so a caller need not read the PC
/// before each step to have it.
AVR_API uint32_t avr_step_entry(const AvrCpu* cpu);

AVR_API uint32_t avr_fault_address(const AvrCpu* cpu);
AVR_API int avr_fault_was_program(const AvrCpu* cpu);

#ifdef __cplusplus
}
#endif

#endif
