---
id: OH-50
title: A Cortex-M4 core for the two nRF52840 boards
status: open
priority: P2
created: '2026-08-25'
touches:
- core/cortexm4/*
- tests/cortexm4/*
---

NOT OH-36, which tools/tickets.py flagged this against at 0.50 -- the resemblance is the title's phrasing, not the work. OH-36 is Armv8-M for eight boards and its blocker is that nothing free models the security extensions. This is Armv7E-M for two, and Armv7E-M is a strict SUPERSET of the Armv6-M already implemented, so it starts from working code rather than from nothing.

Two boards: XIAO-nRF52840-DIP and -SMD. The 16-bit Thumb map and its shift-carry rules carry over from core/cortexm0 unchanged; the work is Thumb-2 -- the 32-bit encodings, IT blocks, and the load/store forms gcc emits at -Os.

The oracle is the problem and it belongs in the ticket rather than in a surprise halfway through. docs/architectures.md records QEMU as having cortex-m4 with NO independent second source, so a disagreement could not be adjudicated. And QEMU is not installed here at all -- verified 2026-08-25. There is currently no way to lockstep this core against anything.

What IS available, both verified the same day: arm-none-eabi with thumb/v7e-m multilib, so real Cortex-M4 firmware compiles here; and core/cortexm0/disasm.py with its objdump comparison, which is a real oracle for the DECODE half and extends to Thumb-2 unchanged in method -- OH-45 checked 56,551 encodings that way.

That asymmetry should shape the work: the decode can be checked exhaustively and the execution cannot be checked at all until an oracle exists. Do not start the interpreter expecting to verify it the way cortexm0 was verified.

Consider extending core/cortexm0 rather than adding a directory. Armv7E-M really is a superset, and one Thumb-16 implementation is one truth instead of two that drift -- against which, webui/boards/catalogue.py keys a board to a core NAME, and 'cortexm0' is the name the RP2040 and SAMD21 rows already use.

Done when a real compiled Cortex-M4 image runs, or when this ticket records why it cannot be verified and stops there.
