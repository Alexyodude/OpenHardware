#!/usr/bin/env python3
# OpenHardware - Armv6-M Thumb, as text.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Disassemble Thumb-16 (plus the 32-bit `BL` pair) for `core/cortexm0`.

## This IS a second decoder, and that is the thing to worry about

`core/i8086/disasm.py` opens by refusing to decode: length, modrm and operands
all come from the C decoder through the ABI, because *"re-deriving any of them
here would create a second decoder that agrees with the first until it does
not, and the one that disagrees would be the one on screen."* That reasoning is
right and it does not apply here, because there is nothing to defer to --
`core/cortexm0/exec.cc` decodes inline as it executes and exposes no decoder.

So this file does re-derive, and the danger is real. What contains it is that
the check is against a **third** party: `arm-none-eabi-objdump`, which neither
this file nor `exec.cc` had any hand in. `tests/cortexm0/test_disasm.py`
compares four committed images -- real compiler output, two chips -- instruction
by instruction against it.

**The width is the part that check earns its keep on.** A wrong mnemonic is one
wrong line. A wrong *length* desynchronises every line after it, so the
comparison fails loudly and immediately rather than showing plausible garbage
half a screen down. That is the failure this file would otherwise be most
likely to hide.

## Where it differs from objdump, deliberately

Only in what it leaves out. objdump annotates: `movs r2, #144  @ 0x90`,
`ldr r3, [pc, #44]  @ (0x3c)`. Those are conveniences it computes, not part of
the instruction, and reproducing its rules for when to emit them would be an
argument about formatting rather than about decoding. The test strips them from
objdump's side and compares mnemonic and operands, which is the part where a
disagreement means somebody is wrong.

## What "unimplemented" renders as

