#!/usr/bin/env python3
# OpenHardware - every check, one command, in the order that reads well.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Every check, one command.

Each row names the defect it catches and how to make it fail on purpose. A
check with nothing to point at is a check nobody will keep running -- and a
check nobody runs is worse than none, because its existence is taken for
coverage.

    python tools/checkall.py            # all of it
    python tools/checkall.py --quiet    # only what failed
    python tools/checkall.py --prove    # print how to break each one

Exit 3 from a row prints SKIP, loudly, and is not a failure: the first three
checkers say SKIPPED when there is no PICSimLab source checkout, which is a
statement about this machine and not about the tree. A quiet pass and a real
one must never look alike.

The table refuses to rot: before running anything, every checker armed
SCRIPT-ENFORCED in rules/*.md frontmatter must be a row here, or the run
fails on the spot. Adding a checker to the registry therefore means adding a
row -- there is no third state where it exists and nothing runs it.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

try:
    from tools.rules_meta import load_rules
except ModuleNotFoundError:  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from rules_meta import load_rules

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable
SKIPPED = 3

#: name, argv (run under this interpreter, cwd repo root), what it catches,
#: how to make it fail.
#: **The fourth column is not documentation.** It is the instruction for
#: verifying the row can still fail, and writing it forces you to know.
#: If you cannot fill it in, you do not yet know whether the check can fail.
#: Not in this table means not watched.
CHECKS = [
    ("upstream backends include no parts or UI",
     ["tools/check_layering.py"],
     "an #include from sim_backend/ into parts/ or the UI, upstream",
     "add `#include \"parts/x.h\"` to a header under "
     "../picsimlab-reference/src/sim_backend/ and re-run"),

    ("the board contract is the size the tests expect",
     ["tools/check_board_contract.py"],
     "upstream growing board.h a pure virtual this repository has not seen",
     "append `virtual void Nonsense(void) = 0;` to upstream's src/lib/board.h"),

    ("part schema citations still resolve",
     ["tools/check_part_schemas.py"],
     "a schema whose source path, case, or line no longer exists upstream",
     "point one webui/parts/schemas/*.json `source` at src/parts/nope.cc:1"),

    ("every file states the licence it is under",
     ["tools/check_licenses.py"],
     "a tracked source file with no SPDX MIT header, or a GPL claim "
     "outside patches/",
     "delete the SPDX line from any tools/*.py"),

    ("patches and their ledger agree both ways",
     ["tools/check_deltas.py"],
     "an undocumented patch, or a `### ` heading whose patch is gone",
     "add an orphan `### nothing.patch` heading to patches/README.md"),

    ("no nondeterminism entered the C++",
     ["tools/check_banned_symbols.py"],
     "rand(, time( or clock( in tracked C/C++ outside comments",
     "add `rand();` to a tracked .cc and `git add` it -- untracked files "
     "are invisible to this checker"),

    ("no board claims to run firmware without a witness",
     ["tools/check_board_claims.py"],
     "a run-claim anywhere FIRMWARE_VERIFIED's named tests do not back",
     "assert in any watched .md that a chip outside FIRMWARE_VERIFIED has "
     "executed an image. Spell the claim there and not here: this column is "
     "itself scanned, and the first draft of this row tripped the checker"),

    ("no two tickets claim one file",
     ["tools/check_ticket_claims.py"],
     "open tickets whose claims collide on a path that exists",
     "give a second open ticket a `touches:` line for tools/checkall.py"),

    ("the ticket guard still refuses what it must",
     ["tools/ticket_guard.py", "--self-test"],
     "a guard edit that quietly allows a cross-ticket write",
     "invert one refusal in tools/ticket_guard.py and re-run"),

    ("claims documents make about this tree are true of it",
     ["tools/check_facts.py"],
     "a count, list or description restated in prose and now wrong, or an "
     "anchored claim whose function moved under it",
     "change `seven suites` in CLAUDE.md to `six`, or edit "
     "is_mask_film's body without --confirm"),

    ("the board-sources survey was regenerated",
     ["docs/research/board-sources/render.py", "--check"],
     "survey.md edited by hand, or left behind by a sources.json edit -- "
     "generation is an event, not a property",
     "change one URL in sources.json without re-running render.py"),

    ("the test suites pass",
     ["-m", "pytest", "-q"],
     "everything the seven suites watch",
     "add `assert False` to any test"),
]


def missing_from_table() -> list[str]:
    """Armed SCRIPT-ENFORCED checkers the table above does not run."""
    rows = {cmd[0] for _, cmd, _, _ in CHECKS}
    armed = {
        mech.checker
        for rule in load_rules(ROOT / "rules")
        for mech in rule.mechanisms
        if mech.tier == "SCRIPT-ENFORCED" and mech.armed and mech.checker
    }
    return sorted(armed - rows)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = list(sys.argv[1:] if argv is None else argv)

    if "--prove" in args:
        print("\nMake each fail, then confirm it passes again. A check that "
              "has never failed\nis a check you have no evidence about.\n")
        for name, _, _, how in CHECKS:
            print(f"  {name}\n      {how}\n")
        return 0

    quiet = "--quiet" in args

    unrun = missing_from_table()
    for checker in unrun:
        print(f"\nFAIL  {checker} is armed in rules/ but has no row in this "
              f"table -- it exists and nothing runs it")

    failed = list(unrun)
    skipped = []
    for name, cmd, catches, _ in CHECKS:
        result = subprocess.run([PY, *cmd], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        if result.returncode == SKIPPED:
            skipped.append(name)
            verdict = "SKIP"
        elif result.returncode == 0:
            verdict = "PASS"
        else:
            failed.append(name)
            verdict = "FAIL"
        if not quiet or verdict == "FAIL":
            print(f"\n{verdict}  {name}")
            print(f"      catches: {catches}")
            lines = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
            for line in lines[:30]:
                print("    " + line)
            if len(lines) > 30:
                print(f"    ... {len(lines) - 30} more line(s)")

    print()
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    verdict = f"all {len(CHECKS)} checks pass"
    if skipped:
        verdict += f" ({len(skipped)} SKIPPED, which is a statement about " \
                   f"this machine: {', '.join(skipped)})"
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
