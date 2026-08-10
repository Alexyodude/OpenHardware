#!/usr/bin/env python3
# OpenHardware — derive the repository inventory from the repository itself.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Report what this fork contains: tests, rule mechanisms, files, ledger cells.

The numbers are **computed, never claimed**. A hand-maintained inventory saying
"65 tests" is wrong the moment someone adds a test, and this repository has
already caught that failure twice in its own rule documents — `gpl-hygiene.md`
and `upstream-sync.md` each drifted from the code they described inside a single
session. An inventory is exactly the kind of document that rots fastest, so
this one is generated on demand instead of written down.

Four collectors, one per thing worth counting:

* `collect_tests`   — parses each test file with `ast`
* `collect_mechanisms` — reads `.claude/rules/*.md` frontmatter
* `collect_files`   — asks git what changed since the `fork-point` tag
* `collect_ledgers` — parses every ledger under `docs/features/`

Each raises rather than returning an empty result. A report that renders
cheerfully with nothing in it is indistinguishable from a report of a healthy
repository, which is the vacuous green this project exists to prevent.

**Known model limit:** `collect_tests` counts `def test_*` via `ast`, so it
counts a parametrised test once where pytest counts it many times. No test here
is parametrised today, and `test_ast_count_matches_pytest_collection` fails
loudly if that ever stops being true — the divergence is designed to be noisy
rather than silent.
"""

from __future__ import annotations

import argparse
import ast
import collections
import pathlib
import subprocess
import sys

try:
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    # Unlike the four checkers, this tool imports its siblings. Running it as
    # `python tools/inventory.py` puts `tools/` on sys.path rather than the repo
    # root, so the package is not importable. Rather than force
    # `python -m tools.inventory` and break the `python tools/<name>.py`
    # convention CLAUDE.md documents for every other tool, put the repo root on
    # the path and retry. Both invocations then work.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools.ledger import LedgerError, parse_ledger
    from tools.rules_meta import RuleParseError, load_rules

TESTS_DIR = pathlib.Path("tests/rules")
RULES_DIR = pathlib.Path(".claude/rules")
FEATURES_DIR = pathlib.Path("docs/features")
FORK_POINT = "fork-point"

STATUS_LABELS = {"A": "added", "M": "modified", "D": "deleted"}


class InventoryError(Exception):
    """A source of inventory data is missing, empty, or unreadable."""


def collect_tests(tests_dir: pathlib.Path = TESTS_DIR) -> dict[str, int]:
    """Map each test file to the number of `def test_*` functions it declares."""
    if not tests_dir.is_dir():
        raise InventoryError(f"{tests_dir}: test directory does not exist")
    paths = sorted(tests_dir.glob("test_*.py"))
    if not paths:
        raise InventoryError(f"{tests_dir}: contains no test files")

    counts: dict[str, int] = {}
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise InventoryError(f"{path}: does not parse: {exc}") from exc
        counts[path.as_posix()] = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return counts


def collect_mechanisms(
    rules_dir: pathlib.Path = RULES_DIR,
) -> list[tuple[str, str, bool, str | None]]:
    """Every declared mechanism as (rule, tier, armed, checker)."""
    try:
        rules = load_rules(rules_dir)
    except RuleParseError as exc:
        # Surface every failure as InventoryError so a caller catches one type.
        # main() catches only InventoryError, so letting this through would
        # print a traceback instead of a diagnostic.
        raise InventoryError(f"{rules_dir}: {exc}") from exc

    rows = [
        (rule.name, mech.tier, mech.armed, mech.checker)
        for rule in rules
        for mech in rule.mechanisms
    ]
    if not rows:
        raise InventoryError(f"{rules_dir}: rules declare no mechanisms at all")
    return rows


def collect_files(fork_point: str = FORK_POINT) -> dict[str, list[str]]:
    """Files changed since the fork point, grouped by git status letter."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", fork_point, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise InventoryError(f"git diff against {fork_point!r} failed: {exc}") from exc

    grouped: dict[str, list[str]] = collections.defaultdict(list)
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        grouped[status.strip()[:1]].append(path.strip())

    if not grouped:
        raise InventoryError(
            f"no files changed since {fork_point!r}; either the tag is wrong or "
            f"this is not the fork"
        )
    return dict(grouped)


