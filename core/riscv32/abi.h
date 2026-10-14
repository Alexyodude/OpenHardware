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
//: Bumped to 2 on 2026-08-25 (OH-47), which added the four mmio
//: entry points below. The binding refuses a library reporting a
//: different number rather than calling a symbol that is not there.
//: Bumped to 3 at OH-161's step 2, which added
//: `riscv32_map_snapshot_counter`; step 1's `riscv32_map_stream` and
//: `riscv32_stream` arrived without one, and are counted in this one.
//: Bumped to 4 at OH-161's step 3, which added `riscv32_map_input` and
//: `riscv32_drive_input`.
//: Bumped to 5 at OH-225, which added `riscv32_step_entry`.
//: Bumped to 6 at OH-161's step 4, which added `riscv32_map_sampler` and
//: `riscv32_hold_samples`.
//: Bumped to 7 at OH-161's step 5, which added `riscv32_map_doorbell`,
//: `riscv32_rang_at`, `riscv32_map_fifo`, `riscv32_written_count`,
//: `riscv32_take_written` and `riscv32_hold_readable`, and the step result
//: `RISCV32_RANG`; and, before it shipped, `riscv32_fault_reason`,
//: `riscv32_peek_word`, `riscv32_is_doorbell` and `riscv32_is_fifo`.
#define RISCV32_ABI_VERSION 7

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

/// Memory-mapped registers. See `cpu.h` for why a peripheral is not a region
/// and why four of `core/cortexm0`'s six behaviours are here.
///
/// `op` is `riscv32::WriteOp` as an int: 0 Store, 1 Set, 2 Clear, 3 Xor.
RISCV32_API void riscv32_map_register(Riscv32Cpu* cpu, uint32_t address,
                                      uint32_t value);
RISCV32_API void riscv32_map_alias(Riscv32Cpu* cpu, uint32_t address,
                                   uint32_t target, int op, int readable);

/// An address whose writes append a byte to a captured stream: a TX FIFO,
/// where a plain register would keep only the last character written.
///
/// Captured only while `enable_address & enable_mask` is non-zero -- a
/// transmitter whose clock is off sends nothing, and a model without the gate
/// lets firmware appear to print before it enabled the peripheral. See cpu.h.
RISCV32_API void riscv32_map_stream(Riscv32Cpu* cpu, uint32_t address,
                                    uint32_t enable_address,
                                    uint32_t enable_mask);

/// Copy up to `capacity` bytes of the stream at `address` into `out`, and
/// return how many bytes the stream holds.
///
/// The return value is the true length, not the number copied, so a caller
/// that passed too small a buffer can tell -- rather than silently reading a
/// truncated prefix as if it were the whole output.
RISCV32_API uint32_t riscv32_stream(const Riscv32Cpu* cpu, uint32_t address,
                                    uint8_t* out, uint32_t capacity);

/// A free-running counter read through a snapshot: a write carrying
/// `update_mask` to `op_address` copies the count into `low_address` and
/// `high_address` (kept to `high_mask`), after which `op_address` reads
/// `valid_mask`. It counts once per `instructions_per_tick` retired
/// instructions while `enable_address & enable_mask` is non-zero. An ESP32's
/// SYSTIMER unit, whose UPDATE / VALUE_VALID handshake a live counter would
/// answer at the wrong moment. `instructions_per_tick` is a stated
/// approximation; this core has no cycle model. See cpu.h.
RISCV32_API void riscv32_map_snapshot_counter(
    Riscv32Cpu* cpu, uint32_t op_address, uint32_t update_mask,
    uint32_t valid_mask, uint32_t low_address, uint32_t high_address,
    uint32_t high_mask, uint32_t enable_address, uint32_t enable_mask,
    uint32_t instructions_per_tick);

/// A read-only register whose read answers the level on each pin: per pin
/// named in `pads`, 0 where the pad register at `pad_base + n * pad_stride`
/// has `input_enable_mask` clear; `out_address`'s bit where
/// `enable_address`'s is set; the level `riscv32_drive_input` gave it; 1
/// where only `pull_up_mask` is set; else 0. An ESP32's `GPIO_IN`. See cpu.h.
RISCV32_API void riscv32_map_input(Riscv32Cpu* cpu, uint32_t address,
                                   uint32_t out_address,
                                   uint32_t enable_address, uint32_t pad_base,
                                   uint32_t pad_stride, uint32_t pads,
                                   uint32_t input_enable_mask,
                                   uint32_t pull_up_mask,
                                   uint32_t pull_down_mask);

/// What the world outside drives onto the pins of the input register at
/// `address`, replacing what the last call said. 0, having changed nothing,
/// where `address` is no input register.
RISCV32_API int riscv32_drive_input(Riscv32Cpu* cpu, uint32_t address,
                                    uint32_t driven, uint32_t levels);

/// A converter started by a write: `control_address` stores as a register
/// from `value`, and a write that raises `start_mask` copies the word held
/// for `written & key_mask` into `result_address` and sets `done_mask` in
/// `status_address`, while `enable_address & enable_mask` is set. An ESP32's
/// SAR ADC one-time sample. See cpu.h for what faults.
RISCV32_API void riscv32_map_sampler(Riscv32Cpu* cpu, uint32_t control_address,
                                     uint32_t value, uint32_t start_mask,
                                     uint32_t key_mask, uint32_t result_address,
                                     uint32_t status_address,
                                     uint32_t done_mask,
                                     uint32_t enable_address,
                                     uint32_t enable_mask);

