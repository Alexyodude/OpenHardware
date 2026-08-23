---
id: OH-6
title: SST8088 conformance harness
status: open
priority: P0
owner: session/harness
created: '2026-08-23'
touches:
- tests/i8086/conformance.py
- tests/i8086/test_conformance.py
---

Drives the core directly rather than through rcontrol, which has no register-write command. Reports pass rate per opcode.
