# OpenHardware — the three Zc groups: Zcb, Zcmp, and Zcmt with its JVT.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Where the verdicts come from, group by group
#
# Every encoding below is hand-assembled from the Zc specification v1.0.4
# (ratified 2023), with the field layout stated beside each constant so a
# transposed bit is findable by reading. Two of the three groups are also
# cross-checked against rvcpp -- the vendored Hazard3 simulator implements
# Zcb and Zcmp, and `tools/gen_rv32_tests.py`'s corpus carries its answers
# for the single-writeback Zcb operations. What rvcpp CANNOT check:
#
#   * Zcmp's multi-register transfers. Its trace prints one writeback per
#     instruction, so a cm.pop that reloads thirteen registers shows only
#     the sp write -- measured 2026-08-31, the ra and s0 reloads appear
#     nowhere in the trace (their round-trip is visible only through later
#     instructions). So the stack images here are hand-worked, and the
#     probe that agreed with rvcpp's sp arithmetic (-16/+16 for
#     `cm.push {ra,s0}`) is recorded in OH-146 rather than automated.
#   * Zcmt entirely: Hazard3 has no table jumps and no JVT.
#
# ## Why half of these tests are about refusing
#
# The three groups live in slots base RVC reserves or gives to extensions no
# part here has, and the C5 is the only part with any of them. A C6 that
# executed one, or a C5 that executed a reserved row inside them, would be
# decoding an instruction as some other instruction -- the silent-wrong-answer
# class `core/riscv32/exec.cc` is shaped around refusing.

import pytest

abi = pytest.importorskip("core.riscv32.abi")

import struct

RAM = 0x1000
TOP = 0x3000

#: RV32IMAC plus all three Zc groups: the ESP32-C5's own mask.
C5 = abi.ESP32_C5
#: RV32IMAC: the C6, which must refuse every encoding in this file.
C6 = abi.ESP32_C6


def fresh(mask: int = C5) -> "abi.Cpu":
    cpu = abi.Cpu()
    cpu.set_extensions(mask)
    cpu.add_region(RAM, TOP - RAM, True)
    return cpu


def run(cpu: "abi.Cpu", encoding: int, pc: int = RAM,
        regs: dict[int, int] | None = None) -> "abi.Cpu":
    x = [0] * 32
    for index, value in (regs or {}).items():
        x[index] = value
    cpu.set_regs(x, pc)
    width = "<H" if encoding <= 0xFFFF else "<I"
    cpu.write_block(pc, struct.pack(width, encoding))
    cpu.step()
    return cpu


# --- Zcb: the loads and stores ----------------------------------------------
#
# Quadrant 0, funct3=100. The two offset bits sit SWAPPED -- bit 6 is uimm[0]
# and bit 5 is uimm[1], the same low-bits-near-6 shape C.LW uses -- and the
# tests below prove the swap rather than assuming it.

#: c.lbu a2, 1(a1): 100 000 011(a1) [6]=uimm0=1 [5]=uimm1=0 100(a2) 00
C_LBU_A2_1_A1 = 0x81D0
#: The same fields with bit 5 instead of bit 6: offset TWO, not one.
C_LBU_A2_2_A1 = 0x81B0
#: c.lh a2, 0(a1): 100 001 011 [6]=1(signed) [5]=uimm1=0 100 00
C_LH_A2_0_A1 = 0x85D0
#: c.lhu a2, 0(a1): bit 6 clear.
C_LHU_A2_0_A1 = 0x8590
#: c.sh a2, 2(a1): 100 011 011 [6]=0 [5]=uimm1=1 100 00
C_SH_A2_2_A1 = 0x8DB0


def test_the_zcb_offset_bits_really_are_swapped():
    """bit 6 is uimm[0]. An implementation that read the two bits in the
    natural order would load from a1+2 here and a1+1 in the next test, and
    every byte access in compiled code would be off by a swap."""
    cpu = fresh()
    cpu.write_block(0x1800, bytes([0x11, 0x22, 0x33]))
    run(cpu, C_LBU_A2_1_A1, regs={11: 0x1800})
    assert cpu.reg(12) == 0x22
    cpu = fresh()
    cpu.write_block(0x1800, bytes([0x11, 0x22, 0x33]))
    run(cpu, C_LBU_A2_2_A1, regs={11: 0x1800})
    assert cpu.reg(12) == 0x33


