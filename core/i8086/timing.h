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
// The execution-unit cost has one honest source, and `RegisterFormClocks`
// below is it: Intel's own published table, for the register-form
// instructions whose cost is a single number, checked against the corpus and
// never read from it -- all but two of its figures, which no queue state in
// the corpus can reach (see `RegisterFormCycles`). When the bus interface
// starts a fetch is still nobody's number, so the F2 cells stay `planned`.
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

/// What Intel's own table says a REGISTER-FORM instruction costs the
/// execution unit, in clocks, or 0 where this makes no claim.
///
/// ## Where every number comes from
///
/// Intel, *8086 Family User's Manual* (October 1979, 9800722-03), Table 2-21,
/// "Instruction Set Reference Data", pp. 2-51 to 2-68, the `Clocks` column.
/// Page 2-50 says what that column means: "The time provided assumes that the
/// instruction has already been prefetched and that it is waiting in the
/// instruction queue". So it is the execution unit's cost alone, with the
/// bus out of the picture -- exactly what a full queue isolates in the corpus.
/// **No number here was read off the corpus.** The corpus checks them.
///
/// The table's `Bytes` column decides WHICH encoding a row is about. Intel's
/// "register, immediate" MOV is 2-3 bytes, so it is B0-BF and not C6/C7 with
/// mod 3, which is 3-4 bytes; the decoding guide (Table 4-13) marks the
/// latter "not used". Where Intel tables no such encoding, this says 0.
///
/// ## What says 0, and why
///
/// - any memory operand (mod != 3): its cost depends on the effective address
///   and on bus transfers, which is the prefetch model this is not;
/// - an instruction whose cost depends on its data -- AAA, AAS, CWD, shifts
///   by CL, MUL, DIV -- or that moves IP, the stack, a string or a port;
/// - an encoding Intel's decoding guide marks "not used", such as 82, 83 /1
///   /4 /6, D0-D3 /6, F6/F7 /1 and 8C/8E with a segment register above 3,
///   and 8E /1, which loads CS and so is a jump;
/// - **LAHF.** Intel's table says 4 (p. 2-59); every full-queue case in the
///   corpus measures 2. The part disagrees with its own datasheet, and the
///   honest response to that is to leave the row out and pin the observation
///   (`test_timing.py`), not to write 2 here and call it Intel's.
std::uint8_t RegisterFormClocks(std::uint8_t opcode, std::uint8_t modrm);

/// Clocks for a register-form instruction, counted as the corpus counts them
/// -- from the cycle its opcode leaves the queue to the cycle the NEXT
/// instruction's opcode does -- or 0 where this makes no claim.
///
/// The execution unit and the bus interface run in parallel, so the count is
/// whichever finishes last: `RegisterFormClocks`, or the bus fetching what is
/// not yet queued. That is claimed in exactly two queue states:
///
/// - **`queued == 0`.** The opcode itself arrives on the first cycle, so the
///   bus still owes the rest of the instruction and then the next opcode:
///   `length` bus cycles, which is `MinimumCycles(length, 0)`.
/// - **`queued > length`.** The queue holds the instruction AND the next
///   opcode, so the bus owes nothing and the count is the table's alone.
///   `queued` is clamped to `kQueueBytes` first, as `MinimumCycles` clamps
///   it, so a four-byte instruction never qualifies.
///
/// **Only the second state checks Intel's figure.** From an empty queue the
/// bus is never the faster unit -- at best a tie, DAA, DAS and SAHF's four
/// against four -- so there the count checks the decoding and the length,
/// and catches a figure only if it rises past the bus. And the second state is out of reach of a four-byte
/// instruction, so two of Intel's figures are tabled here and checked by
/// nothing: ALU register, immed16 (81 with mod 3) and TEST reg16, immed16
/// (F7 /0 with mod 3). `test_timing.py` pins that it is exactly those two.
///
/// Between them -- a queue that holds the instruction but not what follows,
/// or part of it -- the answer depends on when the bus interface starts its
/// next fetch, which is a prefetch model. A four-byte instruction with a full
/// queue measures 7 clocks, not 4 and not 8, which is that model showing.
/// This answers 0 there rather than guess.
///
/// Returns 0 too when `length` is not the length the matched row encodes:
/// a prefixed instruction, or a buffer cut short.
std::uint32_t RegisterFormCycles(const std::uint8_t* bytes, std::uint8_t length,
                                 std::uint8_t queued);

}  // namespace i8086

#endif  // OPENHARDWARE_I8086_TIMING_H
