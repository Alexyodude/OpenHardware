#!/usr/bin/env python3
# OpenHardware - generate an RV32 conformance corpus that carries its own gating.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Emit `tests/rv32/corpus/*.json`: encodings, what each one requires, and
what rvcpp does with it.

## The oracle is right about behaviour and silent about permission

`webui/boards/catalogue.py`'s ORACLES entry says rvcpp is "right on the legal
space, wrong at the illegal-instruction edge", and that is not a caveat to
work around -- it decides the shape of this file. Measured here, at
`third_party/rvcpp-build/rvcpp.exe`:

    80000048: 0863a2af : t0    <- 00000000 :      amoadd.w x5, x6, (x7)
    8000004c: 1003a42f : s0    <- 0000002a :      lr.w     x8, (x7)

Both are A-extension encodings. rvcpp executed both. An ESP32-C3 is RV32IMC
and must raise illegal-instruction on both; an ESP32-C6 is RV32IMAC and must
execute them. No lockstep run against this oracle can tell those two parts
apart, because the oracle is neither of them.

The same defect appears a second time, independently, in the RVC decoder,
which has no XLEN gate:

    80000048:     6010 : a2    <- 00000000 :      c.flw   x12, (x8)
    8000004a:     6602 : a2    <- 00000000 :      c.flwsp x12

Those need F. No ESP32-C part has an FPU, so both must be refused on every
target this project models, and rvcpp executes them.

## So a case carries two verdicts from two sources, and never blends them

Each case records:

* `requires` -- the extension letters the encoding needs, with the opcode,
  funct3 and funct5 fields it was read from. **Source: the ISA manual's
  encoding tables.** This is what rvcpp cannot tell us.
* `rvcpp` -- what the oracle actually did, captured by running it here.
  **Source: the oracle.** This is what the manual's tables do not tell us
  cheaply.

Whether a given case is legal is then *derived*, per target, by
`requires <= target`, rather than stored. That matters: a hand-written
"illegal on C3" column would be a third thing to keep in sync, and adding the
C5 or an RP2350 would mean editing every row instead of adding one target.

`docs/architectures.md` keeps evidence classes apart rather than averaging
them, and this is the same habit applied per case.

## Regenerating

    python tools/gen_rv32_tests.py

The corpus is committed, unlike the Armv6-M one, because the gating half needs
no oracle at all and would otherwise skip in exactly the situation it exists to
catch. Regenerating the `rvcpp` cells needs the oracle built; without it this
**exits 3 and says SKIPPED**, the same contract the rule checkers keep, rather
than emitting a corpus with the oracle's cells silently empty.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import struct
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests" / "rv32" / "corpus"
ORACLE = REPO / "third_party" / "rvcpp-build" / "rvcpp.exe"

#: rvcpp's own map, read from `third_party/hazard3/test/sim/rvcpp/main.cpp`:
#: `#define RAM_BASE 0x80000000u` and `RVCore core(mem, RAM_BASE + 0x40, ...)`.
#: Taken from the oracle rather than chosen, so a captured final state means
#: the same thing on both sides without a translation nobody would test.
RAM_BASE = 0x80000000
RESET_PC = RAM_BASE + 0x40
SANDBOX = RAM_BASE + 0x1000
RAM_SIZE = 0x4000

#: Seeded once. `rules/determinism.md` forbids nondeterministic calls in new
#: code, and a corpus that changed every run would make a regression and a
#: reroll indistinguishable.
SEED = 20260825

#: RISC-V ABI register names, in `x` order. rvcpp's trace prints these rather
#: than numbers, so reading it back needs the table.
ABI_NAMES = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)
NAME_TO_X = {name: index for index, name in enumerate(ABI_NAMES)}


class OracleMissing(Exception):
    """rvcpp is not built. A skip, never a silently empty corpus."""


# --- the encoding tables -----------------------------------------------------
#
# Fields, not literals. A hand-written list of hex words would be a table of
# answers with no way to check it; building each word from opcode, funct3 and
# funct5 means the citation in every case is the arithmetic that produced it.

OP = 0x33          # R-type register ALU
OP_IMM = 0x13      # I-type immediate ALU
AMO = 0x2F         # atomics -- the whole A extension lives behind this opcode

