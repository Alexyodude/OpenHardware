---
id: OH-21
title: Full 16-bit Thumb, a real memory map, and lockstep against rp2040js on real
  firmware
status: in-review
priority: P1
created: '2026-08-24'
touches:
- core/cortexm0/**
- tests/cortexm0/**
- tools/lockstep_armv6m.mjs
---

_No description yet._

**Note 2026-08-24:** Full 16-bit Thumb (formats 5-19: loads, stores, branches, push/pop, high regs, BL, STM/LDM, SXT/UXT/REV, hints), a two-region memory map (flash 0x10000000 + SRAM 0x20000000), fault-address reporting, and an explicit MMIO register mechanism.

MEASURED ON REAL FIRMWARE (.pio/build/pico/firmware.uf2, Arduino blink):
  - lockstep vs rp2040js: 100,000 of 100,000 instructions matched EXACTLY, all 16 registers and flags, with one peripheral read (SIO CPUID) satisfied from the oracle.
  - standalone with only 0xD0000000 mapped: 225,723 instructions before reaching 0x4000E000.
  - 0x4000E000 is RESETS base + 0x2000 = the RP2040 atomic-SET alias. That is the exact next thing to build, and docs/research/peripheral-layer/ already has RESETS/XOSC/PLL/CLOCKS/IO_BANK0/PADS_BANK0 regmaps plus the atomic_aliases design.

REAL BUG FOUND BY A UNIT TEST, not by the corpus and not by 100k firmware instructions: 'advance PC only if it changed' cannot see 'B .', a branch to itself, because its target equals its own address. B . is the idle loop at the end of most firmware AND the body of the default fault handler, so the core stepped straight past a stopped program. Fixed by advancing PC before executing and letting branches overwrite it; failure restores PC so the untouched-on-error contract holds.

The peripheral profiler (tools/lockstep_armv6m.mjs --profile-peripherals) had to patch the CORE's bus methods, not the RP2040's: wrapping only the machine caught 1 access in 200,000 instructions and made busy firmware look idle.

MMIO is reads-as-written on EXPLICITLY REGISTERED addresses only; everything else still faults. Not a peripheral window reading as zero -- that turns every wait-for-ready poll into a silent infinite loop. The mechanism is in the core; the map is not, so core/cortexm0 never learns a chip's memory map.

STILL NOT A WORKING BOARD: no peripherals, so no GPIO toggle, no timers, no UART. Next: RESETS with atomic aliases, then CLOCKS/XOSC/PLL, then SIO GPIO.

Noted, not done: gen_armv6m_tests.mjs covers formats 1-4 only, so 5-19 rest on the lockstep run plus tests/cortexm0/test_program.py; the firmware is a build artefact and not in the repo, so that run is not a repeatable test.
