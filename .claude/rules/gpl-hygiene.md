---
rule: gpl-hygiene
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_licenses.py
    armed: true
---

# GPL hygiene

PICSimLab is GPL-2-or-later. This fork inherits that, and every rule here
protects one consequence of it.

## 1. 2026-08-09 — SCRIPT-ENFORCED: no file may carry a v2-only header

`find_v2_only` in `tools/check_licenses.py` scans the whole tree for a file
whose first 4000 bytes mention `GNU General Public License` and `version 2`
without `later version`.

Upstream is v2-**or-later**, verified in `src/picsimlab1.cc` and
`src/sim_backend/bsim_simavr.h`. That is what makes **Apache-2.0 dependencies
usable**: the combined work moves forward to GPL-3, with which Apache-2.0 is
compatible. Under GPL-2-only it is not, because of the patent-termination
clause.

So the check is deliberately inverted from the obvious one. Asserting that a
GPL header is *present* would pass the exact tree that breaks the project — one
v2-only file among thousands of correct ones. The check asserts the *absence*
of v2-only headers instead.

`COPYING` cannot settle this and is excluded by extension: it is the stock GPL-2
text, whose appendix carries the "or any later version" boilerplate in every
copy ever distributed. Only per-file source headers decide it, and
`test_non_source_files_are_ignored` pins that exclusion.

Run against the whole tree on 2026-08-09: **344 source files scanned, zero
v2-only headers.** `python tools/check_licenses.py` printed
`check_licenses: OK` and exited 0. Spec §8.1's GPL-2-or-later claim, previously
resting on the two-file sample above, is now settled for the whole tree.

## 2. 2026-08-09 — SCRIPT-ENFORCED: new source files carry the header

Scoped to files added since `fork-point`, via
`git diff --diff-filter=A fork-point HEAD`. Upstream's files are upstream's
business; ours are ours.

## 3. 2026-08-10 — CONVENTION: dependency licences

MIT, BSD, and GPL-compatible licences only. Apache-2.0 is permitted **only
while section 1 passes** — the moment it fails, every Apache-2.0 dependency
must go.

Third-party Python dependencies, in full:

| package | licence | needed by |
|---|---|---|
| PyYAML | MIT | `tools/rules_meta.py` frontmatter parsing |
| pytest | MIT | the test suites |
| websockets | BSD-3-Clause | `webui/bridge.py` |

**The upgrade trigger in this section's previous version has fired.** It said
this should become SCRIPT-ENFORCED "the moment a second or third dependency
shows up", on the grounds that a CONVENTION label stops being honest once
there is more than one thing to forget to check. `websockets` was added on
2026-08-10 and there are now three.

That upgrade is **not yet built**, and this section is therefore knowingly
weaker than its own stated standard. It is recorded in `docs/known-issues.md`
rather than left implicit, because a rule that quietly declines to follow its
own instruction is the precise failure this repository exists to prevent. The
checker needs a declared manifest to check against; there is none yet, and
inventing one as a side effect of a UI change would have been the wrong place
to do it.
