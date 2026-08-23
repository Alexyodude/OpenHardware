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
