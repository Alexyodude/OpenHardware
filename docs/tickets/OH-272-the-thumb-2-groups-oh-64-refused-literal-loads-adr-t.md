---
id: OH-272
title: 'The Thumb-2 groups OH-64 refused: literal loads, ADR, TBB/TBH, the exclusives,
  the system group and DSP'
status: open
priority: P2
created: '2026-11-05'
---

Found 2026-11-05 under OH-64, which built the integer Thumb-2 core against Unicorn 2.1.4 and icicle-emu 0.0.11 and refused, by returning Unimplemented, what the oracle never vectored (core/cortexm0/thumb2.cc's file note; m4_oracle.REFUSED):

- PC-relative LDR.W Rt, [PC, #imm12] and ADR: the oracle's code page is execute-only, and the two emulators disagree about reading it. GCC's literal pools put these in nearly every image.
- TBB/TBH: GCC emits them for a dense switch.
- LDREX/STREX/CLREX: every RTOS and C11 atomic.
- The system group: MSR, MRS, CPSID/CPSIE wide forms, DSB/DMB/ISB, NOP.W, WFI/WFE/SEV wide forms. CMSIS startup and every SDK's SystemInit reach for these.
- The DSP extension: saturating and SIMD arithmetic, SSAT/USAT, PKH.

Each needs vectors of its own before it can be trusted: for the literal loads, map the oracle's code page readable and record where the emulators part. Done when each group is vectored and runs in lockstep, or is refused with a reason in m4_oracle.REFUSED, one group per commit. Needs OH-64.