def test_zcb_halfword_loads_tell_signed_from_unsigned_by_bit_six():
    cpu = fresh()
    cpu.write_block(0x1800, struct.pack("<H", 0x8001))
    run(cpu, C_LH_A2_0_A1, regs={11: 0x1800})
    assert cpu.reg(12) == 0xFFFF8001, "c.lh sign-extends"
    cpu = fresh()
    cpu.write_block(0x1800, struct.pack("<H", 0x8001))
    run(cpu, C_LHU_A2_0_A1, regs={11: 0x1800})
    assert cpu.reg(12) == 0x8001, "c.lhu zero-extends"


def test_zcb_stores_land_where_their_loads_read():
    cpu = fresh()
    run(cpu, C_SH_A2_2_A1, regs={11: 0x1800, 12: 0x1234ABCD})
    assert cpu.read_word(0x1800) >> 16 == 0xABCD


# --- Zcb: the register group -------------------------------------------------
#
# Quadrant 1, the bit12=1 half of the register-register slot RV64 uses for
# c.subw/c.addw: funct2 10 is C.MUL, funct2 11 holds the unaries.

C_ZEXT_B_S0 = 0x9C61   #: 100 111 000(s0) 11 000 01
C_NOT_S1 = 0x9CF5      #: 100 111 001(s1) 11 101 01
C_MUL_S0_S1 = 0x9C45   #: 100 111 000(s0) 10 001(s1) 01
C_SEXT_B_S0 = 0x9C65   #: the unary slot 001: needs Zbb, which the C5 lacks


def test_the_zcb_unaries_and_mul_compute():
    cpu = fresh()
    run(cpu, C_ZEXT_B_S0, regs={8: 0x1234FFAB})
    assert cpu.reg(8) == 0xAB
    cpu = fresh()
    run(cpu, C_NOT_S1, regs={9: 0x0F0F0F0F})
    assert cpu.reg(9) == 0xF0F0F0F0
    cpu = fresh()
    run(cpu, C_MUL_S0_S1, regs={8: 7, 9: 6})
    assert cpu.reg(8) == 42


def test_the_zbb_unaries_are_refused_even_on_the_c5():
    """c.sext.b, c.zext.h and c.sext.h exist only on parts with Zbb, and the
    C5 has none. Executing them anyway would decode instructions the C5's
    own datasheet does not grant it. The RP2350 has Zbb and runs them:
    `test_zbb_zbkb.py`'s compressed tests."""
    with pytest.raises(abi.Illegal):
        run(fresh(), C_SEXT_B_S0, regs={8: 0x80})


def test_c_mul_needs_m_as_well_as_zcb():
    """The expansion inherits the 32-bit mul's M gate -- the spec's rule.
    A part with Zcb and no M (none exists here, so the mask is synthetic)
    must refuse."""
    cpu = abi.Cpu()
    cpu.set_extensions(abi.EXT_C | abi.EXT_ZCB)
    cpu.add_region(RAM, TOP - RAM, True)
    with pytest.raises(abi.Illegal):
        run(cpu, C_MUL_S0_S1, regs={8: 7, 9: 6})


# --- Zcmp: push and pop ------------------------------------------------------
#
# Quadrant 2, funct3=101 -- the c.fsdsp slot, dead on every FPU-less part.
# [12:8] rows 11000/11010/11100/11110; rlist in [7:4]; spimm in [3:2].

CM_PUSH_RA_S0 = 0xB852       #: cm.push {ra,s0}, -16
CM_POP_RA_S0 = 0xBA52        #: cm.pop {ra,s0}, 16
CM_POPRET_RA_S0 = 0xBE52     #: cm.popret {ra,s0}, 16
CM_POPRETZ_RA_S0 = 0xBC52    #: cm.popretz {ra,s0}, 16
CM_PUSH_ALL = 0xB8F2         #: cm.push {ra,s0-s11}, -64
CM_PUSH_RA_S0_SP48 = 0xB85E  #: cm.push {ra,s0}, -64 (spimm=3)
CM_MVA01S_S0_S1 = 0xAC66     #: cm.mva01s s0, s1
CM_MVSA01_S2_S3 = 0xAD2E     #: cm.mvsa01 s2, s3


def test_cm_push_stores_the_spec_order_and_moves_sp_last():
    """s0 nearest the old sp, ra at the bottom -- the spec's own expansion:
    `sw s0,-4(sp); sw ra,-8(sp); addi sp,sp,-16`."""
    cpu = fresh()
    run(cpu, CM_PUSH_RA_S0, regs={2: 0x1F00, 1: 0x111, 8: 0x222})
    assert cpu.read_word(0x1EFC) == 0x222
    assert cpu.read_word(0x1EF8) == 0x111
    assert cpu.reg(2) == 0x1EF0
    assert cpu.pc == RAM + 2


