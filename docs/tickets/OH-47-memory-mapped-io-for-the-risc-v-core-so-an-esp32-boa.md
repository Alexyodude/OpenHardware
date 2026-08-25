---
id: OH-47
title: Memory-mapped IO for the RISC-V core, so an ESP32 board can be described
status: open
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/mmio.md
- core/riscv32/machine.py
---

The seven ESP32-C boards sit exactly where the SAMD21 sat before OH-39: core built, no board description, not runnable. The difference is that the SAMD21 needed only a file, and these need a mechanism first.

core/riscv32 has NO MMIO at all -- no map_register, no map_alias, no map_constant, no map_stream, no map_counter. Its Cpu offers add_region and the block accessors and nothing else, so a board description written against it would have nothing to map a peripheral onto. Mapping peripheral space as a plain region is not an option and is the specific thing core/cortexm0/cpu.h argues against at length: a window that reads as written turns every wait-for-ready poll into an infinite loop.

Port the five behaviours core/cortexm0 grew, in the order they were forced there rather than all at once: map_register and map_alias are what a GPIO blink needs; map_constant, map_stream and map_counter came later from a UART and a timer and should wait for the same demand. Sub-word access matters more here than it did on Arm -- ESP32 peripheral registers are word-accessed, but the ESP32-C3 GPIO block uses W1TS/W1TC set/clear registers, which is exactly map_alias.

BLOCKED, and on a claim rather than on the work: core/riscv32/** is claimed by OH-44, which is a live extension programme -- its body sequences Zbb, then Zbkb, then the Zc* group. This ticket claims only a placeholder path so it can exist without colliding. Whoever picks it up must coordinate with OH-44 first; two sessions in one core's cpu.h is precisely what rules/ticket-claims.md exists to prevent.

Done when an ESP32-C3 GPIO register can be mapped, written and read back, an unmodelled address in the same peripheral still faults, and the behaviours have the tests core/cortexm0's did.

**Note 2026-08-25:** Widened 2026-08-25 to include core/riscv32/machine.py. OH-52 changed what a board needs of a core: webui/api.py now resolves core.<core>.machine for blank/refuses/write/enter/view/readable/read/word, and webui/boards/contract.py asks that module what a board owes. So MMIO alone no longer makes a RISC-V board loadable -- contract.core_requirements('riscv32') currently RAISES, by design, saying the core cannot host a board. See core/cortexm0/machine.py and core/avr/machine.py for the two shapes, and note the AVR one exists to prove the interface is not Arm-specific.
