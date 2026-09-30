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
import re
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
BOARD_FIRMWARE_VERIFIED = {}
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


#: A manifest with one row, whose name carries a chip.
MANIFEST = '''
ROWS = (
    Row(board="Some Thing ESP32-C6", chip="ESP32-C6"),
)
'''


def build_root(
    tmp_path: pathlib.Path,
    *,
    catalogue: str = CATALOGUE,
    manifest: str | None = MANIFEST,
    evidence: str | None = EVIDENCE,
    image: bool = True,
    files: dict[str, str] | None = None,
) -> pathlib.Path:
    """A miniature repository, correct unless an argument says otherwise."""
    boards = tmp_path / "webui" / "boards"
    boards.mkdir(parents=True)
    (boards / "catalogue.py").write_text(catalogue, encoding="utf-8")
    if manifest is not None:
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "board_manifest.py").write_text(manifest, encoding="utf-8")

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
    assert ("Adafruit Feather ESP32-C6 -> tests/webui/test_feather_esp32c6_board.py"
            in result.stdout)
    assert ("SparkFun Thing Plus ESP32-C6 -> tests/webui/test_sparkfun_esp32c6_board.py"
            in result.stdout)
    assert ("Adafruit QT Py ESP32-C3 -> tests/webui/test_qtpy_esp32c3_board.py"
            in result.stdout)
    assert ("SparkFun Pro Micro ESP32-C3 -> "
            "tests/webui/test_sparkfun_pro_micro_esp32c3_board.py" in result.stdout)
    assert ("SparkFun Qwiic Pocket ESP32-C6 -> "
            "tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py" in result.stdout)
    assert "Adafruit KB2040 -> tests/webui/test_kb2040_board.py" in result.stdout
    assert ("PCBCUPID Glyph Mini RP2040 -> "
            "tests/webui/test_glyph_mini_rp2040_board.py" in result.stdout)


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


# --- 1, for a row of tools/board_manifest.py (OH-183) -------------------------

#: The miniature, with the chip the row carries verified: its name alone would
#: pass on the chip's evidence.
C6_CATALOGUE = CATALOGUE.replace(
    'FIRMWARE_VERIFIED = {"RP2040": "tests/cortexm0/test_blink.py"}',
    'FIRMWARE_VERIFIED = {"RP2040": "tests/cortexm0/test_blink.py", '
    '"ESP32-C6": "tests/cortexm0/test_blink.py"}',
)


def test_a_row_named_beside_a_run_claim_needs_its_own_entry_not_its_chips(tmp_path):
    root = build_root(tmp_path, catalogue=C6_CATALOGUE,
                      files={"docs/boards.md": "The Some Thing ESP32-C6 runs firmware."})
    found = C.unevidenced_chip_claims(root)
    assert len(found) == 1, found
    assert found[0].startswith(
        "docs/boards.md:1: says Some Thing ESP32-C6 runs firmware, but Some Thing "
        "ESP32-C6 is a row in tools/board_manifest.py and names no test in "
        "BOARD_FIRMWARE_VERIFIED"), found


def test_a_row_with_its_own_entry_may_say_it(tmp_path):
    catalogue = C6_CATALOGUE.replace(
        "BOARD_FIRMWARE_VERIFIED = {}",
        'BOARD_FIRMWARE_VERIFIED = {"Some Thing ESP32-C6": "tests/cortexm0/test_blink.py"}')
    root = build_root(tmp_path, catalogue=catalogue,
                      files={"docs/boards.md": "The Some Thing ESP32-C6 runs firmware."})
    assert C.unevidenced_chip_claims(root) == []


def test_the_chip_in_a_rows_name_is_not_read_as_a_second_claim(tmp_path):
    """Its own entry licenses the row; the ESP32-C6 in its name is its name,
    and an unverified chip beside it on the line is still caught."""
    catalogue = CATALOGUE.replace(
        "BOARD_FIRMWARE_VERIFIED = {}",
        'BOARD_FIRMWARE_VERIFIED = {"Some Thing ESP32-C6": "tests/cortexm0/test_blink.py"}')
    root = build_root(tmp_path, catalogue=catalogue, files={"docs/boards.md": (
        "The Some Thing ESP32-C6 runs firmware.\n"
        "The Some Thing ESP32-C6 and the SAMD21 run firmware.\n")})
    found = C.unevidenced_chip_claims(root)
    assert len(found) == 1, found
    assert found[0].startswith("docs/boards.md:2: says SAMD21 runs firmware"), found