The halfword, in hex, as `.short 0xNNNN` -- never a blank and never a guess. A
listing with a hole in it invites the reader to assume the hole is nothing,
and this core's own `StepResult::Unimplemented` exists to say the opposite.
"""

from __future__ import annotations

import dataclasses

#: Register names, indexed. `sp`, `lr` and `pc` rather than r13-r15, which is
#: how objdump spells them and how anyone reading a stack frame thinks.
REGISTERS = (
    "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
    "r8", "r9", "sl", "fp", "ip", "sp", "lr", "pc",
)

#: Condition suffixes for format 16, by the 4-bit field. 14 is "always", which
#: is encoded as an unconditional branch instead, and 15 is the SVC escape --
#: neither reaches this table.
CONDITIONS = (
    "eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
    "hi", "ls", "ge", "lt", "gt", "le",
)

#: Format 4, by its 4-bit opcode. `negs` is how objdump spells `RSBS Rd, Rn, #0`.
ALU_OPS = (
    "ands", "eors", "lsls", "lsrs", "asrs", "adcs", "sbcs", "rors",
    "tst", "negs", "cmp", "cmn", "orrs", "muls", "bics", "mvns",
)


@dataclasses.dataclass(frozen=True)
class Line:
    """One disassembled instruction."""

    address: int
    #: 2, or 4 for the `BL` pair. The field the objdump comparison protects.
    width: int
    #: The raw halfword, or the two of them packed first-then-second.
    encoding: int
    text: str

    @property
    def raw(self) -> str:
        """The encoding as objdump prints it: little-endian halfwords."""
        if self.width == 2:
            return f"{self.encoding:04x}"
        return f"{self.encoding >> 16:04x} {self.encoding & 0xFFFF:04x}"


def _reg(index: int) -> str:
    return REGISTERS[index & 0xF]


def _reglist(bits: int, extra: str | None = None) -> str:
    """`{r0, r4, lr}` -- the shape PUSH, POP, STMIA and LDMIA all print.

    Ranges are not collapsed. objdump prints `{r4, r5, lr}` rather than
    `{r4-r5, lr}` for short runs, and matching it exactly is worth more than
    being clever about it.
    """
    names = [REGISTERS[bit] for bit in range(8) if bits & (1 << bit)]
    if extra is not None:
        names.append(extra)
    return "{" + ", ".join(names) + "}"


def _target(address: int, offset: int) -> str:
    """A branch destination, absolute, as objdump prints it.

    The `+ 4` is the architecture rather than an adjustment: reading the PC
    during an instruction yields the address of that instruction plus four,
    because of a pipeline that no longer exists and an encoding that still
    assumes it.
    """
    return f"0x{(address + 4 + offset) & 0xFFFFFFFF:x}"


def _signed(value: int, bits: int) -> int:
    """Sign-extend `value` from `bits` wide."""
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def decode(encoding: int, address: int = 0, second: int | None = None) -> tuple[str, int]:
    """One instruction as `(text, width)`.

    `second` is the halfword following `encoding`, needed only to complete a
    `BL` pair. Passing None where one is needed yields the `.short` rendering
    rather than reading past the end of a buffer.
    """
    top = encoding >> 12

    # --- format 1/2: shift by immediate, add/subtract -----------------------
    if top == 0b0000 or top == 0b0001:
        if (encoding >> 11) & 0b11 != 0b11:
            op = (encoding >> 11) & 0b11
            imm = (encoding >> 6) & 0x1F
            rs, rd = (encoding >> 3) & 7, encoding & 7
            mnemonic = ("lsls", "lsrs", "asrs")[op]
            # imm5 == 0 means three different things across the three shifts,
            # and getting any of them wrong prints a plausible instruction that
            # is not the one encoded.
            #
            #  * LSL #0 is not a shift at all -- it *is* the `MOV (register)`
            #    encoding, which is why Armv6-M has no separate one and why
            #    objdump prints `movs`. Rendering it as `lsls Rd, Rs, #0` is
            #    the mistake this branch exists to avoid.
            #  * LSR #0 and ASR #0 mean 32, per `Shift_C` in DDI0419 -- the
            #    same rule `core/cortexm0/shift.cc` implements.
            if op == 0 and imm == 0:
                return f"movs\t{_reg(rd)}, {_reg(rs)}", 2
            if op != 0 and imm == 0:
                imm = 32
            return f"{mnemonic}\t{_reg(rd)}, {_reg(rs)}, #{imm}", 2
        immediate = (encoding >> 10) & 1
        subtract = (encoding >> 9) & 1
        operand = (encoding >> 6) & 7
        rs, rd = (encoding >> 3) & 7, encoding & 7
        mnemonic = "subs" if subtract else "adds"
        if immediate:
            return f"{mnemonic}\t{_reg(rd)}, {_reg(rs)}, #{operand}", 2
        return f"{mnemonic}\t{_reg(rd)}, {_reg(rs)}, {_reg(operand)}", 2

    # --- format 3: move/compare/add/subtract immediate ----------------------
    if top in (0b0010, 0b0011):
        op = (encoding >> 11) & 0b11
        rd = (encoding >> 8) & 7
        imm = encoding & 0xFF
        mnemonic = ("movs", "cmp", "adds", "subs")[op]
        return f"{mnemonic}\t{_reg(rd)}, #{imm}", 2

    if top == 0b0100:
        # --- format 4: ALU operations ---------------------------------------
        if (encoding >> 10) & 0b111111 == 0b010000:
            op = (encoding >> 6) & 0xF
            rs, rd = (encoding >> 3) & 7, encoding & 7
            return f"{ALU_OPS[op]}\t{_reg(rd)}, {_reg(rs)}", 2

        # --- format 5: high registers and branch-exchange --------------------
        if (encoding >> 10) & 0b111111 == 0b010001:
            op = (encoding >> 8) & 0b11
            rs = ((encoding >> 6) & 1) << 3 | ((encoding >> 3) & 7)
            rd = ((encoding >> 7) & 1) << 3 | (encoding & 7)
            if op == 0b11:
                # BLX is the H1 == 1 half, and Armv6-M has it. **The low three
                # bits must be zero**; nonzero is UNPREDICTABLE, and accepting
                # it printed `blx r0` for 96 encodings that encode no such
                # thing. objdump reads those as Armv8-M's `bxns`/`blxns`, a
                # wider architecture than this core has.
                if encoding & 0b111:
                    return f".short\t0x{encoding:04x}", 2
                return (f"{'blx' if (encoding >> 7) & 1 else 'bx'}\t{_reg(rs)}", 2)
            # `mov r8, r8` is the traditional Thumb no-op, and objdump prints
            # it as `nop`. Armv6-M also has a real one at 0xbf00; both exist.
            if encoding == 0x46C0:
                return "nop", 2
            return f"{('add', 'cmp', 'mov')[op]}\t{_reg(rd)}, {_reg(rs)}", 2

        # --- format 6: PC-relative load --------------------------------------
        rd = (encoding >> 8) & 7
        offset = (encoding & 0xFF) * 4
        return f"ldr\t{_reg(rd)}, [pc, #{offset}]", 2

    # --- formats 7 and 8: load/store with a register offset -----------------
    if top == 0b0101:
        ro, rb, rd = (encoding >> 6) & 7, (encoding >> 3) & 7, encoding & 7
        if (encoding >> 9) & 1:
            mnemonic = ("strh", "ldrsb", "ldrh", "ldrsh")[(encoding >> 10) & 0b11]
        else:
            mnemonic = ("str", "strb", "ldr", "ldrb")[(encoding >> 10) & 0b11]
        return f"{mnemonic}\t{_reg(rd)}, [{_reg(rb)}, {_reg(ro)}]", 2

    # --- format 9: load/store with a 5-bit immediate -------------------------
    if top in (0b0110, 0b0111):
        byte = (encoding >> 12) & 1
        load = (encoding >> 11) & 1
        imm = (encoding >> 6) & 0x1F
        rb, rd = (encoding >> 3) & 7, encoding & 7
        mnemonic = ("str", "ldr", "strb", "ldrb")[byte * 2 + load]
        # A byte access scales by 1, a word access by 4.
        scale = 1 if byte else 4
        return f"{mnemonic}\t{_reg(rd)}, [{_reg(rb)}, #{imm * scale}]", 2

    # --- format 10: load/store halfword --------------------------------------
    if top == 0b1000:
        load = (encoding >> 11) & 1
        imm = ((encoding >> 6) & 0x1F) * 2
        rb, rd = (encoding >> 3) & 7, encoding & 7
        return f"{'ldrh' if load else 'strh'}\t{_reg(rd)}, [{_reg(rb)}, #{imm}]", 2

    # --- format 11: SP-relative load/store -----------------------------------
    if top == 0b1001:
        load = (encoding >> 11) & 1
        rd = (encoding >> 8) & 7
        imm = (encoding & 0xFF) * 4
        return f"{'ldr' if load else 'str'}\t{_reg(rd)}, [sp, #{imm}]", 2

    # --- format 12: load address ---------------------------------------------
    if top == 0b1010:
        from_sp = (encoding >> 11) & 1
        rd = (encoding >> 8) & 7
        imm = (encoding & 0xFF) * 4
        base = "sp" if from_sp else "pc"
        return f"add\t{_reg(rd)}, {base}, #{imm}", 2

    if top == 0b1011:
        # --- format 13: adjust the stack pointer ------------------------------
        if (encoding >> 8) & 0xFF == 0b10110000:
            imm = (encoding & 0x7F) * 4
            return f"{'sub' if (encoding >> 7) & 1 else 'add'}\tsp, #{imm}", 2

        # --- format 14: push/pop ----------------------------------------------
        if (encoding >> 9) & 0b111 == 0b010:
            load = (encoding >> 11) & 1
            extra = ((encoding >> 8) & 1) and ("pc" if load else "lr")
            mnemonic = "pop" if load else "push"
            return f"{mnemonic}\t{_reglist(encoding & 0xFF, extra or None)}", 2

        # --- Armv6-M: sign- and zero-extend ------------------------------------
        if (encoding >> 8) & 0xFF == 0b10110010:
            rs, rd = (encoding >> 3) & 7, encoding & 7
            mnemonic = ("sxth", "sxtb", "uxth", "uxtb")[(encoding >> 6) & 0b11]
            return f"{mnemonic}\t{_reg(rd)}, {_reg(rs)}", 2

        # --- Armv6-M: byte-reverse ---------------------------------------------
        if (encoding >> 8) & 0xFF == 0b10111010:
            op = (encoding >> 6) & 0b11
            # 00 rev, 01 rev16, 11 revsh -- and **10 is not a byte-reverse at
            # all**. This table read `rev, "", rev16, revsh` with its gap at
            # 01, so it printed `rev16` for 64 encodings Armv6-M leaves
            # undefined, and for none of the ones that mean it. No committed
            # image contains a byte-reverse, so only the exhaustive sweep
            # against objdump could find this.
            if op != 0b10:
                rs, rd = (encoding >> 3) & 7, encoding & 7
                return f"{('rev', 'rev16', '', 'revsh')[op]}\t{_reg(rd)}, {_reg(rs)}", 2

        # --- Armv6-M: change processor state -----------------------------------
        # Exactly CPSIE i and CPSID i. The mask was
        # `(encoding >> 5) & 0x7FF == 0b10110110011`, which claimed the whole
        # of 0xb660-0xb67f -- sixteen encodings for the two instructions
        # Armv6-M actually defines.
        if encoding in (0xB662, 0xB672):
            return f"cps{'id' if encoding & 0x10 else 'ie'}\ti", 2

        # --- Armv6-M: breakpoint ------------------------------------------------
        if (encoding >> 8) & 0xFF == 0b10111110:
            return f"bkpt\t0x{encoding & 0xFF:04x}", 2

        # --- Armv6-M: the hint space --------------------------------------------
        if (encoding >> 8) & 0xFF == 0b10111111 and encoding & 0xF == 0:
            hint = (encoding >> 4) & 0xF
            if hint < 5:
                return ("nop", "yield", "wfe", "wfi", "sev")[hint], 2

    # --- format 15: multiple load/store ---------------------------------------
    if top == 0b1100:
        load = (encoding >> 11) & 1
        rb = (encoding >> 8) & 7
        # objdump writes the write-back `!` on STMIA always, and on LDMIA only
        # when the base is not itself in the list -- because that is when the
        # architecture writes it back.
        bang = "" if load and (encoding & (1 << rb)) else "!"
        mnemonic = "ldmia" if load else "stmia"
        return f"{mnemonic}\t{_reg(rb)}{bang}, {_reglist(encoding & 0xFF)}", 2

    if top == 0b1101:
        condition = (encoding >> 8) & 0xF
        # --- format 17: supervisor call ---------------------------------------
        if condition == 0b1111:
            # Decimal, which is how objdump prints it.
            return f"svc\t{encoding & 0xFF}", 2
        if condition == 0b1110:
            # Permanently UNDEFINED, and objdump says so rather than inventing
            # a branch that never executes.
            return f"udf\t#{encoding & 0xFF}", 2
        # --- format 16: conditional branch -------------------------------------
        offset = _signed(encoding & 0xFF, 8) * 2
        return f"b{CONDITIONS[condition]}.n\t{_target(address, offset)}", 2

    # --- format 18: unconditional branch ---------------------------------------
    if top == 0b1110 and not (encoding >> 11) & 1:
        offset = _signed(encoding & 0x7FF, 11) * 2
        return f"b.n\t{_target(address, offset)}", 2

    # --- format 19: the long branch with link ------------------------------------
    if (encoding >> 11) & 0b11111 == 0b11110:
        if second is None or (second >> 11) & 0b11111 not in (0b11111, 0b11101):
            return f".short\t0x{encoding:04x}", 2
        high = _signed(encoding & 0x7FF, 11)
        low = second & 0x7FF
        offset = (high << 12) | (low << 1)
        blx = (second >> 11) & 0b11111 == 0b11101
        return f"{'blx' if blx else 'bl'}\t{_target(address, offset)}", 4

    return f".short\t0x{encoding:04x}", 2


def disassemble(data: bytes, base: int = 0) -> list[Line]:
    """Every instruction in `data`, in order, starting at address `base`.

    Linear rather than following branches, which is what objdump does with a
    raw binary and therefore what the comparison needs. It also means a data
    word inside the code is decoded as an instruction -- true of every linear
    disassembler and the reason a listing shows `.short` at all.
    """
    lines: list[Line] = []
    offset = 0
    while offset + 2 <= len(data):
        encoding = int.from_bytes(data[offset:offset + 2], "little")
        second = (
            int.from_bytes(data[offset + 2:offset + 4], "little")
            if offset + 4 <= len(data) else None
        )
        text, width = decode(encoding, base + offset, second)
        packed = encoding if width == 2 else (encoding << 16) | (second or 0)
        lines.append(Line(base + offset, width, packed, text))
        offset += width
    return lines


def disassemble_range(cpu, address: int, count: int) -> list[Line]:
    """`count` instructions from `address`, read through a CPU's memory.

    Reads halfword by halfword rather than a block, so a listing that runs off
    the end of a region stops there instead of failing whole -- the pane wants
    what it can show, not an exception.
    """
    lines: list[Line] = []
    at = address
    for _ in range(count):
        try:
            first = int.from_bytes(cpu.read_block(at, 2), "little")
        except Exception:  # noqa: BLE001 - any fault means "nothing more to show"
            break
        try:
            second = int.from_bytes(cpu.read_block(at + 2, 2), "little")
        except Exception:  # noqa: BLE001 - a pair at the very end of a region
            second = None
        text, width = decode(first, at, second)
        packed = first if width == 2 else (first << 16) | (second or 0)
        lines.append(Line(at, width, packed, text))
        at += width
    return lines
