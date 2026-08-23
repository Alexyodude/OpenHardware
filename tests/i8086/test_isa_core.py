# OpenHardware - execution and the flags it produces.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for core/i8086/alu.cc and exec_core.cc, per ticket OH-3.

Flags are tested by executing real ADD instructions rather than by calling
Add8 directly. A unit test of the ALU proves the arithmetic; running the
instruction proves the arithmetic *and* that execution routes operands to it
correctly, which is where the bug usually is.

The boundary values are chosen so CF and OF disagree. A core that conflates
them -- a common mistake, since both mean "it did not fit" -- passes every
test using small positive numbers and fails on exactly these.
"""

import pytest

from core.i8086 import abi

CF, PF, AF, ZF, SF, OF = 0x0001, 0x0004, 0x0010, 0x0040, 0x0080, 0x0800

#: Byte register encodings, in the order the modrm reg field uses them.
BYTE_REGISTERS = ("al", "cl", "dl", "bl", "ah", "ch", "dh", "bh")


def run_add(cpu, left: int, right: int) -> tuple[int, int]:
    """ADD BL, CL with BL=left and CL=right. Returns (result, flags)."""
    cpu.set_regs(cs=0x0000, ip=0x0000, bx=left & 0xFF, cx=right & 0xFF, flags=0)
    cpu.write_block(0x00000, bytes([0x00, 0xCB]))  # mod=3 reg=001(CL) rm=011(BL)
    cpu.step()
    return cpu.regs.bx & 0xFF, cpu.regs.flags


# --- NOP ------------------------------------------------------------------------


def test_nop_advances_ip_by_one(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0100)
    cpu.write_block(0x00100, bytes([0x90]))
    cpu.step()
    assert cpu.regs.ip == 0x0101


def test_a_prefixed_nop_advances_by_two(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0100)
    cpu.write_block(0x00100, bytes([0x2E, 0x90]))
    cpu.step()
    assert cpu.regs.ip == 0x0102


def test_nop_changes_nothing_else(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0100, ax=0x1234, bx=0x5678, flags=0x0801)
    cpu.write_block(0x00100, bytes([0x90]))
    before = cpu.regs.as_dict()
    cpu.step()
    after = cpu.regs.as_dict()
    del before["ip"], after["ip"]
    assert before == after


# --- byte register encoding --------------------------------------------------------


def test_every_byte_register_encoding_reads_the_right_half(cpu):
    """reg 0..7 is AL,CL,DL,BL,AH,CH,DH,BH. Swapping a low and high half is a
    bug that still 'works' for anything using only one of them."""
    # MOV AL, <reg>  -- 88 /r with rm=000 (AL), reg varying
    values = {"ax": 0x11AA, "cx": 0x22BB, "dx": 0x33CC, "bx": 0x44DD}
    expected = {
        0: 0xAA, 1: 0xBB, 2: 0xCC, 3: 0xDD,   # AL CL DL BL -- low halves
        4: 0x11, 5: 0x22, 6: 0x33, 7: 0x44,   # AH CH DH BH -- high halves
    }
    for reg, want in expected.items():
        cpu.set_regs(cs=0x0000, ip=0x0000, **values)
        modrm = 0xC0 | (reg << 3) | 0x00  # mod=3, rm=000 -> AL
        cpu.write_block(0x00000, bytes([0x88, modrm]))
        cpu.step()
        got = cpu.regs.ax & 0xFF
        assert got == want, f"reg={reg} ({BYTE_REGISTERS[reg]}) gave {got:02X}, want {want:02X}"


def test_writing_a_low_half_leaves_the_high_half(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ax=0xAA00, cx=0x0055)
    cpu.write_block(0x00000, bytes([0x88, 0xC8]))  # MOV AL, CL
    cpu.step()
    assert cpu.regs.ax == 0xAA55


def test_writing_a_high_half_leaves_the_low_half(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ax=0x00AA, cx=0x0055)
    cpu.write_block(0x00000, bytes([0x88, 0xCC]))  # MOV AH, CL
    cpu.step()
    assert cpu.regs.ax == 0x55AA


# --- MOV to memory -------------------------------------------------------------------


def test_mov_writes_to_the_computed_address(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x2000, bx=0x0010, di=0x0005, dx=0x0042)
    cpu.write_block(0x00000, bytes([0x88, 0x11]))  # MOV [bx+di], DL
    cpu.step()
    assert cpu.read_byte(abi.physical(0x2000, 0x0015)) == 0x42


def test_mov_honours_a_segment_override(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x2000, es=0x5000, bx=0x0010, di=0x0005, dx=0x0042)
    cpu.write_block(0x00000, bytes([0x26, 0x88, 0x11]))  # ES: MOV [bx+di], DL
    cpu.step()
    assert cpu.read_byte(abi.physical(0x5000, 0x0015)) == 0x42
    assert cpu.read_byte(abi.physical(0x2000, 0x0015)) == 0x00


# --- ADD, and the flags -----------------------------------------------------------------


def test_a_simple_add_produces_the_sum(cpu):
    result, _ = run_add(cpu, 0x12, 0x34)
    assert result == 0x46


def test_carry_is_the_unsigned_carry_out_of_bit_seven(cpu):
    _, flags = run_add(cpu, 0xFF, 0x01)
    assert flags & CF


def test_no_carry_when_the_sum_fits(cpu):
    _, flags = run_add(cpu, 0x7F, 0x01)
    assert not flags & CF


def test_overflow_is_signed_and_is_not_carry(cpu):
    """0x7F + 0x01 is 128, which overflows a signed byte but does not carry.
    A core conflating CF and OF gets exactly this case wrong."""
    _, flags = run_add(cpu, 0x7F, 0x01)
    assert flags & OF
    assert not flags & CF


def test_carry_without_overflow(cpu):
    """0xFF + 0x01 carries unsigned, and -1 + 1 = 0 does not overflow signed.
    The mirror image of the case above."""
    _, flags = run_add(cpu, 0xFF, 0x01)
    assert flags & CF
    assert not flags & OF


def test_auxiliary_carry_is_the_carry_out_of_bit_three(cpu):
    _, flags = run_add(cpu, 0x0F, 0x01)
    assert flags & AF


def test_no_auxiliary_carry_within_a_nibble(cpu):
    _, flags = run_add(cpu, 0x01, 0x01)
    assert not flags & AF


def test_zero_sets_the_zero_flag(cpu):
    result, flags = run_add(cpu, 0xFF, 0x01)
    assert result == 0 and flags & ZF


def test_a_negative_result_sets_sign(cpu):
    _, flags = run_add(cpu, 0x7F, 0x02)
    assert flags & SF


def test_parity_is_set_on_an_even_number_of_bits(cpu):
    """PF reads backwards to most expectations: it is set on EVEN parity."""
    result, flags = run_add(cpu, 0x03, 0x00)  # 0b11, two bits set
    assert result == 0x03 and flags & PF


def test_parity_is_clear_on_an_odd_number_of_bits(cpu):
    result, flags = run_add(cpu, 0x07, 0x00)  # 0b111, three bits set
    assert result == 0x07 and not flags & PF


def test_parity_considers_only_the_low_byte(cpu):
    """Even for 16-bit operations PF is the parity of the low 8 bits."""
    result, flags = run_add(cpu, 0x01, 0x00)
    assert result == 0x01 and not flags & PF


def test_add_writes_through_to_memory(cpu):
    cpu.set_regs(cs=0x0000, ip=0x0000, ds=0x2000, bx=0x0010, di=0x0005, cx=0x0003)
    cpu.write_byte(abi.physical(0x2000, 0x0015), 0x04)
    cpu.write_block(0x00000, bytes([0x00, 0x09]))  # ADD [bx+di], CL
    cpu.step()
    assert cpu.read_byte(abi.physical(0x2000, 0x0015)) == 0x07


def test_the_always_set_flag_bits_survive_an_add(cpu):
    _, flags = run_add(cpu, 0x01, 0x01)
    assert flags & 0xF002 == 0xF002


# --- unimplemented opcodes must be loud ------------------------------------------------


def test_an_unimplemented_opcode_raises(cpu):
    """Silently doing nothing would make an unwritten opcode behave like a
    NOP, and a conformance case whose expected state happened to match would
    then pass."""
    cpu.set_regs(cs=0x0000, ip=0x0000)
    cpu.write_block(0x00000, bytes([0xF4]))  # HLT, not implemented
    with pytest.raises(abi.Unimplemented, match="F4"):
        cpu.step()


def test_an_unimplemented_opcode_leaves_ip_alone(cpu):
    """So the caller can report which instruction stopped it."""
    cpu.set_regs(cs=0x0000, ip=0x0123)
    cpu.write_block(0x00123, bytes([0xF4]))
    with pytest.raises(abi.Unimplemented):
        cpu.step()
    assert cpu.regs.ip == 0x0123


# --- IP wrapping -------------------------------------------------------------------------


def test_ip_wraps_inside_the_segment(cpu):
    """An instruction ending at 0xFFFF continues at offset 0, not in the next
    segment."""
    cpu.set_regs(cs=0x1000, ip=0xFFFF)
    cpu.write_byte(abi.physical(0x1000, 0xFFFF), 0x90)
    cpu.step()
    assert cpu.regs.ip == 0x0000
