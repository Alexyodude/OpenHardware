# OpenHardware — the RV32 disassembler, swept against objdump.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file is mostly one comparison run three ways
#
# `core/riscv32/disasm.py` is a **second decoder**. `core/riscv32/exec.cc`
# already decodes every one of these encodings to execute them; this decodes
# them again, in another language, to produce text. The two can disagree, and a
# listing that disagrees with what executed is worse than no listing.
#
# `riscv32-esp-elf-objdump` is what contains that risk, the same way
# `arm-none-eabi-objdump` does for `tests/cortexm0/test_disasm.py` — which swept
# 56,551 encodings and found three bugs four real firmware images could not.
#
# Three sweeps, because they catch different things:
#
#   * **every compressed encoding** — all 49,152 of them, enumerable whole
#   * **every opcode/funct3/funct7 triple** — 32,768, which checks every
#     mnemonic decision in the 32-bit space
#   * **every field of every form** — 27,904, registers across all 32 and
#     immediates across a spread including both sign bits. This is the one that
#     catches a transposed immediate, which the other two cannot: a wrong
#     immediate is still the right mnemonic.
#
# ## Two normalisations, and neither is a tolerance
#
# Whitespace, because a tab and a space carry no information here. And
# objdump's own `# 0x...` annotation, which it appends when a base register is
# `zero` and it can therefore compute the absolute address — that is objdump
# adding a convenience, not part of the instruction. 522 lines differed by only
# that, and reading them as decode failures would have been a full day wasted.
#
# ## Where objdump is not the authority
#
# It decodes a **different** architecture, not merely a wider one, and in both
# directions:
#
#   * wider — the F and D extensions, which no part here has
#   * narrower — Zbs, which its default `rv32` target does not know at all,
#     and which this core implements and gates per part
#
# `ACCOUNTED` names every such class with the reason. A divergence outside that
# table is a bug in this module.

import itertools
import pathlib
import re
import shutil
import subprocess

import pytest

from core.riscv32 import abi, disasm

#: objdump's line format: `   c:	00100093          	addi	ra,zero,1`. The
#: encoding column may hold several space-separated halfwords -- see
#: `render` for when, and why that matters more than it looks.
_LINE = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f ]+?)\s{2,}(.*)$")

#: Mnemonic prefixes objdump renders and this module does not, with the reason.
#:
#: **Every entry is a fact about what this core implements, not a tolerance.**
#: The F and D extensions have no part here; Zcf and Zcd are their compressed
#: forms. If a part with an FPU ever arrives, these stop being correct and this
#: is where that shows up.
ACCOUNTED_THEIRS = {
    "c.fld": "Zcd: needs D", "c.fldsp": "Zcd: needs D",
    "c.fsd": "Zcd: needs D", "c.fsdsp": "Zcd: needs D",
    "c.flw": "Zcf: needs F", "c.flwsp": "Zcf: needs F",
    "c.fsw": "Zcf: needs F", "c.fswsp": "Zcf: needs F",
}

#: objdump's RV128 spelling of a shamt-zero compressed shift, and what this
#: module renders instead. On RV32 those encodings are HINTs; the bits say
#: "shift by zero" and that is what is printed.
HINT_SPELLINGS = {"c.slli64": "c.slli", "c.srli64": "c.srli", "c.srai64": "c.srai"}

#: One slot, two extensions: quadrant 2's funct3=101 is Zcd's c.fsdsp on a
#: part with D, and Zcmp/Zcmt's cm.* on a part with neither -- the spec's own
#: acknowledged overlap, and a part cannot have both readings at once. objdump
#: 8.4 knows only the D reading; this module renders the Zc reading because
#: that is what `core/riscv32/exec.cc` executes (OH-146). Checked as a pair,
#: like HINT_SPELLINGS, so a divergence that is not this overlay still trips.
OVERLAY_SPELLINGS = {
    "c.fsdsp": {"cm.push", "cm.pop", "cm.popret", "cm.popretz",
                "cm.mvsa01", "cm.mva01s", "cm.jt", "cm.jalt"},
}

