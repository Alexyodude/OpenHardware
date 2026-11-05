#!/usr/bin/env python3
# OpenHardware - Armv7E-M execution vectors, from two emulators that share no code.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Generate the fixtures `tests/cortexm0/test_thumb2_exec.py` checks the core against.

## Why two oracles, and why these two

OH-50 stopped the Cortex-M4 work at the decoder for one reason: there was no
execution oracle on this machine, and an interpreter checked only against tests
its own author wrote is the evidence this repository declines to produce. The
ticket that followed it, OH-64, asks for "an oracle that is not QEMU alone".

* **Unicorn 2.1.4** is QEMU's TCG front end with the system emulation cut away.
  It is the obvious oracle and it is the QEMU lineage, so on its own it is
  exactly what the ticket rules out.
* **icicle-emu 0.0.11** is not a QEMU at all. It executes Ghidra's SLEIGH
  processor specification for Thumb-2 -- a separate team writing a separate
  description of the same manual, in a separate language, for a decompiler.

**A case is kept only where both agree**, on every register, all four flags
and every byte of the sandbox. Where they disagree the case is dropped and
counted rather than adjudicated, for the reason `docs/architectures.md` 4.2
gives: two oracles that differ say *that* one is wrong, not which. The counts
are printed, so a run that agrees on suspiciously little is visible.

Both are **tool dependencies, never runtime ones**, and the output is
committed, so the test runs on a machine that has neither -- the same
arrangement `tools/sweep_thumb2.py` has with objdump.

    pip install unicorn==2.1.4 icicle-emu==0.0.11
    python -m tools.m4_oracle               # regenerate everything
    python -m tools.m4_oracle --survey      # which mnemonics, how often agreed

## What each oracle got wrong about the other's assumptions

Measured on this machine, and each one shaped the generator below:

* **Unicorn does not count an `IT` as an instruction.** QEMU folds it into the
  instruction it governs, so `count=2` from an `IT` runs three. IT-block cases
  therefore run Unicorn to an *end address*, which is exact because nothing
  inside a generated block branches.
* **Unicorn fetches ahead.** A one-instruction run that branches off the code
  page faults on the fetch of the target, which no Cortex-M4 does. A fetch
  hook maps the page it wanted, empty, and the count stops the run before
  anything there executes.
* **Unicorn ignores execute-only pages**; icicle honours them. A load from the
  code page therefore disagrees and drops out, which is the right result for a
  reason of its own: the test's core would read whatever bytes it happened to
  hold there.
* **icicle caches what it decoded, by address, across rewrites.** Writing a
  new instruction where an old one was, even after unmapping and remapping
  the page, runs the *old* one -- measured: three different `adds r0, #n`
  in turn all added 1. Only `reset()` drops the cache, and it unmaps
  everything with it, so every case rebuilds the map from nothing. That
  costs 2 ms; a new instance would cost 0.1 s.
* **icicle refuses a write to an execute-only page** -- SelfModifyingCode --
  so the code page is mapped writable, filled, and only then protected.

## Layout, which the test rebuilds exactly

    CODE     0x20001000  4 KB   the instructions under test
    SANDBOX  0x20008000  32 KB  data, filled with `sandbox_byte`

Nothing else is mapped, so an access anywhere else faults in both oracles and
the case is dropped. The fill is a function of the address rather than zeros,
because a load that returned zero from the wrong address would agree with a
load that returned zero from the right one.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import pathlib
import random
import struct
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.cortexm0.disasm import Profile, decode  # noqa: E402

OUT = REPO / "tests" / "cortexm0" / "m4"

#: The blink is the nRF52840 board's evidence as well as a trace, and
#: `tools/check_board_claims.py` requires the image a `FIRMWARE_VERIFIED` test
#: names to sit beside that test -- so it lives with the board test, and the
#: trace records where, relative to the repository, rather than beside `OUT`.
BLINK = REPO / "tests" / "webui" / "nrf52840" / "blink.bin"

CODE = 0x20001000
CODE_SIZE = 0x1000
SANDBOX = 0x20008000
SANDBOX_SIZE = 0x8000

#: Fixed, so the committed fixture is reproducible from the tool. Changing it
#: is a regeneration, and the diff says so.
SEED = 0x4D34

