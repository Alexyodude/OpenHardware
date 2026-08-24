---
id: OH-38
title: 'Xtensa LX7 for the ESP32-S3 boards: blocked, because both oracles are the
  same oracle'
status: blocked
priority: P3
created: '2026-08-25'
touches:
- core/xtensa/**
- tests/xtensa/**
---

Three boards here are ESP32-S3 and none can run anything. Filed blocked rather than left unfiled, so the gap is visible on the board instead of being rediscovered by whoever reaches for the S3 next.

The blocker is not effort, it is verification. catalogue.py's ORACLES entry: 'NONE. QEMU-xtensa and binutils-xtensa both derive from the same Tensilica archive via import_core.sh, so their agreement is a tautology (docs/architectures.md 2.1c).' Two references that look independent, one source. A core checked against both would pass every test and prove nothing, which is worse than a core with no tests, because the tests would be believed.

Every other core here rests on a second source that could disagree: cortexm0 on rp2040js hand-written from DDI0419, riscv32 on rvcpp, cortexm33 on QEMU with the single-source limitation recorded. Xtensa has no such thing.

What would unblock it: a hardware-captured trace from a real S3, which makes the silicon the oracle; or a second implementation with a provenance chain that does not reach Tensilica's archive. Either changes the answer. Neither exists today, and PICSimLab's own ESP route runs the vendor's QEMU rather than modelling the ISA -- worth weighing before writing a core at all.

Do not start this by writing a decoder. Start it by finding an oracle, or by deciding the S3 is emulated through the vendor stack instead.
