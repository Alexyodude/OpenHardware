// OpenHardware — how long an 8088 instruction can possibly take.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "timing.h"

namespace i8086 {

std::uint32_t MinimumCycles(std::uint8_t length, std::uint8_t queued) {
    const std::uint8_t held = queued < kQueueBytes ? queued : kQueueBytes;
    const std::uint8_t fetch = length > held
                                   ? static_cast<std::uint8_t>(length - held)
                                   : 0;
    return static_cast<std::uint32_t>(fetch) * kClocksPerBusCycle;
}

}  // namespace i8086
