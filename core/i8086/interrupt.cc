// OpenHardware — taking an 8086 interrupt vector.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.

#include "interrupt.h"

#include "alu.h"

namespace i8086 {
namespace {

/// SP decrements by two, then the word lands at SS:SP.
///
/// A local copy of `exec_core.cc`'s `Push`, and deliberately not shared. It is
/// four lines, and the alternative is a header exporting the stack primitives
/// so that two files can disagree about whether the decrement comes first.
/// `.claude/CLAUDE.md` rule 8: split only when the interface is simpler than
/// what it hides, and "push a word" is not.
///
/// Through `WriteWordAt` so a stack wrapping past offset 0 comes back at
/// 0xFFFE rather than spilling into the next segment.
void PushWord(Cpu& cpu, std::uint16_t value) {
    cpu.regs().sp = static_cast<std::uint16_t>(cpu.regs().sp - 2);
    cpu.WriteWordAt(cpu.regs().ss, cpu.regs().sp, value);
}

}  // namespace

void RaiseInterrupt(Cpu& cpu, std::uint8_t vector, std::uint16_t return_ip) {
    // FLAGS goes first, and it is the value the instruction has already
    // computed -- the corpus pushes the adjusted word, not the one the
    // instruction started with.
    PushWord(cpu, cpu.regs().flags);
    // Cleared after the push, so IRET restores them. A handler entered with
    // interrupts still enabled would be re-entered by the next one; a handler
    // entered with TF still set would single-step itself.
    SetFlag(cpu.regs().flags, kInterrupt, false);
    SetFlag(cpu.regs().flags, kTrap, false);
    PushWord(cpu, cpu.regs().cs);
    PushWord(cpu, return_ip);

    // The table is 256 entries of offset-then-segment at 0000:0000.
    const std::uint16_t entry = static_cast<std::uint16_t>(vector * 4);
    cpu.regs().ip = cpu.ReadWordAt(0x0000, entry);
    cpu.regs().cs = cpu.ReadWordAt(0x0000, static_cast<std::uint16_t>(entry + 2));
}

}  // namespace i8086
