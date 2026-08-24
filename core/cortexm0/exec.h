// OpenHardware — execute one Thumb instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#ifndef OPENHARDWARE_CORTEXM0_EXEC_H
#define OPENHARDWARE_CORTEXM0_EXEC_H

#include "cpu.h"

namespace cortexm0 {

/// Fetch, execute and advance PC by one 16-bit instruction.
///
/// On anything but `Ok` the processor is untouched, PC included. See
/// `StepResult` in cpu.h for why that matters to a conformance run.
StepResult step(Cpu& cpu);

}  // namespace cortexm0

#endif
