# OpenHardware — Armv7E-M decode, and the line where this ticket stopped.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What OH-50 built and what it deliberately did not
#
# **Built: the decoder.** `core/cortexm0/disasm.py` gained a `Profile`, the
# Armv7-M instruction-length rule, and the Thumb-2 encodings a Cortex-M4
# actually executes. Checked against `arm-none-eabi-objdump` over 172,032 wide
# encodings, 1,260 `IT`-block renderings and a real compiled image.
#
# **Not built: the interpreter.** Nothing here executes an Armv7E-M
# instruction, and that is a decision with a reason rather than a gap. QEMU is
# not installed on this machine — verified 2026-08-25 — so there is no way to
# lockstep a Thumb-2 interpreter against anything. `docs/architectures.md`
# records that even where QEMU exists it is a *single* oracle for cortex-m4,
# with no independent second source, so a disagreement could be detected and
# not adjudicated.
#
# A Thumb-2 interpreter verified only by tests written by whoever wrote the
# interpreter is the kind of evidence this repository declines to produce, and
# `rules/board-claims.md` exists because that declining has to be structural.
# So the decode half — which has a real, independent oracle — was taken as far
# as it goes, and the execution half was left with the reason written down.
#
# ## Why that is safe to ship
#
# `test_the_interpreter_refuses_every_thumb2_prefix` is the load-bearing one.
# `core/cortexm0/exec.cc` answers `StepResult::Unimplemented` — processor
# completely untouched — for every 32-bit encoding, so a Cortex-M4 image loaded
# onto a board today stops on its first wide instruction and says which one.
# It does not execute half of it and it does not decode it as something else.
#
# ## And why the sweeps live in tools/
#
# `tools/sweep_thumb2.py` holds the comparison and this file asserts on what it
# returns. One sweep, two callers: the CLI answers "what should I write next",
# which is not a pass or a fail, and these tests answer "is it still right".

import pathlib
import re
import shutil
import subprocess

import pytest

from core.cortexm0 import disasm
from tools import sweep_thumb2

HERE = pathlib.Path(__file__).resolve().parent
PROBE = HERE / "m4" / "probe.bin"
SOURCE = HERE / "m4" / "probe.c"
SCRIPT = HERE / "m4" / "probe.ld"

#: Where `probe.ld` links. nRF52840 flash starts at zero; the offset leaves
#: room for a vector table and keeps every branch target five hex digits wide.
PROBE_BASE = 0x00010000

#: Every 32-bit Thumb-2 prefix group, one representative each, as
#: `(first halfword, second halfword)`. Used by the test that pins the
#: interpreter's refusal, so a future Thumb-2 interpreter has to update a test
#: whose name says what it is protecting.
PREFIXES = {
    "0xE8 load/store multiple": (0xE8B0, 0x0006),
    "0xE9 load/store dual": (0xE9C0, 0x1200),
    "0xEB data-processing, shifted register": (0xEB01, 0x0002),
    "0xF1 data-processing, modified immediate": (0xF101, 0x0001),
    "0xF8 load/store single": (0xF8D0, 0x1004),
    "0xFA data-processing, register": (0xFAB3, 0xF383),
    "0xFB multiply": (0xFB01, 0xF002),
}


def objdump() -> pathlib.Path:
    path = sweep_thumb2.objdump_path()
    if path is None:
        pytest.skip("no arm-none-eabi-objdump on PATH or in ~/.platformio")
    return path


def probe_bytes() -> bytes:
    if not PROBE.is_file():
        pytest.skip(f"{PROBE} is missing")
    return PROBE.read_bytes()


# --- the sweeps -------------------------------------------------------------


def test_the_wide_encoding_sweep_finds_no_disagreement():
    """Every wide first halfword, 0xE800..0xFFFF, against a spread of second
    halfwords: 172,032 encodings compared with objdump.

    **The floor on `agreed` is the half that matters.** A decoder that named
    nothing would have zero disagreements too, which is exactly how the RISC-V
    sweeps managed to stay green over a broken `fence` — see
    `docs/HANDOFF_2026-08-25_the-esp32-c-series.md` 3.3. So this asserts both
    directions: nothing wrong, and a great deal right.
    """
    report = sweep_thumb2.compare(objdump())
    assert not report.wrong, "\n".join(str(d) for d in report.wrong[:20])
    assert report.swept > 170_000, report.swept
    assert report.agreed > 55_000, (
        f"only {report.agreed} encodings agreed; a sweep with no disagreements "
        f"and nothing decoded is not evidence"
    )


