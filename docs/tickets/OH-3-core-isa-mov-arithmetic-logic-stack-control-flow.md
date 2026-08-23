---
id: OH-3
title: 'Core ISA: mov, arithmetic, logic, stack, control flow'
status: in-review
priority: P0
owner: session/isa
created: '2026-08-23'
touches:
- core/i8086/exec_core.*
- core/i8086/alu.*
- tests/i8086/test_isa_core.py
- core/i8086/abi.h
- core/i8086/abi.cc
- core/i8086/abi.py
- tests/i8086/conformance.py
- tests/i8086/test_conformance.py
---

Slice 2c. The opcodes a real program needs first, each verified against SST8088.
