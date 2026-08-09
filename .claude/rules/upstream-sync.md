---
rule: upstream-sync
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_deltas.py
    armed: true
---

# Upstream sync

The fork commit is tagged `fork-point`
(`cd92747b1a04cab56c17f4e9ac35a1406c9935f7`, 2026-07-30).

## 1. 2026-08-09 — SCRIPT-ENFORCED: modifications to upstream files must be logged

`tools/check_deltas.py` intersects `git diff --name-only fork-point HEAD` with
`git ls-tree -r --name-only fork-point` and subtracts the paths backticked in
`## ` heading lines of `docs/upstream-deltas.md`. Backticks anywhere else in
the ledger — reason prose, intro text, bullet lists — authorise nothing.
Anything left exits non-zero.

Additive files are unrestricted and always will be. Two of this fork's three
planned additions — the 8086 core and the web UI — are entirely new files and
will never appear in the ledger.

## 2. 2026-08-09 — SCRIPT-ENFORCED: an unresolvable tag is an error

`unlogged_modifications` raises when the fork-point file set is empty. Without
that guard a missing or misspelled tag yields an empty intersection, which
reads as "no unlogged modifications" — the check would pass hardest at the exact
moment it stopped working. `test_empty_fork_point_set_raises` pins it.

## 3. 2026-08-09 — CONVENTION: prefer a new file to an edit

The analog solver is the one planned change with no purely additive form, since
it must give `src/lib/spareparts.cc` shared-node semantics it does not have
(spec section 4.1). Every entry the ledger ever gains is a future merge
conflict, so the question to answer before adding one is whether the change can
live beside the original instead of inside it.

Local-only ignores belong in `.git/info/exclude`, never in upstream's
`.gitignore`. This repository's own `.omc/` entry is handled that way.
