---
id: OH-49
title: An AVR core for the Arduino Uno, and a blink that proves it
status: done
priority: P1
created: '2026-08-25'
touches:
- core/avr/*
- tests/avr/*
- webui/boards/atmega328p.py
---

The Arduino Uno is the one board here that is not a Seeed XIAO, the most recognisable MCU in the catalogue, and the only chip class left that is neither blocked on an oracle nor claimed by another session. One board, and the cheapest remaining core.

AVR is small: 8-bit, roughly 130 instructions, 32 general registers memory-mapped at 0x00-0x1F with IO space above them, and a Harvard split that makes program and data genuinely separate address spaces -- which is the one structural thing core/cortexm0 and core/i8086 do not prepare anyone for. add_region will need to say WHICH space.

Oracle, stated honestly rather than assumed: docs/architectures.md records simavr and avr-gdb as existing and NEITHER as hardware-captured, so this cannot reach the i8086's standard of evidence and must not claim to. Neither is installed here. What is achievable is the standard RP2040 and SAMD21 met: a real compiled blink from avr-gcc, watched toggling a real PORTB bit. That is a smaller claim than conformance and a true one.

Toolchain: not present. PlatformIO fetches it -- Tool Manager: Installing toolchain-atmelavr

Tool Manager: Error: Please read https://bit.ly/package-manager-ioerror

Tool Manager: Warning! Package Mirror: HTTPSConnectionPool(host='sin1.contabostorage.com', port=443): Max retries exceeded with url: /fd833e6c4db04192b0ad7e561907b935:pioregmirrorsg/tools/46/fd/e2035ec291b1784da9427a0fa61b21758e8a608821bd2764aaf9d2d6f91d/toolchain-atmelavr-windows-3.70300.220127.tar.gz (Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x000001FFE2492C10>: Failed to establish a new connection: [WinError 10061] No connection could be made because the target machine actively refused it'))

Tool Manager: Looking for another mirror...

Downloading 0% 10% 20% 30% 40% 50% 60% 70% 80% 90% 100%

Unpacking 0% 10% 20% 30% 40% 50% 60% 70% 80% 90% 100%

Tool Manager: toolchain-atmelavr@3.70300.220127 has been installed! -- which is how framework-arduino-samd arrived for OH-39 and how the SAMD21's register provenance was obtained.

Build it in vertical slices the way OH-20 did for cortexm0: the ABI and build plumbing plus enough instructions to run something, then widen. A slice with no way to verify it is a horizontal layer in disguise.

Done when a real compiled image toggles a PORTB bit, ATmega328P is described in webui/boards/, and Arduino Uno reports runnable in the catalogue.

**Note 2026-08-25:** Core delivered and verified; the board description is NOT, and stopping there is deliberate.

Delivered: core/avr with the fourteen instructions avr-gcc 7.3.0 emits for tests/avr/blink/blink.c at -Os, read off the disassembly rather than chosen. A real compiled image toggles PB5 -- 19 transitions in 20,000 instructions at a constant period of 1,110, alternating, with DDRB bit 5 set. 18 tests. Five mutations run and all caught, one of them only after a test was added for it.

Two defects the fixture found, both SILENT -- ran to completion and produced a plausible wrong answer:
 - the ldd/std mask included bit 9, which is the load/store selector read inside the branch, so every load matched and no store ever did.
 - brbc/brbs polarity inverted. Bit 10 SET means branch-if-CLEAR, the opposite of how the bit reads. The blink still ran 60,000 instructions without faulting and still alternated; it toggled every 10 instructions instead of 1,110 because the delay loop took its exit branch on the first comparison. Only asserting the PERIOD caught it, not the transition count.

A third was found by mutation and could not be caught by the blink at all: cpc must only ever CLEAR Z, never set it, which is what makes a multi-byte compare work. That image branches on C after its cpc and never on Z, so the rule could be deleted with all sixteen tests passing. Now pinned by its own 16-bit compare test rather than deleted as unexercised.

NOT DONE, and the reason is a real design question rather than time: webui/boards/atmega328p.py, and Arduino Uno reporting runnable. webui/boards/contract.py requires VECTOR_TABLE_OFFSETS because webui/api.py's _place() needs it -- and _place reads an initial stack pointer and a reset handler out of the first two words, which is an Arm arrangement. An AVR simply begins executing at address zero. So an atmega328p.py could satisfy the contract literally, with VECTOR_TABLE_OFFSETS = (0,), and the catalogue would then report Arduino Uno runnable while api.load_firmware could not actually enter it -- the claim-something-you-cannot-do failure this repository refuses everywhere else.

The board contract needs a notion of 'how does this board enter an image' that admits a machine with no vector table, and that belongs in a ticket of its own rather than being guessed at here. The AVR core is the first non-Arm board-capable core, so it is the first time the question could be asked.

**Note 2026-08-25:** Closed here, remaining half moved to OH-52. The core half is delivered and committed at bb1e139. The board half -- webui/boards/atmega328p.py and Arduino Uno reporting runnable -- turned out not to be a small remainder of this ticket but a change to webui/api.py's machine surface: the Core protocol there is missing ten of its twelve methods on the AVR, so entry is one of eleven gaps rather than the gap. That is OH-52's subject and it owns webui/boards/atmega328p.py and core/avr/machine.py from now on. This ticket's Done-when is therefore NOT met and it is not being claimed as met; it is superseded.
