# OpenHardware - tests for the upstream patch ledger checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib

from tools.check_deltas import (
    documented_patches,
    orphaned,
    patch_files,
    undocumented,
)

REPO = pathlib.Path(__file__).resolve().parents[2]

LEDGER = """# Patches to PICSimLab

Intro prose mentioning `not-a-heading.patch`, which authorises nothing.

- a bullet naming `also-not-a-heading.patch`

### `0001-real.patch`

Reason: because.

### `0002-another.patch`

Reason: also because.
"""


def _ledger(tmp_path, text: str) -> pathlib.Path:
    path = tmp_path / "README.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- parsing the ledger ------------------------------------------------------


def test_heading_names_are_parsed(tmp_path):
    assert documented_patches(_ledger(tmp_path, LEDGER)) == {
        "0001-real.patch",
        "0002-another.patch",
    }


def test_backticks_outside_headings_authorise_nothing(tmp_path):
    """Prose and bullets are not entries. Carried over from the fork-era rule."""
    names = documented_patches(_ledger(tmp_path, LEDGER))
    assert "not-a-heading.patch" not in names
    assert "also-not-a-heading.patch" not in names


def test_a_missing_ledger_yields_no_entries(tmp_path):
    assert documented_patches(tmp_path / "nope.md") == set()


# --- finding the patches -----------------------------------------------------


def test_patch_files_are_found(tmp_path):
    (tmp_path / "0001-real.patch").write_text("--- a/x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a patch\n", encoding="utf-8")
    assert patch_files(tmp_path) == {"0001-real.patch"}


def test_a_missing_patch_directory_is_not_an_error(tmp_path):
    """Zero patches is the goal state, not a failure."""
    assert patch_files(tmp_path / "nope") == set()


# --- the two directions ------------------------------------------------------


def test_an_undocumented_patch_is_flagged():
    assert undocumented({"a.patch", "b.patch"}, {"a.patch"}) == ["b.patch"]


def test_an_orphaned_ledger_entry_is_flagged():
    """Prose describing a patch that no longer exists reads as current."""
    assert orphaned({"a.patch"}, {"a.patch", "gone.patch"}) == ["gone.patch"]


def test_agreement_yields_nothing():
    both = {"a.patch", "b.patch"}
    assert undocumented(both, both) == []
    assert orphaned(both, both) == []


def test_no_patches_and_no_entries_agree():
    assert undocumented(set(), set()) == []
    assert orphaned(set(), set()) == []


# --- the repository itself ---------------------------------------------------


def test_this_repositorys_patches_are_all_documented():
    present = patch_files(REPO / "patches")
    documented = documented_patches(REPO / "patches" / "README.md")
    assert undocumented(present, documented) == []
    assert orphaned(present, documented) == []


def test_the_one_known_patch_is_present():
    """Pins the ARCH_X86 patch. If it is retired upstream, delete this too."""
    assert "0001-board-arch-x86.patch" in patch_files(REPO / "patches")
