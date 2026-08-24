# OpenHardware — the claim that a board runs firmware must point at a test.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Exercises `tools/check_board_claims.py`, the checker for rules/board-claims.md.

Most tests build a miniature repository in `tmp_path` -- a catalogue holding the
register, a named test, and an image beside it -- and then break one thing at a
time. Running against a fixture rather than the real tree is what lets a
failure be constructed on purpose; running the real checker as a subprocess, in
`test_the_repository_passes_today`, is what proves the fixtures resemble it.

No `@pytest.mark.parametrize` anywhere: `tools/inventory.py` counts `def test_*`
with `ast`, and `test_ast_count_matches_pytest_collection` fails on the
divergence. Where a case repeats, it repeats inside one test.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from tools import check_board_claims as C
from tools.rules_meta import parse_rule

REPO = pathlib.Path(__file__).resolve().parents[2]

#: A catalogue with two chips and evidence for exactly one of them.
CATALOGUE = '''
CHIPS = {
    "RP2040": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    "SAMD21": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    "ESP32-C6": ("RV32IMAC", "riscv32"),
}
FIRMWARE_VERIFIED = {"RP2040": "tests/cortexm0/test_blink.py"}
'''

#: A named test that does everything check 5 asks: names an image that is
#: there, reads it off disk, and steps a CPU over it.
EVIDENCE = '''
import pathlib

IMAGE = pathlib.Path(__file__).resolve().parent / "blink.bin"


def test_the_led_actually_blinks(cpu):
    cpu.write_block(0x10000100, IMAGE.read_bytes())
    for _ in range(20):
        cpu.step()
'''


def build_root(
    tmp_path: pathlib.Path,
    *,
    catalogue: str = CATALOGUE,
    evidence: str | None = EVIDENCE,
    image: bool = True,
    files: dict[str, str] | None = None,
) -> pathlib.Path:
    """A miniature repository, correct unless an argument says otherwise."""
    boards = tmp_path / "webui" / "boards"
    boards.mkdir(parents=True)
    (boards / "catalogue.py").write_text(catalogue, encoding="utf-8")

    suite = tmp_path / "tests" / "cortexm0"
    suite.mkdir(parents=True)
    if evidence is not None:
        (suite / "test_blink.py").write_text(evidence, encoding="utf-8")
    if image:
        (suite / "blink.bin").write_bytes(bytes(range(16)))

    for relative, text in (files or {}).items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def problems(root: pathlib.Path) -> list[str]:
    """Every check, run over one root, flattened."""
    out: list[str] = []
    for _, check in C.CHECKS:
        out += check(root)
    return out


# --- the real repository ----------------------------------------------------


def test_the_repository_passes_today():
    """RP2040 is the one claim, and it holds."""
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "check_board_claims.py")],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RP2040 -> tests/cortexm0/test_blink.py" in result.stdout


def test_the_rule_arms_this_checker():
    rule = parse_rule(REPO / "rules" / "board-claims.md")
    scripted = [m for m in rule.mechanisms if m.tier == "SCRIPT-ENFORCED"]
    assert [(m.checker, m.armed) for m in scripted] == [
        ("tools/check_board_claims.py", True)
    ]


def test_claude_md_runs_it_before_a_commit():
    """A checker nobody runs is a rule nobody has."""
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    block = text.split("## Before you commit", 1)[1].split("```", 2)[1]
    assert "python tools/check_board_claims.py" in block


def test_the_rule_and_the_checker_are_not_their_own_surfaces():
    """Both quote the phrases they govern; scanning them would be circular."""
    scanned = {p.relative_to(REPO).as_posix() for p in C.surfaces(REPO)}
    assert "rules/board-claims.md" not in scanned
    assert "tools/check_board_claims.py" not in scanned
    assert "webui/boards/catalogue.py" in scanned


# --- the fixture, unbroken --------------------------------------------------


def test_a_correct_miniature_repository_reports_nothing(tmp_path):
    assert problems(build_root(tmp_path)) == []


# --- 1. a chip named beside a run-claim -------------------------------------


def test_a_chip_named_beside_a_run_claim_must_name_a_test(tmp_path):
    """Every phrasing that would be a lie if no image had executed."""
    phrasings = (
        "The SAMD21 board runs firmware today.",
        "SAMD21, running firmware in the browser.",
        "Firmware runs on the SAMD21.",
        "The SAMD21 ran real firmware last week.",
        "SAMD21: firmware verified.",
    )
    for index, phrase in enumerate(phrasings):
        root = build_root(tmp_path / str(index), files={"docs/boards.md": phrase})
        found = C.unevidenced_chip_claims(root)
        assert len(found) == 1, f"{phrase!r} produced {found}"
        assert "SAMD21" in found[0]
        assert "docs/boards.md:1" in found[0]


def test_the_same_sentence_about_the_verified_chip_is_allowed(tmp_path):
    root = build_root(tmp_path, files={"docs/boards.md": "The RP2040 runs firmware."})
    assert C.unevidenced_chip_claims(root) == []


