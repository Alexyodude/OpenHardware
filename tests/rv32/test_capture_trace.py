# OpenHardware - tests for the silicon capture harness (OH-159).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`tools/capture_trace.py`: a GDB single-step log becomes rv32 cases, and
replaying them through `core/riscv32` names every disagreement.

Every log in this file is SYNTHETIC: written here, in the shape GDB prints,
to prove the harness reads it and refuses what it must refuse. None of it is
a capture, and none of it is evidence about silicon. A real capture lives in
`tests/fixtures/hardware/` and is checked by the last test.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import capture_trace as ct

HARDWARE = REPO / "tests" / "fixtures" / "hardware"
BASE = 0x42000100


def dump(regs: dict[int, int], pc: int, halves: tuple[int, int],
         drop: str | None = None) -> str:
    """One halt as `info registers` and `x/2xh $pc` print it."""
    full = {n: 0 for n in range(1, 32)}
    full.update(regs)
    lines = [ct.STEP]
    for number in range(1, 32):
        name = "fp" if number == 8 else ct.ABI_NAMES[number]
        if name == drop:
            continue
        value = full[number]
        lines.append(f"{name:<15}0x{value:<16x}{value}")
    lines.append(f"pc             0x{pc:<16x}0x{pc:x} <main+{pc & 0xff}>")
    lines.append(f"0x{pc:x} <main+{pc & 0xff}>:\t0x{halves[0]:04x}\t0x{halves[1]:04x}")
    return "\n".join(lines) + "\n"


def log(*halts: str, end: bool = True) -> str:
    return ("Remote debugging using localhost:3333\n" + "".join(halts)
            + (ct.END + "\n" if end else ""))


def halves32(word: int) -> tuple[int, int]:
    return word & 0xFFFF, word >> 16


def trace(steps: list[tuple[dict[int, int], int, tuple[int, int]]]) -> str:
    return log(*(dump(r, pc, h) for r, pc, h in steps))


def fixture_of(text: str) -> dict:
    return ct.fixture(text, "esp32c3", "synthetic, no board", "2026-11-05")


# addi a0,a0,1 ; c.addi a0,1 ; add a2,a0,a1 ; beq a0,a0,+8 ; then the target.
ADDI = 0x00150513
C_ADDI = 0x0505
ADD = 0x00B50633
BEQ = 0x00A50463
AGREEING = [
    ({10: 5, 11: 7}, BASE, halves32(ADDI)),
    ({10: 6, 11: 7}, BASE + 4, (C_ADDI, 0x0000)),
    ({10: 7, 11: 7}, BASE + 6, halves32(ADD)),
    ({10: 7, 11: 7, 12: 14}, BASE + 10, halves32(BEQ)),
    ({10: 7, 11: 7, 12: 14}, BASE + 18, halves32(ADDI)),
]


def test_a_trace_that_agrees_with_the_core_passes():
    data = fixture_of(trace(AGREEING))
    assert [c["mnemonic"] for c in data["cases"]] == [
        "addi a0,a0,1", "c.addi a0,1", "add a2,a0,a1",
        data["cases"][3]["mnemonic"]]
    assert data["cases"][3]["mnemonic"].startswith("beq")
    assert data["cases"][1]["width"] == 16
    assert data["cases"][1]["encoding"] == "0x0505"
    assert data["cases"][0]["silicon"] == {
        "status": "executed", "writes": {"10": 6}, "pc": BASE + 4}
    report = ct.replay(data)
    assert report.wrong == []
    assert report.compared == 4
    assert report.ok


def test_initial_is_the_whole_register_file_not_a_delta():
    data = fixture_of(trace(AGREEING))
    assert sorted(map(int, data["cases"][0]["initial"])) == list(range(1, 32))


def test_a_wrong_result_register_is_named():
    steps = list(AGREEING)
    steps[1] = ({10: 9, 11: 7}, BASE + 4, (C_ADDI, 0x0000))  # addi gave 9?
    steps[2] = ({10: 10, 11: 7}, BASE + 6, halves32(ADD))
    steps[3] = ({10: 10, 11: 7, 12: 17}, BASE + 10, halves32(BEQ))
    steps[4] = ({10: 10, 11: 7, 12: 17}, BASE + 18, halves32(ADDI))
    report = ct.replay(fixture_of(trace(steps)))
    assert not report.ok
    assert len(report.wrong) == 1
    assert "case 0" in report.wrong[0] and "x10 (a0)" in report.wrong[0]


def test_a_register_the_core_left_alone_but_silicon_changed_is_named():
    steps = [
        ({10: 5}, BASE, halves32(ADDI)),
        ({10: 6, 13: 1}, BASE + 4, halves32(ADDI)),
    ]
    report = ct.replay(fixture_of(trace(steps)))
    assert [w for w in report.wrong if "x13 (a3)" in w]
    assert not report.ok


def test_a_register_the_core_wrote_but_silicon_left_alone_is_named():
    # The delta hazard: silicon's `writes` is empty, so a check that only
    # looked at written registers would compare nothing and pass.
    steps = [
        ({10: 5}, BASE, halves32(ADDI)),
        ({10: 5}, BASE + 4, halves32(ADDI)),
    ]
    report = ct.replay(fixture_of(trace(steps)))
    assert report.compared == 1
    assert len(report.wrong) == 1 and "x10 (a0)" in report.wrong[0]


