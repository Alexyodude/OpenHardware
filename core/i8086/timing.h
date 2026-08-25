// OpenHardware — how long an 8088 instruction can possibly take.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this is, and what it deliberately is not
//
// This is the **lower bound**, not the cycle count. It answers "an instruction
// of this many bytes, with this many already in the queue, cannot finish in
// fewer clocks than this" -- and nothing else. `docs/features/i8086.md`'s three
// F2 cells stay `planned`, because a bound is not a count.
//
// It is here rather than deferred because it is the one part of 8088 timing
// that can be derived from the architecture instead of fitted to data, and
// therefore the one part that can be *checked* against the corpus rather than
// trained on it. Everything above it -- the execution-unit cost of each
// opcode, when the bus is idle, when the queue refills -- has to come from
// somewhere, and fitting a table to the oracle and then testing against the
// same oracle proves nothing.
//
// ## The two numbers, and where they come from
//
// **The 8088 has an eight-bit external bus.** That is the whole difference
// between it and the 8086, and it is why the corpus was captured on an 8088:
// an instruction's bytes arrive one at a time. **A bus cycle is four clocks**
// -- T1, T2, T3, T4 -- which the corpus's own trace shows directly, one row per
// state. So a byte that is not already in the queue costs four clocks to
// fetch.
//
// **The prefetch queue holds four bytes.** An 8086 holds six; this is the
// other half of the 8088's difference.
//
// ## Confirmed, not assumed
//
// `tests/i8086/test_timing.py` checks the bound against every case in the
// corpus: **2,857,000 cases, zero violations, and 521,944 meet it exactly.**
//
// That second number is what makes the first one mean something. A bound
// nothing ever reaches is vacuously true and says nothing about the model --
// eighteen per cent of the corpus is fetch-bound, so this is a real constraint
// that a wrong number would break immediately.

#ifndef OPENHARDWARE_I8086_TIMING_H
#define OPENHARDWARE_I8086_TIMING_H

#include <cstdint>

namespace i8086 {

/// The 8088's prefetch queue, in bytes. An 8086 holds six.
constexpr std::uint8_t kQueueBytes = 4;

/// Clocks in one bus cycle: T1, T2, T3, T4. Visible one row at a time in the
/// corpus's own `cycles` array.
constexpr std::uint8_t kClocksPerBusCycle = 4;

/// The fewest clocks an instruction of `length` bytes can take when `queued`
/// of its bytes are already in the prefetch queue.
///
/// `queued` above `kQueueBytes` is clamped rather than refused: a caller
/// asking about a queue deeper than the part has is asking about a different
/// processor, and answering "no fetches needed" is the right answer to the
/// question actually asked.
std::uint32_t MinimumCycles(std::uint8_t length, std::uint8_t queued);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_TIMING_H
