# OpenHardware - render decoded 8086 instructions as text.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Turn what `Cpu.decode` returns into assembly, for ticket OH-7.

## This does not decode

Length, modrm, displacement, immediate and effective address all come from the
C decoder through the ABI. Re-deriving any of them here would create a second
decoder that agrees with the first until it does not, and the one that
disagrees would be the one on screen.

So this file holds exactly one thing the core does not: **names**. The core
has never needed to know that `0x74` is called `je`, and giving it a string
table would be 256 entries of pure presentation compiled into a library whose
job is arithmetic.

## Where the names come from

The mnemonics are the ones the SST8088 corpus uses, not Intel's, wherever the
two differ -- `setmo` rather than nothing at all for the shift group's `/6`,
`salc` for `0xD6`. The corpus is what this project checks itself against, so
matching its vocabulary means a failing case and a disassembly listing say the
same word about the same instruction.

## Unknown instructions

Nothing is guessed. An opcode with no name renders as `db <hex>`, which is what
a disassembler should say about a byte it cannot explain, and is visibly
different from a plausible-looking wrong answer.
"""

from __future__ import annotations

import dataclasses

from core.i8086 import abi

#: The word registers, in modrm encoding order.
WORD_REGISTERS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
#: The byte registers. A different order, and mixing the two up produces a
#: listing that is wrong in a way that reads perfectly.
BYTE_REGISTERS = ("al", "cl", "dl", "bl", "ah", "ch", "dh", "bh")
#: Segment registers as the modrm reg field numbers them.
SEGMENT_REGISTERS = ("es", "cs", "ss", "ds")

#: The eight ALU operations, indexed by opcode bits 5:3.
ALU_NAMES = ("add", "or", "adc", "sbb", "and", "sub", "xor", "cmp")

#: The sixteen conditions, indexed by the low nibble of a Jcc opcode.
CONDITIONS = ("jo", "jno", "jb", "jnb", "jz", "jnz", "jbe", "ja",
              "js", "jns", "jp", "jnp", "jl", "jnl", "jle", "jnle")

#: The shift group, by modrm reg. `/6` is SETMO, which Intel does not list.
SHIFT_NAMES = ("rol", "ror", "rcl", "rcr", "shl", "shr", "setmo", "sar")

#: Group 3, by modrm reg. `/1` is an undocumented second encoding of TEST.
GROUP3_NAMES = ("test", "test", "not", "neg", "mul", "imul", "div", "idiv")

#: Group 5, by modrm reg. `/7` does not exist.
GROUP5_NAMES = ("inc", "dec", "call", "call far", "jmp", "jmp far", "push", None)

#: The base-plus-index part of each addressing mode, by modrm rm.
ADDRESSING = ("bx+si", "bx+di", "bp+si", "bp+di", "si", "di", "bp", "bx")

#: Opcodes whose whole text is fixed.
SIMPLE = {
    0x27: "daa", 0x2F: "das", 0x37: "aaa", 0x3F: "aas",
    0x90: "nop", 0x98: "cbw", 0x99: "cwd", 0x9B: "wait",
    0x9C: "pushf", 0x9D: "popf", 0x9E: "sahf", 0x9F: "lahf",
    0xA4: "movsb", 0xA5: "movsw", 0xA6: "cmpsb", 0xA7: "cmpsw",
    0xAA: "stosb", 0xAB: "stosw", 0xAC: "lodsb", 0xAD: "lodsw",
    0xAE: "scasb", 0xAF: "scasw",
    0xC1: "ret", 0xC3: "ret", 0xC9: "retf", 0xCB: "retf",
    0xCC: "int3", 0xCE: "into", 0xCF: "iret",
    0xD6: "salc", 0xD7: "xlat",
    0xF4: "hlt", 0xF5: "cmc", 0xF8: "clc", 0xF9: "stc",
    0xFA: "cli", 0xFB: "sti", 0xFC: "cld", 0xFD: "std",
}


@dataclasses.dataclass(frozen=True)
class Line:
    """One disassembled instruction."""

    cs: int
    ip: int
    length: int
    text: str
    raw: bytes

    @property
    def address(self) -> int:
        """The physical address, for a memory view to line up against."""
        return abi.physical(self.cs, self.ip)

    @property
    def hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.raw)


def _hex(value: int, width: int = 0) -> str:
    """Assembly-style hex: a leading zero when it would start with a letter.

    `0A2h`, not `A2h`. Every assembler needs it to tell a number from a label,
    and a listing that omits it is one nobody can paste back.
    """
    text = f"{value:0{width}X}"
    return (text if text[0].isdigit() else "0" + text) + "h"


def _signed(value: int) -> str:
    return f"+{_hex(value)}" if value >= 0 else f"-{_hex(-value)}"


def register(index: int, wide: bool) -> str:
    return WORD_REGISTERS[index & 7] if wide else BYTE_REGISTERS[index & 7]


def memory(decoded: abi.Decoded, size: str | None = None) -> str:
    """The `[bx+si+1234h]` half of an operand, with any override applied."""
    if decoded.mod == 0 and decoded.rm == 6:
        inside = _hex(decoded.displacement & 0xFFFF, 4)
    else:
        inside = ADDRESSING[decoded.rm]
        if decoded.mod in (1, 2) and decoded.displacement:
            inside += _signed(decoded.displacement)
    override = decoded.override_name
    prefix = f"{override}:" if override else ""
    return f"{size + ' ' if size else ''}{prefix}[{inside}]"


def rm(decoded: abi.Decoded, wide: bool, size: str | None = None) -> str:
    """The r/m operand: a register when mod is 3, memory otherwise.

    `size` is only wanted when nothing else in the instruction implies a
    width -- `inc byte [bx]` needs it and `mov [bx], al` does not.
    """
    if decoded.mod == 3:
        return register(decoded.rm, wide)
    return memory(decoded, size)


def _size_word(wide: bool) -> str:
    return "word" if wide else "byte"


def _alu_group(decoded: abi.Decoded) -> str | None:
    """0x00-0x3F, which is eight operations in six forms."""
    opcode = decoded.opcode
    name = ALU_NAMES[(opcode >> 3) & 7]
    form = opcode & 7
    wide = bool(decoded.wide)
    if form <= 3:
        left = rm(decoded, wide) if form in (0, 1) else register(decoded.reg, wide)
        right = register(decoded.reg, wide) if form in (0, 1) else rm(decoded, wide)
        return f"{name} {left}, {right}"
    if form == 4:
        return f"{name} al, {_hex(decoded.immediate & 0xFF, 2)}"
    if form == 5:
        return f"{name} ax, {_hex(decoded.immediate & 0xFFFF, 4)}"
    # Forms 6 and 7 are not ALU operations; the caller handles them.
    return None


def _text(decoded: abi.Decoded) -> str:
    """The instruction, without any repeat prefix."""
    opcode = decoded.opcode
    wide = bool(decoded.wide)

    if opcode in SIMPLE:
        return SIMPLE[opcode]

    if opcode < 0x20 and (opcode & 7) >= 6:
        verb = "push" if (opcode & 1) == 0 else "pop"
        return f"{verb} {SEGMENT_REGISTERS[(opcode >> 3) & 3]}"

    if opcode < 0x40 and (opcode & 7) <= 5:
        rendered = _alu_group(decoded)
        if rendered is not None:
            return rendered

    if 0x40 <= opcode <= 0x4F:
        verb = "inc" if opcode < 0x48 else "dec"
        return f"{verb} {WORD_REGISTERS[opcode & 7]}"
    if 0x50 <= opcode <= 0x5F:
        verb = "push" if opcode < 0x58 else "pop"
        return f"{verb} {WORD_REGISTERS[opcode & 7]}"
    if 0x60 <= opcode <= 0x7F:
        return f"{CONDITIONS[opcode & 0x0F]} {_hex(decoded.immediate & 0xFFFF, 4)}"
    if 0x80 <= opcode <= 0x83:
        name = ALU_NAMES[decoded.reg]
        value = decoded.immediate & (0xFFFF if wide else 0xFF)
        return f"{name} {rm(decoded, wide, _size_word(wide))}, {_hex(value, 4 if wide else 2)}"
    if opcode in (0x84, 0x85):
        return f"test {rm(decoded, wide)}, {register(decoded.reg, wide)}"
    if opcode in (0x86, 0x87):
        return f"xchg {rm(decoded, wide)}, {register(decoded.reg, wide)}"
    if 0x88 <= opcode <= 0x8B:
        left = rm(decoded, wide) if opcode < 0x8A else register(decoded.reg, wide)
        right = register(decoded.reg, wide) if opcode < 0x8A else rm(decoded, wide)
        return f"mov {left}, {right}"
    if opcode == 0x8C:
        return f"mov {rm(decoded, True)}, {SEGMENT_REGISTERS[decoded.reg & 3]}"
    if opcode == 0x8D:
        return f"lea {WORD_REGISTERS[decoded.reg]}, {memory(decoded)}"
    if opcode == 0x8E:
        return f"mov {SEGMENT_REGISTERS[decoded.reg & 3]}, {rm(decoded, True)}"
    if opcode == 0x8F:
        return f"pop {rm(decoded, True, 'word')}"
    if 0x91 <= opcode <= 0x97:
        return f"xchg ax, {WORD_REGISTERS[opcode & 7]}"
    if opcode in (0x9A, 0xEA):
        verb = "call" if opcode == 0x9A else "jmp"
        return (f"{verb} far {_hex(decoded.displacement & 0xFFFF, 4)}:"
                f"{_hex(decoded.immediate & 0xFFFF, 4)}")
    if 0xA0 <= opcode <= 0xA3:
        override = decoded.override_name
        where = f"{override}:" if override else ""
        where += f"[{_hex(decoded.displacement & 0xFFFF, 4)}]"
        accumulator = "ax" if wide else "al"
        return (f"mov {accumulator}, {where}" if opcode < 0xA2
                else f"mov {where}, {accumulator}")
    if opcode in (0xA8, 0xA9):
        value = decoded.immediate & (0xFFFF if wide else 0xFF)
        return f"test {'ax' if wide else 'al'}, {_hex(value, 4 if wide else 2)}"
    if 0xB0 <= opcode <= 0xBF:
        value = decoded.immediate & (0xFFFF if wide else 0xFF)
        return (f"mov {register(decoded.reg_in_opcode, wide)}, "
                f"{_hex(value, 4 if wide else 2)}")
    if opcode in (0xC0, 0xC2):
        return f"ret {_hex(decoded.immediate & 0xFFFF, 4)}"
    if opcode in (0xC8, 0xCA):
        return f"retf {_hex(decoded.immediate & 0xFFFF, 4)}"
    if opcode in (0xC4, 0xC5):
        return f"{'les' if opcode == 0xC4 else 'lds'} {WORD_REGISTERS[decoded.reg]}, {memory(decoded)}"
    if opcode in (0xC6, 0xC7):
        value = decoded.immediate & (0xFFFF if wide else 0xFF)
        return f"mov {rm(decoded, wide, _size_word(wide))}, {_hex(value, 4 if wide else 2)}"
    if opcode == 0xCD:
        return f"int {_hex(decoded.immediate & 0xFF, 2)}"
    if 0xD0 <= opcode <= 0xD3:
        count = "1" if opcode < 0xD2 else "cl"
        return f"{SHIFT_NAMES[decoded.reg]} {rm(decoded, wide, _size_word(wide))}, {count}"
    if opcode in (0xD4, 0xD5):
        return f"{'aam' if opcode == 0xD4 else 'aad'} {_hex(decoded.immediate & 0xFF, 2)}"
    if 0xD8 <= opcode <= 0xDF:
        return f"esc {_hex(opcode & 7, 2)}, {rm(decoded, False)}"
    if 0xE0 <= opcode <= 0xE3:
        name = ("loopnz", "loopz", "loop", "jcxz")[opcode & 3]
        return f"{name} {_hex(decoded.immediate & 0xFFFF, 4)}"
    if opcode in (0xE4, 0xE5):
        return f"in {'ax' if wide else 'al'}, {_hex(decoded.immediate & 0xFF, 2)}"
    if opcode in (0xE6, 0xE7):
        return f"out {_hex(decoded.immediate & 0xFF, 2)}, {'ax' if wide else 'al'}"
    if opcode in (0xEC, 0xED):
        return f"in {'ax' if wide else 'al'}, dx"
    if opcode in (0xEE, 0xEF):
        return f"out dx, {'ax' if wide else 'al'}"
    if opcode in (0xE8, 0xE9, 0xEB):
        verb = "call" if opcode == 0xE8 else "jmp"
        return f"{verb} {_hex(decoded.immediate & 0xFFFF, 4)}"
    if opcode in (0xF6, 0xF7):
        name = GROUP3_NAMES[decoded.reg]
        operand = rm(decoded, wide, _size_word(wide))
        if decoded.reg <= 1:
            value = decoded.immediate & (0xFFFF if wide else 0xFF)
            return f"{name} {operand}, {_hex(value, 4 if wide else 2)}"
        return f"{name} {operand}"
    if opcode == 0xFE:
        return f"{('inc', 'dec')[decoded.reg & 1]} {rm(decoded, False, 'byte')}"
    if opcode == 0xFF:
        name = GROUP5_NAMES[decoded.reg]
        if name is None:
            return f"db {_hex(opcode, 2)}"
        return f"{name} {rm(decoded, True, 'word')}"

    return f"db {_hex(opcode, 2)}"


def disassemble(cpu: abi.Cpu, cs: int | None = None, ip: int | None = None) -> Line:
    """One instruction at cs:ip, or at CS:IP when neither is given."""
    where_cs = cpu.regs.cs if cs is None else cs
    where_ip = cpu.regs.ip if ip is None else ip
    decoded = cpu.decode(where_cs, where_ip)

    raw = bytes(
        cpu.read_byte(abi.physical(where_cs, (where_ip + n) & 0xFFFF))
        for n in range(max(decoded.length, 1))
    )
    if not decoded.valid:
        # The decoder refused: too many prefixes and no opcode ever reached.
        # Say so rather than naming whatever byte it stopped on.
        return Line(where_cs, where_ip, 1, f"db {_hex(raw[0], 2)}", raw[:1])

    text = _text(decoded)
    if decoded.repeat and 0xA4 <= decoded.opcode <= 0xAF:
        # The prefix is only shown where it does something. On anything else
        # the part accepts it and ignores it, and printing `rep mov ax, bx`
        # would suggest otherwise.
        compares = (decoded.opcode & 0xFE) in (0xA6, 0xAE)
        text = f"{decoded.repeat_name if compares else 'rep'} {text}"

    # A relative branch is far more useful as its destination than as its
    # displacement -- the displacement is the one number a reader cannot use.
    if decoded.form in (abi.FORM_REL8, abi.FORM_REL16) and decoded.opcode != 0xCD:
        target = (where_ip + decoded.length + decoded.immediate) & 0xFFFF
        text = text.rsplit(" ", 1)[0] + " " + _hex(target, 4)

    return Line(where_cs, where_ip, decoded.length, text, raw)


def disassemble_range(cpu: abi.Cpu, cs: int, ip: int, count: int) -> list[Line]:
    """`count` instructions from cs:ip, following each one's length.

    Disassembly is not seekable: where the next instruction starts depends on
    how long this one is, so a listing can only be built forwards from a known
    starting point. A view that scrolls has to remember where it began.
    """
    lines: list[Line] = []
    offset = ip
    for _ in range(count):
        line = disassemble(cpu, cs, offset)
        lines.append(line)
        offset = (offset + max(line.length, 1)) & 0xFFFF
    return lines
