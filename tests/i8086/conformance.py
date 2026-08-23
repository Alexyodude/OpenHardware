# OpenHardware - run SST8088 cases against the core and report what diverged.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""The conformance harness, per ticket OH-6.

`tools/sst8088.py` reads the corpus. This runs it: load a case's state into a
processor, execute one instruction, and compare all fourteen registers and
every byte the case mentions against what the silicon actually produced.

## Why it takes a `step` rather than calling one

Execution is OH-3 and does not exist yet. Rather than wait for it, the harness
is parameterised over "something that advances the processor by one
instruction". That has three consequences worth having:

* it can be built and tested now, against stand-ins that are deliberately
  right and deliberately wrong, so the harness's own logic is verified before
  it is ever pointed at a real core;
* when OH-3 lands, wiring it up is one argument;
* a future second implementation -- an interpreter, a recompiler, MartyPC over
  a pipe as the differential oracle decision 2.2 records -- runs through the
  same harness with no changes here.

## Memory is compared where the case speaks

Only addresses appearing in the case are checked. The corpus specifies a
handful of bytes per case and says nothing about the other million; comparing
all of them would fail on memory the hardware never described.

## Undefined flags

Several instructions leave flags documented-undefined, and the hardware still
produces *something* for them. Comparing those bits reports failures that are
not defects. `flag_mask` narrows the comparison, and `i8086.flag.undefined` in
`docs/features/i8086.md` is the cell that will eventually pin which bits are
excluded for which opcode -- read from this corpus, since hardware is the only
place that answer exists.

The default masks nothing. A harness that quietly ignored bits by default
would be the vacuous green this repository exists to prevent.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import Callable, Iterable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.i8086 import abi  # noqa: E402
from tools import sst8088  # noqa: E402

#: Every bit the 8086 defines. Bits 1, 3, 5 and 12-15 are unassigned and are
#: not compared -- `sst8088.FLAG_BITS` is the authority on which nine exist.
DEFINED_FLAGS = sum(1 << bit for bit in sst8088.FLAG_BITS.values())

#: A callable that advances one instruction. Returns nothing; the processor is
#: mutated in place.
Step = Callable[[abi.Cpu], None]


class HarnessError(Exception):
    """The harness could not run, which is never the same as a failing case."""


@dataclasses.dataclass(frozen=True)
class Divergence:
    """One place the core and the silicon disagree."""

    kind: str  # "register" or "memory"
    where: str
    expected: int
    actual: int

    def __str__(self) -> str:
        width = 4 if self.kind == "register" else 2
        return (
            f"{self.kind} {self.where}: "
            f"expected {self.expected:0{width}X}, got {self.actual:0{width}X}"
        )


@dataclasses.dataclass(frozen=True)
class Result:
    case: sst8088.Case
    divergences: tuple[Divergence, ...]

    @property
    def ok(self) -> bool:
        return not self.divergences

    def describe(self) -> str:
        if self.ok:
            return f"{self.case.name} [{self.case.index}]: ok"
        detail = "; ".join(str(d) for d in self.divergences[:6])
        more = "" if len(self.divergences) <= 6 else f" (+{len(self.divergences) - 6} more)"
        code = " ".join(f"{b:02X}" for b in self.case.code)
        return f"{self.case.name} [{self.case.index}] ({code}): {detail}{more}"


def load_case(cpu: abi.Cpu, case: sst8088.Case) -> None:
    """Put a case's initial state into the processor.

    Memory first, then registers. The order matters if a future core prefetches
    on a register write: the bytes must already be there for it to fetch.
    """
    cpu.clear_memory()
    for address, value in case.initial_ram.items():
        cpu.write_byte(address, value)
    cpu.set_regs(**case.initial_regs)


def compare(cpu: abi.Cpu, case: sst8088.Case, flag_mask: int = 0xFFFF) -> tuple[Divergence, ...]:
    """Every disagreement between the processor and the case's expected state."""
    out: list[Divergence] = []

    actual = cpu.regs.as_dict()
    for name in sst8088.REGISTERS:
        expected = case.expected_regs[name]
        got = actual[name]
        if name == "flags":
            # Compare only bits the part defines, and only those the caller
            # has not masked out as undefined for this opcode.
            mask = DEFINED_FLAGS & flag_mask
            expected &= mask
            got &= mask
        if expected != got:
            out.append(Divergence("register", name, expected, got))

    for address in sorted(case.expected_ram):
        expected = case.expected_ram[address]
        got = cpu.read_byte(address)
        if expected != got:
            out.append(Divergence("memory", f"{address:05X}", expected, got))

    return tuple(out)


