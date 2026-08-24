# OpenHardware — assemble the RV32I instructions these tests run.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Hand-encode RV32I, because there is no RISC-V toolchain on this machine.

`tests/cortexm0/test_blink.py` runs a real compiled image, and that is the
stronger claim. It cannot be made here: `arm-none-eabi-gcc` is present via
PlatformIO and no RISC-V compiler is, so the choice is between hand-encoded
programs and nothing at all.

**The encoder cannot silently agree with the decoder**, which is the obvious
objection to testing a decoder with your own encoder. Every program built here
is executed by rvcpp as well, and rvcpp's decoder was written by someone else
from the same manual. A shared bug would have to be a shared misreading of the
ISA manual by two unrelated authors, which is a different and much smaller risk
than one author's typo.

Written as functions per instruction format rather than a mnemonic parser: a
parser is a program, and a program in a test fixture needs its own tests.
"""

from __future__ import annotations

#: ABI register names, in architectural order. The same table rvcpp prints
#: from, so a trace line and a program in this file name registers identically.
NAMES = (
    "x0", "ra", "sp", "gp", "tp", "t0", "t1", "t2", "s0", "s1", "a0", "a1",
    "a2", "a3", "a4", "a5", "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)

NUMBER = {name: index for index, name in enumerate(NAMES)}


class EncodeError(Exception):
    """An operand that does not fit the field it was given for."""


def _reg(register: int | str) -> int:
    if isinstance(register, str):
        if register not in NUMBER:
            raise EncodeError(f"no register named {register!r}; see NAMES")
        return NUMBER[register]
    if not 0 <= register < 32:
        raise EncodeError(f"register {register} is outside x0-x31")
    return register


def _fits_signed(value: int, bits: int, what: str) -> int:
    """Range-check an immediate and return it masked.

    Checked rather than truncated. A branch offset that silently wrapped would
    assemble into a program that jumps somewhere plausible, and the resulting
    lockstep failure would be blamed on the core.
    """
    low = -(1 << (bits - 1))
    high = (1 << (bits - 1)) - 1
    if not low <= value <= high:
        raise EncodeError(f"{what} {value} does not fit in {bits} signed bits")
    return value & ((1 << bits) - 1)


def r_type(funct7: int, rs2: int | str, rs1: int | str, funct3: int,
           rd: int | str, opcode: int) -> int:
    return ((funct7 & 0x7F) << 25 | _reg(rs2) << 20 | _reg(rs1) << 15 |
            (funct3 & 0x7) << 12 | _reg(rd) << 7 | (opcode & 0x7F))


def i_type(imm: int, rs1: int | str, funct3: int, rd: int | str,
           opcode: int) -> int:
    return (_fits_signed(imm, 12, "I-type immediate") << 20 | _reg(rs1) << 15 |
            (funct3 & 0x7) << 12 | _reg(rd) << 7 | (opcode & 0x7F))


def s_type(imm: int, rs2: int | str, rs1: int | str, funct3: int,
           opcode: int) -> int:
    value = _fits_signed(imm, 12, "S-type immediate")
    return ((value >> 5) << 25 | _reg(rs2) << 20 | _reg(rs1) << 15 |
            (funct3 & 0x7) << 12 | (value & 0x1F) << 7 | (opcode & 0x7F))


def b_type(imm: int, rs2: int | str, rs1: int | str, funct3: int,
           opcode: int) -> int:
    """Branch offsets are in halfwords, so bit 0 is not encoded at all."""
    if imm % 2 != 0:
        raise EncodeError(f"branch offset {imm} is odd; targets are halfword-aligned")
    value = _fits_signed(imm, 13, "branch offset")
    return (((value >> 12) & 0x1) << 31 | ((value >> 5) & 0x3F) << 25 |
            _reg(rs2) << 20 | _reg(rs1) << 15 | (funct3 & 0x7) << 12 |
            ((value >> 1) & 0xF) << 8 | ((value >> 11) & 0x1) << 7 |
            (opcode & 0x7F))


def u_type(imm20: int, rd: int | str, opcode: int) -> int:
    """`imm20` is the value that lands in bits 31:12, not a byte address."""
    if not 0 <= imm20 < (1 << 20):
        raise EncodeError(f"U-type immediate {imm20:#x} is not 20 bits")
    return (imm20 << 12) | _reg(rd) << 7 | (opcode & 0x7F)


def j_type(imm: int, rd: int | str, opcode: int) -> int:
    if imm % 2 != 0:
        raise EncodeError(f"jump offset {imm} is odd")
    value = _fits_signed(imm, 21, "jump offset")
    return (((value >> 20) & 0x1) << 31 | ((value >> 1) & 0x3FF) << 21 |
            ((value >> 11) & 0x1) << 20 | ((value >> 12) & 0xFF) << 12 |
            _reg(rd) << 7 | (opcode & 0x7F))


# --- the instructions these tests use ---------------------------------------
#
# Not the whole base set. Each one here is used by a program below or by a
# test; adding the rest would be a table nobody reads and nothing checks.

def lui(rd, imm20): return u_type(imm20, rd, 0x37)
def auipc(rd, imm20): return u_type(imm20, rd, 0x17)
def jal(rd, offset): return j_type(offset, rd, 0x6F)
def jalr(rd, rs1, imm=0): return i_type(imm, rs1, 0x0, rd, 0x67)

def beq(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x0, 0x63)
def bne(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x1, 0x63)
def blt(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x4, 0x63)
def bge(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x5, 0x63)
def bltu(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x6, 0x63)
def bgeu(rs1, rs2, offset): return b_type(offset, rs2, rs1, 0x7, 0x63)

def lb(rd, rs1, imm): return i_type(imm, rs1, 0x0, rd, 0x03)
def lh(rd, rs1, imm): return i_type(imm, rs1, 0x1, rd, 0x03)
def lw(rd, rs1, imm): return i_type(imm, rs1, 0x2, rd, 0x03)
def lbu(rd, rs1, imm): return i_type(imm, rs1, 0x4, rd, 0x03)
def lhu(rd, rs1, imm): return i_type(imm, rs1, 0x5, rd, 0x03)

def sb(rs2, rs1, imm): return s_type(imm, rs2, rs1, 0x0, 0x23)
def sh(rs2, rs1, imm): return s_type(imm, rs2, rs1, 0x1, 0x23)
def sw(rs2, rs1, imm): return s_type(imm, rs2, rs1, 0x2, 0x23)

def addi(rd, rs1, imm): return i_type(imm, rs1, 0x0, rd, 0x13)
def slti(rd, rs1, imm): return i_type(imm, rs1, 0x2, rd, 0x13)
def sltiu(rd, rs1, imm): return i_type(imm, rs1, 0x3, rd, 0x13)
def xori(rd, rs1, imm): return i_type(imm, rs1, 0x4, rd, 0x13)
def ori(rd, rs1, imm): return i_type(imm, rs1, 0x6, rd, 0x13)
def andi(rd, rs1, imm): return i_type(imm, rs1, 0x7, rd, 0x13)

def slli(rd, rs1, shamt): return r_type(0x00, shamt, rs1, 0x1, rd, 0x13)
def srli(rd, rs1, shamt): return r_type(0x00, shamt, rs1, 0x5, rd, 0x13)
def srai(rd, rs1, shamt): return r_type(0x20, shamt, rs1, 0x5, rd, 0x13)

def add(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x0, rd, 0x33)
def sub(rd, rs1, rs2): return r_type(0x20, rs2, rs1, 0x0, rd, 0x33)
def sll(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x1, rd, 0x33)
def slt(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x2, rd, 0x33)
def sltu(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x3, rd, 0x33)
def xor_(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x4, rd, 0x33)
def srl(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x5, rd, 0x33)
def sra(rd, rs1, rs2): return r_type(0x20, rs2, rs1, 0x5, rd, 0x33)
def or_(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x6, rd, 0x33)
def and_(rd, rs1, rs2): return r_type(0x00, rs2, rs1, 0x7, rd, 0x33)

def fence(): return i_type(0, "x0", 0x0, "x0", 0x0F)
def ecall(): return i_type(0, "x0", 0x0, "x0", 0x73)

# --- encodings this core must refuse ----------------------------------------
#
# Spelled out here so a test can name what it is refusing rather than paste a
# hex word. Each is a real, valid encoding of a real instruction -- refusing a
# malformed word proves nothing about extension gating.

def mul(rd, rs1, rs2):
    """M extension. Legal on every ESP32-C part; not implemented here yet."""
    return r_type(0x01, rs2, rs1, 0x0, rd, 0x33)


def lr_w(rd, rs1):
    """A extension. **The instruction the C3 must trap and the C6 must run.**"""
    return r_type(0x08, "x0", rs1, 0x2, rd, 0x2F)


def amoadd_w(rd, rs1, rs2):
    """A extension, and the one a compiler emits for an atomic increment."""
    return r_type(0x00, rs2, rs1, 0x2, rd, 0x2F)


def c_addi(rd, imm):
    """A 16-bit C-extension encoding, returned as a halfword rather than a word."""
    if rd == 0 or _reg(rd) == 0:
        raise EncodeError("c.addi cannot target x0")
    value = _fits_signed(imm, 6, "c.addi immediate")
    return (((value >> 5) & 0x1) << 12 | _reg(rd) << 7 |
            (value & 0x1F) << 2 | 0x1)


def image(words: list[int], offset: int = 0x40) -> bytes:
    """A flat binary rvcpp can load: `offset` bytes of padding, then the code.

    0x40 because rvcpp's testbench enters at `RAM_BASE + 0x40` and nothing
    configures that -- see `main.cpp`, which constructs `RVCore(mem, RAM_BASE +
    0x40, RAM_BASE, ram_size)`.
    """
    out = bytearray(offset)
    for word in words:
        out += int(word & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)
