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


def test_zba_is_illegal_on_a_c3_and_executes_on_an_rp2350(cpu):
    """The gating case for the first extension this core *implements*.

    Different from the atomic above in one way that matters. `lr.w` on an
    ESP32-C6 answers `Unimplemented`, because the extension is enabled and
    nobody has written it. `sh1add` on an RP2350 answers `Ok` and produces a
    number -- so this pair separates "the part refuses it" from "the part runs
    it", which is the stronger of the two statements and the one that could not
    be made before.

    rvcpp executes `sh1add` for both parts (rv_core.cpp:265), so no lockstep
    run will ever produce the left-hand half of this test.
    """
    for encoding, shift in ((e.sh1add("a0", "t0", "t1"), 1),
                            (e.sh2add("a0", "t0", "t1"), 2),
                            (e.sh3add("a0", "t0", "t1"), 3)):
        load(cpu, [encoding])
        cpu.set_extensions(abi.ESP32_C3)
        with pytest.raises(abi.Illegal):
            cpu.step()

        load(cpu, [encoding])
        cpu.set_extensions(abi.RP2350_MODELLED)
        regs = cpu.get_regs().as_list()
        regs[5], regs[6] = 7, 5          # t0, t1
        cpu.set_regs(regs, pc=PC)
        cpu.step()
        assert cpu.reg(10) == (7 << shift) + 5, (
            f"sh{shift}add produced {cpu.reg(10)}, expected (7 << {shift}) + 5"
        )


def test_zba_is_not_reached_by_enabling_some_other_extension(cpu):
    """The bit has to be the Zba bit, not any bit that happens to be set.

    A gate written as "not the base ISA" would let M or A switch Zba on, and
    every test above would still pass because both parts that have M also have
    everything else those tests use. The ESP32-C6 is the counter-example that
    exists in silicon: RV32IMAC, so M and A and C are all on and Zba is not.
    """
    load(cpu, [e.sh1add("a0", "t0", "t1")])
    cpu.set_extensions(abi.ESP32_C6)
    with pytest.raises(abi.Illegal):
        cpu.step()

    assert abi.RP2350_MODELLED & abi.EXT_ZBA
    assert not abi.ESP32_C6 & abi.EXT_ZBA
    assert not abi.ESP32_C3 & abi.EXT_ZBA


def test_an_unassigned_encoding_under_zbas_funct7_is_still_illegal(cpu):
    """Zba is three funct3 values, not a whole funct7.

    **This docstring used to say funct7 0b0010000 with funct3 001 was `bset`
    from Zbs. It is not, and the error survived into OH-44's justification.**
    `bset` is funct7 0b0010100 -- `RVOPC_BSET_BITS` in rvcpp's own table --
    so this encoding belongs to no extension at all. The assertion was always
    right and only the label was wrong, which is why nothing failed when Zbs
    landed and why the "tripwire" OH-44 was sequenced for did not exist.

    What it does check is still worth checking, and now more so: Zba opened
    funct7 0b0010000 at funct3 010, 100 and 110, and this is one of the four
    values it must have left shut.
    """
    unassigned = e.r_type(0x10, "t1", "t0", 0x1, "a0", 0x33)
    load(cpu, [unassigned])
    cpu.set_extensions(abi.RP2350_MODELLED)
    with pytest.raises(abi.Illegal):
        cpu.step()


def test_zbs_opens_its_funct7_values_only_at_the_funct3_it_defines(cpu):
    """The guard the test above was *meant* to be, on the right encodings.

    Zbs defines funct3 001 for all three of its funct7 values and funct3 101
    for 0x24 alone. So `0x14` with funct3 101 is not an instruction, and a
    gate keyed on the extension and the funct7 without the funct3 would
    execute it. rvcpp implements Zbs, so a lockstep run would have agreed.
    """
    for funct7, funct3 in ((0x14, 0x5), (0x34, 0x5), (0x14, 0x2), (0x24, 0x3)):
        load(cpu, [e.r_type(funct7, "t1", "t0", funct3, "a0", 0x33)])
        cpu.set_extensions(abi.RP2350_MODELLED)
        with pytest.raises(abi.Illegal):
            cpu.step()


def test_zbs_does_not_reopen_the_rv64_six_bit_shift(cpu):
    """The line Zbs actually had to be threaded past, and the one that matters.

    `SLLI` refuses any nonzero funct7 because a one in bit 25 is RV64's
    six-bit shift amount, and an RV32 part raises illegal-instruction rather
    than shifting by a masked one. Zbs shares that funct3, so the refusal had
    to become a list of named funct7 values instead of "nonzero" -- and every
    Zbs funct7 has bit 25 clear, so the RV64 encoding stays shut.

    Written as its own test because the two facts are separable: a decoder
    could get every Zbs bit right and still have opened this by using
    `funct7 != 0` as the new gate.
    """
    rv64_slli = e.r_type(0x01, 3, "t0", 0x1, "a0", 0x13)
    for part in (abi.ESP32_C6, abi.RP2350_MODELLED):
        load(cpu, [rv64_slli])
        cpu.set_extensions(part)
        with pytest.raises(abi.Illegal):
            cpu.step()


def test_zbs_is_illegal_on_both_esp32_parts_and_executes_on_an_rp2350(cpu):
    """All eight, both ways, with the values checked rather than the outcome.

    An extension test that only asserts "did not raise" would pass over a
    decoder that ran the wrong one of the four -- they share a funct7 space
    and differ by three bits, which is exactly where a transposition hides.
    """
    start = 0xF0F0F0F0
    index = 4
    expected = {
        "bset": start | (1 << index),
        "bclr": start & ~(1 << index),
        "binv": start ^ (1 << index),
        "bext": (start >> index) & 1,
    }
    for name, encoded in (
        ("bset", e.bset("a0", "t0", "t1")), ("bclr", e.bclr("a0", "t0", "t1")),
        ("binv", e.binv("a0", "t0", "t1")), ("bext", e.bext("a0", "t0", "t1")),
        ("bset", e.bseti("a0", "t0", index)), ("bclr", e.bclri("a0", "t0", index)),
        ("binv", e.binvi("a0", "t0", index)), ("bext", e.bexti("a0", "t0", index)),
    ):
        for part in (abi.ESP32_C3, abi.ESP32_C6):
            load(cpu, [encoded])
            cpu.set_extensions(part)
            with pytest.raises(abi.Illegal):
                cpu.step()

        load(cpu, [encoded])
        cpu.set_extensions(abi.RP2350_MODELLED)
        regs = cpu.get_regs().as_list()
        regs[5], regs[6] = start, index      # t0, t1
        cpu.set_regs(regs, pc=PC)
        cpu.step()
        assert cpu.reg(10) == expected[name], (
            f"{name} ({encoded:#010x}) produced {cpu.reg(10):#010x}, "
            f"expected {expected[name]:#010x}"
        )


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
