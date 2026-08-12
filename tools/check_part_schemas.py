#!/usr/bin/env python3
# OpenHardware — validate part wiring schemas.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Checker for the schema requirements in .claude/rules/conformance-fixtures.md.

Loading proves a schema is well formed. This additionally proves its citation
is checkable: a `source` must name a file that exists and a line within it. A
schema whose citation cannot be followed is indistinguishable from one that was
guessed, and a guessed schema wires a circuit wrongly while reporting success.
"""

from __future__ import annotations

import pathlib
import re
import sys

try:
    from webui.parts.schema import SchemaError, load_all_schemas
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from webui.parts.schema import SchemaError, load_all_schemas

SCHEMA_DIR = pathlib.Path("webui/parts/schemas")
_SOURCE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")


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
        if not cited.is_file():
            problems.append(f"{schema.part}: source file {match.group('path')} does not exist")
            continue
        lines = cited.read_text(encoding="utf-8", errors="replace").splitlines()
        if int(match.group("line")) > len(lines):
            problems.append(
                f"{schema.part}: source line {match.group('line')} is past the end of "
                f"{match.group('path')} ({len(lines)} lines)"
            )
    return problems


def main() -> int:
    try:
        problems = find_problems(SCHEMA_DIR, repo_root=pathlib.Path("."))
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
