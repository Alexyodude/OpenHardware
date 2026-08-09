#!/usr/bin/env python3
# OpenHardware — enforce that CPU backends do not depend on parts or the UI.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for .claude/rules/core-interface.md.

Nothing under ``src/sim_backend/`` may include from ``src/parts/`` or from the
lxrad UI layer. A backend that reaches into parts stops being swappable, which
is the property the ``bsim_*`` seam exists to provide.
"""

from __future__ import annotations

import pathlib
import re
import sys

BACKEND_DIR = pathlib.Path("src/sim_backend")
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})

_INCLUDE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]')
_FORBIDDEN_SUBSTRING = ("parts/", "lxrad")
_FORBIDDEN_PATTERN = re.compile(r"picsimlab\d")


def _is_forbidden(target: str) -> bool:
    if any(fragment in target for fragment in _FORBIDDEN_SUBSTRING):
        return True
    return bool(_FORBIDDEN_PATTERN.search(target))


def find_violations(
    backend_dir: pathlib.Path = BACKEND_DIR,
) -> list[tuple[pathlib.Path, int, str]]:
    paths = sorted(
        path
        for path in backend_dir.glob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    ) if backend_dir.is_dir() else []

    if not paths:
        raise ValueError(f"{backend_dir}: no source files to scan")

    violations: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            match = _INCLUDE.match(line)
            if match and _is_forbidden(match.group(1)):
                violations.append((path, number, match.group(1)))
    return violations


def main() -> int:
    try:
        violations = find_violations()
    except ValueError as exc:
        print(f"check_layering: {exc}", file=sys.stderr)
        return 2
    for path, number, target in violations:
        print(f"{path}:{number}: forbidden include {target!r}", file=sys.stderr)
    if violations:
        print(
            f"check_layering: {len(violations)} violation(s) of "
            f".claude/rules/core-interface.md",
            file=sys.stderr,
        )
        return 1
    print("check_layering: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