def test_cm_pop_mirrors_and_popret_returns_through_the_reloaded_ra():
    cpu = fresh()
    cpu.write_block(0x1EF8, struct.pack("<II", 0x1200, 0x333))
    run(cpu, CM_POP_RA_S0, regs={2: 0x1EF0})
    assert (cpu.reg(1), cpu.reg(8), cpu.reg(2)) == (0x1200, 0x333, 0x1F00)
    assert cpu.pc == RAM + 2, "cm.pop stays"

    cpu = fresh()
    cpu.write_block(0x1EF8, struct.pack("<II", 0x1200, 0x333))
    run(cpu, CM_POPRET_RA_S0, regs={2: 0x1EF0})
    assert cpu.pc == 0x1200, "cm.popret returns through the ra it loaded"

    cpu = fresh()
    cpu.write_block(0x1EF8, struct.pack("<II", 0x1200, 0x333))
    run(cpu, CM_POPRETZ_RA_S0, regs={2: 0x1EF0, 10: 0xDEAD})
    assert cpu.reg(10) == 0 and cpu.pc == 0x1200, "popretz zeroes a0 too"


def test_the_full_rlist_is_thirteen_registers_and_sixty_four_bytes():
    """rlist 15 means {ra, s0-s11}: thirteen registers, because the spec
    skips the twelve-register set entirely. 13*4 rounds up to 64."""
    cpu = fresh()
    run(cpu, CM_PUSH_ALL,
        regs={2: 0x1F00, 1: 1, 8: 2, 9: 3, 18: 4, 19: 5, 20: 6, 21: 7,
              22: 8, 23: 9, 24: 10, 25: 11, 26: 12, 27: 13})
    assert cpu.reg(2) == 0x1F00 - 64
    assert cpu.read_word(0x1F00 - 4) == 13, "s11 nearest the old sp"
    assert cpu.read_word(0x1F00 - 52) == 1, "ra at the bottom of the block"


def test_spimm_grows_the_adjustment_without_moving_the_block():
    cpu = fresh()
    run(cpu, CM_PUSH_RA_S0_SP48, regs={2: 0x1F00, 1: 0x111, 8: 0x222})
    assert cpu.reg(2) == 0x1F00 - 64, "16 base + 3*16 spimm"
    assert cpu.read_word(0x1EFC) == 0x222, "the frame still hugs the old sp"


def test_a_faulting_pop_reloads_nothing():
    """All-or-nothing, the same contract StepResult promises for refusals:
    the loads go to temporaries first, so a stack that runs off the region
    leaves every register -- sp included -- exactly as it was."""
    cpu = fresh()
    with pytest.raises(abi.MemoryFault):
        # sp + 16 - 4 reads at TOP - 4 + 8: past the region's end.
        run(cpu, CM_POP_RA_S0, regs={2: TOP - 8, 1: 0x77, 8: 0x88})
    assert cpu.reg(1) == 0x77 and cpu.reg(8) == 0x88
    assert cpu.reg(2) == TOP - 8, "sp untouched"


def test_a_faulting_push_moves_no_sp():
    cpu = fresh()
    with pytest.raises(abi.MemoryFault):
        run(cpu, CM_PUSH_RA_S0, regs={2: RAM + 4, 1: 1, 8: 2})
    assert cpu.reg(2) == RAM + 4


def test_the_move_pairs_move_and_the_same_register_pair_is_reserved():
    cpu = fresh()
    run(cpu, CM_MVA01S_S0_S1, regs={8: 0x77, 9: 0x88})
    assert (cpu.reg(10), cpu.reg(11)) == (0x77, 0x88)
    cpu = fresh()
    run(cpu, CM_MVSA01_S2_S3, regs={10: 0xAA, 11: 0xBB})
    assert (cpu.reg(18), cpu.reg(19)) == (0xAA, 0xBB)
    with pytest.raises(abi.Illegal):
        run(fresh(), 0xAC22)  # cm.mvsa01 s0, s0


# --- Zcmt: the table jumps and their JVT -------------------------------------

CSRW_JVT_A0 = 0x01751073   #: csrrw x0, jvt, a0
CSRR_A1_JVT = 0x017025F3   #: csrrs a1, jvt, x0
CM_JT_0 = 0xA002           #: 101 000 index=0 10
CM_JALT_32 = 0xA082        #: index 32: the first linking entry