#: Whole 32-bit opcodes this core does not implement, and what each is.
#:
#: **Keyed by opcode rather than by mnemonic, and that is the point.** The
#: atomics alone spell themselves eight ways once `.aq`, `.rl` and `.aqrl` are
#: counted, and the floating-point families more than fifty. Listing spellings
#: would be listing objdump's vocabulary; listing opcodes is stating what
#: `core/riscv32/exec.cc` implements, which is the fact that actually decides
#: it. A new extension arriving in one of these opcodes is then a change to
#: this table rather than a surprise.
UNIMPLEMENTED_OPCODES = {
    0x07: "FP load -- F, D and Q, and no part here has an FPU",
    0x27: "FP store -- same",
    0x2F: "AMO -- the A extension, gated per part and rendered by nothing here",
    0x43: "FMADD -- F, D and Q",
    0x47: "FMSUB -- F, D and Q",
    0x4B: "FNMSUB -- F, D and Q",
    0x4F: "FNMADD -- F, D and Q",
    0x53: "OP-FP -- F, D and Q",
    0x73: "SYSTEM -- Zicsr, and this core has no CSRs. The bare `ecall` and "
          "`ebreak` encodings are rendered; everything else here is a CSR "
          "access or a privileged instruction",
}

#: Mnemonics this module renders and objdump's default `rv32` target refuses.
#:
#: **objdump is narrower here, not this module wrong.** Its `riscv:rv32` does
#: not include Zba or Zbs, which `core/riscv32/exec.cc` implements and gates on
#: the part -- an RP2350 has Zbs and an ESP32-C3 must refuse it. And a `fence`
#: whose reserved `rd`/`rs1` fields are set is one the specification says base
#: implementations **shall ignore**; objdump declines to render it, the core
#: executes it, and this renders what the core does.
ACCOUNTED_MINE = {
    "bset": "Zbs, absent from objdump's default rv32",
    "bclr": "Zbs", "binv": "Zbs", "bext": "Zbs",
    "bseti": "Zbs", "bclri": "Zbs", "binvi": "Zbs", "bexti": "Zbs",
    "sh1add": "Zba, absent from objdump's default rv32",
    "sh2add": "Zba", "sh3add": "Zba",
    "c.lbu": "Zcb, ratified 2023; this binutils predates it",
    "c.lhu": "Zcb", "c.lh": "Zcb", "c.sb": "Zcb", "c.sh": "Zcb",
    "c.zext.b": "Zcb", "c.sext.b": "Zcb", "c.zext.h": "Zcb",
    "c.sext.h": "Zcb", "c.not": "Zcb", "c.mul": "Zcb",
    "cm.push": "Zcmp", "cm.pop": "Zcmp",
    "cm.popret": "Zcmp", "cm.popretz": "Zcmp",
    "cm.mvsa01": "Zcmp", "cm.mva01s": "Zcmp",
    "cm.jt": "Zcmt", "cm.jalt": "Zcmt",
    "fence": "reserved rd/rs1 fields, which the ISA says to ignore",
    "fence.i": "same, for Zifencei",
}

#: Shifts whose amount is 32 or more are RV64's six-bit field. objdump renders
#: them; this part has 32-bit registers and `core/riscv32/exec.cc` refuses
#: them, so refusing to render them agrees with what executes.
_RV64_SHIFT = re.compile(r"^(slli|srli|srai)\s+\S+,\S+,0x([0-9a-f]+)$")


def objdump() -> pathlib.Path:
    """The toolchain's disassembler, or skip. **A skip and never a pass.**"""
    found = shutil.which("riscv32-esp-elf-objdump")
    if found:
        return pathlib.Path(found)
    path = pathlib.Path.home() / (
        ".platformio/packages/toolchain-riscv32-esp/bin/riscv32-esp-elf-objdump.exe"
    )
    if not path.is_file():
        pytest.skip(f"no riscv32-esp-elf-objdump on PATH or at {path}")
    return path


def normalise(text: str) -> str:
    """Whitespace, and objdump's own computed-address annotation.

    objdump appends `# 0x1234` when a base register is `zero`, because it can
    then work out the absolute address. That is a convenience it adds, not part
    of the instruction -- 522 lines of the field sweep differ by only that, and
    reading them as decode failures would have wasted a day.
    """
    return re.sub(r"\s+", " ", text.split("#")[0].replace("	", " ")).strip()


