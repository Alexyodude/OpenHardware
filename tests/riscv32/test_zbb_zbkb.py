# OpenHardware — Zbb and Zbkb, the RP2350's last two groups (OH-208).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Where each instruction is defined
#
# The ratified RISC-V unprivileged ISA, release 20240411, chapter 28 ("B"
# Extension for Bit Manipulation, Version 1.0.0). Its `Zbb` and `Zbkb`
# sections say which group an instruction is in, and its alphabetical
# instruction pages give each one's RV32 encoding and Sail. Zbkb is also
# chapter 32's (Cryptography Extensions: Scalar & Entropy Source
# Instructions, Version 1.0.1), section `Zbkb`.
#
#     Zbb only    clz ctz cpop  min minu max maxu  sext.b sext.h zext.h  orc.b
#     both        andn orn xnor  rol ror rori  rev8
#     Zbkb only   pack packh  brev8  zip unzip
#
# **RV32-specific**: `rev8` is 0x698 here and 0x6b8 on RV64; `zext.h` is
# `pack rd, rs1, x0` here and an OP-32 encoding on RV64; `zip` and `unzip`
# exist on RV32 only; `rori` has a five-bit amount, so funct7 0b0110001 is
# RV64's and illegal here. Chapter 28 spells `brev8` as `rev.b`; chapter
# 32, riscv-opcodes and GNU binutils spell it `brev8`.
#
# **One figure in both chapters disagrees with everything else.** `zip`
# and `unzip` are drawn with 0x1e and 0x1f in the rs2 field; riscv-opcodes'
# `extensions/rv32_zbkb` says `24..20=15`, rvcpp's `RVOPC_ZIP_BITS` (the
# Hazard3 author's own table) says 0b01111, and GNU as 2.43 assembles
# `zip a0,a1` to 0x08f59513. This core and these tests use 0b01111.
#
# The Zcb compressed forms `c.sext.b`, `c.zext.h` and `c.sext.h` are in the
# same file because each one's page in chapter 27 (Zc*) says "Zbb is also
# required": they run on the RP2350 and are refused on the C5.
#
# ## The oracle, and what it can and cannot see
#
# rvcpp, Hazard3's own simulator (docs/architectures.md 2.1b), at
# `third_party/hazard3` 8af9929, implements every instruction above:
# `rv_core.cpp:248/252/254` (xnor, orn, andn), `:271-277` (max, maxu, min,
# minu), `:279/282` (ror, rol), `:285/287` (pack -- with rs2 = x0 also
# zext.h, which has no branch of its own -- and packh), `:337-379` (clz,
# cpop, ctz, sext.b, sext.h, zip, unzip, brev8, orc.b, rev8, rori) and
# `:849-855` (c.sext.b, c.zext.h, c.sext.h). So every one is held in
# lockstep below.
#
# **One qualification, stated where it applies.** This machine has no g++,
# so rvcpp is built with MSVC through `tests/riscv32/oracle/
# rvcpp_msvc_shim.h`, which supplies the four GCC builtins rvcpp computes
# `clz`, `ctz`, `cpop` and `rev8` with -- `_BitScanReverse`,
# `_BitScanForward`, `__popcnt`, `_byteswap_ulong`. For those four the
# oracle's arithmetic is that shim over MSVC's intrinsics (rvcpp itself
# answers the zero cases before calling them), so they are also checked
# against the spec's Sail in Python, a third implementation, below.
#
# What lockstep cannot see at all is gating: rvcpp runs every extension on
# every part, Zbc's `clmul` included. The refusals are asserted from the
# group tables above instead.

import pytest

from core.riscv32 import abi, disasm

from . import encode as e
from . import lockstep
from .conftest import PC, load

#: rvcpp's testbench halts when the CPU writes IO_EXIT.
EXIT = [e.lui("a7", 0xC0000), e.sw("x0", "a7", 8)]

M32 = 0xFFFFFFFF