def without_the_pilots_entry() -> str:
    """This repository's catalogue with the SparkFun Thing Plus ESP32-C6's
    own `BOARD_FIRMWARE_VERIFIED` entry taken out. It has held one since
    OH-185, so this is how it is again a row whose chip has an entry and
    which has none."""
    text = (REPO / C.CATALOGUE).read_text(encoding="utf-8")
    kept, cut = re.subn(r'^[ \t]*"SparkFun Thing Plus ESP32-C6": "[^"]*",\r?\n', "",
                        text, flags=re.MULTILINE)
    assert cut == 1, "the pilot's own entry is not one line of the register"
    return kept


def test_the_pilot_beside_a_run_claim_fails_and_the_feather_passes(tmp_path):
    """The ticket's two sentences, against this repository's own register and
    manifest: with its own entry, each passes (OH-185); with the SparkFun
    Thing Plus ESP32-C6's taken out, it fails on its chip's entry, and the
    Adafruit Feather ESP32-C6 still passes on its own."""
    files = {"docs/boards.md": ("The SparkFun Thing Plus ESP32-C6 runs firmware.\n"
                                "The Adafruit Feather ESP32-C6 runs firmware.\n")}
    manifest = (REPO / C.MANIFEST).read_text(encoding="utf-8")
    root = build_root(tmp_path / "own", manifest=manifest, files=files,
                      catalogue=(REPO / C.CATALOGUE).read_text(encoding="utf-8"))
    assert C.unevidenced_chip_claims(root) == []
    root = build_root(tmp_path / "cut", manifest=manifest, files=files,
                      catalogue=without_the_pilots_entry())
    found = C.unevidenced_chip_claims(root)
    assert len(found) == 1, found
    assert found[0].startswith(
        "docs/boards.md:1: says SparkFun Thing Plus ESP32-C6 runs firmware"), found


def test_the_pilot_hard_wrapped_across_two_lines_is_still_the_pilot(tmp_path):
    """How this repository's own prose spells it: `SparkFun Thing Plus`, a
    line break, `ESP32-C6`."""
    root = build_root(
        tmp_path,
        catalogue=without_the_pilots_entry(),
        manifest=(REPO / C.MANIFEST).read_text(encoding="utf-8"),
        files={"docs/boards.md": "The SparkFun Thing Plus\nESP32-C6 runs firmware.\n"},
    )
    found = C.unevidenced_chip_claims(root)
    assert len(found) == 1, found
    assert found[0].startswith(
        "docs/boards.md:2: says SparkFun Thing Plus ESP32-C6 runs firmware"), found


def test_a_rows_name_is_read_with_any_whitespace_between_its_words(tmp_path):
    """A line break, `&nbsp;`, two spaces, lower case: each is the row, and
    its chip is not read a second time."""
    for index, text in enumerate((
        "The Some Thing\nESP32-C6 runs firmware.\n",
        "The Some Thing ESP32-C6\nruns firmware.\n",
        "The Some&nbsp;Thing&nbsp;ESP32-C6 runs firmware.\n",
        "The Some  Thing ESP32-C6 runs firmware.\n",
        "the some thing esp32-c6 runs firmware.\n",
    )):
        root = build_root(tmp_path / str(index), files={"docs/boards.md": text})
        found = C.unevidenced_chip_claims(root)
        assert len(found) == 1, (text, found)
        assert "says Some Thing ESP32-C6 runs firmware" in found[0], (text, found)


def test_a_name_on_the_line_above_its_own_claim_is_reported_once(tmp_path):
    for index, text in enumerate((
        "The Some Thing ESP32-C6 runs firmware.\nIt runs firmware all day.\n",
        "The Some Thing ESP32-C6 runs firmware, and\nit runs firmware all day.\n",
        "Done. The Some Thing ESP32-C6 runs firmware, and\nit runs firmware all day.\n",
    )):
        root = build_root(tmp_path / str(index), files={"docs/boards.md": text})
        found = C.unevidenced_chip_claims(root)
        assert len(found) == 1 and found[0].startswith("docs/boards.md:1:"), (text, found)


