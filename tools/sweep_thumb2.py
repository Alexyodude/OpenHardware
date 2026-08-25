#!/usr/bin/env python3
# OpenHardware - sweep core/cortexm0/disasm.py's Thumb-2 half against objdump.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Compare this repository's Armv7E-M decoder against `arm-none-eabi-objdump`.

## Why a tool and not only a test

`tests/cortexm0/test_thumb2_disasm.py` imports from here and asserts on what
these functions return, so there is one sweep rather than two that drift. The
CLI exists because the *development* question -- "what is still unnamed,
grouped by mnemonic, most common first" -- is not a pass or a fail and does not
belong in an assertion. Run it while writing a decoder group; run the test to
keep it right.

    python -m tools.sweep_thumb2                 # summary
    python -m tools.sweep_thumb2 --unnamed 40    # what to write next
    python -m tools.sweep_thumb2 --wrong         # where the two disagree

## The oracle, and what it is not

objdump is about as independent as this repository gets: neither this file nor
`core/cortexm0/disasm.py` had any hand in it. It is still **one** oracle, so a
disagreement is detected and cannot be adjudicated -- `docs/architectures.md`
4.2 draws that distinction and it holds here.

It also decodes a *different* target in both directions, which is the trap the
RISC-V sweeps paid for twice:

* **Wider.** Told `-m armv7e-m` it still knows NEON, VFP, the generic
  coprocessor space and even the old FPA mnemonics. An nRF52840's Cortex-M4
  has none of those except the FPU, which this decoder does not attempt. That
  is 32,112 of the encodings objdump names here -- more than a third -- so the
  raw "percentage objdump named that we did not" is **not** a coverage figure.
* **Later.** `0xE89F` is `clrm`, which is **Armv8.1-M**. objdump naming an
  encoding is not evidence that any part in this repository has it.

## Compare by address, never by position

The lesson `docs/HANDOFF_2026-08-25_the-esp32-c-series.md` 3.5 paid for: when
objdump cannot decode something it **re-syncs on halfwords**, so zipping two
disassemblers drifts exactly where the interesting encodings are. Both sides
here produce a dict keyed by address.

## Two sweeps, because an IT block cannot be checked one encoding at a time

`compare` decodes each `(hw1, hw2)` pair in isolation, which is right for the
wide encodings and structurally blind to `IT`: that instruction changes how the
instructions *after* it are rendered. `compare_stream` disassembles a whole
image linearly on both sides, and `it_sequences` builds one made of every `IT`
encoding followed by five instructions.

## What the verdicts mean

    agreed       both name it, identically
    both-refuse  neither names it -- agreement, and the bulk of any sweep
    unnamed      objdump names it, this decoder says `.word`
    accounted    they differ in the one way objdump is known to lose a bit
    wrong        anything else -- the defect list

`wrong` is the only one that is a defect. `unnamed` is a coverage number that
has to be read against the paragraph above about what objdump knows.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.cortexm0 import disasm  # noqa: E402

#: Where the swept blob is placed. Arbitrary and even; the value only shows up
#: in branch targets, which is why it is not zero -- a decoder that forgot to
#: add the base would agree with objdump at zero and nowhere else.
BASE = 0x8000

#: objdump's own name for the architecture. **Not `armv6-m`**, which is what
#: `tests/cortexm0/test_disasm.py` passes: told the narrower one, objdump
#: refuses every Thumb-2 encoding and the sweep would agree with itself.
ARCH = "armv7e-m"


@dataclasses.dataclass(frozen=True)
class Divergence:
    """One encoding the two disassemblers do not agree about."""

    hw1: int
    hw2: int
    mine: str
    theirs: str

    def __str__(self) -> str:
        return (
            f"{self.hw1:04x} {self.hw2:04x}  mine {self.mine!r}  "
            f"objdump {self.theirs!r}"
        )


@dataclasses.dataclass(frozen=True)
class Report:
    """What one sweep found."""

    swept: int
    agreed: int
    both_refuse: int
    unnamed: list[tuple[int, int, str]]
    wrong: list[Divergence]
    #: Divergences `objdump_drops_writeback` accounts for. Counted rather than
    #: hidden: a number that moves is a question, and a number that reaches
    #: zero means the accounting is dead and should be deleted.
    accounted: list[Divergence] = dataclasses.field(default_factory=list)

    @property
    def named_by_objdump(self) -> int:
        return (
            self.agreed
            + len(self.unnamed)
            + len(self.accounted)
            + len([d for d in self.wrong if d.theirs])
        )

    def summary(self) -> str:
        named = self.agreed + len(self.accounted)
        share = 100 * named / self.named_by_objdump if self.named_by_objdump else 0
        return (
            f"{self.swept} swept: {self.agreed} agreed, "
            f"{self.both_refuse} refused by both, {len(self.unnamed)} unnamed, "
            f"{len(self.accounted)} accounted, {len(self.wrong)} wrong. "
            f"Of {self.named_by_objdump} objdump names, this decoder names "
            f"{share:.1f}%."
        )