def table(cpu: "abi.Cpu", base: int) -> None:
    cpu.write_block(base, struct.pack("<I", 0x1300))
    cpu.write_block(base + 128, struct.pack("<I", 0x1400))
    run(cpu, CSRW_JVT_A0, regs={10: base})


def test_jvt_round_trips_and_masks_its_mode_bits():
    """WARL: bits 5:0 are the table mode and mode zero is the only one
    defined, so a write with mode bits set reads back without them."""
    cpu = fresh()
    run(cpu, CSRW_JVT_A0, regs={10: 0x1867})
    cpu.set_regs([0] * 32, RAM + 4)
    cpu.write_block(RAM + 4, struct.pack("<I", CSRR_A1_JVT))
    cpu.step()
    assert cpu.reg(11) == 0x1840


def test_cm_jt_jumps_and_cm_jalt_links():
    cpu = fresh()
    table(cpu, 0x1840)
    cpu.set_regs([0] * 32, RAM + 4)
    cpu.write_block(RAM + 4, struct.pack("<H", CM_JT_0))
    cpu.step()
    assert cpu.pc == 0x1300 and cpu.reg(1) == 0, "jt does not link"

    cpu = fresh()
    table(cpu, 0x1840)
    cpu.set_regs([0] * 32, RAM + 6)
    cpu.write_block(RAM + 6, struct.pack("<H", CM_JALT_32))
    cpu.step()
    assert cpu.pc == 0x1400, "index 32 reads slot base+128"
    assert cpu.reg(1) == RAM + 8, "jalt links past its own two bytes"


def test_a_table_outside_memory_faults_at_the_slot():
    cpu = fresh()
    run(cpu, CSRW_JVT_A0, regs={10: 0x8000})
    cpu.set_regs([0] * 32, RAM + 4)
    cpu.write_block(RAM + 4, struct.pack("<H", CM_JT_0))
    with pytest.raises(abi.MemoryFault):
        cpu.step()


# --- gating ------------------------------------------------------------------

EVERY_IMPLEMENTED = (
    C_LBU_A2_1_A1, C_LH_A2_0_A1, C_LHU_A2_0_A1, C_SH_A2_2_A1,
    C_ZEXT_B_S0, C_NOT_S1, C_MUL_S0_S1,
    CM_PUSH_RA_S0, CM_POP_RA_S0, CM_POPRET_RA_S0, CM_POPRETZ_RA_S0,
    CM_MVA01S_S0_S1, CM_MVSA01_S2_S3, CM_JT_0, CM_JALT_32,
)

#: Rows inside the Zc spaces the spec leaves reserved: refused on EVERY
#: configuration, the C5's included.
RESERVED_ROWS = (
    0x9000,   # quadrant 0 funct3=100, [12:10]=100
    0x8DF0,   # c.sh with bit 6 set
    0x9C79,   # the unary slot 110
    0xB952,   # a push row with bit 8 set
    0xB812,   # cm.push rlist=1
    0xAC22,   # cm.mvsa01 s0, s0
)


def test_a_c6_refuses_every_zc_encoding_as_illegal():
    """The other half of having the extensions: a part without them must
    refuse -- Illegal, the architecture's answer, never Unimplemented."""
    for encoding in EVERY_IMPLEMENTED:
        with pytest.raises(abi.Illegal):
            run(fresh(C6), encoding, regs={2: 0x1F00, 11: 0x1800})


def test_the_reserved_rows_refuse_on_the_c5_too():
    for encoding in RESERVED_ROWS:
        with pytest.raises(abi.Illegal):
            run(fresh(), encoding, regs={2: 0x1F00})


def test_the_jvt_csr_stays_unimplemented_without_zcmt():
    """Not Illegal: a C6's Zicsr encodings keep the honest third answer --
    this core has no CSRs and no traps, and that is a hole in the model,
    not a fact about the part."""
    with pytest.raises(abi.Unimplemented):
        run(fresh(C6), CSRW_JVT_A0, regs={10: 0x1840})


def test_set_isa_spells_the_c5_and_refuses_what_it_cannot_represent():
    cpu = abi.Cpu()
    cpu.set_isa("RV32IMAC_ZCB_ZCMP_ZCMT")
    assert cpu.extensions() == C5
    with pytest.raises(abi.AbiError, match="cannot represent"):
        cpu.set_isa("RV32IMAC_ZBB")
