---
rule: upstream-sync
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_deltas.py
    armed: true
---

# Upstream sync

PICSimLab is **not in this repository**. It is located at runtime by
`webui/picsimlab.py` and consumed as an external install; see
`docs/picsimlab-reference.md` for how to get a copy.

The rule is unchanged from the fork era: **no change to upstream goes
unrecorded.** What a change *is* has changed, and §1 is rewritten around that.

## 1. 2026-08-23 — SCRIPT-ENFORCED: every upstream change is a documented patch

A change to PICSimLab is a file in `patches/`. `tools/check_deltas.py` requires
that every `patches/*.patch` is named in a `### ` heading of
`patches/README.md`, and that every such heading names a patch that exists.
Backticks anywhere else — reason prose, intro text, bullet lists — authorise
nothing; only the heading is the entry.

Both directions are checked. An undocumented patch is the obvious failure; an
orphaned heading describing a patch that no longer exists is the quieter one,
and worse in the way stale documentation is always worse than none.

### What this replaces, and the bug it retires

Until 2026-08-23 this rule intersected `git diff --name-only fork-point HEAD`
with `git ls-tree -r --name-only fork-point`, subtracting paths logged in
`docs/upstream-deltas.md`.

`docs/known-issues.md` 1.8 recorded that this premise — everything in
`fork-point..HEAD` is ours — **is false for any tree that also contains
upstream commits made after the tag.** It fired the first time CI ever ran, on
upstream's own eight files, and the note warned the same eight would come back
the day the fork merged upstream for real.

That bug is now structurally impossible. A patch file is ours by construction:
nobody else writes into `patches/`, and no upstream merge can put anything
there. The old §2 — "an unresolvable tag is an error" — is retired with it,
because there is no tag to resolve.

`docs/upstream-deltas.md` is deleted; `patches/README.md` is the ledger.

## 2. 2026-08-23 — CONVENTION: prefer no patch at all

Every patch is a rebase cost, paid every time upstream moves. Before adding
one, the question is whether the change can be avoided:

1. **Can it be done over the rcontrol protocol instead?** Almost everything
   `webui/` does is, which is why 101 files of this project needed exactly one
   line of upstream C++.
2. **Can it be sent upstream?** A merged change is a retired patch. The one
   patch here — `ARCH_X86` in the board architecture enum — is a single enum
   member and an obvious contribution. Offering it to
   `lcgamboa/picsimlab` would empty the directory.
3. **Only then, a patch**, with a `### ` section saying what and why.

The analog solver remains the one planned change with no purely additive form:
it needs `src/lib/spareparts.cc` to have shared-node semantics it does not
have (spec §4.1). That will be a patch, and a large one.

## 3. 2026-08-23 — CONVENTION: patches keep their own licence

A diff against GPL source is a derivative of it. `patches/` is
GPL-2-or-later while the rest of this repository is MIT, and
`rules/licence-hygiene.md` §3 enforces the split in both directions.

## 4. 2026-08-23 — the reference checkout may move under you

`webui/picsimlab.py` resolves whatever PICSimLab it is pointed at, with no
pinned revision. A patch that applied last month may not apply today, and
`tools/apply_patches.sh` fails loudly rather than half-applying when that
happens.

There is deliberately **no pinned upstream SHA**. Pinning one would make the
reference a dependency to be upgraded on a schedule, which is most of the cost
of being a fork with none of the benefit. The patches are small enough to
re-cut, and `patches/README.md` records what each one changes so re-cutting is
a reading exercise rather than an archaeology one.

Local ignores now go in this repository's own `.gitignore`. In the fork that
file was upstream's, and the rule said to use `.git/info/exclude` instead;
that constraint is gone.
