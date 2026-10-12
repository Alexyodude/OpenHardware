#!/usr/bin/env python3
# OpenHardware - RV32 instructions as text.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Disassemble what `core/riscv32` executes, for the Disassembly pane.

`webui/api.py`'s `listing_view` resolves `core.<core>.disasm` and answers
`{present: false, note}` when it does not exist. `riscv32` was the live case
that comment named; this is the module that closes it.

## This is a second decoder, and that is the risk

`core/riscv32/exec.cc` already decodes every one of these encodings. This
decodes them again, in a different language, to produce text -- so the two can
disagree, and a listing that disagrees with what executed is worse than no
listing at all.

`arm-none-eabi-objdump` is what contains that risk for the Cortex-M0, and
`riscv32-esp-elf-objdump` does it here: `tests/riscv32/test_disasm.py` lays
every encoding this module claims end to end and compares a single objdump
pass. The compressed half of that space is small enough to enumerate whole --
49,152 encodings -- which is the same sweep `tests/riscv32/test_rvc.py` runs
against the executor.

## Width is decided by the first two bits, and getting it wrong is silent

`(halfword & 3) != 3` means a 16-bit instruction. So a listing interleaves
widths, and `disassemble` must advance by **what it decoded** rather than by a
constant. A fixed stride does not fault: it produces a plausible listing offset
by two bytes from the second instruction onward, every line of it a real
instruction and none of them the ones that ran.

## What it prints, and why it matches objdump rather than being tidier

The compressed mnemonics are printed as `c.addi`, `c.lw` and so on, which is
what `objdump -M no-aliases` prints. Printing the *expansion* -- `addi a5,a5,1`
for `c.addi a5,1` -- was the alternative, and it is arguably more useful to a
reader. It was rejected because it would make the sweep need a mapping table
between two spellings of every instruction, and that table would be a third
place the encoding is written down. Matching the oracle exactly is worth more
than being clever, which is the same call `core/cortexm0/disasm.py` makes about
not collapsing register-list ranges.

Registers print by their ABI names -- `sp`, `a0`, `ra` -- because that is what
every RISC-V document, objdump, and `core/riscv32/machine.py`'s register view
use. `x2` reads as a number; `sp` reads as a stack pointer.
"""

from __future__ import annotations

import dataclasses

from core.riscv32.machine import REGISTER_NAMES

#: What this module can render. Kept as a set so a test can assert the
#: disassembler and the executor agree about scope: an encoding one knows and
#: the other does not is a divergence waiting to be found by a person rather
#: than by a sweep.
EXTENSIONS = ("I", "M", "C", "Zba", "Zbb", "Zbs", "Zbkb", "Zcb", "Zcmp", "Zcmt",
              "Xh3bextm")


@dataclasses.dataclass(frozen=True)
class Line:
    """One disassembled instruction."""

    address: int
    #: 2 or 4. The field the objdump comparison protects.
    width: int
    #: The encoding, as a whole word for a 32-bit instruction and as the
    #: halfword alone for a compressed one.
    encoding: int
    text: str

    @property
    def raw(self) -> str:
        """The encoding as objdump prints it.

        Four hex digits for a compressed instruction and eight for a full one,
        which is the width objdump uses and therefore what a reader comparing
        the two panes expects.
        """
        return f"{self.encoding:04x}" if self.width == 2 else f"{self.encoding:08x}"


def _reg(index: int) -> str:
    return REGISTER_NAMES[index & 0x1F]


def _creg(three: int) -> str:
    """A compressed register field, which names x8..x15 in three bits."""
    return REGISTER_NAMES[(three & 0x7) + 8]


def _sreg(three: int) -> str:
    """A Zcmp saved-register operand: 0..1 are s0..s1, 2..7 are s2..s7."""
    return _reg(8 + three if three < 2 else 16 + three)


def _rlist_text(rlist: int) -> str:
    """A Zcmp register list, the spec's own spelling."""
    if rlist == 4:
        return "{ra}"
    if rlist == 5:
        return "{ra,s0}"
    if rlist == 15:
        return "{ra,s0-s11}"
    return f"{{ra,s0-s{rlist - 5}}}"


