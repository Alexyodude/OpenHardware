# OpenHardware - tests for the SST8088 conformance harness.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for tests/i8086/conformance.py, per ticket OH-6.

Two layers, and the first is what makes the second trustworthy.

**The harness, against stand-ins.** Most of this file drives the harness with
behaviour known exactly: one step that produces the right answer, and several
wrong in one specific way each. That is the only way to know a harness works.
Pointed at a real core, a harness that always says "pass" and a harness that
is correct look identical until the core has a bug, and by then you are
debugging both.

**The core, against silicon.** The last few run the real core over all eleven
cases and require 11/11, plus a matching run of the do-nothing baseline that
must still score 0. If those two ever report the same rate, the comparison has
stopped meaning anything.

The cases are the eleven real ones committed under `tests/fixtures/sst8088/`,
so every shape exercised here is a shape the corpus actually produces.
"""

import pathlib

import pytest

from core.i8086 import abi
from tools import sst8088

from . import conformance

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sst8088"


@pytest.fixture(scope="module")
def cases():
    """The eleven committed cases, across three opcode files."""
    found = []
    for path in sorted(FIXTURES.glob("*.json")):
        found.extend(sst8088.load(path))
    if not found:
        pytest.skip(f"no fixture cases under {FIXTURES}")
    return found


@pytest.fixture
def case():
    """The NOP case: the simplest real thing the corpus contains.

    Loaded by name rather than as `cases[0]`. Glob order puts `00.json`
    first -- an ADD with a memory write and four moved registers -- and two
    tests below assert on exactly what this case changes, so taking whichever
    file sorted first made them pass or fail on filenames.
    """
    path = FIXTURES / "90.json"
    if not path.is_file():
        pytest.skip(f"{path} absent")
    return sst8088.load(path)[0]


# --- the stand-ins -------------------------------------------------------------


def perfect(case: sst8088.Case) -> conformance.Step:
    """A step that produces exactly what the silicon did."""

    def step(cpu: abi.Cpu) -> None:
        cpu.set_regs(**case.expected_regs)
        for address, value in case.expected_ram.items():
            cpu.write_byte(address, value)

    return step


def does_nothing(cpu: abi.Cpu) -> None:
    """What an unimplemented core does. Every case with a state change fails."""


def wrong_in(register: str, case: sst8088.Case) -> conformance.Step:
    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        cpu.set_regs(**{register: (case.expected_regs[register] ^ 0x0001)})

    return step


# --- the harness agrees with a correct core --------------------------------------


def test_a_perfect_step_passes(case):
    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, perfect(case))
    assert result.ok, result.describe()


def test_every_fixture_case_passes_a_perfect_step(cases):
    """Each case needs its own perfect step, so they run one at a time."""
    failed = []
    with abi.Cpu() as cpu:
        for one in cases:
            result = conformance.run_case(cpu, one, perfect(one))
            if not result.ok:
                failed.append(result.describe())
    assert not failed, "; ".join(failed)


# --- and disagrees with an incorrect one -------------------------------------------


def test_a_step_that_does_nothing_fails(case):
    """The NOP case advances IP by two; a core that does nothing must not pass."""
    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, does_nothing)
    assert not result.ok
    assert any(d.where == "ip" for d in result.divergences)


def test_one_wrong_register_is_reported_and_named(case):
    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, wrong_in("bx", case))
    assert [d.where for d in result.divergences] == ["bx"]


def test_wrong_memory_is_reported_with_its_address(case):
    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        address = sorted(case.expected_ram)[0]
        cpu.write_byte(address, case.expected_ram[address] ^ 0xFF)

    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, step)
    assert [d.kind for d in result.divergences] == ["memory"]
    assert result.divergences[0].where == f"{sorted(case.expected_ram)[0]:05X}"


# --- the delta trap ----------------------------------------------------------------


def test_all_fourteen_registers_are_compared_not_just_the_changed_ones(case):
    """`final` lists only what moved. A harness comparing against it directly
    would check one register and call it a pass -- the exact trap
    tools/sst8088.py's docstring warns about.

    This NOP case moves only IP, so corrupting AX must still fail."""
    assert case.changed_registers == ("ip",), "fixture assumption"
    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, wrong_in("ax", case))
    assert not result.ok
    assert [d.where for d in result.divergences] == ["ax"]


def test_memory_the_case_does_not_mention_is_not_compared(case):
    """The corpus specifies a handful of bytes and says nothing about the other
    million. Comparing those would fail on memory hardware never described."""

    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        cpu.write_byte(0x7FF00, 0xAA)  # nowhere near anything the case names

    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, step)
    assert result.ok, result.describe()


# --- flags -------------------------------------------------------------------------


def test_undefined_flag_bits_are_never_compared(case):
    """Bits 1, 3, 5 and 12-15 are unassigned on this part."""

    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        cpu.set_regs(flags=case.expected_regs["flags"] ^ 0b0000_0000_0010_1000)

    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, step)
    assert result.ok, result.describe()


def test_a_defined_flag_bit_is_compared(case):
    """Carry is bit 0 and is always meaningful."""

    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        cpu.set_regs(flags=case.expected_regs["flags"] ^ 0x0001)

    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, step)
    assert [d.where for d in result.divergences] == ["flags"]


def test_a_mask_can_exclude_a_flag_an_opcode_leaves_undefined(case):
    """Several instructions leave flags undefined and hardware still produces
    something. `flag_mask` is how those are excluded, per opcode."""

    def step(cpu: abi.Cpu) -> None:
        perfect(case)(cpu)
        cpu.set_regs(flags=case.expected_regs["flags"] ^ 0x0001)

    with abi.Cpu() as cpu:
        masked = conformance.run_case(cpu, case, step, flag_mask=~0x0001 & 0xFFFF)
    assert masked.ok, masked.describe()


def test_the_default_mask_hides_nothing():
    """A harness that quietly ignored bits by default would be vacuous."""
    import inspect

    signature = inspect.signature(conformance.run_case)
    assert signature.parameters["flag_mask"].default == 0xFFFF


# --- reporting ----------------------------------------------------------------------


def test_a_report_counts_both_outcomes(cases):
    report = conformance.run_cases(cases, does_nothing, name="90")
    assert report.total == len(cases)
    assert report.failed > 0
    assert report.passed + report.failed == report.total


def test_a_report_keeps_only_a_few_failures(cases):
    """An unimplemented opcode produces ten thousand identical failures; the
    first few say everything the last few would."""
    report = conformance.run_cases(cases, does_nothing, name="90")
    assert len(report.failures) <= report.keep_failures


def test_running_zero_cases_raises(cases):
    """No failures over no tests reads exactly like a pass."""
    with pytest.raises(conformance.HarnessError, match="zero cases"):
        conformance.run_cases([], does_nothing, name="empty")


def test_a_limit_stops_early(cases):
    report = conformance.run_cases(cases, does_nothing, name="90", limit=2)
    assert report.total == 2


def test_a_file_can_be_run_directly():
    report = conformance.run_file(FIXTURES / "90.json", does_nothing)
    assert report.name == "90"
    assert report.total > 0


def test_the_summary_puts_the_worst_first():
    good = conformance.Report("good", passed=10, failed=0)
    bad = conformance.Report("bad", passed=1, failed=9)
    text = conformance.summarise([good, bad])
    assert text.index("bad") < text.index("good")


def test_a_failure_describes_itself_with_the_opcode_bytes(case):
    with abi.Cpu() as cpu:
        result = conformance.run_case(cpu, case, does_nothing)
    described = result.describe()
    assert "2E 90" in described and "ip" in described


# --- against the real corpus, when it has been fetched --------------------------------


def test_the_fetched_corpus_runs_if_it_is_present():
    """Skips by name when tools/get_8088_tests.sh has not been run.

    This is the only test here that touches the ~2 GB corpus, and it runs a
    handful of cases rather than all 10,000 -- it is checking that the reader
    and harness survive real files, not measuring conformance.
    """
    corpus = pathlib.Path(__file__).resolve().parents[2] / "third_party" / "sst8088" / "v2"
    if not corpus.is_dir():
        pytest.skip("corpus absent; run bash tools/get_8088_tests.sh")
    files = sst8088.opcode_files(corpus)[:3]
    for path in files:
        report = conformance.run_file(path, does_nothing, limit=5)
        assert report.total == 5


# --- the real core against the real cases ------------------------------------------


def test_the_real_core_passes_every_committed_case(cases):
    """The number this whole slice exists to move: 0/11 to 11/11.

    Asserted rather than printed. A printed rate that quietly drops to 9/11
    is a regression nobody notices until they read the log; an assertion
    fails the build.
    """
    report = conformance.run_cases(cases, conformance.core_step, name="fixtures")
    detail = "; ".join(f.describe() for f in report.failures)
    assert report.passed == report.total, (
        f"{report.failed} of {report.total} regressed: {detail}"
    )
    assert report.total == 11, "the committed excerpt is eleven cases"


def test_the_do_nothing_baseline_still_fails(cases):
    """Proves the 100% above is the core and not a harness that passes
    anything. If both report the same rate, the comparison is meaningless."""
    baseline = conformance.run_cases(cases, conformance.no_execution, name="baseline")
    assert baseline.passed == 0


def test_every_add_case_matches_flags_exactly(cases):
    """All four 00.json cases change flags, so they are the real flag test --
    against silicon, not against a manual."""
    adds = [c for c in cases if c.name.startswith("add")]
    assert len(adds) == 4, "fixture assumption"
    report = conformance.run_cases(adds, conformance.core_step, name="add")
    assert report.passed == 4, "; ".join(f.describe() for f in report.failures)