#: Per-mnemonic cap on kept cases. Uniform sampling of the encoding space
#: weights a form by how many bits its operands have, which is not how often it
#: is wrong: `ldr.w` would outnumber `clz` a hundred to one. Capping per
#: mnemonic spreads the vectors across the decoder's groups instead. Sixty
#: rather than more because the fixture is committed: at 120 it was the largest
#: test file in the repository, twice the AVR corpus, for operands that are
#: random either way.
PER_MNEMONIC = 60

#: How many candidates to try before giving up on filling the caps. A bound,
#: so a mnemonic the oracles never agree on cannot hang the run.
ATTEMPTS = 400_000

#: Mnemonics the core refuses under Armv7E-M, each with the reason, and which
#: the generator therefore never emits. **The test reads this table too**: an
#: encoding here must come back `Unimplemented`, so "not covered by vectors"
#: and "refused" are one list and cannot drift apart.
#:
#: The sat and DSP group is refused rather than half-done because every one of
#: them can set the **Q** flag, which `Cpu::set_apsr` does not model. Agreement
#: filtering would keep only the cases where Q stayed clear, and an
#: implementation passing those would be wrong on exactly the inputs that
#: saturate. Most of the group the decoder does not name either, and those the
#: core refuses by reaching the end of its decode; the four it does name are
#: the ones the test can draw.
REFUSED: dict[str, str] = {
    **{m: "can set Q, which the core does not model" for m in (
        "ssat", "usat", "ssat16", "usat16", "qadd", "qsub", "qdadd", "qdsub",
        "qadd16", "qadd8", "qasx", "qsax", "qsub16", "qsub8",
        "uqadd16", "uqadd8", "uqasx", "uqsax", "uqsub16", "uqsub8",
        "smlabb", "smlabt", "smlatb", "smlatt", "smlad", "smladx",
        "smlawb", "smlawt", "smlsd", "smlsdx", "smuad", "smuadx",
    )},
    **{m: "sets or reads the GE flags, which the core does not model" for m in (
        "sadd16", "sadd8", "sasx", "ssax", "ssub16", "ssub8",
        "uadd16", "uadd8", "uasx", "usax", "usub16", "usub8", "sel",
    )},
    **{m: "needs the exclusive monitor, which the core does not model" for m in (
        "ldrex", "ldrexb", "ldrexh", "strex", "strexb", "strexh", "clrex",
    )},
    # The Armv6-M core already stops on SVC and BKPT and says why in exec.cc;
    # an Armv7-M part takes them exactly as an Armv6-M one does, so nothing
    # about the wider profile changes that answer.
    **{m: "enters an exception this project has no handler for" for m in (
        "svc", "bkpt", "udf",
    )},
}

#: Wide encodings the core refuses whose mnemonic is also a narrow one it runs,
#: so they cannot go in `REFUSED`. `blx label` is the only one: it is ARMv7-A's
#: switch into ARM state, which an M-profile part does not have.
WIDE_REFUSED: dict[str, str] = {
    "blx": "the immediate form switches to ARM state, which Armv7-M lacks",
}

#: Mnemonics the core *executes* that are kept out of the vectors anyway, each
#: because a single step in these two oracles cannot show what it did. They are
#: the Armv6-M core's own code path, unchanged, and that core's tests cover them.
UNVECTORED: dict[str, str] = {
    **{m: "waits for an event, which ends an oracle's run rather than a step"
       for m in ("wfi", "wfe", "sev", "yield")},
    **{m: "changes PRIMASK, which neither oracle's state here compares"
       for m in ("cpsid", "cpsie")},
}

#: Never inside a generated `IT` block. A branch may legally be the *last*
#: instruction of one, but then the block's end address is not where Unicorn
#: stops, and the single-instruction cases cover every branch anyway.
CONTROL = frozenset({"b", "bl", "bx", "blx", "cbz", "cbnz", "tbb", "tbh"})


def sandbox_byte(address: int) -> int:
    """What the untouched sandbox holds at `address`. Imported by the test."""
    return ((address * 0x9E3779B1) >> 13) & 0xFF


