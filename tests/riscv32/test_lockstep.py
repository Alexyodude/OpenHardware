# OpenHardware — this core and rvcpp, executing the same bytes.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What these prove, and the smaller claim they make than cortexm0's
#
# `tests/cortexm0/test_blink.py` runs an image built by a real compiler. That
# cannot be done here: **this machine has no RISC-V toolchain** -- no
# riscv32-esp-elf-gcc, no riscv64-unknown-elf-gcc, no clang, and no PlatformIO
# package to borrow one from. So the programs below are hand-encoded by
# `encode.py`, and "runs real compiled firmware" is a claim OH-34 cannot make
# until a cross-compiler exists here.
#
# What they do prove is the thing a differential run is for: the same bytes,
# two independently written implementations, compared over all 32 registers
# and the PC after every single instruction. rvcpp was written by the author of
# the Hazard3 silicon from the same manual, and it is not derived from anything
# this project wrote.
#
# ## And the thing they can never prove
#
# rvcpp has no extension gating. Everything about what an ESP32-C3 must
# *refuse* is invisible here and lives in `test_extension_gating.py`, whose
# verdicts come from the ISA manual instead. A green run of this file says the
# core agrees about legal code and says nothing at all about illegal code.

import pytest

from core.riscv32 import abi

from . import encode as e
from . import lockstep

#: rvcpp's testbench halts when the CPU writes IO_EXIT. Every program ends with
#: this or it runs to the cycle limit, and a run that ended by timing out has
#: compared a tail of instructions nobody wrote.
EXIT = [e.lui("a7", 0xC0000), e.sw("x0", "a7", 8)]


def image(body: list[int]) -> bytes:
    return e.image(body + EXIT)


def check(report: lockstep.Report, least: int) -> None:
    """Assert the two models agreed, with the failure spelled out."""
    assert report.divergence is None, str(report.divergence)
    assert report.stopped is None, (
        f"this core stopped after {report.agreed} of {report.traced} "
        f"instructions: {report.stopped}"
    )
    assert report.matched_the_oracle
    assert report.agreed >= least, (
        f"only {report.agreed} instructions were compared; the program was "
        f"meant to run at least {least}"
    )


def test_zba_agrees_with_rvcpp(oracle, tmp_path):
    """The RP2350's Zba, against the model written by the author of its silicon.

    `sh1add`, `sh2add` and `sh3add` are the whole of Zba on RV32, and they are
    the first extension this core implements rather than classifies-and-
    refuses. Run with `RP2350_MODELLED`, because with Zba off the core must
    raise illegal-instruction -- which is `test_extension_gating.py`'s half of
    the answer and is invisible here, since rvcpp executes them for every part.

    Both operands are chosen to overflow: `(rs1 << 3) + rs2` on 0x2000_0000
    wraps, and a model that widened to 64 bits somewhere would agree on every
    small case and diverge only here.
    """
    body = [
        e.lui("t0", 0x12345),
        e.addi("t0", "t0", 0x678),
        e.addi("t1", "x0", -1),
        e.sh1add("a0", "t0", "t1"),
        e.sh2add("a1", "t0", "t1"),
        e.sh3add("a2", "t0", "t1"),
        e.lui("t2", 0x20000),
        e.sh3add("a3", "t2", "t0"),
        e.sh1add("a4", "t1", "t1"),
        e.sh2add("x0", "t0", "t1"),
    ]
    check(
        lockstep.run(image(body), tmp_path, extensions=abi.RP2350_MODELLED),
        least=len(body),
    )


def test_zbs_agrees_with_rvcpp(oracle, tmp_path):
    """All eight Zbs encodings against the model written by Hazard3's author.

    Both forms of all four, because the register and immediate halves are
    decoded in different places -- opcode 0b0110011 and 0b0010011 -- and a
    core could get one right and the other wrong with no test between them.

    Bit 31 is exercised on purpose: `bset` at index 31 is the one that
    distinguishes `1u << 31` from a signed shift, and a model that got that
    wrong would agree on every other index.
    """
    body = [
        e.lui("t0", 0xF0F0F),
        e.addi("t0", "t0", 0x0F0),
        e.addi("t1", "x0", 4),
        e.bset("a0", "t0", "t1"),
        e.bclr("a1", "t0", "t1"),
        e.binv("a2", "t0", "t1"),
        e.bext("a3", "t0", "t1"),
        e.bseti("a4", "t0", 31),
        e.bclri("a5", "t0", 31),
        e.binvi("a6", "t0", 0),
        e.bexti("a7", "t0", 31),
        # An index above 31 cannot be encoded -- the field is five bits -- so
        # the wrap a 64-bit model would show up on is unreachable here, and
        # saying so is cheaper than a test that pretends to cover it.
        e.bext("s0", "t0", "t0"),
    ]
    check(
        lockstep.run(image(body), tmp_path, extensions=abi.RP2350_MODELLED),
        least=len(body),
    )