def objdump_path() -> pathlib.Path | None:
    """arm-none-eabi-objdump, or None.

    None rather than a raise, so a caller can skip. The same contract the rule
    checkers keep when they cannot find a PICSimLab source tree: a check that
    cannot run says so and never passes quietly.
    """
    found = shutil.which("arm-none-eabi-objdump")
    if found:
        return pathlib.Path(found)
    installed = (
        pathlib.Path.home()
        / ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-objdump.exe"
    )
    return installed if installed.is_file() else None


def objdump_drops_writeback(hw1: int, hw2: int, mine: str, theirs: str) -> bool:
    """Whether this divergence is the one place objdump renders *less* than the
    encoding carries, rather than this decoder rendering something wrong.

    `LDRD`/`STRD` pre-indexed with a **positive zero** offset: objdump prints
    `strd r0, r0, [r0]`, byte for byte what it prints for the no-writeback
    encoding beside it. Two distinct instructions, one string. Measured against
    `arm-none-eabi-objdump` 12.3.1 -- it keeps the `!` for `#-0`, so this is
    not a general rule about zero offsets.

    Kept as a **predicate over the encoding**, never as a mnemonic on an
    exclusion list. `docs/HANDOFF_2026-08-25_the-esp32-c-series.md` 3.3 records
    this repository shipping a tolerance twice that excused a whole mnemonic
    and therefore excused its bugs: a wrongly-decoded `strd` would have been
    forgiven by a list saying "strd is accounted for". This asks instead
    whether the two renderings differ by exactly one trailing `!` on exactly
    the encoding whose writeback bit is set, so any other disagreement about
    the same mnemonic is still a failure.
    """
    if mine != theirs + "!":
        return False
    # 0xFE40 selects the prefix and `hw1[6]`, which is what says "load/store
    # dual" -- and **not** `hw1[4]`, the load bit. The first mask included it
    # and so accounted for `strd` while leaving all 2,208 `ldrd` encodings
    # reported as wrong: a predicate that is too tight fails loudly, which is
    # the direction an accounting rule should err in.
    if (hw1 & 0xFE40) != 0xE840:
        return False
    p_bit, u_bit, writeback = (hw1 >> 8) & 1, (hw1 >> 7) & 1, (hw1 >> 5) & 1
    return bool(p_bit and writeback and u_bit and (hw2 & 0xFF) == 0)


def wide_space() -> list[tuple[int, int]]:
    """The encodings the pairwise sweep covers, as `(hw1, hw2)` pairs.

    **Every wide first halfword**, 0xE800 through 0xFFFF -- 6,144 of them,
    which is all three of the prefixes `is_wide` accepts. Each is paired with a
    fixed spread of second halfwords rather than all 65,536, because the
    product is 402 million and the second halfword mostly carries registers.

    The spread exercises the fields that *select* a form: bits 15:12 pick
    between forms in several groups, bits 7:4 select shift type, sub-operation
    and rotation, and 0x0000 / 0xFFFF catch the all-clear and all-set edges
    that off-by-one masks fall into.

    Deterministic and written out. A random spread would make a failing sweep
    unreproducible, which is the property that matters most when one fails.
    """
    seconds = (
        0x0000, 0x0001, 0x0102, 0x0F03, 0x1000, 0x1234, 0x2000, 0x3040,
        0x4050, 0x5060, 0x6070, 0x7080, 0x8000, 0x9ABC, 0xA0B0, 0xB0C0,
        0xC0D0, 0xD0E0, 0xE0F0, 0xF000, 0xFA05, 0xFFFF,
        # The `hw2[15:12] == 0b1111` group with `hw2[7:4]` set, which is where
        # `clz`, `rbit`, `rev.w` and `revsh.w` live. **Added after the spread
        # above turned out to reach none of them**: every second halfword with
        # the required top nibble had zeros in bits 7:4, so a whole sub-group
        # sat outside the sweep while the summary line read 0 wrong. Adding
        # these six immediately found 91 real disagreements.
        #
        # A sweep is only as good as its spread, and that was the second time
        # in this ticket that the measuring instrument was the thing at fault.
        0xF080, 0xF090, 0xF0A0, 0xF0B0, 0xF1C8, 0xF3F3,
    )
    return [(hw1, hw2) for hw1 in range(0xE800, 0x10000) for hw2 in seconds]


