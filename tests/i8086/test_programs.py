# OpenHardware - whole programs, executed end to end.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Multi-instruction programs, per ticket OH-12.

**Every other test in this repository executes exactly one instruction.** The
conformance harness loads a case, steps once and compares; the unit tests set
registers, step once and assert. That is 2.5 million hardware-verified cases
of evidence that each instruction is right in isolation, and no evidence at
all that two of them work in sequence.

The gap is not theoretical. An instruction can be perfect against the corpus
and still be useless in a program:

* IP can advance by the right amount for a case that starts fresh and by the
  wrong amount when the previous instruction left a prefix pending;
* a jump can compute the right target and land somewhere the next fetch
  cannot decode;
* an interrupt can push the right words and return to an address that is
  correct for the trap and wrong for the instruction after it.

None of those is visible one instruction at a time. So these programs run
until they finish, and check the answer -- not the intermediate state.

The expected values are arithmetic anyone can verify by hand, deliberately:
the sum of 1 to 10 is 55, five factorial is 120. A program whose answer needs
the emulator to work out is not a test of the emulator.
"""

import pytest

from core.i8086 import abi

#: Where every program is loaded, and where its data goes.
#:
#: **The interrupt vector table occupies the first 1024 bytes of memory**, and
#: the 256 after it are where a real machine keeps its BIOS data. 0x0500 is the
#: first byte clear of both.
#:
#: This file first loaded programs at 0x0000, so the test that installs a
#: handler wrote vector 0 straight over its own first instruction and the
#: fault dispatched into rubble. A single-instruction test can never meet
#: that, because it never has both a program and a vector table in memory at
#: once.
#:
#: The fix was 0x0100 -- "where DOS loads a .COM" -- which is *also* inside the
#: table: vectors 0x40 to 0xFF live at 0x0100-0x03FF. DOS gets away with it
#: because that offset sits in a segment whose base is far above the table,
#: and here every segment starts at zero. Only the sample programs that happen
#: to use a low vector number survived the difference, which is exactly the
#: kind of luck a test should not depend on.
CODE = 0x0500
DATA = 0x0200


def load(cpu, code: bytes, **regs) -> None:
    """Put a program at 0000:0100 with a stack, and nothing else set."""
    cpu.clear_memory()
    cpu.set_regs(cs=0x0000, ip=CODE, ds=0x0000, es=0x0000, ss=0x0000,
                 sp=0x0400, flags=0, **regs)
    cpu.write_block(CODE, code)


def run(cpu, stop_at: int, limit: int = 200) -> int:
    """Step until IP reaches CODE + `stop_at`, and return the number of steps.

    `stop_at` is relative to the start of the program, so it matches the byte
    offsets in each listing's comments.

    `limit` is a real bound, not a formality: a program with a wrong jump
    offset loops forever, and a test that hangs is worse than one that fails.
    """
    target = CODE + stop_at
    for taken in range(limit):
        if cpu.regs.ip == target:
            return taken
        cpu.step()
    raise AssertionError(
        f"still running after {limit} steps, at IP={cpu.regs.ip:04X}; "
        f"expected to reach {target:04X}"
    )


# --- a counted loop ------------------------------------------------------------


def test_a_loop_sums_one_to_ten(cpu):
    """The smallest program that needs three things at once: an immediate to
    load the count, an accumulator that survives the iteration, and LOOP."""
    program = bytes([
        0xB9, 0x0A, 0x00,        # 0: mov cx, 10
        0x31, 0xC0,              # 3: xor ax, ax
        0x01, 0xC8,              # 5: add ax, cx      <- top
        0xE2, 0xFC,              # 7: loop top        (-4)
        0xA3, 0x00, 0x02,        # 9: mov [0200], ax
    ])                           # 12: done
    load(cpu, program)
    run(cpu, stop_at=12)
    assert cpu.regs.ax == 55
    assert cpu.read_word(DATA) == 55
    assert cpu.regs.cx == 0, "LOOP must run the count down to zero"


def test_the_loop_really_iterated(cpu):
    """A core that fell straight through would still leave AX at 10 and look
    plausible. Ten iterations plus the four instructions around them."""
    program = bytes([
        0xB9, 0x0A, 0x00,
        0x31, 0xC0,
        0x01, 0xC8,
        0xE2, 0xFC,
        0xA3, 0x00, 0x02,
    ])
    load(cpu, program)
    steps = run(cpu, stop_at=12)
    assert steps == 2 + 10 * 2 + 1


# --- arithmetic that accumulates ------------------------------------------------


def test_a_program_computes_five_factorial(cpu):
    """MUL writes AX and DX, and the loop depends on CX surviving it."""
    program = bytes([
        0xB8, 0x01, 0x00,        # 0: mov ax, 1
        0xB9, 0x05, 0x00,        # 3: mov cx, 5
        0xF7, 0xE1,              # 6: mul cx          <- top
        0xE2, 0xFC,              # 8: loop top        (-4)
        0xA3, 0x00, 0x02,        # 10: mov [0200], ax
    ])                           # 13: done
    load(cpu, program)
    run(cpu, stop_at=13)
    assert cpu.regs.ax == 120
    assert cpu.read_word(DATA) == 120


# --- a subroutine ---------------------------------------------------------------


def test_a_call_returns_to_the_instruction_after_it(cpu):
    """CALL pushes the address of the NEXT instruction, and RET must land on
    it. Off by one either way and the program executes its own operands."""
    program = bytes([
        0xB8, 0x05, 0x00,        # 0: mov ax, 5
        0xE8, 0x03, 0x00,        # 3: call +3 -> 9
        0xA3, 0x00, 0x02,        # 6: mov [0200], ax
        # 9: the subroutine
        0x05, 0x0A, 0x00,        # 9: add ax, 10
        0xC3,                    # 12: ret
    ])
    load(cpu, program)
    run(cpu, stop_at=9)          # into the subroutine
    assert cpu.regs.sp == 0x03FE, "one word pushed"
    run(cpu, stop_at=6)          # and back out
    assert cpu.regs.sp == 0x0400, "and popped again"
    run(cpu, stop_at=9, limit=2)
    assert cpu.read_word(DATA) == 15


def test_a_subroutine_can_preserve_a_register_across_itself(cpu):
    """PUSH and POP either side of a body that clobbers BX. The stack has to
    come back balanced or RET returns to the saved value."""
    program = bytes([
        0xBB, 0x34, 0x12,        # 0: mov bx, 1234h
        0xE8, 0x06, 0x00,        # 3: call +6 -> 12
        0x89, 0x1E, 0x00, 0x02,  # 6: mov [0200], bx
        0x90, 0x90,              # 10: nop, nop
        # 12: the subroutine
        0x53,                    # 12: push bx
        0xBB, 0xFF, 0xFF,        # 13: mov bx, FFFFh   (clobber)
        0x5B,                    # 16: pop bx
        0xC3,                    # 17: ret
    ])
    load(cpu, program)
    run(cpu, stop_at=10)
    assert cpu.regs.bx == 0x1234, "BX must survive the subroutine"
    assert cpu.read_word(DATA) == 0x1234
    assert cpu.regs.sp == 0x0400, "the stack is balanced"


# --- strings --------------------------------------------------------------------


def test_a_program_measures_a_string_with_repne_scasb(cpu):
    """The idiom every C runtime uses for strlen. One instruction does the
    whole scan, and the length comes out of what CX has left."""
    program = bytes([
        0xBF, 0x00, 0x02,        # 0: mov di, 0200h
        0xB0, 0x00,              # 3: mov al, 0
        0xB9, 0x20, 0x00,        # 5: mov cx, 32
        0xF2, 0xAE,              # 8: repne scasb
        0xB8, 0x20, 0x00,        # 10: mov ax, 32
        0x29, 0xC8,              # 13: sub ax, cx
        0x48,                    # 15: dec ax          (drop the terminator)
        0xA3, 0x10, 0x02,        # 16: mov [0210], ax
    ])                           # 19: done
    load(cpu, program)
    cpu.write_block(DATA, b"OpenHardware\x00")
    run(cpu, stop_at=19)
    assert cpu.read_word(0x0210) == len("OpenHardware")


def test_a_program_copies_a_string_with_rep_movsb(cpu):
    program = bytes([
        0xBE, 0x00, 0x02,        # 0: mov si, 0200h
        0xBF, 0x00, 0x03,        # 3: mov di, 0300h
        0xB9, 0x0C, 0x00,        # 6: mov cx, 12
        0xF3, 0xA4,              # 9: rep movsb
    ])                           # 11: done
    load(cpu, program)
    cpu.write_block(DATA, b"OpenHardware")
    run(cpu, stop_at=11)
    assert cpu.read_block(0x0300, 12) == b"OpenHardware"


# --- an interrupt, taken and returned from --------------------------------------


def test_a_divide_error_runs_a_handler_and_comes_back(cpu):
    """The whole interrupt path in one program: a fault, the vector table, a
    handler that leaves a mark, IRET, and the instruction after the fault.

    This is the test that most needed a program to exist. The trap was
    verified one instruction at a time against 47 corpus cases -- but a case
    ends the moment the handler is entered, so nothing had ever checked that
    IRET returns to the right place, or that execution continues at all.
    """
    program = bytes([
        0xB8, 0x10, 0x00,        # 0: mov ax, 16
        0xB3, 0x00,              # 3: mov bl, 0
        0xF6, 0xF3,              # 5: div bl        -> interrupt 0
        0xA3, 0x00, 0x02,        # 7: mov [0200], ax
    ])                           # 10: done
    load(cpu, program)
    # Vector 0 -> 0000:0800, and a handler that marks memory and returns.
    # The handler lives well clear of both the program and the vector table.
    cpu.write_word(0x0000, 0x0800)
    cpu.write_word(0x0002, 0x0000)
    cpu.write_block(0x0800, bytes([
        0xC7, 0x06, 0x02, 0x02, 0xEF, 0xBE,   # mov word [0202], BEEFh
        0xCF,                                  # iret
    ]))

    load_sp = cpu.regs.sp
    run(cpu, stop_at=10)

    assert cpu.read_word(0x0202) == 0xBEEF, "the handler never ran"
    assert cpu.read_word(DATA) == 16, "execution did not resume after the fault"
    assert cpu.regs.sp == load_sp, "IRET must unwind all three pushed words"


def test_an_explicit_software_interrupt_behaves_the_same_way(cpu):
    """INT n shares RaiseInterrupt with the divide error, so this is the same
    path reached deliberately rather than by a fault."""
    program = bytes([
        0xCD, 0x21,              # 0: int 21h
        0xA3, 0x00, 0x02,        # 2: mov [0200], ax
    ])                           # 5: done
    load(cpu, program, ax=0x1234)
    cpu.write_word(0x21 * 4, 0x0800)
    cpu.write_word(0x21 * 4 + 2, 0x0000)
    cpu.write_block(0x0800, bytes([
        0xB8, 0x99, 0x00,        # mov ax, 0099h
        0xCF,                    # iret
    ]))
    run(cpu, stop_at=5)
    assert cpu.regs.ax == 0x0099, "the handler's work must survive IRET"
    assert cpu.read_word(DATA) == 0x0099


# --- the thing that must not happen ----------------------------------------------


def test_an_unimplemented_opcode_stops_the_program_loudly(cpu):
    """A program is where a silently-skipped instruction does the most damage:
    it does not fail, it produces a wrong answer several thousand
    instructions later. `step` raises instead."""
    # Every opcode the 8086 defines is implemented, so the gap has to be one
    # of the encodings inside a group that the part leaves undefined: FF /7 is
    # group 5's eighth member and there is no instruction there.
    program = bytes([
        0xB8, 0x05, 0x00,        # 0: mov ax, 5
        0xFF, 0xF8,              # 3: FF /7 -- no such instruction
    ])
    load(cpu, program)
    assert cpu.step() is True    # mov
    with pytest.raises(abi.Unimplemented):
        cpu.step()
    assert cpu.regs.ip == CODE + 3, "IP must not move past what it refused"