def sandbox_image() -> bytes:
    return bytes(sandbox_byte(SANDBOX + i) for i in range(SANDBOX_SIZE))


def mnemonic(text: str) -> str:
    """The bare operation: `ldr.w r0, [r1]` -> `ldr`, `itte ls` -> `it`.

    Width suffixes go, and so does a flag-setting `s` only where the decoder
    puts one on a mnemonic that also exists without it -- `adds` and `add` are
    one family for coverage, as are `muls` and `mul`.
    """
    word = text.split()[0].split(".")[0]
    if word.startswith("it") and set(word[2:]) <= {"t", "e"}:
        return "it"
    return word


def _family(text: str) -> str:
    word = mnemonic(text)
    for base in ("ands", "bics", "orrs", "orns", "eors", "adds", "adcs",
                 "sbcs", "subs", "rsbs", "movs", "mvns", "lsls", "lsrs",
                 "asrs", "rors", "rrxs", "muls", "negs"):
        if word == base:
            return base[:-1]
    return word


def _conditionless(word: str) -> str:
    # `ldrls` inside an IT block is `ldr`. The two-letter codes are stripped
    # only where what remains is itself a word the table knows, so `bls` is a
    # `b` and `cls` is not invented.
    for code in ("eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls",
                 "ge", "lt", "gt", "le", "hs", "lo"):
        if word.endswith(code) and len(word) > 2:
            return word[:-2]
    return word


def _random_registers(rng: random.Random, regime: int) -> list[int]:
    """r0-r12 and LR. SP and PC are set by the caller.

    Two regimes, because one cannot serve both halves of the instruction set.
    Uniformly random values exercise the arithmetic and send nearly every
    load and store off the map. The second puts each register either near the
    middle of the sandbox -- far enough in that an imm12 offset either way, or
    a 16-register `stmdb`, stays inside -- or at a small integer that an
    index or a shift count would be.
    """
    out = []
    for _ in range(14):
        if regime == 0:
            out.append(rng.getrandbits(32))
        elif rng.getrandbits(1):
            out.append(SANDBOX + 0x2000 + rng.randrange(0x4000))
        else:
            out.append(rng.choice((0, 1, 2, 3, 4, 7, 8, 31, 32, 33, 0xFF,
                                   0xFFFFFFFF, 0x80000000, 0x7FFFFFFF,
                                   rng.randrange(64))))
    return out


def initial_state(rng: random.Random) -> tuple[list[int], int]:
    regime = rng.getrandbits(1)
    low = _random_registers(rng, regime)
    regs = low[:13] + [SANDBOX + 0x4000 + 4 * rng.randrange(0x400), low[13], CODE]
    apsr = rng.getrandbits(4) << 28
    return regs, apsr


# --- the encodings --------------------------------------------------------


def _named(hw1: int, hw2: int) -> tuple[str, int] | None:
    text, width = decode(hw1, CODE, hw2, Profile.V7EM)
    if text.startswith((".word", ".short")):
        return None
    word = _conditionless(mnemonic(text))
    for name in {word, mnemonic(text)}:
        if name in REFUSED or name in UNVECTORED:
            return None
        if width == 4 and name in WIDE_REFUSED:
            return None
    if width == 4 and _unpredictable_pc(word, text):
        return None
    if width == 4 and word in TWICE_NAMED and (hw1 ^ hw2) & 0xF:
        return None
    if _writes_back_over_itself(word, text):
        return None
    if _two_destinations_alike(word, text):
        return None
    return text, width


# Wide forms that write two registers at once. Naming one register for both
# is UNPREDICTABLE, and unlike the write-back forms above the oracles do NOT
# disagree on these -- both keep the second write -- so no survey found them.
# The interpreter running against these vectors did, by refusing all 17 that
# had been kept: agreement between two emulators on an UNPREDICTABLE form is
# a shared choice, not the architecture, and is not something to test against.
TWO_DESTINATIONS = frozenset({"ldrd", "smull", "umull", "smlal", "umlal"})


def _two_destinations_alike(word: str, text: str) -> bool:
    if word not in TWO_DESTINATIONS:
        return False
    operands = text.split(None, 1)[1].split(",")
    first, second = (_registers(part) for part in operands[:2])
    return first == second