def test_a_row_named_above_an_unrelated_claim_is_not_that_claim(tmp_path):
    """Review of OH-183: the join reads only the claim's own sentence. A
    sentence that ended on the line above, a blank line, or a table row is
    not part of it, and nor is a line further up than the longest row's
    name has words -- three here."""
    for index, text in enumerate((
        "The Some Thing ESP32-C6 is refused.\nThe Other Board runs firmware.\n",
        'It is "the Some Thing ESP32-C6." The Other\nBoard runs firmware.\n',
        "The Some Thing ESP32-C6 and\n\nthe Other Board run firmware.\n",
        "| Some Thing ESP32-C6 | refused |\n| Other Board | runs firmware |\n",
        "Below, the Some Thing ESP32-C6 and\n| Other Board | runs firmware |\n",
        "The Some Thing ESP32-C6 and\none\ntwo\nthree\nfour runs firmware.\n",
    )):
        root = build_root(tmp_path / str(index), files={"docs/boards.md": text})
        assert C.unevidenced_chip_claims(root) == [], text


def test_a_row_named_anywhere_in_the_claims_sentence_above_it_is_read(tmp_path):
    """Three lines up, a three-line wrap, an HTML line break between words,
    and the pilot a word a line: each is the row, reported once, on the
    claim's line."""
    pilot = {"catalogue": without_the_pilots_entry(),
             "manifest": (REPO / C.MANIFEST).read_text(encoding="utf-8")}
    for index, (text, row, line, real) in enumerate((
        ("The Some Thing ESP32-C6 and\none\ntwo\nthree runs firmware.\n",
         "Some Thing ESP32-C6", 4, False),
        ("Done. The Some\nThing\nESP32-C6 runs firmware.\n", "Some Thing ESP32-C6", 3, False),
        ("The Some<br>Thing<BR />ESP32-C6 runs firmware.\n", "Some Thing ESP32-C6", 1, False),
        ("The SparkFun\nThing\nPlus\nESP32-C6 runs firmware.\n",
         "SparkFun Thing Plus ESP32-C6", 4, True),
    )):
        root = build_root(tmp_path / str(index), files={"docs/boards.md": text},
                          **(pilot if real else {}))
        found = C.unevidenced_chip_claims(root)
        assert len(found) == 1, (text, found)
        assert found[0].startswith(f"docs/boards.md:{line}: says {row} runs firmware"), (
            text, found)


def test_a_row_named_for_a_prefix_of_another_does_not_take_its_match(tmp_path):
    manifest = ('ROWS = (\n    Row(board="Some Thing", chip="ESP32-C6"),\n'
                '    Row(board="Some Thing Pro", chip="ESP32-C6"),\n)\n')
    catalogue = CATALOGUE.replace(
        "BOARD_FIRMWARE_VERIFIED = {}",
        'BOARD_FIRMWARE_VERIFIED = {"Some Thing Pro": "tests/cortexm0/test_blink.py"}')
    root = build_root(tmp_path, catalogue=catalogue, manifest=manifest,
                      files={"docs/boards.md": "The Some Thing Pro runs firmware.\n"})
    assert C.unevidenced_chip_claims(root) == []


def test_a_row_with_its_own_entry_passes_in_any_case(tmp_path):
    catalogue = CATALOGUE.replace(
        "BOARD_FIRMWARE_VERIFIED = {}",
        'BOARD_FIRMWARE_VERIFIED = {"Some Thing ESP32-C6": "tests/cortexm0/test_blink.py"}')
    root = build_root(tmp_path, catalogue=catalogue,
                      files={"docs/boards.md": "the SOME thing esp32-c6 runs firmware.\n"})
    assert C.unevidenced_chip_claims(root) == []


def test_a_paraphrase_of_a_rows_name_is_read_only_as_its_chip(tmp_path):
    """What §8 says is not read: not the manifest's spelling, so not the row."""
    for index, text in enumerate(("The Thing ESP32-C6 runs firmware.\n",
                                  "The Some Thing - ESP32-C6 runs firmware.\n")):
        root = build_root(tmp_path / str(index), catalogue=C6_CATALOGUE,
                          files={"docs/boards.md": text})
        assert C.unevidenced_chip_claims(root) == [], text


def test_a_manifest_that_is_not_there_is_an_error_not_a_pass(tmp_path):
    """With no rows read, every row's name passes on its chip's evidence."""
    root = build_root(tmp_path, manifest=None)
    with pytest.raises(C.ClaimError, match="the manifest is not there"):
        C.unevidenced_chip_claims(root)


