#!/usr/bin/env python3
# OpenHardware - turn a debug probe's single-step log into a conformance fixture.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Silicon as the oracle: capture, convert, replay (OH-159).

Two cores here have no software oracle that does not descend from the thing
being checked -- Xtensa (OH-38) and Armv7E-M execution (OH-64). A real chip
halted and single-stepped under a debug probe is one. This file is the
harness that turns such a session into fixtures, once, for every part.

## The three verbs

    python tools/capture_trace.py script --steps 200 > capture.gdb
    python tools/capture_trace.py convert trace.log --board "..." \\
        --captured-on 2026-11-05 -o tests/fixtures/hardware/<name>.json
    python tools/capture_trace.py check tests/fixtures/hardware/<name>.json

`script` writes the GDB command file that produces the log, so the log's
shape is this file's to define rather than whatever a person typed. `convert`
reads that log. `check` replays each case through this repository's own core
and names every disagreement.

## The capture mechanism, per part (the ticket's step 1)

* **ESP32-C3** (implemented). The chip carries its own USB-Serial-JTAG, so
  no probe is bought: Espressif's OpenOCD fork with
  `board/esp32c3-builtin.cfg`, and `riscv32-esp-elf-gdb` stepping with
  `stepi`. RISC-V's debug module halts after one instruction and exposes
  the whole architectural register file, which is exactly a trace.
* **ESP32-S3** (not implemented, and not yet known to be sufficient). The
  same built-in USB-JTAG, `board/esp32s3-builtin.cfg` and
  `xtensa-esp32s3-elf-gdb`. What must be established on a board before
  treating one as an oracle: that OpenOCD's Xtensa `stepi` retires exactly
  one instruction, and that GDB's register dump is the physical AR file
  plus WINDOWBASE/WINDOWSTART rather than only the sixteen visible a0-a15.
  A windowed core checked against the visible window alone would pass
  every call/return bug.
* **nRF52840** (not implemented). SWD through any CMSIS-DAP probe,
  `interface/cmsis-dap.cfg` with `target/nrf52.cfg`, and
  `arm-none-eabi-gdb`. CoreSight's halting debug single-steps directly;
  r0-r12, sp, lr, pc and xPSR are what a trace records.

Only the C3 is implemented because the ticket's step 3 is the point: a
harness proven against a core already known good, before its first use on
one that is not. The S3 and nRF52840 converters get written with a board on
the bench, not before, so they are written against the log a real probe
prints rather than against a guess at it.

## The fixture is the rv32 corpus's case, with `silicon` as the oracle key

`rules/conformance-fixtures.md` governs, and the ticket forbids a second
format. `tests/rv32/corpus/*.json` already stores a case as `encoding`,
`width`, `initial` and one cell per oracle (`rvcpp`, holding `status` and
`writes`); the AVR corpus does the same with `avr8js`. A captured case is
that shape with the cell named `silicon`, and three differences, each forced:

* `initial` is the **complete** register file, never a delta. The capture
  has all of it, and storing it whole is what lets `check` compare every
  register after the step -- the delta hazard `tests/rv32/test_conformance.py`
  describes cannot arise when nothing is left out.
* `pc` is the case's own field and the silicon cell records the PC after.
  The corpus always runs at one sandbox address; a capture runs where the
  firmware is, and a taken branch is only checkable against the address it
  was taken from.
* there is no `requires`. That field says which parts must execute an
  encoding; a capture says that ONE part did, and the file names the part.

A case is a pair of consecutive halts: the state before a `stepi`, and the
state after it.

## What `check` cannot replay, and says so

The log records registers, not memory. A load or store faults on the
replay's memory, which holds only the instruction itself, and is counted as
skipped -- never as a pass. A SYSTEM-opcode instruction reads CSRs such as
`mcycle` whose value on the chip a register dump cannot reproduce, so it is
skipped by name. A file in which nothing was compared fails, for the reason
`rules/conformance-fixtures.md` section 4 gives.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Markers `script` emits and `convert` requires. A log without the end
#: marker was cut short, and a truncated log is refused rather than read as
#: a shorter trace.
STEP = "==oh-step=="
END = "==oh-end=="

#: Where OpenOCD's GDB server listens by default.
GDB_PORT = 3333

#: x1..x31 by the names GDB's RISC-V target prints. x8 appears as `fp` in
#: GDB's dump and as `s0` in the ABI table, so both spellings are accepted.
#: x0 is hard-wired and not required; GDB omits it from `info registers`.
ABI_NAMES = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)
INDEX = {name: number for number, name in enumerate(ABI_NAMES)}
INDEX["fp"] = 8

#: The SYSTEM major opcode: CSR access, ecall, ebreak, mret, wfi.
SYSTEM = 0x73

_REG_LINE = re.compile(r"^(\w+)\s+(0x[0-9a-fA-F]+)\b")
_HALVES = re.compile(
    r"^(0x[0-9a-fA-F]+)(?:\s+<[^>]*>)?:\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)")