def render(blob: pathlib.Path) -> dict[int, str]:
    """objdump's text for `blob`, **keyed by address**.

    Keyed by address rather than paired line-for-line, because the two
    disassemblers do not agree on stride. **When objdump cannot decode a word
    it re-syncs on halfwords**, printing `009f 0000 000f` as one six-byte blob
    where this module renders three separate entries. Zipping the two outputs
    together therefore drifts the moment either meets something it does not
    know -- which is exactly the region a sweep is for.

    So the caller looks up each candidate by the address it was laid at, and
    an address objdump skipped is handled explicitly rather than mis-compared.
    """
    out = subprocess.run(
        [str(objdump()), "-D", "-b", "binary", "-m", "riscv:rv32",
         "-M", "no-aliases", str(blob)],
        capture_output=True, text=True, check=True,
    ).stdout
    table: dict[int, str] = {}
    for line in out.splitlines():
        match = _LINE.match(line)
        if match:
            table[int(match.group(1), 16)] = normalise(match.group(3))
    return table


def excused(encoding: int, width: int, theirs: str, mine: str) -> bool:
    """Whether a divergence is one of the named, understood ones.

    Three cases, and the first is not a divergence at all.
    """
    theirs_head = theirs.split()[0] if theirs else ""
    mine_head = mine.split()[0] if mine else ""
    theirs_refused = theirs == "" or theirs_head.startswith("0x")
    mine_refused = mine_head.startswith("0x")

    if theirs_refused and mine_refused:
        # **Both refuse, and the hex differs only because the strides do.**
        # objdump re-syncs on halfwords and prints `0x9f0031009f` for three
        # words this module renders as three. Same verdict, different framing;
        # comparing the digits would be comparing the re-sync.
        return True
    if mine_refused:
        if width == 4 and (encoding & 0x7F) in UNIMPLEMENTED_OPCODES:
            return True
        if theirs_head in ACCOUNTED_THEIRS:
            return True
        shift = _RV64_SHIFT.match(theirs)
        return bool(shift and int(shift.group(2), 16) >= 32)
    if theirs_refused:
        return mine_head in ACCOUNTED_MINE

    # **Both decode, and disagree only about the name.** The only class here is
    # objdump's RV128 spelling of a shamt-zero shift -- `c.slli64 zero` where
    # this renders `c.slli zero,0x0`. On RV32 that encoding is a HINT, and the
    # bits say shift-by-zero, so rendering them is the honest answer and the
    # `64` is objdump reaching for a wider architecture again.
    #
    # Checked as a *pair* rather than by objdump's name alone, so a future
    # divergence where objdump says `c.slli64` and this says something else
    # entirely is still reported.
    if theirs_head in HINT_SPELLINGS:
        return mine_head == HINT_SPELLINGS[theirs_head]
    if theirs_head in OVERLAY_SPELLINGS:
        return mine_head in OVERLAY_SPELLINGS[theirs_head]
    return False


def compare(tmp_path, words: list[int], width: int) -> tuple[int, list[str]]:
    """Lay `words` end to end, one objdump pass, and compare by address."""
    path = tmp_path / f"sweep{width}.bin"
    path.write_bytes(b"".join(w.to_bytes(width, "little") for w in words))
    theirs_at = render(path)

    agreed = 0
    unexplained: list[str] = []
    for index, encoding in enumerate(words):
        at = index * width
        mine = normalise(disasm.decode(encoding, at)[0])
        # An address objdump emitted no line for is one it re-synced past, so
        # it could not decode the word. `excused` handles that as a refusal.
        theirs = theirs_at.get(at, "")
        if theirs and mine == theirs:
            agreed += 1
            continue
        if excused(encoding, width, theirs, mine):
            continue
        unexplained.append(
            f"0x{encoding:0{width * 2}x} at 0x{at:x}: "
            f"objdump {theirs!r}, this module {mine!r}"
        )
    return agreed, unexplained


# --- the three sweeps -------------------------------------------------------


