---
id: OH-36
title: A Cortex-M33 core for the eight Armv8-M boards, and the oracle it does not
  have
status: blocked
priority: P2
created: '2026-08-25'
touches:
- core/cortexm33/**
- tests/cortexm33/**
---

Eight boards -- XIAO RP2350, MG24, nRF54l15 and nRF54LM20A, two package variants each -- are Armv8-M and none can run anything. That is the largest single block of dead boards in the repository, and it is deliberately not first, because catalogue.py's ORACLES says why: 'none free that models Armv8-M security extensions; QEMU has m33 but not the RP2350's Hazard3 half.'

State the oracle gap up front rather than discovering it at lockstep. QEMU's cortex-m33 covers the baseline and is a single source, so a disagreement could not be adjudicated -- the same objection recorded against cortexm4. TrustZone-M has no free reference at all. And the RP2350 is two architectures on one die: an Armv8-M core and a Hazard3 RV32, either of which may be running.

So scope this to what can actually be verified: the non-secure baseline, against QEMU, with the security extensions absent rather than approximated. A core that implements SAU and MPU banking with nothing to check them against is a core nobody can trust, and the repository's habit is to refuse rather than to imply.

The RP2350's RISC-V half may reach through the RV32 core instead. Whether that is a cheaper route to a running RP2350 than Armv8-M is worth answering before starting.

Done when a compiled non-secure image runs in lockstep with QEMU, the security extensions are documented as unimplemented rather than stubbed, and the single-source limitation is recorded where a future reader will hit it.

**Note 2026-08-25:** BLOCKED and split, on this ticket's own checkpoint evidence, verified independently. TWO blockers, not one. (a) No oracle: qemu-system-arm absent, and it cannot be built here -- QEMU needs meson plus GCC or Clang and all four are absent; MSVC 14.44 is the only C compiler. The rvcpp shim that saved OH-34 was 13 lines over a 1,080-line single-file simulator and does not scale to a build system of hundreds of translation units. (b) No image: arm-none-eabi-gcc is absent, and unlike cortexm0 there is no committed Armv8-M artefact -- test_blink.py's header records that its 76-byte blink.bin was compiled elsewhere precisely so the test runs without a toolchain. So even a QEMU binary appearing tomorrow leaves nothing to feed it but hand-assembled instructions. The ticket's own single-source objection survives both. SPLIT: the RP2350's two boards go through their RISC-V door as OH-42, which the user has chosen; the remaining six -- MG24 x2, nRF54l15 x2, nRF54LM20A x2 -- have no RISC-V door and stay blocked here until someone decides to fetch a prebuilt QEMU and an ARM toolchain. That is a decision about third-party binaries, not a coding step. docs/architectures.md 5.4 'RP2350 -- two doors, one much cheaper' already reached this conclusion before the ticket was filed.
