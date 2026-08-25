---
id: OH-47
title: Memory-mapped IO for the RISC-V core, so an ESP32 board can be described
status: done
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/mmio.md
- core/riscv32/machine.py
- tests/webui/test_board_runtime_contract.py
- tests/riscv32/test_mmio.py
---

The seven ESP32-C boards sit exactly where the SAMD21 sat before OH-39: core built, no board description, not runnable. The difference is that the SAMD21 needed only a file, and these need a mechanism first.

core/riscv32 has NO MMIO at all -- no map_register, no map_alias, no map_constant, no map_stream, no map_counter. Its Cpu offers add_region and the block accessors and nothing else, so a board description written against it would have nothing to map a peripheral onto. Mapping peripheral space as a plain region is not an option and is the specific thing core/cortexm0/cpu.h argues against at length: a window that reads as written turns every wait-for-ready poll into an infinite loop.

Port the five behaviours core/cortexm0 grew, in the order they were forced there rather than all at once: map_register and map_alias are what a GPIO blink needs; map_constant, map_stream and map_counter came later from a UART and a timer and should wait for the same demand. Sub-word access matters more here than it did on Arm -- ESP32 peripheral registers are word-accessed, but the ESP32-C3 GPIO block uses W1TS/W1TC set/clear registers, which is exactly map_alias.

BLOCKED, and on a claim rather than on the work: core/riscv32/** is claimed by OH-44, which is a live extension programme -- its body sequences Zbb, then Zbkb, then the Zc* group. This ticket claims only a placeholder path so it can exist without colliding. Whoever picks it up must coordinate with OH-44 first; two sessions in one core's cpu.h is precisely what rules/ticket-claims.md exists to prevent.

Done when an ESP32-C3 GPIO register can be mapped, written and read back, an unmodelled address in the same peripheral still faults, and the behaviours have the tests core/cortexm0's did.

**Note 2026-08-25:** Widened 2026-08-25 to include core/riscv32/machine.py. OH-52 changed what a board needs of a core: webui/api.py now resolves core.<core>.machine for blank/refuses/write/enter/view/readable/read/word, and webui/boards/contract.py asks that module what a board owes. So MMIO alone no longer makes a RISC-V board loadable -- contract.core_requirements('riscv32') currently RAISES, by design, saying the core cannot host a board. See core/cortexm0/machine.py and core/avr/machine.py for the two shapes, and note the AVR one exists to prove the interface is not Arm-specific.

**Note 2026-08-25:** Delivered. Two of the five behaviours -- map_register and map_alias -- plus core/riscv32/machine.py, and the ABI bumped to version 2.

TWO AND NOT FIVE, which is this ticket's own instruction and worth restating. map_constant, map_stream and map_counter came to core/cortexm0 from a UART and a timer; porting them now would be speculative generality in the one file that argues hardest against it. cpu.h says so where a reader will meet it.

Every acceptance criterion measured:
 - an ESP32-C3 GPIO register mapped, written, read back
 - W1TS sets and W1TC clears bits in GPIO_OUT without touching the rest
 - a write-only alias reads as ZERO, which is the part's answer rather than this model shrugging
 - an unmodelled address in the same peripheral (0x60004040) still faults, naming the address
 - a register is not a region: in_range false, is_mapped true, which webui/api.py leans on for its words= refusal

SUB-WORD ACCESS IS WIRED FROM THE START, unlike cortexm0 which shipped word-only and had to be fixed. Every byte of a register names the same entry, and read_byte_checked/write_byte_checked/read_halfword/write_halfword all consult MMIO before the region lookup. Tested through EXECUTED sb/lbu/sh rather than through the binding, because that is how a real access arrives and because abi.Cpu exposes only word and block access -- adding byte accessors to test it would have tested the accessors.

machine.py: the third of these, and the one that shows the OH-52 interface was not shaped around either of the first two. Flat-addressed like the Arm one, enters like the AVR one, needed no new function. REQUIRES is empty. FLAG_BITS is empty and that is a fact rather than a gap -- RV32 has no condition-code register, a comparison writes a register and a branch compares two.

STATED PLAINLY because it is a real limit: what `enter` enters is the lowest address the image loads at. An ESP32-C3's reset vector is inside mask ROM that then loads the application, and that ROM is Espressif's, not redistributable, and 384 KB. So an ESP-IDF application will not run here; a bare-metal image will, which is the standard the RP2040, SAMD21 and ATmega328P images already meet. docs/architectures.md records that PICSimLab's own ESP route runs the vendor's QEMU rather than modelling it.

Five mutations, all caught, including a deliberate reintroduction of the cortexm0 sub-word bug.

ONE TRIPWIRE FIRED: my own from OH-52. test_a_core_with_no_machine_module_cannot_host_a_board used riscv32 as its example of a core that cannot host a board. It now can. Moved to i8086, which is the better example and a permanent one -- no board in the catalogue carries an i8086 -- and a companion test now asserts the three board-capable cores all DO have a machine module, so the first cannot pass by every core lacking one.

A fixture hazard worth the next reader's time: tests/riscv32/conftest.py has an autouse _fresh_board that un-installs whatever the previous test described. A module-level fixture named `cpu` is therefore set up and then WIPED before the test body runs, silently. Depending on `cpu` instead of shadowing it puts the mapping after the reset. That cost fourteen confusing failures.

1,227 passed, 17 skipped; all eight checkers exit 0.