def _sign_extend(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _bits(value: int, hi: int, lo: int) -> int:
    return (value >> lo) & ((1 << (hi - lo + 1)) - 1)


def _orders(bits: int) -> str:
    """A fence's `pred` or `succ` field, as objdump spells it.

    Bit 3 is device input, 2 device output, 1 memory read, 0 memory write, and
    objdump prints the set letters in that order -- `rw`, `iorw`, `i`. A field
    of zero orders nothing, which is a legal encoding with no meaning, and
    objdump calls it `unknown` rather than printing an empty operand.
    """
    letters = "".join(
        letter for bit, letter in ((3, "i"), (2, "o"), (1, "r"), (0, "w"))
        if bits & (1 << bit)
    )
    return letters or "unknown"


def _target(address: int, offset: int) -> str:
    """A branch target, as objdump prints one in a raw binary.

    `0x...` and not a symbol: with `-D -b binary` there are no symbols, which
    is the mode the sweep uses and therefore the spelling to match.
    """
    return f"0x{(address + offset) & 0xFFFFFFFF:x}"


# --- the 32-bit instructions ------------------------------------------------

_BRANCH = {0x0: "beq", 0x1: "bne", 0x4: "blt", 0x5: "bge", 0x6: "bltu", 0x7: "bgeu"}
_LOAD = {0x0: "lb", 0x1: "lh", 0x2: "lw", 0x4: "lbu", 0x5: "lhu"}
_STORE = {0x0: "sb", 0x1: "sh", 0x2: "sw"}
_OP_IMM = {0x0: "addi", 0x2: "slti", 0x3: "sltiu", 0x4: "xori", 0x6: "ori", 0x7: "andi"}
_OP = {0x0: "add", 0x1: "sll", 0x2: "slt", 0x3: "sltu",
       0x4: "xor", 0x5: "srl", 0x6: "or", 0x7: "and"}
_MULDIV = {0x0: "mul", 0x1: "mulh", 0x2: "mulhsu", 0x3: "mulhu",
           0x4: "div", 0x5: "divu", 0x6: "rem", 0x7: "remu"}


def _decode32(word: int, address: int) -> str:
    opcode = word & 0x7F
    rd = _bits(word, 11, 7)
    funct3 = _bits(word, 14, 12)
    rs1 = _bits(word, 19, 15)
    rs2 = _bits(word, 24, 20)
    funct7 = _bits(word, 31, 25)

    if opcode == 0x37:
        return f"lui\t{_reg(rd)},0x{_bits(word, 31, 12):x}"
    if opcode == 0x17:
        return f"auipc\t{_reg(rd)},0x{_bits(word, 31, 12):x}"

    if opcode == 0x6F:
        offset = _sign_extend(
            (_bits(word, 31, 31) << 20) | (_bits(word, 19, 12) << 12)
            | (_bits(word, 20, 20) << 11) | (_bits(word, 30, 21) << 1), 21)
        return f"jal\t{_reg(rd)},{_target(address, offset)}"

    if opcode == 0x67 and funct3 == 0:
        return f"jalr\t{_reg(rd)},{_sign_extend(_bits(word, 31, 20), 12)}({_reg(rs1)})"

    if opcode == 0x63 and funct3 in _BRANCH:
        offset = _sign_extend(
            (_bits(word, 31, 31) << 12) | (_bits(word, 7, 7) << 11)
            | (_bits(word, 30, 25) << 5) | (_bits(word, 11, 8) << 1), 13)
        return (f"{_BRANCH[funct3]}\t{_reg(rs1)},{_reg(rs2)},"
                f"{_target(address, offset)}")

    if opcode == 0x03 and funct3 in _LOAD:
        offset = _sign_extend(_bits(word, 31, 20), 12)
        return f"{_LOAD[funct3]}\t{_reg(rd)},{offset}({_reg(rs1)})"

    if opcode == 0x23 and funct3 in _STORE:
        offset = _sign_extend((funct7 << 5) | rd, 12)
        return f"{_STORE[funct3]}\t{_reg(rs2)},{offset}({_reg(rs1)})"

    if opcode == 0x13:
        if funct3 in _OP_IMM:
            imm = _sign_extend(_bits(word, 31, 20), 12)
            return f"{_OP_IMM[funct3]}\t{_reg(rd)},{_reg(rs1)},{imm}"
        if funct3 == 0x1 and funct7 == 0x00:
            return f"slli\t{_reg(rd)},{_reg(rs1)},0x{rs2:x}"
        if funct3 == 0x5 and funct7 in (0x00, 0x20):
            name = "srli" if funct7 == 0x00 else "srai"
            return f"{name}\t{_reg(rd)},{_reg(rs1)},0x{rs2:x}"
        # Zbs immediates share funct3 001 and 101 with the shifts, which is the
        # overlap OH-44 records as the real hazard of that slice.
        zbs = {(0x1, 0x14): "bseti", (0x1, 0x24): "bclri",
               (0x1, 0x34): "binvi", (0x5, 0x24): "bexti"}
        if (funct3, funct7) in zbs:
            return f"{zbs[(funct3, funct7)]}\t{_reg(rd)},{_reg(rs1)},0x{rs2:x}"
        # Zbb and Zbkb (OH-208): one-operand forms named by the whole 12-bit
        # immediate, the rs2 field being part of the name rather than a
        # register -- matched the same way `exec.cc` matches them.
        unary = ({0x600: "clz", 0x601: "ctz", 0x602: "cpop", 0x604: "sext.b",
                  0x605: "sext.h", 0x08F: "zip"} if funct3 == 0x1 else
                 {0x287: "orc.b", 0x698: "rev8", 0x687: "brev8", 0x08F: "unzip"}
                 if funct3 == 0x5 else {})
        if _bits(word, 31, 20) in unary:
            return f"{unary[_bits(word, 31, 20)]}\t{_reg(rd)},{_reg(rs1)}"
        if funct3 == 0x5 and funct7 == 0x30:
            return f"rori\t{_reg(rd)},{_reg(rs1)},0x{rs2:x}"
        return ""

    if opcode == 0x33:
        if funct7 == 0x01:
            return f"{_MULDIV[funct3]}\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        if funct7 == 0x00 and funct3 in _OP:
            return f"{_OP[funct3]}\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        if funct7 == 0x20 and funct3 == 0x0:
            return f"sub\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        if funct7 == 0x20 and funct3 == 0x5:
            return f"sra\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        zba = {0x2: "sh1add", 0x4: "sh2add", 0x6: "sh3add"}
        if funct7 == 0x10 and funct3 in zba:
            return f"{zba[funct3]}\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        zbs = {(0x1, 0x14): "bset", (0x1, 0x24): "bclr",
               (0x1, 0x34): "binv", (0x5, 0x24): "bext"}
        if (funct3, funct7) in zbs:
            return f"{zbs[(funct3, funct7)]}\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        # Zbb and Zbkb (OH-208). `pack rd,rs1,zero` is Zbb's RV32 `zext.h`
        # -- one encoding, and objdump names it zext.h, so this does too.
        if funct7 == 0x04 and funct3 == 0x4 and rs2 == 0:
            return f"zext.h\t{_reg(rd)},{_reg(rs1)}"
        zbb = {(0x4, 0x20): "xnor", (0x6, 0x20): "orn", (0x7, 0x20): "andn",
               (0x4, 0x05): "min", (0x5, 0x05): "minu", (0x6, 0x05): "max",
               (0x7, 0x05): "maxu", (0x1, 0x30): "rol", (0x5, 0x30): "ror",
               (0x4, 0x04): "pack", (0x7, 0x04): "packh"}
        if (funct3, funct7) in zbb:
            return f"{zbb[(funct3, funct7)]}\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)}"
        return ""

    if opcode == 0x0F:
        if funct3 == 0x0:
            # **`pred` and `succ` are operands, not padding.** They say which
            # of input, output, read and write the fence orders, and objdump
            # prints them -- `fence rw,rw` is the one a compiler emits. This
            # rendered a bare `fence` until the objdump sweep showed the
            # difference, which is precisely what a sweep is for: no image in
            # this repository contains a fence, so nothing else would have
            # said so.
            #
            # The `rd` and `rs1` fields are ignored, and that is the
            # specification's instruction rather than a shortcut: they are
            # reserved for finer-grain fences, and "base implementations shall
            # ignore these fields". objdump is stricter and refuses to render
            # them when set; `core/riscv32/exec.cc` ignores them too, so this
            # agrees with what executes.
            return f"fence	{_orders(_bits(word, 27, 24))},{_orders(_bits(word, 23, 20))}"
        if funct3 == 0x1:
            return "fence.i"
        return ""

    if opcode == 0x73:
        if word == 0x00000073:
            return "ecall"
        if word == 0x00100073:
            return "ebreak"
        # JVT (0x017) is the one CSR the core executes (OH-146, Zcmt), so it
        # is the one this renders -- in objdump's own spelling, `0x17` and
        # all, so the sweep needs no excuse for it. Every other CSR encoding
        # stays refused here exactly as it stays Unimplemented there.
        if _bits(word, 31, 20) == 0x017 and funct3 not in (0x0, 0x4):
            name = {0x1: "csrrw", 0x2: "csrrs", 0x3: "csrrc",
                    0x5: "csrrwi", 0x6: "csrrsi", 0x7: "csrrci"}[funct3]
            operand = _reg(rs1) if funct3 < 0x4 else str(rs1)
            return f"{name}\t{_reg(rd)},0x17,{operand}"
        return ""

    if opcode == 0x0B:
        # custom-0: the Hazard3's Xh3bextm (OH-219), the two shapes
        # `exec.cc` runs and no others -- bits 31:29 and 25 clear, funct3
        # 000 or 100. No binutils knows them, so the operands follow the
        # doc's own macros, `h3.bextm rd rs1 rs2 nbits` and `h3.bextmi rd
        # rs1 shamt nbits` (custom_extensions.adoc:161, :213), with the shift
        # amount in hex as `slli`'s is and `nbits` from bits 28:26, plus one.
        if funct3 in (0x0, 0x4) and word & 0xE2000000 == 0:
            nbits = _bits(word, 28, 26) + 1
            if funct3 == 0x0:
                return f"h3.bextm\t{_reg(rd)},{_reg(rs1)},{_reg(rs2)},{nbits}"
            return f"h3.bextmi\t{_reg(rd)},{_reg(rs1)},0x{rs2:x},{nbits}"
        return ""

    return ""


