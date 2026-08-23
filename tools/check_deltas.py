#!/usr/bin/env python3
# OpenHardware - require every change to upstream to be a documented patch.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/upstream-sync.md.

The rule has not changed: **no change to PICSimLab goes unrecorded.** The
mechanism has, because the thing it watches has.

While this was a fork, a change to upstream meant a modified file sitting in
this tree, and the checker intersected `git diff fork-point HEAD` with
`git ls-tree fork-point`. Both halves of that are gone: there is no upstream
file here to modify, and no fork-point tag to diff against.

A change to upstream is now a **patch file**, and the ledger is
`patches/README.md`. Every `patches/*.patch` must be named in a `### ` heading
there, and every heading must name a patch that exists. Backticks anywhere
else -- reason prose, intro text, bullet lists -- authorise nothing; only the
heading is the entry. That much carries over verbatim.

## Why this is a stronger check than the one it replaces

`docs/known-issues.md` 1.8 recorded that the old premise -- everything in
`fork-point..HEAD` is ours -- is false for any tree that also contains
upstream commits made after the tag. It fired the first time CI ever ran, on
upstream's own eight files, and the note warned the same eight would return
the day the fork merged upstream for real.

A patch file cannot have that bug. It is ours by construction: nobody else
writes into `patches/`, and no upstream merge can put anything there.

## Both directions

An undocumented patch is the obvious failure. An orphaned heading -- prose
describing a patch that no longer exists -- is the quieter one, and it is
worse in the way stale documentation is always worse than missing
documentation: it reads as current.
"""

from __future__ import annotations

import pathlib
import re
import sys

PATCH_DIR = pathlib.Path("patches")
LEDGER_NAME = "README.md"

_HEADING_NAME = re.compile(r"^###\s+`([^`]+)`", re.MULTILINE)


class DeltaError(Exception):
    """The patch directory and its ledger disagree about what exists."""


def documented_patches(ledger: pathlib.Path) -> set[str]:
    """Patch filenames named in `### ` headings of the ledger."""
    if not ledger.is_file():
        return set()
    text = ledger.read_text(encoding="utf-8")
    return {match.group(1).strip() for match in _HEADING_NAME.finditer(text)}


def patch_files(directory: pathlib.Path = PATCH_DIR) -> set[str]:
    """Every `*.patch` in the directory, by filename."""
    if not directory.is_dir():
        return set()
    return {path.name for path in directory.glob("*.patch")}


def undocumented(present: set[str], documented: set[str]) -> list[str]:
    """Patches with no ledger entry."""
    return sorted(present - documented)


def orphaned(present: set[str], documented: set[str]) -> list[str]:
    """Ledger entries naming a patch that is not there."""
    return sorted(documented - present)


def main() -> int:
    present = patch_files()
    ledger = PATCH_DIR / LEDGER_NAME

    if present and not ledger.is_file():
        print(
            f"check_deltas: {len(present)} patch(es) but no {ledger}",
            file=sys.stderr,
        )
        return 2

    documented = documented_patches(ledger)
    missing = undocumented(present, documented)
    stale = orphaned(present, documented)

    for name in missing:
        print(
            f"patches/{name}: applied to upstream but absent from {ledger}. "
            f"Add a '### `{name}`' section saying what it changes and why.",
            file=sys.stderr,
        )
    for name in stale:
        print(
            f"{ledger}: documents `{name}`, which does not exist. "
            f"Remove the section, or restore the patch.",
            file=sys.stderr,
        )

    if missing or stale:
        print(
            f"check_deltas: {len(missing) + len(stale)} patch/ledger "
            f"disagreement(s), per rules/upstream-sync.md",
            file=sys.stderr,
        )
        return 1

    if not present:
        # The goal state, and worth saying out loud rather than printing a
        # bare OK that looks identical to "checked something".
        print("check_deltas: OK (no patches; upstream is unmodified)")
        return 0

    print(f"check_deltas: OK ({len(present)} patch(es), all documented)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
