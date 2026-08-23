---
id: OH-14
title: A page listing every chip on the board list and its emulation status
status: open
priority: P2
created: '2026-08-24'
touches:
- webui/static/targets.html
---

docs/architectures.md is 642 lines of prose and tables. The question people actually ask of it -- which chips are we emulating, what would each cost, and is there an oracle -- needs a page you can scan, not a document you read. Serve it from the existing emulator server: resolve_static already serves any .html under static/, so this needs no server change. The page must carry an evidence class per claim (ran-here / datasheet / toolchain-only / conflict / none) because the survey's own value is that it does not average contradictions away.
