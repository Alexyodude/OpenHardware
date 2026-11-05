---
id: OH-64
title: A Cortex-M4 interpreter and the two nRF52840 boards, which need an oracle first
status: in-progress
priority: P2
owner: oh-64-worktree
created: '2026-08-26'
touches:
- webui/boards/nrf52840.py
- tests/cortexm0/test_thumb2_disasm.py
- tests/cortexm0/m4/*
- docs/tickets/OH-64-*
- core/cortexm0/exec.cc
- core/cortexm0/exec.h
- core/cortexm0/cpu.h
- core/cortexm0/cpu.cc
- core/cortexm0/abi.h
- core/cortexm0/abi.cc
- core/cortexm0/abi.py
- core/cortexm0/thumb2.cc
- core/cortexm0/CMakeLists.txt
- tools/m4_oracle.py
- tests/cortexm0/test_thumb2_exec.py
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- tests/webui/test_nrf52840_board.py
- docs/architectures.md
- core/cortexm0/thumb2.h
- tests/webui/nrf52840/*
- tests/rules/test_import_pindefs.py
- tools/import_pindefs.py
- webui/boards/XIAO-nRF52840-DIP.json
- webui/boards/XIAO-nRF52840-SMD.json
- tests/webui/test_pin_view.py
---

TWO OF THE FOURTEEN BOARDS THAT DO NOT RUN. XIAO-nRF52840-DIP and -SMD, chip nRF52840, core cortexm4. This is OH-50's residual, filed because OH-50 closed on its second Done-when and left the interpreter with no ticket of its own.

HALF THE WORK IS DONE AND COMMITTED. OH-50 built Armv7E-M DECODE behind a Profile gate in core/cortexm0/disasm.py and verified it against objdump over 172,032 wide encodings, 1,260 IT-block renderings and a real compiled Cortex-M4 image at 143 of 143 lines, with zero disagreements (ca38cb7). It also fixed two pre-existing decoder bugs found on the way: pop was never decoded, and the 0xFA dispatch mask was too narrow.

WHAT IS SAFE ABOUT THE CURRENT STATE. core/cortexm0/exec.cc answers Unimplemented with the processor completely untouched for every Thumb-2 prefix, checked across all seven groups by test_the_interpreter_refuses_every_thumb2_prefix. A Cortex-M4 image loaded today stops on its first wide instruction and names it. **That test FAILS the day somebody writes the interpreter, and that is intended** -- it is the list of things that must start working.

WHY IT IS BLOCKED, and this is the whole reason OH-50 stopped. There is no execution oracle. QEMU is not installed here -- verified twice: no qemu-system-arm, no PlatformIO package, nothing in Program Files -- and docs/architectures.md records that even where it exists QEMU is a SINGLE source for cortex-m4 with no independent second, so a disagreement could be detected and not adjudicated. That is the same bar OH-38 refuses the Xtensa work on.

WHAT WOULD UNBLOCK IT, in the order they are worth trying: a second independent Armv7E-M implementation to put beside QEMU, hand-written from DDI0403 the way rp2040js is from DDI0419 -- rp2040js's author is already this repository's oracle for Armv6-M and for AVR; or real hardware, since an nRF52840 board with a debug probe is a hardware-captured source and outranks both; or a published conformance vector set, if one exists that is not derived from the same archive both candidates are.

DO NOT WRITE webui/boards/nrf52840.py FIRST. OH-50 left it out deliberately and said why: writing it would make two boards report runnable while an image on either stops at its first wide instruction, which is the claim-you-cannot-keep failure rules/board-claims.md exists to prevent. The board description belongs WITH the interpreter, in this ticket, not before it.

CLAIM NARROWED AGAIN 2026-08-26, off core/cortexm0/exec.cc and core/cortexm0/cpu.h. OH-67 needs both to add SysTick and exception entry, which is unblocked work standing directly in front of the P1 top ticket, and this ticket is blocked on an oracle it does not have and cannot use either file meanwhile. rules/ticket-claims.md is clear that blocked still owns, so the claim is released deliberately rather than ignored: the day an Armv7E-M oracle exists, re-add both here, because an interpreter really does live in them. Nothing about the M4 work changes -- what changes is that a stalled claim is no longer holding a file that another ticket can use today.

CLAIM NARROWED 2026-08-26. This used to claim tests/cortexm0/* whole, which swept in tests/cortexm0/test_conformance.py -- the Armv6-M corpus run, which belongs to OH-17 and has nothing to do with Armv7E-M. Narrowed to the two paths this ticket's own work actually needs.

Done when a Cortex-M4 image executes in lockstep against an oracle that is not QEMU alone, when webui/boards/nrf52840.py lands beside it, and when catalogue.FIRMWARE_VERIFIED names a test that watched a real image run on an nRF52840.

**Note 2026-08-30:** the claim on `webui/boards/nrf52840.py` is DELIBERATE and
the file does not exist, so `tools/check_ticket_claims.py` calls it a likely
typo. It is not. The ticket's own "DO NOT WRITE webui/boards/nrf52840.py
FIRST" paragraph is the reason: the board description belongs with the
interpreter, and holding the name is what stops it being written before the
oracle exists. Recorded so the checker's wording does not get somebody to
"fix" the claim.

Still blocked on the same thing, re-checked 2026-08-30: there is no Armv7E-M
execution oracle here, and QEMU alone would be a single source even if it were
installed.

**Note 2026-11-05:** Oracle found 2026-11-05: Unicorn 2.1.4 (QEMU lineage) and icicle-emu 0.0.11 (Rust, Ghidra SLEIGH lineage) both run thumbv7em and pip-install on Python 3.14. Two independent implementations, so 'not QEMU alone' is met. Both are TOOL dependencies (the cadquery-ocp precedent): tools/m4_oracle.py runs each case under both, keeps only agreement, and the vectors and traces are committed under tests/cortexm0/m4/ so the test cannot skip. Claims re-added on exec.cc and cpu.h as this ticket said to; abi.py lent by OH-161, catalogue.py and its test by OH-210.

**Note 2026-11-05:** Lockstep findings, each recorded where it is enforced: icicle-emu 0.0.11 keeps C on a rotated modified-immediate constant where the manual (and Unicorn) set it to bit 31, so the vectors keep only cases where the two agree and a hand-written test holds the rule (thumb2.cc, expand_immediate). Encodings the architecture calls UNPREDICTABLE are filtered out of the vectors rather than matched, since two emulators agreeing on one is no evidence (tools/m4_oracle.py). Unicorn does not count an IT as an instruction, so IT-block cases run it to an end address (m4_oracle.py's header). A pending exception is held until an IT block ends, because this core stacks only NZCV and not ITSTATE (exec.cc, before ServicePending). No alignment checks, as on the V6M core; LDM/STM/LDRD/STRD unaligned would UsageFault on silicon and do not here (thumb2.cc).

**Note 2026-11-05:** Shape: the M4 is an Armv7E-M profile of core/cortexm0, with Thumb-2 in thumb2.cc, not a new core/cortexm4 tree. Cpu::map_field (cpu.h) is the one new memory-map primitive: a word whose bit 0 lives in another register's bit, which is what nRF52840 PIN_CNF.DIR is to DIR. The refusal test is test_what_the_interpreter_refuses_it_refuses_untouched. tests/webui/nrf52840/blink.bin sits beside test_nrf52840_board.py, which FIRMWARE_VERIFIED names. The on-board LEDs went into tools/import_pindefs.py's on_board so they land in HEADER, because api.level_keys reads HEADER only.

**Note 2026-11-05:** Lent files, returned when OH-64 lands: abi.py and tests/webui/test_pin_view.py from OH-161; webui/boards/catalogue.py and tests/webui/test_board_catalogue.py from OH-210; tools/import_pindefs.py and tests/rules/test_import_pindefs.py from OH-172. Filed from this work: OH-270 (UDF on v6-M branches), OH-271 (FPU), OH-272 (refused Thumb-2 groups), OH-273 (nRF52840 peripherals for an SDK image), OH-274 (GPIO IN, PIN_CNF reset), OH-275 (Seeed LED polarity), OH-276 (test_import_pindefs on a partial fetch). Ids 254-269 were skipped because another session was filing into that range at the time.
