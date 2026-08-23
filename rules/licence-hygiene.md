---
rule: licence-hygiene
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_licenses.py
    armed: true
---

# Licence hygiene

This repository is **MIT**. It was extracted from a GPL-2-or-later fork of
PICSimLab on 2026-08-23, and three trees inside it are still not MIT. Every
rule here protects one consequence of that sentence.

## 0. 2026-08-23 — why MIT is available at all

The previous version of this rule opened "PICSimLab is GPL-2-or-later. This
fork inherits that." That was true of a fork. It is not true of this
repository, and the reason is worth stating rather than assuming, because it
is the whole basis of the relicense.

Nothing here is a derivative of PICSimLab's source:

- `webui/` talks to PICSimLab over the **rcontrol TCP protocol**
  (`webui/rcontrol.py`). Separate process, arm's-length IPC, no linking and no
  inclusion. It is a client, in the way that a browser is not a derivative of
  the server it fetches from.
- `webui/assets.py` **reads** board art from a PICSimLab install at runtime.
  Reading a file the user already has is not redistribution; this repository
  ships none of that artwork.
- `tools/` are our own rule checkers. `tools/draft_part_schemas.py` *scrapes*
  upstream C++, but a tool that reads a file is not derived from it.

Two things genuinely are downstream of upstream's source, and both are handled
rather than waved away. See `PROVENANCE.md` for the full audit — this rule is
the enforcement, that document is the reasoning.

**The Apache-2.0 argument in the old §1 is now moot.** That rule existed to
keep a GPL-3 upgrade path open, because Apache-2.0 is incompatible with
GPL-2-only. Under MIT there is no such constraint: MIT is compatible with
everything, so a dependency's licence can no longer be broken by a header in
this tree. The old check is retired, not weakened.

## 1. 2026-08-23 — SCRIPT-ENFORCED: our source says MIT

Every source file outside the exempt trees carries
`SPDX-License-Identifier: MIT`. `missing_mit` in `tools/check_licenses.py`.

SPDX rather than prose, deliberately. The old header was three lines of
boilerplate that had to be pattern-matched, and matching prose is exactly how
the previous checker ended up asserting the *absence* of a bad header instead
of the presence of a good one — a file with no header at all passed it
trivially, which `docs/known-issues.md` §1.2 recorded and never fixed. An SPDX
identifier is one string, either present or not.

Run on 2026-08-23: **61 files carry the identifier, zero missing.**

## 2. 2026-08-23 — SCRIPT-ENFORCED: our source does not say GPL

`stray_gpl` fails on a GPL grant in any header outside `patches/`.

This is the check that catches a half-finished relicense. A GPL header here
now means one of exactly two things, and both need a person to look:

1. a file the relicense missed, or
2. upstream code copied in that should not have been.

The second is the one that matters. Without this check, pasting a function out
of `src/parts/output_LEDs.cc` into `webui/` would be invisible.

### Headers, not prose

Checks 1 and 2 read only the **leading comment block** — up to the first line
that is not blank, a shebang, a doctype, or a comment. Below that is prose,
and prose discusses licences: `tools/check_licenses.py` names the GPL a dozen
times in its own docstring.

The first version of this checker scanned whole files and **failed on itself**
on the first run. That is where the header/prose line got drawn, and
`test_gpl_discussed_below_the_header_is_not_a_claim` pins it.

## 3. 2026-08-23 — SCRIPT-ENFORCED: patches say GPL, and never MIT

`patches/` holds diffs against PICSimLab's GPL-2-or-later source. A diff is a
derivative of what it patches. Those files are GPL no matter what `LICENSE`
says, and `mislabelled_patches` checks it in both directions: nothing in there
may claim MIT, and `patches/README.md` must state the licence.

This is not a problem to be solved later. It is the correct description of
what a patch to somebody else's GPL source is, and the only wrong move would
be to relabel it for tidiness.

Currently one patch: `0001-board-arch-x86.patch`, adding `ARCH_X86` to the
board architecture enum. Offering it upstream would retire the directory.

## 4. 2026-08-23 — CONVENTION: exempt trees

Third-party source keeps the header it shipped with. Giving three.js a header
of ours would misstate its origin, which is a worse defect than the missing
header check 1 looks for.

| tree | licence | holder |
|---|---|---|
| `webui/static/vendor/` | MIT | three.js authors |
| `tests/fixtures/sst8088/` | MIT | Daniel Balsom |

Excluded by **directory**, not by file, so the next vendored dependency is
covered without editing the checker — and a dependency arriving in a directory
nobody exempted is a licence question for a person, not a header to rewrite.

## 5. 2026-08-10 — CONVENTION: dependency licences

MIT, BSD, and Apache-2.0 are all fine now (see §0). Full list:

| package | licence | form | needed by |
|---|---|---|---|
| PyYAML | MIT | installed | `tools/rules_meta.py` frontmatter parsing |
| pytest | MIT | installed | the test suites |
| websockets | BSD-3-Clause | installed | `webui/bridge.py` |
| three.js 0.185.1 | MIT | **vendored** | `webui/static/scene3d.js` |

Vendoring three.js is what the offline guarantee requires — a page that fetches
a renderer from a CDN is not offline, and `webui.pkg.offline-guarantee` is a
ledger cell whose oracle is the browser's own network log. It costs ~2.1 MB.

**This section is still knowingly weaker than its own standard.** Its previous
version said it should become SCRIPT-ENFORCED "the moment a second or third
dependency shows up"; there are four. The checker needs a declared manifest to
check against and there is none yet. Recorded in `docs/known-issues.md` rather
than left implicit, because a rule that quietly declines to follow its own
instruction is the precise failure this repository exists to prevent.

## 6. Attribution survives the relicense

PICSimLab is GPL-2-or-later, © Luis Claudio Gambôa Lopes. This project drives
it, reads its artwork, and cites its source lines throughout
`webui/parts/schemas/`. None of that is required by licence any more, and all
of it stays: `LICENSE`, `PROVENANCE.md`, `README.md` and
`docs/picsimlab-reference.md` each name upstream and link to it.

Relicensing our own code is not a reason to stop crediting the project this
one exists to serve.