def test_the_only_accounted_difference_is_the_one_objdump_loses():
    """The exclusion list, asserted rather than trusted.

    objdump renders a pre-indexed `LDRD`/`STRD` with a positive zero offset
    identically to the no-writeback encoding beside it, losing a bit. This
    decoder keeps the `!`. That is the **only** accepted difference, it is
    recognised by a predicate over the encoding rather than by mnemonic, and it
    is asserted to be non-empty so that the accounting cannot quietly become
    dead code describing a version of objdump nobody runs any more.
    """
    report = sweep_thumb2.compare(objdump())
    assert report.accounted, (
        "nothing matched the writeback accounting; either objdump changed or "
        "the predicate no longer selects anything, and either way "
        "`objdump_drops_writeback` is now a comment about the past"
    )
    for divergence in report.accounted:
        assert divergence.mine == divergence.theirs + "!"
        assert divergence.mine.split()[0] in ("ldrd", "strd")


def test_the_it_block_sweep_finds_no_disagreement():
    """Every defined `IT` encoding, each followed by five instructions.

    A separate sweep because `IT` cannot be checked one encoding at a time: it
    changes how the instructions *after* it render. 14 conditions by 15 masks,
    and the `al`-with-else-arm case is left out as UNPREDICTABLE — see
    `tools.sweep_thumb2.it_sequences`.
    """
    report = sweep_thumb2.compare_stream(objdump(), sweep_thumb2.it_sequences())
    assert not report.wrong, "\n".join(str(d) for d in report.wrong[:20])
    assert not report.unnamed, report.unnamed[:10]
    assert report.agreed == report.swept == 1260, report.summary()


# --- a real compiled image --------------------------------------------------


def test_the_committed_probe_disassembles_the_way_objdump_does():
    """The whole point, on real compiler output rather than on a sweep.

    Line for line and **by address**, not by position: two linear
    disassemblers do not agree on stride, so zipping their output drifts the
    moment either meets something it does not know.
    """
    image = probe_bytes()
    theirs = _objdump_lines(image)
    mine = disasm.disassemble(image, PROBE_BASE, disasm.Profile.V7EM)

    assert mine, "the probe disassembled to nothing"
    for line in mine:
        ours = sweep_thumb2.normalise(line.text)
        assert line.address in theirs, (
            f"objdump has no instruction at 0x{line.address:x}, which means "
            f"the two disassemblers disagree about a width earlier on"
        )
        assert ours == theirs[line.address], (
            f"0x{line.address:x}: this module says {ours!r}, "
            f"objdump says {theirs[line.address]!r}"
        )


def test_the_probe_is_still_worth_disassembling():
    """A fixture that drifted into being all 16-bit would pass the test above
    while checking none of this ticket's work.

    Asserted on the properties that make it a Cortex-M4 image: a third of it is
    wide, and the encodings that only exist on Armv7-M are present.
    """
    lines = disasm.disassemble(probe_bytes(), PROBE_BASE, disasm.Profile.V7EM)
    wide = [line for line in lines if line.width == 4]
    assert len(wide) > len(lines) // 4, (
        f"only {len(wide)} of {len(lines)} instructions are 32-bit; the probe "
        f"has stopped being a Thumb-2 fixture"
    )
    # Checked against what GCC actually emitted rather than what `probe.c` asks
    # for. The source requests a 64-bit multiply-accumulate and GCC chose a
    # different sequence than `umlal`, so asserting on `umlal` would be
    # asserting on a compiler's mood: this names the instructions that are
    # really in the committed bytes, one from each group worth covering.
    text = " ".join(line.text for line in lines)
    for wanted in ("clz", "sdiv", "udiv", "ldrd", "it", "cbz", "ldmia.w"):
        assert wanted in text, f"no {wanted} in the probe"
    assert not [line for line in lines if line.text.startswith((".word", ".short"))], (
        "this decoder cannot name every instruction in its own fixture"
    )


def test_the_committed_probe_matches_its_source():
    """Skipped where no toolchain exists rather than failing, the same contract
    the other compiled fixtures keep."""
    home = pathlib.Path.home() / ".platformio/packages/toolchain-gccarmnoneeabi/bin"
    compiler = shutil.which("arm-none-eabi-gcc") or home / "arm-none-eabi-gcc.exe"
    objcopy = shutil.which("arm-none-eabi-objcopy") or home / "arm-none-eabi-objcopy.exe"
    if not pathlib.Path(compiler).is_file() or not pathlib.Path(objcopy).is_file():
        pytest.skip("no arm-none-eabi toolchain")

    import tempfile

    with tempfile.TemporaryDirectory() as work:
        elf = pathlib.Path(work) / "probe.elf"
        rebuilt = pathlib.Path(work) / "probe.bin"
        subprocess.run(
            [str(compiler), "-mthumb", "-march=armv7e-m", "-mfloat-abi=soft",
             "-Os", "-ffreestanding", "-nostdlib", "-nostartfiles",
             "-T", str(SCRIPT), "-o", str(elf), str(SOURCE)],
            check=True, capture_output=True,
        )
        subprocess.run([str(objcopy), "-O", "binary", str(elf), str(rebuilt)],
                       check=True, capture_output=True)
        assert rebuilt.read_bytes() == probe_bytes()


# --- the profile is a real gate, not a label --------------------------------


def test_the_two_profiles_disagree_about_how_long_an_instruction_is():
    """The single rule the whole profile exists for.

    `0xE8B0` is an undefined 16-bit encoding on Armv6-M and the first half of
    `ldmia.w` on Armv7-M. Getting this wrong does not print one wrong line; it
    desynchronises the stream and prints wrong lines to the end of the buffer.
    """
    assert not disasm.is_wide(0xE8B0, disasm.Profile.V6M)
    assert disasm.is_wide(0xE8B0, disasm.Profile.V7EM)
    assert not disasm.is_wide(0xE7FE, disasm.Profile.V6M), "b.n is 16 bits on both"
    assert not disasm.is_wide(0xE7FE, disasm.Profile.V7EM)
    # `BL` is the one wide encoding Armv6-M has, so both agree here.
    assert disasm.is_wide(0xF000, disasm.Profile.V6M)
    assert disasm.is_wide(0xF000, disasm.Profile.V7EM)


def test_an_armv6m_part_reads_the_same_bytes_as_something_else():
    """Two profiles over one buffer, and they do not merely differ in coverage
    — they differ in **where the instructions start**.

    An Armv6-M part meeting these four bytes sees an undefined halfword
    followed by a perfectly ordinary `movs`; an Armv7E-M part sees one
    `ldmia.w`. Both readings are correct about their own silicon, which is why
    the profile is a parameter rather than a fix.

    **The second halfword is the point.** It is not garbage on either part:
    `0x0006` really is `movs r6, r0`, so an Armv6-M reading of a Cortex-M4
    image does not produce obvious rubbish. It produces a plausible listing,
    shifted, which is the failure this rule exists to prevent.
    """
    image = bytes.fromhex("b0e80600")
    narrow = disasm.disassemble(image, 0, disasm.Profile.V6M)
    wide = disasm.disassemble(image, 0, disasm.Profile.V7EM)
    assert [line.width for line in narrow] == [2, 2]
    assert [line.width for line in wide] == [4]
    assert narrow[0].text.startswith(".short"), "Armv6-M has no 0xE8B0"
    assert narrow[1].text == "movs	r6, r0", (
        "the trailing halfword of a wide instruction read as a narrow one, "
        "and it is a real instruction rather than an obvious error"
    )
    assert wide[0].text.startswith("ldmia.w")


def test_the_narrow_armv7m_encodings_are_refused_on_armv6m():
    """**Armv7E-M adds 16-bit encodings too**, which is the thing "a strict
    superset" hides. `CBZ`, `CBNZ` and `IT` are two bytes long and sit in space
    Armv6-M leaves undefined, so the profile has to reach the narrow decoder
    and not only the width rule.
    """
    for encoding, expected in ((0xB129, "cbz"), (0xB9A1, "cbnz"), (0xBF08, "it")):
        wide, _ = disasm.decode(encoding, 0x100C0, None, disasm.Profile.V7EM)
        assert wide.startswith(expected), wide
        narrow, width = disasm.decode(encoding, 0x100C0, None, disasm.Profile.V6M)
        assert narrow.startswith(".short"), (
            f"0x{encoding:04x} is Armv7-M only; an Armv6-M listing must not "
            f"name it, and this said {narrow!r}"
        )
        assert width == 2


def test_a_wide_encoding_this_decoder_cannot_name_still_has_width_four():
    """The property that keeps an unknown instruction from corrupting every
    line after it. The text is one wrong line; the width is the rest of the
    buffer.

    A coprocessor encoding, which a Cortex-M4 without external coprocessors
    does not have and this decoder does not attempt.
    """
    text, width = disasm.decode(0xEC00, 0, 0x1234, disasm.Profile.V7EM)
    assert width == 4
    assert text.startswith(".word"), text
    assert "0xec001234" in text, "and it prints the bytes rather than a guess"


