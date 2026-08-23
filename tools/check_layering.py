#!/usr/bin/env python3
# OpenHardware — enforce that CPU backends do not depend on parts or the UI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/core-interface.md.

Nothing under ``src/sim_backend/`` may include from ``src/parts/`` or from the
lxrad UI layer. A backend that reaches into parts stops being swappable, which
is the property the ``bsim_*`` seam exists to provide.
"""

from __future__ import annotations

import pathlib
import re
import sys


try:
    from webui import picsimlab
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui import picsimlab

#: Exit code meaning "did not run", distinct from 0 (ran, clean) and 1 (found
#: problems). A checker that needs upstream source and cannot find it must be
#: distinguishable from one that checked and was happy; collapsing the two is
#: how a suite goes green while checking nothing.
SKIPPED = 3


def _skip(checker: str) -> int:
    print(
        f"{checker}: SKIPPED - no PICSimLab source checkout. "
        f"Set ${picsimlab.ENV_VAR} or see docs/picsimlab-reference.md.",
        file=sys.stderr,
    )
    return SKIPPED


def backend_dir() -> pathlib.Path:
    """`src/sim_backend` inside the PICSimLab source checkout."""
    return picsimlab.source_root() / "src" / "sim_backend"


SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp"})

_INCLUDE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]')
_FORBIDDEN_SUBSTRING = ("parts/", "lxrad")
_FORBIDDEN_PATTERN = re.compile(r"picsimlab\d")


def _is_forbidden(target: str) -> bool:
    if any(fragment in target for fragment in _FORBIDDEN_SUBSTRING):
        return True
    return bool(_FORBIDDEN_PATTERN.search(target))


def find_violations(
    directory: pathlib.Path | None = None,
) -> list[tuple[pathlib.Path, int, str]]:
    directory = backend_dir() if directory is None else directory
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    ) if directory.is_dir() else []

    if not paths:
        raise ValueError(f"{directory}: no source files to scan")

    violations: list[tuple[pathlib.Path, int, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            match = _INCLUDE.match(line)
            if match and _is_forbidden(match.group(1)):
                violations.append((path, number, match.group(1)))
    return violations


def main() -> int:
    if picsimlab.find_source() is None:
        return _skip("check_layering")
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
            f"rules/core-interface.md",
            file=sys.stderr,
        )
        return 1
    print("check_layering: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
