#!/usr/bin/env python3
# OpenHardware — ban nondeterministic calls from new simulation code.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/determinism.md.

Scoped to files added since ``fork-point``. Upstream's existing use of these
symbols is upstream's business; a delta would be needed to change it, and this
checker is not the place to force one.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

FORK_POINT = "fork-point"
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})
BANNED = ("rand", "time", "clock")

_CALL = re.compile(r"(?<![\w])(" + "|".join(BANNED) + r")\s*\(")
_COMMENT = re.compile(r"^\s*(//|/\*|\*)")


def find_banned(
    paths: list[pathlib.Path],
) -> list[tuple[pathlib.Path, int, str]]:
    hits: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if _COMMENT.match(line):
                continue
            match = _CALL.search(line)
            if match:
                hits.append((path, number, match.group(1)))
    return hits


def _added_since_fork_point() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", FORK_POINT, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [pathlib.Path(line) for line in result.stdout.split() if line]


def main() -> int:
    try:
        hits = find_banned(_added_since_fork_point())
    except subprocess.CalledProcessError as exc:
        print(f"check_banned_symbols: {exc}", file=sys.stderr)
        return 2
    for path, number, symbol in hits:
        print(f"{path}:{number}: nondeterministic call {symbol}()", file=sys.stderr)
    if hits:
        print(
            f"check_banned_symbols: {len(hits)} violation(s) of "
            f".claude/rules/determinism.md",
            file=sys.stderr,
        )
        return 1
    print("check_banned_symbols: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
