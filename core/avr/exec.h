// OpenHardware — one AVR instruction.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#ifndef OPENHARDWARE_AVR_EXEC_H
#define OPENHARDWARE_AVR_EXEC_H

#include "cpu.h"

namespace avr {

/// Execute the instruction at PC, advancing PC past it.
///
/// On `Unimplemented` the machine is untouched, PC included, so a caller can
/// name the word that stopped it. See exec.cc for why that matters more on a
/// variable-length encoding than it does on Arm.
StepResult step(Cpu& cpu);

}  // namespace avr

#endif
