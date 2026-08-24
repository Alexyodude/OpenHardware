# OpenHardware — run the same image through this core and rvcpp, and compare.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Differential execution against Hazard3's rvcpp.

## What it compares, and why that is the whole register file

rvcpp prints one line per instruction: the PC, the encoding, and the register
it wrote. A writeback is the only way a GPR changes, so replaying those lines
from a zeroed file reconstructs rvcpp's **complete** register state after every
instruction -- not a sample of it. This compares all 32 against ours, plus the
PC of the instruction about to run, which is what makes it a check on control
flow rather than only on arithmetic.

Comparing the traced PC is the load-bearing half. Two models can agree on every
register and still be running different programs if one took a branch the other
did not; the next disagreement then appears somewhere unrelated, and the reader
goes looking for a bug in whatever instruction happened to be there.

## What it cannot check, and this is not a limitation of the rig

**rvcpp has no extension gating at all.** It executes M, A, C, Zba, Zbb, Zbc,
Zbs, Zbkb and Zcmp unconditionally, so an atomic runs on it whether the part
being modelled has the A extension or not. The ESP32-C3 is RV32IMC and must
trap `lr.w`; the C6 is RV32IMAC and must execute it. **No run of this file will
ever detect getting that wrong.** It is measured, not inferred --
docs/architectures.md 2.1b, and OH-35 exists to close it with a corpus whose
verdicts come from the ISA manual instead.

So a green lockstep run says "this core agrees with another implementation
about legal code". It does not say the core refuses what the silicon refuses.

## The board here is rvcpp's testbench, not a chip

`main.cpp` puts RAM at 0x80000000 and its exit/print registers at 0xc0000000.
Those are constants of that testbench, so they live in this file -- the core
knows no addresses, and a test that wants memory says so. An ESP32-C3's real
map is a different thing entirely and belongs to a board module.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess

from core.riscv32 import abi

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Where `tests/riscv32/oracle/build_rvcpp.py` puts the built oracle.
ORACLE = REPO / "third_party" / "rvcpp-build"

#: rvcpp's testbench map. From `main.cpp`, not from any datasheet.
RAM_BASE = 0x80000000
ENTRY_OFFSET = 0x40
IO_BASE = 0xC0000000
IO_SIZE = 0x1000

#: 64 KiB, passed to rvcpp as `--memsize 64` so both models have the same RAM.
#: rvcpp defaults to 16 MiB; allocating that on our side per test would cost
#: more than every other thing these tests do put together.
RAM_SIZE = 64 * 1024

