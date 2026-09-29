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