def test_a_claim_with_no_firmware_word_in_it_is_not_this_rules_business(tmp_path):
    """"supported" and "works" are claims about the repository, and matching
    them would report lines nobody can act on."""
    root = build_root(
        tmp_path, files={"docs/boards.md": "The SAMD21 board is supported and works."}
    )
    assert problems(root) == []


def test_a_part_that_merely_starts_with_a_known_chip_is_not_that_chip(tmp_path):
    """ESP32-C61 is a real Espressif part and is not an ESP32-C6. Without the
    delimiter guard this reports a chip that is not on the board, which is a
    finding nobody can act on."""
    root = build_root(
        tmp_path, files={"docs/boards.md": "XIAO-ESP32-C61-DIP runs firmware."}
    )
    assert C.unevidenced_chip_claims(root) == []


# --- 2. a code surface that never reads the register ------------------------


def test_a_badge_that_names_no_chip_still_has_to_read_the_register(tmp_path):
    """Check 1 is blind here: "RUNS FIRMWARE" spells out no chip at all."""
    source = 'function badge(board) { return ["pill", "RUNS FIRMWARE"]; }'
    root = build_root(tmp_path, files={"webui/static/boards.js": source})
    assert C.unevidenced_chip_claims(root) == []
    found = C.ungrounded_code_claims(root)
    assert len(found) == 1 and "webui/static/boards.js:1" in found[0]


def test_the_same_badge_derived_from_the_register_is_allowed(tmp_path):
    source = (
        'function badge(board) {'
        ' return board.firmware_verified ? "RUNS FIRMWARE" : "UNPROVEN"; }'
    )
    root = build_root(tmp_path, files={"webui/static/boards.js": source})
    assert problems(root) == []


def test_prose_is_not_held_to_the_two_code_checks(tmp_path):
    """A document does not consult anything, so asking it to would fail every
    honest paragraph about the badge -- including this repository's own record
    of the regression check 3 exists to catch."""
    note = "The badge said RUNS FIRMWARE from board.runnable, which was wrong."
    root = build_root(tmp_path, files={"docs/history.md": note})
    assert C.ungrounded_code_claims(root) == []
    assert C.claims_decided_by_a_weaker_fact(root) == []


# --- 3. decided by a fact about the repository ------------------------------


def test_a_run_claim_decided_by_a_fact_about_the_repository_fails(tmp_path):
    """The regression that has already happened, in each of its four flavours."""
    for index, field in enumerate(("runnable", "core_built", "core_exists", "described")):
        source = f'''
const proven = data.boards.filter((b) => b.firmware_verified).length;




function badge(board) {{
  if (board.{field}) return ["pill", "RUNS FIRMWARE"];
}}
'''
        root = build_root(tmp_path / str(index), files={"webui/static/boards.js": source})
        assert C.ungrounded_code_claims(root) == [], "the file does read the register"
        found = C.claims_decided_by_a_weaker_fact(root)
        assert len(found) == 1, f"{field} produced {found}"
        assert field in found[0]


def test_a_weaker_fact_standing_next_to_the_evidence_is_allowed(tmp_path):
    source = (
        'if (board.runnable && board.firmware_verified)'
        ' return ["pill", "RUNS FIRMWARE"];'
    )
    root = build_root(tmp_path, files={"webui/static/boards.js": source})
    assert C.claims_decided_by_a_weaker_fact(root) == []


def test_a_condition_on_one_line_and_its_body_on_the_next_is_still_caught(tmp_path):
    source = '''
const proven = data.boards.filter((b) => b.firmware_verified).length;




if (board.runnable)
  return ["pill", "RUNS FIRMWARE"];
'''
    root = build_root(tmp_path, files={"webui/static/boards.js": source})
    assert len(C.claims_decided_by_a_weaker_fact(root)) == 1


# --- 4 and 5. the evidence itself -------------------------------------------


def test_a_named_test_that_is_not_there_fails(tmp_path):
    root = build_root(tmp_path, evidence=None)
    found = C.missing_evidence(root)
    assert len(found) == 1 and "tests/cortexm0/test_blink.py" in found[0]
    assert C.evidence_that_never_loads_an_image(root) == [], "said once is enough"


def test_a_named_test_that_names_no_image_fails(tmp_path):
    """Naming any file satisfies check 4; this is what check 5 adds."""
    evidence = '''
def test_the_led_actually_blinks(cpu):
    cpu.write_block(0x10000100, bytes(16))
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence)
    assert C.missing_evidence(root) == []
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1 and "names no image file" in found[0]


def test_a_named_test_citing_an_image_that_does_not_exist_fails(tmp_path):
    root = build_root(tmp_path, image=False)
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1, found
    assert "blink.bin" in found[0] and "no such file exists" in found[0]


def test_a_named_test_that_never_reads_the_image_off_disk_fails(tmp_path):
    """It names blink.bin, and blink.bin is there. It still never opens it."""
    evidence = '''