# Wide forms that carry Rm in both halfwords. The architecture calls a
# mismatch UNPREDICTABLE, and the two oracles prove it by reading different
# copies: on `fa91 f389` icicle reversed r1 and Unicorn r9. The decoder prints
# the first halfword's, which is what objdump does.
TWICE_NAMED = frozenset({"clz", "rbit", "rev", "rev16", "revsh"})


def _writes_back_over_itself(word: str, text: str) -> bool:
    """A write-back to a base register the same instruction loads or stores.

    `ldrd r2, r3, [r3], #-432` both loads r3 and writes the incremented base
    into it, and `stmia.w sp!, {..}` with the base in its own list stores a
    value the architecture does not fix. Both are UNPREDICTABLE (or UNKNOWN,
    for the narrow `stmia` whose base is not the lowest listed), and the
    oracles disagreed on every family of them the second survey drew.
    """
    if not ("!" in text or "], #" in text):
        return False
    operands = text.split(None, 1)[1] if " " in text or "\t" in text else ""
    if word.startswith(("ldm", "stm")):
        base, _, listed = operands.partition("!")
    else:
        listed, _, address = operands.partition("[")
        base = address.split(",")[0].split("]")[0]
    named = _registers(base)
    return bool(named) and named <= _registers(listed)


def _registers(listing: str) -> set[str]:
    """The register names in an operand list. The decoder writes no ranges."""
    names = {part.strip(" {}") for part in listing.split(",")}
    return {ALIASES.get(n, n) for n in names if n}


# The disassembler's names for r9-r12, so a base and a list compare as one.
ALIASES = {"sb": "r9", "sl": "r10", "fp": "r11", "ip": "r12"}


def _unpredictable_pc(word: str, text: str) -> bool:
    """A wide form naming PC where the architecture leaves the result open.

    The decoder names these, because objdump does and a disassembler's job is
    to say what the bits are. But `orn pc, r1, r2` or `asr.w r5, pc, pc` is
    UNPREDICTABLE, and two oracles agreeing on one says only that they made the
    same choice. The forms that are *defined* stay in: a load into PC, which is
    how `pop.w` returns, and a load list that ends in PC. A store list holding
    PC is UNPREDICTABLE and goes.
    """
    head, _, tail = text.partition("{")
    listed, _, after = tail.partition("}")
    if word.startswith("stm") and "pc" in listed:
        return True
    rest = head + after
    if "pc" not in rest:
        return False
    operands = rest.split(None, 1)[1] if len(rest.split(None, 1)) > 1 else ""
    return not (word == "ldr" and operands.startswith("pc,"))


def random_instruction(rng: random.Random, *, wide: bool | None = None,
                       in_it: bool = False) -> tuple[bytes, str] | None:
    """One named instruction as `(bytes, text)`, or None if the draw missed.

    Wide 60% of the time. The narrow set is smaller and every draw of it names
    something, so a lower share still fills its caps, and a higher one starved
    the wide register-group forms the first survey found thin.
    """
    if wide is None:
        wide = rng.random() < 0.6
    if wide:
        hw1 = 0xE800 + rng.randrange(0x1800)
        hw2 = rng.getrandbits(16)
    else:
        hw1 = rng.getrandbits(16)
        hw2 = 0
    named = _named(hw1, hw2)
    if named is None:
        return None
    text, width = named
    if (width == 4) != wide:
        return None
    if in_it:
        word = _conditionless(mnemonic(text))
        if word in CONTROL or word == "it" or "pc" in text:
            return None
    data = struct.pack("<HH", hw1, hw2) if width == 4 else struct.pack("<H", hw1)
    return data, text


def mutate(rng: random.Random, code: bytes) -> tuple[bytes, str] | None:
    """A wide encoding near `code`: each bit below the top five flipped at 1/8.

    Uniform draws reach a mnemonic in proportion to how much of the encoding
    space it owns, and `sdiv`, `rbit` and `clz` own almost none -- the first
    full survey kept zero, zero and two of them. Flipping a few bits of one
    that already decoded mostly lands on the same instruction with other
    operands, which is what fills the cap. The top five bits stay, so the
    result is still wide; the decoder still names it or it is dropped, so no
    encoding gets in that a uniform draw could not have produced.
    """
    hw1, hw2 = struct.unpack("<HH", code)
    word = (hw1 << 16) | hw2
    for bit in range(27):
        if rng.random() < 0.125:
            word ^= 1 << bit
    hw1, hw2 = word >> 16, word & 0xFFFF
    named = _named(hw1, hw2)
    if named is None or named[1] != 4:
        return None
    return struct.pack("<HH", hw1, hw2), named[0]


