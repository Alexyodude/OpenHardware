# OpenHardware — the Hazard3's own extensions, on the RP2350 (OH-219).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Which four, and where each one's encodings are
#
# The RP2350 datasheet (build 80d627281ed5, the copy docs/architectures.md
# 5.4 cites) names them in section 3.8, PDF p.227: "Additionally, RP2350
# enables the following Hazard3 custom extensions" -- Xh3power, Xh3bextm
# ("used in bootrom"), Xh3irq and Xh3pmpm -- and 3.8.8's Table 387 (p.279)
# sets EXTENSION_XH3BEXTM, _XH3IRQ, _XH3PMPM and _XH3POWER to 1. Hazard3's
# own documentation, `third_party/hazard3` at 8af9929,
# `doc/sections/custom_extensions.adoc`, says where each one's encodings are:
#
#   Xh3bextm  two instructions in custom-0, opcode 0x0b: h3.bextm at funct3
#             000 and h3.bextmi at 100 (:123-141, :174-193). Bits 31:29 and
#             25 are RES0, and 28:26 hold the mask's width less one.
#   Xh3irq    "no new instructions, but several CSRs" (:29): h3.meiea to
#             h3.meicontext, 0xbe0 to 0xbe5 (`csr.adoc` :620-734).
#   Xh3pmpm   one CSR, h3.pmpcfgm0 (:49), at 0xbd0 (`csr.adoc` :828).
#   Xh3power  one CSR, h3.msleep (:60), at 0xbf0 (`csr.adoc` :850), and two
#             hints "in the `slt` nop-compatible custom hint space" (:60):
#             h3.block is `slt x0, x0, x0` (:76), h3.unblock `slt x0, x0,
#             x1` (:98).
#
# The datasheet's CSR list (3.8.9, PDF pp.285-286) gives the same addresses.
#
# ## What this core answers, and why each is the right word
#
# Only Xh3bextm has encodings of its own, and they are what answered
# `Illegal` -- "the silicon lacks this" -- on an RP2350 whose silicon runs
# them. rvcpp implements both (`test/sim/rvcpp/rv_core.cpp:646-656`, masks at
# `include/encoding/rv_opcodes.h:249-252`), so they are modelled and held in
# lockstep with it, behind `EXT_XH3BEXTM`, which `abi.RP2350` alone has.
# Every other custom-0 word stays Illegal on the RP2350, and rightly: the
# Hazard3's decoder matches only those two shapes (`hdl/rv_opcodes.vh:156-157`,
# `hdl/hazard3_decode.v:502-505`) and rvcpp traps the rest.
#
# The other three are CSRs, and this core has none: every CSR access
# answers `Unimplemented`, a hole in the model, which is the true word for
# them. Xh3power's two hints are base-ISA `slt` writes to x0, and run as
# that, changing nothing, here and in rvcpp. What the silicon does besides
# -- sleep until an unblock or an interrupt -- is time, which this core does
# not model; no register differs afterwards.
#
# **The datasheet misprints one field.** Tables 379 and 380 (3.8.6.4, PDF
# pp.272-273) give bits 6:2 as `0b01011`. That is the low five bits of the
# whole opcode 0b0001011; its bits 6:2 are 0b00010, which is what
# custom_extensions.adoc:139 and :191 print, and the same pages' own macros
# assemble `.insn r 0x0b` and `.insn i 0x0b`. The HDL and rvcpp agree: 0x0b.
#
# ## The listing
#
# `core/riscv32/disasm.py` names both, and nothing outside this repository
# can check how: GNU objdump 2.43.1 prints `0x00c5850b` as `.insn 4,
# 0x00c5850b`, and GCC 14.2 rejects `-march=rv32i_xh3bextm` as an
# "unsupported non-standard extension". So the reference is the doc's own
# macros, `h3.bextm rd rs1 rs2 nbits` and `h3.bextmi rd rs1 shamt nbits`
# (:161, :213), in the module's objdump spelling: commas, a shift amount in
# hex as objdump prints `slli`'s, the width in decimal as the macros take it.

from core.riscv32 import abi, disasm

from . import encode as e
from . import lockstep
from .conftest import PC
from .test_zbb_zbkb import check, image, li, verdict

#: Every amount h3.bextm's five-bit field takes, and four the register form
#: must cut to `rs2[4:0]` (custom_extensions.adoc:160): 32 and 33 shift like
#: 0 and 1, 63 and 0xFFFFFFE1 like 31 and 1.
#:
#: **On this machine those four cannot fail.** x86 and ARM64 mask a shift
#: count to five bits in hardware, so exec.cc without its `& 0x1Fu` passes
#: every test here (OH-219's review removed it and all of them stayed
#: green). They hold the answer, not the mask; the mask is there because a
#: C++ shift by 32 or more is undefined.
AMOUNTS = (*range(32), 32, 33, 63, 0xFFFFFFE1)

#: Values whose eight-bit windows differ at every shift: a width or a shift
#: off by one gives a different answer on each.
VALUES = (0xDEADBEEF, 0x80000001, 0xFFFFFFFF, 0x12345678)

