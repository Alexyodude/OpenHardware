# OpenHardware — the instruction formats the corpus does not cover.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# `tools/gen_armv6m_tests.mjs` generates formats 1-4 only: register-only
# arithmetic. Everything a program actually does -- memory, branches, the
# stack, the high registers -- has no corpus behind it.
#
# It does have an oracle. `tools/lockstep_armv6m.mjs` runs a real Pico image
# through rp2040js and this core together and compares all sixteen registers
# and the flags after every instruction; the measured result on
# `.pio/build/pico/firmware.uf2` is **100,000 of 100,000 instructions matching
# exactly**, and standalone the same image runs 225,723 instructions before
# reaching a peripheral this core does not model.
#
# That run is not a test, though, because the firmware is a build artefact and
# is not in this repository. So the rules most likely to be wrong are pinned
# here with hand-assembled encodings, and the lockstep run is the wider net.
#
# Each test names the trap it guards. Every one of them is a rule where the
# obvious implementation is silently wrong rather than obviously broken.

from tests.cortexm0.conftest import PC

FLASH = 0x10000000


def load(cpu, words, *, at=PC, sp=0x20002000, regs=None):
    """Assemble halfwords at `at`, point PC there, and return nothing.

    **Clears memory first**, so any fixture word a test needs must be written
    *after* calling this. Four tests here were written the other way round and
    silently tested against zeros.
    """
    cpu.clear_memory()
    for index, halfword in enumerate(words):
        cpu.write_halfword(at + index * 2, halfword)
    state = [0] * 16
    for index, value in (regs or {}).items():
        state[index] = value
    state[13] = sp
    state[15] = at
    cpu.set_regs(state, apsr=0)


def run(cpu, count):
    for _ in range(count):
        cpu.step()
    return cpu.get_regs()


# --- the stack -------------------------------------------------------------


def test_push_stores_the_lowest_register_at_the_lowest_address(cpu):
    """The trap: pushing in register order while SP decrements gives a stack
    that pops back reversed. It only shows with more than one register, so a
    single-register test passes either way."""
    load(cpu, [0xB407], regs={0: 0xAAAA0000, 1: 0xBBBB1111, 2: 0xCCCC2222})
    regs = run(cpu, 1)  # PUSH {r0, r1, r2}
    assert regs.r[13] == 0x20002000 - 12
    assert cpu.read_word(0x20002000 - 12) == 0xAAAA0000
    assert cpu.read_word(0x20002000 - 8) == 0xBBBB1111
    assert cpu.read_word(0x20002000 - 4) == 0xCCCC2222


def test_push_then_pop_round_trips_three_registers(cpu):
    load(cpu, [0xB407, 0xBC07], regs={0: 0x11111111, 1: 0x22222222, 2: 0x33333333})
    run(cpu, 1)
    cpu.set_regs([0] * 13 + [cpu.get_regs().r[13], 0, cpu.get_regs().r[15]], apsr=0)
    regs = run(cpu, 1)
    assert (regs.r[0], regs.r[1], regs.r[2]) == (0x11111111, 0x22222222, 0x33333333)
    assert regs.r[13] == 0x20002000


def test_pop_pc_branches_and_clears_the_thumb_bit(cpu):
    """`POP {pc}` is how nearly every function returns. The stored address has
    bit 0 set to mean Thumb; leaving it set makes the next fetch odd."""
    load(cpu, [0xBD00])
    cpu.write_word(0x20002000, 0x10000205)   # after load(): it clears memory
    regs = run(cpu, 1)
    assert regs.r[15] == 0x10000204
    assert regs.r[13] == 0x20002004


# --- branches --------------------------------------------------------------


def test_a_taken_branch_is_not_also_advanced_by_two(cpu):
    """The trap this core actually had to fix: formats 1-4 could never write
    PC, so `step` advanced unconditionally. Adding branches without making the
    advance conditional turns every taken branch into branch-plus-two."""
    load(cpu, [0xE001, 0x2001, 0x2002, 0x2003])   # B +2, then MOVS r0,#1/2/3
    regs = run(cpu, 1)
    assert regs.r[15] == PC + 6                    # skipped two halfwords


def test_a_branch_backwards_uses_a_signed_offset(cpu):
    load(cpu, [0x2001, 0xE7FE])                    # MOVS r0,#1 ; B .
    run(cpu, 1)
    regs = run(cpu, 1)
    assert regs.r[15] == PC + 2                    # branched to itself


def test_a_conditional_branch_not_taken_falls_through(cpu):
    load(cpu, [0x2000, 0xD100, 0x2007])            # MOVS r0,#0 ; BNE +0 ; MOVS r0,#7
    run(cpu, 1)                                    # Z set by MOVS r0,#0
    regs = run(cpu, 2)
    assert regs.r[0] == 7


def test_bl_is_one_instruction_of_four_bytes_not_two_of_two(cpu):
    """The second halfword of a BL is not a valid instruction. A core that
    stepped over the first would execute garbage next."""
    # BL +0x10 from PC: F000 F808
    load(cpu, [0xF000, 0xF808])
    regs = run(cpu, 1)
    assert regs.r[14] == (PC + 4) | 1               # LR is the return address
    assert regs.r[15] == PC + 4 + 0x10


def test_bx_lr_returns_and_drops_the_thumb_bit(cpu):
    load(cpu, [0x4770], regs={14: 0x10000301})      # BX lr
    regs = run(cpu, 1)
    assert regs.r[15] == 0x10000300