# --- the compressed instructions --------------------------------------------


def _decode16(c: int, address: int) -> str:
    quadrant = c & 0x3
    funct3 = _bits(c, 15, 13)

    if c == 0:
        # The all-zero halfword is a *defined* illegal encoding in RVC rather
        # than an unassigned one, and it has a name. `core/riscv32/exec.cc`
        # routes it to `Illegal` for the same reason: zeros are what a program
        # reads the instant it runs off the end of anything, so this is the
        # encoding that has to be loudest.
        return "c.unimp"

    if quadrant == 0:
        rd, rs1 = _creg(_bits(c, 4, 2)), _creg(_bits(c, 9, 7))
        if funct3 == 0x0:
            imm = ((_bits(c, 10, 7) << 6) | (_bits(c, 12, 11) << 4)
                   | (_bits(c, 5, 5) << 3) | (_bits(c, 6, 6) << 2))
            return "" if imm == 0 else f"c.addi4spn\t{rd},sp,{imm}"
        if funct3 in (0x2, 0x6):
            imm = ((_bits(c, 5, 5) << 6) | (_bits(c, 12, 10) << 3)
                   | (_bits(c, 6, 6) << 2))
            name = "c.lw" if funct3 == 0x2 else "c.sw"
            return f"{name}\t{rd},{imm}({rs1})"
        if funct3 == 0x4:
            # Zcb (OH-146). Rendered whether or not the part has it, the way
            # bset is: the disassembler renders the union, the executor gates.
            kind = _bits(c, 12, 10)
            if kind == 0x0:
                imm = (_bits(c, 5, 5) << 1) | _bits(c, 6, 6)
                return f"c.lbu\t{rd},{imm}({rs1})"
            if kind == 0x1:
                name = "c.lh" if _bits(c, 6, 6) else "c.lhu"
                return f"{name}\t{rd},{_bits(c, 5, 5) << 1}({rs1})"
            if kind == 0x2:
                imm = (_bits(c, 5, 5) << 1) | _bits(c, 6, 6)
                return f"c.sb\t{rd},{imm}({rs1})"
            if kind == 0x3 and _bits(c, 6, 6) == 0:
                return f"c.sh\t{rd},{_bits(c, 5, 5) << 1}({rs1})"
            return ""
        return ""

    if quadrant == 1:
        rd = _bits(c, 11, 7)
        imm6 = _sign_extend((_bits(c, 12, 12) << 5) | _bits(c, 6, 2), 6)
        if funct3 == 0x0:
            return f"c.addi\t{_reg(rd)},{imm6}"
        if funct3 == 0x1:
            offset = _sign_extend(
                (_bits(c, 12, 12) << 11) | (_bits(c, 8, 8) << 10)
                | (_bits(c, 10, 9) << 8) | (_bits(c, 6, 6) << 7)
                | (_bits(c, 7, 7) << 6) | (_bits(c, 2, 2) << 5)
                | (_bits(c, 11, 11) << 4) | (_bits(c, 5, 3) << 1), 12)
            return f"c.jal\t{_target(address, offset)}"
        if funct3 == 0x2:
            return f"c.li\t{_reg(rd)},{imm6}"
        if funct3 == 0x3:
            if rd == 2:
                imm = _sign_extend(
                    (_bits(c, 12, 12) << 9) | (_bits(c, 4, 3) << 7)
                    | (_bits(c, 5, 5) << 6) | (_bits(c, 2, 2) << 5)
                    | (_bits(c, 6, 6) << 4), 10)
                return "" if imm == 0 else f"c.addi16sp\tsp,{imm}"
            return "" if imm6 == 0 else f"c.lui\t{_reg(rd)},0x{imm6 & 0xFFFFF:x}"
        if funct3 == 0x4:
            rsd = _creg(_bits(c, 9, 7))
            kind = _bits(c, 11, 10)
            shamt = (_bits(c, 12, 12) << 5) | _bits(c, 6, 2)
            if kind == 0x0:
                return f"c.srli\t{rsd},0x{shamt:x}"
            if kind == 0x1:
                return f"c.srai\t{rsd},0x{shamt:x}"
            if kind == 0x2:
                return f"c.andi\t{rsd},{imm6}"
            if _bits(c, 12, 12):
                # C.SUBW / C.ADDW (funct2 00, 01) are RV64; Zcb (OH-146)
                # takes 10 for C.MUL and 11 for its unary group. The Zbb
                # unaries render too -- the union again -- and since OH-208
                # the RP2350 runs them while the C5 refuses them.
                pair = _bits(c, 6, 5)
                if pair == 0x2:
                    return f"c.mul\t{rsd},{_creg(_bits(c, 4, 2))}"
                if pair == 0x3:
                    name = {0x0: "c.zext.b", 0x1: "c.sext.b", 0x2: "c.zext.h",
                            0x3: "c.sext.h", 0x5: "c.not"}.get(_bits(c, 4, 2))
                    return f"{name}\t{rsd}" if name else ""
                return ""
            rs2 = _creg(_bits(c, 4, 2))
            name = {0x0: "c.sub", 0x1: "c.xor", 0x2: "c.or", 0x3: "c.and"}[
                _bits(c, 6, 5)]
            return f"{name}\t{rsd},{rs2}"
        if funct3 == 0x5:
            offset = _sign_extend(
                (_bits(c, 12, 12) << 11) | (_bits(c, 8, 8) << 10)
                | (_bits(c, 10, 9) << 8) | (_bits(c, 6, 6) << 7)
                | (_bits(c, 7, 7) << 6) | (_bits(c, 2, 2) << 5)
                | (_bits(c, 11, 11) << 4) | (_bits(c, 5, 3) << 1), 12)
            return f"c.j\t{_target(address, offset)}"
        offset = _sign_extend(
            (_bits(c, 12, 12) << 8) | (_bits(c, 6, 5) << 6)
            | (_bits(c, 2, 2) << 5) | (_bits(c, 11, 10) << 3)
            | (_bits(c, 4, 3) << 1), 9)
        name = "c.beqz" if funct3 == 0x6 else "c.bnez"
        return f"{name}\t{_creg(_bits(c, 9, 7))},{_target(address, offset)}"

    rd, rs2 = _bits(c, 11, 7), _bits(c, 6, 2)
    if funct3 == 0x0:
        shamt = (_bits(c, 12, 12) << 5) | _bits(c, 6, 2)
        return f"c.slli\t{_reg(rd)},0x{shamt:x}"
    if funct3 == 0x2:
        if rd == 0:
            return ""
        imm = ((_bits(c, 3, 2) << 6) | (_bits(c, 12, 12) << 5)
               | (_bits(c, 6, 4) << 2))
        return f"c.lwsp\t{_reg(rd)},{imm}(sp)"
    if funct3 == 0x4:
        if _bits(c, 12, 12) == 0:
            if rs2 == 0:
                return "" if rd == 0 else f"c.jr\t{_reg(rd)}"
            return f"c.mv\t{_reg(rd)},{_reg(rs2)}"
        if rs2 == 0:
            return "c.ebreak" if rd == 0 else f"c.jalr\t{_reg(rd)}"
        return f"c.add\t{_reg(rd)},{_reg(rs2)}"
    if funct3 == 0x5:
        # Zcmp and Zcmt (OH-146), in the c.fsdsp slot no FPU-less part uses.
        kind = _bits(c, 12, 10)
        if kind == 0x0:
            index = _bits(c, 9, 2)
            return f"cm.jalt\t{index}" if index >= 32 else f"cm.jt\t{index}"
        if kind == 0x3:
            pair = _bits(c, 6, 5)
            first, second = _sreg(_bits(c, 9, 7)), _sreg(_bits(c, 4, 2))
            if pair == 0x1 and first != second:
                return f"cm.mvsa01\t{first},{second}"
            if pair == 0x3:
                return f"cm.mva01s\t{first},{second}"
            return ""
        if kind in (0x6, 0x7) and _bits(c, 8, 8) == 0:
            rlist = _bits(c, 7, 4)
            if rlist < 4:
                return ""
            count = 13 if rlist == 15 else rlist - 3
            adjust = (count * 4 + 15) // 16 * 16 + _bits(c, 3, 2) * 16
            name = {0xC: "cm.push", 0xD: "cm.pop",
                    0xE: "cm.popretz", 0xF: "cm.popret"}[_bits(c, 12, 9)]
            sign = "-" if name == "cm.push" else ""
            return f"{name}\t{_rlist_text(rlist)},{sign}{adjust}"
        return ""
    if funct3 == 0x6:
        imm = (_bits(c, 8, 7) << 6) | (_bits(c, 12, 9) << 2)
        return f"c.swsp\t{_reg(rs2)},{imm}(sp)"
    return ""