#: Operands for the one-operand forms. Every single bit and every
#: single-bit hole, for clz, ctz and cpop at each count; the sign bits sext.b
#: and sext.h read; byte patterns orc.b, rev8 and brev8 move whole; and the
#: halves and alternations zip and unzip interleave.
UNARY_VALUES = tuple(sorted({
    0x00000000, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x80000001, 0x00000001,
    *(1 << bit for bit in range(32)),
    *(M32 ^ (1 << bit) for bit in range(32)),
    0x0000007F, 0x00000080, 0x000000FF, 0x00007FFF, 0x00008000, 0x0000FF80,
    0x0000FF00, 0x00FF0000, 0xFF000000, 0x00FF00FF, 0xFF00FF00, 0x0000FFFF,
    0xFFFF0000, 0x01020304, 0x80402010, 0x01000080, 0x00800100, 0x01010101,
    0x80808080, 0x7F7F7F7F, 0x12345678, 0xDEADBEEF, 0x55555555, 0xAAAAAAAA,
    0x33333333, 0xCCCCCCCC, 0x0F0F0F0F, 0xF0F0F0F0,
}))

#: Operands for the two-operand forms, taken pairwise: zero, all ones, both
#: sign-bit edges, both halfword halves, and two that are none of those.
BINARY_VALUES = (0x00000000, 0x00000001, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
                 0x80000001, 0x0000FFFF, 0xFFFF0000, 0x000000FF, 0xFFFFFF80,
                 0x12345678, 0xDEADBEEF)

#: Rotate amounts: every one the five-bit field holds, and four the register
#: forms must mask -- 32 and 33 rotate like 0 and 1, 63 like 31.
AMOUNTS = (*range(32), 32, 33, 63, 0xFFFFFFE1)


def li(register: str, value: int) -> list[int]:
    """`lui` + `addi`, the pair `li` assembles to for a full 32-bit value."""
    upper = ((value + 0x800) >> 12) & 0xFFFFF
    lower = (((value - (upper << 12)) + 0x800) & 0xFFF) - 0x800
    return [e.lui(register, upper), e.addi(register, register, lower)]


def image(body: list[int]) -> bytes:
    return e.image(body + EXIT)


def check(report: lockstep.Report, least: int) -> None:
    """Assert the two models agreed, with the failure spelled out."""
    assert report.divergence is None, str(report.divergence)
    assert report.stopped is None, (
        f"this core stopped after {report.agreed} of {report.traced} "
        f"instructions: {report.stopped}")
    assert report.matched_the_oracle
    assert report.agreed >= least, (
        f"only {report.agreed} instructions were compared; the program was "
        f"meant to run at least {least}")


# --- the spec's Sail, in Python ---------------------------------------------
#
# Transcribed from each instruction's page in chapter 28 rather than from
# exec.cc, so a misreading would have to be made twice by two writers in two
# languages to pass -- and then a third time by rvcpp, for every instruction
# the oracle can see.