#: 1 to 8, the widths the three-bit `size` field encodes.
WIDTHS = range(1, 9)

#: One destination per width, so a program's every result stays in the file
#: lockstep compares.
RESULTS = ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "s2")

#: Xh3power's two hints, by their base-ISA encodings.
H3_BLOCK = e.slt("x0", "x0", "x0")
H3_UNBLOCK = e.slt("x0", "x0", 1)

#: The CSRs of Xh3irq, Xh3pmpm and Xh3power, by `csr.adoc`'s addresses.
XH3_CSRS = {"h3.meiea": 0xBE0, "h3.meipa": 0xBE1, "h3.meifa": 0xBE2,
            "h3.meipra": 0xBE3, "h3.meinext": 0xBE4, "h3.meicontext": 0xBE5,
            "h3.pmpcfgm0": 0xBD0, "h3.msleep": 0xBF0}


def h3_extract(value: int, amount: int, width: int) -> int:
    """custom_extensions.adoc:160 and :212, as written there:
    `rd = (rs1 >> rs2[4:0]) & ~(-1 << nbits)`, the immediate form with
    `shamt` for `rs2[4:0]`."""
    return (value >> (amount & 0x1F)) & ~(-1 << width) & 0xFFFFFFFF


def csr_access(funct3: int, rd: str, csr: int, rs1: str) -> int:
    """A Zicsr instruction: the CSR's address in bits 31:20, SYSTEM's
    opcode, funct3 001 for csrrw and 010 for csrrs."""
    return (csr << 20) | e.r_type(0x00, "x0", rs1, funct3, rd, 0x73)


# --- lockstep: this core and rvcpp, on the same bytes -----------------------


def test_h3_bextm_and_h3_bextmi_agree_with_rvcpp_at_every_width_and_shift(oracle, tmp_path):
    """h3.bextm at every width and every amount in `AMOUNTS`, h3.bextmi at
    every width and every shift, over `VALUES` -- and one of each writing
    x0, and Xh3power's two hints, which rvcpp also runs as `slt` to x0."""
    body: list[int] = []
    for value in VALUES:
        body += li("t0", value)
        for amount in AMOUNTS:
            body += li("t1", amount)
            body += [e.h3_bextm(rd, "t0", "t1", width)
                     for rd, width in zip(RESULTS, WIDTHS)]
        for shamt in range(32):
            body += [e.h3_bextmi(rd, "t0", shamt, width)
                     for rd, width in zip(RESULTS, WIDTHS)]
    body += [e.h3_bextm("x0", "t0", "t1", 8), e.h3_bextmi("x0", "t0", 3, 8),
             H3_BLOCK, H3_UNBLOCK]
    check(lockstep.run(image(body), tmp_path, extensions=abi.RP2350,
                       cycles=4 * len(body)), least=len(body))


# --- Hazard3's own definition, without the oracle ---------------------------


def test_h3_bextm_and_h3_bextmi_compute_what_the_hazard3_docs_define(cpu):
    """The same grid through `h3_extract`, the documentation's own line:
    the evidence for these two on a machine with no rvcpp."""
    wrong = []
    for value in VALUES:
        for width in WIDTHS:
            for amount in AMOUNTS:
                word = e.h3_bextm("a0", "t0", "t1", width)
                assert verdict(cpu, word, abi.RP2350, {5: value, 6: amount}) == "ok"
                if cpu.reg(10) != h3_extract(value, amount, width):
                    wrong.append(f"h3.bextm({value:#010x}, {amount:#x}, {width}) "
                                 f"= {cpu.reg(10):#x}")
            for shamt in range(32):
                word = e.h3_bextmi("a0", "t0", shamt, width)
                assert verdict(cpu, word, abi.RP2350, {5: value}) == "ok"
                if cpu.reg(10) != h3_extract(value, shamt, width):
                    wrong.append(f"h3.bextmi({value:#010x}, {shamt}, {width}) "
                                 f"= {cpu.reg(10):#x}")
    assert not wrong, wrong[:10]


def test_the_encoder_builds_what_the_hazard3_docs_assemble():
    """encode.py writes these words, and both models run whatever it writes,
    in agreement -- so it is held to the documentation's own macros,
    `.insn r 0x0b, 0, ((nbits - 1) & 0x7) << 1, rd, rs1, rs2` and `.insn i
    0x0b, 0x4, rd, rs1, (shamt & 0x1f) | (((nbits - 1) & 0x7) << 6)`
    (custom_extensions.adoc:169 and :224), arithmetic that reaches `size`
    through funct7 and the immediate rather than through bit 26. And to the
    one word this ticket was filed with, `h3.bextm a0, a1, a2, 1`."""
    assert e.h3_bextm("a0", "a1", "a2", 1) == 0x00C5850B
    for width in WIDTHS:
        funct7 = ((width - 1) & 0x7) << 1
        assert e.h3_bextm("a0", "a1", "a2", width) == (
            (funct7 << 25) | (12 << 20) | (11 << 15) | (0 << 12) | (10 << 7) | 0x0B)
        for shamt in range(32):
            imm = (shamt & 0x1F) | (((width - 1) & 0x7) << 6)
            assert e.h3_bextmi("a0", "a1", shamt, width) == (
                (imm << 20) | (11 << 15) | (4 << 12) | (10 << 7) | 0x0B)