# --- the interface `webui/api.py` calls -------------------------------------


def decode(word: int, address: int = 0) -> tuple[str, int]:
    """One instruction as text, and how many bytes it occupied.

    `word` is up to four bytes read little-endian. When the low two bits are
    not both set only the low halfword is looked at, and the width is 2.

    An encoding this module does not render answers `.word` or `.short` the way
    objdump does with an undecodable one -- a listing that silently skipped it
    would misalign every line after it.
    """
    if (word & 0x3) != 0x3:
        half = word & 0xFFFF
        text = _decode16(half, address)
        # Unpadded, because that is how objdump prints an encoding it cannot
        # decode -- `0x4`, not `0x0004`. Matching it keeps the sweep a direct
        # text comparison rather than one with a formatting exception.
        return (text or f"0x{half:x}", 2)
    text = _decode32(word & 0xFFFFFFFF, address)
    return (text or f"0x{word & 0xFFFFFFFF:x}", 4)


def disassemble(data: bytes, base: int = 0) -> list[Line]:
    """Every instruction in `data`, in order, from address `base`.

    Linear rather than following branches, which is what objdump does with a
    raw binary and therefore what the comparison needs.
    """
    lines: list[Line] = []
    offset = 0
    while offset + 2 <= len(data):
        half = int.from_bytes(data[offset:offset + 2], "little")
        if (half & 3) != 3:
            text, _ = decode(half, base + offset)
            lines.append(Line(base + offset, 2, half, text))
            offset += 2
            continue
        if offset + 4 > len(data):
            break
        word = int.from_bytes(data[offset:offset + 4], "little")
        text, _ = decode(word, base + offset)
        lines.append(Line(base + offset, 4, word, text))
        offset += 4
    return lines


def disassemble_range(cpu, address: int, count: int) -> list[Line]:
    """`count` instructions from `address`, read through a CPU's memory.

    Halfword by halfword rather than a block, so a listing that runs off the
    end of a region stops there instead of failing whole -- the pane wants what
    it can show, not an exception.
    """
    lines: list[Line] = []
    at = address
    for _ in range(count):
        try:
            half = int.from_bytes(cpu.read_block(at, 2), "little")
        except Exception:  # noqa: BLE001 - any fault means "nothing more to show"
            break
        if (half & 3) != 3:
            text, _ = decode(half, at)
            lines.append(Line(at, 2, half, text))
            at += 2
            continue
        try:
            word = int.from_bytes(cpu.read_block(at, 4), "little")
        except Exception:  # noqa: BLE001 - a word at the very end of a region
            break
        text, _ = decode(word, at)
        lines.append(Line(at, 4, word, text))
        at += 4
    return lines
