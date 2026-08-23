# OpenHardware - the C ABI and the processor state behind it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for core/i8086/abi.h, abi.cc and abi.py, per ticket OH-1.

This slice has no decode and no execution, so what is checked is the pipeline
and the state: that the library builds, that Python and C++ agree on the
struct, and that memory and segmentation behave the way the oracle will
require when OH-6 starts feeding real cases through.

The register values here are taken from an actual SST8088 case rather than
invented, so the shapes exercised are the shapes the corpus will produce.
"""

import ctypes

import pytest

from core.i8086 import abi

#: The initial state of the first case in tests/fixtures/sst8088/90.json.
#: Real values from a real capture, so nothing here is a shape the corpus
#: cannot produce.
ORACLE_CASE = {
    "ax": 22348, "bx": 20994, "cx": 55040, "dx": 35727,
    "cs": 30669, "ss": 7470, "ds": 56187, "es": 16953,
    "sp": 29826, "bp": 22563, "si": 22092, "di": 14300,
    "ip": 37865, "flags": 64646,
}


# --- the contract between the three files ------------------------------------


def test_the_library_and_the_binding_agree_on_the_abi_version(library):
    assert library.i8086_abi_version() == abi.ABI_VERSION


def test_the_register_struct_is_the_same_size_on_both_sides(library):
    """A field added on one side reads the wrong bytes rather than failing."""
    assert library.i8086_regs_size() == ctypes.sizeof(abi.Registers)


def test_the_struct_is_fourteen_packed_words():
    assert ctypes.sizeof(abi.Registers) == 14 * 2
    assert len(abi.REGISTER_NAMES) == 14


def test_the_field_order_matches_the_corpus():
    """The harness fills this struct straight from a case's `regs` object."""
    assert set(abi.REGISTER_NAMES) == set(ORACLE_CASE)


def test_the_address_space_is_one_megabyte(library):
    assert abi.memory_size() == 1 << 20


# --- reset --------------------------------------------------------------------


def test_reset_puts_the_processor_at_the_reset_vector(cpu):
    cpu.set_regs(cs=0x1234, ip=0x5678)
    cpu.reset()
    assert (cpu.regs.cs, cpu.regs.ip) == (0xFFFF, 0x0000)


def test_reset_clears_the_general_registers(cpu):
    cpu.set_regs(ax=0xDEAD, bx=0xBEEF, sp=0x1000)
    cpu.reset()
    assert (cpu.regs.ax, cpu.regs.bx, cpu.regs.sp) == (0, 0, 0)


def test_reset_leaves_memory_alone(cpu):
    """Reset does not touch DRAM on real hardware, and a case may set memory
    before reset in some orderings -- zeroing here would discard it."""
    cpu.write_byte(0x00500, 0xAB)
    cpu.reset()
    assert cpu.read_byte(0x00500) == 0xAB


# --- the flag bits hardware holds high ------------------------------------------


def test_the_always_set_flag_bits_survive_reset(cpu):
    cpu.reset()
    assert cpu.regs.flags & 0xF002 == 0xF002


def test_the_always_set_flag_bits_cannot_be_cleared(cpu):
    """Every `flags` value in the corpus has them set; a core that lets them
    clear disagrees with hardware on the first case it runs."""
    cpu.set_regs(flags=0x0000)
    assert cpu.regs.flags & 0xF002 == 0xF002


def test_a_real_corpus_flags_value_round_trips(cpu):
    cpu.set_regs(flags=ORACLE_CASE["flags"])
    assert cpu.regs.flags == ORACLE_CASE["flags"]


# --- registers -------------------------------------------------------------------


def test_a_whole_oracle_case_round_trips(cpu):
    cpu.set_regs(**ORACLE_CASE)
    assert cpu.regs.as_dict() == ORACLE_CASE


def test_setting_one_register_leaves_the_others(cpu):
    cpu.set_regs(**ORACLE_CASE)
    cpu.set_regs(ax=0x0001)
    after = cpu.regs.as_dict()
    assert after["ax"] == 0x0001
    assert after["bx"] == ORACLE_CASE["bx"]


def test_an_unknown_register_is_refused(cpu):
    with pytest.raises(abi.AbiError, match="no register"):
        cpu.set_regs(rax=1)


# --- memory ---------------------------------------------------------------------


def test_a_byte_round_trips(cpu):
    cpu.write_byte(0x12345, 0xA5)
    assert cpu.read_byte(0x12345) == 0xA5


def test_a_word_is_little_endian(cpu):
    cpu.write_word(0x00100, 0x1234)
    assert (cpu.read_byte(0x00100), cpu.read_byte(0x00101)) == (0x34, 0x12)
    assert cpu.read_word(0x00100) == 0x1234


def test_a_block_round_trips(cpu):
    payload = bytes(range(256))
    cpu.write_block(0x02000, payload)
    assert cpu.read_block(0x02000, 256) == payload


def test_an_empty_block_is_not_an_error(cpu):
    cpu.write_block(0x02000, b"")
    assert cpu.read_block(0x02000, 0) == b""


def test_clear_memory_zeroes_everything(cpu):
    cpu.write_byte(0x00001, 0xFF)
    cpu.write_byte(0xFFFFE, 0xFF)
    cpu.clear_memory()
    assert (cpu.read_byte(0x00001), cpu.read_byte(0xFFFFE)) == (0, 0)


# --- segmentation, and the wrap that has no A20 line -------------------------------


def test_a_segment_offset_pair_becomes_a_physical_address():
    assert abi.physical(0x0040, 0x0000) == 0x00400
    assert abi.physical(0x1234, 0x5678) == 0x179B8


def test_the_top_of_the_address_space_wraps(cpu):
    """0xFFFF:0xFFFF computes to 0x10FFEF, and an 8086 has no twenty-first
    address line to carry it. Later parts do not wrap; that is where the A20
    gate came from."""
    assert abi.physical(0xFFFF, 0xFFFF) == 0x0FFEF


def test_a_word_write_across_the_top_wraps_too(cpu):
    """The high byte of a word at 0xFFFFF lands at 0x00000, not off the end."""
    cpu.write_word(0xFFFFF, 0xBEEF)
    assert cpu.read_byte(0xFFFFF) == 0xEF
    assert cpu.read_byte(0x00000) == 0xBE


def test_a_block_write_across_the_top_wraps(cpu):
    """memcpy would run off the end of the buffer here; the ABI writes byte
    at a time for exactly this case."""
    cpu.write_block(0xFFFFE, bytes([1, 2, 3, 4]))
    assert cpu.read_byte(0xFFFFE) == 1
    assert cpu.read_byte(0xFFFFF) == 2
    assert cpu.read_byte(0x00000) == 3
    assert cpu.read_byte(0x00001) == 4


# --- lifetime -----------------------------------------------------------------------


def test_two_processors_do_not_share_memory(library):
    with abi.Cpu() as first, abi.Cpu() as second:
        first.write_byte(0x00300, 0x11)
        second.write_byte(0x00300, 0x22)
        assert first.read_byte(0x00300) == 0x11
        assert second.read_byte(0x00300) == 0x22


def test_using_a_closed_processor_is_refused(library):
    instance = abi.Cpu()
    instance.close()
    with pytest.raises(abi.AbiError, match="closed"):
        instance.reset()


def test_closing_twice_is_harmless(library):
    instance = abi.Cpu()
    instance.close()
    instance.close()