/// The word each of `count` keys converts to, replacing what the last call
/// held. 0, having changed nothing, where `control_address` is no sampler.
RISCV32_API int riscv32_hold_samples(Riscv32Cpu* cpu, uint32_t control_address,
                                     const uint32_t* keys,
                                     const uint32_t* words, uint32_t count);

/// A register that rings when written: `address` stores as a register from
/// `value`, with every bit of `write_trigger` stored as 0, and a write whose
/// value carries any bit of `ring_mask` ends its step with `RISCV32_RANG`
/// after the store has retired. See cpu.h. 0, having changed nothing, where
/// `address` is a register of a snapshot counter; so for the FIFO.
RISCV32_API int riscv32_map_doorbell(Riscv32Cpu* cpu, uint32_t address,
                                     uint32_t value, uint32_t ring_mask,
                                     uint32_t write_trigger);

/// The doorbell the most recent step rang; meaningful only straight after a
/// step returned `RISCV32_RANG`.
RISCV32_API uint32_t riscv32_rang_at(const Riscv32Cpu* cpu);

/// A byte FIFO at `address`: writes append while `enable_address &
/// enable_mask` is set, reads pop what `riscv32_hold_readable` gave and fault
/// when nothing is held. See cpu.h.
RISCV32_API int riscv32_map_fifo(Riscv32Cpu* cpu, uint32_t address,
                                 uint32_t enable_address,
                                 uint32_t enable_mask);

/// How many bytes firmware has written to the FIFO at `address` since they
/// were last taken; 0 where it is no FIFO.
RISCV32_API uint32_t riscv32_written_count(const Riscv32Cpu* cpu,
                                           uint32_t address);

/// Copy the written bytes into `out` and forget them, returning how many
/// there were. **When that is more than `capacity` nothing is copied or
/// forgotten**, so a caller sees the true count and no bytes are lost to a
/// buffer that was too small.
RISCV32_API uint32_t riscv32_take_written(Riscv32Cpu* cpu, uint32_t address,
                                          uint8_t* out, uint32_t capacity);

/// The bytes reads of the FIFO at `address` pop, replacing what was held.
/// 0, having changed nothing, where `address` is no FIFO.
RISCV32_API int riscv32_hold_readable(Riscv32Cpu* cpu, uint32_t address,
                                      const uint8_t* bytes, uint32_t count);

RISCV32_API int riscv32_is_mapped(const Riscv32Cpu* cpu, uint32_t address);
RISCV32_API void riscv32_clear_mmio(Riscv32Cpu* cpu);

/// Execute one instruction at PC, advancing PC past it.
///
/// 0 success, 1 an encoding this core has not implemented, 2 memory refused
/// the access, 3 an encoding this *part* must refuse because the extension it
/// belongs to is not enabled, 4 (`RISCV32_RANG`) success, with a doorbell rung.
///
/// **4 is a success and the first result that follows a retired
/// instruction.** The store has landed, PC is past it and the machine has
/// aged, exactly as for 0; `riscv32_rang_at` names the doorbell, and the
/// caller runs whatever answers it before the next step. It exists only at
/// this boundary: `riscv32::StepResult` has no such value.
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

/// The `riscv32_step` result for a retired instruction that rang a doorbell.
#define RISCV32_RANG 4

/// The PC the most recent riscv32_step began at; zero before the first.
///
/// For when the core faults on the host part-way through an instruction
/// (OH-225): once an instruction has moved PC, PC names the next one rather
/// than the one that faulted. Every step records it, at the cost of one
/// store, so a caller need not read PC before each step to have it.
RISCV32_API uint32_t riscv32_step_entry(const Riscv32Cpu* cpu);

/// Why the most recent access was refused, as `riscv32::FaultReason`: 0
/// nothing mapped there (or any fault that names no other reason), 1 a FIFO
/// read with nothing held, 2 a FIFO whose enable register is not mapped, 3 a
/// byte or halfword read of a FIFO above byte 0, 4 an access through an alias
/// onto a FIFO or a doorbell. Meaningful straight after a
/// step returned 2 or a read or write returned 0. ABI 7.
RISCV32_API int riscv32_fault_reason(const Riscv32Cpu* cpu);

/// `riscv32_read_word` that changes nothing: a FIFO answers the byte its next
/// read will pop. The only read a viewer may make of one. A failed peek
/// leaves the fault record alone and gives its reason (as
/// `riscv32_fault_reason`) in `*reason`. ABI 7.
RISCV32_API int riscv32_peek_word(const Riscv32Cpu* cpu, uint32_t address,
                                  uint32_t* out, int* reason);

/// Whether `address` is a doorbell / a FIFO. ABI 7.
RISCV32_API int riscv32_is_doorbell(const Riscv32Cpu* cpu, uint32_t address);
RISCV32_API int riscv32_is_fifo(const Riscv32Cpu* cpu, uint32_t address);

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
