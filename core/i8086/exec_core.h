// OpenHardware - execute one instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#ifndef OPENHARDWARE_I8086_EXEC_CORE_H
#define OPENHARDWARE_I8086_EXEC_CORE_H

#include <cstdint>

#include "cpu.h"
#include "decode.h"

namespace i8086 {

/// What one step did.
///
/// `kUnimplemented` exists so an opcode nobody has written yet is loud. The
/// alternative -- doing nothing and advancing IP -- makes an unimplemented
/// instruction indistinguishable from a NOP, and a conformance case whose
/// expected state happens to match would then *pass*. That is the vacuous
/// green this repository is built against.
enum class StepStatus : std::uint8_t {
    kOk = 0,
    kUnimplemented = 1,
};

/// The eight byte registers, in encoding order: AL CL DL BL AH CH DH BH.
std::uint8_t ReadByteRegister(const Registers& regs, std::uint8_t index);
void WriteByteRegister(Registers& regs, std::uint8_t index, std::uint8_t value);

/// Decode and execute the instruction at CS:IP, advancing IP past it.
///
/// IP advances only on success. A `kUnimplemented` step leaves the processor
/// exactly where it was, so the caller can report which instruction stopped it.
StepStatus Step(Cpu& cpu);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_EXEC_CORE_H