class TraceError(ValueError):
    """The log is not a complete capture. Raised, never skipped past."""


@dataclasses.dataclass(frozen=True)
class Part:
    name: str
    isa: str
    openocd: str
    gdb: str


def _parts() -> dict[str, Part]:
    # The ISA string is the board module's, so a capture is replayed against
    # exactly the part the emulator claims to be, and the two cannot drift.
    from webui.boards import esp32c3
    return {
        "esp32c3": Part("ESP32-C3", esp32c3.ISA, "board/esp32c3-builtin.cfg",
                        "riscv32-esp-elf-gdb"),
    }


@dataclasses.dataclass(frozen=True)
class Halt:
    """One halted state: x0..x31, the PC, and the two halfwords at the PC."""

    regs: tuple[int, ...]
    pc: int
    halves: tuple[int, int]

    @property
    def width(self) -> int:
        return 32 if (self.halves[0] & 0x3) == 0x3 else 16

    @property
    def encoding(self) -> int:
        low, high = self.halves
        return low | (high << 16) if self.width == 32 else low


@dataclasses.dataclass
class Report:
    compared: int = 0
    skipped: list[str] = dataclasses.field(default_factory=list)
    wrong: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.compared > 0 and not self.wrong


def gdb_script(steps: int, port: int = GDB_PORT) -> str:
    """The GDB command file whose output `parse_log` reads.

    It attaches to a halted target where it already is and resets nothing:
    the trace is whatever the chip was running, which is real silicon
    whatever program it is. `set_maskisr steponly` is OpenOCD's RISC-V
    command for stepping with interrupts masked; without it a step can land
    in a vector, and `check` would report that step's PC as a disagreement.
    """
    if steps < 1:
        raise ValueError(f"steps must be at least 1, got {steps}")
    dump = f"echo {STEP}\\n\ninfo registers\nx/2xh $pc\n"
    return (
        "set pagination off\n"
        "set confirm off\n"
        "set height 0\n"
        f"target extended-remote localhost:{port}\n"
        "monitor halt\n"
        "monitor riscv set_maskisr steponly\n"
        "set $oh_i = 0\n"
        f"while $oh_i < {steps}\n"
        + "".join("  " + line + "\n" for line in dump.splitlines())
        + "  stepi\n"
        "  set $oh_i = $oh_i + 1\n"
        "end\n"
        + dump
        + f"echo {END}\\n\n"
        "detach\n"
    )


def _parse_halt(block: str, ordinal: int) -> Halt:
    regs: dict[int, int] = {}
    pc = None
    halves = None
    for raw in block.splitlines():
        line = raw.strip()
        match = _HALVES.match(line)
        if match:
            if halves is not None:
                raise TraceError(f"halt {ordinal}: two memory dumps")
            address = int(match.group(1), 16)
            halves = (address, int(match.group(2), 16), int(match.group(3), 16))
            continue
        match = _REG_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), int(match.group(2), 16)
        if name == "pc":
            if pc is not None:
                raise TraceError(f"halt {ordinal}: pc printed twice")
            pc = value
        elif name in INDEX:
            number = INDEX[name]
            if number in regs:
                raise TraceError(
                    f"halt {ordinal}: x{number} printed twice ({name})")
            regs[number] = value
    missing = [ABI_NAMES[n] for n in range(1, 32) if n not in regs]
    if missing:
        raise TraceError(
            f"halt {ordinal}: no value for {', '.join(missing)}. A register "
            f"left out would be compared against nothing.")
    if pc is None:
        raise TraceError(f"halt {ordinal}: no pc")
    if halves is None:
        raise TraceError(f"halt {ordinal}: no instruction bytes (x/2xh $pc)")
    if halves[0] != pc:
        raise TraceError(
            f"halt {ordinal}: instruction bytes read at {halves[0]:#010x} but "
            f"the pc is {pc:#010x}")
    if regs.get(0, 0) != 0:
        raise TraceError(f"halt {ordinal}: x0 is {regs[0]:#x}, not zero")
    return Halt(tuple(regs.get(n, 0) for n in range(32)), pc,
                (halves[1], halves[2]))


def parse_log(text: str) -> list[Halt]:
    """Every halt in a log written by `gdb_script`'s commands."""
    if END not in text:
        raise TraceError(
            f"no {END} marker: the capture ended early, or the log was not "
            f"written by `capture_trace.py script`")
    body = text.split(END, 1)[0]
    blocks = body.split(STEP)[1:]
    if len(blocks) < 2:
        raise TraceError(
            f"{len(blocks)} halt(s) in the log; a case needs one before and "
            f"one after a step")
    return [_parse_halt(block, ordinal) for ordinal, block in enumerate(blocks)]