#: RV32I "Integer Register-Register Operations": funct7 0b0000000, except SUB
#: and SRA which use 0b0100000. Always present; `requires` is empty.
RV32I_OP = (
    ("add", 0x00, 0x0), ("sub", 0x20, 0x0), ("sll", 0x00, 0x1),
    ("slt", 0x00, 0x2), ("sltu", 0x00, 0x3), ("xor", 0x00, 0x4),
    ("srl", 0x00, 0x5), ("sra", 0x20, 0x5), ("or", 0x00, 0x6),
    ("and", 0x00, 0x7),
)

#: RV32M "Standard Extension for Integer Multiplication and Division": the same
#: opcode as RV32I_OP with funct7 0b0000001. The whole extension is that one
#: funct7 value, which is why a decoder without gating runs it by accident.
RV32M_OP = (
    ("mul", 0x0), ("mulh", 0x1), ("mulhsu", 0x2), ("mulhu", 0x3),
    ("div", 0x4), ("divu", 0x5), ("rem", 0x6), ("remu", 0x7),
)

#: RV32A "Standard Extension for Atomic Instructions": opcode AMO, funct3 0b010
#: for the `.w` width, funct5 selecting the operation. aq and rl are the two
#: bits below funct5 and are left 0 here -- ordering is not what this corpus is
#: about, and varying it would multiply every case by four for no new verdict.
RV32A_OP = (
    ("amoadd.w", 0x00), ("amoswap.w", 0x01), ("lr.w", 0x02), ("sc.w", 0x03),
    ("amoxor.w", 0x04), ("amoor.w", 0x08), ("amoand.w", 0x0C),
    ("amomin.w", 0x10), ("amomax.w", 0x14), ("amominu.w", 0x18),
    ("amomaxu.w", 0x1C),
)


def r_type(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, op: int) -> int:
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | op


def i_type(imm: int, rs1: int, funct3: int, rd: int, op: int) -> int:
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | op


def amo(funct5: int, rs2: int, rs1: int, rd: int) -> int:
    """One AMO word. aq and rl are the low two bits of the funct7 field."""
    return r_type(funct5 << 2, rs2, rs1, 0x2, rd, AMO)


def lui(rd: int, upper: int) -> int:
    return ((upper & 0xFFFFF) << 12) | (rd << 7) | 0x37


# --- the compressed encodings ------------------------------------------------
#
# Offsets are 0 wherever an instruction takes one. RVC scrambles immediate bits
# across the word, and this corpus is about which encodings a part accepts, not
# about immediate assembly -- a zero offset exercises the same decode path with
# no chance of a scrambling bug being baked into a case and then asserted.


def ci(funct3: int, imm6: int, rd: int, op: int) -> int:
    """CI format: funct3, imm[5], rd, imm[4:0], op."""
    return ((funct3 & 0x7) << 13) | (((imm6 >> 5) & 1) << 12) | \
           ((rd & 0x1F) << 7) | ((imm6 & 0x1F) << 2) | (op & 0x3)


def cr(funct4: int, rd: int, rs2: int) -> int:
    """CR format: funct4, rd/rs1, rs2, op=0b10."""
    return ((funct4 & 0xF) << 12) | ((rd & 0x1F) << 7) | ((rs2 & 0x1F) << 2) | 0x2


def ca(funct2: int, rd_prime: int, rs2_prime: int) -> int:
    """CA format: 100011, rd', funct2, rs2', op=0b01. Registers are x8-x15."""
    return (0b100011 << 10) | ((rd_prime & 0x7) << 7) | \
           ((funct2 & 0x3) << 5) | ((rs2_prime & 0x7) << 2) | 0x1


