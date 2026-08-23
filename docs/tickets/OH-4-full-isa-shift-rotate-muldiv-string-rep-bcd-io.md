---
id: OH-4
title: 'Full ISA: shift/rotate, muldiv, string, rep, bcd, io'
status: open
priority: P1
owner: session/isa
created: '2026-08-23'
touches:
- core/i8086/exec_full.*
- tests/i8086/test_isa_full.py
---

Slice 2d. Includes flag.undefined, whose documented-undefined results are only knowable from hardware -- which is what the oracle is.