def test_a_row_whose_name_is_not_a_literal_is_an_error_not_a_pass(tmp_path):
    root = build_root(tmp_path, manifest='ROWS = (Row(board=NAME, chip="ESP32-C6"),)\n')
    with pytest.raises(C.ClaimError, match='a row with no literal board='):
        C.unevidenced_chip_claims(root)


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
    would fail an honest test for a reason that is about style. The path is
    the one beside the test, which a bare `"blink.bin"` is not (OH-196)."""
    evidence = '''
import pathlib


def test_the_led_actually_blinks(cpu):
    with open(pathlib.Path(__file__).resolve().parent / "blink.bin", "rb") as handle:
        cpu.write_block(0x10000100, handle.read())
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence)
    assert C.evidence_that_never_loads_an_image(root) == []


def test_an_image_of_that_name_elsewhere_under_the_tests_directory_is_not_the_one_named(
        tmp_path):
    """OH-196's review: the named image deleted, check 5 still passed on
    another test's `blink.bin` under the same directory, because it matched
    the name anywhere there. It is the path the test builds that counts."""
    root = build_root(tmp_path, image=False,
                      files={"tests/cortexm0/elsewhere/blink.bin": "not this one"})
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1, found
    assert "no such file exists beside it" in found[0], found
    assert "tests/cortexm0/blink.bin" in found[0], found


def test_an_image_named_only_onto_a_temporary_directory_is_not_beside_the_test(tmp_path):
    """A build's output, joined onto a directory the test makes as it runs,
    is no path the file builds from where it is: naming it shows nothing,
    even with a file of that name beside the test."""
    evidence = '''
import tempfile
import pathlib


def test_the_led_actually_blinks(cpu):
    with tempfile.TemporaryDirectory() as tmp:
        cpu.write_block(0x10000100, (pathlib.Path(tmp) / "blink.bin").read_bytes())
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1, found
    assert "joins none of them onto a path built from its own __file__" in found[0], found


def test_an_image_in_the_fixture_directory_the_test_builds_its_path_to_counts(tmp_path):
    """The shape every entry has: a directory beside the test named once at
    module level, and the image joined onto it through a second name."""
    evidence = '''
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = "blink"
IMAGE = HERE / FIXTURE / "blink.bin"


def test_the_led_actually_blinks(cpu):
    cpu.write_block(0x10000100, IMAGE.read_bytes())
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence, image=False,
                      files={"tests/cortexm0/blink/blink.bin": "an image"})
    assert C.evidence_that_never_loads_an_image(root) == []
    (root / "tests/cortexm0/blink/blink.bin").unlink()
    (root / "tests/cortexm0/blink.bin").write_text("beside, but not where it looks")
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1 and "tests/cortexm0/blink/blink.bin" in found[0], found


def test_an_image_the_test_builds_a_path_to_outside_its_own_directory_is_not_beside_it(
        tmp_path):
    """`.parents[1]` climbs out of the test's directory, to an image some
    other suite owns: a path the file builds, and still not its own."""
    evidence = '''
import pathlib

IMAGE = pathlib.Path(__file__).resolve().parents[1] / "blink.bin"


def test_the_led_actually_blinks(cpu):
    cpu.write_block(0x10000100, IMAGE.read_bytes())
    cpu.step()
'''
    root = build_root(tmp_path, evidence=evidence, image=False,
                      files={"tests/blink.bin": "another suite's"})
    found = C.evidence_that_never_loads_an_image(root)
    assert len(found) == 1 and "it builds" in found[0] and "tests/blink.bin" in found[0], found


# --- 4 and 5 for a board's own entry (rules/board-claims.md §7) ---------------

#: One manifest board with its own entry, naming the chip miniature's test.
BOARD_CATALOGUE = CATALOGUE.replace(
    "BOARD_FIRMWARE_VERIFIED = {}",
    'BOARD_FIRMWARE_VERIFIED = {"Some Feather": "tests/cortexm0/test_blink.py"}',
)

#: `EVIDENCE`, loading the board it is evidence for by name.
BOARD_EVIDENCE = '''
import pathlib

from webui import api

BOARD = "Some Feather"
IMAGE = pathlib.Path(__file__).resolve().parent / "blink.bin"


def test_the_led_actually_blinks():
    with api.load_firmware(BOARD, IMAGE.read_bytes(), base=0) as session:
        for _ in range(20):
            session.step()
'''

#: What check 5 says of a board entry whose test does not load that board.
NEVER_LOADS = ("Some Feather: tests/cortexm0/test_blink.py never loads 'Some Feather', "
               "the board it is evidence for (no load_firmware call whose first "
               "argument is that name, or a name bound to it once, plainly, at "
               "module level)")


def test_a_board_entry_whose_test_loads_it_and_runs_an_image_reports_nothing(tmp_path):
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=BOARD_EVIDENCE)
    assert C.board_register(root) == {"Some Feather": "tests/cortexm0/test_blink.py"}
    assert problems(root) == []


def test_a_board_entry_whose_test_never_loads_the_board_fails(tmp_path):
    """Check 5 alone would take the chip's test for the board's: it loads
    and steps an image. What makes it this board's is that it runs it."""
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE)
    found = C.evidence_that_never_loads_an_image(root)
    assert found == [NEVER_LOADS], found


