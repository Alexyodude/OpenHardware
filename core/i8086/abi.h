// OpenHardware - flat C ABI over the i8086 core.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why a C ABI and not a Python extension
//
// The conformance harness is Python: `tools/sst8088.py` already reads the
// corpus, pytest already runs everything, and CI already installs neither a
// compiler toolchain for pybind11 nor a wheel-building step. ctypes needs a
// plain shared library and nothing else.
//
// So this layer is deliberately dull. No classes, no exceptions crossing the
// boundary, no ownership subtleties: an opaque handle, plain integers, and a
// struct whose layout Python mirrors field for field.
//
// ## The struct is the contract
//
// `I8086Registers` must stay laid out exactly as `ctypes.Structure` in
// `tests/i8086/conftest.py` declares it. A field added on one side and not the
// other does not fail to compile or fail to load -- it silently reads the
// wrong bytes. `i8086_abi_version` and `i8086_regs_size` exist so the Python
// side can assert the two agree before running anything.

#ifndef OPENHARDWARE_I8086_ABI_H
#define OPENHARDWARE_I8086_ABI_H

#include <stdint.h>

#if defined(_WIN32)
#define I8086_API __declspec(dllexport)
#else
#define I8086_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// Bumped whenever this header's shape changes. Python refuses to run against
/// a library that disagrees, which turns a silent struct mismatch into a clear
/// failure at import.
#define I8086_ABI_VERSION 5

/// Mirrors i8086::Registers.
///
/// The field ORDER is this file's own and deliberately need not match the
/// corpus's -- every crossing is by name (`set_regs(**case.initial_regs)`,
/// `as_dict()`), never positional. An earlier version of this comment
/// claimed the orders matched. They do not, and nothing noticed because
/// nothing depends on it.
typedef struct {
    uint16_t ax, bx, cx, dx;
    uint16_t si, di, bp, sp;
    uint16_t cs, ds, es, ss;
    uint16_t ip;
    uint16_t flags;
} I8086Registers;

/// A decoded instruction, flattened for the ABI.
///
/// `ea_*` are filled only when the instruction has a memory operand, so a
/// caller need not reimplement the addressing table to know where an
/// instruction points. `segment_override` and `ea_segment` use
/// 0=ES 1=CS 2=SS 3=DS 4=none, matching i8086::Segment.
typedef struct {
    uint8_t opcode;
    uint8_t has_modrm;
    uint8_t mod;
    uint8_t reg;
    uint8_t rm;
    int16_t displacement;
    uint8_t segment_override;
    uint8_t length;
    uint8_t valid;
    uint8_t has_memory_operand;
    uint8_t ea_segment;
    uint16_t ea_offset;
    uint32_t ea_physical;
} I8086Decoded;

typedef struct I8086Cpu I8086Cpu;

I8086_API int i8086_abi_version(void);
/// sizeof(I8086Registers), so Python can check its mirror matches.
I8086_API uint32_t i8086_regs_size(void);
/// Bytes of address space, so Python need not hardcode 1 MB.
I8086_API uint32_t i8086_memory_size(void);

I8086_API I8086Cpu* i8086_new(void);
I8086_API void i8086_free(I8086Cpu* cpu);
I8086_API void i8086_reset(I8086Cpu* cpu);

I8086_API void i8086_get_regs(const I8086Cpu* cpu, I8086Registers* out);
I8086_API void i8086_set_regs(I8086Cpu* cpu, const I8086Registers* in);

I8086_API uint8_t i8086_read_byte(const I8086Cpu* cpu, uint32_t address);
I8086_API void i8086_write_byte(I8086Cpu* cpu, uint32_t address, uint8_t value);
I8086_API uint16_t i8086_read_word(const I8086Cpu* cpu, uint32_t address);
I8086_API void i8086_write_word(I8086Cpu* cpu, uint32_t address, uint16_t value);

/// Bulk load, so a conformance case's `ram` list is one call rather than one
/// call per byte. A case can carry thousands of bytes and the corpus has
/// hundreds of thousands of cases.
I8086_API void i8086_write_block(I8086Cpu* cpu, uint32_t address, const uint8_t* data,
                                 uint32_t length);
I8086_API void i8086_read_block(const I8086Cpu* cpu, uint32_t address, uint8_t* out,
                                uint32_t length);

I8086_API void i8086_clear_memory(I8086Cpu* cpu);

/// Segment:offset to physical, exposed so the Python side tests the same
/// wrapping the core uses rather than reimplementing it.
I8086_API uint32_t i8086_physical(uint16_t segment, uint16_t offset);

/// Decode the instruction at cs:ip without executing it.
I8086_API void i8086_decode(const I8086Cpu* cpu, uint16_t cs, uint16_t ip,
                            I8086Decoded* out);
I8086_API uint32_t i8086_decoded_size(void);

/// Bit 0: implemented. Bit 1: takes a modrm byte. From the single table both
/// the decoder and the executor consult.
I8086_API int i8086_opcode_info(uint8_t opcode);

/// Execute one instruction at CS:IP, advancing IP past it.
///
/// Returns 0 on success and 1 for an opcode that is not implemented. On 1 the
/// processor is untouched, including IP -- so a caller can report exactly
/// which instruction stopped it, and a conformance case can never pass by
/// accident because an unwritten opcode behaved like a NOP.
I8086_API int i8086_step(I8086Cpu* cpu);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // OPENHARDWARE_I8086_ABI_H