def test_every_compressed_encoding_renders_the_way_objdump_does(tmp_path):
    """All 49,152 halfwords with `(c & 3) != 3`, in one pass.

    Enumerable whole, so it is enumerated. The encodings a compiler never emits
    are exactly the ones a hand-written decoder gets wrong.
    """
    candidates = [c for c in range(1 << 16) if (c & 3) != 3]
    agreed, unexplained = compare(tmp_path, candidates, 2)
    assert unexplained == [], unexplained[:10]
    # 31k, down from 32k at OH-146: the Zc renderings moved the whole
    # quadrant-2 funct3=101 slot and quadrant 0's 100 slot out of the
    # both-refused bucket -- objdump 8.4 predates Zc -- into accounted
    # divergences. The floor only exists to prove the sweep ran.
    assert agreed > 31_000, f"only {agreed} agreed; the sweep is not running"


def test_every_opcode_and_function_field_renders_the_way_objdump_does(tmp_path):
    """Every opcode x funct3 x funct7, registers fixed. 32,768 encodings.

    This checks every *mnemonic* decision in the 32-bit space -- which opcode
    means what, and which funct7 belongs to which extension. It cannot check an
    immediate, because the registers and immediates never move.
    """
    words = [
        opcode | (1 << 7) | (funct3 << 12) | (2 << 15) | (3 << 20) | (funct7 << 25)
        for opcode in range(0x03, 0x80, 4)
        for funct3 in range(8)
        for funct7 in range(128)
    ]
    agreed, unexplained = compare(tmp_path, words, 4)
    assert unexplained == [], unexplained[:10]
    assert agreed > 20_000, f"only {agreed} agreed; the sweep is not running"


def test_every_field_of_every_form_renders_the_way_objdump_does(tmp_path):
    """Registers across all 32 and immediates across a spread. 27,904 encodings.

    **The one the other two cannot replace.** A transposed pair of immediate
    bits leaves the mnemonic right and the offset wrong, which is the silent
    class: a listing that reads perfectly and points two bytes from where
    execution is.
    """
    immediates = [0, 1, 2, 3, 0x7FF, 0x800, 0xFFF, 0x555, 0xAAA, 0x400, 0x3FF]
    words: list[int] = []
    for reg in range(32):
        for imm in immediates:
            words.append(0x37 | (reg << 7) | (imm << 12))
            words.append(0x17 | (reg << 7) | (imm << 12))
            words.append(0x6F | (reg << 7) | (imm << 12))
            words.append(0x67 | (reg << 7) | (reg << 15) | (imm << 20))
            for funct3 in (0, 1, 4, 5, 6, 7):
                words.append(0x63 | ((imm & 0x1F) << 7) | (funct3 << 12)
                             | (reg << 15) | (((reg + 1) % 32) << 20)
                             | ((imm >> 5) << 25))
            for funct3 in (0, 1, 2, 4, 5):
                words.append(0x03 | (reg << 7) | (funct3 << 12)
                             | (((reg + 3) % 32) << 15) | (imm << 20))
            for funct3 in (0, 1, 2):
                words.append(0x23 | ((imm & 0x1F) << 7) | (funct3 << 12)
                             | (reg << 15) | (((reg + 5) % 32) << 20)
                             | ((imm >> 5) << 25))
            for funct3 in (0, 2, 3, 4, 6, 7):
                words.append(0x13 | (reg << 7) | (funct3 << 12)
                             | (((reg + 7) % 32) << 15) | (imm << 20))
        for shamt in range(32):
            base = (reg << 7) | (((reg + 1) % 32) << 15) | (shamt << 20)
            words.append(0x13 | base | (1 << 12))
            words.append(0x13 | base | (5 << 12))
            words.append(0x13 | base | (5 << 12) | (0x20 << 25))
            for funct3 in range(8):
                pair = (reg << 7) | (shamt << 15) | (((shamt + 9) % 32) << 20)
                words.append(0x33 | pair | (funct3 << 12))
                words.append(0x33 | pair | (funct3 << 12) | (1 << 25))

    agreed, unexplained = compare(tmp_path, [w & 0xFFFFFFFF for w in words], 4)
    assert unexplained == [], unexplained[:10]
    assert agreed > 25_000, f"only {agreed} agreed; the sweep is not running"


# --- and the properties a sweep cannot state --------------------------------


