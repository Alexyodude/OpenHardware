---
id: OH-157
title: The RP2350 runs through its Hazard3 half, and needs no new core or oracle
status: open
priority: P1
created: '2026-09-03'
touches:
- webui/boards/rp2350.py
- tests/riscv32/rp2350/**
---

Two of the fourteen dead boards can probably be made to run without a new
core, without a new oracle, and without touching the Cortex-M33 work at all.
Nobody has tried, because the RP2350 sits inside OH-36's Armv8-M block and
that ticket is blocked.

THE RP2350 IS TWO ARCHITECTURES ON ONE DIE. Dual Cortex-M33 and dual Hazard3
RISC-V, whichever is unused held in reset (docs/architectures.md 5.4, marked
[V]). OH-36 says so itself -- "The RP2350's RISC-V half may reach through the
RV32 core instead. Whether that is a cheaper route to a running RP2350 than
Armv8-M is worth answering before starting" -- and then, correctly, does not
answer it, because OH-36 is about Armv8-M. So the question was asked in a
place where nobody would act on it.

EVERYTHING THE RISC-V ROUTE NEEDS ALREADY EXISTS EXCEPT ONE FILE.

* The core: core/riscv32 is built and firmware-verified on four chips
  (ESP32-C3, C5, C6 and, through RP2040 for cortexm0, separately).
* The oracle: rvcpp, Hazard3's OWN 1,080-line C++17 golden model, which this
  repository already ships, builds and runs -- docs/architectures.md 2.1b.
  It is the oracle the whole riscv32 corpus rests on. There is no oracle gap
  here of the kind that blocks Armv8-M, Xtensa and Armv7E-M.
* The ISA: core/riscv32/abi.py already carries a Hazard3 constant, with the
  datasheet's own string cited --
  rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp -- and Zcb and Zcmp
  landed at OH-146.
* The second core: docs/architectures.md 5.5 establishes that core 1 can
  simply not exist. At reset it parks itself and drains its mailbox; nothing
  at boot waits FOR it. The SIO FIFO registers need to exist as stubs that do
  not fault.

WHAT IS MISSING is webui/boards/rp2350.py. catalogue.py reports the RP2350 as
described=NO, and that single fact is why both its boards report unrunnable
while their core is built and their oracle is running. Compare
webui/boards/esp32c6.py, which is the nearest sibling in shape.

STEPS, in the order that keeps each one falsifiable:

1. Answer the cheap question first: does a minimal image built -march=rv32imac
   avoid Zbb and Zbkb entirely? abi.py's own note says those two are NOT
   modelled and that the Hazard3 constant "describes a part that does not
   exist". If a blink needs them, this ticket grows a decoder step; if it
   does not, it does not. Do not assume -- build one and disassemble it.
2. Write webui/boards/rp2350.py: flash and SRAM origins and sizes, and the
   GPIO registers, each cited to the RP2350 datasheet the way esp32c6.py
   cites ESP-IDF's soc.h. Nothing invented; a register whose address is not
   in the datasheet is left unmapped, which is the rule that made the C3's
   GPIO_IN absence honest.
3. Stub the SIO FIFO registers so a single-core image that touches them does
   not fault, and say in the file that core 1 does not exist rather than
   modelling it.
4. Verify the OH-148 way: a named test that watches a real compiled image
   drive the board's own pin, not merely that a loader accepted bytes. The
   RP2350 is composed and its 3D model already draws, so the pin names are
   already correct.

DONE WHEN both XIAO-RP2350 boards report runnable and firmware_verified from
catalogue.py, on the RISC-V half, with the file stating plainly that the
Cortex-M33 half is not modelled and that OH-36 is where that lives.

THIS DOES NOT TOUCH OH-36 and must not. That ticket is held by another
session and claims core/cortexm33/** and tests/cortexm33/**; this one claims
none of them. If this succeeds it makes OH-36 smaller -- seven boards rather
than nine -- and it does not make OH-36 unnecessary, because a real RP2350
boots its Arm half by default and the M33 remains the honest target.
