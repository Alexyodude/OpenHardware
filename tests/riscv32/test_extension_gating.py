# OpenHardware — what this part must refuse, which the oracle cannot check.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file is separate from test_lockstep.py
#
# Everything here is invisible to the oracle. rvcpp has **no extension gating
# of any kind** -- all 94 of its opcodes are live unconditionally, Zbc included
# -- so it executes an atomic whether the part being modelled has the A
# extension or not. Measured, not inferred: docs/architectures.md 2.1b.
#
# The consequence is concrete. The ESP32-C3 is RV32IMC and **must trap
# `lr.w`**; the ESP32-C6 is RV32IMAC and must execute it. A core built only
# against rvcpp will happily run atomics on a C3, and a lockstep suite will
# agree with it every time. So these verdicts come from the ISA manual and from
# docs/architectures.md 4.2's datasheet row, which is a different evidence
# class, and this repository's habit is to keep those apart rather than average
# them.
#
# OH-35 turns this into a generated corpus. This file is the part of it that
# OH-34 can carry on its own, and it is deliberately here rather than deferred:
# the gate has to exist before the decoder grows, or every instruction added
# after it inherits the wrong default.

import pytest

from core.riscv32 import abi

from . import encode as e
from .conftest import PC, load


def test_an_atomic_is_illegal_on_a_c3_and_merely_unwritten_on_a_c6(cpu):
    """**The distinction this whole core is shaped around.**

    Same encoding, two parts, two different correct answers. `Illegal` is the
    C3 behaving properly; `Unimplemented` is this emulator being unfinished on
    a C6. A core with one outcome for both would be silently wrong for one
    family, and no run of test_lockstep.py could ever say which.
    """
    for atomic in (e.lr_w("t0", "t1"), e.amoadd_w("t0", "t1", "t2")):
        load(cpu, [atomic])
        cpu.set_extensions(abi.ESP32_C3)
        with pytest.raises(abi.Illegal):
            cpu.step()

        load(cpu, [atomic])
        cpu.set_extensions(abi.ESP32_C6)
        with pytest.raises(abi.Unimplemented):
            cpu.step()


def test_the_two_refusals_are_different_codes_at_the_abi_and_not_only_in_python(cpu):
    """The exception types are a convenience of the binding. What a second
    caller sees -- a WASM build, a corpus runner -- is the integer, and if
    those collapsed the Python distinction would be decoration."""
    assert abi.ILLEGAL != abi.UNIMPLEMENTED
    load(cpu, [e.lr_w("t0", "t1")])
    cpu.set_extensions(abi.ESP32_C3)
    assert cpu._lib.riscv32_step(cpu._handle) == abi.ILLEGAL
    cpu.set_extensions(abi.ESP32_C6)
    assert cpu._lib.riscv32_step(cpu._handle) == abi.UNIMPLEMENTED


def test_a_multiply_is_illegal_without_m_and_unwritten_with_it(cpu):
    """Every ESP32-C part has M, so the illegal case is not one a board here
    will reach. It is checked anyway because it is the same gate as A, and a
    gate that is only ever exercised in one direction is half tested."""
    load(cpu, [e.mul("t0", "t1", "t2")])
    cpu.set_extensions(0)
    with pytest.raises(abi.Illegal):
        cpu.step()

    load(cpu, [e.mul("t0", "t1", "t2")])
    cpu.set_extensions(abi.EXT_M)
    with pytest.raises(abi.Unimplemented):
        cpu.step()


def test_a_compressed_encoding_is_illegal_without_c_and_unwritten_with_it(cpu):
    """The first halfword decides the width, so a 16-bit encoding is refused
    before anything tries to read four bytes."""
    halfword = e.c_addi("ra", 1)
    word = halfword | (halfword << 16)

    load(cpu, [word])
    cpu.set_extensions(abi.EXT_M)
    with pytest.raises(abi.Illegal):
        cpu.step()

    load(cpu, [word])
    cpu.set_extensions(abi.ESP32_C3)
    with pytest.raises(abi.Unimplemented):
        cpu.step()


def test_instruction_alignment_follows_the_c_extension(cpu):
    """Four bytes without C, two with it. The requirement genuinely changes,
    which is why the core derives it instead of holding a constant."""
    load(cpu, [e.jalr("ra", "t0", 0)])
    cpu.set_regs([0] * 5 + [PC + 2] + [0] * 26, pc=PC)
    cpu.set_extensions(0)
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{PC + 2:08x}" in str(caught.value)

    load(cpu, [e.jalr("ra", "t0", 0)])
    cpu.set_regs([0] * 5 + [PC + 2] + [0] * 26, pc=PC)
    cpu.set_extensions(abi.ESP32_C3)
    cpu.step()
    assert cpu.pc == PC + 2


def test_an_rv64_shift_encoding_is_illegal_on_a_32_bit_part(cpu):
    """A six-bit shift amount is the RV64 encoding, and an RV32 part raises
    illegal-instruction rather than shifting by a masked amount.

    This is the same class of hole rvcpp has in its own compressed decoder,
    where C_LD, C_SD, C_LDSP and C_SDSP execute as RV64 integer loads on a
    32-bit model (docs/architectures.md 2.1b). An RV64 meaning quietly accepted
    on a 32-bit part is a thing that has already happened once, to somebody who
    knew the architecture better than this file does.
    """
    rv64_slli = e.slli("t0", "t1", 0) | (1 << 25)
    load(cpu, [rv64_slli])
    cpu.set_extensions(abi.ESP32_C6)
    with pytest.raises(abi.Illegal):
        cpu.step()


def test_system_encodings_are_unwritten_rather_than_faked(cpu):
    """ECALL, EBREAK and Zicsr all either enter a trap or touch a CSR, and
    this core has neither. Answering a CSR read with a plausible value would
    be inventing machine state, and ESP-IDF reads mstatus and mtvec within its
    first hundred instructions."""
    load(cpu, [e.ecall()])
    cpu.set_extensions(abi.ESP32_C6)
    with pytest.raises(abi.Unimplemented):
        cpu.step()


def test_a_word_of_zeros_and_a_word_of_ones_are_both_illegal(cpu):
    """What a program reads once it has run off the end of anything. Both must
    stop the core rather than decode into something that looks like progress.
    """
    for word in (0x00000000, 0xFFFFFFFF):
        load(cpu, [word])
        cpu.set_extensions(abi.ESP32_C6)
        with pytest.raises(abi.Illegal):
            cpu.step()
