# OpenHardware - the C ABI and the processor state behind it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for core/i8086/abi.h, abi.cc and abi.py, per tickets OH-1 and OH-2.

The contract between three files that drift silently: abi.h declares it,
abi.cc implements it, abi.py mirrors it. A field added on one side and not the
other does not fail to compile and does not fail to load -- it reads the wrong
bytes. So the sizes are checked, the names are checked, and the opcode table
is swept across all 256 values.

The register values here are taken from an actual SST8088 case rather than
invented, so the shapes exercised are the shapes the corpus produces.
"""

import ctypes

import pytest

from core.i8086 import abi

#: The initial state of the first case in tests/fixtures/sst8088/90.json.
#: Real values from a real capture, so nothing here is a shape the corpus
#: cannot produce.
#: The eight bytes that are prefixes rather than opcodes.
#:
#: 26/2E/36/3E are the segment overrides and F0-F3 are LOCK, its undocumented
#: second encoding, REPNE and REP. Nothing else in the 256 is unclaimed.
#:
#: The four segment overrides sit exactly where the last four ALU groups would
#: put `PUSH sreg`, which is why the pattern claiming the stack ops has to
#: stop at 0x20: below it, form 6 is PUSH ES/CS/SS/DS; above it, form 6 is a
#: prefix and form 7 is a BCD adjust.
PREFIX_BYTES = {0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF1, 0xF2, 0xF3}

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


def test_the_struct_names_exactly_the_corpus_registers():
    """Same fourteen names -- and the order is deliberately NOT asserted.

    This used to be `set(...) == set(...)` under a name claiming the field
    ORDER matched the corpus, which a set comparison cannot check. It does not
    match, three docstrings said it did, and nothing caught it because nothing
    depends on it: every crossing is by name.

    So the claim is gone and this asserts what is actually required -- the same
    names, so `set_regs(**case.initial_regs)` cannot raise on an unknown key.
    """
    assert set(abi.REGISTER_NAMES) == set(ORACLE_CASE)
    assert len(abi.REGISTER_NAMES) == len(set(abi.REGISTER_NAMES)), "no duplicates"


def test_the_orders_differ_which_is_fine_and_deliberate():
    """Pins the fact the old comment got wrong, so nobody re-asserts it."""
    from tools import sst8088

    assert abi.REGISTER_NAMES != sst8088.REGISTERS
    assert set(abi.REGISTER_NAMES) == set(sst8088.REGISTERS)


def test_a_whole_corpus_case_survives_the_name_crossing(cpu):
    """The property the order claim was standing in for."""
    cpu.set_regs(**ORACLE_CASE)
    assert cpu.regs.as_dict() == ORACLE_CASE


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


# --- word access at a segment boundary ------------------------------------------


def test_a_physical_word_read_wraps_at_the_megabyte(cpu):
    """The raw accessor: documented as physical, and inspection-only."""
    cpu.write_byte(0xFFFFF, 0xEF)
    cpu.write_byte(0x00000, 0xBE)
    assert cpu.read_word(0xFFFFF) == 0xBEEF


def test_the_raw_word_accessor_is_not_segment_aware(cpu):
    """Pins the boundary that made this worth splitting in two.

    A word at seg:FFFF takes its high byte from seg:0000 on real hardware --
    the same segment. The physical accessor reads physical+1, which is the
    next paragraph. That is correct for a debugger and wrong for an operand,
    and PUSH/POP at SS:SP hits it the moment SP nears 0xFFFF.
    """
    cpu.write_byte(abi.physical(0x1000, 0xFFFF), 0xEF)
    cpu.write_byte(abi.physical(0x1000, 0x0000), 0xBE)   # what hardware wants
    cpu.write_byte(abi.physical(0x1000, 0xFFFF) + 1, 0x77)  # what physical+1 gives
    assert cpu.read_word(abi.physical(0x1000, 0xFFFF)) == 0x77EF


# --- one opcode table, not two ----------------------------------------------------


def test_the_opcode_table_is_the_only_authority(library):
    """Sweeps all 256, and the map is now complete.

    This used to enumerate families, because for four tickets only some of
    them existed and a set of families was the only readable way to say which.
    That is over: **every opcode the 8086 defines is implemented**, and the
    only four bytes reporting otherwise are prefixes, which are not opcodes at
    all -- see the test below.

    Asserted as "everything except the prefixes" rather than as a list,
    because the interesting property now is completeness, and a list of 252
    numbers states it far worse than one sentence does.
    """
    implemented = {op for op in range(256) if abi.opcode_info(op)[0]}
    assert implemented == set(range(256)) - PREFIX_BYTES


def test_the_prefix_bytes_are_not_opcodes(library):
    """The eight prefix bytes report `implemented = False`, and that is right.

    Four segment overrides, LOCK, its undocumented second encoding, REPNE and
    REP. The decoder consumes them in its prefix loop before it reaches an
    opcode,
    so `Lookup` is never asked about them in anger -- and answering "yes" would
    be worse, because it would claim they can be executed on their own.

    The distinction matters to a disassembler, which must show `F3 A4` as one
    instruction and not two.
    """
    for byte in sorted(PREFIX_BYTES):
        assert not abi.opcode_info(byte)[0], f"{byte:02X} is a prefix, not an opcode"


def test_a_prefixed_instruction_is_one_instruction(library):
    """The consequence of the above, checked rather than asserted in prose."""
    with abi.Cpu() as cpu:
        cpu.set_regs(cs=0x0000, ip=0x0000)
        cpu.write_block(0x00000, bytes([0xF3, 0xA4]))     # rep movsb
        decoded = cpu.decode()
        assert decoded.opcode == 0xA4
        assert decoded.length == 2


def test_the_segment_stack_ops_are_implemented_including_the_one_with_no_oracle(library):
    """PUSH/POP ES, CS, SS and DS.

    0x0F is POP CS. The part executes it, and **SST8088 has no file for it** --
    it is the only instruction in the core with no hardware oracle behind it,
    written by symmetry with the other three. That is recorded here rather
    than left for someone to discover from a missing download.
    """
    for opcode in (0x06, 0x07, 0x0E, 0x0F, 0x16, 0x17, 0x1E, 0x1F):
        assert abi.opcode_info(opcode)[0], f"{opcode:02X} is not implemented"


def test_the_immediate_alu_forms_carry_no_modrm(library):
    """Forms 4 and 5 of the ALU group take an immediate and no modrm.

    This test used to assert the opposite -- that they were unimplemented and
    refused -- which was true until they landed. What it pins now is the fact
    that made them worth refusing in the first place: they decode at a
    different length from forms 0-3, so a table claiming a modrm here would
    put IP one or two bytes out on every one of them.

    Forms 6 and 7 are deliberately not swept. They are not ALU operations at
    all: for the first four groups they are the segment-register stack ops
    (06/07/0E/0F/16/17/1E/1F) and for the last four they are DAA, DAS, AAA
    and AAS. The group is regular in its low four forms and not in its high
    four.
    """
    for base in range(0x00, 0x40, 0x08):
        for form in (0x04, 0x05):
            opcode = base + form
            implemented, has_modrm, wide = (*abi.opcode_info(opcode),
                                            abi.opcode_is_wide(opcode))
            assert implemented, f"{opcode:02X} is not implemented"
            assert not has_modrm, f"{opcode:02X} must not claim a modrm byte"
            assert wide == (form == 0x05), f"{opcode:02X} has the wrong width"


def test_the_alu_group_width_follows_opcode_bit_zero(library):
    for op in range(0x00, 0x40):
        if (op & 0x07) > 0x03:
            continue
        assert abi.opcode_is_wide(op) == bool(op & 1), f"{op:02X} width wrong"


def test_push_and_pop_are_always_wide(library):
    """This part has no byte form of either."""
    for op in range(0x50, 0x60):
        assert abi.opcode_is_wide(op), f"{op:02X} should be 16-bit"


def test_halt_is_implemented_and_reports_itself_as_stopped(library):
    """HLT is the one instruction with no corpus file -- it cannot be
    single-stepped on a capture rig, because the rig's next step never comes.

    So it is checked here by hand, and it must be distinguishable from an
    opcode nobody has written: `step` returns False rather than raising.
    """
    assert abi.opcode_info(0xF4)[0], "HLT is implemented"
    with abi.Cpu() as cpu:
        cpu.set_regs(cs=0x0000, ip=0x0000)
        cpu.write_block(0x00000, bytes([0x90, 0xF4]))
        assert cpu.step() is True, "NOP keeps running"
        assert cpu.step() is False, "HLT stops"
