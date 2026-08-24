# OpenHardware — the RV32I base integer set, instruction by instruction.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# These check this core alone and run in milliseconds. They are not the
# evidence that the core is right -- `test_lockstep.py` is, because it compares
# against an implementation written by somebody else. What these are for is
# saying *which* instruction is wrong when lockstep stops, which a differential
# run cannot tell you: it reports the first disagreement and nothing about the
# nine instructions it never reached.
#
# No `@pytest.mark.parametrize` anywhere: `tools/inventory.py` counts
# `def test_*` with `ast` and `test_ast_count_matches_pytest_collection` fails
# on the divergence. Cases that repeat, repeat inside one test.

import pytest

from core.riscv32 import abi

from . import encode as e
from .conftest import PC, RAM, RAM_SIZE, SCRATCH, load, run


def test_x0_stays_zero_however_hard_a_program_writes_to_it(cpu):
    """`add x0, x1, x2` is legal, common, and must do nothing at all."""
    run(cpu, [e.addi("ra", "x0", 5), e.addi("x0", "ra", 99), e.add("x0", "ra", "ra")])
    assert cpu.reg(0) == 0
    assert cpu.reg(1) == 5


def test_the_register_immediate_arithmetic(cpu):
    cases = (
        (e.addi("t1", "t0", 10), 5, 15),
        (e.addi("t1", "t0", -10), 5, (5 - 10) & 0xFFFFFFFF),
        (e.xori("t1", "t0", 0x0F0), 0x0FF, 0x00F),
        (e.ori("t1", "t0", 0x0F0), 0x00F, 0x0FF),
        (e.andi("t1", "t0", 0x0F0), 0x0FF, 0x0F0),
        (e.slti("t1", "t0", 0), 0xFFFFFFFF, 1),
        (e.sltiu("t1", "t0", 0), 0xFFFFFFFF, 0),
        (e.sltiu("t1", "t0", 1), 0, 1),
    )
    for instruction, operand, expected in cases:
        load(cpu, [instruction])
        cpu.set_regs([0] * 5 + [operand] + [0] * 26, pc=PC)
        cpu.step()
        assert cpu.reg(6) == expected, f"0x{instruction:08x} on 0x{operand:08x}"


def test_the_register_register_arithmetic(cpu):
    cases = (
        (e.add("t2", "t0", "t1"), 7, 5, 12),
        (e.sub("t2", "t0", "t1"), 7, 5, 2),
        (e.sub("t2", "t0", "t1"), 5, 7, (5 - 7) & 0xFFFFFFFF),
        (e.xor_("t2", "t0", "t1"), 0xFF, 0x0F, 0xF0),
        (e.or_("t2", "t0", "t1"), 0xF0, 0x0F, 0xFF),
        (e.and_("t2", "t0", "t1"), 0xFF, 0x0F, 0x0F),
        (e.slt("t2", "t0", "t1"), 0xFFFFFFFF, 0, 1),
        (e.sltu("t2", "t0", "t1"), 0xFFFFFFFF, 0, 0),
        (e.sll("t2", "t0", "t1"), 1, 4, 16),
        (e.srl("t2", "t0", "t1"), 0x80000000, 4, 0x08000000),
        (e.sra("t2", "t0", "t1"), 0x80000000, 4, 0xF8000000),
    )
    for instruction, a, b, expected in cases:
        load(cpu, [instruction])
        cpu.set_regs([0] * 5 + [a, b] + [0] * 25, pc=PC)
        cpu.step()
        assert cpu.reg(7) == expected, f"0x{instruction:08x} on 0x{a:08x}, 0x{b:08x}"


def test_a_shift_uses_only_the_low_five_bits_of_its_amount(cpu):
    """RV32 masks the shift amount to five bits, so a shift by 33 is a shift
    by 1. A model that shifted by 33 in C++ would be undefined behaviour that
    happens to look right on x86 and wrong on Arm."""
    load(cpu, [e.sll("t2", "t0", "t1")])
    cpu.set_regs([0] * 5 + [1, 33] + [0] * 25, pc=PC)
    cpu.step()
    assert cpu.reg(7) == 2


def test_an_arithmetic_right_shift_keeps_the_sign_and_a_logical_one_does_not(cpu):
    run(cpu, [
        e.addi("t0", "x0", -8),
        e.srai("t1", "t0", 1),
        e.srli("t2", "t0", 1),
    ])
    assert cpu.reg(6) == (-4) & 0xFFFFFFFF
    assert cpu.reg(7) == 0x7FFFFFFC


