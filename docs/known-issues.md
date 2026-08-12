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
| 3.4 | **`gpl-hygiene.md` section 3 is knowingly weaker than its own stated standard.** It said it should become SCRIPT-ENFORCED once a second or third dependency appeared. `websockets` was added on 2026-08-10 and there are now three — PyYAML, pytest, websockets — and the upgrade has not been built. Recorded rather than left implicit: a rule quietly declining to follow its own instruction is the failure this repo exists to prevent. | A declared dependency manifest plus `tools/check_dependencies.py` validating each entry against the allowlist, and asserting every third-party import in our code is declared. Then flip section 3 to SCRIPT-ENFORCED and wire it into `rules.yml`. |

## 4. Workflow friction

`CLAUDE.md` lists a pre-commit sequence that runs all four checkers.
`check_licenses.py` walks the filesystem while `check_deltas.py` and
`check_banned_symbols.py` walk git. Top-level `lib/` has a `.gitignore` of `*`
and `bscripts` populates it at build time, so **anyone who has built the project
and then follows the documented pre-commit sequence will scan vendored
third-party sources.** That produces a false positive, never a false green, but
it erodes trust in the documented workflow. Scoping `find_v2_only` to tracked
files would fix it.

## 4a. Upstream defects observed on a live PICSimLab 0.9.3

Found on 2026-08-10 running the simulator built in WSL. These are upstream's,
not this fork's, and are recorded so nobody rediscovers them the hard way.

| # | Issue | Consequence |
|---|---|---|
| 4a.1 | **`spadd` segfaults when a part's assets are missing.** Adding a part whose `part.map`/`part.svg` are absent logs `Erro CC_LOADIMAGE!` and then `Caught SIGSEGV`. It does not return ERROR. | Any UI offering part placement can kill the simulator. The bridge must expect the connection to drop rather than an error reply. Worth reporting upstream. |
| 4a.2 | **Corrected.** Part assets are not missing — they ship in `share/parts/`. The binary looks for `share/picsimlab/parts/`, an installed layout with one extra path component, so a plain source build cannot find them. Symlinking `share/picsimlab -> share` makes them resolve and `spadd` then succeeds. My first diagnosis said the assets were never produced; that was wrong, and the difference matters because the real fix is `make install` or a `_SHARE_` path, not generating anything. | An in-tree run needs the symlink or a proper install. Without it, every part placement hits 4a.1 and kills the simulator. |
| 4a.5 | With assets resolving, `spadd "Push Buttons" 100 100` returns Ok and `sprdcfg 0` returns a real config — the part genuinely exists. But `get part[0].in[N]` returns ERROR for every N, so `Part->GetInputCount()` is 0 for a part placed without the GUI having laid it out. | The write-confirm path a browser UI needs is still not reachable headlessly. This is the specific remaining blocker for `webui.ui.button-press` and `webui.ui.pot-drag`, and it is narrower than "parts do not work": placement works, input enumeration does not. |
| 4a.3 | `set pin[N]` is accepted but **not observable** via `get pin[N]` on an Arduino Uno. With the simulation paused, `set pin[04] = 0` and `= 1` both leave the value at 16. | Driving MCU pins is not a viable UI interaction path on this board. Buttons and potentiometers must go through spare parts, which 4a.2 blocks. Pinned by `test_pin_writes_are_not_observable_via_get_pin`. |
| 4a.4 | `get board.in[]` and `get board.out[]` return ERROR on Arduino Uno, which has no on-board controls (`Use Spare: 0` by default). | Board I/O is board-dependent. A portable UI cannot assume it exists; boards like PICGenios have it, the Uno does not. |

