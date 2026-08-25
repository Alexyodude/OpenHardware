---
id: OH-49
title: An AVR core for the Arduino Uno, and a blink that proves it
status: open
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
