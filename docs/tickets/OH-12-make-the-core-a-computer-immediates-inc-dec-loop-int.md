---
id: OH-12
title: 'Make the core a computer: immediates, INC/DEC, LOOP, INT, and the rest of
  the 8086'
status: open
priority: P1
owner: session/isa
created: '2026-08-23'
touches:
- core/i8086/decode.*
- core/i8086/exec_core.*
- core/i8086/CMakeLists.txt
- tests/i8086/test_isa_rest.py
- tests/i8086/test_abi.py
---

OH-1 through OH-4 built a rigorously verified instruction EXECUTOR: 997,000 hardware cases at 100% across 122 opcode files. It is not yet a computer, and OH-7's UI is not worth building on top of it until it is.

110 of 256 opcodes are implemented. Every one of the 997,000 verified cases is a single instruction executed from a freshly loaded state -- the core has never run a two-instruction sequence, because it cannot: there is no way to load a constant into a register, compare against one, increment, or loop.

Missing, grouped by what they unblock:

  immediates   04-3D (ALU acc,imm), 80/81/82/83 (ALU r/m,imm),
               A8/A9 (TEST imm), B0-BF (MOV reg,imm), C6/C7 (MOV r/m,imm),
               A0-A3 (MOV acc,moffs)
  counting     40-4F (INC/DEC r16), FE (group 4), FF (group 5, which also
               carries CALL/JMP/PUSH r/m)
  control      E0-E3 (LOOPNE/LOOPE/LOOP/JCXZ), CD/CC/CE/CF (INT n, INT3,
               INTO, IRET), 9A/EA (far CALL/JMP), C2/CA/CB (RET imm, RETF)
  the rest     8D LEA, 8C/8E segment moves, 06-1F segment PUSH/POP,
               86/87 XCHG r/m, 91-97 XCHG AX, 98/99 CBW/CWD, 9C-9F
               PUSHF/POPF/SAHF/LAHF, 8F POP r/m, D7 XLAT, F4 HLT

Build in the same verified slices OH-4 used, one family at a time against the corpus, and finish by running an actual program end to end -- which is the one thing no test in this repository has ever done.

Note F4 (HLT) has no corpus file: it cannot be single-stepped on the capture rig. It needs a test written by hand and a note saying the oracle is silent on it.

Note the interrupt sequence already exists as RaiseInterrupt in core/i8086/exec_core.cc and is verified by AAM and DIV. INT n and IRET should use it, and OH-5 should lift it into interrupt.* rather than any of this duplicating it.
