// OpenHardware — taking an Armv6-M exception, and coming back from one.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this is a file rather than three functions in exec.cc
//
// The same reason `core/i8086/interrupt.h` is one: what an exception does to
// the machine is not what an *instruction* does to it, and the stack frame's
// layout is a contract three separate places have to agree on -- entry writes
// it, return reads it, and a test compares it word by word against rp2040js.
// Spreading that across the decoder would make the agreement implicit.
//
// ## What is modelled, and what is deliberately not
//
// **One exception source: SysTick.** No NVIC, no external interrupts, no
// PendSV, no SVCall. `exec.cc` still answers `Unimplemented` for SVC, which is
// correct rather than lazy -- pretending an SVC returned would let a program
// continue past a call that never happened.
//
// **One stack: the main one.** Armv6-M has a banked process stack selected by
// `CONTROL.SPSEL`, and nothing here selects it: an image comes out of reset on
// MSP, and only an RTOS switches. So `EXC_RETURN` is always 0xFFFFFFF9 from
// Thread mode, and the 0xFFFFFFFD case has no caller. Adding the bank for a
// caller that does not exist is what rule 6 forbids; `ReturnFromException`
// refuses the value rather than silently treating it as the main stack, so the
// day an RTOS arrives it stops loudly instead of running on the wrong stack.
//
// **No nesting and no priority.** With one source there is nothing to
// arbitrate, and SysTick cannot pre-empt itself: same priority, so the
// architecture makes it wait. `ServicePending` refuses to enter while IPSR is
// non-zero, which is that rule, and it leaves the request pending so the
// exception is taken the instant the handler returns -- tail-chaining, which
// is what the part does.
//
// ## The frame, and where its shape comes from
//
// Eight words, in this order from the frame pointer: r0, r1, r2, r3, r12, LR,
// the return address, xPSR. Only the *locations* are architected, not the
// order they are written in.
//
// SP is forced down to an eight-byte boundary on entry, and bit 9 of the
// stacked xPSR records whether it had to move. Return puts back exactly what
// entry took. Getting that wrong misaligns the stack by four bytes *only on
// interrupts that happen to arrive at an odd word*, so it survives every test
// that fires one exception and corrupts a program that runs for a while --
// which is why it is checked against the oracle rather than against a reading.
//
// `../rp2040js/src/cortex-m0-core.ts`, `exceptionEntry` and `exceptionReturn`,
// is that oracle. It is already this project's Armv6-M reference for the
// instruction set; using a second source for the exception model would be
// blending two, which `docs/architectures.md` rules out.

#ifndef OPENHARDWARE_CORTEXM0_EXCEPTION_H
#define OPENHARDWARE_CORTEXM0_EXCEPTION_H

#include "cpu.h"

namespace cortexm0 {

/// Take exception `number`: stack the interrupted frame and enter its handler.
///
/// False when a stack write or the vector fetch faulted, having changed
/// nothing a caller should trust. On a real part that is a HardFault escalating
/// to lockup; here it is a `MemoryFault` naming the address, which is the more
/// useful of the two when a board's map is what is actually wrong.
bool EnterException(Cpu& cpu, unsigned number);

/// Undo it. `exc_return` is the value that reached PC.
///
/// False when the frame could not be read, or when `exc_return` names the
/// process stack -- see the header note on why that is refused rather than
/// approximated.
bool ReturnFromException(Cpu& cpu, uint32_t exc_return);

/// Take a pending SysTick if one is due and nothing is masking it.
///
/// True when an exception was taken, in which case **no instruction ran** and
/// the caller must not execute one: PC now names the handler's first
/// instruction, and stepping over it would skip it.
bool ServicePending(Cpu& cpu);

}  // namespace cortexm0

#endif  // OPENHARDWARE_CORTEXM0_EXCEPTION_H