def random_it_block(rng: random.Random) -> tuple[bytes, str, int] | None:
    """An `IT` and the instructions it governs, as `(bytes, text, steps)`.

    `firstcond` never AL: `it al` with an else arm is UNPREDICTABLE, and with
    none it is a no-op that the single-instruction cases cover.
    """
    firstcond = rng.randrange(14)
    mask = 1 + rng.randrange(15)
    count = 4 - ((mask & -mask).bit_length() - 1)
    head = 0xBF00 | (firstcond << 4) | mask
    text, _ = decode(head, CODE, None, Profile.V7EM)
    data = struct.pack("<H", head)
    parts = [text]
    for _ in range(count):
        for _ in range(64):
            drawn = random_instruction(rng, in_it=True)
            if drawn is not None:
                break
        else:
            return None
        data += drawn[0]
        parts.append(drawn[1])
    return data, "; ".join(parts), 1 + count


# --- the oracles ----------------------------------------------------------


class UnicornM4:
    def __init__(self) -> None:
        import unicorn
        from unicorn import arm_const

        self._u = unicorn
        self._a = arm_const
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM,
                             unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(arm_const.UC_CPU_ARM_CORTEX_M4)
        self.uc.mem_map(CODE, CODE_SIZE, unicorn.UC_PROT_ALL)
        self.uc.mem_map(SANDBOX, SANDBOX_SIZE,
                        unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self._extra: list[int] = []
        self.uc.hook_add(unicorn.UC_HOOK_MEM_FETCH_UNMAPPED, self._map_target)
        a = arm_const
        self._regs = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(13)] + [
            a.UC_ARM_REG_SP, a.UC_ARM_REG_LR, a.UC_ARM_REG_PC]

    def _map_target(self, uc, access, address, size, value, data) -> bool:
        # See the module docstring: QEMU translates the branch target before
        # the count stops it, and a Cortex-M4 does not fetch there at all. The
        # page is mapped no-access-but-execute and empty, and is unmapped
        # again after the case.
        page = address & ~0xFFF
        if page in self._extra or len(self._extra) > 4:
            return False
        uc.mem_map(page, 0x1000, self._u.UC_PROT_EXEC | self._u.UC_PROT_READ)
        self._extra.append(page)
        return True

    def run(self, code: bytes, regs: list[int], apsr: int, steps: int,
            sandbox: bytes, *, to_end: bool) -> dict | None:
        uc, a = self.uc, self._a
        for page in self._extra:
            uc.mem_unmap(page, 0x1000)
        self._extra.clear()
        uc.mem_write(CODE, b"\xff" * CODE_SIZE)
        uc.mem_write(CODE, code)
        # The same trap as icicle's, in QEMU's form: a translation block
        # outlives a write to the bytes it was translated from. Without this
        # every single-instruction case ran the *previous* case's code.
        uc.ctl_remove_cache(CODE, CODE + CODE_SIZE)
        uc.mem_write(SANDBOX, sandbox)
        for reg, value in zip(self._regs, regs, strict=True):
            uc.reg_write(reg, value)
        uc.reg_write(a.UC_ARM_REG_XPSR, apsr | (1 << 24))
        try:
            if to_end:
                uc.emu_start(CODE | 1, CODE + len(code))
            else:
                uc.emu_start(CODE | 1, 0xFFFFFFFE, count=steps)
        except self._u.UcError:
            return None
        xpsr = uc.reg_read(a.UC_ARM_REG_XPSR)
        out = [uc.reg_read(reg) & 0xFFFFFFFF for reg in self._regs]
        out[15] &= ~1
        return {
            "regs": out,
            "apsr": xpsr & 0xF0000000,
            # Q is bit 27 and GE 19:16. A case that set either is one the core
            # cannot represent; REFUSED keeps the known ones out, this catches
            # any the table missed.
            "unmodelled": xpsr & 0x080F0000,
            "sandbox": bytes(uc.mem_read(SANDBOX, SANDBOX_SIZE)),
        }


