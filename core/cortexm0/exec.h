// OpenHardware — execute one Thumb instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#ifndef OPENHARDWARE_CORTEXM0_EXEC_H
#define OPENHARDWARE_CORTEXM0_EXEC_H

#include <stdint.h>

#include "cpu.h"

namespace cortexm0 {

/// Fetch, execute and advance PC by one 16-bit instruction.
///
/// On anything but `Ok` the processor is untouched, PC included. See
/// `StepResult` in cpu.h for why that matters to a conformance run.
StepResult step(Cpu& cpu);

// Shared with thumb2.cc, which executes the 32-bit encodings under Armv7E-M
// and needs the same two answers the narrow ones do. Defined in exec.cc.

/// Whether the four-bit condition `code` holds on the current flags. 0xE and
/// 0xF both answer true; the callers that must refuse 0xF do so themselves.
bool condition_holds(const Cpu& cpu, unsigned code);

/// Write PC from a register or memory, which in Handler mode may be an
/// exception return rather than a branch. See exec.cc.
StepResult write_pc_or_return(Cpu& cpu, uint32_t value);

}  // namespace cortexm0

#endif
