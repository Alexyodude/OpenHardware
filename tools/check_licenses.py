#!/usr/bin/env python3
# OpenHardware — verify GPL headers keep the v2-or-later path open.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/gpl-hygiene.md.

Two checks with different scopes:

* v2-only headers are searched for across the **whole tree**, because a single
  such file revokes the GPL-3 path and every Apache-2.0 dependency with it.
* header presence is required only on files **added since fork-point**, because
  upstream's files are upstream's business.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

FORK_POINT = "fork-point"
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp", ".py"})

_GPL = "GNU General Public License"
_VERSION_2 = "version 2"
_LATER = "later version"
_HEAD_BYTES = 4000


def _source_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and ".git" not in path.parts
    )


def find_v2_only(root: pathlib.Path = pathlib.Path(".")) -> list[pathlib.Path]:
    paths = _source_files(root)
    if not paths:
        raise ValueError(f"{root}: no source files to scan")
    offenders = []
    for path in paths:
        head = path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]
        if _GPL in head and _VERSION_2 in head and _LATER not in head:
            offenders.append(path)
    return offenders


def find_missing_headers(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    offenders = []
    for path in paths:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:_HEAD_BYTES]
        if _GPL not in head:
            offenders.append(path)
    return offenders


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
        v2_only = find_v2_only()
        missing = find_missing_headers(_added_since_fork_point())
    except ValueError as exc:
        print(f"check_licenses: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"check_licenses: {exc}", file=sys.stderr)
        return 2

    for path in v2_only:
        print(f"{path}: GPL header is version-2-only", file=sys.stderr)

    for path in missing:
        print(f"{path}: new source file has no GPL header", file=sys.stderr)

    if v2_only:
        print(
            "check_licenses: a v2-only header revokes the GPL-3 path; "
            "every Apache-2.0 dependency must be removed",
            file=sys.stderr,
        )
    if v2_only or missing:
        return 1
    print("check_licenses: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
