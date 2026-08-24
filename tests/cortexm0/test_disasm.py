# OpenHardware — Armv6-M as text, checked against a disassembler nobody here wrote.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why the oracle matters more here than usual
#
# `core/cortexm0/disasm.py` is a **second decoder**. `core/i8086/disasm.py`
# refuses to be one, taking length and operands from the C decoder through the
# ABI — but `core/cortexm0/exec.cc` decodes inline as it executes and exposes
# nothing, so there is nothing to defer to.
#
# A second decoder is safe only while something independent checks it, and
# `arm-none-eabi-objdump` is about as independent as this repository gets: it
# is Arm's own toolchain, neither this file nor `exec.cc` had any hand in it,
# and it reads the same committed images the core already runs.
#
# ## Two checks, and the second is the one that found the bugs
#
# The four committed images are 162 instructions of real compiler output. That
# is a good check and a narrow one: between them they contain no byte-reverse,
# no `CPS`, no `SVC` and no high-register `BX` with a malformed operand.
#
# So the second check sweeps **every 16-bit encoding the disassembler claims**
# — 56,551 of the 65,536 — and compares each against objdump. It found three
# real defects the images could not:
#
#   * the `rev`/`rev16`/`revsh` table was indexed with its gap in the wrong
#     slot, so it named 64 undefined encodings `rev16` and never named a real
#     one correctly;
#   * `BX`/`BLX` accepted nonzero low bits, which are UNPREDICTABLE;
#   * `MOV r8, r8` is the canonical no-op and was printed as a move.
#
# ## Where the two tools legitimately disagree
#
# objdump decodes a wider architecture than this core has. Told `-m armv6-m` it
# still renders 32-bit Thumb-2 (`and.w`) and Armv8-M security instructions
# (`bxns`), which Armv6-M does not define. Those show up only where a literal
# pool is being decoded as code — see
# `test_the_comparison_stops_where_the_code_does`, which is about that boundary
# and says why it is not a fudge.

import itertools
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from core.cortexm0 import disasm

HERE = pathlib.Path(__file__).resolve().parent

#: Every committed image in this suite: four real compiler outputs, two chips.
IMAGES = (
    "blink/blink.bin",
    "samd21/blink.bin",
    "uart/hello.bin",
    "timer/delay.bin",
)

#: `   e:\t4b0b      \tldr\tr3, [pc, #44]\t@ (0x3c)`
ROW = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f ]+?)\s{2,}(\S+)\s*(.*)$")


def objdump() -> pathlib.Path:
    """The toolchain's disassembler, or skip.

    PATH first, then the PlatformIO toolchain this machine happens to have —
    the same order `test_blink.py` uses, and for the same reason: a check that
    runs on one computer protects nothing on CI. **Absence is a skip and never
    a pass**, the contract every checker in this repository keeps.
    """
    found = shutil.which("arm-none-eabi-objdump")
    path = pathlib.Path(found) if found else pathlib.Path(
        os.environ.get("USERPROFILE", pathlib.Path.home()),
        ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-objdump.exe",
    )
    if not path.is_file():
        pytest.skip(f"no arm-none-eabi-objdump on PATH or at {path}")
    return path


def objdump_text(binary: pathlib.Path) -> dict[int, str]:
    """objdump's rendering of `binary`, address to `mnemonic\\toperands`.

    **Trailing `@` annotations are dropped**, and that is the one deliberate
    difference between the two renderings. objdump computes conveniences —
    `movs r2, #144  @ 0x90`, `ldr r3, [pc, #44]  @ (0x3c)` — which are not part
    of the instruction. Reproducing the rules for when it emits them would be
    an argument about formatting rather than about decoding, and a difference
    in the part that is compared is a difference that means somebody is wrong.
    """
    result = subprocess.run(
        [str(objdump()), "-D", "-b", "binary", "-m", "armv6-m",
         "-M", "force-thumb", str(binary)],
        capture_output=True, text=True, check=True,
    )
    out: dict[int, str] = {}
    for line in result.stdout.splitlines():
        matched = ROW.match(line)
        if not matched:
            continue
        address, _raw, mnemonic, operands = matched.groups()
        operands = operands.split("@")[0].strip()
        out[int(address, 16)] = f"{mnemonic}\t{operands}".rstrip("\t ")
    return out


# --- the committed images ---------------------------------------------------


