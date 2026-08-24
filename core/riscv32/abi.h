// OpenHardware — the RV32 core's C ABI.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// The same contract the i8086 and Cortex-M0 headers keep, and for the same
// reason: a struct declared on both sides of a ctypes boundary is a shape
// agreed twice, and a field added to one side and not the other neither fails
// to compile nor fails to load -- it silently reads the wrong bytes.
// `riscv32_abi_version` and `riscv32_regs_size` exist so Python can assert the
// two agree before running anything.

#ifndef OPENHARDWARE_RISCV32_ABI_H
#define OPENHARDWARE_RISCV32_ABI_H

#include <stdint.h>

#if defined(_WIN32)
#define RISCV32_API __declspec(dllexport)
#else
#define RISCV32_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// Bumped whenever this header's shape changes. Python refuses to run against
/// a library that disagrees, which turns a silent struct mismatch into a clear
/// failure at import.
#define RISCV32_ABI_VERSION 1

/// x0 through x31, then PC.
///
/// Indexed rather than named, and in architectural order, because that is the
/// order rvcpp's `RVCore::regs[32]` uses and every crossing with the oracle is
/// positional. Matching the oracle's own shape removes the translation step
/// where a transcription error would live.
///
/// x0 is present and always reads zero. Omitting it would renumber all 31
/// others by one against every disassembly, every trace line and the oracle.
typedef struct {
    uint32_t x[32];
    uint32_t pc;
} Riscv32Registers;

typedef struct Riscv32Cpu Riscv32Cpu;

RISCV32_API int riscv32_abi_version(void);
/// sizeof(Riscv32Registers), so Python can check its mirror matches.
RISCV32_API uint32_t riscv32_regs_size(void);

RISCV32_API Riscv32Cpu* riscv32_new(void);
RISCV32_API void riscv32_free(Riscv32Cpu* cpu);
RISCV32_API void riscv32_reset(Riscv32Cpu* cpu);

RISCV32_API void riscv32_get_regs(const Riscv32Cpu* cpu, Riscv32Registers* out);
RISCV32_API void riscv32_set_regs(Riscv32Cpu* cpu, const Riscv32Registers* in);

/// Which optional extensions this part has, as the bits of `riscv32::Extension`
/// -- 1 for M, 2 for A, 4 for C. Nothing is enabled until a board says so.
///
/// This is the only piece of chip knowledge the core accepts, and it is here
/// rather than inferred because it is the one thing lockstep against rvcpp can
/// never check: rvcpp runs every extension. See OH-35.
RISCV32_API uint32_t riscv32_extensions(const Riscv32Cpu* cpu);
RISCV32_API void riscv32_set_extensions(Riscv32Cpu* cpu, uint32_t mask);

/// 0 on a fault, having read or written nothing. Not a zero-filled read: an
/// address this core does not model is not the same as an address holding
/// zero, and a harness has to be able to tell them apart.
RISCV32_API int riscv32_read_word(const Riscv32Cpu* cpu, uint32_t address,
                                  uint32_t* out);
RISCV32_API int riscv32_write_word(Riscv32Cpu* cpu, uint32_t address,
                                   uint32_t value);

/// Bulk transfer, so loading an image is one call rather than one per word.
/// The whole span is range-checked first, so a block overrunning a region
/// writes none of it rather than half of it.
RISCV32_API int riscv32_write_block(Riscv32Cpu* cpu, uint32_t address,
                                    const uint8_t* data, uint32_t length);
RISCV32_API int riscv32_read_block(const Riscv32Cpu* cpu, uint32_t address,
                                   uint8_t* out, uint32_t length);

RISCV32_API void riscv32_clear_memory(Riscv32Cpu* cpu);

/// A readable, writable region of `size` bytes at `base`. `executable` 0 makes
/// a fetch from it fault while data reads still answer -- what a stub standing
/// in for contents this project cannot ship needs. See cpu.h.
/// 0 when it overlaps a region already added, having added nothing.
RISCV32_API int riscv32_add_region(Riscv32Cpu* cpu, uint32_t base,
                                   uint32_t size, int executable, uint8_t fill);
RISCV32_API void riscv32_clear_regions(Riscv32Cpu* cpu);

/// Execute one instruction at PC, advancing PC past it.
///
/// 0 success, 1 an encoding this core has not implemented, 2 memory refused
/// the access, 3 an encoding this *part* must refuse because the extension it
/// belongs to is not enabled.
///
/// **3 is not a worse 1.** 1 says this emulator is unfinished; 3 says the
/// silicon would trap here, and a model that returned 0 instead would be
/// wrong in a way no lockstep run against rvcpp can detect. Ask
/// `riscv32_fault_address` about 2.
///
/// On 1, 2 and 3 the processor is untouched, PC included -- so a caller can
/// report exactly which instruction stopped it, and a conformance case can
/// never pass by accident because an unwritten encoding behaved like a NOP.
RISCV32_API int riscv32_step(Riscv32Cpu* cpu);

/// The address of the most recent failed access, and whether it was a fetch.
/// Only meaningful straight after a step returned 2.
RISCV32_API uint32_t riscv32_fault_address(const Riscv32Cpu* cpu);
RISCV32_API int riscv32_fault_was_fetch(const Riscv32Cpu* cpu);

/// Whether `bytes` at `address` fall in any region. Lets a caller tell the two
/// fetch failures apart: an address that does not exist, and one that exists
/// and is not executable. They mean different things -- a missing memory map
/// versus a jump into a stub -- and one message for both sends the reader the
/// wrong way.
RISCV32_API int riscv32_in_range(const Riscv32Cpu* cpu, uint32_t address,
                                 uint32_t bytes);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif
