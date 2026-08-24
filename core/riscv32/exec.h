// OpenHardware — decode and execute one RV32 instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// Separate from cpu.h so that "can this core reach this address" stays
// answerable without reading an instruction set, and so the instruction set
// can grow without the memory model being recompiled by everyone who reads it.

#ifndef OPENHARDWARE_RISCV32_EXEC_H
#define OPENHARDWARE_RISCV32_EXEC_H

#include "cpu.h"

namespace riscv32 {

/// Execute the instruction at PC, advancing PC past it.
///
/// On anything but `Ok` the processor is left completely untouched, PC
/// included, so a caller can report exactly which instruction stopped it.
StepResult step(Cpu& cpu);

}  // namespace riscv32

#endif