def test_every_committed_image_disassembles_the_way_objdump_does():
    """Four real compiler outputs across two chips, instruction by instruction.

    **A wrong width is what this really guards.** A wrong mnemonic is one wrong
    line; a wrong length desynchronises every line after it, so a boundary
    error fails here immediately rather than showing plausible nonsense half a
    screen down.
    """
    compared = 0
    for name in IMAGES:
        binary = HERE / name
        theirs = objdump_text(binary)
        for line in disasm.disassemble(binary.read_bytes()):
            # The literal pool is data. See the boundary test below.
            if line.text.startswith(".short"):
                break
            assert line.address in theirs, (
                f"{name}: objdump has no instruction at 0x{line.address:x}, "
                f"so the two disagree about an instruction's length"
            )
            assert line.text.rstrip("\t ") == theirs[line.address], (
                f"{name} 0x{line.address:x}: objdump says "
                f"{theirs[line.address]!r}, this says {line.text!r}"
            )
            compared += 1
    assert compared >= 100, (
        f"only {compared} instructions compared; the images or the boundary "
        f"rule changed and this test is no longer checking what it claims"
    )


def test_the_comparison_stops_where_the_code_does():
    """The boundary is the literal pool, and it is a real one rather than a
    convenient place to stop.

    `blink.c` loads peripheral addresses through `ldr rN, [pc, #...]`, so its
    constants sit in flash immediately after the code. `0x4000f000` — which is
    `RESETS_RESET + ALIAS_CLR` — is stored little-endian, so the halfword there
    is `0xf000`, which begins the 32-bit Thumb prefix. objdump pairs it with
    the next halfword and renders `and.w`, an Armv7-M instruction this core
    does not have and this disassembler correctly refuses.

    Neither tool is wrong. objdump decodes a wider architecture than Armv6-M
    even when told `-m armv6-m`, and past the last instruction both are
    decoding data. This pins where that starts so the stopping rule cannot
    quietly swallow real code.
    """
    binary = HERE / "blink/blink.bin"
    lines = disasm.disassemble(binary.read_bytes())
    first_data = next(i for i, line in enumerate(lines) if line.text.startswith(".short"))
    # Everything before it decoded; the halfword there is the low half of a
    # peripheral address, not an instruction.
    assert lines[first_data].encoding == 0xF000
    assert first_data > 20, "the code region should be most of a 76-byte image"


# --- every encoding it claims ------------------------------------------------


def test_every_encoding_it_claims_matches_objdump():
    """The exhaustive check: all 65,536 halfwords, restricted to the ones this
    disassembler says it knows.

    Restricted rather than exhaustive over the whole space, because what this
    can honestly assert is *"everything I claim, I claim correctly"*. What
    objdump makes of the encodings rendered `.short` is a question about a
    wider architecture, and cataloguing its answers would be describing a tool
    rather than checking one.

    Concatenating the claimed encodings into one binary is safe because every
    one of them is below 0xE800: the 32-bit prefixes are `11101`, `11110` and
    `11111`, and all three are either `BL` — which is width 4 and excluded — or
    `.short`. So no pair of adjacent test encodings can be read as one 32-bit
    instruction by either side. The assertion below pins that, since it is the
    thing that would silently invalidate the whole comparison.
    """
    objdump()      # skip early rather than build a corpus we cannot check

    claimed = []
    for encoding in range(0x10000):
        text, width = disasm.decode(encoding, 0, None)
        if width == 2 and not text.startswith(".short"):
            claimed.append(encoding)

    assert claimed, "the disassembler claims nothing; the decoder is broken"
    assert max(claimed) < 0xE800, (
        f"0x{max(claimed):04x} is claimed as a 16-bit instruction and sits in "
        f"the 32-bit prefix space, so this corpus can no longer be laid out "
        f"end to end"
    )

    blob = b"".join(e.to_bytes(2, "little") for e in claimed)
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "claimed.bin"
        path.write_bytes(blob)
        theirs = objdump_text(path)

    for index, encoding in enumerate(claimed):
        mine = disasm.decode(encoding, index * 2, None)[0].rstrip("\t ")
        assert theirs.get(index * 2) == mine, (
            f"0x{encoding:04x}: objdump says {theirs.get(index * 2)!r}, "
            f"this says {mine!r}"
        )


def test_it_claims_most_of_the_encoding_space():
    """A guard on the test above, which would pass trivially if the
    disassembler claimed almost nothing. Armv6-M leaves a lot undefined, but
    the bulk of the 16-bit map is real instructions."""
    claimed = sum(
        1 for e in range(0x10000)
        if not disasm.decode(e, 0, None)[0].startswith(".short")
    )
    assert claimed > 50_000, f"only {claimed} of 65,536 encodings are decoded"


# --- the cases the sweep found ------------------------------------------------


def test_shifting_left_by_zero_is_a_move():
    """Armv6-M has no separate `MOV (register)` — `LSLS Rd, Rs, #0` *is* it,
    which is why objdump prints `movs`."""
    assert disasm.decode(0x0011)[0] == "movs\tr1, r2"


