# OpenHardware - instruction decode and effective addresses.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for core/i8086/decode.cc, per ticket OH-2.

Decode is where an emulator goes quietly wrong. An arithmetic bug produces a
visibly incorrect number; a decode bug produces the *right* operation on the
*wrong* operand, or the right instruction at the wrong length, which then
desynchronises everything after it. So the addressing table is checked
exhaustively rather than by sampling.

The programs are the real byte sequences from `tests/fixtures/sst8088/`
wherever one exists, so what is exercised is what the hardware was actually
given.
"""

import pytest

from core.i8086 import abi

#: Register values chosen so every addressing mode produces a distinct
#: address. With BX=SI=DI=0 several modes collide and a wrong table entry
#: still computes the right answer.
BASE = {
    "bx": 0x0100, "si": 0x0020, "di": 0x0003,
    "bp": 0x1000, "ss": 0x2000, "ds": 0x3000, "es": 0x4000, "cs": 0x0000,
}


def decode(cpu, code: bytes, **regs):
    """Put a byte sequence at 0000:0000 and decode it.

    `regs` overrides BASE rather than being passed alongside it -- `**BASE,
    **regs` raises on any key in both, which is exactly the case a test
    overriding BX needs.
    """
    cpu.set_regs(**{**BASE, **regs})
    cpu.write_block(0x00000, code)
    return cpu.decode(0x0000, 0x0000)


# --- length, which IP depends on --------------------------------------------


def test_a_bare_nop_is_one_byte(cpu):
    assert decode(cpu, bytes([0x90])).length == 1


def test_a_prefixed_nop_is_two_bytes(cpu):
    """The fixtures contain both, and they advance IP differently."""
    assert decode(cpu, bytes([0x2E, 0x90])).length == 2


def test_a_register_form_modrm_is_two_bytes(cpu):
    assert decode(cpu, bytes([0x00, 0xCF])).length == 2


def test_a_disp8_form_is_three_bytes(cpu):
    assert decode(cpu, bytes([0x00, 0x4B, 0x9C])).length == 3


def test_a_disp16_form_is_four_bytes(cpu):
    # mod=10 rm=000 -> [bx+si+disp16]
    assert decode(cpu, bytes([0x00, 0x80, 0x34, 0x12])).length == 4


def test_a_direct_address_form_is_four_bytes(cpu):
    # mod=00 rm=110 is disp16, not [bp]
    assert decode(cpu, bytes([0x00, 0x06, 0x34, 0x12])).length == 4


def test_every_fixture_program_decodes_to_its_own_length(cpu):
    """Length is exact for all eleven cases, or IP goes wrong everywhere."""
    programs = {
        (0x00, 0x4B, 0x9C): 3,
        (0x00, 0xCF): 2,
        (0x00, 0x69, 0x12): 3,
        (0x00, 0x1D): 2,
        (0x2E, 0x88, 0xF6): 3,
        (0x2E, 0x88, 0x11): 3,
        (0x88, 0x69, 0x0D): 3,
        (0x3E, 0x88, 0x02): 3,
        (0x2E, 0x90): 2,
        (0x90,): 1,
        (0x36, 0x90): 2,
    }
    for code, expected in programs.items():
        got = decode(cpu, bytes(code)).length
        assert got == expected, f"{[f'{b:02X}' for b in code]} decoded as {got}, want {expected}"


# --- the modrm split -----------------------------------------------------------


def test_modrm_splits_into_mod_reg_rm(cpu):
    result = decode(cpu, bytes([0x00, 0xCF]))
    assert (result.mod, result.reg, result.rm) == (3, 1, 7)


def test_mod_three_is_the_register_form_and_has_no_address(cpu):
    assert decode(cpu, bytes([0x00, 0xCF])).has_memory_operand == 0


def test_a_memory_form_reports_an_address(cpu):
    assert decode(cpu, bytes([0x00, 0x1D])).has_memory_operand == 1


# --- displacement --------------------------------------------------------------


def test_disp8_is_sign_extended(cpu):
    """0x9C is -100. Read unsigned it is +156, putting the operand 256 bytes
    from where the hardware put it -- and the instruction still 'works'."""
    assert decode(cpu, bytes([0x00, 0x4B, 0x9C])).displacement == -100


def test_a_positive_disp8_stays_positive(cpu):
    assert decode(cpu, bytes([0x00, 0x69, 0x12])).displacement == 0x12


def test_disp16_is_little_endian(cpu):
    assert decode(cpu, bytes([0x00, 0x80, 0x34, 0x12])).displacement == 0x1234


# --- the addressing table, exhaustively -------------------------------------------


def test_every_mod_zero_addressing_mode_matches_the_intel_table(cpu):
    """rm 000..111 with mod=00, against the table in the 8086 manual.

    rm=110 is the exception: a direct address, not [bp]."""
    expected = {
        0b000: BASE["bx"] + BASE["si"],
        0b001: BASE["bx"] + BASE["di"],
        0b010: BASE["bp"] + BASE["si"],
        0b011: BASE["bp"] + BASE["di"],
        0b100: BASE["si"],
        0b101: BASE["di"],
        0b111: BASE["bx"],
    }
    for rm, want in expected.items():
        modrm = (0b00 << 6) | (0b000 << 3) | rm
        result = decode(cpu, bytes([0x00, modrm]))
        assert result.ea_offset == want, f"rm={rm:03b} gave {result.ea_offset:04X}, want {want:04X}"


def test_mod_zero_rm_six_is_a_direct_address_and_does_not_read_bp(cpu):
    """[bp] with no displacement is unreachable; that encoding is disp16."""
    result = decode(cpu, bytes([0x00, 0x06, 0x34, 0x12]))
    assert result.ea_offset == 0x1234
    assert result.ea_offset != BASE["bp"]


def test_mod_one_rm_six_is_bp_plus_disp8(cpu):
    result = decode(cpu, bytes([0x00, 0x46, 0x10]))
    assert result.ea_offset == BASE["bp"] + 0x10


def test_a_displacement_is_added_to_the_base(cpu):
    result = decode(cpu, bytes([0x00, 0x4B, 0x9C]))  # [bp+di-100]
    assert result.ea_offset == (BASE["bp"] + BASE["di"] - 100) & 0xFFFF


def test_an_offset_wraps_inside_the_segment(cpu):
    """Offset arithmetic is 16-bit; it does not carry into the segment."""
    result = decode(cpu, bytes([0x00, 0x47, 0x7F]), bx=0xFFFF)
    assert result.ea_offset == (0xFFFF + 0x7F) & 0xFFFF


# --- default segments and overrides -----------------------------------------------


def test_a_bp_relative_access_defaults_to_stack(cpu):
    """The 8086 assumes BP means a stack frame."""
    for modrm in (0x42, 0x43, 0x46):  # [bp+si+d8], [bp+di+d8], [bp+d8]
        result = decode(cpu, bytes([0x00, modrm, 0x00]))
        assert result.segment_name == "ss", f"modrm {modrm:02X} used {result.segment_name}"


def test_a_non_bp_access_defaults_to_data(cpu):
    for modrm in (0x00, 0x01, 0x04, 0x05, 0x07):
        result = decode(cpu, bytes([0x00, modrm]))
        assert result.segment_name == "ds", f"modrm {modrm:02X} used {result.segment_name}"


def test_each_prefix_selects_its_segment(cpu):
    for prefix, name in ((0x26, "es"), (0x2E, "cs"), (0x36, "ss"), (0x3E, "ds")):
        result = decode(cpu, bytes([prefix, 0x90]))
        assert result.override_name == name, f"{prefix:02X} gave {result.override_name}"


def test_an_override_beats_the_bp_default(cpu):
    """Case `3E 88 02` from the corpus: [bp+si] would use SS, and 3E forces DS.

    This is the case that proves the override is applied after the default
    rather than only when the default is already DS."""
    result = decode(cpu, bytes([0x3E, 0x88, 0x02]))
    assert result.segment_name == "ds"
    assert result.ea_physical == abi.physical(BASE["ds"], BASE["bp"] + BASE["si"])


def test_an_override_changes_the_physical_address(cpu):
    without = decode(cpu, bytes([0x88, 0x02]))
    with_cs = decode(cpu, bytes([0x2E, 0x88, 0x02]))
    assert without.ea_physical != with_cs.ea_physical
    assert with_cs.ea_physical == abi.physical(BASE["cs"], BASE["bp"] + BASE["si"])


def test_no_prefix_reports_no_override(cpu):
    assert decode(cpu, bytes([0x90])).override_name is None


def test_the_last_override_wins(cpu):
    """Hardware allows several prefixes; the final segment prefix is the one
    that takes effect."""
    assert decode(cpu, bytes([0x2E, 0x36, 0x90])).override_name == "ss"


# --- fetch wrapping ------------------------------------------------------------------


def test_a_fetch_wraps_inside_the_segment(cpu):
    """An instruction starting at offset 0xFFFF continues at offset 0 of the
    same segment, not at the start of the next one."""
    cpu.set_regs(**BASE)
    cpu.write_byte(abi.physical(0x0000, 0xFFFF), 0x00)
    cpu.write_byte(abi.physical(0x0000, 0x0000), 0xCF)
    result = cpu.decode(0x0000, 0xFFFF)
    assert result.opcode == 0x00
    assert (result.mod, result.reg, result.rm) == (3, 1, 7)


# --- the struct contract --------------------------------------------------------------


def test_the_decoded_struct_matches_the_library(library):
    import ctypes

    assert library.i8086_decoded_size() == ctypes.sizeof(abi.Decoded)


def test_an_unknown_opcode_reports_no_modrm(cpu):
    """Opcodes without a modrm byte must not consume one, or length is wrong."""
    assert decode(cpu, bytes([0x90])).has_modrm == 0
