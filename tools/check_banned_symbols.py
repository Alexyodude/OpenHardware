#!/usr/bin/env python3
# OpenHardware — ban nondeterministic calls from new simulation code.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/determinism.md.

Scoped to the C/C++ this repository tracks. It used to be scoped to files
added since ``fork-point``, because upstream's own tree was here and its use of
these symbols was upstream's business. With PICSimLab consumed as an external
install there is no upstream source in this tree, so every C/C++ file here is
ours by definition and the scoping question disappears.

**There is no C/C++ here yet** -- the x86-16 core is planned, not written. The
checker therefore reports the number of files it scanned, so a zero is stated
rather than implied. A bare "OK" over an empty set is indistinguishable from a
real pass, which is the vacuous green this repository exists to prevent.

Comment stripping is a small C-style scan (``//`` to end of line, ``/* ... */``
possibly spanning several lines), not a full C parser: a ``/*`` inside a
string literal is not recognised as a string and would incorrectly be treated
as opening a comment. That is out of scope here.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})
BANNED = ("rand", "time", "clock")

_CALL = re.compile(r"(?<![\w])(" + "|".join(BANNED) + r")\s*\(")


def _strip_comments(lines: list[str]) -> list[str]:
    """Return `lines` with `//` and `/* ... */` comment text removed.

    A boolean carries "currently inside a block comment" from line to line,
    so a comment opened on one line and closed on a later one strips
    everything in between, and code following the close is still scanned —
    including code on the very line where the block comment closes.
    """
    stripped: list[str] = []
    in_block = False
    for line in lines:
        out: list[str] = []
        i = 0
        n = len(line)
        while i < n:
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    i = n
                else:
                    i = end + 2
                    in_block = False
                continue
            line_comment = line.find("//", i)
            block_comment = line.find("/*", i)
            if line_comment == -1 and block_comment == -1:
                out.append(line[i:])
                i = n
            elif block_comment == -1 or (
                line_comment != -1 and line_comment < block_comment
            ):
                out.append(line[i:line_comment])
                i = n
            else:
                out.append(line[i:block_comment])
                i = block_comment + 2
                in_block = True
        stripped.append("".join(out))
    return stripped


def find_banned(
    paths: list[pathlib.Path],
) -> list[tuple[pathlib.Path, int, str]]:
    hits: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        code_lines = _strip_comments(text.splitlines())
        for number, line in enumerate(code_lines, start=1):
            match = _CALL.search(line)
            if match:
                hits.append((path, number, match.group(1)))
    return hits


def _tracked_sources() -> list[pathlib.Path]:
    """Every C/C++ file git tracks here. See the module docstring on scope."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        path
        for path in (pathlib.Path(line) for line in result.stdout.split() if line)
        if path.suffix in SOURCE_SUFFIXES
    ]


def main() -> int:
    try:
        sources = _tracked_sources()
        hits = find_banned(sources)
    except subprocess.CalledProcessError as exc:
        print(f"check_banned_symbols: {exc}", file=sys.stderr)
        return 2
    for path, number, symbol in hits:
        print(f"{path}:{number}: nondeterministic call {symbol}()", file=sys.stderr)
    if hits:
        print(
            f"check_banned_symbols: {len(hits)} violation(s) of "
            f"rules/determinism.md",
            file=sys.stderr,
        )
        return 1
    if not sources:
        print("check_banned_symbols: OK (0 C/C++ files tracked; none written yet)")
    else:
        print(f"check_banned_symbols: OK ({len(sources)} C/C++ file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
