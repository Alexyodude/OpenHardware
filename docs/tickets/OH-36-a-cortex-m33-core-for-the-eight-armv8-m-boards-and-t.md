---
id: OH-36
title: A Cortex-M33 core for the eight Armv8-M boards, and the oracle it does not
  have
status: open
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