def test_the_width_comes_from_the_instruction_and_not_from_a_stride():
    """A listing interleaves 16-bit and 32-bit instructions, and advancing by a
    constant does not fault -- it produces a plausible listing offset by two
    bytes from the second line onward, every entry a real instruction and none
    of them the ones that ran.

    The bytes below are the start of `tests/riscv32/c3blink/blink.bin`: a
    32-bit `lui`, then two compressed, then a 32-bit `jal`.
    """
    image = (pathlib.Path(__file__).resolve().parent / "c3blink" / "blink.bin")
    if not image.is_file():
        pytest.skip(f"{image} is missing")
    lines = disasm.disassemble(image.read_bytes(), base=0x42000000)
    assert [line.width for line in lines[:4]] == [4, 2, 4, 4], (
        [(hex(line.address), line.width, line.text) for line in lines[:4]]
    )
    # Addresses advance by the widths, which is the property that breaks first.
    for previous, following in itertools.pairwise(lines):
        assert following.address == previous.address + previous.width


def test_a_listing_reads_through_a_cpu_and_stops_at_the_edge_of_a_region():
    """The pane wants what it can show, not an exception. A region ends and the
    listing ends with it rather than failing whole."""
    with abi.Cpu() as cpu:
        cpu.set_isa("RV32IMC")
        cpu.add_region(0x42000000, 8, executable=True)
        cpu.write_word(0x42000000, 0x00100093)      # addi ra,zero,1
        cpu.write_word(0x42000004, 0x00200113)      # addi sp,zero,2
        lines = disasm.disassemble_range(cpu, 0x42000000, 24)
    assert len(lines) == 2, [line.text for line in lines]
    assert lines[0].text.replace("\t", " ") == "addi ra,zero,1"
    assert lines[1].address == 0x42000004


def test_an_encoding_this_module_cannot_render_still_occupies_its_bytes():
    """A listing that silently skipped an unrenderable word would misalign
    every line after it. So it renders as its hex and keeps its width, which is
    what objdump does too."""
    text, width = disasm.decode(0x0000007F, 0)      # an unassigned opcode
    assert text == "0x7f"
    assert width == 4
    text, width = disasm.decode(0x9C21, 0)          # reserved compressed
    assert text == "0x9c21"
    assert width == 2


def test_the_raw_column_matches_the_width():
    """Four hex digits for a compressed instruction and eight for a full one,
    which is what objdump prints and therefore what a reader comparing the two
    panes expects."""
    lines = disasm.disassemble(bytes.fromhex("93001000") + bytes.fromhex("0545"), 0)
    assert lines[0].width == 4 and len(lines[0].raw) == 8
    assert lines[1].width == 2 and len(lines[1].raw) == 4


def test_a_fence_renders_its_orderings_the_way_objdump_spells_them():
    """**Found by mutation, and it was a hole this file dug itself.**

    Reversing the `pred`/`succ` bit order left all three sweeps green. Every
    fence they contain has non-zero `rd` and `rs1` -- the sweeps vary those --
    so objdump refuses to render them, `ACCOUNTED_MINE` excuses the difference,
    and the operands are never compared at all. An accounting entry that
    excuses a whole mnemonic excuses its bugs with it.

    So the well-formed encodings are asserted directly. Bit 3 is device input,
    2 device output, 1 memory read, 0 memory write; the values below are
    objdump's own output, read off `riscv32-esp-elf-objdump` rather than
    derived.
    """
    expected = {
        0x0000000F: "fence unknown,unknown",
        0x0110000F: "fence w,w",
        0x0330000F: "fence rw,rw",
        0x0FF0000F: "fence iorw,iorw",
        0x0840000F: "fence i,o",
        0x0210000F: "fence r,w",
    }
    for encoding, text in expected.items():
        assert normalise(disasm.decode(encoding, 0)[0]) == text, hex(encoding)


def test_the_fence_orderings_agree_with_objdump_and_not_only_with_this_table(
    tmp_path,
):
    """The table above is a transcription, and a transcription can be wrong in
    the same direction twice. This runs the same encodings through objdump."""
    words = [0x0000000F, 0x0110000F, 0x0330000F, 0x0FF0000F,
             0x0840000F, 0x0210000F]
    path = tmp_path / "fences.bin"
    path.write_bytes(b"".join(w.to_bytes(4, "little") for w in words))
    theirs_at = render(path)
    assert len(theirs_at) == len(words), "objdump rendered every one of them"
    for index, encoding in enumerate(words):
        mine = normalise(disasm.decode(encoding, index * 4)[0])
        assert mine == theirs_at[index * 4], hex(encoding)
