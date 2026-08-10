# Known issues

Open findings from the review of the feature-strategy machinery
(branch `design/feature-strategy`, 2026-08-09). Every item here was raised by a
code review, triaged as **defer** rather than block, and left deliberately
unfixed. None affects the tree as it stands; each is recorded because the
conditions that make it harmless are not permanent.

Findings that were fixed during that branch are listed in §4 so they are not
re-reported.

## 1. Checkers

| # | File | Issue | What would fix it |
|---|---|---|---|
| 1.1 | `tools/check_layering.py` | Forbidden-include matching is substring-based, so a path such as `counterparts/` would match `parts/`. No occurrence in the tree today. Over-matching fails loudly, so this is a false positive, never a false pass. | Match path segments rather than substrings. |
| 1.2 | `tools/check_licenses.py` | A file with no licence header at all passes `find_v2_only` trivially. A clean scan therefore proves that nothing **revokes** GPL-2-or-later, not that every file **grants** it. `find_missing_headers` covers files added since `fork-point`, so the gap is confined to upstream's own tree. | Nothing, unless upstream's headers are ever audited directly. Do not restate a clean scan as proof of a positive grant. |
| 1.3 | `tools/check_licenses.py` | If `fork-point` is unresolvable **and** a genuine v2-only file exists, the `CalledProcessError` path returns 2 and the v2-only finding is never reported. Exit 2 still fails CI, so nothing merges on a false green. | Report findings already gathered before returning 2. |
| 1.4 | `tools/check_deltas.py` | Compares `fork-point..HEAD`, not the working tree. Correct for a CI gate, but a locally modified upstream file passes until committed. Not stated in `.claude/rules/upstream-sync.md`. | Document the choice in the rule. |
| 1.5 | `tools/check_deltas.py` | Deletions of upstream files **are** caught, because `git diff --name-only` lists deleted paths and the intersection catches them. The rule document never says so, so a reader would assume only edits are covered. | One sentence in the rule. |
| 1.6 | `tools/rules_meta.py` | `load_rules` reports "rules directory does not exist" when the path exists but is a file — `is_dir()` is false either way. | Distinguish the two cases in the message. |
| 1.7 | `tools/rules_meta.py` | `RULES_DIR` is a relative default resolved against the current working directory at call time. Every current caller passes an explicit path, so nothing depends on it. | Resolve relative to the module's location, or drop the default. |

## 2. Parser and tests

| # | File | Issue | What would fix it |
|---|---|---|---|
| 2.1 | `tools/ledger.py` | A row whose every column is `-` is classified as a separator and **silently skipped**. This is a silent drop inside the `PARSER-ENFORCED` parser — the one place this project says silent drops are worst. Harmless today only because such a row carries no data and no realistic id or tier is a bare `-`. | Require the separator row to be structurally distinct, or raise on an all-dash row that is not the second line. |
| 2.2 | `tools/ledger.py` | The empty-id guard has no dedicated test. | Three lines. |
| 2.3 | `tests/rules/test_checkers_are_wired_into_ci.py` | Scans single-line `run:` entries only. A checker invoked inside a multi-line `run: |` block would not be matched. All four current invocations are single-line. This is a false negative, not a false pass. | Scan the whole `run:` value, not the line. |
| 2.4 | `tests/rules/test_claude_md_lists_every_rule.py` | Asserts each rule slug appears somewhere in `CLAUDE.md`. Because each slug is a substring of its own path, this would pass on a file containing nothing but five paths. The weakest test in the suite. | Assert something structural — that each rule is listed with its checker, for instance. |
| 2.5 | `tests/rules/test_check_banned_symbols.py` | `test_clean_file_passes` would still pass under several broken implementations. Not vacuous — it does prove no false positive on ordinary code — but it is paired with positive tests that carry the real weight. | Nothing required. |

## 3. Rule documents

| # | Issue | What would fix it |
|---|---|---|
| 3.1 | Frontmatter tiers are validated by `tools/rules_meta.py`; **prose tier labels are not**. `.claude/rules/conformance-fixtures.md` heads a section `CRITICAL`, which is not one of the five valid tiers, and three different heading-label forms are in use across the five files. | Validate prose section labels against the same vocabulary as frontmatter. |
| 3.2 | **Resolved 2026-08-09.** `.claude/rules/determinism.md` described three mechanisms in prose while declaring two in frontmatter. The original triage assumed the other rules declared their CONVENTION entries; the final review checked and found four of five did not, making `core-interface.md` the outlier rather than `determinism.md`. That no-op entry has been dropped, so all five rules now agree: frontmatter declares only mechanisms with a checker, and CONVENTION sections live in prose alone. | — |
| 3.3 | Prose drifted out of sync with code **twice independently** during fix rounds, in `gpl-hygiene.md` and `upstream-sync.md`. Both were corrected, but nothing in the process re-reads a rule's prose when its checker changes. In a repository whose thesis is that a rule claiming enforcement it lacks is worse than no rule, this is the structural weakness most worth closing. | A check that a rule naming a checker is re-read whenever that checker changes — or at minimum a review-checklist item. |

## 4. Workflow friction

`CLAUDE.md` lists a pre-commit sequence that runs all four checkers.
`check_licenses.py` walks the filesystem while `check_deltas.py` and
`check_banned_symbols.py` walk git. Top-level `lib/` has a `.gitignore` of `*`
and `bscripts` populates it at build time, so **anyone who has built the project
and then follows the documented pre-commit sequence will scan vendored
third-party sources.** That produces a false positive, never a false green, but
it erodes trust in the documented workflow. Scoping `find_v2_only` to tracked
files would fix it.

## 5. Open specification questions

Both are recorded as `blocked_by` on unarmed mechanisms, so nothing currently
claims enforcement it does not have.

- **§8.3** — partly answered without a build. `src/lib/rcontrol.cc` exposes no
  VCD command; its vocabulary is `all blist buclist clk dumpe dumpf dumpr exit
  help info oscmeasures oscrdcfg oscshow oscwrcfg pins pinsl quit reset sim
  splist spshow start stop sync version`. VCD is configured by placing a
  `virtual_VCD_Dump` part in a `.pzw` workspace, not driven remotely. A
  conformance fixture is therefore a pre-wired workspace **plus** rcontrol for
  control and assertions. What remains is confirming that surface works
  headlessly.
- **§8.4** — unanswered. Requires a Linux build; `src/Makefile.NOGUI` hardcodes
  `Linux64_NOGUI`, links archives from a Debian multiarch path, and needs four
  static libraries that only `bscripts` produces.

`.github/workflows/nogui-probe.yml` exists to answer both. It is manual-only and
cannot run until `fork-point` is pushed to a remote.

## 6. Resolved during the branch — do not re-report

- The meta-guard verified checkers existed but never that CI ran them.
- `tools/check_layering.py` used non-recursive `glob`, missing nested directories.
- `tools/ledger.py` was armed while nothing parsed any real ledger.
- `find_v2_only` over-matched files merely citing the GPL.
- `logged_paths` authorised every backticked token anywhere in the delta ledger.
- The banned-symbol checker skipped whole lines beginning with a comment, hiding
  calls after a closed block comment, and false-flagged calls inside genuine
  multi-line comments.
- `check_licenses.py` crashed with a traceback where its siblings exit cleanly.
- CI could not pass at all with `fork-point` unpushed.
