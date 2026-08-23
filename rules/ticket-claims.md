---
rule: ticket-claims
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_ticket_claims.py
    armed: true
  - tier: HOOK-ENFORCED
    checker: tools/ticket_guard.py
    armed: true
---

# Ticket claims

Work is tracked as tickets in `docs/tickets/`, one file each, and a ticket
declares the paths it may edit. A session takes a ticket before writing.

## 0. 2026-08-23 — why this exists now

The i8086 ledger is 43 cells across seven slices, and several do not depend on
each other. That is work for more than one session at once, and two sessions
editing this tree with nothing between them but a handoff document is how an
edit gets lost and nobody notices until CI.

This repository already had the failure in a milder form: `docs/known-issues.md`
3.3 records that rule prose drifted out of sync with its checker **twice
independently during one session**, because two lines of work touched the same
documents without either knowing.

## 1. 2026-08-23 — one file per ticket

Every ticket is `docs/tickets/OH-<n>-<slug>.md` with YAML frontmatter: `id`,
`title`, `status`, `priority`, and the load-bearing `touches`.

The obvious alternative — one `TICKETS.md` holding a table — fails at exactly
the job it is for. Two sessions appending rows conflict on the list itself, so
the coordination mechanism becomes the thing that needs coordinating. A
directory of files is the one shape where two sessions adding work do not
collide.

Frontmatter rather than a bespoke format because `tools/rules_meta.py` already
reads that shape for `rules/`, and PyYAML is already a declared dependency.

## 2. 2026-08-23 — SCRIPT-ENFORCED: no two open tickets claim one file

`collisions` in `tools/check_ticket_claims.py`.

Compared against files that **actually exist**, never by intersecting the
patterns. `tools/*.py` and `**/tickets.py` overlap in the abstract on every
repository and in practice only where a file sits in both. Theoretical overlap
produces warnings nobody can act on, and a check whose output cannot be acted
on is a check that gets ignored.

`blocked` counts as open. A ticket waiting on something still owns its files;
releasing them because it stalled is precisely how two sessions end up in one
file.

## 3. 2026-08-23 — HOOK-ENFORCED: the write is refused before it lands

`tools/ticket_guard.py`, as a `PreToolUse` hook.

This is the only layer that **prevents**. The checker in §2 runs on a diff and
reports; by then the edit exists and somebody has to work out whose it was.

| Layer | Catches | Skippable |
|---|---|---|
| `tools/ticket_guard.py` | a write into another ticket's path, before it happens | only by disabling hooks |
| `tools/check_ticket_claims.py` | everything, whoever produced the diff | no |
| `CLAUDE.md` | nothing — it is what makes a session cooperate at all | always |

### It fails open on its own errors

A guard that blocks every edit because its own YAML is malformed is worse than
the collisions it prevents: it stops all work rather than some. Parse failures
go to stderr and the write is allowed.

### It is deliberately narrow

Reads are never blocked. Writes to unclaimed paths are never blocked — most of
the tree is unclaimed, and demanding a ticket for every edit makes the guard
something people switch off, taking §2 with it.

## 4. 2026-08-23 — one ticket at a time, and the lock is what makes it real

`tickets start` takes a ticket through a lock file created with `O_EXCL`. The
check and the create must be one operation, or two sessions starting together
both see it free.

A named ticket is **self-declared and worth nothing on its own** — without the
lock, two sessions could both export `OH-3` and both be waved through. So the
guard refuses three states beyond the file check: naming a ticket another
session holds, naming one while already holding a different one, and naming one
without having claimed it.

**No expiry, deliberately.** A lock cannot tell a crashed session from a
thinking one, and a claim that quietly lapses is worse than one you must take
on purpose. A dead claim is taken with `--steal`, which prints its age first so
the decision is informed.

## 5. 2026-08-23 — CONVENTION: the files are the truth, GitHub is a mirror

The guard runs on every edit, so it cannot make a network call to ask who owns
a path — that would put a round trip in front of every write and fail offline.
The claim lives in the file. `tickets sync` is one-way.

## 6. 2026-08-23 — duplicate detection warns and never fails

`tickets new` refuses on a resemblance and `--force` overrides; `tickets dupes`
audits the open board. Threshold 0.30.

It never fails a build. No threshold cleanly separates "duplicate" from
"adjacent", and a fuzzy gate that blocks would get switched off along with the
exact claim check sitting next to it.

Closed tickets are excluded from the audit: they are history, and a new ticket
resembling finished work is usually a follow-up rather than a duplicate.

## 7. Known weakness: the hook is not committed

`.claude/` is git-ignored in this repository, so the `PreToolUse` registration
cannot ship with the code. `docs/tickets/README.md` carries the snippet and the
install step.

That makes §3 opt-in per clone, which is weaker than §2 and weaker than this
rule would like. It is recorded here rather than left implicit, because a rule
that overstates its own enforcement is the failure this repository exists to
prevent. §2 runs in CI regardless and catches the same mistakes after the fact.