def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def _sext(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return (value - (1 << bits)) & M32 if value >> (bits - 1) else value


SAIL_UNARY = {
    "clz": lambda x: 32 - x.bit_length(),
    "ctz": lambda x: 32 if x == 0 else (x & -x).bit_length() - 1,
    "cpop": lambda x: bin(x).count("1"),
    "sext.b": lambda x: _sext(x, 8),
    "sext.h": lambda x: _sext(x, 16),
    "zext.h": lambda x: x & 0xFFFF,
    "orc.b": lambda x: sum(0xFF << s for s in (0, 8, 16, 24) if (x >> s) & 0xFF),
    "rev8": lambda x: int.from_bytes(x.to_bytes(4, "little"), "big"),
    "brev8": lambda x: int.from_bytes(
        bytes(int(f"{byte:08b}"[::-1], 2) for byte in x.to_bytes(4, "little")),
        "little"),
    "zip": lambda x: sum((((x >> i) & 1) << (2 * i))
                         | (((x >> (i + 16)) & 1) << (2 * i + 1)) for i in range(16)),
    "unzip": lambda x: sum((((x >> (2 * i)) & 1) << i)
                           | (((x >> (2 * i + 1)) & 1) << (i + 16)) for i in range(16)),
}

SAIL_BINARY = {
    "andn": lambda a, b: a & ~b & M32,
    "orn": lambda a, b: (a | ~b) & M32,
    "xnor": lambda a, b: ~(a ^ b) & M32,
    "min": lambda a, b: a if _signed(a) < _signed(b) else b,
    "minu": lambda a, b: a if a < b else b,
    "max": lambda a, b: a if _signed(a) > _signed(b) else b,
    "maxu": lambda a, b: a if a > b else b,
    "rol": lambda a, b: ((a << (b & 31)) | (a >> (32 - (b & 31)))) & M32,
    "ror": lambda a, b: ((a >> (b & 31)) | (a << (32 - (b & 31)))) & M32,
    "pack": lambda a, b: (a & 0xFFFF) | ((b & 0xFFFF) << 16),
    "packh": lambda a, b: (a & 0xFF) | ((b & 0xFF) << 8),
}

#: Each mnemonic's encoder, one-operand forms as (rd, rs1).
UNARY = {
    "clz": e.clz, "ctz": e.ctz, "cpop": e.cpop, "sext.b": e.sext_b,
    "sext.h": e.sext_h, "zext.h": e.zext_h, "orc.b": e.orc_b, "rev8": e.rev8,
    "brev8": e.brev8, "zip": e.zip_, "unzip": e.unzip,
}
BINARY = {
    "andn": e.andn, "orn": e.orn, "xnor": e.xnor, "min": e.min_,
    "minu": e.minu, "max": e.max_, "maxu": e.maxu, "rol": e.rol, "ror": e.ror,
    "pack": e.pack, "packh": e.packh,
}

#: The group tables at the top, as the encodings each part must gate.
ZBB_ONLY = (e.clz("a0", "t0"), e.ctz("a0", "t0"), e.cpop("a0", "t0"),
            e.sext_b("a0", "t0"), e.sext_h("a0", "t0"), e.orc_b("a0", "t0"),
            e.min_("a0", "t0", "t1"), e.minu("a0", "t0", "t1"),
            e.max_("a0", "t0", "t1"), e.maxu("a0", "t0", "t1"))
SHARED = (e.andn("a0", "t0", "t1"), e.orn("a0", "t0", "t1"),
          e.xnor("a0", "t0", "t1"), e.rol("a0", "t0", "t1"),
          e.ror("a0", "t0", "t1"), e.rori("a0", "t0", 7), e.rev8("a0", "t0"))
ZBKB_ONLY = (e.pack("a0", "t0", "t1"), e.packh("a0", "t0", "t1"),
             e.brev8("a0", "t0"), e.zip_("a0", "t0"), e.unzip("a0", "t0"))

#: The Hazard3 with one of its two groups taken away -- masks no part has,
#: which is the only way to see the two groups gated separately.
WITHOUT_ZBB = abi.RP2350 & ~abi.EXT_ZBB
WITHOUT_ZBKB = abi.RP2350 & ~abi.EXT_ZBKB
WITHOUT_EITHER = abi.RP2350 & ~(abi.EXT_ZBB | abi.EXT_ZBKB)

ESP32_PARTS = {"ESP32-C3": abi.ESP32_C3, "ESP32-C5": abi.ESP32_C5,
               "ESP32-C6": abi.ESP32_C6}


def verdict(cpu, word: int, mask: int, regs: dict[int, int] | None = None) -> str:
    """'ok', 'illegal' or 'unimplemented' for one 32-bit word on one mask."""
    load(cpu, [word])
    cpu.set_extensions(mask)
    values = [0] * 32
    for number, value in (regs or {}).items():
        values[number] = value
    cpu.set_regs(values, pc=PC)
    try:
        cpu.step()
    except abi.Illegal:
        return "illegal"
    except abi.Unimplemented:
        return "unimplemented"
    return "ok"


# --- lockstep: this core and rvcpp, on the same bytes -----------------------


def test_every_one_operand_form_agrees_with_rvcpp_over_every_edge(oracle, tmp_path):
    """clz, ctz, cpop, sext.b, sext.h, zext.h, orc.b, rev8, brev8, zip and
    unzip over every value in `UNARY_VALUES`, all 32 registers and the PC
    compared after each instruction -- and one `clz x0` at the end, which
    rvcpp reports a writeback for and which must leave x0 zero here."""
    body: list[int] = []
    results = ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "s2", "s3", "s4", "s5")
    for value in UNARY_VALUES:
        body += li("t0", value)
        body += [UNARY[name](rd, "t0") for name, rd in zip(UNARY, results)]
    body.append(e.clz("x0", "t0"))
    check(lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                       cycles=4 * len(body)), least=len(body))


