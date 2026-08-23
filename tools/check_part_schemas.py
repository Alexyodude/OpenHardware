#!/usr/bin/env python3
# OpenHardware — validate part wiring schemas.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for the schema requirements in rules/conformance-fixtures.md.

Loading proves a schema is well formed. This additionally proves its citation
is checkable: a `source` must name a file that exists and a line within it. A
schema whose citation cannot be followed is indistinguishable from one that was
guessed, and a guessed schema wires a circuit wrongly while reporting success.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

try:
    from webui.parts.schema import SchemaError, load_all_schemas
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui.parts.schema import SchemaError, load_all_schemas

try:
    from webui import picsimlab
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui import picsimlab

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[1] / "webui" / "parts" / "schemas"

#: See tools/check_layering.py for why a skip needs its own exit code.
SKIPPED = 3
_SOURCE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")


def _spelled_exactly(repo_root: pathlib.Path, relative: str) -> bool:
    """True only if every component of `relative` matches its on-disk spelling.

    `Path.is_file()` answers a different question on different filesystems.
    Windows and macOS resolve case-insensitively, so a citation of
    `src/parts/output_leds.cc` opened `output_LEDs.cc` on this fork's
    development machine and the checker reported OK for six days; Linux CI
    rejected it on the first run it ever performed.

    A citation exists to be followed by a person, and `git` stores the name
    with its case, so the spelling is part of the citation. Listing each parent
    and requiring an exact match makes the checker give the same answer
    everywhere rather than the answer its host filesystem prefers.
    """
    current = repo_root
    for component in pathlib.PurePosixPath(relative).parts:
        try:
            names = os.listdir(current)
        except (NotADirectoryError, FileNotFoundError, PermissionError):
            return False
        if component not in names:
            return False
        current = current / component
    return current.is_file()


def find_problems(
    directory: pathlib.Path = SCHEMA_DIR, repo_root: pathlib.Path | None = None
) -> list[str]:
    """Return every problem found. Raises if there is nothing to check."""
    schemas = load_all_schemas(directory)

    problems: list[str] = []
    for schema in schemas.values():
        match = _SOURCE.match(schema.source)
        if not match:
            problems.append(
                f"{schema.part}: source {schema.source!r} has no line number"
            )
            continue
        if repo_root is None:
            continue
        cited = repo_root / match.group("path")
        if not _spelled_exactly(repo_root, match.group("path")):
            # Name the two cases apart: a typo and a case slip need different
            # fixes, and on Windows the second one looks like nothing at all.
            detail = (
                "does not match the on-disk spelling"
                if cited.is_file()
                else "does not exist"
            )
            problems.append(f"{schema.part}: source file {match.group('path')} {detail}")
            continue
        lines = cited.read_text(encoding="utf-8", errors="replace").splitlines()
        if int(match.group("line")) > len(lines):
            problems.append(
                f"{schema.part}: source line {match.group('line')} is past the end of "
                f"{match.group('path')} ({len(lines)} lines)"
            )
    return problems


def main() -> int:
    # `repo_root` here means the root the citations are relative to, and every
    # citation names a path inside PICSimLab (`src/parts/output_LEDs.cc:220`),
    # not inside this repository. Since the split those are different trees.
    source = picsimlab.find_source()
    if source is None:
        print(
            "check_part_schemas: SKIPPED - no PICSimLab source checkout, so "
            f"schema citations cannot be followed. Set ${picsimlab.ENV_VAR} "
            "or see docs/picsimlab-reference.md.",
            file=sys.stderr,
        )
        return SKIPPED
    try:
        problems = find_problems(SCHEMA_DIR, repo_root=source)
    except SchemaError as exc:
        print(f"check_part_schemas: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_part_schemas: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("check_part_schemas: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
