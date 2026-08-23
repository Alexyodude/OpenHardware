---
id: OH-7
title: 'Emulator UI: registers, flags, memory, disassembly'
status: open
priority: P1
owner: session/ui
created: '2026-08-23'
touches:
- webui/static/emulator.*
- webui/emulator.py
- tests/webui/test_emulator.py
---

The application surface: load a binary, step and run, watch state change. Talks to the core, not to PICSimLab.