| 4a.6 | **The NOGUI build cannot be linked with GCC 11.4 on Ubuntu 22.04.** `make -f Makefile.NOGUI` compiles cleanly and reaches the link stage, then dies with `lto1: internal compiler error: Segmentation fault` → `lto-wrapper: fatal error`. Removing `-flto=auto` from `Makefile.NOGUI` does **not** help: the dependency archives built by `bscripts/build_all_static.sh` (picsim, lxrad, simavr) carry LTO IR themselves, so the linker still runs `lto-wrapper`. `bscripts/build_package_NOGUI.sh` fails earlier and separately, on Debian packaging plumbing — `debuild` runs in the wrong directory, so `src/Makefile` and `debian/rules` are missing. | Spec §8.4 cannot be answered without rebuilding the whole dependency chain with LTO disabled, or using a different compiler. The WX GUI build is unaffected and works. |

| 4a.7 | **The simulator crashes under repeated live-test runs.** After many cycles of placing and deleting a Push Buttons part, PICSimLab 0.9.3 died with a SIGSEGV stack trace in `/root/.picsimlab/picsimlab_log0.txt`. Same family as 4a.1. | A live test run can fail through no fault of the code. The failure presents as an **error**, not a pass — the fixture cannot reach the simulator and says so, which is the intended behaviour. Before debugging a live-test failure, check the simulator is still alive: `wsl -d Ubuntu-22.04 -- pgrep picsimlab`. Restart, then re-run. |

## 4b. What a wrong part schema can still do undetected

Added 2026-08-10 after the peripherals work. This is the honest limit of the
schema mechanism, stated so nobody has to rediscover it.

A part schema says what each position in a peripheral's positional CSV config
means. Several guards defend it: the loader validates structure (roles, labels,
`dir`/`type`); `tools/check_part_schemas.py` proves a `source` names a file and
a line that exist; the server rejects under-arity; the client compares arity
against the live part on every read; and a live round-trip confirms arity,
storage and settings survival.

**None of them can detect a schema whose fields are in the wrong order.**

`connect()` writes through `schema.index_of(label)` and `read_wiring()` reads
through the same positions, so any transposition round-trips perfectly clean.
Swap `B3` and `B7`, or `active` and `mode`, and every test still passes while
the circuit is wired wrong. The same blindness covers a wrong `dir` (nothing
cross-checks `in`/`out` against the C++ array the value came from), a
mislabelled field at the correct position, and a `source` citation pointing at
a real but irrelevant line.

**Only a human re-reading the cited `sprintf` catches these.** That is why every
schema carries a `source`, and why `verified` was narrowed to claim arity and
storage rather than layout.

Two smaller gaps, both measured live on PICSimLab 0.9.3:

| # | Gap | Consequence |
|---|---|---|
| 4b.1 | The server's arity guard is **one-sided**. `Part->ReadPreferences` returns `sscanf`'s assignment count, so under-arity is rejected but **over-arity is accepted with the extra field silently dropped**. | An over-long schema is caught only by the client's own check, and only on a later read. Do not rely on the server to reject it. |
| 4b.2 | Config fields are `%hhu`, so pin values wrap mod 256. Before the range check landed, `connect(..., 300)` was accepted and read back as 44. | `_set_field` now rejects anything outside 0..255. Any future code path that writes a config without going through it reopens this. |

## 4c. Tests that constrain less than their names suggest

From the final review of the peripherals work, 2026-08-10. None block; all are
worth knowing before trusting a green suite.

| test | what it actually proves |
|---|---|
| `test_no_shipped_schema_claims_verification_it_has_not_earned` | Asserts the substring `round-trip` appears in `verified`. A hand-written `"verified": "round-trip"` passes it — **it cannot detect the hand-authoring it is named for.** |
| `test_*_matches_its_source` (×3) | Restates the JSON in Python rather than deriving from the C++. They are change-detectors, not oracles: both sides move together if someone edits the schema. |
| `test_a_placed_part_matches_its_schema_arity` | Cannot fail independently of `read_wiring`'s own internal arity check. |
| `test_version_returns_something`, `test_supported_boards_parse`, `test_supported_parts_parse` | Truthiness only. |
| `test_settings_survive_a_pin_write` | Checks `active` and `Size` but not `mode`. |

The suite's genuinely constraining tests — arity mismatch, role refusal, unknown
label, quote format, duplicate names, and every negative control verified to
fail against the pre-fix code — are what the confidence rests on.

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
