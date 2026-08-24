---
id: OH-19
title: Target selection in the UI, driven by which cores are actually built
status: done
priority: P1
created: '2026-08-24'
touches:
- webui/targets.py
- tests/webui/test_targets.py
- webui/emulator_server.py
- webui/static/emulator.html
- webui/static/emulator.js
- webui/static/emulator.css
- tests/webui/test_emulator.py
---

_No description yet._

**Note 2026-08-24:** Landed: webui/targets.py computes target status from core/<n>/CMakeLists.txt (the same test build_core.cores() uses) plus the presence of the built library; GET /api/targets and POST /api/target on the emulator server; a target selector in the toolbar and a generated 'Runnable now' panel at the top of the Targets view. 19 tests in tests/webui/test_targets.py, four mutations proven to fail. Browser-verified in both themes, including the UNBUILT path via a temporary core/cortexm0/. Selection is REFUSED for anything not ready rather than accepted-and-disabled. Surveyed chips are deliberately NOT in the selector: an option you can never pick is a promise the repo has not made. Noted, not done: renderStatus says '1 steps' (pre-existing grammar bug, adjacent to this work); the selector stays disabled until a second core exists, since there is nothing to switch to.
