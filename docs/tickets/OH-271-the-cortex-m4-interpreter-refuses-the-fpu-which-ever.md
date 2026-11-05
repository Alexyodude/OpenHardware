---
id: OH-271
title: The Cortex-M4 interpreter refuses the FPU, which every Seeed Arduino nRF52840
  sketch is built for
status: open
priority: P2
created: '2026-11-05'
---

Found 2026-11-05 under OH-64. The nRF52840 is a Cortex-M4F. core/cortexm0/thumb2.cc refuses the coprocessor and FPU space, and m4_oracle.REFUSED lists it, so the test image (tests/webui/nrf52840/blink.c) is built -mfloat-abi=soft. Seeed's own core is not: platform.txt in Seeed-Studio/Adafruit_nRF52_Arduino @ 667f05f sets build.float_flags=-mfloat-abi=hard -mfpu=fpv4-sp-d16, so a sketch built for the board by its vendor's toolchain stops at the first VFP instruction, and its startup writes CPACR before main.

Done when: FPv4-SP single precision -- the data-processing group, VLDR/VSTR/VPUSH/VPOP, VMOV between core and extension registers, VMRS/VMSR and FPSCR -- is vectored by tools/m4_oracle.py against Unicorn and icicle and executes in lockstep; CPACR gates it (a VFP instruction with CP10/CP11 off faults or stops, as the architecture says); exception-entry stacking of the FP context is implemented or refused by name. Needs OH-64's interpreter.