class IcicleM4:
    FLAGS = (("NG", 31), ("ZR", 30), ("CY", 29), ("OV", 28))

    def __init__(self) -> None:
        import icicle

        self._i = icicle
        self.ic = icicle.Icicle("thumbv7em", jit=False)
        self._names = [f"r{i}" for i in range(13)] + ["sp", "lr", "pc"]

    def run(self, code: bytes, regs: list[int], apsr: int, steps: int,
            sandbox: bytes) -> dict | None:
        ic, protect = self.ic, self._i.MemoryProtection
        ic.reset()
        ic.mem_map(CODE, CODE_SIZE, protect.ReadWrite)
        ic.mem_write(CODE, b"\xff" * CODE_SIZE)
        ic.mem_write(CODE, code)
        ic.mem_protect(CODE, CODE_SIZE, protect.ExecuteOnly)
        ic.mem_map(SANDBOX, SANDBOX_SIZE, protect.ReadWrite)
        ic.mem_write(SANDBOX, sandbox)
        # A fresh instance reads contextreg as zero; that is where SLEIGH keeps
        # the IT state, so a case that faulted mid-block cannot leak into the
        # next one.
        ic.reg_write("contextreg", 0)
        ic.reg_write("Q", 0)
        for name, value in zip(self._names, regs, strict=True):
            # **Without the Thumb bit.** icicle takes the PC as an address and
            # faults ExecUnaligned on an odd one; Unicorn wants the bit set.
            ic.reg_write(name, value & ~1 if name == "pc" else value)
        for name, bit in self.FLAGS:
            ic.reg_write(name, (apsr >> bit) & 1)
        status = ic.step(steps)
        if status != self._i.RunStatus.InstructionLimit:
            return None
        out = [ic.reg_read(name) & 0xFFFFFFFF for name in self._names]
        out[15] &= ~1
        flags = 0
        for name, bit in self.FLAGS:
            flags |= (ic.reg_read(name) & 1) << bit
        return {
            "regs": out,
            "apsr": flags,
            "unmodelled": (ic.reg_read("Q") & 1) << 27,
            "sandbox": bytes(ic.mem_read(SANDBOX, SANDBOX_SIZE)),
        }


def writes(before: bytes, after: bytes) -> list[list]:
    """Changed sandbox bytes as `[address, "hex"]` runs."""
    runs: list[list] = []
    index = 0
    while index < len(before):
        if before[index] == after[index]:
            index += 1
            continue
        start = index
        while index < len(before) and before[index] != after[index]:
            index += 1
        runs.append([SANDBOX + start, after[start:index].hex()])
    return runs


# --- generation -----------------------------------------------------------