#: ABI register names as rvcpp prints them, in architectural order.
REG_NAMES = (
    "x0", "ra", "sp", "gp", "tp", "t0", "t1", "t2", "s0", "s1", "a0", "a1",
    "a2", "a3", "a4", "a5", "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)
REG_NUMBER = {name: index for index, name in enumerate(REG_NAMES)}

#: `80000040: 00500093 : ra    <- 00000005 :` and the 16-bit form, which pads
#: the encoding to eight columns with four leading spaces.
_STEP = re.compile(
    r"^([0-9a-f]{8}): (?:([0-9a-f]{8})|    ([0-9a-f]{4})) : (.*)$"
)

#: The tail of a step line when it wrote a register.
_WRITEBACK = re.compile(r"^([a-z0-9]+) +<- ([0-9a-f]{8}) :$")


class OracleError(Exception):
    """rvcpp is absent, failed to run, or printed something unparseable."""


@dataclasses.dataclass(frozen=True)
class OracleStep:
    """One traced instruction: where it was, what it was, what it wrote."""

    pc: int
    encoding: int
    width: int
    writeback: tuple[int, int] | None


@dataclasses.dataclass(frozen=True)
class Divergence:
    """The first place the two models stopped agreeing."""

    index: int
    pc: int
    encoding: int
    field: str
    ours: int
    oracle: int

    def __str__(self) -> str:
        return (
            f"step {self.index} at pc=0x{self.pc:08x} (encoding "
            f"0x{self.encoding:08x}): {self.field} is 0x{self.ours:08x} here "
            f"and 0x{self.oracle:08x} in rvcpp"
        )


@dataclasses.dataclass(frozen=True)
class Report:
    """How far the two models agreed, and what ended the run."""

    agreed: int
    traced: int
    divergence: Divergence | None
    stopped: str | None

    @property
    def matched_the_oracle(self) -> bool:
        """Every instruction rvcpp traced, executed here to the same effect."""
        return self.divergence is None and self.agreed == self.traced


def executable() -> pathlib.Path | None:
    """The built oracle, or None. Absence is a skip, never a pass."""
    for name in ("rvcpp.exe", "rvcpp"):
        candidate = ORACLE / name
        if candidate.is_file():
            return candidate
    return None


def trace(image: bytes, cycles: int, tmp_dir: pathlib.Path) -> list[OracleStep]:
    """Run rvcpp over `image` and parse its per-instruction trace."""
    binary = executable()
    if binary is None:
        raise OracleError(
            f"no rvcpp under {ORACLE}. Build it:\n"
            f"  git clone https://github.com/Wren6991/Hazard3 third_party/hazard3\n"
            f"  python tests/riscv32/oracle/build_rvcpp.py"
        )
    path = tmp_dir / "image.bin"
    path.write_bytes(image)
    result = subprocess.run(
        [str(binary), "--bin", str(path), "--cycles", str(cycles),
         "--memsize", str(RAM_SIZE // 1024), "--trace"],
        capture_output=True, text=True,
    )
    # rvcpp exits non-zero when the program asks it to, via IO_EXIT, so the
    # return code says nothing about whether the run was usable. An empty
    # trace does, and it is the failure that would otherwise pass silently:
    # zero instructions compared is zero disagreements found.
    steps = parse(result.stdout)
    if not steps:
        raise OracleError(
            f"rvcpp traced no instructions (exit {result.returncode}). "
            f"stdout: {result.stdout[:400]!r} stderr: {result.stderr[:400]!r}"
        )
    return steps


def parse(output: str) -> list[OracleStep]:
    """Trace lines to steps, ignoring everything that is not one.

    rvcpp interleaves `IO_PRINT_U32:` lines, trap markers and continuation
    lines that start with spaces. Only a line beginning with an eight-digit PC
    is an instruction, which is what anchoring the pattern buys.
    """
    steps: list[OracleStep] = []
    for line in output.splitlines():
        match = _STEP.match(line)
        if match is None:
            continue
        wide, narrow = match.group(2), match.group(3)
        encoding = int(wide, 16) if wide else int(narrow, 16)
        writeback = None
        tail = _WRITEBACK.match(match.group(4).rstrip())
        if tail is not None:
            name = tail.group(1)
            if name not in REG_NUMBER:
                # `pc <- ...` uses the same shape and is not a GPR write. Any
                # other name would be a trace format this parser has not been
                # taught, and guessing would corrupt the reconstructed file.
                if name != "pc":
                    raise OracleError(f"unknown register in trace line: {line!r}")
            else:
                writeback = (REG_NUMBER[name], int(tail.group(2), 16))
        steps.append(OracleStep(
            pc=int(match.group(1), 16),
            encoding=encoding,
            width=4 if wide else 2,
            writeback=writeback,
        ))
    return steps


def install(cpu: abi.Cpu, image: bytes, extensions: int) -> None:
    """Give the core rvcpp's testbench board and load the image into it."""
    cpu.clear_regions()
    cpu.add_region(RAM_BASE, RAM_SIZE)
    # The testbench IO window, as plain writable words. rvcpp gives print and
    # exit their own behaviour there; here they only have to not fault, since
    # a store changes no register and the comparison is over registers. A
    # region that faulted would end every run at the first printf.
    cpu.add_region(IO_BASE, IO_SIZE, executable=False)
    cpu.set_extensions(extensions)
    cpu.write_block(RAM_BASE, image)
    cpu.set_regs([0] * 32, pc=RAM_BASE + ENTRY_OFFSET)


def run(image: bytes, tmp_dir: pathlib.Path, extensions: int = abi.ESP32_C3,
        cycles: int = 2000) -> Report:
    """Execute `image` in both models and compare after every instruction.

    Stops at the first disagreement rather than counting them: after one
    divergence the two models are running different programs, and every
    difference after it is a consequence rather than a finding.
    """
    steps = trace(image, cycles, tmp_dir)

    with abi.Cpu() as cpu:
        install(cpu, image, extensions)
        oracle_regs = [0] * 32
        agreed = 0

        for index, step in enumerate(steps):
            if cpu.pc != step.pc:
                return Report(agreed, len(steps), Divergence(
                    index, step.pc, step.encoding, "pc", cpu.pc, step.pc), None)
            try:
                cpu.step()
            except abi.AbiError as exc:
                return Report(agreed, len(steps), None, str(exc))

            if step.writeback is not None:
                number, value = step.writeback
                oracle_regs[number] = value

            ours = cpu.get_regs().as_list()
            for number in range(32):
                if ours[number] != oracle_regs[number]:
                    return Report(agreed, len(steps), Divergence(
                        index, step.pc, step.encoding, REG_NAMES[number],
                        ours[number], oracle_regs[number]), None)
            agreed += 1

    return Report(agreed, len(steps), None, None)