def test_every_two_operand_form_agrees_with_rvcpp_over_every_pair(oracle, tmp_path):
    """andn, orn, xnor, min, minu, max, maxu, rol, ror, pack and packh over
    every ordered pair of `BINARY_VALUES` -- signed against unsigned order at
    both sign-bit edges, and the halves pack and packh keep."""
    body: list[int] = []
    results = ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "s2", "s3", "s4", "s5")
    for first in BINARY_VALUES:
        for second in BINARY_VALUES:
            body += li("t0", first) + li("t1", second)
            body += [BINARY[name](rd, "t0", "t1") for name, rd in zip(BINARY, results)]
    check(lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                       cycles=4 * len(body)), least=len(body))


def test_every_rotate_amount_agrees_with_rvcpp(oracle, tmp_path):
    """rol and ror by every amount in `AMOUNTS` -- all 32 the field holds,
    and four the register forms must mask -- and rori by all 32, on values
    whose rotations are all distinct."""
    body: list[int] = []
    for value in (0x80000001, 0x12345678, 0xDEADBEEF):
        body += li("t0", value)
        for amount in AMOUNTS:
            body += li("t1", amount)
            body += [e.rol("a0", "t0", "t1"), e.ror("a1", "t0", "t1")]
        body += [e.rori("a2", "t0", amount) for amount in range(32)]
    check(lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                       cycles=4 * len(body)), least=len(body))


def test_the_compressed_zbb_unaries_agree_with_rvcpp(oracle, tmp_path):
    """c.sext.b, c.zext.h and c.sext.h on all eight registers they can name,
    over the sign-bit edges, two halfwords to a word."""
    body: list[int] = []
    registers = ("s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5")
    for value in (0x00000000, 0x0000007F, 0x00000080, 0x00007FFF, 0x00008000,
                  0xFFFFFFFF, 0x12345678, 0xDEADBEEF):
        for register in registers:
            body += li(register, value)
            body.append(e.c_sext_b(register) | (e.c_zext_h(register) << 16))
            body += li(register, value)
            body.append(e.c_sext_h(register) | (0x0001 << 16))   # c.nop behind
    check(lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                       cycles=8 * len(body)), least=len(body))


def test_rvcpp_runs_zbc_which_the_rp2350_lacks_and_this_core_refuses(oracle, tmp_path):
    """The blind spot, shown rather than claimed. `clmul` shares funct7
    0b0000101 with min and max; it is Zbc, absent from the RP2350's string.
    rvcpp traces it and carries on, and this core stops on it as Illegal --
    so a lockstep run that only counted agreements would read as a pass."""
    body = li("t0", 0x12345678) + li("t1", 0x9ABCDEF0) + [e.clmul("a0", "t0", "t1")]
    report = lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                          cycles=4 * len(body))
    assert report.divergence is None, str(report.divergence)
    assert report.agreed == 4, report
    assert report.traced > report.agreed, "rvcpp stopped at clmul too"
    assert report.stopped is not None and "is illegal for extensions" in report.stopped


# --- the spec's Sail, without the oracle -------------------------------------


def test_every_one_operand_form_matches_the_specs_sail(cpu):
    """The same values through the Sail transcriptions above: the evidence
    for clz, ctz, cpop and rev8 that does not route through the MSVC shim,
    and the evidence for all eleven on a machine with no rvcpp."""
    wrong = []
    for name, encoder in UNARY.items():
        for value in UNARY_VALUES:
            assert verdict(cpu, encoder("a0", "t0"), abi.RP2350, {5: value}) == "ok"
            expected = SAIL_UNARY[name](value)
            if cpu.reg(10) != expected:
                wrong.append(f"{name}({value:#010x}) = {cpu.reg(10):#010x}, "
                             f"Sail says {expected:#010x}")
    assert not wrong, wrong[:10]


def test_every_two_operand_form_matches_the_specs_sail(cpu):
    wrong = []
    for name, encoder in BINARY.items():
        for first in BINARY_VALUES:
            for second in (*BINARY_VALUES, *AMOUNTS):
                registers = {5: first, 6: second}
                assert verdict(cpu, encoder("a0", "t0", "t1"), abi.RP2350,
                               registers) == "ok"
                expected = SAIL_BINARY[name](first, second & M32)
                if cpu.reg(10) != expected:
                    wrong.append(f"{name}({first:#010x}, {second:#010x}) = "
                                 f"{cpu.reg(10):#010x}, Sail says {expected:#010x}")
    assert not wrong, wrong[:10]