def test_lui_lands_in_the_top_twenty_bits_and_auipc_adds_the_pc(cpu):
    run(cpu, [e.lui("t0", 0x12345), e.auipc("t1", 0)])
    assert cpu.reg(5) == 0x12345000
    # AUIPC of zero is the address of the AUIPC itself, which is how every
    # position-independent RISC-V program finds out where it is.
    assert cpu.reg(6) == PC + 4


def test_every_branch_condition_both_ways(cpu):
    """Six conditions, taken and not taken. The offset is 8, so a taken branch
    skips the instruction after it and a not-taken one does not."""
    cases = (
        (e.beq, 3, 3, True), (e.beq, 3, 4, False),
        (e.bne, 3, 4, True), (e.bne, 3, 3, False),
        (e.blt, 0xFFFFFFFF, 1, True), (e.blt, 1, 0xFFFFFFFF, False),
        (e.bge, 1, 0xFFFFFFFF, True), (e.bge, 0xFFFFFFFF, 1, False),
        (e.bltu, 1, 0xFFFFFFFF, True), (e.bltu, 0xFFFFFFFF, 1, False),
        (e.bgeu, 0xFFFFFFFF, 1, True), (e.bgeu, 1, 0xFFFFFFFF, False),
    )
    for branch, a, b, expected in cases:
        load(cpu, [branch("t0", "t1", 8)])
        cpu.set_regs([0] * 5 + [a, b] + [0] * 25, pc=PC)
        cpu.step()
        target = PC + 8 if expected else PC + 4
        assert cpu.pc == target, (
            f"{branch.__name__}(0x{a:08x}, 0x{b:08x}) went to 0x{cpu.pc:08x}"
        )


def test_a_branch_compares_signed_where_it_says_signed(cpu):
    """BLT and BLTU differ on exactly this pair and on nothing else visible.
    Getting them the wrong way round passes every equality test."""
    for branch, expected in ((e.blt, True), (e.bltu, False)):
        load(cpu, [branch("t0", "t1", 8)])
        cpu.set_regs([0] * 5 + [0xFFFFFFFF, 1] + [0] * 25, pc=PC)
        cpu.step()
        assert (cpu.pc == PC + 8) is expected, branch.__name__


def test_jal_links_the_instruction_after_it(cpu):
    load(cpu, [e.jal("ra", 16)])
    cpu.step()
    assert cpu.pc == PC + 16
    assert cpu.reg(1) == PC + 4


def test_jalr_clears_bit_zero_of_its_target(cpu):
    """A function pointer with a stray low bit must work rather than trap.
    The architecture says the bit is cleared, not checked."""
    load(cpu, [e.jalr("ra", "t0", 0)])
    cpu.set_regs([0] * 5 + [PC + 0x101] + [0] * 26, pc=PC)
    cpu.step()
    assert cpu.pc == PC + 0x100


def test_jalr_reads_its_source_before_writing_its_link(cpu):
    """`jalr ra, ra, 0` is how a compiler returns through a saved pointer, so
    rd and rs1 being the same register is the common case rather than a corner.
    Writing the link first would jump to the link."""
    load(cpu, [e.jalr("ra", "ra", 0)])
    cpu.set_regs([0, PC + 0x40] + [0] * 30, pc=PC)
    cpu.step()
    assert cpu.pc == PC + 0x40
    assert cpu.reg(1) == PC + 4


def test_loads_sign_extend_and_zero_extend_as_their_names_say(cpu):
    """LB and LBU differ on exactly one bit of the source and produce values
    32 bits apart. The same for LH and LHU."""
    cpu.write_word(SCRATCH, 0x0000FF80)
    cases = (
        (e.lb("t1", "t0", 0), 0xFFFFFF80),
        (e.lbu("t1", "t0", 0), 0x00000080),
        (e.lh("t1", "t0", 0), 0xFFFFFF80),
        (e.lhu("t1", "t0", 0), 0x0000FF80),
        (e.lw("t1", "t0", 0), 0x0000FF80),
    )
    for instruction, expected in cases:
        load(cpu, [instruction])
        cpu.set_regs([0] * 5 + [SCRATCH] + [0] * 26, pc=PC)
        cpu.step()
        assert cpu.reg(6) == expected, f"0x{instruction:08x}"


