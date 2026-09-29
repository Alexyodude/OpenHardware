# OpenHardware - tests for the claims checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for tools/check_facts.py.

The thing worth testing here is not that the checker passes -- it does, and
that is what makes it dangerous. Every test below is written so that it fails
when the checker becomes *unable* to fail: a pattern that matches nothing, a
document that disappears, an anchor that never goes stale.

No `@pytest.mark.parametrize` anywhere, deliberately: `tools/inventory.py`
counts `def test_*` with `ast`, and a parametrised test would count once here
and many times in pytest. Loops inside one test instead. See CLAUDE.md.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tools import check_facts
from tools.stale import Store, key_of

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_checker_passes_against_the_tree_as_committed():
    """The baseline. Every other test here is about it being able to fail."""
    assert check_facts.run_facts() == []


def test_every_watched_document_exists():
    """A watch list that silently stops watching is the failure mode.

    `run_facts` reports a missing document rather than skipping it, so this
    also pins that the paths in the table are real paths.
    """
    for _, doc, _, _ in check_facts.FACTS:
        assert (ROOT / doc).is_file(), f"{doc} is watched but does not exist"


def test_a_missing_document_is_a_finding_not_a_skip(tmp_path):
    """The trap: `if not path.exists(): continue` switches a checker off."""
    complaints = check_facts.run_facts(tmp_path)
    assert complaints, "an empty tree produced no complaints at all"
    for _, doc, _, _ in check_facts.FACTS:
        assert any(doc in line and "LISTED BUT MISSING" in line
                   for line in complaints), f"{doc} vanished without a word"


def test_every_row_complains_when_its_sentence_is_gone():
    """A pattern that matches nothing must say so, not report clean.

    Feeds each check a document it cannot find its claim in. Zero results is a
    hypothesis, not a result -- so the checks are run against known-empty text
    exactly as `traps.md` prescribes.
    """
    for ident, _, _, check in check_facts.FACTS:
        complaints = check("nothing in here says anything about this tree.\n")
        assert complaints, f"{ident} found nothing to check and called it a pass"
        assert any("can no longer be found" in line or "LISTED" in line
                   for line in complaints), \
            f"{ident} complained, but not that its pattern is dead: {complaints}"


def test_word_numerals_this_repository_actually_writes():
    """The prose says 'twenty-five', not 25. A reader that cannot parse the
    repository's own register would silently never match."""
    cases = {
        "six": 6, "Seven": 7, "eleven": 11, "twelve": 12, "thirteen": 13,
        "twenty-five": 25, "twenty-six": 26, "forty-three": 43, "12": 12,
        "26.": 26,
    }
    for token, expected in cases.items():
        assert check_facts.as_number(token) == expected, token
    for bad in ("several", "a few", "", "twenty-twenty"):
        with pytest.raises(ValueError):
            check_facts.as_number(bad)


def test_the_claude_md_precommit_block_names_every_armed_checker():
    """The defect this row was written for: check_ticket_claims.py was armed,
    ran in CI, and was missing from the block a human is told to run."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert check_facts.precommit_checkers(text) == []

    without = text.replace("python tools/check_ticket_claims.py\r\n", "")
    without = without.replace("python tools/check_ticket_claims.py\n", "")
    complaints = check_facts.precommit_checkers(without)
    assert any("check_ticket_claims" in line for line in complaints)

    extra = text.replace("python tools/check_licenses.py",
                         "python tools/check_licenses.py\npython tools/check_retired.py")
    assert any("check_retired" in line and "no armed rule declares" in line
               for line in check_facts.precommit_checkers(extra))


def test_the_board_split_points_at_twins_and_reads_the_two_tables(monkeypatch):
    """The model paragraph counts nothing now; TWINS does.

    What stays watched is the pointer, and the two structural errors a
    hand-written total used to expose: a board named in the model tables that
    no longer exists, and a board named in both. Each is broken once here.
    """
    models, composed = check_facts._model_and_composed_boards()
    boards = check_facts._catalogue_boards()
    assert not (models & composed), "MODELS and COMPOSED overlap"
    assert (models | composed) <= boards, "a model names a board that is gone"

    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert check_facts.board_model_split(text) == []

    unpointed = text.replace("python tools/inventory.py      # TWINS", "# TWINS")
    assert unpointed != text
    assert any("pattern is dead" in line
               for line in check_facts.board_model_split(unpointed))

    some = sorted(composed)[0]
    monkeypatch.setattr(check_facts, "_model_and_composed_boards",
                        lambda: (models | {"XIAO-GONE"}, composed))
    assert any("'XIAO-GONE'" in line
               for line in check_facts.board_model_split(text))
    monkeypatch.setattr(check_facts, "_model_and_composed_boards",
                        lambda: (models | {some}, composed))
    assert any("overlap" in line
               for line in check_facts.board_model_split(text))


def test_the_kicad_url_check_counts_tracked_files_not_mentions():
    """CLAUDE.md claims one home for that URL. The check must read the tree,
    and must fail when a second home appears -- see DUPLICATION.md."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert check_facts.kicad_url_lives_once(text) == []
    assert check_facts.kicad_url_lives_once("no such claim here") != []


def test_an_anchored_claim_goes_stale_when_its_function_moves(tmp_path):
    """Anchoring is about belief, not generation: the stored hash is the
    source as it was when a human last confirmed the claim about it."""
    store = Store(tmp_path / "store.json")
    before = "def f():\n    return 1\n"
    store.confirm("claim", before, file="x.py")
    assert not store.stale("claim", before)
    assert store.stale("claim", "def f():\n    return 2\n")

    reflowed = "def f():\n        return 1\n"
    assert not store.stale("claim", reflowed), \
        "whitespace-only reflow read as an edit"


def test_every_anchor_names_a_function_that_exists_and_is_confirmed():
    """An anchor pointing at a renamed function would raise rather than pass,
    and an unconfirmed one reports without failing. Both are checked here so
    the committed store cannot quietly empty out."""
    store = Store(check_facts.STORE_PATH)
    for ident, file, name in check_facts.ANCHORS:
        source = check_facts.function_source(ROOT / file, name)
        assert not store.unanchored(ident), f"{ident} was never confirmed"
        assert not store.stale(ident, source), \
            f"{ident} is stale: re-read both sides, then --confirm it"
        assert store.data[ident]["hash"] == key_of(source)


def test_the_store_holds_nothing_the_anchors_table_does_not_name():
    """A store entry with no row is an anchor nobody checks any more."""
    stored = set(json.loads(
        check_facts.STORE_PATH.read_text(encoding="utf-8")))
    assert stored == {ident for ident, _, _ in check_facts.ANCHORS}


def test_confirm_takes_one_id_and_refuses_an_unknown_one():
    """There is deliberately no --confirm-all: clearing a stale flag without
    looking is the one action that must stay expensive."""
    assert check_facts.confirm("no-such-anchor") == 2
    assert check_facts.main(["--confirm"]) == 2
    assert check_facts.main(["--nonsense"]) == 2