def test_shifting_right_by_zero_means_thirty_two():
    """`Shift_C` in DDI0419: imm5 == 0 encodes 32 for LSR and ASR, the same
    rule `core/cortexm0/shift.cc` implements."""
    assert disasm.decode(0x0800)[0] == "lsrs\tr0, r0, #32"
    assert disasm.decode(0x1000)[0] == "asrs\tr0, r0, #32"


def test_the_byte_reverses_are_not_off_by_one():
    """The defect the sweep found: 00 is `rev`, 01 is `rev16`, 11 is `revsh`,
    and **10 is not a byte-reverse at all**."""
    assert disasm.decode(0xBA00)[0] == "rev\tr0, r0"
    assert disasm.decode(0xBA40)[0] == "rev16\tr0, r0"
    assert disasm.decode(0xBAC0)[0] == "revsh\tr0, r0"
    assert disasm.decode(0xBA80)[0].startswith(".short")


def test_a_branch_exchange_with_rubbish_in_its_low_bits_is_not_one():
    """Nonzero low bits are UNPREDICTABLE. Accepting them named 96 encodings
    `blx`."""
    assert disasm.decode(0x4700)[0] == "bx\tr0"
    assert disasm.decode(0x4701)[0].startswith(".short")


def test_the_traditional_no_op_is_spelled_nop():
    """`MOV r8, r8`, which predates Armv6-M's own `nop` at 0xbf00."""
    assert disasm.decode(0x46C0)[0] == "nop"
    assert disasm.decode(0xBF00)[0] == "nop"


def test_only_the_two_defined_processor_state_changes_are_claimed():
    """Armv6-M defines `CPSIE i` and `CPSID i`. The first mask claimed sixteen
    encodings for those two."""
    assert disasm.decode(0xB662)[0] == "cpsie\ti"
    assert disasm.decode(0xB672)[0] == "cpsid\ti"
    assert disasm.decode(0xB660)[0].startswith(".short")


# --- widths and the unimplemented rendering -----------------------------------


def test_the_branch_with_link_pair_is_four_bytes_wide():
    """The one 32-bit instruction Armv6-M has, and the only place a width can
    be 4."""
    text, width = disasm.decode(0xF000, 0, 0xF800)
    assert width == 4
    assert text.startswith("bl\t")


def test_half_a_branch_with_link_is_not_an_instruction():
    """A `BL` prefix with nothing after it — the end of a buffer. Rendering it
    as a branch to somewhere would invent a destination."""
    text, width = disasm.decode(0xF000, 0, None)
    assert width == 2
    assert text == ".short\t0xf000"


def test_an_unimplemented_encoding_names_its_halfword():
    """Never blank and never a guess. A listing with a hole invites the reader
    to assume the hole is nothing, and `StepResult::Unimplemented` exists to
    say the opposite."""
    assert disasm.decode(0xDE00)[0] == "udf\t#0"
    assert disasm.decode(0xB680)[0] == ".short\t0xb680"


def test_addresses_and_widths_advance_together():
    """Each line starts where the last one ended. The property the image
    comparison depends on, asserted directly so a failure there is easier to
    place."""
    lines = disasm.disassemble((HERE / "uart/hello.bin").read_bytes(), base=0x10000100)
    assert lines[0].address == 0x10000100
    for before, after in itertools.pairwise(lines):
        assert after.address == before.address + before.width


# --- reading through a CPU ----------------------------------------------------


def test_it_disassembles_out_of_a_running_board(cpu):
    """The entry point `webui/emulator.py` will need: instructions read from a
    CPU's memory rather than from a file."""
    from webui.boards import rp2040

    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    image = (HERE / "uart/hello.bin").read_bytes()
    cpu.write_block(0x10000100, image)

    lines = disasm.disassemble_range(cpu, 0x10000108, 4)
    assert len(lines) == 4
    assert lines[0].address == 0x10000108
    from_file = disasm.disassemble(image, base=0x10000100)
    expected = {line.address: line.text for line in from_file}
    for line in lines:
        assert line.text == expected[line.address]


def test_reading_past_the_end_of_memory_stops_rather_than_raises(cpu):
    """A listing pane wants what it can show. Faulting whole would blank the
    view because its last line ran off a region."""
    from webui.boards import rp2040

    cpu.clear_memory()
    cpu.clear_registers()
    cpu.clear_regions()
    rp2040.install(cpu)
    top = rp2040.SRAM + rp2040.SRAM_SIZE - 4
    assert len(disasm.disassemble_range(cpu, top, 8)) < 8
