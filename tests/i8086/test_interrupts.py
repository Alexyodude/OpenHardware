# OpenHardware — the 8086 interrupt sequence, and the one part no corpus covers.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file exists when test_conformance.py already runs 2.8M cases
#
# **The corpus cannot adjudicate the single-step trap.** Measured 2026-08-26
# across all 308 files: 2,857,000 cases, and **zero** have TF set in their
# initial flags. That is not an oversight in the capture. A rig that
# single-steps the part to record one instruction at a time cannot arm a trap
# that fires at the end of every instruction — it would be capturing its own
# mechanism.
#
# So TF is the one flag in this processor whose behaviour has no
# hardware-captured evidence anywhere, and it is asserted here against the
# 8086 manual instead. Same arrangement `tests/avr/test_datasheet_edges.py`
# uses for the two AVR rules its oracle is wrong about: where the oracle
# cannot be asked, ask the manual, and say which.
#
# INT n, INT3, INTO and IRET are a different case — the corpus covers CC, CD,
# CE and CF and `test_conformance.py` runs them. What is asserted here about
# those is the *shape* a reader needs to see in one place: which words go on
# the stack, in what order, and what IRET does with them.
#
# ## What is deliberately NOT modelled
#
# **The MOV-SS inhibit.** On real hardware an instruction that loads SS
# suppresses interrupts — including the trap — for exactly one instruction, so
# that `MOV SS,AX` / `MOV SP,BX` cannot be split by a handler that would then
# run on a half-built stack. This core does not model it. It has no oracle for
# it either, nothing here has needed it, and inventing the behaviour would be
# a claim with no evidence. Recorded rather than silently absent.

import pytest

from core.i8086 import abi

#: FLAGS bits, from the 8086 manual's own numbering.
CARRY = 1 << 0
INTERRUPT = 1 << 9
TRAP = 1 << 8
OVERFLOW = 1 << 11

#: Bits an 8086 reads back as one whatever is written. `core/i8086/cpu.h`
#: calls this kFlagsAlwaysSet; named here so the expected flag words below are
#: readable rather than a magic 0xF002.
ALWAYS_SET = 0xF002

#: Where these tests put a program and a handler. Far apart so a run-on is
#: obvious rather than landing in the other one.
CODE = 0x0100
HANDLER_SEGMENT = 0x2000
HANDLER_OFFSET = 0x0050


def machine(program: bytes, *, flags: int = 0, vector: int | None = None):
    """A CPU with `program` at 0000:0100 and, optionally, one vector armed."""
    cpu = abi.Cpu()
    cpu.write_block(CODE, program)
    cpu.set_regs(cs=0, ip=CODE, ss=0, sp=0x0800, flags=flags | ALWAYS_SET)
    if vector is not None:
        # Four bytes at vector * 4: offset then segment, little-endian.
        cpu.write_word(vector * 4, HANDLER_OFFSET)
        cpu.write_word(vector * 4 + 2, HANDLER_SEGMENT)
    return cpu


def stack_words(cpu, count: int = 3) -> list[int]:
    """The words the interrupt sequence pushed, innermost first.

    SP points at the last thing pushed -- IP -- so reading upward gives IP,
    CS, FLAGS, which is the reverse of the order they were written in.
    """
    sp = cpu.regs.sp
    return [cpu.read_word((cpu.regs.ss << 4) + sp + 2 * i)
            for i in range(count)]


# --- the sequence itself ----------------------------------------------------


def test_int3_pushes_flags_then_cs_then_ip_and_jumps_through_the_table():
    """The whole mechanism in one assertion. There is no privilege level, no
    error code and no gate type: 256 far pointers at the bottom of memory."""
    cpu = machine(b"\xcc", flags=CARRY, vector=3)
    cpu.step()

    ip, cs, flags = stack_words(cpu)
    assert (cs, ip) == (0x0000, CODE + 1), "the return address is the next instruction"
    assert flags & CARRY, "the flags pushed are the ones the program had"
    assert cpu.regs.cs == HANDLER_SEGMENT
    assert cpu.regs.ip == HANDLER_OFFSET


def test_the_pushed_address_is_after_the_instruction_and_not_the_instruction():
    """**The measured detail OH-5 exists to preserve**, and the one thing an
    8086 does differently from every later x86 part.

    A 386 pushes the FAULTING address for a divide error so the handler can
    fix up and retry. An 8086 pushes the address after it, which is why an
    8086 handler cannot retry and was never meant to. `D4 00` at IP 0x8573
    pushes 0x8575 -- two bytes on, because AAM is two bytes long.
    """
    cpu = machine(b"\xcd\x21", vector=0x21)   # INT 21h, two bytes
    cpu.step()
    ip, _, _ = stack_words(cpu)
    assert ip == CODE + 2


def test_taking_a_vector_clears_the_interrupt_and_trap_flags():
    """A handler entered with IF still set would be re-entered by the next
    interrupt; one entered with TF still set would single-step itself.

    Both are cleared AFTER the push, so IRET restores whatever the program
    had -- which the pushed word above already showed.
    """
    cpu = machine(b"\xcc", flags=INTERRUPT | TRAP, vector=3)
    cpu.step()
    assert not cpu.regs.flags & INTERRUPT
    assert not cpu.regs.flags & TRAP


