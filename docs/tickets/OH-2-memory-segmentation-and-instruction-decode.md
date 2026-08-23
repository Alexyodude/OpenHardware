---
id: OH-2
title: Memory, segmentation and instruction decode
status: done
priority: P0
owner: session/decode
created: '2026-08-23'
touches:
- core/i8086/decode.*
- tests/i8086/test_decode.py
- core/i8086/abi.h
- core/i8086/abi.cc
- core/i8086/abi.py
---

Slice 2b. 1 MB space, 20-bit physical addressing, modrm, segment override, displacement, immediate. Segmentation lands early because every later cell depends on it.

**Note 2026-08-23:** Architect review found three items, all fixed: prefix guard misdecoded at 15+ (read a prefix as an opcode); OpcodeHasModRm and the exec switch were two unlinked tables; three docstrings claimed the register order matched the corpus and it does not.
