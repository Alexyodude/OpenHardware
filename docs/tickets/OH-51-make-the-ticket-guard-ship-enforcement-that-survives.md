---
id: OH-51
title: 'Make the ticket guard ship: enforcement that survives a fresh clone'
status: open
priority: P1
created: '2026-08-25'
touches:
- tools/check_ticket_claims.py
- tools/githooks/**
- tools/install_hooks.py
- tests/rules/test_ticket_hooks.py
- rules/ticket-claims.md
- tools/tickets.py
- tests/rules/test_tickets.py
- docs/tickets/README.md
---

`tools/ticket_guard.py` is written, tested (6/6 self-test) and does nothing on a fresh clone, because the only thing that invokes it is a `PreToolUse` entry in `.gitignore`d `.claude/settings.json`. `docs/tickets/README.md` states this outright -- *"It cannot ship with the code"* -- and `rules/ticket-claims.md` section 7 records the gap rather than glossing it. So the claim system a whole session relies on has **no write-time enforcement anywhere except one developer's machine**.

`.claude/` stays ignored. The comment above it in `.gitignore` says it is installed from a personal template and is deliberately not committed per-project; un-ignoring it to smuggle a hook in would commit machine-specific settings to fix a repository problem.

## What is missing, precisely

`tools/check_ticket_claims.py` diffs `merge-base(base, HEAD)..HEAD` -- committed work on a branch, which is the CI shape. Nothing checks **staged** files, so there is no commit-time gate either. The enforcement ladder currently has a top rung (CI) and a bottom rung that does not ship (the PreToolUse hook), and nothing between.

## The shape

    # tools/check_ticket_claims.py
    def staged_files() -> list[str]:        # git diff --cached --name-only
    def main(argv) -> int:                  # gains --staged

    # tools/githooks/pre-commit             tracked, so it ships
    #!/bin/sh
    exec python tools/check_ticket_claims.py --staged

    # tools/install_hooks.py
    def install_git_hooks(repo) -> str      # git config core.hooksPath tools/githooks
    def install_claude_hook(repo) -> str    # merge PreToolUse into .claude/settings.json
    def main() -> int                       # idempotent, reports what it changed

The git hook is the part that actually ships: its *content* is tracked, and installation is one documented command rather than a JSON block a person retypes. It also guards commits made by any tool, not only by Claude Code, which the PreToolUse hook never could.

Done when a staged write into another ticket's claimed path is refused at commit time on a clone where nobody edited `.claude/`, the installer is idempotent, and a negative control proves the hook can actually reject.

Not in scope: `docs/tickets/README.md`, which OH-17 holds. Its installation section will need rewriting once this lands.

**Note 2026-08-25:** Done. Two commits: 16dceeb ships the enforcement (staged_files + --staged on check_ticket_claims, the tracked tools/githooks/pre-commit, tools/install_hooks.py, 5 tests) and 1a817d1 fixes what shipping it exposed -- a ticket now always owns its own file, because OH-17's docs/tickets/** claim was blocking 15 of 16 open tickets from recording their own notes. NOT DONE, and it needs OH-17 to release the path: docs/tickets/README.md still documents the old install step as a JSON block to retype, and should now say 'python tools/install_hooks.py'. Its 'It cannot ship with the code' paragraph is also no longer the whole truth -- the registration still cannot ship, but the git hook's content does. Also still true and worth leaving alone: OH-17's claim on docs/tickets/** is over-broad for a conformance-corpus ticket, and the new ownership rule works around it rather than fixing it.