def test_into_takes_the_vector_only_when_overflow_is_set():
    """A conditional trap, and the condition is OF. This is the difference
    between INTO and INT 4, which are otherwise the same thing."""
    taken = machine(b"\xce", flags=OVERFLOW, vector=4)
    taken.step()
    assert taken.regs.cs == HANDLER_SEGMENT

    not_taken = machine(b"\xce", flags=0, vector=4)
    not_taken.step()
    assert not_taken.regs.cs == 0x0000
    assert not_taken.regs.ip == CODE + 1


def test_iret_puts_back_everything_the_vector_took():
    """The round trip. IRET pops IP, CS and FLAGS -- and popping FLAGS is what
    makes it different from RETF, which leaves them alone."""
    cpu = machine(b"\xcc", flags=CARRY | INTERRUPT, vector=3)
    cpu.write_block((HANDLER_SEGMENT << 4) + HANDLER_OFFSET, b"\xcf")
    before_sp = cpu.regs.sp

    cpu.step()                                    # INT3
    assert cpu.regs.sp == before_sp - 6
    cpu.step()                                    # IRET

    regs = cpu.regs
    assert (regs.cs, regs.ip) == (0x0000, CODE + 1)
    assert regs.sp == before_sp
    assert regs.flags & CARRY
    assert regs.flags & INTERRUPT, "IRET restores IF, which the vector cleared"


# --- the single-step trap, which no corpus covers ---------------------------


def test_a_step_with_the_trap_flag_set_takes_vector_one():
    """The rule, from the manual: at the end of an instruction with TF set, a
    type-1 interrupt is generated.

    Asserted against the manual because it cannot be asserted against the
    corpus -- see the header. Zero of 2,857,000 captured cases have TF set.
    """
    cpu = machine(b"\x40", flags=TRAP, vector=1)   # INC AX
    cpu.step()

    assert cpu.regs.ax == 1, "the instruction ran before the trap"
    assert cpu.regs.cs == HANDLER_SEGMENT
    assert cpu.regs.ip == HANDLER_OFFSET
    ip, cs, _ = stack_words(cpu)
    assert (cs, ip) == (0x0000, CODE + 1), "a trap resumes after, not at"


def test_a_step_without_the_trap_flag_takes_nothing():
    """The other direction, so the test above cannot pass on a core that
    traps unconditionally."""
    cpu = machine(b"\x40", flags=0, vector=1)
    cpu.step()
    assert cpu.regs.cs == 0x0000
    assert cpu.regs.ip == CODE + 1


def test_the_handler_is_not_itself_single_stepped():
    """TF is cleared by the sequence, so the first instruction of the handler
    runs without trapping. Without this a stepped program would take vector 1
    forever and never execute a line of the handler."""
    cpu = machine(b"\x40", flags=TRAP, vector=1)
    cpu.write_block((HANDLER_SEGMENT << 4) + HANDLER_OFFSET, b"\x40\x40")
    cpu.step()                                    # INC AX, then the trap
    sp_in_handler = cpu.regs.sp

    cpu.step()                                    # first instruction of the handler
    assert cpu.regs.sp == sp_in_handler, "the handler trapped on itself"
    assert cpu.regs.ip == HANDLER_OFFSET + 1


def test_an_int_while_stepping_takes_one_vector_and_not_two():
    """`INT n` clears TF as part of its own sequence, so there is no second
    trap on the way out.

    This is why `Step` checks TF at BOTH ends rather than naming the four
    opcodes that raise: an instruction that took a vector has already cleared
    the flag, and the check after sees that for free.
    """
    cpu = machine(b"\xcd\x21", flags=TRAP, vector=0x21)
    cpu.write_word(1 * 4, 0x0999)                 # vector 1, somewhere else
    cpu.write_word(1 * 4 + 2, 0x3000)
    before_sp = cpu.regs.sp
    cpu.step()

    assert cpu.regs.sp == before_sp - 6, "two vectors were taken, not one"
    assert cpu.regs.cs == HANDLER_SEGMENT, "it took the INT's vector"


def test_setting_the_trap_flag_does_not_trap_after_the_instruction_that_set_it():
    """**An 8086 behaviour, and not a later-x86 one.**

    TF is sampled before the instruction, so a `POPF` that turns stepping ON
    does not trap after itself -- the trap arrives after the instruction
    following. Reading TF only at the end would trap immediately, which is
    what a 386 does and what this part does not.
    """
    # PUSH the flags-with-TF word, POPF it, then INC AX.
    cpu = machine(b"\x9d\x40", flags=0, vector=1)
    cpu.write_word(cpu.regs.sp - 2, TRAP | ALWAYS_SET)
    cpu.set_regs(sp=cpu.regs.sp - 2)

    cpu.step()                                    # POPF -- sets TF
    assert cpu.regs.flags & TRAP
    assert cpu.regs.cs == 0x0000, "POPF trapped after itself"

    cpu.step()                                    # INC AX -- now it traps
    assert cpu.regs.cs == HANDLER_SEGMENT