def test_half_a_wide_instruction_at_the_end_of_a_buffer_is_not_invented():
    """Claiming width 4 for bytes that are not there would be inventing the
    missing half. The halfword is rendered as itself instead."""
    text, width = disasm.decode(0xE8B0, 0, None, disasm.Profile.V7EM)
    assert width == 2
    assert text.startswith(".short")


# --- the pre-existing defect this ticket surfaced ---------------------------


def test_pop_decodes_on_both_profiles():
    """A bug that predates this ticket, pinned so it cannot come back.

    `core/cortexm0/disasm.py` tested bits 11:9 against `0b010` for PUSH/POP.
    Bit 11 is the *load* bit, so the test matched PUSH only and every POP fell
    through to `.short` — on Armv6-M, where it has always been a legal
    instruction.

    It survived `tests/cortexm0/test_disasm.py`'s four-image objdump
    comparison because **none of those four images contains a POP**: they are
    `for(;;)` leaves that never return. The Armv7E-M probe has real functions,
    and found it immediately.
    """
    for profile in (disasm.Profile.V6M, disasm.Profile.V7EM):
        assert disasm.decode(0xBD30, 0, None, profile)[0] == "pop\t{r4, r5, pc}"
        assert disasm.decode(0xBC30, 0, None, profile)[0] == "pop\t{r4, r5}"
        assert disasm.decode(0xB570, 0, None, profile)[0] == "push\t{r4, r5, r6, lr}"


# --- what makes shipping a decoder with no interpreter honest ---------------


def test_the_interpreter_refuses_every_thumb2_prefix():
    """The reason a decoder without an interpreter is safe to ship.

    `core/cortexm0/exec.cc` implements Armv6-M. Every Thumb-2 encoding must
    come back as `Unimplemented` with the **processor completely untouched** —
    not executed, not partially executed, and not decoded as some 16-bit
    instruction that happens to share bits.

    That last one is the risk the width rule creates: `0xE8B0` is a real
    halfword on both parts, and an interpreter that read it as Armv6-M would
    step two bytes into the middle of a 32-bit instruction and carry on.

    **When someone writes the Thumb-2 interpreter this test fails**, which is
    intended: it is the list of things that have to start working, and its
    name says what it is protecting.
    """
    abi = pytest.importorskip("core.cortexm0.abi")
    ram, entry = 0x20000000, 0x20000100

    with abi.Cpu() as cpu:
        for name, (hw1, hw2) in PREFIXES.items():
            cpu.clear_regions()
            cpu.add_region(ram, 0x1000)
            cpu.write_block(entry, hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little"))
            cpu.set_regs([0] * 13 + [ram + 0x800, 0, entry], apsr=0)
            before = list(cpu.get_regs().as_list())
            with pytest.raises(abi.Unimplemented):
                cpu.step()
            assert list(cpu.get_regs().as_list()) == before, (
                f"{name}: refused, but the processor moved"
            )


def test_every_prefix_group_the_decoder_names_is_one_the_interpreter_refuses():
    """The two halves of this ticket, checked against each other.

    Each representative in `PREFIXES` is an instruction this file's decoder
    *does* name — otherwise the test above would be asserting that the
    interpreter refuses encodings nobody claims to understand, which is true of
    every random halfword and proves nothing.
    """
    for name, (hw1, hw2) in PREFIXES.items():
        text, width = disasm.decode(hw1, 0, hw2, disasm.Profile.V7EM)
        assert width == 4, name
        assert not text.startswith((".word", ".short")), (
            f"{name}: the decoder does not name 0x{hw1:04x}{hw2:04x}, so the "
            f"interpreter refusing it says nothing"
        )


# --- objdump, read the way the sweeps read it -------------------------------


def _objdump_lines(image: bytes) -> dict[int, str]:
    """objdump's rendering of `image` at `PROBE_BASE`, keyed by address."""
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        binary = pathlib.Path(work) / "probe.bin"
        binary.write_bytes(image)
        result = subprocess.run(
            [str(objdump()), "-D", "-b", "binary", "-m", sweep_thumb2.ARCH,
             "-M", "force-thumb", f"--adjust-vma={PROBE_BASE:#x}", str(binary)],
            check=True, capture_output=True, text=True,
        )
    out: dict[int, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{4} ?)+)\s+(.*)$", line)
        if match:
            body = match.group(3).split("@")[0].split(";")[0]
            out[int(match.group(1), 16)] = sweep_thumb2.normalise(body)
    return out
