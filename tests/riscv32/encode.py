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

# Zba address generation. funct7 0b0010000 with funct3 010, 100 and 110, taken
# from rvcpp's own encoding table so the two models cannot disagree about the
# bits before they disagree about the answer:
# `RVOPC_SH1ADD_BITS = 0b0010000_00000_00000_010_00000_0110011`
# (third_party/hazard3/test/sim/rvcpp/include/encoding/rv_opcodes.h:149).
def sh1add(rd, rs1, rs2): return r_type(0x10, rs2, rs1, 0x2, rd, 0x33)
def sh2add(rd, rs1, rs2): return r_type(0x10, rs2, rs1, 0x4, rd, 0x33)
def sh3add(rd, rs1, rs2): return r_type(0x10, rs2, rs1, 0x6, rd, 0x33)

# Zbs single-bit. Three funct7 values, and the funct3 does half the deciding:
# set, clear and invert share 001 while extract is 101 and exists under 0x24
# only. Taken from rvcpp's table so the bits are not from memory --
# `RVOPC_BSET_BITS = 0b0010100_00000_00000_001_00000_0110011`
# (third_party/hazard3/test/sim/rvcpp/include/encoding/rv_opcodes.h:...).
#
# The immediate forms are the same funct7 and funct3 over opcode 0b0010011,
# with the shift-amount field where rs2 sits -- which is why they are built
# with r_type rather than i_type, exactly as slli and srai above are.
def bset(rd, rs1, rs2): return r_type(0x14, rs2, rs1, 0x1, rd, 0x33)
def bclr(rd, rs1, rs2): return r_type(0x24, rs2, rs1, 0x1, rd, 0x33)
def bext(rd, rs1, rs2): return r_type(0x24, rs2, rs1, 0x5, rd, 0x33)
def binv(rd, rs1, rs2): return r_type(0x34, rs2, rs1, 0x1, rd, 0x33)

def bseti(rd, rs1, shamt): return r_type(0x14, shamt, rs1, 0x1, rd, 0x13)
def bclri(rd, rs1, shamt): return r_type(0x24, shamt, rs1, 0x1, rd, 0x13)
def bexti(rd, rs1, shamt): return r_type(0x24, shamt, rs1, 0x5, rd, 0x13)
def binvi(rd, rs1, shamt): return r_type(0x34, shamt, rs1, 0x1, rd, 0x13)

# Zbb and Zbkb (OH-208), the RP2350's last two groups. Bits from rvcpp's own
# table, `third_party/hazard3/test/sim/rvcpp/include/encoding/
# rv_opcodes.h:157-230` -- e.g. `RVOPC_CLZ_BITS =
# 0b0110000_00000_00000_001_00000_0010011` -- and every helper here is held
# to its own mnemonic through `core/riscv32/disasm.py`, which is swept
# against GNU objdump 2.43 (test_zbb_zbkb.py, test_disasm.py).
#
# The register forms are ordinary R-type. The one-operand forms are not:
# their rs2 field is the rest of the operation's name, so it is passed as a
# number -- clz is 0, ctz 1, cpop 2, sext.b 4, sext.h 5 under funct7
# 0b0110000; zip and unzip 0b01111 under 0b0000100.
def andn(rd, rs1, rs2): return r_type(0x20, rs2, rs1, 0x7, rd, 0x33)
def orn(rd, rs1, rs2): return r_type(0x20, rs2, rs1, 0x6, rd, 0x33)
def xnor(rd, rs1, rs2): return r_type(0x20, rs2, rs1, 0x4, rd, 0x33)
def min_(rd, rs1, rs2): return r_type(0x05, rs2, rs1, 0x4, rd, 0x33)
def minu(rd, rs1, rs2): return r_type(0x05, rs2, rs1, 0x5, rd, 0x33)
def max_(rd, rs1, rs2): return r_type(0x05, rs2, rs1, 0x6, rd, 0x33)
def maxu(rd, rs1, rs2): return r_type(0x05, rs2, rs1, 0x7, rd, 0x33)
def rol(rd, rs1, rs2): return r_type(0x30, rs2, rs1, 0x1, rd, 0x33)
def ror(rd, rs1, rs2): return r_type(0x30, rs2, rs1, 0x5, rd, 0x33)
def pack(rd, rs1, rs2): return r_type(0x04, rs2, rs1, 0x4, rd, 0x33)
def packh(rd, rs1, rs2): return r_type(0x04, rs2, rs1, 0x7, rd, 0x33)
def zext_h(rd, rs1): return r_type(0x04, "x0", rs1, 0x4, rd, 0x33)