def test_a_few_values_worked_by_hand_from_the_spec_pages(cpu):
    """Values a reader can check against the instruction pages without
    running anything, through the core and through the Sail transcription
    both: zip spreads the low half onto the even bits, so 0x0000FFFF zips to
    0x55555555 and unzips back; brev8 mirrors each byte in place; rev8 swaps
    the bytes end for end; orc.b fills each byte with a bit set; clz and ctz
    of zero are 32, which the spec defines and `__builtin_clz` does not."""
    worked = (
        ("zip", 0x0000FFFF, 0x55555555), ("unzip", 0x55555555, 0x0000FFFF),
        ("brev8", 0x01020304, 0x8040C020), ("rev8", 0x12345678, 0x78563412),
        ("orc.b", 0x00100001, 0x00FF00FF), ("clz", 0, 32), ("ctz", 0, 32),
        ("cpop", 0xFFFFFFFF, 32), ("sext.h", 0x00008000, 0xFFFF8000),
    )
    for name, value, expected in worked:
        assert SAIL_UNARY[name](value) == expected, name
        assert verdict(cpu, UNARY[name]("a0", "t0"), abi.RP2350, {5: value}) == "ok"
        assert cpu.reg(10) == expected, f"{name}({value:#x}) = {cpu.reg(10):#x}"


# --- gating: which part may run which group ---------------------------------


def test_no_esp32_part_runs_any_zbb_or_zbkb_encoding(cpu):
    """The C3 is RV32IMC, the C6 RV32IMAC and the C5 RV32IMAC with three Zc
    groups (docs/architectures.md 4.2, from Espressif's datasheets); the
    ESP32 Arduino core 3.3.11 compiles all three without either group
    (`-march=rv32imc_zicsr_zifencei`, and `rv32imac_zicsr_zifencei` for the
    C5 and C6, in esp32-arduino-libs' `flags/c_flags`). So every encoding
    here is Illegal on each -- the part's answer, never Unimplemented."""
    wrong = []
    for part, mask in ESP32_PARTS.items():
        for word in (*ZBB_ONLY, *SHARED, *ZBKB_ONLY, e.zext_h("a0", "t0")):
            answer = verdict(cpu, word, mask)
            if answer != "illegal":
                wrong.append(f"{part} answered {answer} for {word:#010x}")
    assert not wrong, wrong


def test_zbb_only_instructions_need_zbb(cpu):
    """clz on a part with Zbkb and no Zbb is refused: the groups share seven
    encodings, not all of them."""
    for word in ZBB_ONLY:
        assert verdict(cpu, word, WITHOUT_ZBB) == "illegal", hex(word)
        assert verdict(cpu, word, WITHOUT_ZBKB) == "ok", hex(word)


def test_zbkb_only_instructions_need_zbkb(cpu):
    for word in ZBKB_ONLY:
        assert verdict(cpu, word, WITHOUT_ZBKB) == "illegal", hex(word)
        assert verdict(cpu, word, WITHOUT_ZBB) == "ok", hex(word)


def test_the_seven_shared_instructions_run_with_either_group_and_not_neither(cpu):
    for word in SHARED:
        assert verdict(cpu, word, WITHOUT_ZBB) == "ok", hex(word)
        assert verdict(cpu, word, WITHOUT_ZBKB) == "ok", hex(word)
        assert verdict(cpu, word, WITHOUT_EITHER) == "illegal", hex(word)


def test_zext_h_is_pack_with_x0_so_either_group_opens_that_one_word(cpu):
    """RV32's zext.h is defined as `pack rd, rs1, x0` (chapter 28, zext.h's
    page): Zbb by one name, Zbkb by the other. Any other rs2 is pack proper,
    and only Zbkb has it."""
    zext_h = e.zext_h("a0", "t0")
    assert zext_h == e.pack("a0", "t0", "x0")
    assert verdict(cpu, zext_h, WITHOUT_ZBKB, {5: 0xABCD1234}) == "ok"
    assert cpu.reg(10) == 0x1234
    assert verdict(cpu, zext_h, WITHOUT_ZBB, {5: 0xABCD1234}) == "ok"
    assert verdict(cpu, zext_h, WITHOUT_EITHER) == "illegal"
    assert verdict(cpu, e.pack("a0", "t0", "t1"), WITHOUT_ZBKB) == "illegal"


