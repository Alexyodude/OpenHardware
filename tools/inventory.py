#!/usr/bin/env python3
# OpenHardware — derive the repository inventory from the repository itself.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Report what this repository contains: tests, mechanisms, files, ledger cells.

The numbers are **computed, never claimed**. A hand-maintained inventory saying
"65 tests" is wrong the moment someone adds a test, and this repository has
already caught that failure twice in its own rule documents — `gpl-hygiene.md`
and `upstream-sync.md` each drifted from the code they described inside a single
session. An inventory is exactly the kind of document that rots fastest, so
this one is generated on demand instead of written down.

Four collectors, one per thing worth counting:

* `collect_tests`   — parses each test file with `ast`
* `collect_mechanisms` — reads `.claude/rules/*.md` frontmatter
* `collect_files`   — asks git what this repository tracks
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
import typing

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
#: Top-level directories, in the order the report lists them. Anything
#: outside them lands in `other`, which is deliberately visible: the
#: separation from upstream is only kept by noticing when something
#: unexpected appears at the root.
KNOWN_AREAS = ("webui", "tools", "tests", "docs", "patches", ".claude", ".github")


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


def collect_files(repo: pathlib.Path | None = None) -> dict[str, list[str]]:
    """Every tracked file, grouped by top-level directory.

    This used to ask `git diff fork-point HEAD` — what did we change
    relative to upstream. That question died with the fork: PICSimLab is no
    longer in this tree, so there is no fork point to diff against and
    **every tracked file is ours**. Asking git what it tracks is the same
    question more directly put, and it needs no tag pushed to a remote for
    CI to work — which is what kept `.github/workflows/rules.yml` from
    ever running.

    Grouping is by area rather than git status letter for the same reason:
    with nothing inherited, `added` against `modified` says nothing, while
    `webui 34, tools 13` says what the repository is made of.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        NotADirectoryError,
    ) as exc:
        raise InventoryError(f"git ls-files failed: {exc}") from exc

    grouped: dict[str, list[str]] = collections.defaultdict(list)
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        head = path.split("/")[0]
        grouped[head if head in KNOWN_AREAS else "other"].append(path)

    if not grouped:
        raise InventoryError("git tracks no files here; this is not the repository")
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


class _Inventory(typing.NamedTuple):
    tests: dict[str, int]
    mechanisms: list[tuple[str, str, bool, str | None]]
    files: dict[str, list[str]]
    ledgers: dict[str, collections.Counter]


def _gather() -> _Inventory:
    """Collect every section once, so the two renderers cannot disagree."""
    return _Inventory(
        collect_tests(), collect_mechanisms(), collect_files(), collect_ledgers()
    )


def _armed(mechanisms: list[tuple[str, str, bool, str | None]]) -> int:
    return sum(1 for _, _, is_armed, _ in mechanisms if is_armed)


def _tests_by_size(tests: dict[str, int]) -> list[tuple[str, int]]:
    """Largest file first, then alphabetical — one ordering for both renderers."""
    return sorted(tests.items(), key=lambda kv: (-kv[1], kv[0]))


def _breakdown(counter: collections.Counter) -> str:
    return ", ".join(f"{count} {status}" for status, count in sorted(counter.items()))


def render_text() -> str:
    inv = _gather()
    armed = _armed(inv.mechanisms)
    lines = [f"OpenHardware inventory at {_head()}", ""]

    lines.append(f"TESTS — {sum(inv.tests.values())} across {len(inv.tests)} files")
    for path, count in _tests_by_size(inv.tests):
        lines.append(f"  {count:>4}  {path}")

    lines.append("")
    lines.append(f"MECHANISMS — {armed} armed, {len(inv.mechanisms) - armed} unarmed")
    for rule, tier, is_armed, checker in inv.mechanisms:
        lines.append(
            f"  {'ARMED  ' if is_armed else 'unarmed'}  {tier:<16}  {rule}  ->  {checker}"
        )

    lines.append("")
    lines.append(
        f"FILES tracked — {sum(len(p) for p in inv.files.values())}"
    )
    for area, paths in sorted(inv.files.items()):
        lines.append(f"  {len(paths):>4}  {area}")

    lines.append("")
    lines.append(f"LEDGERS — {len(inv.ledgers)}")
    for path, counter in inv.ledgers.items():
        lines.append(f"  {sum(counter.values()):>4}  {path}  ({_breakdown(counter)})")

    return "\n".join(lines)


def render_markdown() -> str:
    inv = _gather()
    armed = _armed(inv.mechanisms)

    out = [
        "# OpenHardware inventory",
        "",
        f"Generated from `{_head()}` by `tools/inventory.py`. Every number here is "
        "computed from the repository; do not edit this by hand.",
        "",
        f"## Tests — {sum(inv.tests.values())}",
        "",
        "| file | tests |",
        "|---|---|",
    ]
    out += [f"| `{path}` | {count} |" for path, count in _tests_by_size(inv.tests)]

    out += [
        "",
        f"## Mechanisms — {armed} armed, {len(inv.mechanisms) - armed} unarmed",
        "",
        "| rule | tier | armed | checker |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {rule} | `{tier}` | {'yes' if is_armed else 'no'} | `{checker}` |"
        for rule, tier, is_armed, checker in inv.mechanisms
    ]

    out += [
        "",
        f"## Files tracked — {sum(len(p) for p in inv.files.values())}",
        "",
        "| area | count |",
        "|---|---|",
    ]
    out += [
        f"| `{area}` | {len(paths)} |"
        for area, paths in sorted(inv.files.items())
    ]

    out += [
        "",
        f"## Ledgers — {len(inv.ledgers)}",
        "",
        "| ledger | cells | breakdown |",
        "|---|---|---|",
    ]
    out += [
        f"| `{path}` | {sum(counter.values())} | {_breakdown(counter)} |"
        for path, counter in inv.ledgers.items()
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