def clz(rd, rs1): return r_type(0x30, 0x00, rs1, 0x1, rd, 0x13)
def ctz(rd, rs1): return r_type(0x30, 0x01, rs1, 0x1, rd, 0x13)
def cpop(rd, rs1): return r_type(0x30, 0x02, rs1, 0x1, rd, 0x13)
def sext_b(rd, rs1): return r_type(0x30, 0x04, rs1, 0x1, rd, 0x13)
def sext_h(rd, rs1): return r_type(0x30, 0x05, rs1, 0x1, rd, 0x13)
def zip_(rd, rs1): return r_type(0x04, 0x0F, rs1, 0x1, rd, 0x13)
def unzip(rd, rs1): return r_type(0x04, 0x0F, rs1, 0x5, rd, 0x13)
def orc_b(rd, rs1): return r_type(0x14, 0x07, rs1, 0x5, rd, 0x13)
def rev8(rd, rs1): return r_type(0x34, 0x18, rs1, 0x5, rd, 0x13)
def brev8(rd, rs1): return r_type(0x34, 0x07, rs1, 0x5, rd, 0x13)
def rori(rd, rs1, shamt): return r_type(0x30, shamt, rs1, 0x5, rd, 0x13)


def clmul(rd, rs1, rs2):
    """Zbc, **which no part here has** -- not in the RP2350's string -- and
    which shares funct7 0b0000101 with Zbb's min and max. rvcpp executes it
    for every part (`rv_core.cpp:289`), which is what makes it the encoding
    to reach for when a test wants the oracle to run what this core
    refuses."""
    return r_type(0x05, rs2, rs1, 0x1, rd, 0x33)


def _zbb_unary_c(rd, select: int) -> int:
    """Zcb's quadrant-1 unary slot, `100 111 rd' 11 select 01`."""
    number = _reg(rd)
    if not 8 <= number <= 15:
        raise EncodeError(f"a compressed unary names x8-x15, not x{number}")
    return 0x9C61 | ((number - 8) << 7) | (select << 2)


def c_sext_b(rd): return _zbb_unary_c(rd, 0x1)
def c_zext_h(rd): return _zbb_unary_c(rd, 0x2)
def c_sext_h(rd): return _zbb_unary_c(rd, 0x3)


# Xh3bextm, the Hazard3's own (OH-219), from the field tables in
# `third_party/hazard3/doc/sections/custom_extensions.adoc`: custom-0, opcode
# 0x0b; funct3 000 for h3.bextm and 100 for h3.bextmi; `size` in bits 28:26,
# the mask's width less one; bits 31:29 and 25 RES0. The shift amount is rs2
# in one and the five-bit field where rs2 sits in the other.
def _h3_size(nbits: int) -> int:
    if not 1 <= nbits <= 8:
        raise EncodeError(f"h3.bextm extracts 1 to 8 bits, not {nbits}")
    return (nbits - 1) << 26


def h3_bextm(rd, rs1, rs2, nbits):
    return _h3_size(nbits) | r_type(0x00, rs2, rs1, 0x0, rd, 0x0B)


def h3_bextmi(rd, rs1, shamt, nbits):
    if not 0 <= shamt < 32:
        raise EncodeError(f"h3.bextmi shifts by 0 to 31, not {shamt}")
    return _h3_size(nbits) | r_type(0x00, shamt, rs1, 0x4, rd, 0x0B)


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

def fence_i():
    """Zifencei. **Unimplemented here on every part**, and it has no bit in
    `Extension` because no board has needed one -- so this core has not decided
    about it, which is different from a part refusing it.

    Useful precisely because of that: it touches no memory, needs no operands,
    and rvcpp treats it as a no-op, so it is the cheapest encoding that this
    core stops on and the oracle runs straight through."""
    return i_type(0, "x0", 0x1, "x0", 0x0F)

# --- encodings this core must refuse ----------------------------------------
#
# Spelled out here so a test can name what it is refusing rather than paste a
# hex word. Each is a real, valid encoding of a real instruction -- refusing a
# malformed word proves nothing about extension gating.

def mul(rd, rs1, rs2):
    """M extension. Legal on every ESP32-C part, and implemented since OH-55 --
    so this is no longer an encoding to reach for when a test wants one this
    core refuses. `fence_i` and the atomics are."""
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
