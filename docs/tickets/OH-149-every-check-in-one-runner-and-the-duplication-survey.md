---
id: OH-149
title: Every check in one runner, and the duplication survey it starts from
status: in-review
priority: P2
created: '2026-08-31'
touches:
- tools/checkall.py
- tools/stale.py
- tools/viewer.html
- tools/DUPLICATION.md
- tools/check_facts.py
- tests/rules/test_check_facts.py
- CLAUDE.md
- docs/research/board-sources/render.py
- docs/research/board-sources/survey.md
- tools/facts_store.json
---

uvx nodeengine scaffolded tools/stale.py, tools/checkall.py and tools/viewer.html. This ticket does what the scaffold asks: survey what this repository states in more than one place (tools/DUPLICATION.md), name one source per relationship, rewrite checkall.py's table to run this repo's real checkers plus a new facts check for prose counts nothing currently watches, and break every row on purpose before believing it.

**Note 2026-08-31:** Survey landed as tools/DUPLICATION.md, from four parallel sweeps (root docs, docs tree, checker inventory, code). Nine claims found already false against the tree; four are OH-149's to fix, the rest are recorded there as their own units of work. Proof so far: all 11 check_facts cases fail on purpose and pass after restore, including the two structural ones -- a sentence rewritten away reports a dead pattern, and a deleted document reports LISTED BUT MISSING rather than skipping.

**Note 2026-08-31:** The KICAD_3D row caught its own checker: writing the URL literal into check_facts.py's git-grep argument made tools/check_facts.py a second home for it, and the check failed the moment the file was staged. Fixed by assembling the needle from fragments rather than excluding the checker's own path -- an exclusion would have blinded the row to a real copy landing there. Same lesson check_licenses records about reading headers rather than whole files.

**Note 2026-08-31:** Landed as 0e517b7. Suite state at commit: 2000 passed, 17 skipped, 4 failed -- none in this ticket's files. Three are tests/rules/test_compose_board_3d.py, which pass in isolation and shift between runs because OH-150 is editing tools/compose_board_3d.py live; one is tests/webui/test_compile.py::test_a_failed_build_leaves_nothing_behind, which globs the shared system temp directory and sees two openhardware-build-* dirs left by another session's builds at 19:25 and 19:28. Both belong to their own tickets and are recorded rather than fixed here.

**Note 2026-09-29:** 2026-09-29, by the OH-174 orchestrator holding this ticket for one change: CLAUDE.md's model paragraph no longer states counts. OH-176 added the 27th board (SparkFun Thing Plus ESP32-C6) and check_facts went red on two of the paragraph's claims (26 boards; the one left out). The counts are derived by OH-175's TWINS section of tools/inventory.py, so the paragraph now points there and claude-md:board-model-split watches the pointer plus the two table errors (a model naming a board that is gone, a board in both tables). The pointer pattern was made to fail on purpose: a lazy match first passed with the block deleted because CLAUDE.md names the same command further down, and was tightened to require the first code block after the sentence. DUPLICATION.md's entry is marked retired.

**Note 2026-09-30:** 2026-09-30, from OH-186 (lane3, not yet on master): import_3d_model.COMPOSED now keeps only the XIAO and Uno entries by hand and appends every manifest .brd row at import time. check_facts._model_and_composed_boards reads COMPOSED by parsing the source with ast, so once OH-186 merges it sees only the hand-kept boards: the claude-md:board-model-split row's phantom and overlap checks will silently stop covering manifest boards. Read the value the importer computes (or the composer's COMPOSITIONS) instead of the literal, and make the row fail once on a manifest board in both tables.

**Note 2026-09-30:** 2026-09-30, from OH-186's review: CLAUDE.md's OH-106 paragraph says the pin-1 check has 'Six packages qualify and the closest wins by 1.6 mm', and the next paragraph '23 of the 43 packages placed'; the reviewer measured 15 qualifying packages, several not decided by 1.6 mm, and the 43 has grown with every composed manifest board. Same class as the board-model paragraph this ticket already fixed: point the reader at compose_board_3d.py --check's printed counts instead of stating them, and retire or re-point any fact row that watches them.

**Note 2026-09-30:** 2026-09-30, from OH-186: cutting the counts in compose_board_3d.mark_turns' docstring (six packages, 1.6 mm) staled check_facts' claude-md:mark-turns anchor and failed test_every_anchor_names_a_function_that_exists_and_is_confirmed, so OH-186 restored them. The counts are stale (the review measured 15 qualifying packages). Whoever takes this: cut them from both the docstring and CLAUDE.md, re-read both sides, and re-confirm the anchor with check_facts.py --confirm claude-md:mark-turns (it writes tools/facts_store.json, this ticket's).

**Note 2026-09-30:** 2026-09-30, from OH-191: the composed Uno now reads Arduino's schematic too, so CLAUDE.md:117 ('It needs the vendor's .brd') should say it needs the .brd and the .sch from the same CAD zip. Also from that review: three tests in tests/rules/test_compose_board_3d.py (~854, ~1720, ~1793) write scratch files beside vendor files in third_party/seeed-pcb, so parallel test runs race.

**Note 2026-09-30:** 2026-09-30, by the orchestrator: check_facts._model_and_composed_boards now imports import_3d_model's MODELS and COMPOSED instead of parsing the literal (test_the_composed_boards_include_every_manifest_board_the_composer_takes, red when manifest boards drop out); CLAUDE.md's pin-1 counts replaced by a pointer to compose_board_3d.py --check. Left: the mark_turns docstring's counts (compose_board_3d.py, on loan to the composer lane; re-confirm claude-md:mark-turns after cutting them), and CLAUDE.md's Uno sentence once OH-191 (the Uno reads its .sch) merges.

**Note 2026-09-30:** 2026-09-30: the review of 4243d9c found its new CLAUDE.md pointer false (--check prints no qualifying packages or margins) and an unverified universal left in; fixed in the next commit, each remaining claim checked against compose_board_3d.py's print statements. The earlier commit message's 'every composed board moved the counts' was not measured and is withdrawn.