def test_a_board_entry_whose_test_names_it_and_loads_another_fails(tmp_path):
    """The name in a variable nothing reads, and a XIAO on the load call:
    naming the board is not running it (OH-183)."""
    evidence = BOARD_EVIDENCE.replace("api.load_firmware(BOARD,",
                                      'api.load_firmware("XIAO-ESP32-C6-DIP",')
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert found == [NEVER_LOADS], found


def test_a_board_name_given_to_another_call_or_argument_is_not_the_load(tmp_path):
    evidence = BOARD_EVIDENCE.replace(
        "    with api.load_firmware(BOARD,",
        '    print(BOARD)\n    with api.load_firmware("XIAO-ESP32-C6-DIP", BOARD,')
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert found == [NEVER_LOADS], found


def test_a_board_name_rebound_before_the_load_is_not_the_board(tmp_path):
    evidence = BOARD_EVIDENCE.replace('BOARD = "Some Feather"\n',
                                      'BOARD = "Some Feather"\nBOARD = "XIAO-ESP32-C6-DIP"\n')
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    assert found == [NEVER_LOADS], found


def test_a_board_name_bound_any_way_but_one_plain_module_assignment_is_unresolved(
        tmp_path):
    """Review of OH-183: each of these leaves `BOARD` at the load call not
    provably the board, so the entry fails rather than trusts it."""
    cases = {
        "local rebinding": ("    with api.load_firmware(BOARD,",
                            '    BOARD = "XIAO-ESP32-C6-DIP"\n'
                            "    with api.load_firmware(BOARD,"),
        "parameter default": ("def test_the_led_actually_blinks():",
                              'def test_the_led_actually_blinks(BOARD="XIAO-ESP32-C6-DIP"):'),
        "global rebound in setup_module": (
            "def test_the_led_actually_blinks():",
            "def setup_module():\n    global BOARD\n    BOARD = \"XIAO-ESP32-C6-DIP\"\n\n\n"
            "def test_the_led_actually_blinks():"),
        "tuple unpacking": ('BOARD = "Some Feather"\n', 'BOARD, OTHER = "Some Feather", 1\n'),
        "rebinding under if": ('BOARD = "Some Feather"\n',
                               'BOARD = "Some Feather"\nif IMAGE:\n    BOARD = "XIAO"\n'),
        "rebinding under for": ('BOARD = "Some Feather"\n',
                                'BOARD = "Some Feather"\nfor BOARD in ("XIAO",):\n    pass\n'),
        "import-as": ('BOARD = "Some Feather"\n',
                      'BOARD = "Some Feather"\nfrom os import sep as BOARD\n'),
        "annotated": ('BOARD = "Some Feather"\n', 'BOARD: str = "Some Feather"\n'),
        "import *": ('BOARD = "Some Feather"\n',
                     'BOARD = "Some Feather"\nfrom somewhere import *\n'),
    }
    for index, (label, (old, new)) in enumerate(cases.items()):
        assert BOARD_EVIDENCE.count(old) == 1, label
        root = build_root(tmp_path / str(index), catalogue=BOARD_CATALOGUE,
                          evidence=BOARD_EVIDENCE.replace(old, new))
        found = C.evidence_that_never_loads_an_image(root)
        assert found == [NEVER_LOADS], (label, found)


