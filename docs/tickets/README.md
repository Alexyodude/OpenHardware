# Tickets

One file per unit of work. A ticket declares the paths it may edit, and a
session takes a ticket before writing. `rules/ticket-claims.md` is the rule;
this is how to use it.

## Day to day

```bash
python tools/tickets.py list                  # open tickets, most urgent first
python tools/tickets.py start OH-3            # take it for this session
python tools/tickets.py note OH-3 "found X"   # append a dated finding
python tools/tickets.py set OH-3 --status in-review
python tools/tickets.py stop                  # give it back
```

Before touching an unfamiliar file:

```bash
python tools/tickets.py owner webui/api.py
```

Before filing something:

```bash
python tools/tickets.py similar "decode the modrm byte"
python tools/tickets.py new "Decode the modrm byte" \
    --priority P1 --touches 'core/i8086/decode.*' 'tests/i8086/test_decode.py'
```

`new` refuses on a resemblance and prints what it matched. `--force` overrides.

## Installing the enforcement

```bash
python tools/install_hooks.py
```

That is the whole install. Run it twice and the second run tells you there was
nothing to do.

It sets up two checks, deliberately different in strength:

| | Catches | Ships? |
|---|---|---|
| `tools/ticket_guard.py` | the write, **before** it lands | no — registration only |
| `tools/githooks/pre-commit` | the commit, after the write | **yes** — content is tracked |

**The guard is the better check and the one that cannot travel.** It runs as a
Claude Code `PreToolUse` hook, and the only place that can be registered is
`.claude/settings.json`, which is git-ignored here — the note above it in
`.gitignore` says it comes from a personal template and is not committed
per-project. So `install_hooks.py` *generates* that registration rather than
the repository carrying it.

**The commit hook is the one that survives a clone**, because its content is a
tracked file and installation is one command. It is weaker: it sees a write
after it happened rather than refusing it, and `git commit --no-verify`
bypasses it. That is not closed on purpose — a check nobody can bypass gets
uninstalled instead, and an uninstalled check protects nothing. It also
degrades to a warning rather than an error where python is not on `PATH`,
because a hook that makes the repository uncommittable gets removed.

Check they took:

```bash
python tools/ticket_guard.py --self-test    # 6 cases
python tools/install_hooks.py --check       # reports, changes nothing
python tools/check_ticket_claims.py --staged
```

`install_hooks.py` refuses rather than overwrites: a `core.hooksPath` someone
else already set, or a `.claude/settings.json` it cannot parse. Silently taking
over either would be a worse failure than not installing.

Without any of it you still get `tools/check_ticket_claims.py` in CI, which
catches the same mistakes after the fact. What is left of that gap is recorded
in `rules/ticket-claims.md` §7.1 rather than glossed over.

## The file format

```markdown
---
id: OH-3
title: Core ISA: mov, arithmetic, logic, stack, control flow
status: open
priority: P0
owner: session/isa
created: 2026-08-23
touches:
  - core/i8086/exec_core.*
  - tests/i8086/test_isa_core.py
---

Prose: the problem, and how you will know it is solved.
```

| field | meaning |
|---|---|
| `status` | `open`, `in-progress`, `in-review`, `blocked`, `done`, `duplicate` |
| `priority` | `P0`–`P3` |
| `touches` | paths or globs this ticket may edit — the load-bearing field |
| `avoid` | paths it must not touch, even if unclaimed |

Everything except `done` and `duplicate` holds the claim. `blocked` included:
a stalled ticket still owns its files.

### Claim patterns

`*` stops at a `/`; `**` does not. A pattern with no wildcard and no extension
is read as a directory, so `core/i8086` claims everything beneath it.

| pattern | matches |
|---|---|
| `tools/*.py` | `tools/tickets.py`, **not** `tools/sub/x.py` |
| `core/**` | anything under `core/` |
| `**/cpu.cc` | `cpu.cc` at any depth |
| `core/i8086` | everything under `core/i8086/` |

**Quote any pattern starting with `*` when hand-editing.** A bare
`- **/cpu.cc` is a YAML alias reference, not a string, and the file will not
parse — which takes down every command that reads the directory, not just that
ticket. The CLI quotes automatically; only hand edits are exposed.

## Two sessions at once

The claim is the lock, and the lock is a file created with `O_EXCL` — the check
and the create are one operation, so two sessions starting together cannot both
see it free.

```bash
python tools/tickets.py whoami     # what this session holds, and what others do
```

A session is identified by `$OH_SESSION_ID`, then `$CLAUDE_SESSION_ID`, then
its parent pid.

**Locks never expire.** A lock cannot tell a crashed session from one that is
thinking, and a claim that quietly lapses is worse than one you have to take
deliberately. If a session is genuinely gone:

```bash
python tools/tickets.py start OH-3 --steal    # prints the age of what it takes
```

One ticket at a time: `start` releases whatever else this session held.

## Housekeeping

```bash
python tools/tickets.py dupes                 # audit the open board
python tools/tickets.py merge OH-9 --into OH-3   # same problem, filed twice
python tools/tickets.py group OH-9 --parent OH-3 # related but distinct
python tools/tickets.py check                 # collisions and claim violations
```

`merge` moves the claims across and marks the source `duplicate`; `group` keeps
both and records the link.
