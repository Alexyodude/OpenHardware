---
id: OH-3
title: 'Core ISA: mov, arithmetic, logic, stack, control flow'
status: in-progress
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

**Note 2026-08-23:** Partially done 2026-08-23. Landed: NOP, MOV r/m8 r8 (0x88), ADD r/m8 r8 (0x00), the byte register file, and Add8 with CF/AF/OF/ZF/SF/PF verified exhaustively over all 65,536 operand pairs. NOT done and still in scope: logic (AND/OR/XOR), stack (PUSH/POP), control flow (JMP/Jcc/CALL/RET), the 16-bit forms of everything, and the other MOV and ADD encodings. Conformance is 11/11 only against the committed eleven-case excerpt -- that is three opcodes, not the ISA.
