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

A *wide* encoding this file cannot name renders as `.word 0xNNNNNNNN` and keeps
**width 4**, which matters more than the text does: see `is_wide`.

## Two profiles, and the only thing that really separates them

`Profile.V6M` is what an RP2040 and a SAMD21 speak. `Profile.V7EM` is what an
nRF52840's Cortex-M4 speaks, and Armv7E-M is a strict superset -- every
Thumb-16 encoding below means the same thing on both, which is why this is one
file with a gate rather than two files that drift.

**What is not shared is how long an instruction is**, and that is upstream of
everything else. On Armv6-M exactly one encoding is 32 bits wide (`BL`), so the
rule is `(hw & 0xF800) == 0xF000`. On Armv7-M three prefixes are wide, and the
same halfword `0xE8B0` that is an undefined 16-bit encoding on one part is the
first half of `ldmia.w` on the other. Get that wrong and every line after it is
garbage -- which is exactly the failure the objdump comparison is best at
catching, and the reason the gate is a parameter rather than a guess.

This file is the decoder only. `core/cortexm0/exec.cc` executes Armv6-M and
answers `StepResult::Unimplemented` -- processor completely untouched -- for
every Thumb-2 encoding, verified 2026-08-25 across all six prefix groups. So a
Cortex-M4 image can be read here and cannot be run anywhere, and it stops
saying so rather than executing something else. OH-50 records why.
"""

from __future__ import annotations

import dataclasses
import enum

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


class Profile(enum.Enum):
    """Which Thumb this decoder is reading.

    A value rather than a boolean, because `wide=True` at a call site says
    nothing about which architecture it means and these names are the ones
    `docs/architectures.md` and `webui/boards/catalogue.py` already use.
    """

    V6M = "Armv6-M"
    V7EM = "Armv7E-M"


def is_wide(halfword: int, profile: Profile) -> bool:
    """Whether `halfword` begins a 32-bit instruction.

    **The one rule that differs between the two profiles**, and the one that
    has to be right before anything else can be. A wrong width does not print a
    wrong line; it desynchronises the stream and prints wrong lines from there
    to the end of the buffer.

    Armv7-M, DDI0403 A5.1: a halfword is the first of a 32-bit instruction when
    its top five bits are `0b11101`, `0b11110` or `0b11111` -- so bits 15:13
    are all set *and* bits 12:11 are not both clear.

    Armv6-M, DDI0419 A5.1: only `0b11110`. `BL` is the sole 32-bit encoding on
    the part, which is why `0xE8B0` is undefined there and `ldmia.w r0!, {..}`
    here.
    """
    if profile is Profile.V7EM:
        return (halfword & 0xE000) == 0xE000 and (halfword & 0x1800) != 0
    return (halfword & 0xF800) == 0xF000


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


def _narrow_v7em(encoding: int, address: int) -> str | None:
    """The 16-bit encodings Armv7E-M has and Armv6-M does not.

    Two of them, and neither is a wide instruction:

    * `CBZ`/`CBNZ` -- compare against zero and branch forward. Forward only,
      and the offset is unsigned, which is why a `cbz` never appears at the
      bottom of a loop.
    * `IT` -- makes the next one to four instructions conditional. It carries
      no operation of its own; the suffix letters say which of the following
      instructions run under the condition and which under its inverse.

    Returns None for everything else, so the Thumb-16 table below still sees
    every encoding it owns.
    """
    if (encoding & 0xF500) == 0xB100:
        # `1011 op 0 i 1 imm5 Rn`. The immediate is `i:imm5:0` -- six bits and
        # a zero, unsigned, so the range is 0 to 126 bytes forward.
        nonzero = (encoding >> 11) & 1
        offset = (((encoding >> 9) & 1) << 6) | (((encoding >> 3) & 0x1F) << 1)
        return (
            f"{'cbnz' if nonzero else 'cbz'}	{_reg(encoding & 7)}, "
            f"{_target(address, offset)}"
        )
    if (encoding & 0xFF00) == 0xBF00 and (encoding & 0xF):
        return _it_block(encoding)
    return None


def _it_block(encoding: int) -> str | None:
    """`IT`, `ITE`, `ITTE`, ... from `1011 1111 firstcond mask`.

    The mask is not a count. Its **lowest set bit** marks the end of the
    block, and the bits above it -- read from bit 3 downwards -- say `t` where
    they equal the low bit of the condition and `e` where they differ. So
    `mask = 0b1000` is a one-instruction `it`, and `0b1010` with a condition
    whose low bit is 1 is `itte`.

    A mask of zero is not an `IT` at all: that is the hint space -- `nop`,
    `yield`, `wfe`, `wfi`, `sev` -- which this file does not name. The caller
    checks it before asking.
    """
    firstcond = (encoding >> 4) & 0xF
    mask = encoding & 0xF
    if firstcond == 0xF:
        return None
    condition = "al" if firstcond == 0xE else CONDITIONS[firstcond]

    for lowest in (0, 1, 2, 3):
        if mask & (1 << lowest):
            break
    if firstcond == 0xE and lowest != 3:
        # `it al` is the only unconditional form: an `else` arm under `al`
        # would be an arm that never runs, and the architecture makes it
        # UNPREDICTABLE rather than allowing it.
        return None
    letters = "".join(
        "t" if ((mask >> bit) & 1) == (firstcond & 1) else "e"
        for bit in range(3, lowest, -1)
    )
    return f"it{letters}	{condition}"


# --- Thumb-2: the 32-bit encodings Armv7E-M adds ---------------------------
#
# Reached only from `decode` under `Profile.V7EM`, and only for a halfword
# `is_wide` has already accepted. Every function here returns the rendered text
# or **None**, and None means `.word` with width 4 -- never a guess, and never
# a width other than 4.
#
# Grouped the way DDI0403 A5.3 groups them, by `op1` (bits 12:11 of the first
# halfword) and `op2` (bits 10:4). The group boundaries are the manual's, not
# this file's, so a reader with the manual open can find the branch that
# handles what they are looking at.


def _wide(hw1: int, hw2: int, address: int) -> str | None:
    """A 32-bit Thumb-2 instruction as text, or None if this file cannot name it."""
    op1 = (hw1 >> 11) & 0b11
    if op1 == 0b10:
        if hw2 & 0x8000:
            return _wide_branch(hw1, hw2, address)
        if (hw1 >> 9) & 1:
            return _wide_plain_immediate(hw1, hw2)
        return _wide_modified_immediate(hw1, hw2)
    if op1 == 0b01 and ((hw1 >> 9) & 0b11) == 0b00:
        # `op2` of `00xx0xx` and `00xx1xx`: the two halves are told apart by
        # `hw1[6]`, which is the manual's own split point.
        if (hw1 >> 6) & 1:
            return _wide_load_store_dual(hw1, hw2)
        return _wide_load_store_multiple(hw1, hw2)
    if op1 == 0b11:
        if ((hw1 >> 9) & 0b11) == 0b00:
            return _wide_load_store_single(hw1, hw2)
        if ((hw1 >> 8) & 0b111) == 0b010:
            # `op2` of `010xxxx`, DDI0403 A5.3. Read as `(hw1 >> 7) & 0b1111
            # == 0b0100` first, which is `0100xxx` -- half the range, so
            # 0xFA80..0xFAFF never reached this function and `clz`, `rbit`,
            # `rev.w` and `revsh.w` were unreachable while looking implemented.
            return _wide_register(hw1, hw2)
        if ((hw1 >> 7) & 0b1111) in (0b0110, 0b0111):
            return _wide_multiply(hw1, hw2)
        return None
    if op1 == 0b01 and ((hw1 >> 9) & 0b11) == 0b01:
        # `op2` of `01xxxxx`, DDI0403 A5.3 -- which is 0xEA00..0xEBFF and not
        # 0xEC00. **This read 0b10 first**, putting the coprocessor space into
        # the data-processing decoder, and the sweep reported 8,168 encodings
        # this file named and objdump refused. Naming something that does not
        # exist is the worse direction of that comparison: an unnamed encoding
        # is a `.word` a reader can look up, and an invented one is a lie.
        return _wide_shifted_register(hw1, hw2)
    return None


#: Data-processing opcodes, `hw1[8:5]`, shared by the modified-immediate and
#: shifted-register groups -- the same table indexed the same way, which is why
#: it is one tuple rather than two. None marks an opcode the architecture does
#: not define in this group.
DP_OPS: tuple[str | None, ...] = (
    "and", "bic", "orr", "orn", "eor", None, "pkh", None,
    "add", None, "adc", "sbc", None, "sub", "rsb", None,
)

#: What an opcode becomes when its destination is `pc` and it sets flags: the
#: comparison that discards its result. objdump prints these names, not
#: `ands.w pc, ...`, and rendering the latter would be naming a form the
#: architecture does not have.
DP_TO_TEST = {"and": "tst", "eor": "teq", "add": "cmn", "sub": "cmp"}

#: Opcodes that take no `.w`, because they have no 16-bit form to be told
#: apart from. The suffix means "the wide encoding of an instruction that also
#: has a narrow one"; `ORN` and `TEQ` have only ever been 32 bits, so objdump
#: prints them bare. `MVN` is not here -- Thumb-16 has `mvns`, so `mvn.w` is a
#: real disambiguation even though it arrives through the same `ORN` encoding.
#: Nor are `TST`, `CMP` and `CMN`, which all have narrow forms.
#:
#: `RSB` is the one worth a sentence. Thumb-16 *does* have it, as `negs` --
#: `RSBS Rd, Rn, #0` -- so a `.w` looks justified. objdump spells the narrow
#: form `negs` and treats it as a different mnemonic rather than an alias, so
#: nothing is left for `rsb` to be told apart from and it prints bare in both
#: the immediate and the register form. Checked against the tool rather than
#: reasoned out: the first version had `.w` and the sweep reported 1,080
#: disagreements.
NO_WIDE_SUFFIX = frozenset({"orn", "teq", "rsb"})


#: And what it becomes when its *source* is `pc`: the one-operand form.
#: `orr` with no first operand is a move; `orn` with none is a move of the
#: complement. Same encoding space, different instruction.
DP_FROM_PC = {"orr": "mov", "orn": "mvn"}

#: The four shift types, `hw2[5:4]`. `rrx` is not in the tuple because it is
#: `ror` with an immediate of zero and takes no operand -- see `_shift_suffix`.
SHIFT_TYPES = ("lsl", "lsr", "asr", "ror")


def _expand_immediate(i: int, imm3: int, imm8: int) -> int:
    """`ThumbExpandImm`, DDI0403 A5.3.2.

    **The single most misreadable thing in Thumb-2**, and worth the space. A
    twelve-bit field encodes a 32-bit constant four different ways, chosen by
    its top two bits:

        00 00  0x000000ab      the byte
        00 01  0x00ab00ab      repeated in halves
        00 10  0xab00ab00      repeated in the other halves
        00 11  0xabababab      repeated in all four
        else   ROR(0x80|imm7)  a set top bit, rotated

    The fourth line is the one that catches people: any value with bits 11:10
    set is *not* a repeat pattern, it is a rotation, and the byte it rotates
    has an implicit leading 1 that is not in the encoding. Reading it as a
    plain byte gives a number that is wrong by a factor of two and looks
    perfectly reasonable in a listing.
    """
    imm12 = (i << 11) | (imm3 << 8) | imm8
    if (imm12 >> 10) == 0:
        kind = (imm12 >> 8) & 0b11
        if kind == 0b00:
            return imm8
        if kind == 0b01:
            return (imm8 << 16) | imm8
        if kind == 0b10:
            return (imm8 << 24) | (imm8 << 8)
        return (imm8 << 24) | (imm8 << 16) | (imm8 << 8) | imm8
    unrotated = 0x80 | (imm12 & 0x7F)
    rotation = (imm12 >> 7) & 0x1F
    return ((unrotated >> rotation) | (unrotated << (32 - rotation))) & 0xFFFFFFFF


def _shift_suffix(hw2: int) -> str:
    """`, lsl #3` or `, rrx` or nothing, from a shifted-register second half.

    Three encodings of zero mean three different things, the same trap
    `decode`'s format 1/2 branch documents for Thumb-16: `lsl #0` is no shift
    at all and objdump prints nothing; `lsr #0` and `asr #0` mean 32; and
    `ror #0` is not a rotation but `rrx`, the one-bit rotate through carry.
    """
    kind = (hw2 >> 4) & 0b11
    amount = (((hw2 >> 12) & 0b111) << 2) | ((hw2 >> 6) & 0b11)
    if kind == 0b00 and amount == 0:
        return ""
    if kind == 0b11 and amount == 0:
        return ", rrx"
    if kind in (0b01, 0b10) and amount == 0:
        amount = 32
    return f", {SHIFT_TYPES[kind]} #{amount}"


#: Load/store single, by `hw1[6:5]`: the size, and `11` is not a size.
LS_SIZES: tuple[str | None, ...] = ("b", "h", "", None)


def _wide_load_store_single(hw1: int, hw2: int) -> str | None:
    """LDR/STR and their byte, halfword and sign-extending forms, DDI0403 A6.7.5.

    One encoding family with three addressing shapes, chosen by `hw1[7]` and
    then by the top bits of the second halfword:

        hw1[7] = 1              [Rn, #imm12]        unsigned, always positive
        hw1[7] = 0, hw2[11] = 1 [Rn, #±imm8] and its pre/post forms
        hw1[7] = 0, hw2[11:6]=0 [Rn, Rm, lsl #imm2]

    `hw1[8]` is the sign-extending bit, which is why `LDRSB` and `LDRSH` are
    here rather than in a group of their own, and why there is no `STRS`
    anything -- sign extension is a property of a load.
    """
    sign = (hw1 >> 8) & 1
    imm12_form = (hw1 >> 7) & 1
    size = LS_SIZES[(hw1 >> 5) & 0b11]
    load = (hw1 >> 4) & 1
    rn, rt = hw1 & 0xF, (hw2 >> 12) & 0xF

    if size is None or (sign and not load) or (sign and size == ""):
        # A word cannot be sign-extended and a store has nothing to extend, so
        # both are undefined rather than instructions this file has not got to.
        return None
    if rn == 0xF:
        # The literal forms, `[pc, #imm]`. Not attempted: rendering them the
        # way objdump does means resolving the target, and a wrong target in a
        # listing is the failure this file most wants to avoid.
        return None
    if load and rt == 0xF:
        # **Not a load at all.** A load into `pc` in this group is the memory
        # hint space -- `PLD`, `PLI` -- which reads nothing into a register and
        # is architecturally a different instruction. This file does not name
        # the hints, and naming them `ldrb.w pc, ...` would be worse than not
        # naming them: it would claim a destination register the instruction
        # does not have. The sweep reported 780 of these.
        return None

    mnemonic = ("ldr" if load else "str") + ("s" if sign else "") + size

    if imm12_form:
        # A zero offset is not printed. Unambiguous here in a way it was not
        # for LDRD: this form has no sign bit, so there is no `#-0` for `[Rn]`
        # to be confused with and nothing is lost.
        if hw2 & 0xFFF == 0:
            return f"{mnemonic}.w	{_reg(rt)}, [{_reg(rn)}]"
        return f"{mnemonic}.w	{_reg(rt)}, [{_reg(rn)}, #{hw2 & 0xFFF}]"

    if (hw2 >> 11) & 1:
        p_bit, u_bit, writeback = (hw2 >> 10) & 1, (hw2 >> 9) & 1, (hw2 >> 8) & 1
        if not p_bit and not writeback:
            return None                     # the memory hints, not named here
        offset, sign_text = hw2 & 0xFF, "" if u_bit else "-"
        # `.w` on these too. It is not obvious -- the pre- and post-indexed
        # forms have no Thumb-16 counterpart to be told apart from, so the
        # suffix looks unearned -- but objdump prints it and the suffix is a
        # rendering convention rather than an architectural fact. The first
        # version left it off and the sweep reported 975 disagreements.
        if not p_bit:
            return f"{mnemonic}.w	{_reg(rt)}, [{_reg(rn)}], #{sign_text}{offset}"
        bang = "!" if writeback else ""
        return f"{mnemonic}.w	{_reg(rt)}, [{_reg(rn)}, #{sign_text}{offset}]{bang}"

    if (hw2 >> 6) & 0x3F:
        return None                          # unallocated, and objdump agrees
    shift = (hw2 >> 4) & 0b11
    rm = hw2 & 0xF
    amount = f", lsl #{shift}" if shift else ""
    return f"{mnemonic}.w	{_reg(rt)}, [{_reg(rn)}, {_reg(rm)}{amount}]"


def _wide_register(hw1: int, hw2: int) -> str | None:
    """Data-processing on registers, DDI0403 A6.7.

    Two things share this space and are told apart by `hw2[7:4]`:

    * the **wide shifts**, whose amount is in a register rather than an
      immediate -- `lsl.w r0, r1, r2`, which Thumb-16 cannot express because
      it has no three-operand shift
    * the **extends** (`sxtb`, `uxth`, ...) and the **misc** group
      (`clz`, `rbit`, `rev.w`), which are single-operand transforms

    `hw2[15:12]` must be `1111` in every one of them. It is a should-be-one
    field rather than a register, and decoding an encoding without it would
    name an instruction the architecture does not define.
    """
    if (hw2 >> 12) & 0xF != 0xF:
        return None
    op = (hw1 >> 4) & 0xF
    rn, rd, rm = hw1 & 0xF, (hw2 >> 8) & 0xF, hw2 & 0xF
    kind = (hw2 >> 4) & 0xF

    if ((hw1 >> 7) & 1) == 0 and kind == 0:
        # The register-amount shifts. `hw1[7:5]` picks which, and `hw1[4]` is
        # the flag-setting bit as everywhere else.
        shift = SHIFT_TYPES[(hw1 >> 5) & 0b11]
        flags = "s" if op & 1 else ""
        return f"{shift}{flags}.w	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}"

    if ((hw1 >> 7) & 1) == 0 and (kind >> 2) == 0b10:
        # The extends. A rotation of zero is not printed, the same convention
        # `_shift_suffix` keeps: `ror #0` is no rotation.
        names = ("sxth", "uxth", "sxtb16", "uxtb16", "sxtb", "uxtb", None, None)
        name = names[(hw1 >> 4) & 0b111]
        if name is None:
            return None
        rotation = ((hw2 >> 4) & 0b11) * 8
        turn = f", ror #{rotation}" if rotation else ""
        if rn != 0xF:
            # The accumulating forms, SXTAH and friends. Named for what they
            # are rather than skipped, because they differ from the above by
            # one register and would otherwise decode as the wrong instruction.
            return f"{name[:3]}a{name[3:]}	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}{turn}"
        # `.w` only where Thumb-16 has the same instruction to be told apart
        # from -- `sxth`, `uxth`, `sxtb`, `uxtb` do and the `*16` pair do not,
        # which is the same rule `NO_WIDE_SUFFIX` states for the
        # data-processing group. The accumulating forms above take none
        # either: `sxtah` has never been 16 bits.
        suffix = "" if name.endswith("16") else ".w"
        return f"{name}{suffix}	{_reg(rd)}, {_reg(rm)}{turn}"

    # **The source is `Rn`, not `Rm`.** These one-operand forms encode the
    # same register twice -- `hw1[3:0]` and `hw2[3:0]` -- and objdump prints
    # the first. When the two differ the encoding is UNPREDICTABLE and objdump
    # prints `hw1`'s anyway; matching it is what keeps the comparison about
    # decoding rather than about which copy to believe.
    if ((hw1 >> 7) & 1) == 1 and kind == 0b1000 and ((hw1 >> 4) & 0b111) == 0b011:
        return f"clz	{_reg(rd)}, {_reg(rn)}"
    if ((hw1 >> 7) & 1) == 1 and ((hw1 >> 4) & 0b111) == 0b001:
        names = ("rev.w", "rev16.w", "rbit", "revsh.w")
        if kind >> 2 != 0b10:
            return None
        return f"{names[kind & 0b11]}	{_reg(rd)}, {_reg(rn)}"
    return None


def _wide_multiply(hw1: int, hw2: int) -> str | None:
    """Multiply, multiply-accumulate and divide, DDI0403 A6.7.

    `MUL` and `MLA` are the same encoding: the accumulator register is `pc`
    when there is none. Rendering `mla rd, rn, rm, pc` would be naming a
    register the instruction does not read.
    """
    long_form = (hw1 >> 7) & 1
    op = (hw1 >> 4) & 0b111
    rn, ra, rd, rm = hw1 & 0xF, (hw2 >> 12) & 0xF, (hw2 >> 8) & 0xF, hw2 & 0xF
    kind = (hw2 >> 4) & 0xF

    if not long_form:
        if op != 0 or (hw2 >> 6) & 0b11:
            return None
        if kind == 0b0000:
            if ra == 0xF:
                return f"mul.w	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}"
            return f"mla	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}, {_reg(ra)}"
        if kind == 0b0001 and ra != 0xF:
            return f"mls	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}, {_reg(ra)}"
        return None

    # The long forms write a register *pair*, so `ra` is the low half of the
    # result rather than an accumulator input -- the same field, a different
    # meaning, which is why it is renamed here.
    low, high = ra, rd
    if kind == 0b0000 and op in (0b000, 0b010, 0b100, 0b110):
        names = {0b000: "smull", 0b010: "umull", 0b100: "smlal", 0b110: "umlal"}
        return f"{names[op]}	{_reg(low)}, {_reg(high)}, {_reg(rn)}, {_reg(rm)}"
    if kind == 0b1111 and op in (0b001, 0b011) and low == 0xF:
        return f"{'sdiv' if op == 0b001 else 'udiv'}	{_reg(high)}, {_reg(rn)}, {_reg(rm)}"
    return None


def _wide_load_store_multiple(hw1: int, hw2: int) -> str | None:
    """STM, LDM, PUSH.W and POP.W, DDI0403 A6.7.

    Two of these have a second name rather than a second encoding: a store
    that decrements before, writes back, and uses `sp` **is** `PUSH`, and the
    matching load is `POP`. objdump prints the second name, and printing
    `stmdb sp!, {...}` instead would be technically true and would not be what
    anyone reading a prologue expects to see.

    The register list is the whole second halfword, so unlike Thumb-16's
    eight-bit form it can name `r8`-`r12` -- which is most of why the wide
    encoding exists.
    """
    op = (hw1 >> 7) & 0b11
    writeback, load = (hw1 >> 5) & 1, (hw1 >> 4) & 1
    rn = hw1 & 0xF
    if op not in (0b01, 0b10):
        return None
    if rn == 0xF:
        # `Rn == pc` is UNPREDICTABLE on Armv7E-M. objdump names it `clrm`,
        # which is real -- and is **Armv8.1-M**, an architecture no part in
        # this repository has. This is the decodes-a-wider-target trap the
        # RISC-V sweeps met with F and D, arriving from the other direction:
        # there objdump named encodings the part refuses, here it names one
        # from a later revision of the same family. Either way the sweep must
        # not be satisfied by agreeing with it.
        return None
    registers = _wide_reglist(hw2)

    # **No `push.w`/`pop.w` aliasing**, and that is objdump's choice rather
    # than this file's preference. `LDMIA sp!` really is `POP` and `STMDB sp!`
    # really is `PUSH` -- the architecture says so -- but the oracle prints the
    # base form for the wide encodings, and the first version of this function
    # aliased both and disagreed on 66 encodings.
    #
    # It also aliased `LDMDB sp!` to `pop.w`, which is wrong on its own terms:
    # `POP` is the increment-after form. That bug would have survived a
    # reviewer and did not survive the sweep.
    suffix = ".w" if op == 0b01 else ""
    mnemonic = ("stm" if not load else "ldm") + ("ia" if op == 0b01 else "db")
    bang = "!" if writeback else ""
    return f"{mnemonic}{suffix}	{_reg(rn)}{bang}, {registers}"


def _wide_reglist(bits: int) -> str:
    """`{r0, r4, lr}` over all sixteen registers.

    The Thumb-16 `_reglist` above covers eight and takes the ninth as a
    keyword argument, because `PUSH` and `POP` are the only encodings that can
    name `lr` or `pc` there. Here every bit is a register and there is no
    special case, which is a different enough shape to be its own function
    rather than a flag on that one.

    An empty list prints as `{}` -- which is what objdump does, and which is a
    real encoding rather than a rendering failure.
    """
    names = [REGISTERS[bit] for bit in range(16) if bits & (1 << bit)]
    return "{" + ", ".join(names) + "}"


def _wide_load_store_dual(hw1: int, hw2: int) -> str | None:
    """LDRD, STRD and the table branches, DDI0403 A6.7.

    Two registers in one instruction, and an eight-bit offset **scaled by
    four** -- the scaling is easy to drop and produces a listing whose offsets
    are all a quarter of the truth.

    `TBB` and `TBH` share this space and are not loads at all: they read a
    jump table and branch. They are here because the manual puts them here.
    """
    p_bit, u_bit = (hw1 >> 8) & 1, (hw1 >> 7) & 1
    writeback, load = (hw1 >> 5) & 1, (hw1 >> 4) & 1
    rn = hw1 & 0xF
    rt, rt2 = (hw2 >> 12) & 0xF, (hw2 >> 8) & 0xF

    if not p_bit and not writeback:
        # The exclusive accesses and the table branches, which this file does
        # not name. Left as `.word` rather than guessed at.
        return None
    if rn == 0xF:
        # The literal forms, whose operand is a pc-relative address rather
        # than a register. Not attempted.
        return None

    offset = (hw2 & 0xFF) * 4
    # objdump prints the sign whenever `U` is clear, including for zero --
    # `[r0], #-0` is its own output and not a typo. The sign is part of the
    # encoding, so a rendering that dropped it for zero would lose a bit.
    sign = "" if u_bit else "-"
    mnemonic = "ldrd" if load else "strd"
    registers = f"{_reg(rt)}, {_reg(rt2)}, "
    if not p_bit:
        return f"{mnemonic}	{registers}[{_reg(rn)}], #{sign}{offset}"
    bang = "!" if writeback else ""
    # A *positive* zero offset is not printed; a negative one is. That looks
    # like a quirk and is a real distinction: `#-0` is `U == 0`, a bit of the
    # encoding, and omitting it would render two different instructions
    # identically. The post-indexed form above prints it either way, because
    # there the offset is the writeback and dropping it would lose the whole
    # operation.
    if u_bit and offset == 0:
        return f"{mnemonic}	{registers}[{_reg(rn)}]{bang}"
    return f"{mnemonic}	{registers}[{_reg(rn)}, #{sign}{offset}]{bang}"


def _wide_suffix(op: str) -> str:
    """`.w`, or nothing for an opcode that has no narrow form. See
    `NO_WIDE_SUFFIX`."""
    return "" if op in NO_WIDE_SUFFIX else ".w"


def _wide_modified_immediate(hw1: int, hw2: int) -> str | None:
    """Data-processing with a modified immediate, DDI0403 A6.7.

    `hw1[9]` is clear here, which is what separates this from the plain-binary
    group: the twelve immediate bits are run through `_expand_immediate`
    rather than used as a number.
    """
    op = DP_OPS[(hw1 >> 5) & 0xF]
    if op is None or op == "pkh":
        return None
    setflags = (hw1 >> 4) & 1
    rn, rd = hw1 & 0xF, (hw2 >> 8) & 0xF
    value = _expand_immediate((hw1 >> 10) & 1, (hw2 >> 12) & 0b111, hw2 & 0xFF)

    if rd == 0xF and setflags and op in DP_TO_TEST:
        return f"{DP_TO_TEST[op]}{_wide_suffix(DP_TO_TEST[op])}	{_reg(rn)}, #{value}"
    if rn == 0xF and op in DP_FROM_PC:
        flags = "s" if setflags else ""
        return f"{DP_FROM_PC[op]}{flags}{_wide_suffix(DP_FROM_PC[op])}	{_reg(rd)}, #{value}"
    if rn == 0xF:
        return None
    flags = "s" if setflags else ""
    return f"{op}{flags}{_wide_suffix(op)}	{_reg(rd)}, {_reg(rn)}, #{value}"


def _wide_plain_immediate(hw1: int, hw2: int) -> str | None:
    """Data-processing with a plain binary immediate, DDI0403 A6.7.

    `hw1[9]` is set. These carry a literal twelve- or sixteen-bit number and
    never set flags, which is why `addw`/`subw` are spelled without a `.w`:
    the `w` is part of the mnemonic rather than a width suffix.
    """
    op = (hw1 >> 4) & 0x1F
    rn, rd = hw1 & 0xF, (hw2 >> 8) & 0xF
    imm12 = (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 0b111) << 8) | (hw2 & 0xFF)

    if op == 0b00000:
        # ADDW, or ADR when the operand is the program counter.
        if rn == 0xF:
            return None
        return f"addw	{_reg(rd)}, {_reg(rn)}, #{imm12}"
    if op == 0b01010:
        if rn == 0xF:
            return None
        return f"subw	{_reg(rd)}, {_reg(rn)}, #{imm12}"
    if op == 0b00100:
        # MOVW: the immediate reaches sixteen bits by taking four more from
        # the first halfword, which is the whole point of the encoding.
        return f"movw	{_reg(rd)}, #{(rn << 12) | imm12}"
    if op == 0b01100:
        return f"movt	{_reg(rd)}, #{(rn << 12) | imm12}"

    # The saturating and bitfield instructions share this group and take their
    # operands apart differently: `imm3:imm2` is a shift amount for the
    # saturates and a bit position for the bitfields, and the five-bit tail is
    # a width for one and a saturation limit for the other.
    # `hw2[15]`, `hw2[5]` and **`hw1[10]`** are all should-be-zero in every
    # encoding below, DDI0403's `(0)`. objdump refuses when any is set.
    #
    # `hw1[10]` is the one worth naming: it is the `i` bit, and it is a real
    # immediate bit for `ADDW`, `SUBW`, `MOVW` and `MOVT` above -- the same
    # position meaning something in one half of this group and nothing in the
    # other. So the guard goes here rather than at the top of the function,
    # where it would have silently truncated every `movw` immediate.
    if hw2 & 0x8020 or (hw1 >> 10) & 1:
        return None
    position = (((hw2 >> 12) & 0b111) << 2) | ((hw2 >> 6) & 0b11)
    tail = hw2 & 0x1F

    if op in (0b10000, 0b10010):
        # SSAT. `+ 1` because the field encodes the limit one less than it
        # means -- saturating to zero bits is not a thing, so the encoding
        # spends the value on something useful. USAT below does *not* do this,
        # which is the kind of asymmetry that is only ever found by checking.
        #
        # **The `asr` variant with a shift of zero is a different
        # instruction**: `SSAT16`, which saturates two halfwords rather than a
        # word. The first version here rendered it as an unshifted `ssat` --
        # a plausible line naming the wrong instruction, which is the failure
        # this whole comparison exists to catch, and the sweep caught it.
        if op == 0b10010 and position == 0:
            return f"ssat16	{_reg(rd)}, #{tail + 1}, {_reg(rn)}"
        return (
            f"ssat	{_reg(rd)}, #{tail + 1}, {_reg(rn)}"
            f"{_saturate_shift(op == 0b10010, position)}"
        )
    if op in (0b11000, 0b11010):
        if op == 0b11010 and position == 0:
            return f"usat16	{_reg(rd)}, #{tail}, {_reg(rn)}"
        return (
            f"usat	{_reg(rd)}, #{tail}, {_reg(rn)}"
            f"{_saturate_shift(op == 0b11010, position)}"
        )
    if op in (0b10100, 0b11100):
        name = "sbfx" if op == 0b10100 else "ubfx"
        return f"{name}	{_reg(rd)}, {_reg(rn)}, #{position}, #{tail + 1}"
    if op == 0b10110:
        # BFI, or BFC when there is no source register. The five-bit tail is
        # the *last* bit rather than a width here, so the width has to be
        # derived -- and a decoder that printed the field directly would say
        # `#0` where the answer is `#1`.
        width = tail - position + 1
        if width < 1:
            return None
        if rn == 0xF:
            return f"bfc	{_reg(rd)}, #{position}, #{width}"
        return f"bfi	{_reg(rd)}, {_reg(rn)}, #{position}, #{width}"
    return None


def _saturate_shift(arithmetic: bool, amount: int) -> str:
    """`, lsl #3` or `, asr #3` on a saturate, or nothing.

    A shift of zero is not printed, as everywhere else here -- and `asr #0`
    means 32 in the shifted-register group but **not** in this one, where the
    encoding with a zero amount is the halfword form `SSAT16`. The caller
    handles that before asking, so reaching here with `arithmetic` set and an
    amount of zero cannot happen.
    """
    if amount == 0:
        return ""
    return f", {'asr' if arithmetic else 'lsl'} #{amount}"


def _wide_shifted_register(hw1: int, hw2: int) -> str | None:
    """Data-processing on a shifted register, DDI0403 A6.7.

    The register counterpart of `_wide_modified_immediate`, sharing `DP_OPS`
    and the two `pc`-means-something-else rules with it, and adding the
    optional shift `_shift_suffix` renders.
    """
    op = DP_OPS[(hw1 >> 5) & 0xF]
    if op is None or op == "pkh":
        return None
    # `hw2[15]` is a should-be-zero bit in this encoding, DDI0403 A6.7.1's
    # `(0)`. objdump refuses the encoding when it is set and so does this --
    # decoding it anyway would name 5,252 instructions the architecture does
    # not define, which the sweep reported as `wrong` rather than as a gap.
    if hw2 & 0x8000:
        return None
    setflags = (hw1 >> 4) & 1
    rn, rd, rm = hw1 & 0xF, (hw2 >> 8) & 0xF, hw2 & 0xF
    shift = _shift_suffix(hw2)

    if rd == 0xF and setflags and op in DP_TO_TEST:
        return f"{DP_TO_TEST[op]}{_wide_suffix(DP_TO_TEST[op])}	{_reg(rn)}, {_reg(rm)}{shift}"
    if rn == 0xF and op in DP_FROM_PC:
        flags = "s" if setflags else ""
        # `orr` from pc with a shift is how the wide register shifts are
        # encoded: `mov.w r0, r1, lsl #3` is what objdump prints, and the
        # bare-shift spellings `lsl.w` live in the 0xFA group instead.
        return f"{DP_FROM_PC[op]}{flags}{_wide_suffix(DP_FROM_PC[op])}	{_reg(rd)}, {_reg(rm)}{shift}"
    if rn == 0xF:
        return None
    flags = "s" if setflags else ""
    return f"{op}{flags}{_wide_suffix(op)}	{_reg(rd)}, {_reg(rn)}, {_reg(rm)}{shift}"


def _branch_target(address: int, offset: int, align4: bool = False) -> str:
    """Where a wide branch goes, absolute, as objdump prints it.

    `+ 4` is the architecture: reading the PC during an instruction yields that
    instruction's address plus four. `align4` is `BLX`, which clears the low
    two bits because it changes to Arm state and an Arm instruction is aligned
    -- the one branch here whose target is not simply PC-relative.
    """
    base = (address + 4) & 0xFFFFFFFF
    if align4:
        base &= ~0b11
    return f"0x{(base + offset) & 0xFFFFFFFF:x}"


def _wide_branch(hw1: int, hw2: int, address: int) -> str | None:
    """Branches and miscellaneous control, DDI0403 A6.7.

    Four encodings share `hw1[15:11] == 0b11110` and `hw2[15] == 1`, told apart
    by two bits of the second halfword:

        hw2[14]  hw2[12]
           0        0     B<c>.W   T3, conditional, +-1 MB
           0        1     B.W      T4, unconditional, +-16 MB
           1        0     BLX      T2, and its target is 4-aligned
           1        1     BL       T1

    **`I1` and `I2` are not `J1` and `J2`.** The wide forms encode
    `I = NOT(J EOR S)`, which exists so that a short forward branch has a
    bit pattern close to zero rather than to all-ones. Reading J as I directly
    produces a target that is right for positive offsets and wrong for
    negative ones -- a listing that looks correct until a loop branches
    backwards, which is every loop.
    """
    sign = (hw1 >> 10) & 1
    imm11 = hw2 & 0x7FF
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    wide_form = (hw2 >> 12) & 1
    link = (hw2 >> 14) & 1

    if not link and not wide_form:
        # B<c>.W (T3). `cond` of 0b111x is not a branch at all: it is the
        # miscellaneous-control space -- MSR, MRS, DSB, DMB, ISB and the rest --
        # which this file does not name. Returning None there rather than
        # rendering `b<undefined>` keeps the .word fallback honest.
        condition = (hw1 >> 6) & 0xF
        if condition >= 0b1110:
            return None
        imm6 = hw1 & 0x3F
        offset = _signed(
            (sign << 20) | (j2 << 19) | (j1 << 18) | (imm6 << 12) | (imm11 << 1), 21
        )
        return f"b{CONDITIONS[condition]}.w	{_branch_target(address, offset)}"

    imm10 = hw1 & 0x3FF
    i1 = 1 - (j1 ^ sign)
    i2 = 1 - (j2 ^ sign)

    if not link:
        # B.W (T4)
        offset = _signed(
            (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1), 25
        )
        return f"b.w	{_branch_target(address, offset)}"

    if wide_form:
        # BL (T1)
        offset = _signed(
            (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1), 25
        )
        return f"bl	{_branch_target(address, offset)}"

    # BLX (immediate) (T2). The low bit of the second halfword is part of the
    # encoding rather than of the offset, and the target is 4-aligned.
    imm10l = (hw2 >> 1) & 0x3FF
    offset = _signed(
        (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm10l << 2), 25
    )
    return f"blx	{_branch_target(address, offset, align4=True)}"


def decode(
    encoding: int,
    address: int = 0,
    second: int | None = None,
    profile: Profile = Profile.V6M,
    condition: str | None = None,
) -> tuple[str, int]:
    """One instruction as `(text, width)`.

    `second` is the halfword following `encoding`, needed to complete any
    32-bit pair. Passing None where one is needed yields the `.short`
    rendering rather than reading past the end of a buffer.

    `profile` defaults to `V6M` so every existing caller keeps the behaviour it
    had. It is a default with two real call sites rather than one -- an
    Armv6-M board and an Armv7E-M one -- which is what distinguishes it from
    the speculative options `.claude/CLAUDE.md` rule 6 refuses.

    `condition` is the one thing this function cannot work out for itself.
    Inside an Armv7-M `IT` block the *previous* instructions decide whether
    this one runs, and they also suppress its flag-setting -- `movs r3, #11`
    is `movls r3, #11` when an `itte ls` precedes it. A per-instruction
    decoder cannot know that, so `disassemble` tracks it and passes it in.
    See `_ItBlock`.
    """
    if condition is not None:
        # **First, before the width test.** Re-entered once with the condition
        # applied, as a recursive call rather than a parameter threaded
        # through forty return statements -- every branch below builds its
        # text the same way, and the alternative is forty chances to forget.
        #
        # It sat *after* the wide dispatch at first, which meant a 32-bit
        # instruction inside an `IT` block returned before ever seeing the
        # condition: `mla` where objdump said `mlals`. One line of 143, and
        # the kind that reads as correct.
        text, width = decode(encoding, address, second, profile)
        if text.startswith((".word", ".short")):
            return text, width
        return _conditional(text, condition), width

    # **Width first, and before any 16-bit decoding**, because on Armv7E-M the
    # prefixes 0xE8-0xEF and 0xF8-0xFF are wide and the Thumb-16 table below
    # would otherwise happily name them as something 16 bits long. Armv6-M
    # keeps its old path: only the `BL` pair is wide there, and format 19 at
    # the bottom of this function is where it is decoded.
    if profile is Profile.V7EM and is_wide(encoding, profile):
        if second is None:
            # Half a wide instruction at the end of a buffer. Rendered as the
            # halfword it is, because claiming a width of 4 for bytes that are
            # not there would be inventing the missing half.
            return f".short	0x{encoding:04x}", 2
        text = _wide(encoding, second, address)
        if text is None:
            # **Width 4 even with no name.** The text is one wrong line; the
            # width is every line after it.
            return f".word	0x{encoding:04x}{second:04x}", 4
        return text, 4

    if profile is Profile.V7EM:
        # **Armv7E-M adds 16-bit encodings too**, which is the assumption
        # `is_wide`'s docstring does not cover and this branch exists to
        # correct. `CBZ`, `CBNZ` and `IT` are all two bytes long and all sit in
        # space Armv6-M leaves undefined, so "a superset" is true of the
        # instruction set and *not* true of the wide encodings alone.
        #
        # Tried before the Thumb-16 table rather than after, because that table
        # ends in `.short` rather than in a fallthrough and would swallow them.
        narrow = _narrow_v7em(encoding, address)
        if narrow is not None:
            return narrow, 2

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
        # **`0b11` over bits 10:9, not `0b111` over 11:9.** Bit 11 is the load
        # bit that tells PUSH from POP, so testing it as part of the opcode
        # matched `1011 0 10 R` only -- every POP fell through to `.short` and
        # the `load` local below was always zero, making its own `pop` arm and
        # its `pc` arm unreachable.
        #
        # Pre-existing, and it survived `tests/cortexm0/test_disasm.py`'s
        # four-image objdump comparison because **none of those four images
        # contains a POP**: they are `for(;;)` leaves that never return.
        # Found 2026-08-25 by the Armv7E-M probe, which has real functions.
        if (encoding >> 9) & 0b11 == 0b10:
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


#: Thumb-16 mnemonics whose trailing `s` is the flag-setting bit rather than
#: part of the name. Inside an `IT` block those encodings do **not** set flags
#: -- they take the block's condition instead -- so the `s` comes off and the
#: condition goes on. Listed rather than found by stripping any trailing `s`,
#: because a mnemonic that genuinely ended in one would be quietly truncated.
FLAG_SETTING = frozenset(ALU_OPS) | frozenset({
    "movs", "adds", "subs", "lsls", "lsrs", "asrs", "mvns", "negs", "muls",
})


def _conditional(text: str, condition: str) -> str:
    """`movs r3, #11` under `ls` becomes `movls r3, #11`.

    Two edits, and both are the architecture rather than a spelling choice:
    the flag-setting `s` is dropped because an instruction inside an `IT`
    block does not set flags, and the condition is inserted **before** any
    `.w`, because the width suffix is the last thing in an Arm mnemonic.
    """
    mnemonic, tab, operands = text.partition("\t")
    base, dot, width = mnemonic.partition(".")
    if base in FLAG_SETTING:
        base = base[:-1]
    return f"{base}{condition}{dot}{width}{tab}{operands}"


class _ItBlock:
    """How many instructions are still conditional, and under what.

    An `IT` makes the next one to four instructions conditional, alternating
    between the named condition and its inverse as the mask's letters say.
    This walks that queue while `disassemble` steps through the stream, which
    is the only place the ordering is known.

    **The inverse of a condition is its code with the low bit flipped** --
    `eq` is 0 and `ne` is 1, `ge` is 10 and `lt` is 11 -- which is why the
    encoding puts the pairs next to each other and why this needs no table.
    """

    #: Every condition by its 4-bit code. `CONDITIONS` stops at 13 because a
    #: 14 in a *branch* is encoded as an unconditional one instead; in an `IT`
    #: it is a real `al`, so this adds it back.
    NAMES = CONDITIONS + ("al",)

    def __init__(self) -> None:
        self._queue: list[str] = []

    def next_condition(self) -> str | None:
        """The condition for the instruction about to be decoded, if any."""
        return self._queue.pop(0) if self._queue else None

    def saw(self, encoding: int, width: int) -> None:
        """Note an instruction that has just been decoded.

        An `IT` inside an `IT` block is UNPREDICTABLE, so a new one replaces
        the queue rather than nesting -- which is also what objdump does and
        is the only behaviour a linear reader can act on.
        """
        if width != 2 or (encoding & 0xFF00) != 0xBF00 or not (encoding & 0xF):
            return
        firstcond, mask = (encoding >> 4) & 0xF, encoding & 0xF
        if firstcond == 0xF:
            return
        for lowest in (0, 1, 2, 3):
            if mask & (1 << lowest):
                break
        if firstcond == 0xE and lowest != 3:
            # `it al` with an else-arm. The inverse of `al` is condition 15,
            # which names nothing, and an arm that never runs is UNPREDICTABLE
            # -- so the block is not entered at all, matching `_it_block`,
            # which refuses to render the same encoding.
            #
            # This guard was missing while `_it_block` had it, and the two
            # disagreeing crashed the stream sweep with an IndexError on its
            # first run. Two places implementing one rule is the shape of that
            # bug; they are next to each other now so the pairing is visible.
            return
        self._queue = [self.NAMES[firstcond]]
        for bit in range(3, lowest, -1):
            same = ((mask >> bit) & 1) == (firstcond & 1)
            self._queue.append(self.NAMES[firstcond if same else firstcond ^ 1])


def disassemble(
    data: bytes, base: int = 0, profile: Profile = Profile.V6M
) -> list[Line]:
    """Every instruction in `data`, in order, starting at address `base`.

    Linear rather than following branches, which is what objdump does with a
    raw binary and therefore what the comparison needs. It also means a data
    word inside the code is decoded as an instruction -- true of every linear
    disassembler and the reason a listing shows `.short` at all.
    """
    lines: list[Line] = []
    offset = 0
    block = _ItBlock()
    while offset + 2 <= len(data):
        encoding = int.from_bytes(data[offset:offset + 2], "little")
        second = (
            int.from_bytes(data[offset + 2:offset + 4], "little")
            if offset + 4 <= len(data) else None
        )
        text, width = decode(
            encoding, base + offset, second, profile, block.next_condition()
        )
        block.saw(encoding, width)
        packed = encoding if width == 2 else (encoding << 16) | (second or 0)
        lines.append(Line(base + offset, width, packed, text))
        offset += width
    return lines


def disassemble_range(
    cpu, address: int, count: int, profile: Profile = Profile.V6M
) -> list[Line]:
    """`count` instructions from `address`, read through a CPU's memory.

    Reads halfword by halfword rather than a block, so a listing that runs off
    the end of a region stops there instead of failing whole -- the pane wants
    what it can show, not an exception.
    """
    lines: list[Line] = []
    at = address
    block = _ItBlock()
    for _ in range(count):
        try:
            first = int.from_bytes(cpu.read_block(at, 2), "little")
        except Exception:  # noqa: BLE001 - any fault means "nothing more to show"
            break
        try:
            second = int.from_bytes(cpu.read_block(at + 2, 2), "little")
        except Exception:  # noqa: BLE001 - a pair at the very end of a region
            second = None
        text, width = decode(first, at, second, profile, block.next_condition())
        block.saw(first, width)
        packed = first if width == 2 else (first << 16) | (second or 0)
        lines.append(Line(at, width, packed, text))
        at += width
    return lines