def run_case(
    cpu: abi.Cpu,
    case: sst8088.Case,
    step: Step,
    flag_mask: int = 0xFFFF,
) -> Result:
    """Load, step once, compare."""
    load_case(cpu, case)
    step(cpu)
    return Result(case, compare(cpu, case, flag_mask))


@dataclasses.dataclass
class Report:
    """What a run of many cases produced."""

    name: str
    passed: int = 0
    failed: int = 0
    failures: list[Result] = dataclasses.field(default_factory=list)
    #: Failures are kept for inspection, but not all of them -- a wholly
    #: unimplemented opcode produces ten thousand identical ones and the first
    #: few say everything the last few would.
    keep_failures: int = 5

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def add(self, result: Result) -> None:
        if result.ok:
            self.passed += 1
        else:
            self.failed += 1
            if len(self.failures) < self.keep_failures:
                self.failures.append(result)

    def __str__(self) -> str:
        return f"{self.name}: {self.passed}/{self.total} ({self.rate:.1%})"


def run_cases(
    cases: Iterable[sst8088.Case],
    step: Step,
    name: str = "cases",
    flag_mask: int = 0xFFFF,
    limit: int | None = None,
) -> Report:
    """Run an iterable of cases through one processor.

    One processor for all of them, reset by `load_case` between each. Building
    a fresh one per case allocates a megabyte each time, and the corpus has
    hundreds of thousands.
    """
    report = Report(name)
    with abi.Cpu() as cpu:
        for index, case in enumerate(cases):
            if limit is not None and index >= limit:
                break
            report.add(run_case(cpu, case, step, flag_mask))
    if report.total == 0:
        raise HarnessError(
            f"{name}: ran zero cases. A report of no failures over no tests is "
            f"indistinguishable from a passing run, so this is an error."
        )
    return report


def run_file(
    path: pathlib.Path,
    step: Step,
    flag_mask: int = 0xFFFF,
    limit: int | None = None,
) -> Report:
    return run_cases(sst8088.load(path), step, path.stem, flag_mask, limit)


def run_corpus(
    directory: pathlib.Path,
    step: Step,
    limit_per_file: int | None = None,
) -> list[Report]:
    """Every opcode file in a directory, one report each."""
    return [
        run_file(path, step, limit=limit_per_file)
        for path in sst8088.opcode_files(directory)
    ]


def summarise(reports: list[Report]) -> str:
    """A pass rate per opcode, worst first -- that is where the work is."""
    if not reports:
        return "no reports"
    total = sum(r.total for r in reports)
    passed = sum(r.passed for r in reports)
    lines = [f"{passed}/{total} ({passed / total:.2%}) across {len(reports)} opcode file(s)", ""]
    for report in sorted(reports, key=lambda r: (r.rate, r.name)):
        lines.append(f"  {report.rate:6.1%}  {report.name:<10} {report.passed}/{report.total}")
    return "\n".join(lines)


def core_step(cpu: abi.Cpu) -> None:
    """Execute one instruction with the real core.

    An unimplemented opcode raises rather than passing silently, and the
    harness turns that into a failure for the case rather than aborting the
    run -- one unwritten opcode should not hide the pass rate of every other.
    """
    try:
        cpu.step()
    except abi.Unimplemented:
        pass


def no_execution(cpu: abi.Cpu) -> None:
    """A core that does nothing, kept as the baseline to measure against."""


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run SST8088 cases against the core and report a pass rate per opcode."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        help="an opcode file, or a directory of them. "
        "Defaults to the committed excerpt under tests/fixtures/sst8088/.",
    )
    parser.add_argument("--limit", type=int, help="cases per file")
    parser.add_argument("--failures", type=int, default=3, help="failures to print per file")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="run the do-nothing core instead, to see what the real one is worth",
    )
    args = parser.parse_args(argv)

    repo = pathlib.Path(__file__).resolve().parents[2]
    target = args.path or (repo / "tests" / "fixtures" / "sst8088")

    step: Step = no_execution if args.baseline else core_step

    try:
        if target.is_dir():
            reports = run_corpus(target, step, limit_per_file=args.limit)
        else:
            reports = [run_file(target, step, limit=args.limit)]
    except (HarnessError, sst8088.CorpusError) as exc:
        print(f"conformance: {exc}", file=sys.stderr)
        return 2

    label = "none (do-nothing baseline)" if args.baseline else "core/i8086"
    print(f"core: {label}\n")
    print(summarise(reports))
    for report in reports:
        for failure in report.failures[: args.failures]:
            print(f"    {failure.describe()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
