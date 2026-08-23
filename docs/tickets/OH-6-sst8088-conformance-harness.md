---
id: OH-6
title: SST8088 conformance harness
status: done
priority: P0
owner: session/harness
created: '2026-08-23'
touches:
- tests/i8086/conformance.py
- tests/i8086/test_conformance.py
---

Drives the core directly rather than through rcontrol, which has no register-write command. Reports pass rate per opcode.

**Note 2026-08-23:** Harness runs, tested against deliberately-correct and deliberately-wrong stand-ins. Baseline against the committed excerpt is 0/11, which is correct: nothing executes until OH-3.

**Note 2026-08-23:** CI run 32635052721 green: harness suite passed on Linux and the baseline step printed the rate.