def collect_ledgers(
    features_dir: pathlib.Path = FEATURES_DIR,
) -> dict[str, collections.Counter]:
    """Cell counts per status, for every ledger under docs/features/."""
    if not features_dir.is_dir():
        raise InventoryError(f"{features_dir}: features directory does not exist")
    paths = sorted(features_dir.glob("*.md"))
    if not paths:
        raise InventoryError(f"{features_dir}: contains no ledgers")

    try:
        return {
            path.as_posix(): collections.Counter(
                cell.status for cell in parse_ledger(path)
            )
            for path in paths
        }
    except LedgerError as exc:
        raise InventoryError(f"{features_dir}: {exc}") from exc


def _head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def render_text() -> str:
    tests = collect_tests()
    mechanisms = collect_mechanisms()
    files = collect_files()
    ledgers = collect_ledgers()

    armed = sum(1 for _, _, is_armed, _ in mechanisms if is_armed)
    lines = [f"OpenHardware inventory at {_head()}", ""]

    lines.append(f"TESTS — {sum(tests.values())} across {len(tests)} files")
    for path, count in sorted(tests.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {count:>4}  {path}")

    lines.append("")
    lines.append(f"MECHANISMS — {armed} armed, {len(mechanisms) - armed} unarmed")
    for rule, tier, is_armed, checker in mechanisms:
        lines.append(
            f"  {'ARMED  ' if is_armed else 'unarmed'}  {tier:<16}  {rule}  ->  {checker}"
        )

    lines.append("")
    total_files = sum(len(v) for v in files.values())
    lines.append(f"FILES since {FORK_POINT} — {total_files}")
    for status, paths in sorted(files.items()):
        lines.append(f"  {len(paths):>4}  {STATUS_LABELS.get(status, status)}")

    lines.append("")
    lines.append(f"LEDGERS — {len(ledgers)}")
    for path, counter in ledgers.items():
        breakdown = ", ".join(f"{n} {s}" for s, n in sorted(counter.items()))
        lines.append(f"  {sum(counter.values()):>4}  {path}  ({breakdown})")

    return "\n".join(lines)


def render_markdown() -> str:
    tests = collect_tests()
    mechanisms = collect_mechanisms()
    files = collect_files()
    ledgers = collect_ledgers()

    armed = sum(1 for _, _, is_armed, _ in mechanisms if is_armed)
    out = [
        "# OpenHardware inventory",
        "",
        f"Generated from `{_head()}` by `tools/inventory.py`. Every number here is "
        f"computed from the repository; do not edit this by hand.",
        "",
        f"## Tests — {sum(tests.values())}",
        "",
        "| file | tests |",
        "|---|---|",
    ]
    out += [
        f"| `{path}` | {count} |"
        for path, count in sorted(tests.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    out += [
        "",
        f"## Mechanisms — {armed} armed, {len(mechanisms) - armed} unarmed",
        "",
        "| rule | tier | armed | checker |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {rule} | `{tier}` | {'yes' if is_armed else 'no'} | `{checker}` |"
        for rule, tier, is_armed, checker in mechanisms
    ]

    out += [
        "",
        f"## Files since `{FORK_POINT}` — {sum(len(v) for v in files.values())}",
        "",
        "| status | count |",
        "|---|---|",
    ]
    out += [
        f"| {STATUS_LABELS.get(status, status)} | {len(paths)} |"
        for status, paths in sorted(files.items())
    ]

    out += ["", f"## Ledgers — {len(ledgers)}", "", "| ledger | cells | breakdown |", "|---|---|---|"]
    out += [
        f"| `{path}` | {sum(c.values())} | {', '.join(f'{n} {s}' for s, n in sorted(c.items()))} |"
        for path, c in ledgers.items()
    ]

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--markdown", action="store_true", help="emit markdown instead of plain text"
    )
    args = parser.parse_args()
    try:
        print(render_markdown() if args.markdown else render_text())
    except InventoryError as exc:
        print(f"inventory: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