#: What an `IT` sequence is followed by, as halfwords. Chosen so the sweep sees
#: both cases the condition changes: a narrow flag-setting form whose `s` must
#: come off, and a wide one that has no `s` and takes the condition anyway. The
#: fifth is past the longest possible block, so an `IT` that queued too many
#: conditions shows up as a spurious suffix rather than as nothing at all.
IT_FOLLOWERS: tuple[tuple[int, ...], ...] = (
    (0x230B,),              # movs r3, #11          narrow, sets flags
    (0xFB00, 0x3003),       # mla  r0, r0, r3, r3   wide, no `s` to drop
    (0x1CD1,),              # adds r1, r2, #3
    (0x00AC,),              # lsls r4, r5, #2
    (0x4408,),              # add  r0, r1           no flags, no `s`
)


def it_sequences() -> bytes:
    """Every `IT` encoding, each followed by five instructions.

    **A stream rather than a list of pairs**, because that is the whole point:
    an `IT` changes how the instructions *after* it are rendered, so nothing
    about it can be checked one encoding at a time.

    **14 conditions by 15 non-zero masks.** Three things are left out and each
    for its own reason:

    * a mask of zero is not an `IT` at all -- it is the hint space, `nop` and
      `yield` and the rest
    * a `firstcond` of 15 is reserved
    * a `firstcond` of 14 -- `al` -- **with an else-arm is UNPREDICTABLE**: the
      inverse of "always" is "never", which Armv7 removed, so the arm could not
      execute. `core/cortexm0/disasm.py` declines to enter such a block, and
      objdump renders it anyway with `al` on every arm. Neither is wrong about
      an encoding the architecture does not define, and sweeping it would only
      pin one arbitrary reading of it. The `IT` halfword itself still renders
      as `.short` on this side, so a reader sees that something is not
      understood rather than seeing a block that quietly does nothing.

    That leaves 210 blocks over the whole defined space.
    """
    out = bytearray()
    for firstcond in range(0xE):
        for mask in range(1, 0x10):
            out += (0xBF00 | (firstcond << 4) | mask).to_bytes(2, "little")
            for follower in IT_FOLLOWERS:
                for halfword in follower:
                    out += halfword.to_bytes(2, "little")
    return bytes(out)


def blob(pairs: list[tuple[int, int]]) -> bytes:
    """The pairs as little-endian halfwords, back to back."""
    return b"".join(
        hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little") for hw1, hw2 in pairs
    )


def objdump_render(binary: pathlib.Path, objdump: pathlib.Path) -> dict[int, str]:
    """objdump's rendering of `binary`, address to text.

    Keyed by address for the re-sync reason in the module docstring, and
    stripped of the `@ 0x...` annotations objdump computes as a convenience --
    those are not part of the instruction, and reproducing the rules for when
    it emits them would be an argument about formatting rather than decoding.
    """
    # **`--adjust-vma`, and it is load-bearing.** objdump numbers a raw binary
    # from zero, so without this it computes every branch target relative to
    # zero while this decoder computes them relative to BASE -- and the first
    # sweep reported 19,968 disagreements that were all the same constant.
    # That is the shape `docs/HANDOFF_2026-08-25_the-esp32-c-series.md` 3.4
    # describes: a large round failure count is the measuring instrument
    # before it is the thing measured.
    #
    # The alternative, setting BASE to zero, would make the sweep agree with a
    # decoder that forgot to add the base at all -- a real bug, and one this
    # is now the only thing watching for.
    result = subprocess.run(
        [str(objdump), "-D", "-b", "binary", "-m", ARCH, "-M", "force-thumb",
         f"--adjust-vma={BASE:#x}", str(binary)],
        check=True, capture_output=True, text=True,
    )
    out: dict[int, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{4} ?)+)\s+(.*)$", line)
        if not match:
            continue
        out[int(match.group(1), 16)] = (
            match.group(3).split("@")[0].split(";")[0].strip()
        )
    return out


def refused(text: str) -> bool:
    """Whether objdump's line means "I decline to name this".

    `<undefined>` appears *inside* an otherwise-formed line -- objdump prints
    `ldr.w r0, [r0, <undefined>]` when it recognises the shape and not the
    operand. That is objdump declining, not objdump naming something this
    decoder missed, and counting it as a gap overstated the gap by 2,120.
    """
    return (
        not text
        or text.startswith((".word", ".short", "bad", "undefined"))
        or "<undefined>" in text
        or "<illegal>" in text
    )


def normalise(text: str) -> str:
    """Whitespace only, so a tab against spaces is not a divergence."""
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


