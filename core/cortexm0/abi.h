// OpenHardware — the Cortex-M0+ core's C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The same contract the i8086 core's abi.h keeps, and for the same reason: a
// struct declared on both sides of a ctypes boundary is a shape agreed twice,
// and a field added to one side and not the other neither fails to compile nor
// fails to load -- it silently reads the wrong bytes. `cortexm0_abi_version`
// and `cortexm0_regs_size` exist so Python can assert the two agree before
// running anything.

#ifndef OPENHARDWARE_CORTEXM0_ABI_H
#define OPENHARDWARE_CORTEXM0_ABI_H

#include <stdint.h>

#if defined(_WIN32)
#define CORTEXM0_API __declspec(dllexport)
#else
#define CORTEXM0_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// Bumped whenever this header's shape changes. Python refuses to run against
/// a library that disagrees, which turns a silent struct mismatch into a clear
/// failure at import.
#define CORTEXM0_ABI_VERSION 3

/// r0-r15, then the flags.
///
/// The register array is indexed, not named, because the corpus delivers
/// `regs` as a 16-element list and every crossing is positional there. That is
/// the opposite of the i8086 core's by-name convention, and it is deliberate:
/// matching the corpus's own shape is what removes the translation step where
/// a transcription error would live.
///
/// r13 is SP, r14 is LR, r15 is PC. `apsr` carries N, Z, C and V in bits 31
/// down to 28 and nothing else -- the unmodelled bits are dropped on write
/// rather than stored, so they cannot round-trip and look supported.
typedef struct {
    uint32_t r[16];
    uint32_t apsr;
} CortexM0Registers;

typedef struct CortexM0Cpu CortexM0Cpu;

CORTEXM0_API int cortexm0_abi_version(void);
/// sizeof(CortexM0Registers), so Python can check its mirror matches.
CORTEXM0_API uint32_t cortexm0_regs_size(void);

/// The modelled SRAM window, so Python need not hardcode either number.
/// See cpu.h for why there is a window rather than a 4 GB address space.
CORTEXM0_API uint32_t cortexm0_sram_base(void);
CORTEXM0_API uint32_t cortexm0_sram_size(void);

CORTEXM0_API CortexM0Cpu* cortexm0_new(void);
CORTEXM0_API void cortexm0_free(CortexM0Cpu* cpu);
CORTEXM0_API void cortexm0_reset(CortexM0Cpu* cpu);

CORTEXM0_API void cortexm0_get_regs(const CortexM0Cpu* cpu, CortexM0Registers* out);
CORTEXM0_API void cortexm0_set_regs(CortexM0Cpu* cpu, const CortexM0Registers* in);

/// 0 on a fault, having read or written nothing. Not a zero-filled read: an
/// address this core does not model is not the same as an address holding
/// zero, and a conformance harness has to be able to tell them apart.
CORTEXM0_API int cortexm0_read_word(const CortexM0Cpu* cpu, uint32_t address,
                                    uint32_t* out);
CORTEXM0_API int cortexm0_write_word(CortexM0Cpu* cpu, uint32_t address, uint32_t value);
CORTEXM0_API int cortexm0_write_halfword(CortexM0Cpu* cpu, uint32_t address,
                                         uint16_t value);

/// Bulk transfer, so a conformance case's scratch words are one call rather
/// than one per word. The corpus has thousands of cases.
CORTEXM0_API int cortexm0_write_block(CortexM0Cpu* cpu, uint32_t address,
                                      const uint8_t* data, uint32_t length);
CORTEXM0_API int cortexm0_read_block(const CortexM0Cpu* cpu, uint32_t address,
                                     uint8_t* out, uint32_t length);

CORTEXM0_API void cortexm0_clear_memory(CortexM0Cpu* cpu);

/// Make one memory-mapped word respond, reads-as-written. See cpu.h: only
/// registered addresses respond, so an unmodelled peripheral still faults
/// rather than reading as zero and hanging a poll loop.
CORTEXM0_API void cortexm0_map_register(CortexM0Cpu* cpu, uint32_t address,
                                        uint32_t value);
CORTEXM0_API int cortexm0_is_mapped(const CortexM0Cpu* cpu, uint32_t address);

/// Execute one instruction at PC, advancing PC past it.
///
/// Returns 0 on success, 1 for an encoding this core does not implement, and
/// 2 when the fetch itself was outside the modelled SRAM.
///
/// On 1 and 2 the processor is untouched, PC included -- so a caller can
/// report exactly which instruction stopped it, and a conformance case can
/// never pass by accident because an unwritten encoding behaved like a NOP.
///
/// 2 is separate from 1 because they mean different things to whoever is
/// watching: 1 is a hole in this emulator's instruction set, 2 is a program
/// that ran off into space this core does not model.
CORTEXM0_API int cortexm0_step(CortexM0Cpu* cpu);

/// The address of the most recent failed access, and whether it was a fetch.
/// Only meaningful straight after a step returned 2. See cpu.h for why the
/// address is the diagnostic that matters when bringing up firmware.
CORTEXM0_API uint32_t cortexm0_fault_address(const CortexM0Cpu* cpu);
CORTEXM0_API int cortexm0_fault_was_fetch(const CortexM0Cpu* cpu);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif
