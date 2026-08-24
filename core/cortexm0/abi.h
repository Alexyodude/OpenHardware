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
#define CORTEXM0_ABI_VERSION 12

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
/// Forget every mapped register. Separate from clearing memory contents.
CORTEXM0_API void cortexm0_clear_registers(CortexM0Cpu* cpu);

/// A readable, writable region of `size` bytes at `base`. `executable` 0 makes
/// a fetch from it fault while data reads still answer -- what a stub standing
/// in for contents this project cannot ship needs. See cpu.h.
/// 0 when it overlaps a region already added, having added nothing.
CORTEXM0_API int cortexm0_add_region(CortexM0Cpu* cpu, uint32_t base,
                                     uint32_t size, int executable,
                                     uint8_t fill);
CORTEXM0_API void cortexm0_clear_regions(CortexM0Cpu* cpu);

/// Make one memory-mapped word respond, reads-as-written. See cpu.h: only
/// registered addresses respond, so an unmodelled peripheral still faults
/// rather than reading as zero and hanging a poll loop.
CORTEXM0_API void cortexm0_map_register(CortexM0Cpu* cpu, uint32_t address,
                                        uint32_t value);
CORTEXM0_API int cortexm0_is_mapped(const CortexM0Cpu* cpu, uint32_t address);

/// `op`: 0 store, 1 set, 2 clear, 3 xor. An address whose write applies `op`
/// to `target`'s word -- the RP2040's atomic aliases, STM32's BSRR. The
/// offsets that mean "set" on a given chip are the caller's business.
/// `readable` 0 makes it read as zero: a dedicated write-only register such as
/// SIO's GPIO_OUT_SET, as against a bus alias window which reads through to the
/// register it aliases. See cpu.h.
CORTEXM0_API void cortexm0_map_alias(CortexM0Cpu* cpu, uint32_t address,
                                     uint32_t target, int op, int readable);

/// An address whose read derives from `source`, optionally inverted and
/// masked. RP2040's RESET_DONE is `~RESET`; a driver polls it in a loop, so a
/// mirror that did not follow would spin forever.
CORTEXM0_API void cortexm0_map_mirror(CortexM0Cpu* cpu, uint32_t address,
                                      uint32_t source, int invert, uint32_t mask);

/// An address whose reads answer `value` and whose writes are ignored: a
/// read-only status register. `cortexm0_map_mirror` cannot stand in, because a
/// mirror reads from a source register and a constant has none.
CORTEXM0_API void cortexm0_map_constant(CortexM0Cpu* cpu, uint32_t address,
                                        uint32_t value);

/// An address whose writes append a byte to a captured stream: a TX FIFO,
/// where a plain register would keep only the last character written.
///
/// Captured only while `enable_address & enable_mask` is non-zero -- a disabled
/// UART transmits nothing, and a model without the gate lets firmware appear to
/// print before it enabled the peripheral. See cpu.h.
CORTEXM0_API void cortexm0_map_stream(CortexM0Cpu* cpu, uint32_t address,
                                      uint32_t enable_address,
                                      uint32_t enable_mask);

/// Copy up to `capacity` bytes of the stream at `address` into `out`, and
/// return how many bytes the stream holds.
///
/// The return value is the true length, not the number copied, so a caller
/// that passed too small a buffer can tell -- rather than silently reading a
/// truncated prefix as if it were the whole output.
CORTEXM0_API uint32_t cortexm0_stream(const CortexM0Cpu* cpu, uint32_t address,
                                      uint8_t* out, uint32_t capacity);

/// An address whose read answers `executed / instructions_per_tick`: a
/// free-running counter such as the RP2040's TIMERAWL, which pico-sdk's
/// `timer_busy_wait_us_32()` spins on. A register that does not advance makes
/// that loop run forever, and unlike a missing register it cannot be made loud
/// -- the address is modelled and the read does answer. `instructions_per_tick`
/// is a stated approximation; this core has no cycle model. See cpu.h.
CORTEXM0_API void cortexm0_map_counter(CortexM0Cpu* cpu, uint32_t address,
                                       uint32_t instructions_per_tick);

/// Instructions retired since the core was created. Virtual time's only source.
CORTEXM0_API uint64_t cortexm0_executed(const CortexM0Cpu* cpu);

/// Execute one instruction at PC, advancing PC past it.
///
/// Returns 0 on success, 1 for an encoding this core does not implement, and
/// 2 when memory refused the access -- either an address no region covers, or
/// a fetch from a region that exists and is not executable. Ask
/// `cortexm0_fault_address` and `cortexm0_in_range` which.
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

/// Whether `address` falls in any region. Lets a caller tell the two fetch
/// failures apart: an address that does not exist, and one that exists but is
/// not executable. They mean different things -- a missing memory map versus a
/// jump into a stub -- and one message for both sends the reader the wrong way.
CORTEXM0_API int cortexm0_in_range(const CortexM0Cpu* cpu, uint32_t address,
                                   uint32_t bytes);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif
