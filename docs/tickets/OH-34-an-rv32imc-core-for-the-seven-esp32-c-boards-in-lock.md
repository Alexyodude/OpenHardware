---
id: OH-34
title: An RV32IMC core for the seven ESP32-C boards, in lockstep with rvcpp
status: open
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/**
- tests/riscv32/**
- tools/lockstep_rv32.mjs
---

Seven of the 26 boards here are RV32: XIAO ESP32-C3 (three package variants), C5 (two) and C6 (two). None can execute an instruction. This is the next core after cortexm0, chosen over Cortex-M33's eight boards for one reason -- catalogue.py's ORACLES records that Hazard3's rvcpp (Apache-2.0) builds here, and that Armv8-M has no free oracle modelling the security extensions. Eight unverifiable boards are worth less than seven verifiable ones.

Follow the path cortexm0 took, since it worked: OH-20 built formats 1-4 checked against the corpus, OH-21 widened to full 16-bit Thumb plus a real memory map and lockstep against rp2040js on real firmware, and cd9f8c8 took the memory map back out of the core, where it never belonged. Do not re-earn that last lesson -- core/riscv32 is the architecture and knows no chip; addresses live in the board.

Scope is RV32IMC, the C3's set. C5's Zcb/Zcmp/Zcmt and C6's A extension are later and separately verified; a core that quietly accepts them is worse than one that refuses them.

Done when a compiled image runs in lockstep with rvcpp over real firmware and the two agree instruction for instruction, and when tools/check_layering.py passes with no chip address in the core.

The oracle has a known blind spot, filed separately. Read it before trusting a green run.