def generate(attempts: int = ATTEMPTS, per_mnemonic: int = PER_MNEMONIC,
             seed: int = SEED) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    uni, ice = UnicornM4(), IcicleM4()
    sandbox = sandbox_image()
    kept: list[dict] = []
    per: collections.Counter[str] = collections.Counter()
    tried: collections.Counter[str] = collections.Counter()
    why: collections.Counter[str] = collections.Counter()
    # Per family, so a survey says WHICH mnemonics the oracles split on and
    # not only how often: a disagreement concentrated in one family is an
    # UNPREDICTABLE form the filter has not learnt, spread thin it is noise.
    why_by: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter)
    # Wide encodings that decoded, per family, for `mutate` to start from.
    seeds: dict[str, list[bytes]] = collections.defaultdict(list)

    for _ in range(attempts):
        thin = [k for k, found in seeds.items() if per[k] < per_mnemonic]
        if thin and rng.random() < 0.5:
            near = mutate(rng, rng.choice(seeds[rng.choice(thin)]))
            if near is None:
                continue
            code, text = near
            steps = 1
            key = _family(text)
        elif rng.random() < 0.15:
            drawn = random_it_block(rng)
            if drawn is None:
                continue
            code, text, steps = drawn
            key = "it"
        else:
            single = random_instruction(rng)
            if single is None:
                continue
            code, text = single
            steps = 1
            key = _family(text)
        if per[key] >= per_mnemonic:
            continue
        if len(code) == 4 and steps == 1 and len(seeds[key]) < 64:
            seeds[key].append(code)
        tried[key] += 1
        regs, apsr = initial_state(rng)
        theirs = uni.run(code, regs, apsr, steps, sandbox, to_end=steps > 1)
        ours = ice.run(code, regs, apsr, steps, sandbox)
        reason = None
        if theirs is None or ours is None:
            reason = "faulted in " + ("both" if theirs is ours else
                                      "unicorn" if theirs is None else "icicle")
        elif theirs["unmodelled"] or ours["unmodelled"]:
            reason = "set Q or GE"
        elif (theirs["regs"], theirs["apsr"], theirs["sandbox"]) != (
                ours["regs"], ours["apsr"], ours["sandbox"]):
            reason = "disagreed"
        if reason is not None:
            why[reason] += 1
            why_by[key][reason] += 1
            continue
        per[key] += 1
        kept.append({
            "text": text,
            "code": code.hex(),
            "steps": steps,
            "regs": regs,
            "apsr": apsr,
            "expect": {
                "regs": theirs["regs"],
                "apsr": theirs["apsr"],
                "writes": writes(sandbox, theirs["sandbox"]),
            },
        })
    stats = {"kept": dict(per), "tried": dict(tried), "dropped": dict(why),
             "dropped_by": {k: dict(v) for k, v in why_by.items()}}
    return kept, stats


# --- lockstep traces of whole images --------------------------------------


def lockstep(image: bytes, load: int, entry: int, sp: int,
             regions: list[tuple[int, int]], budget: int) -> list[list[int]]:
    """Run a whole image in both oracles and return the agreed states.

    Each state is `r0..r15` then the flags, after one more instruction than
    the last. icicle supplies every state; Unicorn is stepped alongside and
    must agree wherever its step boundaries fall, which is everywhere except
    directly after an `IT` (see the module docstring). Any disagreement is a
    hard stop rather than a dropped case: a trace is one program, and one
    wrong step makes the rest of it meaningless.

    The run ends at `budget` or at the first instruction that branches to
    itself, which is where a bare-metal `for (;;) {}` parks.
    """
    import icicle
    import unicorn
    from unicorn import arm_const as a

    uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M4)
    ic = icicle.Icicle("thumbv7em", jit=False)
    for base, size in regions:
        uc.mem_map(base, size, unicorn.UC_PROT_ALL)
        ic.mem_map(base, size, icicle.MemoryProtection.ExecuteReadWrite)
    uc.mem_write(load, image)
    ic.mem_write(load, image)
    uregs = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(13)] + [
        a.UC_ARM_REG_SP, a.UC_ARM_REG_LR, a.UC_ARM_REG_PC]
    inames = [f"r{i}" for i in range(13)] + ["sp", "lr", "pc"]
    start = [0] * 13 + [sp, 0, entry & ~1]
    for reg, value in zip(uregs, start, strict=True):
        uc.reg_write(reg, value)
    uc.reg_write(a.UC_ARM_REG_XPSR, 1 << 24)
    for name, value in zip(inames, start, strict=True):
        ic.reg_write(name, value)

    def ice_state() -> list[int]:
        flags = 0
        for name, bit in IcicleM4.FLAGS:
            flags |= (ic.reg_read(name) & 1) << bit
        return [ic.reg_read(n) & 0xFFFFFFFF for n in inames] + [flags]

    def uni_state() -> list[int]:
        out = [uc.reg_read(r) & 0xFFFFFFFF for r in uregs]
        out[15] &= ~1
        return out + [uc.reg_read(a.UC_ARM_REG_XPSR) & 0xF0000000]

    trace: list[list[int]] = []
    while len(trace) < budget:
        pc = uc.reg_read(a.UC_ARM_REG_PC) & ~1
        uc.emu_start(pc | 1, 0xFFFFFFFE, count=1)
        want = uni_state()
        # Up to five: Unicorn can run an IT and all four instructions it
        # covers as one step, as it does on the probe's `itte ls`.
        for _ in range(5):
            if ic.step(1) != icicle.RunStatus.InstructionLimit:
                raise RuntimeError(f"icicle stopped at 0x{ice_state()[15]:08x}")
            state = ice_state()
            trace.append(state)
            if state[15] == want[15]:
                break
        if state != want:
            raise RuntimeError(
                f"the oracles disagree after step {len(trace)}:\n"
                f"  unicorn {[hex(v) for v in want]}\n"
                f"  icicle  {[hex(v) for v in state]}"
            )
        if want[15] == pc:
            break
    return trace