def cases_from_halts(halts: list[Halt]) -> list[dict]:
    """One corpus case per `stepi`, oracle cell `silicon`."""
    from core.riscv32 import disasm
    cases = []
    for before, after in itertools.pairwise(halts):
        text, _ = disasm.decode(before.encoding, before.pc)
        digits = 8 if before.width == 32 else 4
        cases.append({
            "mnemonic": text.replace("\t", " "),
            "encoding": f"0x{before.encoding:0{digits}x}",
            "width": before.width,
            "pc": f"0x{before.pc:08x}",
            "initial": {str(n): f"0x{before.regs[n]:08x}" for n in range(1, 32)},
            "silicon": {
                "status": "executed",
                "writes": {str(n): after.regs[n] for n in range(1, 32)
                           if after.regs[n] != before.regs[n]},
                "pc": after.pc,
            },
        })
    return cases


def fixture(log: str, part: str, board: str, captured_on: str) -> dict:
    """The whole file: provenance first, then the cases."""
    known = _parts()
    if part not in known:
        raise ValueError(f"no converter for {part!r}; known: {sorted(known)}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured_on):
        raise ValueError(f"--captured-on wants YYYY-MM-DD, got {captured_on!r}")
    spec = known[part]
    return {
        "part": spec.name,
        "isa": spec.isa,
        "oracle": "silicon",
        "provenance": {
            "board": board,
            "captured_on": captured_on,
            "mechanism": f"openocd -f {spec.openocd}; {spec.gdb} stepi",
            "log_sha256": hashlib.sha256(log.encode("utf-8")).hexdigest(),
        },
        "cases": cases_from_halts(parse_log(log)),
    }


def replay(data: dict) -> Report:
    """Run every case through `core/riscv32` and compare the whole state."""
    from core.riscv32 import abi
    report = Report()
    cases = data.get("cases") or []
    if not cases:
        raise TraceError("the fixture holds no cases")
    with abi.Cpu() as cpu:
        for number, case in enumerate(cases):
            label = (f"case {number} {case['mnemonic']} ({case['encoding']}) "
                     f"at {case['pc']}")
            word = int(case["encoding"], 16)
            width = case["width"]
            if width == 32 and (word & 0x7F) == SYSTEM:
                report.skipped.append(
                    f"{label}: SYSTEM opcode, reads state a register dump "
                    f"does not hold")
                continue
            pc = int(case["pc"], 16)
            size = width // 8
            initial = [0] * 32
            for index, value in case["initial"].items():
                initial[int(index)] = int(value, 16)
            cpu.clear_regions()
            cpu.clear_memory()
            cpu.set_isa(data["isa"])
            cpu.add_region(pc, size)
            cpu.write_block(pc, word.to_bytes(size, "little"))
            cpu.set_regs(initial, pc=pc)
            try:
                cpu.step()
            except (abi.MemoryFault, abi.Refused) as error:
                report.skipped.append(
                    f"{label}: touches memory the capture did not record "
                    f"({error})")
                continue
            except abi.AbiError as error:
                report.wrong.append(
                    f"{label}: the silicon executed it; this core raised "
                    f"{type(error).__name__}: {error}")
                continue
            report.compared += 1
            final = cpu.get_regs()
            silicon = case["silicon"]
            for index in range(1, 32):
                want = silicon["writes"].get(str(index), initial[index])
                if final.x[index] != want:
                    report.wrong.append(
                        f"{label}: x{index} ({ABI_NAMES[index]}) is "
                        f"{final.x[index]:#010x}, the silicon made it "
                        f"{want:#010x}")
            if final.pc != silicon["pc"]:
                report.wrong.append(
                    f"{label}: pc is {final.pc:#010x}, the silicon went to "
                    f"{silicon['pc']:#010x}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True)

    script = sub.add_parser("script", help="print the GDB command file")
    script.add_argument("--steps", type=int, default=200)
    script.add_argument("--port", type=int, default=GDB_PORT)

    convert = sub.add_parser("convert", help="log to fixture")
    convert.add_argument("log", type=pathlib.Path)
    convert.add_argument("--part", default="esp32c3")
    convert.add_argument("--board", required=True,
                         help="which board, as a person would find it again")
    convert.add_argument("--captured-on", required=True, help="YYYY-MM-DD")
    convert.add_argument("-o", "--out", type=pathlib.Path, required=True)

    check = sub.add_parser("check", help="replay a fixture against the core")
    check.add_argument("fixture", type=pathlib.Path)

    args = parser.parse_args(argv)
    if args.verb == "script":
        sys.stdout.write(gdb_script(args.steps, args.port))
        return 0
    if args.verb == "convert":
        data = fixture(args.log.read_text(encoding="utf-8"), args.part,
                       args.board, args.captured_on)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"{args.out}: {len(data['cases'])} cases")
        return 0
    report = replay(json.loads(args.fixture.read_text(encoding="utf-8")))
    for line in report.wrong:
        print(f"WRONG    {line}")
    for line in report.skipped:
        print(f"SKIPPED  {line}")
    print(f"{report.compared} compared, {len(report.wrong)} wrong, "
          f"{len(report.skipped)} skipped")
    if report.compared == 0:
        print("nothing was compared, which is a failure, not a pass")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
