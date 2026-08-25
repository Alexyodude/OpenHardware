---
id: OH-47
title: Memory-mapped IO for the RISC-V core, so an ESP32 board can be described
status: open
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/mmio.md
---

The seven ESP32-C boards sit exactly where the SAMD21 sat before OH-39: core built, no board description, not runnable. The difference is that the SAMD21 needed only a file, and these need a mechanism first.

core/riscv32 has NO MMIO at all -- no map_register, no map_alias, no map_constant, no map_stream, no map_counter. Its Cpu offers add_region and the block accessors and nothing else, so a board description written against it would have nothing to map a peripheral onto. Mapping peripheral space as a plain region is not an option and is the specific thing core/cortexm0/cpu.h argues against at length: a window that reads as written turns every wait-for-ready poll into an infinite loop.

Port the five behaviours core/cortexm0 grew, in the order they were forced there rather than all at once: map_register and map_alias are what a GPIO blink needs; map_constant, map_stream and map_counter came later from a UART and a timer and should wait for the same demand. Sub-word access matters more here than it did on Arm -- ESP32 peripheral registers are word-accessed, but the ESP32-C3 GPIO block uses W1TS/W1TC set/clear registers, which is exactly map_alias.

BLOCKED, and on a claim rather than on the work: core/riscv32/** is claimed by OH-44, which is a live extension programme -- its body sequences Zbb, then Zbkb, then the Zc* group. This ticket claims only a placeholder path so it can exist without colliding. Whoever picks it up must coordinate with OH-44 first; two sessions in one core's cpu.h is precisely what rules/ticket-claims.md exists to prevent.

Done when an ESP32-C3 GPIO register can be mapped, written and read back, an unmodelled address in the same peripheral still faults, and the behaviours have the tests core/cortexm0's did.