#: Each entry is (mnemonic, word, a function giving the expected effect on a
#: register file). The effect is what makes the table self-checking: the
#: generator runs every one of these through rvcpp and refuses to emit a case
#: whose observed write contradicts its own label. A mislabelled encoding in a
#: corpus is the same failure as an artefact class read off a filename.
def compressed_cases() -> tuple[tuple[str, int, object], ...]:
    return (
        ("c.nop", 0x0001, lambda r: {}),
        ("c.li x10, 7", ci(0b010, 7, 10, 0b01), lambda r: {10: 7}),
        ("c.addi x10, 3", ci(0b000, 3, 10, 0b01), lambda r: {10: mask(r[10] + 3)}),
        ("c.slli x10, 4", ci(0b000, 4, 10, 0b10), lambda r: {10: mask(r[10] << 4)}),
        ("c.mv x10, x11", cr(0b1000, 10, 11), lambda r: {10: r[11]}),
        ("c.add x10, x11", cr(0b1001, 10, 11), lambda r: {10: mask(r[10] + r[11])}),
        ("c.sub x10, x11", ca(0b00, 10 - 8, 11 - 8), lambda r: {10: mask(r[10] - r[11])}),
        ("c.xor x10, x11", ca(0b01, 10 - 8, 11 - 8), lambda r: {10: r[10] ^ r[11]}),
        ("c.or x10, x11", ca(0b10, 10 - 8, 11 - 8), lambda r: {10: r[10] | r[11]}),
        ("c.and x10, x11", ca(0b11, 10 - 8, 11 - 8), lambda r: {10: r[10] & r[11]}),
    )


#: Encodings that need an extension **no ESP32-C part has**, so they must be
#: refused on every target this project models -- and rvcpp executes them.
#:
#: In RV32 these four are the F-extension C.FLW/C.FLWSP; the same words are
#: RV64's C.LD/C.LDSP, which is why an RVC decoder with no XLEN gate lets them
#: through. Either reading makes them illegal here: nothing in the ESP32-C
#: family has an FPU, and none of these parts is RV64.
#:
#: The words are the ones `docs/HANDOFF_2026-08-24_boards-firmware-and-the-
#: armv6m-oracle.md` §3.2 measured, re-measured here: rvcpp executed 0x6010 and
#: 0x6602, writing a2, with no trap.
ABSENT_EXTENSION = (
    ("c.flw x12, 0(x8)", 0x6010, "F"),
    ("c.flw x13, 0(x8)", 0x6014, "F"),
    ("c.flwsp x12, 0(sp)", 0x6602, "F"),
    ("c.flwsp x13, 0(sp)", 0x6682, "F"),
)


def mask(value: int) -> int:
    return value & 0xFFFFFFFF


# --- driving the oracle ------------------------------------------------------


def setup_words(regs: dict[int, int]) -> list[int]:
    """`lui`/`addi` pairs that put `regs` into the register file.

    rvcpp has no way to be handed a register file, so the initial state has to
    be *executed* into it. `addi` sign-extends its 12-bit immediate, so the
    upper half is incremented when the lower half's bit 11 is set -- the same
    correction an assembler's `li` pseudo-instruction makes.
    """
    words: list[int] = []
    for number in sorted(regs):
        if number == 0:
            continue
        value = mask(regs[number])
        lower = value & 0xFFF
        upper = (value >> 12) & 0xFFFFF
        if lower & 0x800:
            upper = (upper + 1) & 0xFFFFF
        words.append(lui(number, upper))
        words.append(i_type(lower, number, 0x0, number, OP_IMM))
    return words


