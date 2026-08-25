---
id: OH-64
title: A Cortex-M4 interpreter and the two nRF52840 boards, which need an oracle first
status: open
priority: P2
created: '2026-08-26'
touches:
- core/cortexm0/exec.cc
- core/cortexm0/cpu.h
- webui/boards/nrf52840.py
- tests/cortexm0/test_thumb2_disasm.py
- tests/cortexm0/m4/*
---

TWO OF THE FOURTEEN BOARDS THAT DO NOT RUN. XIAO-nRF52840-DIP and -SMD, chip nRF52840, core cortexm4. This is OH-50's residual, filed because OH-50 closed on its second Done-when and left the interpreter with no ticket of its own.

HALF THE WORK IS DONE AND COMMITTED. OH-50 built Armv7E-M DECODE behind a Profile gate in core/cortexm0/disasm.py and verified it against objdump over 172,032 wide encodings, 1,260 IT-block renderings and a real compiled Cortex-M4 image at 143 of 143 lines, with zero disagreements (ca38cb7). It also fixed two pre-existing decoder bugs found on the way: pop was never decoded, and the 0xFA dispatch mask was too narrow.

WHAT IS SAFE ABOUT THE CURRENT STATE. core/cortexm0/exec.cc answers Unimplemented with the processor completely untouched for every Thumb-2 prefix, checked across all seven groups by test_the_interpreter_refuses_every_thumb2_prefix. A Cortex-M4 image loaded today stops on its first wide instruction and names it. **That test FAILS the day somebody writes the interpreter, and that is intended** -- it is the list of things that must start working.

WHY IT IS BLOCKED, and this is the whole reason OH-50 stopped. There is no execution oracle. QEMU is not installed here -- verified twice: no qemu-system-arm, no PlatformIO package, nothing in Program Files -- and docs/architectures.md records that even where it exists QEMU is a SINGLE source for cortex-m4 with no independent second, so a disagreement could be detected and not adjudicated. That is the same bar OH-38 refuses the Xtensa work on.

WHAT WOULD UNBLOCK IT, in the order they are worth trying: a second independent Armv7E-M implementation to put beside QEMU, hand-written from DDI0403 the way rp2040js is from DDI0419 -- rp2040js's author is already this repository's oracle for Armv6-M and for AVR; or real hardware, since an nRF52840 board with a debug probe is a hardware-captured source and outranks both; or a published conformance vector set, if one exists that is not derived from the same archive both candidates are.

DO NOT WRITE webui/boards/nrf52840.py FIRST. OH-50 left it out deliberately and said why: writing it would make two boards report runnable while an image on either stops at its first wide instruction, which is the claim-you-cannot-keep failure rules/board-claims.md exists to prevent. The board description belongs WITH the interpreter, in this ticket, not before it.

CLAIM NARROWED 2026-08-26. This used to claim tests/cortexm0/* whole, which swept in tests/cortexm0/test_conformance.py -- the Armv6-M corpus run, which belongs to OH-17 and has nothing to do with Armv7E-M. Narrowed to the two paths this ticket's own work actually needs.

Done when a Cortex-M4 image executes in lockstep against an oracle that is not QEMU alone, when webui/boards/nrf52840.py lands beside it, and when catalogue.FIRMWARE_VERIFIED names a test that watched a real image run on an nRF52840.
