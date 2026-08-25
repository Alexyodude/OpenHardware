---
id: OH-50
title: A Cortex-M4 core for the two nRF52840 boards
status: done
priority: P2
created: '2026-08-25'
touches:
- core/cortexm0/disasm.py
- tests/cortexm0/test_thumb2_disasm.py
- tests/cortexm0/m4/probe.c
- tests/cortexm0/m4/probe.ld
- tests/cortexm0/m4/probe.bin
- tools/sweep_thumb2.py
---

NOT OH-36, which tools/tickets.py flagged this against at 0.50 -- the resemblance is the title's phrasing, not the work. OH-36 is Armv8-M for eight boards and its blocker is that nothing free models the security extensions. This is Armv7E-M for two, and Armv7E-M is a strict SUPERSET of the Armv6-M already implemented, so it starts from working code rather than from nothing.

Two boards: XIAO-nRF52840-DIP and -SMD. The 16-bit Thumb map and its shift-carry rules carry over from core/cortexm0 unchanged; the work is Thumb-2 -- the 32-bit encodings, IT blocks, and the load/store forms gcc emits at -Os.

The oracle is the problem and it belongs in the ticket rather than in a surprise halfway through. docs/architectures.md records QEMU as having cortex-m4 with NO independent second source, so a disagreement could not be adjudicated. And QEMU is not installed here at all -- verified 2026-08-25. There is currently no way to lockstep this core against anything.

What IS available, both verified the same day: arm-none-eabi with thumb/v7e-m multilib, so real Cortex-M4 firmware compiles here; and core/cortexm0/disasm.py with its objdump comparison, which is a real oracle for the DECODE half and extends to Thumb-2 unchanged in method -- OH-45 checked 56,551 encodings that way.

That asymmetry should shape the work: the decode can be checked exhaustively and the execution cannot be checked at all until an oracle exists. Do not start the interpreter expecting to verify it the way cortexm0 was verified.

Consider extending core/cortexm0 rather than adding a directory. Armv7E-M really is a superset, and one Thumb-16 implementation is one truth instead of two that drift -- against which, webui/boards/catalogue.py keys a board to a core NAME, and 'cortexm0' is the name the RP2040 and SAMD21 rows already use.

Done when a real compiled Cortex-M4 image runs, or when this ticket records why it cannot be verified and stops there.

**Note 2026-08-25:** Closed 2026-08-25 (ca38cb7) on this ticket's SECOND Done-when: the decode is
built and verified, the execution is not, and the reason is recorded.

SHAPE. Extended core/cortexm0 with a Profile rather than adding core/cortexm4,
so the stale core/cortexm4/* and tests/cortexm4/* claims are removed above.
The precedent is core/riscv32, which already gates instruction LENGTH on a
configured extension and is firmware-verified on three chips.

WHAT THE TICKET UNDERSTATED. "Armv7E-M is a strict superset" is true of the
instruction set and misleading about the work, twice over:

(a) The LENGTH RULE differs and sits upstream of everything. exec.cc used
    (enc & 0xF800) == 0xF000 -- Armv6-M's rule, where BL is the only wide
    instruction. Armv7-M has three wide prefixes. And the failure is not loud:
    0xE8B0 read as narrow leaves 0x0006 next, which is a real `movs r6, r0`,
    so an Armv6-M reading of an M4 image is a plausible listing shifted by two
    bytes rather than obvious rubbish.

(b) Armv7E-M adds SIXTEEN-BIT encodings too -- CBZ, CBNZ, IT -- in space
    Armv6-M leaves undefined. The profile has to reach the narrow decoder, not
    just the width test. IT additionally needs STATE: it makes the following
    instructions conditional and suppresses their flag-setting, so a
    per-instruction decoder cannot be right about them. disassemble now tracks
    a queue.

EVIDENCE. 172,032 wide encodings and 1,260 IT-block renderings against
arm-none-eabi-objdump with 0 disagreements, plus tests/cortexm0/m4/probe.bin
-- 380 bytes of real compiler output -- disassembling 143 of 143 lines
identically. 84.1% of encodings a Cortex-M4 can actually execute. The gap is
measured, not guessed: 32,112 of what objdump names in this space is NEON,
VFP, generic coprocessor and FPA, none of which a Cortex-M4 has; the real
remaining gaps are the exclusive accesses, the table branches and the memory
hints.

TWO PRE-EXISTING BUGS FOUND. (1) POP never decoded on either profile -- the
push/pop branch tested bits 11:9 where bit 11 is the load bit -- and it
survived tests/cortexm0/test_disasm.py's four-image comparison because none of
those four images contains a POP: they are for(;;) leaves that never return.
(2) The 0xFA dispatch used a four-bit test where DDI0403 uses three, so
0xFA80..0xFAFF was unreachable and clz/rbit/rev.w/revsh.w looked implemented
and were not.

TWO HARNESS BUGS, both found by their own shape. 19,968 disagreements that
were all one constant -- objdump numbers a raw binary from zero, so
--adjust-vma. And the sweep's second-halfword spread reached no encoding with
hw2[7:4] set, so a whole sub-group sat outside it while the summary read 0
wrong; widening it found 91 real disagreements immediately.

WHAT IS SAFE ABOUT SHIPPING A DECODER WITH NO INTERPRETER. core/cortexm0/exec.cc
answers Unimplemented with the processor completely untouched for every Thumb-2
prefix -- verified across all seven groups by
test_the_interpreter_refuses_every_thumb2_prefix. So a Cortex-M4 image stops on
its first wide instruction and names it. That test FAILS the day someone writes
the interpreter, which is intended: it is the list of things that must start
working.

STILL BLOCKED, and this is the whole reason the ticket stops here: there is no
execution oracle. QEMU is not installed (verified: no qemu-system-arm, no
PlatformIO package, nothing in Program Files), and docs/architectures.md
records that even where it exists it is a single source for cortex-m4 with no
independent second -- a disagreement could be detected and not adjudicated.

NOT DONE, deliberately: webui/boards/nrf52840.py. Writing it would make the two
nRF52840 boards report runnable, and an image loaded on one would stop at its
first wide instruction. That is a claim this repository would not keep. A board
description belongs with an interpreter, in whatever ticket gets an oracle
first.
