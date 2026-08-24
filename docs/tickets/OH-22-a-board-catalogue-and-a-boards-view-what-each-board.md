---
id: OH-22
title: 'A board catalogue and a Boards view: what each board is and whether it runs'
status: done
priority: P1
created: '2026-08-25'
touches:
- webui/boards/**
- tests/webui/test_board_catalogue.py
- webui/emulator_server.py
- webui/static/emulator.html
- webui/static/emulator.js
---

_No description yet._

**Note 2026-08-25:** Board catalogue + Boards view landed and APPROVED by architect review after three rounds (REJECTED -> REJECTED narrow -> APPROVED). All 9 findings repaired. Residuals R7/R8 also closed: SIO write-only registers now read as zero (was returning GPIO_OUT -- the only defect that answered wrongly rather than loudly), and the blink drift guard resolves the toolchain from PATH instead of one user's home.