def test_the_disassembler_names_both_in_the_docs_operand_order():
    """`h3.bextm rd rs1 rs2 nbits` and `h3.bextmi rd rs1 shamt nbits`
    (custom_extensions.adoc:161, :213), at every width and every shift, on
    registers that are not each other's neighbours -- so a transposed
    operand or a width read from the wrong bits renders a different line."""
    for width in WIDTHS:
        assert disasm.decode(e.h3_bextm("a0", "t0", "s1", width))[0] == (
            f"h3.bextm\ta0,t0,s1,{width}")
        for shamt in range(32):
            assert disasm.decode(e.h3_bextmi("a0", "t0", shamt, width))[0] == (
                f"h3.bextmi\ta0,t0,0x{shamt:x},{width}")


# --- what each part refuses, which rvcpp cannot say ---------------------------


def test_custom_0_runs_only_the_two_xh3bextm_shapes_on_an_rp2350(cpu):
    """Every funct3 x funct7 of custom-0, registers fixed: 1,024 words.

    The two shapes, at each of the eight widths, execute; every other word
    -- RES0 bit 31, 30, 29 or 25 set, or any other funct3 -- is Illegal,
    as on the chip. None may answer Unimplemented: nothing in this opcode
    is waiting to be written. And the disassembler names exactly the words
    that execute, so a listing never names one the core refuses or leaves
    one it runs as a raw word."""
    expected = {(funct3, size << 1) for funct3 in (0x0, 0x4) for size in range(8)}
    executed, wrong = set(), []
    for funct3 in range(8):
        for funct7 in range(128):
            word = e.r_type(funct7, "t1", "t0", funct3, "a0", 0x0B)
            answer = verdict(cpu, word, abi.RP2350, {5: 0xDEADBEEF, 6: 4})
            if answer == "ok":
                executed.add((funct3, funct7))
            elif answer != "illegal":
                wrong.append(f"{word:#010x} answered {answer}")
            named = not disasm.decode(word)[0].startswith("0x")
            if named != (answer == "ok"):
                wrong.append(f"{word:#010x} ({disasm.decode(word)[0]!r}) "
                             f"answered {answer}")
    assert not wrong, wrong[:10]
    assert executed == expected, sorted(executed ^ expected)


def test_xh3bextm_is_its_own_bit_and_no_esp32_c3_or_c6_has_it(cpu):
    """The C3's datasheet gives "RV32IMC ISA" and the C6's "RV32IMAC ISA"
    (docs/architectures.md 4.2), and neither names a custom extension, so
    both refuse a custom-0 word as Illegal. So does an RP2350 with the bit
    taken away, and the bit alone opens both shapes: the gate is that bit
    and nothing else.

    The C5 is left out on purpose. Its datasheet names a custom extension
    of its own, Xhwlp, whose encodings nothing here has read, so what a C5
    must answer for a custom-0 word is not established."""
    words = (e.h3_bextm("a0", "t0", "t1", 4), e.h3_bextmi("a0", "t0", 4, 4))
    for word in words:
        for part in (abi.ESP32_C3, abi.ESP32_C6, abi.RP2350 & ~abi.EXT_XH3BEXTM):
            assert verdict(cpu, word, part) == "illegal", (hex(word), hex(part))
        assert verdict(cpu, word, abi.EXT_XH3BEXTM, {5: 0xDEADBEEF, 6: 4}) == "ok"
        assert cpu.reg(10) == 0xE, hex(cpu.reg(10))


def test_the_other_three_are_csrs_and_answer_unimplemented_on_an_rp2350(cpu):
    """Xh3irq, Xh3pmpm and Xh3power's MSLEEP are CSRs, and this core has no
    CSRs: a read or a write of any of them is a hole in the model, which
    is what `Unimplemented` says. `Illegal` would say the RP2350 lacks
    them, and the datasheet says it has them."""
    for name, csr in XH3_CSRS.items():
        for word in (csr_access(0x2, "a0", csr, "x0"),      # csrr a0, csr
                     csr_access(0x1, "x0", csr, "a0")):     # csrw csr, a0
            assert verdict(cpu, word, abi.RP2350) == "unimplemented", (name, hex(word))


def test_xh3powers_hints_run_as_slt_to_x0_and_change_nothing(cpu):
    """h3.block and h3.unblock are `slt x0, x0, x0` and `slt x0, x0, x1`:
    the base ISA's, so they run on every part, and write only x0. The PC
    moves on four bytes and no register moves at all."""
    registers = {number: 0x01010101 * number for number in range(1, 32)}
    for word in (H3_BLOCK, H3_UNBLOCK):
        for part in (abi.RP2350, abi.ESP32_C3):
            assert verdict(cpu, word, part, registers) == "ok", hex(word)
            assert cpu.get_regs().as_list() == [0] + list(registers.values())
            assert cpu.pc == PC + 4