def test_a_store_writes_exactly_its_width_and_no_more(cpu):
    """A byte store that wrote a word would pass every test that reads back
    what it just wrote, and corrupt the neighbour."""
    cases = ((e.sb, 0xFFFFFF00), (e.sh, 0xFFFF0000), (e.sw, 0x00000000))
    for store, remaining in cases:
        cpu.write_word(SCRATCH, 0xFFFFFFFF)
        load(cpu, [store("t1", "t0", 0)])
        cpu.set_regs([0] * 5 + [SCRATCH, 0] + [0] * 25, pc=PC)
        cpu.step()
        assert cpu.read_word(SCRATCH) == remaining, store.__name__


def test_a_misaligned_word_access_is_refused_and_names_the_address(cpu):
    """Hazard3 traps misaligned access and so must this, or the two diverge on
    the first packed struct. The address is the diagnostic that matters."""
    load(cpu, [e.lw("t1", "t0", 1)])
    cpu.set_regs([0] * 5 + [SCRATCH] + [0] * 26, pc=PC)
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{SCRATCH + 1:08x}" in str(caught.value)


def test_an_unmapped_address_faults_rather_than_reading_as_zero(cpu):
    """Reading unmapped space as zero is how a poll loop becomes a hang: the
    firmware waits forever for a ready bit that will never be set."""
    outside = RAM + RAM_SIZE
    load(cpu, [e.lw("t1", "t0", 0)])
    cpu.set_regs([0] * 5 + [outside] + [0] * 26, pc=PC)
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{outside:08x}" in str(caught.value)
    assert "unmapped" in str(caught.value)


def test_a_fetch_from_a_region_that_is_not_executable_says_which_it_was(cpu):
    """A stub ROM answers data reads and refuses jumps. "Unmapped" and
    "present but not executable" send the reader to different places."""
    stub = RAM + RAM_SIZE
    cpu.add_region(stub, 0x100, executable=False)
    assert cpu.read_word(stub) == 0
    cpu.set_regs([0] * 32, pc=stub)
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert "present but not executable" in str(caught.value)


def test_fence_is_a_no_op_rather_than_a_hole(cpu):
    """One in-order hart with no cache and no observers: ordering it against
    nothing really is nothing. Every compiled program that touches a lock has
    one, so refusing it would stop real firmware immediately."""
    run(cpu, [e.fence(), e.addi("t0", "x0", 7)])
    assert cpu.reg(5) == 7
    assert cpu.pc == PC + 8


def test_a_refused_step_leaves_the_processor_completely_untouched(cpu):
    """PC included. A core that advanced past an encoding it did not know
    would let a case pass by accident whenever the unwritten instruction
    happened to behave like a NOP -- and on RV32 a great many do."""
    load(cpu, [e.mul("t0", "t1", "t2")])
    cpu.set_regs([0] * 5 + [9, 3, 4] + [0] * 24, pc=PC)
    before = cpu.get_regs().as_list()
    with pytest.raises(abi.AbiError):
        cpu.step()
    assert cpu.pc == PC
    assert cpu.get_regs().as_list() == before


def test_the_core_ships_with_no_memory_and_no_extensions(cpu):
    """A core with no board must not be able to execute anything at all. It
    is the property that makes "the memory map is not in the core" checkable
    rather than merely asserted in a comment."""
    cpu.reset()
    assert cpu.extensions() == 0
    assert not cpu.in_range(RAM, 4)
    assert not cpu.in_range(0x00000000, 4)
    cpu.set_regs([0] * 32, pc=RAM)
    with pytest.raises(abi.MemoryFault):
        cpu.step()


def test_a_region_that_overlaps_one_already_there_is_refused(cpu):
    """Two boards describing the same address differently is a bug in a board
    file. Silently keeping one of them makes it a wrong value much later."""
    with pytest.raises(abi.AbiError):
        cpu.add_region(RAM + 0x100, 0x100)


def test_clearing_memory_restores_the_fill_rather_than_zero(cpu):
    """Flash reads 0xFF when erased. Clearing it to zero would leave the core
    in a state the part it models can never be in."""
    flash = RAM + RAM_SIZE
    cpu.add_region(flash, 0x100, fill=0xFF)
    assert cpu.read_word(flash) == 0xFFFFFFFF
    cpu.write_word(flash, 0)
    cpu.clear_memory()
    assert cpu.read_word(flash) == 0xFFFFFFFF


def test_a_block_that_overruns_its_region_writes_none_of_it(cpu):
    """A half-written image runs for a while and then does something
    inexplicable, which costs far more to diagnose than a refused load."""
    near_the_end = RAM + RAM_SIZE - 4
    with pytest.raises(abi.MemoryFault):
        cpu.write_block(near_the_end, bytes(16))
    assert cpu.read_word(near_the_end) == 0