def run_oracle(regs: dict[int, int], word: int, width: int) -> dict:
    """What rvcpp does with one encoding, from its own trace.

    Returns `{"status": "executed", "writes": {...}}` or
    `{"status": "trapped", "cause": n}`. The trace prints ABI register names,
    so the write is mapped back through `NAME_TO_X`.
    """
    if not ORACLE.is_file():
        raise OracleMissing(f"{ORACLE} is not built")

    prologue = setup_words(regs)
    blob = bytearray(b"\x00" * 0x40)
    for entry in prologue:
        blob += struct.pack("<I", entry)
    target_pc = RESET_PC + 4 * len(prologue)
    blob += struct.pack("<I", word) if width == 32 else struct.pack("<H", word)
    blob += struct.pack("<H", 0x0001) * 4          # c.nop padding to land on

    with tempfile.TemporaryDirectory() as directory:
        binary = pathlib.Path(directory) / "case.bin"
        binary.write_bytes(bytes(blob))
        result = subprocess.run(
            [str(ORACLE), "--bin", str(binary),
             "--cycles", str(len(prologue) + 2), "--trace"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    lines = result.stdout.splitlines()
    wanted = f"{target_pc:08x}"
    for index, line in enumerate(lines):
        fields = line.split(":")
        if not fields or fields[0].strip().lower() != wanted:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if "Trap" in following:
            cause = following.split("<-")[1].split()[0] if "<-" in following else "?"
            return {"status": "trapped", "cause": cause}
        writes = {}
        if len(fields) > 2 and "<-" in fields[2]:
            name, _, value = fields[2].partition("<-")
            name = name.strip()
            if name not in NAME_TO_X:
                raise ValueError(
                    f"rvcpp wrote to {name!r}, which is not a RISC-V ABI register "
                    f"name. Trace line: {line!r}"
                )
            writes[NAME_TO_X[name]] = int(value.strip(), 16)
        return {"status": "executed", "writes": writes}

    raise ValueError(
        f"rvcpp never reached pc {wanted} for encoding {word:#010x}. "
        f"Ran {len(prologue) + 2} cycles over {len(prologue)} setup words. "
        f"stdout began: {result.stdout[:200]!r}"
    )


# --- building the cases ------------------------------------------------------

#: Interesting integers first, then seeded noise. The fixed head is there so a
#: sign boundary or a divide-by-zero is always covered rather than covered when
#: the seed happens to be kind.
CORNERS = (0, 1, 2, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0xFFFF, 0x10)


def operand_sets(count: int, rng: random.Random) -> list[tuple[int, int]]:
    pairs = [(a, b) for a in CORNERS[:4] for b in CORNERS[:4]]
    while len(pairs) < count:
        pairs.append((rng.getrandbits(32), rng.getrandbits(32)))
    return pairs[:count]


#: Zba "Address generation", the whole of it on RV32: funct7 0b0010000 with
#: three funct3 values under the same opcode as RV32I_OP. Encodings taken from
#: rvcpp's own table so the corpus and the oracle cannot disagree about the
#: bits before they disagree about the answer --
#: `RVOPC_SH1ADD_BITS = 0b0010000_00000_00000_010_00000_0110011`
#: (third_party/hazard3/test/sim/rvcpp/include/encoding/rv_opcodes.h:149).
#:
#: The RP2350's datasheet ISA string contains `_zba_`; neither ESP32-C part's
#: does. So this family is the first in the corpus where the three targets do
#: not all give the same verdict, and rvcpp gives all three the same one.
RV32ZBA_OP = (
    ("sh1add", 0x2), ("sh2add", 0x4), ("sh3add", 0x6),
)

#: Zbs "Single-bit instructions", as (mnemonic, funct7, funct3). Unlike Zba
#: the funct7 does not decide on its own: set, clear and invert share funct3
#: 001 and differ by funct7, while extract is funct3 101 under 0x24 only. Both
#: fields are in `requires_source` for that reason -- a case citing only the
#: funct7 would describe three encodings.
#:
#: The immediate forms are the same two fields over OP_IMM, sharing funct3
#: with SLLI and SRLI/SRAI. That overlap is the interesting half: opening it
#: had to leave RV64's six-bit shift shut, and `absent_extension` does not
#: cover that because it is not an extension question.
RV32ZBS_OP = (
    ("bset", 0x14, 0x1), ("bclr", 0x24, 0x1),
    ("binv", 0x34, 0x1), ("bext", 0x24, 0x5),
)


#: Zcb, and only Zcb of the three Zc groups, because the corpus's trace
#: model carries one writeback per instruction and that is all rvcpp prints:
#: a cm.pop that reloads thirteen registers shows only its sp write
#: (measured 2026-08-31 -- the ra and s0 reloads appear nowhere in the
#: trace). Zcmp and Zcmt are hand-verified against the Zc specification in
#: `tests/riscv32/test_zc.py` instead; every Zcb operation is a single
#: writeback and fits here.
#:
#: Entries are (mnemonic, encoding, requires, why). The three unaries that
#: also need Zbb split the targets: the RP2350 has Zbb and runs them (OH-208
#: modelled it), the ESP32-C5 has Zcb without Zbb and must refuse them, and
#: rvcpp -- which gates nothing -- executes them for both, which is exactly
#: the divergence the two-verdict design exists to record.
RV32ZCB = (
    ("c.lbu x9, 0(x8)", 0x8004, ["Zcb"],
     "quadrant 0 funct3=100 [12:10]=000; uimm[0] at bit 6, uimm[1] at bit 5"),
    ("c.lbu x9, 3(x8)", 0x8064, ["Zcb"], "both offset bits set: three"),
    ("c.lhu x9, 0(x8)", 0x8404, ["Zcb"], "[12:10]=001 with bit 6 clear"),
    ("c.lh x9, 0(x8)", 0x8444, ["Zcb"], "[12:10]=001 with bit 6 set: signed"),
    ("c.sb x9, 0(x8)", 0x8804, ["Zcb"], "[12:10]=010"),
    ("c.sh x9, 0(x8)", 0x8C04, ["Zcb"], "[12:10]=011 with bit 6 clear"),
    ("c.zext.b x8", 0x9C61, ["Zcb"], "quadrant 1 unary slot 000"),
    ("c.not x8", 0x9C75, ["Zcb"], "unary slot 101"),
    ("c.mul x8, x9", 0x9C45, ["Zcb", "M"],
     "funct2 10; the expansion rides the 32-bit mul and its M gate"),
    ("c.sext.b x8", 0x9C65, ["Zcb", "Zbb"], "unary slot 001: Zbb only"),
    ("c.zext.h x8", 0x9C69, ["Zcb", "Zbb"], "unary slot 010: Zbb only"),
    ("c.sext.h x8", 0x9C6D, ["Zcb", "Zbb"], "unary slot 011: Zbb only"),
)


def build(count: int, want_oracle: bool) -> dict[str, list[dict]]:
    rng = random.Random(SEED)
    families: dict[str, list[dict]] = {}

    def emit(family: str, mnemonic: str, word: int, width: int,
             requires: list[str], cite: str, regs: dict[int, int]) -> None:
        case = {
            "mnemonic": mnemonic,
            "encoding": f"{word:#0{2 + width // 4}x}",
            "width": width,
            "requires": requires,
            "requires_source": cite,
            "initial": {str(k): f"{mask(v):#010x}" for k, v in sorted(regs.items())},
        }
        if want_oracle:
            case["rvcpp"] = run_oracle(regs, word, width)
        families.setdefault(family, []).append(case)

    for mnemonic, funct7, funct3 in RV32I_OP:
        for a, b in operand_sets(count, rng):
            word = r_type(funct7, 11, 10, funct3, 12, OP)
            emit("rv32i_op", f"{mnemonic} x12, x10, x11", word, 32, [],
                 f"RV32I Register-Register: opcode={OP:#04x} funct3={funct3:#03b} "
                 f"funct7={funct7:#04x}", {10: a, 11: b})

    for mnemonic, funct3 in RV32M_OP:
        for a, b in operand_sets(count, rng):
            word = r_type(0x01, 11, 10, funct3, 12, OP)
            emit("rv32m_op", f"{mnemonic} x12, x10, x11", word, 32, ["M"],
                 f"RV32M: opcode={OP:#04x} funct7=0b0000001 funct3={funct3:#05b} "
                 f"-- the extension is that one funct7 value", {10: a, 11: b})

    for mnemonic, funct3 in RV32ZBA_OP:
        for a, b in operand_sets(count, rng):
            word = r_type(0x10, 11, 10, funct3, 12, OP)
            emit("rv32zba", f"{mnemonic} x12, x10, x11", word, 32, ["Zba"],
                 f"Zba address generation: opcode={OP:#04x} funct7=0b0010000 "
                 f"funct3={funct3:#05b} -- the RP2350 datasheet 3.8 ISA string "
                 f"has _zba_ and no ESP32-C part's does", {10: a, 11: b})

    for mnemonic, funct7, funct3 in RV32ZBS_OP:
        for a, b in operand_sets(count, rng):
            emit("rv32zbs", f"{mnemonic} x12, x10, x11",
                 r_type(funct7, 11, 10, funct3, 12, OP), 32, ["Zbs"],
                 f"Zbs single-bit: opcode={OP:#04x} funct7={funct7:#09b} "
                 f"funct3={funct3:#05b} -- both fields decide, since funct3 001 "
                 f"and 101 mean different instructions under the same funct7",
                 {10: a, 11: b})
        for a, _ in operand_sets(count, rng):
            # The immediate form: same funct7 and funct3 over OP_IMM, with the
            # shift-amount field where rs2 sits.
            shamt = a & 0x1F
            emit("rv32zbs", f"{mnemonic}i x12, x10, {shamt}",
                 r_type(funct7, shamt, 10, funct3, 12, OP_IMM), 32, ["Zbs"],
                 f"Zbs single-bit immediate: opcode={OP_IMM:#04x} "
                 f"funct7={funct7:#09b} funct3={funct3:#05b}, shamt in the rs2 "
                 f"field -- the same funct3 SLLI and SRLI use",
                 {10: a})

    for mnemonic, funct5 in RV32A_OP:
        for a, _ in operand_sets(count, rng):
            rs2 = 0 if mnemonic == "lr.w" else 11
            word = amo(funct5, rs2, 10, 12)
            emit("rv32a", f"{mnemonic} x12, x11, (x10)", word, 32, ["A"],
                 f"RV32A: opcode=AMO({AMO:#04x}) funct3=0b010 (.w) "
                 f"funct5={funct5:#07b} aq=0 rl=0", {10: SANDBOX, 11: a})

    for mnemonic, word, _effect in compressed_cases():
        emit("rv32c", mnemonic, word, 16, ["C"],
             "RV32C: 16-bit quadrant encoding, op field in bits [1:0]",
             {10: 0x1234, 11: 0x00FF, 2: SANDBOX, 8: SANDBOX})

    for mnemonic, word, requires, why in RV32ZCB:
        for a, b in operand_sets(count // 2 or 1, rng):
            emit("rv32zcb", mnemonic, word, 16, list(requires),
                 f"Zcb (Zc spec v1.0.4): {why}",
                 {8: SANDBOX if "(x8)" in mnemonic else a, 9: b & 0xFF})

    for mnemonic, word, extension in ABSENT_EXTENSION:
        emit("absent_extension", mnemonic, word, 16, [extension],
             "RV32C quadrant with funct3=0b011: C.FLW/C.FLWSP, which need F. "
             "The same words are RV64's C.LD/C.LDSP. No ESP32-C part has an "
             "FPU and none is RV64, so both readings make this illegal here.",
             {2: SANDBOX, 8: SANDBOX, 12: 0, 13: 0})

    return families


def check_compressed_labels() -> list[str]:
    """Run every compressed encoding past rvcpp and confirm its label.

    RVC scrambles immediates and register fields, so a hand-built word is easy
    to get wrong and impossible to notice once it is sitting in a corpus being
    asserted against. This predicts each one's effect and compares. A
    disagreement is a hard error naming the encoding, not a warning.
    """
    regs = {10: 0x1234, 11: 0x00FF, 2: SANDBOX, 8: SANDBOX}
    confirmed = []
    for mnemonic, word, effect in compressed_cases():
        observed = run_oracle(regs, word, 16)
        if observed["status"] != "executed":
            raise ValueError(
                f"{mnemonic} ({word:#06x}): rvcpp trapped with cause "
                f"{observed.get('cause')}, so the encoding is wrong -- rvcpp "
                f"has no C gating and would have run a correct one."
            )
        expected = {int(k): mask(v) for k, v in effect(regs).items()}
        actual = {k: v for k, v in observed["writes"].items() if k != 0}
        if actual != expected:
            raise ValueError(
                f"{mnemonic} ({word:#06x}): rvcpp wrote {actual!r}, this table "
                f"predicted {expected!r}. The encoding does not mean what the "
                f"mnemonic says. Fix the field packing, not the prediction."
            )
        confirmed.append(mnemonic)
    return confirmed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--count", type=int, default=16,
        help="operand sets per encoding (default 16)")
    args = parser.parse_args()

    if not ORACLE.is_file():
        print(
            f"SKIPPED: no rvcpp at {ORACLE}.\n"
            "  git clone https://github.com/Wren6991/Hazard3 third_party/hazard3\n"
            "  cd third_party/hazard3/test/sim/rvcpp && make\n"
            "The gating half of this corpus needs no oracle, but the rvcpp "
            "cells do, and emitting them empty would look like agreement.",
            file=sys.stderr)
        return 3

    confirmed = check_compressed_labels()
    print(f"{len(confirmed)} compressed encodings confirmed against rvcpp")

    families = build(args.count, want_oracle=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    total = 0
    for family, cases in sorted(families.items()):
        path = CORPUS / f"{family}.json"
        path.write_text(json.dumps(cases, indent=1) + "\n", encoding="utf-8")
        print(f"  {family:<18} {len(cases):>5} cases  {path.name}")
        total += len(cases)
    print(f"{total} cases in {len(families)} families -> {CORPUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