def test_zbs_immediates_share_a_funct3_with_the_shifts_and_agree_anyway(oracle, tmp_path):
    """`slli`, `srli`, `srai` and the Zbs immediates in one program.

    They live under two funct3 values between them and are told apart by
    funct7. Running them adjacently is what would catch a decoder that opened
    the Zbs funct7 values and lost a shift, or the reverse -- neither of which
    a program using only one family would notice.
    """
    body = [
        e.addi("t0", "x0", -1),
        e.slli("a0", "t0", 5),
        e.srli("a1", "t0", 5),
        e.srai("a2", "t0", 5),
        e.bseti("a3", "t0", 5),
        e.bclri("a4", "t0", 5),
        e.bexti("a5", "t0", 5),
        e.binvi("a6", "t0", 5),
        e.slli("a7", "t0", 0),
        e.bclri("s0", "t0", 0),
    ]
    check(
        lockstep.run(image(body), tmp_path, extensions=abi.RP2350_MODELLED),
        least=len(body),
    )


def test_zba_writing_x0_changes_nothing_in_either_model(oracle, tmp_path):
    """x0 stays zero however it is written, and both models must agree it does.

    The last instruction of the program above targets x0 on purpose. rvcpp
    reports a writeback for it, so a core that let the write land would diverge
    on the very next comparison -- but only if something is watching all 32
    registers, which is why lockstep compares the whole file rather than rd.
    """
    body = [e.addi("t0", "x0", 7), e.sh3add("x0", "t0", "t0")]
    report = lockstep.run(image(body), tmp_path, extensions=abi.RP2350_MODELLED)
    check(report, least=len(body))


def test_the_whole_alu_agrees_with_rvcpp(oracle, tmp_path):
    """Every register-register and register-immediate form in one program, so
    a divergence names the instruction rather than the family."""
    body = [
        e.lui("t0", 0x12345),
        e.addi("t0", "t0", 0x678),
        e.addi("t1", "x0", -1),
        e.srli("t2", "t1", 4),
        e.srai("s0", "t1", 4),
        e.slt("s1", "t1", "x0"),
        e.sltu("a0", "t1", "x0"),
        e.xor_("a1", "t0", "t1"),
        e.and_("a2", "t0", "t1"),
        e.or_("a3", "t0", "t1"),
        e.sub("a4", "t0", "t1"),
        e.slli("a5", "t0", 4),
        e.sra("a6", "t1", "t0"),
        e.auipc("s2", 0),
    ]
    check(lockstep.run(image(body), tmp_path), least=len(body))


def test_a_counted_loop_agrees_with_rvcpp(oracle, tmp_path):
    """A backward branch taken nine times and not taken once.

    The instruction count is what makes this different from the ALU program:
    every one of the 30-odd steps is compared, so a branch that fell through a
    lap early would show as a PC divergence rather than as a wrong sum at the
    end.
    """
    body = [
        e.addi("t0", "x0", 0),        # sum
        e.addi("t1", "x0", 1),        # i
        e.addi("t2", "x0", 11),       # limit
        e.add("t0", "t0", "t1"),      # loop:
        e.addi("t1", "t1", 1),
        e.blt("t1", "t2", -8),
    ]
    report = lockstep.run(image(body), tmp_path)
    check(report, least=33)


def test_a_call_and_a_return_agree_with_rvcpp(oracle, tmp_path):
    """JAL links, JALR returns through the link register.

    A core can pass every arithmetic test and fail here, which is the reason
    tools/lockstep_armv6m.mjs exists for the Cortex-M0: random encodings never
    build a stack frame or return through a register they just wrote.
    """
    body = [
        e.addi("a0", "x0", 7),
        e.jal("ra", 12),              # call the doubler at +16
        e.addi("s0", "a0", 0),        # ...returns here
        e.jal("x0", 12),              # jump past it, to the exit
        e.add("a0", "a0", "a0"),      # doubler:
        e.jalr("x0", "ra", 0),
    ]
    check(lockstep.run(image(body), tmp_path), least=6)


