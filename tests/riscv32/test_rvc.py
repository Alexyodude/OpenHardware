# OpenHardware — the compressed instructions, swept against objdump.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why an exhaustive sweep and not a corpus
#
# `tests/rv32/corpus/rv32c.json` holds ten cases. RV32C has around thirty
# encodings and 49,152 halfwords that reach them, so a corpus of ten is a
# sample of a compiler's habits — and the encodings a compiler never emits are
# exactly the ones a hand-written decoder gets wrong. `tests/cortexm0/
# test_disasm.py` made that concrete: 56,551 encodings swept, three real bugs
# that four real firmware images could not find.
#
# The compressed space is small enough to enumerate whole, so it is.
#
# ## Two sweeps, because one of them proves less than it looks
#
# **Legality** — does this core refuse exactly what the architecture refuses?
# That catches a mis-shaped quadrant or a reserved encoding treated as real.
#
# **Operands** — a transposed pair of immediate bits leaves an encoding
# perfectly legal and makes it mean a different offset. It does not fault; it
# loads from somewhere plausible or jumps somewhere plausible, which is the
# silent class this repository ranks worst. So the second sweep *executes*
# every legal encoding from a known state and checks the result against the
# operands objdump decoded for that same halfword.
#
# The second one caught nothing in the core and did catch a bug in itself:
# objdump prints a branch target as an ABSOLUTE address inside the swept blob,
# not as a displacement, and reading it as a displacement failed 8,192
# encodings across all four pc-relative classes at once. Four classes failing
# together is the shape of a harness bug, and it is worth saying so here
# because the next person to see a large round failure count should suspect
# the same thing before they suspect the decoder.
#
# ## Where objdump is not the authority
#
# It decodes a wider architecture than the part has — the same trap
# `tests/cortexm0/test_disasm.py` documents for `and.w` and `bxns`. Told
# `-m riscv:rv32` it still renders `c.fld`, `c.flw`, `c.fsd`, `c.fsw` and
# their stack-pointer forms, which are Zcd and Zcf and need D and F. **No part
# in this repository has an FPU**, so all eight must raise
# illegal-instruction, and `ACCOUNTED` below names every such class with the
# reason. A divergence outside that table is a bug in this core.

import itertools
import pathlib
import re
import shutil
import subprocess

import pytest

from core.riscv32 import abi

#: Every halfword that is a compressed instruction rather than the low half of
#: a 32-bit one. `(c & 3) != 3` is exactly that condition, which is also what
#: lets them be laid end to end and disassembled in a single pass.
CANDIDATES = [c for c in range(1 << 16) if (c & 3) != 3]

#: Where the encoding under test is placed, and a region wide enough that a
#: load or a store reaches memory rather than faulting.
BASE = 0x1000
RAM = 0x40000
REGION = 0x80000

#: x0..x31 as objdump spells them.
NAMES = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)
NUMBER = {name: index for index, name in enumerate(NAMES)}
NUMBER["fp"] = 8

#: Classes objdump renders and this core must refuse, each with the reason.
#:
#: **Every entry is a fact about the part, not a tolerance.** Zcd and Zcf are
#: compressed float accesses and need D and F; the shift forms with a set bit
#: 12 are RV64's six-bit shift amount, which cannot be right on a machine with
#: 32-bit registers. If a future part here has an FPU, the first four rows stop
#: being correct and this test is where that shows up.
ACCOUNTED = {
    "c.fld": "Zcd: needs D, and no part here has an FPU",
    "c.fldsp": "Zcd: needs D, and no part here has an FPU",
    "c.flw": "Zcf: needs F, and no part here has an FPU",
    "c.flwsp": "Zcf: needs F, and no part here has an FPU",
    "c.fsd": "Zcd: needs D, and no part here has an FPU",
    "c.fsdsp": "Zcd: needs D, and no part here has an FPU",
    "c.fsw": "Zcf: needs F, and no part here has an FPU",
    "c.fswsp": "Zcf: needs F, and no part here has an FPU",
    "c.slli": "shamt >= 32 is RV64's six-bit field; reserved on RV32",
    "c.srli": "shamt >= 32 is RV64's six-bit field; reserved on RV32",
    "c.srai": "shamt >= 32 is RV64's six-bit field; reserved on RV32",
}

