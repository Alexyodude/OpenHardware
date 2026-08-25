// OpenHardware — taking an 8086 interrupt vector.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## Why this is its own file now
//
// `RaiseInterrupt` lived in `exec_core.cc` and carried a note saying it moves
// "when OH-5 arrives and has INT n, INT3, INTO and the trap flag to put beside
// it". OH-5 arrived. It is **lifted**, not rewritten: the body below is the
// one the corpus has been agreeing with since OH-4, and writing a second
// implementation of a sequence that pushes three words in a fixed order is how
// two of them come to disagree about which order.
//
// ## What an 8086 interrupt sequence is
//
// Push FLAGS, clear IF and TF, push CS, push IP, then load CS:IP from the
// four bytes at `vector * 4`. Nothing else. There is no privilege level, no
// error code and no gate type -- the whole mechanism is 256 far pointers at
// the bottom of memory, and a program may overwrite any of them.

#ifndef OPENHARDWARE_I8086_INTERRUPT_H
#define OPENHARDWARE_I8086_INTERRUPT_H

#include <cstdint>

#include "cpu.h"

namespace i8086 {

/// The vector a single-step trap takes, from the 8086 manual's table.
///
/// 0 is divide error, 1 is single step, 2 is NMI, 3 is the one-byte INT3 and
/// 4 is INTO. Named because a bare `1` beside a bare `4` in the same function
/// is two chances to write the other one.
constexpr std::uint8_t kVectorDivideError = 0;
constexpr std::uint8_t kVectorSingleStep = 1;
constexpr std::uint8_t kVectorBreakpoint = 3;
constexpr std::uint8_t kVectorOverflow = 4;

/// Take an interrupt vector: push FLAGS, CS and IP, then jump through the
/// table at the bottom of memory.
///
/// **`return_ip` is the address of the next instruction, not the faulting
/// one.** Measured: `D4 00` at IP 0x8573 pushes 0x8575. Later x86 parts push
/// the faulting address for a divide error, which is the difference between
/// it being a fault there and a trap here -- an 8086 handler cannot retry the
/// instruction, and was never meant to.
void RaiseInterrupt(Cpu& cpu, std::uint8_t vector, std::uint16_t return_ip);

}  // namespace i8086

#endif