def test_a_wrong_next_pc_is_named():
    steps = [
        ({10: 7}, BASE, halves32(BEQ)),
        ({10: 7}, BASE + 4, halves32(ADDI)),  # the core takes it to +8
    ]
    report = ct.replay(fixture_of(trace(steps)))
    assert len(report.wrong) == 1 and "pc is" in report.wrong[0]


def test_an_instruction_this_core_does_not_execute_is_wrong_not_skipped():
    # 0x0000000b is custom-0: the chip "executed" it, so a core that
    # cannot is a disagreement, not something to step over.
    steps = [({}, BASE, halves32(0x0000000B)), ({}, BASE + 4, halves32(ADDI))]
    report = ct.replay(fixture_of(trace(steps)))
    assert report.compared == 0
    assert len(report.wrong) == 1


def test_csr_access_is_skipped_by_name_and_counted():
    csrr = 0xB0002573  # csrr a0, mcycle
    steps = [
        ({}, BASE, halves32(csrr)),
        ({10: 1234}, BASE + 4, halves32(ADDI)),
        ({10: 1235}, BASE + 8, halves32(ADDI)),
    ]
    report = ct.replay(fixture_of(trace(steps)))
    assert report.compared == 1 and report.ok
    assert len(report.skipped) == 1 and "SYSTEM" in report.skipped[0]


def test_a_load_is_skipped_never_passed():
    lw = 0x00012503  # lw a0, 0(sp)
    steps = [({2: 0x3FC80000}, BASE, halves32(lw)),
             ({2: 0x3FC80000, 10: 42}, BASE + 4, halves32(ADDI))]
    report = ct.replay(fixture_of(trace(steps)))
    assert report.compared == 0
    assert len(report.skipped) == 1 and "memory" in report.skipped[0]
    assert not report.ok, "a file where nothing was compared must fail"


def test_logs_that_are_not_a_complete_capture_are_refused():
    good = dump({10: 5}, BASE, halves32(ADDI))
    after = dump({10: 6}, BASE + 4, halves32(ADDI))
    without_bytes = "".join(after.splitlines(keepends=True)[:-1])
    refused = {
        "empty": "",
        "truncated": log(good, after, end=False),
        "one halt": log(good),
        "missing register": log(good, dump({10: 6}, BASE + 4, halves32(ADDI),
                                           drop="s3")),
        "bytes not at the pc": log(good, without_bytes
                                   + f"0x{BASE + 8:x}:\t0x0513\t0x0015\n"),
        "no instruction bytes": log(good, without_bytes),
        "register twice": log(good, after + "a0             0x1    1\n"),
    }
    for name, text in refused.items():
        with pytest.raises(ct.TraceError):
            ct.parse_log(text)
            pytest.fail(f"{name}: accepted")


def test_a_fixture_with_no_cases_is_refused():
    with pytest.raises(ct.TraceError):
        ct.replay({"isa": "RV32IMC", "cases": []})


def test_the_fixture_records_where_it_came_from():
    text = trace(AGREEING)
    data = fixture_of(text)
    assert data["part"] == "ESP32-C3"
    assert data["oracle"] == "silicon"
    from webui.boards import esp32c3
    assert data["isa"] == esp32c3.ISA
    assert data["provenance"]["captured_on"] == "2026-11-05"
    assert len(data["provenance"]["log_sha256"]) == 64
    with pytest.raises(ValueError):
        ct.fixture(text, "esp32c3", "b", "yesterday")
    with pytest.raises(ValueError):
        ct.fixture(text, "nrf52840", "b", "2026-11-05")


def test_the_gdb_script_emits_what_the_parser_requires():
    script = ct.gdb_script(3)
    assert script.count(ct.STEP) == 2  # once in the loop, once after it
    assert ct.END in script
    assert "stepi" in script and "info registers" in script
    assert "x/2xh $pc" in script
    assert "localhost:3333" in script
    with pytest.raises(ValueError):
        ct.gdb_script(0)


def test_the_cli_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.log"
    good.write_text(trace(AGREEING), encoding="utf-8")
    out = tmp_path / "good.json"
    assert ct.main(["convert", str(good), "--board", "synthetic",
                    "--captured-on", "2026-11-05", "-o", str(out)]) == 0
    assert ct.main(["check", str(out)]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    data["cases"][0]["silicon"]["writes"]["10"] = 99
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert ct.main(["check", str(bad)]) == 1

    lw = 0x00012503
    only_skips = tmp_path / "skips.log"
    only_skips.write_text(trace([({}, BASE, halves32(lw)),
                                 ({}, BASE + 4, halves32(ADDI))]),
                          encoding="utf-8")
    skipped = tmp_path / "skips.json"
    ct.main(["convert", str(only_skips), "--board", "synthetic",
             "--captured-on", "2026-11-05", "-o", str(skipped)])
    assert ct.main(["check", str(skipped)]) == 1
    assert "nothing was compared" in capsys.readouterr().out


def test_every_committed_capture_replays():
    captures = sorted(HARDWARE.glob("*.json")) if HARDWARE.is_dir() else []
    if not captures:
        pytest.skip("no hardware capture is committed yet: "
                    "tests/fixtures/hardware/ is empty (OH-159 step 3)")
    for path in captures:
        report = ct.replay(json.loads(path.read_text(encoding="utf-8")))
        assert report.ok, f"{path.name}: {report.compared} compared, " \
                          f"wrong: {report.wrong}"