_LINE = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f]{4})\s+(\S+)\s*(.*)$")
_MEM = re.compile(r"^(-?\d+)\((\w+)\)$")


def objdump() -> pathlib.Path:
    """The toolchain's disassembler, or skip.

    **Absence is a skip and never a pass**, the same contract the rule checkers
    keep when they cannot find a PICSimLab source tree: a differential test that
    silently became a no-op is worse than one that says it did not run.
    """
    found = shutil.which("riscv32-esp-elf-objdump")
    if found:
        return pathlib.Path(found)
    path = pathlib.Path.home() / (
        ".platformio/packages/toolchain-riscv32-esp/bin/riscv32-esp-elf-objdump.exe"
    )
    if not path.is_file():
        pytest.skip(f"no riscv32-esp-elf-objdump on PATH or at {path}")
    return path


@pytest.fixture(scope="module")
def decoded(tmp_path_factory) -> dict[int, tuple[str, str, int]]:
    """Every candidate encoding, as objdump reads it.

    One subprocess for all 49,152, because they are laid end to end into a
    single blob. The address each one landed at is carried through as well as
    its text: objdump prints a branch target as an absolute address in that
    blob, so the displacement is only recoverable by subtraction.
    """
    binary = objdump()
    blob = b"".join(c.to_bytes(2, "little") for c in CANDIDATES)
    path = tmp_path_factory.mktemp("rvc") / "all.bin"
    path.write_bytes(blob)
    out = subprocess.run(
        [str(binary), "-D", "-b", "binary", "-m", "riscv:rv32",
         "-M", "no-aliases", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout

    table: dict[int, tuple[str, str, int]] = {}
    for line in out.splitlines():
        match = _LINE.match(line)
        if match:
            table[int(match.group(2), 16)] = (
                match.group(3), match.group(4).strip(), int(match.group(1), 16)
            )
    return table


@pytest.fixture(scope="module")
def machine():
    """An ESP32-C3 with one wide region, for the life of this module.

    Module-scoped because building a core per encoding would pay for 49,152
    allocations to test a pure function of sixteen bits.
    """
    with abi.Cpu() as cpu:
        cpu.set_extensions(abi.ESP32_C3)
        cpu.add_region(0x0000, REGION, executable=True)
        yield cpu


def known_registers() -> list[int]:
    """A distinct value in every register, so reading the wrong one is a wrong
    answer rather than a coincidence."""
    regs = [RAM + i * 0x40 for i in range(32)]
    regs[0] = 0
    return regs


def verdict(cpu, encoding: int) -> str:
    """What this core answers for one encoding: `illegal`, or `decoded`.

    A `MemoryFault` counts as decoded. The expansion was produced and then the
    access it described went somewhere unmapped, which is a fact about the
    address and not about the decode.
    """
    cpu.set_regs(known_registers(), pc=BASE)
    # The upper halfword is a `c.nop`, so a two-byte instruction is followed by
    # something legal rather than by whatever the previous case left.
    cpu.write_word(BASE, encoding | (0x0001 << 16))
    try:
        cpu.step()
    except abi.Illegal:
        return "illegal"
    except (abi.Unimplemented, abi.MemoryFault):
        return "decoded"
    return "decoded"


def test_every_compressed_encoding_agrees_with_objdump_about_legality(decoded, machine):
    """The sweep. 49,152 encodings, and every divergence named.

    A divergence is allowed only where `ACCOUNTED` explains it, and only in the
    direction where objdump decodes something this part refuses. **The other
    direction is never allowed**: an encoding objdump cannot decode and this
    core executes would be this core inventing an instruction.
    """
    unexplained: list[str] = []
    invented: list[str] = []
    agreed = 0

    for encoding in CANDIDATES:
        mnemonic, operands, _ = decoded.get(encoding, ("<missing>", "", 0))
        # objdump prints a bare `0x1234` when it cannot decode, and `c.unimp`
        # for the defined-illegal all-zero halfword.
        refused_by_objdump = mnemonic.startswith("0x") or mnemonic == "c.unimp"
        mine = verdict(machine, encoding)

        if refused_by_objdump == (mine == "illegal"):
            agreed += 1
        elif refused_by_objdump:
            invented.append(f"0x{encoding:04x}: objdump refuses it, this core ran it")
        elif mnemonic not in ACCOUNTED:
            unexplained.append(
                f"0x{encoding:04x}: objdump says {mnemonic} {operands}, "
                f"this core says illegal"
            )

    assert invented == [], invented[:10]
    assert unexplained == [], unexplained[:10]
    assert agreed > 30_000, f"only {agreed} exact agreements; the sweep is not running"


def test_the_encodings_this_part_has_no_hardware_for_are_actually_refused(
    decoded, machine
):
    """`ACCOUNTED` has to be an assertion and not a tolerance.

    **Found by mutation.** Making `c.fldsp` and friends decode left the sweep
    above passing, because that test only ever asks "did objdump decode
    something this core refused" -- and a core that wrongly *decodes* them
    agrees with objdump perfectly. The allowance was doing the job of a check.

    So each accounted class is now asserted in the direction that matters: this
    part has no FPU and 32-bit registers, so every one of these must raise
    illegal-instruction. If a part with an FPU ever arrives, this is the test
    that has to change, and its name says why.
    """
    refused: dict[str, int] = {}
    wrong: list[str] = []

    for encoding, (mnemonic, operands, _) in decoded.items():
        if mnemonic not in ACCOUNTED:
            continue
        # The shift mnemonics also cover legal RV32 shift amounts, and only the
        # ones with a set bit 12 are reserved. objdump prints the decoded
        # amount, so the split is readable rather than re-derived from bits.
        if mnemonic in ("c.slli", "c.srli", "c.srai"):
            amount = int(operands.rsplit(",", 1)[-1], 0)
            if amount < 32:
                continue
        if verdict(machine, encoding) != "illegal":
            wrong.append(f"0x{encoding:04x}: {mnemonic} {operands} -- {ACCOUNTED[mnemonic]}")
        refused[mnemonic] = refused.get(mnemonic, 0) + 1

    assert wrong == [], wrong[:10]
    assert set(refused) == set(ACCOUNTED), (
        f"accounted classes never reached: {sorted(set(ACCOUNTED) - set(refused))}"
    )
    assert sum(refused.values()) > 17_000, (
        f"only {sum(refused.values())} accounted encodings checked"
    )


def test_the_immediate_permutations_match_the_operands_objdump_decodes(decoded, machine):
    """Every scrambled immediate, executed and compared.

    This is the half that legality cannot reach. `c.addi4spn`'s immediate alone
    is four fields in a different order from the bits they come from, and
    getting it wrong produces a legal instruction with a wrong offset.
    """
    failures: list[str] = []
    checked = 0

    for encoding, (mnemonic, operands, at) in sorted(decoded.items()):
        args = [a.strip() for a in operands.split(",")] if operands else []
        regs = known_registers()

        if mnemonic in ("c.li", "c.addi", "c.andi", "c.addi16sp", "c.slli",
                        "c.srli", "c.srai", "c.lui"):
            if len(args) != 2 or args[0] not in NUMBER:
                continue
            rd, imm = NUMBER[args[0]], int(args[1], 0)
            after = _run(machine, regs, encoding)
            if after is None:
                continue
            checked += 1
            if rd == 0:
                continue          # a hint: the write to x0 discards
            before = _signed(regs[rd])
            if mnemonic == "c.li":
                want = imm
            elif mnemonic == "c.addi":
                want = before + imm
            elif mnemonic == "c.andi":
                want = before & imm
            elif mnemonic == "c.addi16sp":
                want = _signed(regs[2]) + imm
            elif mnemonic == "c.slli":
                want = regs[rd] << imm
            elif mnemonic == "c.srli":
                want = (regs[rd] & 0xFFFFFFFF) >> imm
            elif mnemonic == "c.srai":
                want = before >> imm
            else:
                want = imm << 12 if abs(imm) < 0x100000 else imm
            if (want & 0xFFFFFFFF) != after[rd]:
                failures.append(
                    f"0x{encoding:04x} {mnemonic} {operands}: "
                    f"want 0x{want & 0xFFFFFFFF:08x}, got 0x{after[rd]:08x}"
                )

        elif mnemonic == "c.addi4spn":
            if len(args) != 3 or args[0] not in NUMBER:
                continue
            rd, imm = NUMBER[args[0]], int(args[2], 0)
            after = _run(machine, regs, encoding)
            if after is None:
                continue
            checked += 1
            if after[rd] != (regs[2] + imm) & 0xFFFFFFFF:
                failures.append(
                    f"0x{encoding:04x} {mnemonic} {operands}: "
                    f"want 0x{regs[2] + imm:08x}, got 0x{after[rd]:08x}"
                )

        elif mnemonic in ("c.lw", "c.lwsp", "c.sw", "c.swsp"):
            if len(args) != 2 or args[0] not in NUMBER:
                continue
            memory = _MEM.match(args[1])
            if not memory:
                continue
            offset, base = int(memory.group(1)), NUMBER[memory.group(2)]
            target = (regs[base] + offset) & 0xFFFFFFFF
            checked += 1
            if mnemonic.startswith("c.l"):
                # A marker unique to this encoding, so a load from the wrong
                # address reads a different number rather than the same zero.
                marker = 0xA5A50000 | encoding
                machine.set_regs(regs, pc=BASE)
                machine.write_word(target, marker)
                machine.write_word(BASE, encoding | (0x0001 << 16))
                machine.step()
                if machine.reg(NUMBER[args[0]]) != marker:
                    failures.append(
                        f"0x{encoding:04x} {mnemonic} {operands}: loaded "
                        f"0x{machine.reg(NUMBER[args[0]]):08x} from "
                        f"0x{target:08x}, want 0x{marker:08x}"
                    )
            else:
                machine.set_regs(regs, pc=BASE)
                machine.write_word(target, 0)
                machine.write_word(BASE, encoding | (0x0001 << 16))
                machine.step()
                if machine.read_word(target) != regs[NUMBER[args[0]]]:
                    failures.append(
                        f"0x{encoding:04x} {mnemonic} {operands}: stored "
                        f"0x{machine.read_word(target):08x} at 0x{target:08x}, "
                        f"want 0x{regs[NUMBER[args[0]]]:08x}"
                    )

        elif mnemonic in ("c.j", "c.jal", "c.beqz", "c.bnez"):
            try:
                printed = int(args[-1], 0)
            except ValueError:
                continue
            if mnemonic in ("c.beqz", "c.bnez") and args[0] in NUMBER:
                regs[NUMBER[args[0]]] = 0 if mnemonic == "c.beqz" else 1
            after = _run(machine, regs, encoding)
            if after is None:
                continue
            checked += 1
            # `printed` is an absolute address inside the swept blob and `at`
            # is where this encoding sat in it, so the displacement is their
            # difference. See this module's header.
            want = (BASE + printed - at) & 0xFFFFFFFF
            if after[32] != want:
                failures.append(
                    f"0x{encoding:04x} {mnemonic} {operands}: pc "
                    f"0x{after[32]:08x}, want 0x{want:08x}"
                )
            # **And the registers it must not touch.** Found by mutation:
            # expanding `c.j` to `jal x1` instead of `jal x0` puts a return
            # address in `ra` and still lands on exactly the right PC, so a
            # test watching only the PC passes. That is not a small wrong
            # answer -- it silently clobbers the caller's return address.
            expected = dict(enumerate(regs))
            if mnemonic == "c.jal":
                expected[1] = BASE + 2
            for index, value in expected.items():
                if after[index] != value:
                    failures.append(
                        f"0x{encoding:04x} {mnemonic} {operands}: x{index} is "
                        f"0x{after[index]:08x}, want 0x{value:08x}"
                    )
                    break

    assert failures == [], failures[:10]
    assert checked > 20_000, f"only {checked} encodings reached; the sweep is not running"


def test_a_compressed_shift_of_thirty_two_or_more_is_refused(machine):
    """Pinned here because the enforcement moved.

    `expand_quadrant1` used to refuse bit 12 explicitly and no longer does:
    mutation showed no input could tell the difference, because a shift amount
    of 32 or more puts a one into `funct7`, and the 32-bit shift already
    refuses any nonzero funct7 as RV64's six-bit field. Deleting the second
    copy is right; deleting the guarantee would not be, so the *behaviour* is
    asserted where the code used to be.

    `0x9001` is `c.srli s0,0x20`, `0x9401` is `c.srai s0,0x20` and `0x1002` is
    `c.slli zero,0x20` -- read off the objdump sweep rather than hand-derived.
    """
    for encoding, name in ((0x9001, "c.srli"), (0x9401, "c.srai"), (0x1002, "c.slli")):
        assert verdict(machine, encoding) == "illegal", (
            f"0x{encoding:04x} ({name} with shamt 32) executed on a 32-bit part"
        )


def test_a_compressed_shift_below_thirty_two_still_works(machine):
    """The other half, so the test above cannot be satisfied by refusing every
    shift. `0x9081` is `c.srli s0,0x20`'s legal neighbour at shamt 0... which
    is a hint, so this uses a real amount instead."""
    machine.set_regs(known_registers(), pc=BASE)
    # c.srli s0, 4  -- quadrant 1, funct3=100, funct2=00, rd'=s0, shamt=4.
    encoding = 0x8011 | (4 << 2)
    machine.write_word(BASE, encoding | (0x0001 << 16))
    machine.step()
    assert machine.reg(8) == (known_registers()[8] >> 4)


def test_the_link_register_holds_the_address_after_a_compressed_call(machine):
    """`c.jal` links to pc + 2 and `jal` links to pc + 4, and after expansion
    the two are the same encoding.

    So the width has to travel beside the instruction rather than be recovered
    from it, and this is what says so. A model that linked to pc + 4 would
    return two bytes past the call and execute the second half of whatever
    followed -- which does not fault, it runs a different program.
    """
    machine.set_regs(known_registers(), pc=BASE)
    machine.write_word(BASE, 0x2001 | (0x0001 << 16))   # c.jal +0x... , then c.nop
    machine.step()
    assert machine.reg(1) == BASE + 2, "ra is the address after a two-byte call"


# --- and one real compiled image ------------------------------------------
#
# The sweeps above are exhaustive and still prove only that each encoding means
# what objdump says in isolation. What they cannot show is that a *program*
# runs: that the widths interleave correctly instruction after instruction,
# that a compressed branch lands on a 32-bit instruction and vice versa, and
# that the loop terminates. `docs/HANDOFF_2026-08-25_a-fourth-core-and-a-usable
# -page.md` 3.4 is the case for asserting the period rather than only the
# count -- an inverted AVR branch ran sixty thousand instructions, toggled a
# pin, alternated correctly, and was wrong.

#: Shared with `tests/riscv32/test_esp32c3_board.py`, which **owns** it: the
#: rebuild-and-compare lives there, so there is one copy of the compiler
#: invocation. There were two until the linker script landed and only one of
#: them learned about it.
BLINK = pathlib.Path(__file__).resolve().parent / "c3blink" / "blink.bin"

#: Where the image is linked, from `-Wl,-Ttext=0x42000000`. That is the
#: ESP32-C3's external-flash execute window, which is where a real image runs.
BLINK_LOAD = 0x42000000

#: GPIO, from the ESP32-C3 TRM chapter 5. Mapped here as plain memory: this
#: core has no MMIO yet, which is OH-47, and a blink only needs the register to
#: hold what was written to it.
GPIO = 0x60004000
GPIO_OUT = GPIO + 0x04
GPIO_ENABLE = GPIO + 0x20
GPIO8 = 1 << 8


def test_a_real_compiled_image_runs_and_the_gpio_register_alternates():
    """The claim OH-54 exists to make true.

    Eleven of this image's sixteen instructions are compressed, so before this
    slice the core refused the second instruction it fetched. There is no LED
    on a XIAO ESP32-C3, so what is watched is the register the firmware drives
    rather than a pin -- a smaller claim than the RP2040's and a true one.
    """
    if not BLINK.is_file():
        pytest.skip(f"{BLINK} is missing")
    image = BLINK.read_bytes()

    with abi.Cpu() as cpu:
        cpu.set_extensions(abi.ESP32_C3)
        cpu.add_region(BLINK_LOAD, 0x1000, executable=True)
        cpu.add_region(0x3FC80000, 0x60000, executable=False)  # SRAM; _start puts sp near its top
        cpu.add_region(GPIO, 0x100, executable=False)
        for offset in range(0, len(image), 4):
            word = int.from_bytes(image[offset:offset + 4].ljust(4, b"\0"), "little")
            cpu.write_word(BLINK_LOAD + offset, word)

        # **No stack pointer is set here, and that changed.** The image sets
        # its own in `_start`, which is what every RISC-V image does -- `crt0`
        # is where it normally lives, and a `-nostartfiles` build has to do it
        # itself. Setting one here as well would hide a fixture that had
        # stopped doing so.
        cpu.set_regs([0] * 32, pc=BLINK_LOAD)

        transitions: list[tuple[int, bool]] = []
        last = 0
        for step in range(20_000):
            cpu.step()
            now = cpu.read_word(GPIO_OUT) & GPIO8
            if now != last:
                transitions.append((step, bool(now)))
                last = now

        assert cpu.read_word(GPIO_ENABLE) & GPIO8, "GPIO8 was driven as an output"

    assert len(transitions) >= 2, f"the register changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]

    # **The period, and not only the count.** A delay loop counting to 100
    # cannot cost ten instructions, and a branch with the wrong polarity still
    # alternates -- it just alternates at the wrong rate. This is the assertion
    # that caught exactly that defect in `core/avr`.
    steps = [step for step, _ in transitions]
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"
    assert periods.pop() > 100, "a loop counting to 100 costs more than 100 steps"


def test_most_of_the_committed_image_is_compressed():
    """The measurement the whole slice rests on, kept as a test rather than a
    sentence in a ticket.

    If a future toolchain change made this image all-32-bit, the blink test
    above would still pass while proving nothing about RVC.
    """
    if not BLINK.is_file():
        pytest.skip(f"{BLINK} is missing")
    image = BLINK.read_bytes()
    compressed = full = offset = 0
    while offset < len(image):
        half = int.from_bytes(image[offset:offset + 2], "little")
        if (half & 3) == 3:
            full += 1
            offset += 4
        else:
            compressed += 1
            offset += 2
    assert compressed > full, (
        f"{compressed} compressed and {full} full-width; this fixture is "
        f"supposed to be mostly compressed"
    )


def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def _run(cpu, regs: list[int], encoding: int) -> list[int] | None:
    """Execute one encoding from `regs`, returning the 32 registers and the PC."""
    cpu.set_regs(regs, pc=BASE)
    cpu.write_word(BASE, encoding | (0x0001 << 16))
    try:
        cpu.step()
    except abi.AbiError:
        return None
    return [cpu.reg(i) for i in range(32)] + [cpu.pc]
