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
#define AVR_ABI_VERSION 1

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

AVR_API uint32_t avr_fault_address(const AvrCpu* cpu);
AVR_API int avr_fault_was_program(const AvrCpu* cpu);

#ifdef __cplusplus
}
#endif

#endif