def test_the_compressed_zbb_unaries_need_zbb_as_well_as_zcb(cpu):
    """"Zbb is also required" (chapter 27, each one's page). With Zcb and
    Zbkb but no Zbb all three are refused -- c.zext.h too, although the
    pack it expands to is Zbkb's. With both they run, values checked."""
    halves = {"c.sext.b": (e.c_sext_b("s0"), 0xFFFFFF80),
              "c.zext.h": (e.c_zext_h("s0"), 0x00008080),
              "c.sext.h": (e.c_sext_h("s0"), 0xFFFF8080)}
    for name, (half, expected) in halves.items():
        word = half | (0x0001 << 16)
        assert verdict(cpu, word, WITHOUT_ZBB, {8: 0x12348080}) == "illegal", name
        assert verdict(cpu, word, abi.RP2350, {8: 0x12348080}) == "ok", name
        assert cpu.reg(8) == expected, f"{name}: {cpu.reg(8):#010x}"
        assert cpu.pc == PC + 2, f"{name} is two bytes wide"


def test_this_core_runs_exactly_what_the_disassembler_names_on_an_rp2350(cpu):
    """Every OP and OP-IMM funct3 x funct7 x rs2 field: 65,536 words.

    `core/riscv32/disasm.py` is swept against GNU objdump 2.43 over this same
    space (test_disasm.py), so agreeing with it ties the executor's decoder
    to binutils'. Every word it names must run on an RP2350; every word it
    cannot name must be Illegal -- including the neighbours Zbb and Zbkb
    leave shut, like clz's field at 3, zip's at anything but 0b01111, rori
    with bit 25 set, and Zbc's clmul. Nothing may answer Unimplemented.
    """
    wrong = []
    executed = 0
    for opcode in (0x13, 0x33):
        for funct3 in range(8):
            for funct7 in range(128):
                for rs2 in range(32):
                    word = (opcode | (10 << 7) | (funct3 << 12) | (5 << 15)
                            | (rs2 << 20) | (funct7 << 25))
                    named = not disasm.decode(word)[0].startswith("0x")
                    answer = verdict(cpu, word, abi.RP2350)
                    executed += answer == "ok"
                    if answer != ("ok" if named else "illegal"):
                        wrong.append(f"{word:#010x} ({disasm.decode(word)[0]!r}) "
                                     f"answered {answer}")
    assert not wrong, wrong[:10]
    # Derived, not measured. OP-IMM: the six immediate funct3 values take
    # every funct7 and rs2 (6 x 4096); slli, srli, srai, rori, bseti, bclri,
    # binvi and bexti take every amount (8 x 32); and ten words are named
    # whole -- clz, ctz, cpop, sext.b, sext.h, zip, orc.b, rev8, brev8,
    # unzip. OP, each row x 32 rs2: base 10 (eight funct3 under 0, sub,
    # sra), M 8, Zba 3, Zbs 4, and Zbb/Zbkb's eleven register forms (zext.h
    # being pack's rs2 = x0 row).
    assert executed == 6 * 4096 + 8 * 32 + 10 + (10 + 8 + 3 + 4 + 11) * 32, executed


def test_every_encoder_helper_renders_as_its_own_mnemonic():
    """encode.py writes the bits these tests run, and a transposed field
    would make a test about clz run ctz -- in both models, in agreement. So
    each helper is read back through the disassembler that is swept against
    GNU objdump 2.43."""
    for name, encoder in UNARY.items():
        assert disasm.decode(encoder("a0", "t0"))[0] == f"{name}\ta0,t0", name
    for name, encoder in BINARY.items():
        assert disasm.decode(encoder("a0", "t0", "t1"))[0] == f"{name}\ta0,t0,t1", name
    assert disasm.decode(e.rori("a0", "t0", 31))[0] == "rori\ta0,t0,0x1f"
    assert disasm.decode(e.clmul("a0", "t0", "t1"))[0].startswith("0x")
    assert disasm.decode(e.c_sext_b("s1"))[0] == "c.sext.b\ts1"
    assert disasm.decode(e.c_zext_h("s1"))[0] == "c.zext.h\ts1"
    assert disasm.decode(e.c_sext_h("s1"))[0] == "c.sext.h\ts1"
