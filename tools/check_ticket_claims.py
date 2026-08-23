#!/usr/bin/env python3
# OpenHardware - verify a change respects the ticket claims around it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Checker for rules/ticket-claims.md.

`tools/ticket_guard.py` refuses a bad write before it lands, but only inside a
session that has hooks enabled. This runs on the diff, so it catches the same
mistakes whoever produced them and however they got in -- a session with hooks
off, a manual edit, a merge.

Three checks, each a different way for claims to be wrong.

## 1. No two open tickets claim the same file

Compared against files that actually exist, not by intersecting the patterns.
`tools/*.py` and `**/tickets.py` overlap in the abstract on every repository
and in practice only where a file sits in both. Reporting theoretical overlap
produces warnings nobody can act on, and warnings nobody can act on are how a
check gets ignored.

## 2. Every claim matches something

A claim that matches no file is a typo, and a typo in a claim is worse than no
claim: it reads as protection while protecting nothing. The one exception is a
ticket for work not yet written, which is most of them -- so this reports and
does not fail.

## 3. The diff stays inside its ticket

When a ticket is named -- `$OH_TICKET`, or `.omc/current-ticket` -- every
changed file must be either claimed by that ticket or claimed by nobody.
Editing a file another open ticket claims is the failure this exists to catch.

Without a named ticket there is nothing to check the diff against, and the
checker says so rather than passing silently. A quiet pass and a real pass must
never look the same.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

try:
    from tools import tickets as T
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import tickets as T

#: Through the module, never `from tools.tickets import REPO`. That binds a
#: second reference which no later reassignment reaches, so this file would
#: keep scanning the real repository while a caller believed it had been
#: pointed elsewhere. The guard had the same bug and its self-test caught it.
TicketError = T.TicketError

#: Exit code meaning "did not run". Same convention as the checkers that need a
#: PICSimLab checkout; see tools/check_layering.py.
SKIPPED = 3


def changed_files(base: str) -> list[str]:
    """Files this branch changed relative to `base`."""
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", base, "HEAD"],
            cwd=T.REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        result = subprocess.run(
            ["git", "diff", "--name-only", merge_base, "HEAD"],
            cwd=T.REPO,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [T.normalise(line) for line in result.stdout.splitlines() if line.strip()]


def unmatched_claims(tickets) -> tuple[list[tuple[str, str]], int]:
    """(likely typos, count of tickets whose work is simply unwritten).

    The distinction matters more than the raw list. A ticket for work not yet
    started has claims that match nothing, and that is the normal state of most
    of the board -- reporting each one produced twenty-four lines of noise on a
    freshly seeded board, which is the "warnings nobody can act on" failure
    this checker's own docstring warns about.

    So: when *every* claim on a ticket matches nothing, the work is unwritten
    and one summary line covers it. When *some* match and some do not, the ones
    that do not are almost certainly typos -- the ticket is being worked, files
    exist, and a pattern beside them that hits nothing is a mistake worth
    naming.
    """
    files = [T.normalise(p.relative_to(T.REPO)) for p in T.REPO.rglob("*") if p.is_file()]
    files = [f for f in files if not f.startswith((".git/", ".omc/", "third_party/"))]

    suspicious: list[tuple[str, str]] = []
    unwritten = 0
    for ticket in tickets:
        if not ticket.is_open or not ticket.touches:
            continue
        hit = [p for p in ticket.touches if any(T.matches_claim(p, f) for f in files)]
        miss = [p for p in ticket.touches if p not in hit]
        if not miss:
            continue
        if not hit:
            unwritten += 1
            continue
        suspicious += [(ticket.id, p) for p in miss]
    return suspicious, unwritten


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    base = "master"
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]

    try:
        tickets = T.load_tickets()
    except TicketError as exc:
        print(f"check_ticket_claims: {exc}", file=sys.stderr)
        return 2

    if not tickets:
        print("check_ticket_claims: no tickets yet; nothing to check")
        return 0

    failed = False

    # 1 -- two open tickets on one file
    for a, b, path in T.collisions(tickets):
        failed = True
        print(
            f"{path}: claimed by both {a.id} ({a.title}) and {b.id} ({b.title})",
            file=sys.stderr,
        )

    # 2 -- a claim that protects nothing
    suspicious, unwritten = unmatched_claims(tickets)
    for ticket_id, pattern in suspicious:
        print(
            f"note: {ticket_id} claims {pattern!r}, which matches no file, while its "
            f"other claims do match. Likely a typo.",
            file=sys.stderr,
        )
    if unwritten:
        print(f"note: {unwritten} ticket(s) claim only files not yet written.", file=sys.stderr)

    # 3 -- the diff against its ticket
    named = T.current_ticket()
    if named is None:
        print(
            "check_ticket_claims: no ticket named ($OH_TICKET or .omc/current-ticket), "
            "so the diff was NOT checked against one. Collisions above still apply.",
            file=sys.stderr,
        )
    else:
        match = [t for t in tickets if t.id.lower() == named.lower()]
        if not match:
            print(f"check_ticket_claims: named ticket {named} does not exist", file=sys.stderr)
            return 2
        mine = match[0]
        for path in changed_files(base):
            owners = T.owners_of(path, tickets)
            if not owners:
                continue
            if all(o.id != mine.id for o in owners):
                failed = True
                other = ", ".join(o.id for o in owners)
                print(
                    f"{path}: changed while holding {mine.id}, but claimed by {other}",
                    file=sys.stderr,
                )

    if failed:
        print(
            "check_ticket_claims: claim violations, per rules/ticket-claims.md",
            file=sys.stderr,
        )
        return 1

    scope = f" against {named}" if named else ""
    print(f"check_ticket_claims: OK ({len(tickets)} ticket(s){scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