def test_memory_traffic_agrees_with_rvcpp(oracle, tmp_path):
    """Every load and store width, including both sign extensions.

    Registers are all this compares, so a store is only visible through the
    load that reads it back -- which is why each store here has one.
    """
    body = [
        e.lui("t0", 0x80000),
        e.addi("t1", "x0", 0x123),
        e.sw("t1", "t0", 0x100),
        e.lw("t2", "t0", 0x100),
        e.lb("s0", "t0", 0x100),
        e.lbu("s1", "t0", 0x101),
        e.lh("a0", "t0", 0x100),
        e.lhu("a1", "t0", 0x102),
        e.sb("t1", "t0", 0x104),
        e.lbu("a2", "t0", 0x104),
        e.sh("t1", "t0", 0x106),
        e.lhu("a3", "t0", 0x106),
    ]
    check(lockstep.run(image(body), tmp_path), least=len(body))


def test_the_rig_reports_a_divergence_rather_than_only_being_able_to_agree(
        oracle, tmp_path, monkeypatch):
    """**A green run is worthless if red is unreachable.**

    The oracle is doctored by one bit -- one traced writeback given a value it
    did not have -- and the comparison must find it, name the register and name
    the step. Nothing else in this file could tell a working rig from one that
    returns `matched_the_oracle` unconditionally.
    """
    body = [e.addi("t0", "x0", 5), e.addi("t1", "x0", 7), e.add("t2", "t0", "t1")]
    real = lockstep.trace

    def doctored(*args, **kwargs):
        steps = real(*args, **kwargs)
        first = steps[0]
        assert first.writeback is not None, first
        number, value = first.writeback
        return [
            lockstep.OracleStep(first.pc, first.encoding, first.width,
                                (number, value + 1)),
            *steps[1:],
        ]

    monkeypatch.setattr(lockstep, "trace", doctored)
    report = lockstep.run(image(body), tmp_path)

    assert report.divergence is not None
    assert not report.matched_the_oracle
    assert report.divergence.index == 0
    assert report.divergence.field == "t0"
    assert report.divergence.ours == 5
    assert report.divergence.oracle == 6


def test_an_instruction_this_core_has_not_written_stops_the_run_and_says_so(
        oracle, tmp_path):
    """rvcpp runs `fence.i` straight through; this core has no Zifencei.

    The report has to separate that from a disagreement. "We stopped after 3 of
    9" is a progress meter; "we disagreed at step 3" is a bug. Reading one as
    the other sends somebody hunting for a decoder fault that is not there.

    **This used to use `mul`, until OH-55 implemented M and the test quietly
    ran to completion instead** -- agreed=4, stopped=None, and an assertion
    about stopping that no longer had anything to stop on. Any instruction this
    core has not written will do; `fence.i` is the cheapest, because it touches
    no memory and needs no operands.
    """
    body = [
        e.addi("t0", "x0", 6),
        e.addi("t1", "x0", 7),
        e.fence_i(),
    ]
    report = lockstep.run(image(body), tmp_path)

    assert report.divergence is None
    assert report.stopped is not None
    assert "not implemented" in report.stopped
    assert report.agreed == 2
    assert not report.matched_the_oracle


def test_an_empty_trace_is_an_error_rather_than_a_silent_agreement(oracle, tmp_path):
    """Zero instructions compared is zero disagreements found.

    Provoked with a zero cycle budget, which is the shortest route to the
    condition the guard is for: rvcpp ran and printed no instructions. The
    first attempt at this test passed an empty image instead and did not
    raise -- rvcpp executes the zeros, traps, and traces the trap, so it is
    not a silent case at all.
    """
    with pytest.raises(lockstep.OracleError, match="traced no instructions"):
        lockstep.trace(e.image([e.addi("t0", "x0", 1)]), cycles=0,
                       tmp_dir=tmp_path)


def test_the_lockstep_board_is_in_this_file_and_not_in_the_core():
    """The core knows no addresses at all, which is the property commit
    cd9f8c8 restored on cortexm0 and that this ticket was told not to re-earn.
    A fresh core cannot reach RAM until something describes it."""
    with abi.Cpu() as fresh:
        assert not fresh.in_range(lockstep.RAM_BASE, 4)
        assert fresh.extensions() == 0
