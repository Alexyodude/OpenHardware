---
id: OH-45
title: An Armv6-M disassembler, checked against objdump
status: done
priority: P1
created: '2026-08-25'
touches:
- core/cortexm0/disasm.py
- tests/cortexm0/test_disasm.py
---

core/i8086 has disasm.py and core/cortexm0 has nothing, which is why the Emulator tab shows a listing for one core and cannot for the other. It is also why a fault on a board reports an address rather than an instruction: 'no implementation for the encoding at 0x10100000' is the right message and it would be a better one if it named the halfword it could not decode.

Cover the same ground exec.cc does -- Thumb-16 formats 1-19 plus the 32-bit BL pair -- because a disassembler that stops short of the interpreter would show blanks in the middle of code the core can run.

The oracle is arm-none-eabi-objdump, and it is a good one: independent, authoritative, already on this machine, and it disassembles the exact committed images this repository already runs. Compare instruction by instruction over tests/cortexm0/blink/blink.bin, tests/cortexm0/samd21/blink.bin, tests/cortexm0/uart/hello.bin and tests/cortexm0/timer/delay.bin -- four real compiler outputs across two chips, several hundred instructions, every one of them checked against a tool nobody here wrote.

Where objdump is absent the comparison SKIPS and never silently passes, the contract every checker in this repository keeps.

Do not invent a text format. Match objdump's operand spelling closely enough that a difference is a real disagreement rather than a formatting argument, and where they must differ, say so in the file.

Done when the four committed images disassemble identically to objdump, and an unimplemented encoding is rendered as its halfword rather than omitted.
