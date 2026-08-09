#!/usr/bin/env python3
# OpenHardware — require every modification to an upstream file to be logged.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/upstream-sync.md.

Additive files are unrestricted. A file that existed at ``fork-point`` may only
be modified if ``docs/upstream-deltas.md`` names it in backticks on a ``## ``
heading line. Backticks elsewhere in the ledger — reason prose, intro text,
bullet lists — authorise nothing; only the heading is the log entry.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

FORK_POINT = "fork-point"
LEDGER = pathlib.Path("docs/upstream-deltas.md")

_HEADING_PATH = re.compile(r"^##\s+`([^`]+)`", re.MULTILINE)


def logged_paths(ledger: pathlib.Path = LEDGER) -> set[str]:
    if not ledger.is_file():
        return set()
    text = ledger.read_text(encoding="utf-8")
    return {match.group(1).strip() for match in _HEADING_PATH.finditer(text)}


def unlogged_modifications(
    changed: set[str], at_fork: set[str], logged: set[str]
) -> list[str]:
    if not at_fork:
        raise ValueError(
            f"no files at fork-point: does tag {FORK_POINT!r} exist?"
        )
    return sorted((changed & at_fork) - logged)


def _git(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return {line for line in result.stdout.splitlines() if line}


def main() -> int:
    try:
        offenders = unlogged_modifications(
            changed=_git("diff", "--name-only", FORK_POINT, "HEAD"),
            at_fork=_git("ls-tree", "-r", "--name-only", FORK_POINT),
            logged=logged_paths(),
        )
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"check_deltas: {exc}", file=sys.stderr)
        return 2

    for path in offenders:
        print(
            f"{path}: upstream file modified but absent from {LEDGER}",
            file=sys.stderr,
        )
    if offenders:
        print(
            f"check_deltas: {len(offenders)} unlogged upstream modification(s)",
            file=sys.stderr,
        )
        return 1
    print("check_deltas: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