def test_a_board_name_rebound_as_the_test_runs_is_not_detected(tmp_path):
    """What §7 says is not read, held where it is: the file's text binds
    `BOARD` once, plainly, and each of these rebinds it to a XIAO only when
    the test runs, so each passes."""
    load = "    with api.load_firmware(BOARD,"
    xiao = '"BOARD", "XIAO-ESP32-C6-DIP"'
    cases = {
        "globals()": (load, f'    globals()["BOARD"] = "XIAO-ESP32-C6-DIP"\n{load}'),
        "setattr on the module": (load, f"    setattr(sys.modules[__name__], {xiao})\n{load}"),
        "autouse monkeypatch": (
            "def test_the_led_actually_blinks():",
            "@pytest.fixture(autouse=True)\ndef xiao(monkeypatch):\n"
            f"    monkeypatch.setattr(sys.modules[__name__], {xiao})\n\n\n"
            "def test_the_led_actually_blinks():"),
    }
    for index, (label, (old, new)) in enumerate(cases.items()):
        assert BOARD_EVIDENCE.count(old) == 1, label
        root = build_root(tmp_path / str(index), catalogue=BOARD_CATALOGUE,
                          evidence=BOARD_EVIDENCE.replace(old, new))
        assert problems(root) == [], label


def test_a_binding_in_a_function_not_enclosing_the_load_does_not_unresolve_it(tmp_path):
    evidence = BOARD_EVIDENCE + '\n\ndef helper():\n    BOARD = "XIAO-ESP32-C6-DIP"\n'
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    assert problems(root) == []


def test_a_board_entry_loading_its_board_spelled_out_reports_nothing(tmp_path):
    evidence = BOARD_EVIDENCE.replace("api.load_firmware(BOARD,",
                                      'api.load_firmware("Some Feather",')
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    assert problems(root) == []


def test_a_board_entry_loading_its_board_by_keyword_reports_nothing(tmp_path):
    evidence = BOARD_EVIDENCE.replace("api.load_firmware(BOARD,",
                                      "api.load_firmware(board_name=BOARD, data=")
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    assert problems(root) == []


def test_a_board_entry_naming_a_test_that_is_not_there_fails(tmp_path):
    catalogue = BOARD_CATALOGUE.replace(
        '{"Some Feather": "tests/cortexm0/test_blink.py"}',
        '{"Some Feather": "tests/webui/test_some_feather.py"}',
    )
    root = build_root(tmp_path, catalogue=catalogue)
    found = C.missing_evidence(root)
    assert len(found) == 1 and "tests/webui/test_some_feather.py" in found[0], found


def test_a_board_entry_whose_test_never_steps_the_image_fails(tmp_path):
    evidence = BOARD_EVIDENCE.replace("session.step()", "pass")
    root = build_root(tmp_path, catalogue=BOARD_CATALOGUE, evidence=evidence)
    found = C.evidence_that_never_loads_an_image(root)
    # The chip's entry names the same file, so both say it.
    assert found and all("never executes it" in line for line in found), found
    assert any(line.startswith("Some Feather:") for line in found), found


def test_a_catalogue_with_no_board_register_is_an_error_not_a_pass(tmp_path):
    root = build_root(tmp_path, catalogue=CATALOGUE.replace("BOARD_FIRMWARE_VERIFIED = {}", ""))
    with pytest.raises(C.ClaimError, match="no module-level BOARD_FIRMWARE_VERIFIED"):
        C.missing_evidence(root)


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
    checker = tools / "check_board_claims.py"
    checker.write_bytes((REPO / "tools" / "check_board_claims.py").read_bytes())

    result = subprocess.run(
        [sys.executable, str(checker)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "docs/boards.md:1" in result.stderr
    assert "SAMD21 names no test in FIRMWARE_VERIFIED" in result.stderr
    assert "rules/board-claims.md" in result.stderr


def test_a_temporal_clause_is_not_a_claim():
    """The false positive found the day this rule was armed.

    `webui/boards/samd21.py` explained that `PM_APBBMASK_PORT` is already set
    at power-on -- "so the bit is set before firmware runs" -- and the very
    next sentence named the test that turns that from a claim into a
    measurement. The substring match flagged it anyway, so the check fired on
    exactly the discipline it exists to encourage, while a sloppier author who
    wrote "this board runs firmware" in a docstring would have been caught.

    A temporal clause says *when* something happens. It asserts nothing about
    this repository running anything.
    """
    careful = "set before firmware runs. `tests/cortexm0/test_samd21_blink.py` is what turns"
    assert not C._asserts_a_run(careful), "the sentence this fix exists for"

    for temporal in (
        "the register is live when firmware runs",
        "once firmware runs the bit is already set",
        "nothing is written until firmware runs",
        "PORT is clocked at power-on, after firmware runs it is unchanged",
    ):
        assert not C._asserts_a_run(temporal), temporal

    for claim in (
        "this board runs firmware",
        "firmware runs on this board today",
        "the RP2040 ran real firmware here",
        "firmware-verified",
    ):
        assert C._asserts_a_run(claim), claim
