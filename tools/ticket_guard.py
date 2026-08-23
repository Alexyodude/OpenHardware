#!/usr/bin/env python3
# OpenHardware - refuse a write into another ticket's files, before it lands.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""PreToolUse hook: the only layer that prevents rather than reports.

`tools/check_ticket_claims.py` runs on a diff and tells you what went wrong.
By then the edit exists and somebody has to work out whose it was. This runs
before the write and refuses it.

    python tools/ticket_guard.py            # reads a hook payload on stdin
    python tools/ticket_guard.py --self-test

## The contract

Reads the Claude Code PreToolUse payload from stdin and writes a decision to
stdout. Exit 0 with `{"permissionDecision": "deny"}` blocks the call; anything
it does not object to is passed through untouched.

## What it refuses, and what it deliberately does not

**Refused:**

1. Writing a file an *open* ticket claims, when this session holds a different
   ticket, or none.
2. Naming a ticket another session holds. The name is self-declared, so
   without this two sessions could both export the same id and both be waved
   through -- the lock in `tools/tickets.py` is what makes the claim real.
3. Naming a ticket while already holding a different one. One at a time.
4. Naming a ticket without having claimed it at all.

**Allowed, deliberately:**

- Any write to a file no open ticket claims. Most of the tree is unclaimed and
  requiring a ticket for every edit would make the guard something people turn
  off.
- Every read. A session should be able to read anything; only writes collide.
- Everything, when no ticket is named *and* the path is unclaimed. A session
  doing untracked work is bound by file claims alone, which is the weakest
  useful rule rather than no rule.

**Fails open on its own errors.** A guard that blocks every edit because its
own YAML is malformed is worse than the collisions it prevents -- it stops all
work rather than some. Parse failures are reported on stderr and allowed.
"""

from __future__ import annotations

import json
import pathlib
import sys

try:
    from tools import tickets as T
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools import tickets as T

#: Called through the module, never imported by name. `from tools.tickets
#: import current_ticket` would bind a second reference that no later
#: reassignment reaches, so the guard would keep reading the real ticket
#: directory while a caller believed it had redirected it. The self-test found
#: exactly that: three cases passed because the guard was reading an empty
#: production tree rather than the fixture.
TicketError = T.TicketError

WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})


def decide(payload: dict, session: str | None = None) -> tuple[bool, str]:
    """(allowed, reason). Pure, so the self-test can drive it directly."""
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if tool not in WRITE_TOOLS:
        return True, ""

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return True, ""
    path = T.normalise(target)

    session = session or payload.get("session_id") or T.session_id()
    named = T.current_ticket()
    tickets = T.load_tickets()

    # -- the session's own claim, before looking at the file at all
    if named:
        holder = T.holder_of(named)
        if holder and holder[0] != session:
            return False, (
                f"{named} is held by {holder[0]} (since {holder[1]}), not this session. "
                f"Naming a ticket does not claim it: run `python tools/tickets.py start "
                f"{named}`, or --steal if that session is gone."
            )
        if not holder:
            return False, (
                f"this session names {named} but has not claimed it. "
                f"Run `python tools/tickets.py start {named}`."
            )
        others = [t for t in T.held_by(session) if t != named]
        if others:
            return False, (
                f"this session names {named} but holds {', '.join(others)}. "
                f"One ticket at a time -- `tickets start {named}` releases the other."
            )

    # -- the file
    owners = T.owners_of(path, tickets)
    if not owners:
        return True, ""
    if named and any(o.id.lower() == named.lower() for o in owners):
        return True, ""

    claimed_by = ", ".join(f"{o.id} ({o.title})" for o in owners)
    if named:
        return False, (
            f"{path} is claimed by {claimed_by}; this session holds {named}. "
            f"Coordinate, or move the claim with `tickets set`."
        )
    return False, (
        f"{path} is claimed by {claimed_by}, and this session names no ticket. "
        f"Run `python tools/tickets.py start <id>` first."
    )


def _self_test() -> int:
    """Six cases covering each refusal and each deliberate allowance."""
    import tempfile
    import unittest.mock as mock

    from tools import tickets as T

    cases_run = 0
    failures = []

    def check(name, got, want):
        nonlocal cases_run
        cases_run += 1
        if got != want:
            failures.append(f"  {name}: got {got}, want {want}")

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "docs" / "tickets").mkdir(parents=True)
        (root / ".omc" / "ticket-locks").mkdir(parents=True)
        (root / "core").mkdir()
        (root / "core" / "cpu.cc").write_text("// x\n", encoding="utf-8")
        (root / "free.py").write_text("# x\n", encoding="utf-8")
        (root / "docs" / "tickets" / "OH-1-core.md").write_text(
            "---\nid: OH-1\ntitle: The core\nstatus: open\npriority: P1\n"
            "touches:\n  - core/**\n---\n\nbody\n",
            encoding="utf-8",
        )

        with mock.patch.object(T, "REPO", root), mock.patch.object(
            T, "TICKET_DIR", root / "docs" / "tickets"
        ), mock.patch.object(T, "LOCK_DIR", root / ".omc" / "ticket-locks"):
            write = {"tool_name": "Write", "tool_input": {"file_path": "core/cpu.cc"}}
            free = {"tool_name": "Write", "tool_input": {"file_path": "free.py"}}
            read = {"tool_name": "Read", "tool_input": {"file_path": "core/cpu.cc"}}

            with mock.patch.object(T, "current_ticket", lambda: None):
                check("unclaimed file allowed", decide(free, "s1")[0], True)
                check("read allowed", decide(read, "s1")[0], True)
                check("claimed file, no ticket", decide(write, "s1")[0], False)

                T.take("OH-1", "s1")
                with mock.patch.object(T, "current_ticket", lambda: "OH-1"):
                    check("holder may write", decide(write, "s1")[0], True)
                    check("other session refused", decide(write, "s2")[0], False)
                with mock.patch.object(T, "current_ticket", lambda: "OH-1"):
                    check("naming unheld ticket", decide(write, "s2")[0], False)

    if failures:
        print(f"ticket_guard self-test: {len(failures)}/{cases_run} FAILED", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"ticket_guard self-test: {cases_run}/{cases_run} OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return _self_test()

    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
        allowed, reason = decide(payload)
    except (json.JSONDecodeError, TicketError, OSError) as exc:
        # Fail open. See the module docstring.
        print(f"ticket_guard: passing through after {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0

    if allowed:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