IMAGE = "blink.bin"


def test_the_led_actually_blinks(cpu):
    cpu.write_block(0x10000100, bytes(16))
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1 and "never reads an image off disk" in found[0]


def test_a_named_test_that_never_executes_the_image_fails(tmp_path):
    evidence = '''
import pathlib

IMAGE = pathlib.Path(__file__).resolve().parent / "blink.bin"


def test_the_image_has_a_vector_table(cpu):
    cpu.write_block(0x10000100, IMAGE.read_bytes())
    assert cpu.read_word(0x10000100)
'''
    root = build_root(tmp_path, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1 and "never executes it" in found[0]


def test_a_binary_open_counts_as_reading_the_image(tmp_path):
    """read_bytes is the idiom here; refusing every other way of opening a file
    would fail an honest test for a reason that is about style."""
    evidence = '''
def test_the_led_actually_blinks(cpu):
    with open("blink.bin", "rb") as handle:
        cpu.write_block(0x10000100, handle.read())
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence)
    assert C.evidence_that_never_loads_an_image(root) == []


# --- what is not a surface --------------------------------------------------


def test_the_evidence_the_vendor_and_the_record_are_not_surfaces(tmp_path):
    """Each for its own reason: tests are the evidence, a vendor is talking
    about their own silicon, and a ticket is what was decided and when."""
    root = build_root(tmp_path, files={
        "tests/webui/test_badge.py": 'BADGE = "SAMD21 runs firmware"',
        "third_party/seeed/tutorial.md": "Our DAPLink firmware runs on the SAMD21.",
        "docs/tickets/OH-99-slug.md": "We agreed the SAMD21 runs firmware.",
        "docs/research/notes.md": "Suppose the SAMD21 runs firmware.",
        "docs/HANDOFF_2026-01-01_x.md": "Left it saying the SAMD21 runs firmware.",
        "build/generated.js": 'return "RUNS FIRMWARE";',
        ".pytest_cache/x.md": "The SAMD21 runs firmware.",
    })
    assert problems(root) == []


def test_a_new_document_is_a_surface_without_anyone_adding_it(tmp_path):
    """Default-on. The opposite default is how a new page ships making an old
    claim."""
    root = build_root(tmp_path, files={"docs/new/page.md": "The SAMD21 runs firmware."})
    assert len(C.unevidenced_chip_claims(root)) == 1


# --- reading the register ---------------------------------------------------


def test_the_register_is_read_without_importing_the_catalogue(tmp_path):
    """The register has to be readable from a tree that will not import --
    a checkout with no built core, or the fixtures above."""
    catalogue = CATALOGUE + "\nimport a_module_that_certainly_does_not_exist\n"
    root = build_root(tmp_path, catalogue=catalogue)
    assert C.register(root) == {"RP2040": "tests/cortexm0/test_blink.py"}


def test_a_register_that_is_not_a_literal_is_an_error_not_a_pass(tmp_path):
    catalogue = CATALOGUE.replace(
        'FIRMWARE_VERIFIED = {"RP2040": "tests/cortexm0/test_blink.py"}',
        'FIRMWARE_VERIFIED = dict(RP2040="tests/cortexm0/test_blink.py")',
    )
    root = build_root(tmp_path, catalogue=catalogue)
    with pytest.raises(C.ClaimError, match="not a literal"):
        C.register(root)


def test_an_empty_chip_table_is_an_error_not_a_pass(tmp_path):
    """With no chips, every chip claim passes check 1 -- the vacuous green."""
    root = build_root(
        tmp_path, catalogue='CHIPS = {}\nFIRMWARE_VERIFIED = {}\n'
    )
    with pytest.raises(C.ClaimError, match="every chip would pass"):
        C.chips(root)


# --- exit codes -------------------------------------------------------------


def test_a_missing_register_is_skipped_and_never_a_quiet_pass(tmp_path):
    """3, not 0. A checker that could not run must not look like one that ran
    and was happy."""
    tools = tmp_path / "tools"
    tools.mkdir()
    checker = tools / "check_board_claims.py"
    checker.write_bytes((REPO / "tools" / "check_board_claims.py").read_bytes())

    result = subprocess.run(
        [sys.executable, str(checker)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == C.SKIPPED
    assert "SKIPPED" in result.stderr


def test_a_fabricated_claim_fails_the_checker_end_to_end(tmp_path):
    """The whole thing, as a commit would run it: exit 1 and the line to fix."""
    build_root(tmp_path, files={"docs/boards.md": "The SAMD21 board runs firmware."})
    tools = tmp_path / "tools"
    tools.mkdir()
    checker = tools / "check_board_claims.py"
    checker.write_bytes((REPO / "tools" / "check_board_claims.py").read_bytes())

    result = subprocess.run(
        [sys.executable, str(checker)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "docs/boards.md:1" in result.stderr
    assert "SAMD21 names no test in FIRMWARE_VERIFIED" in result.stderr
    assert "rules/board-claims.md" in result.stderr
