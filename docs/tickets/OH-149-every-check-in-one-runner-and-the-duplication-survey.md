---
id: OH-149
title: Every check in one runner, and the duplication survey it starts from
status: open
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