#: Where the probe's `_start` is; see `image_traces`.
PROBE_ENTRY = 0x10128


def image_traces() -> dict[str, dict]:
    """The probe and the nRF52840 blink, each as a lockstep trace."""
    out = {}
    probe = (OUT / "probe.bin").read_bytes()
    # `_start` is the probe's LAST function, not its first: `probe.ld` keeps
    # `.text.start` first, and GCC puts `_start` in plain `.text` without
    # `-ffunction-sections`. The binary carries no symbols, so the address is
    # pinned here and checked: it must be the `push` that opens a function.
    # A rebuild that moved it fails here rather than tracing from the middle
    # of `accumulate`.
    entry = PROBE_ENTRY - 0x10000
    if probe[entry + 1] != 0xB5:
        raise RuntimeError(f"no push at the probe's _start, 0x{PROBE_ENTRY:x}")
    out["probe"] = {
        "image": "tests/cortexm0/m4/probe.bin", "load": 0x10000, "entry": PROBE_ENTRY,
        "sp": 0x20010000,
        "regions": [[0x10000, 0x10000], [0x20000000, 0x10000],
                    [0x50000000, 0x1000]],
        "trace": lockstep(probe, 0x10000, PROBE_ENTRY, 0x20010000,
                          [(0x10000, 0x10000), (0x20000000, 0x10000),
                           (0x50000000, 0x1000)], 20_000),
    }
    blink = BLINK.read_bytes()
    sp, entry = struct.unpack_from("<II", blink)
    out["blink"] = {
        "image": BLINK.relative_to(REPO).as_posix(), "load": 0, "entry": entry & ~1, "sp": sp,
        "regions": [[0, 0x10000], [0x20000000, 0x40000], [0x50000000, 0x1000]],
        "trace": lockstep(blink, 0, entry, sp,
                          [(0, 0x10000), (0x20000000, 0x40000),
                           (0x50000000, 0x1000)], 4_000),
    }
    return out


def versions() -> dict[str, str]:
    import importlib.metadata as metadata

    return {"unicorn": metadata.version("unicorn"),
            "icicle-emu": metadata.version("icicle-emu")}


def _dump(path: pathlib.Path, payload: object) -> None:
    # mtime=0 so the gzip header carries no timestamp: the same inputs give the
    # same bytes, and a regeneration that changed nothing shows no diff.
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(gzip.compress(text, mtime=0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--survey", action="store_true",
                        help="print per-mnemonic agreement and write nothing")
    parser.add_argument("--attempts", type=int, default=ATTEMPTS)
    args = parser.parse_args(argv)

    cases, stats = generate(args.attempts)
    width = max(len(k) for k in stats["tried"]) if stats["tried"] else 4
    for key in sorted(stats["tried"]):
        lost = stats["dropped_by"].get(key, {})
        print(f"  {key:<{width}}  kept {stats['kept'].get(key, 0):>4}"
              f" of {stats['tried'][key]:>5}"
              + (f"  {lost}" if lost and args.survey else ""))
    print(f"kept {len(cases)} cases; dropped {stats['dropped']}")
    if args.survey:
        return 0
    header = {"generator": "tools/m4_oracle.py", "seed": SEED,
              "oracles": versions(),
              "layout": {"code": CODE, "code_size": CODE_SIZE,
                         "sandbox": SANDBOX, "sandbox_size": SANDBOX_SIZE}}
    _dump(OUT / "vectors.json.gz", {**header, "cases": cases})
    _dump(OUT / "traces.json.gz", {**header, "images": image_traces()})
    print(f"wrote {OUT / 'vectors.json.gz'} and {OUT / 'traces.json.gz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