class _Buckets:
    """One comparison goes in exactly one bucket. Shared by both sweeps."""

    def __init__(self) -> None:
        self.agreed = 0
        self.both_refuse = 0
        self.unnamed: list[tuple[int, int, str]] = []
        self.wrong: list[Divergence] = []
        self.accounted: list[Divergence] = []

    def add(self, hw1: int, hw2: int, mine: str, their: str) -> None:
        if not mine and not their:
            self.both_refuse += 1
        elif mine and their and mine == their:
            self.agreed += 1
        elif their and not mine:
            self.unnamed.append((hw1, hw2, their))
        elif objdump_drops_writeback(hw1, hw2, mine, their):
            self.accounted.append(Divergence(hw1, hw2, mine, their))
        else:
            self.wrong.append(Divergence(hw1, hw2, mine, their))

    def report(self, swept: int) -> Report:
        return Report(swept, self.agreed, self.both_refuse, self.unnamed,
                      self.wrong, self.accounted)


def compare(objdump: pathlib.Path, pairs: list[tuple[int, int]] | None = None) -> Report:
    """Sweep `pairs` and say where the two disassemblers stand.

    One objdump invocation over one blob, which is what makes a sweep of this
    size take a second rather than an hour.
    """
    pairs = wide_space() if pairs is None else pairs
    image = blob(pairs)

    with tempfile.TemporaryDirectory() as work:
        binary = pathlib.Path(work) / "sweep.bin"
        binary.write_bytes(image)
        theirs = objdump_render(binary, objdump)

    buckets = _Buckets()
    for index, (hw1, hw2) in enumerate(pairs):
        address = BASE + index * 4
        text, width = disasm.decode(hw1, address, hw2, disasm.Profile.V7EM)
        assert width == 4, f"0x{hw1:04x} is wide; decode returned width {width}"
        mine = "" if text.startswith((".word", ".short")) else normalise(text)
        raw = theirs.get(address, "")
        buckets.add(hw1, hw2, mine, "" if refused(raw) else normalise(raw))
    return buckets.report(len(pairs))


def compare_stream(objdump: pathlib.Path, image: bytes) -> Report:
    """Compare a whole instruction *stream*, not a list of encodings.

    `compare` decodes each pair in isolation, which is right for the wide sweep
    and structurally blind to an `IT` block. This disassembles the image
    linearly on both sides -- which also means a width disagreement
    desynchronises the two and shows up immediately, the property
    `core/cortexm0/disasm.py`'s own docstring says the objdump check earns its
    keep on.
    """
    with tempfile.TemporaryDirectory() as work:
        binary = pathlib.Path(work) / "stream.bin"
        binary.write_bytes(image)
        theirs = objdump_render(binary, objdump)

    buckets = _Buckets()
    lines = disasm.disassemble(image, BASE, disasm.Profile.V7EM)
    for line in lines:
        mine = "" if line.text.startswith((".word", ".short")) else normalise(line.text)
        raw = theirs.get(line.address, "")
        hw1 = line.encoding if line.width == 2 else line.encoding >> 16
        hw2 = 0 if line.width == 2 else line.encoding & 0xFFFF
        buckets.add(hw1, hw2, mine, "" if refused(raw) else normalise(raw))
    return buckets.report(len(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unnamed", type=int, default=0, metavar="N",
                        help="list the N most common mnemonics objdump names "
                             "and this decoder does not")
    parser.add_argument("--wrong", action="store_true",
                        help="list every disagreement, which is the defect list")
    args = parser.parse_args(argv)

    objdump = objdump_path()
    if objdump is None:
        print("sweep_thumb2: SKIPPED - no arm-none-eabi-objdump", file=sys.stderr)
        return 3

    report = compare(objdump)
    print("wide encodings: " + report.summary())

    blocks = compare_stream(objdump, it_sequences())
    print("IT blocks:      " + blocks.summary())

    if args.unnamed:
        counts: collections.Counter[str] = collections.Counter(
            their.split()[0] for _, _, their in report.unnamed
        )
        print(f"\nunnamed, by mnemonic ({len(counts)} distinct):")
        for mnemonic, count in counts.most_common(args.unnamed):
            example = next(t for _, _, t in report.unnamed if t.split()[0] == mnemonic)
            print(f"  {count:6}  {mnemonic:12} e.g. {example}")

    if args.wrong:
        for name, found in (("wide", report.wrong), ("IT block", blocks.wrong)):
            print(f"\n{len(found)} {name} disagreements:")
            for divergence in found[:120]:
                print(f"  {divergence}")

    return 1 if (report.wrong or blocks.wrong) else 0


if __name__ == "__main__":
    raise SystemExit(main())