# --- PC-relative addressing ------------------------------------------------


def test_pc_reads_as_the_instruction_address_plus_four(cpu):
    """Not plus two. The architecture defines PC relative to a three-stage
    pipeline this core does not otherwise model."""
    load(cpu, [0x4478])                             # ADD r0, pc
    regs = run(cpu, 1)
    assert regs.r[0] == PC + 4


def test_a_pc_relative_load_aligns_the_base_down_to_a_word(cpu):
    """`LDR Rd, [PC, #imm]` clears bit 1 of the base first. At an odd halfword
    -- half of all instructions -- omitting that reads the wrong word."""
    at = PC + 2                                     # deliberately not word-aligned
    load(cpu, [0x0000, 0x4801], at=PC)              # pad, then LDR r0, [pc, #4]
    cpu.write_word(PC + 8, 0xFEEDFACE)              # after load(): it clears memory
    cpu.set_regs([0] * 13 + [0x20002000, 0, at], apsr=0)
    regs = run(cpu, 1)
    # base = align_down(at + 4) = align_down(PC + 6) = PC + 4; +4 -> PC + 8
    assert regs.r[0] == 0xFEEDFACE


# --- loads and stores ------------------------------------------------------


def test_a_word_immediate_offset_is_scaled_by_four(cpu):
    """The same five bits reach 124 bytes for a word and 31 for a byte.
    Forgetting to scale is a silently four-times-wrong address."""
    load(cpu, [0x6858], regs={3: 0x20003000})       # LDR r0, [r3, #4]
    cpu.write_word(0x20003004, 0x0BADC0DE)          # after load(): it clears memory
    regs = run(cpu, 1)
    assert regs.r[0] == 0x0BADC0DE


def test_a_byte_immediate_offset_is_not_scaled(cpu):
    load(cpu, [0x7858], regs={3: 0x20003000})       # LDRB r0, [r3, #1]
    cpu.write_word(0x20003000, 0x44332211)          # after load(): it clears memory
    regs = run(cpu, 1)
    assert regs.r[0] == 0x22


def test_a_signed_byte_load_sign_extends_it(cpu):
    load(cpu, [0x5658], regs={3: 0x20003000})       # LDRSB r0, [r3, r1]
    cpu.write_word(0x20003000, 0x000000FF)          # after load(): it clears memory
    regs = run(cpu, 1)
    assert regs.r[0] == 0xFFFFFFFF


def test_an_unsigned_byte_load_leaves_the_top_bits_clear(cpu):
    load(cpu, [0x5C58], regs={3: 0x20003000})       # LDRB r0, [r3, r1]
    cpu.write_word(0x20003000, 0x000000FF)
    regs = run(cpu, 1)
    assert regs.r[0] == 0xFF


def test_stmia_writes_back_the_advanced_base(cpu):
    load(cpu, [0xC303], regs={0: 0xAAAA, 1: 0xBBBB, 3: 0x20003000})  # STMIA r3!,{r0,r1}
    regs = run(cpu, 1)
    assert cpu.read_word(0x20003000) == 0xAAAA
    assert cpu.read_word(0x20003004) == 0xBBBB
    assert regs.r[3] == 0x20003008


def test_ldmia_does_not_write_back_when_the_base_is_in_the_list(cpu):
    """The loaded value wins. Writing back would overwrite what was just
    loaded, which is the opposite of the intent."""
    load(cpu, [0xCB01], regs={3: 0x20003000})       # LDMIA r3!, {r0} -- r3 not in list
    cpu.write_word(0x20003000, 0xDEADBEEF)
    regs = run(cpu, 1)
    assert regs.r[0] == 0xDEADBEEF and regs.r[3] == 0x20003004

    load(cpu, [0xCB08], regs={3: 0x20003000})       # LDMIA r3!, {r3} -- base in list
    cpu.write_word(0x20003000, 0x12345678)
    regs = run(cpu, 1)
    assert regs.r[3] == 0x12345678                  # the loaded value, not 0x20003004


# --- memory-mapped IO ------------------------------------------------------


def test_a_mapped_register_reads_what_was_written_to_it(cpu):
    cpu.clear_memory()
    cpu.map_register(0xD0000000, 0x1234)
    assert cpu.read_word(0xD0000000) == 0x1234
    cpu.write_word(0xD0000000, 0x5678)
    assert cpu.read_word(0xD0000000) == 0x5678


def test_an_unmapped_peripheral_address_still_faults(cpu):
    """The rule the whole mechanism exists for. A peripheral window reading as
    zero turns every 'wait until ready' poll into a silent infinite loop --
    firmware that hangs instead of firmware that says what is missing."""
    import pytest

    from core.cortexm0.abi import MemoryFault

    cpu.clear_memory()
    cpu.map_register(0xD0000000, 0)
    with pytest.raises(MemoryFault):
        cpu.read_word(0xD0000004)


def test_mapping_one_register_does_not_map_its_neighbours(cpu):
    cpu.clear_memory()
    cpu.map_register(0x4000C000, 0)
    assert cpu.is_mapped(0x4000C000)
    assert not cpu.is_mapped(0x4000C004)
    # And the atomic-SET alias the RP2040 puts at +0x2000 is a different
    # address, so it is separately unmapped. That alias is the next thing real
    # firmware asks for: it stops at 0x4000E000 after 225,723 instructions.
    assert not cpu.is_mapped(0x4000E000)
