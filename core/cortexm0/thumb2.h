// OpenHardware — execute one 32-bit Thumb-2 instruction, Armv7E-M (OH-64).
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#ifndef OPENHARDWARE_CORTEXM0_THUMB2_H
#define OPENHARDWARE_CORTEXM0_THUMB2_H

#include <stdint.h>

#include "cpu.h"

namespace cortexm0 {

/// Execute the 32-bit instruction `first:second` sitting at `address`.
///
/// Called by `step` only under `Profile::V7EM`, after PC has already been
/// advanced past both halfwords and after the IT condition, if any, has been
/// found to hold -- so nothing here asks whether it should run, only how.
///
/// `in_it` and `last_in_it` are the two facts about the IT block the decode
/// needs: a conditional `B<c>.W` is UNPREDICTABLE anywhere inside one, and an
/// unconditional branch is permitted only as the block's last instruction.
///
/// The contract is `step`'s: anything but `Ok` means the instruction did not
/// happen, and `step` puts PC back.
StepResult execute_thumb2(Cpu& cpu, uint16_t first, uint16_t second,
                          uint32_t address, bool in_it, bool last_in_it);

}  // namespace cortexm0

#endif
