---
id: OH-58
title: Complete the AVR instruction set, so a real Arduino sketch runs on the Uno
status: done
priority: P1
created: '2026-08-26'
touches:
- core/avr/*
- tests/avr/*
- docs/architectures.md
- tools/gen_avr_corpus.mjs
- tests/avr/corpus/isa.json
- pyproject.toml
- tests/rules/test_testpaths.py
- webui/boards/catalogue.py
- docs/HANDOFF_2026-08-26_the-avr-oracle-and-an-ide-that-cannot-exist-yet.md
---

MEASURED 2026-08-26. A real Arduino sketch -- setup()/loop()/pinMode()/digitalWrite()/delay(), compiled against framework-arduino-avr with avr-gcc 7.3.0, 1058 bytes -- stops on its FIRST instruction on the Uno board:

    Unimplemented: no implementation for 0x940c at word 0x0000

0x940C is JMP, the reset entry of the interrupt vector table. Every Arduino image begins with one.

THE SIZE OF THE GAP, measured by stepping every distinct encoding in that sketch:

    246 distinct encodings in the image
    114 the avr core executes
    132 the avr core refuses

32 mnemonics have NO encoding implemented at all: .word adc add and andi call cli com cp cpse dec jmp lds lpm mov movw muls mulsu nop or ori pop ret reti sbc sbci sbis sbiw sei sts sub subi. Two more are partial: ld (2 of 6 encodings), st (1 of 7).

Without call/ret there are no function calls; without jmp the vector table cannot be crossed; without pop no prologue can be unwound. core/avr was built for tests/avr/blink/blink.bin, a hand-written image, and is a subset sized for exactly that. OH-49 delivered it honestly and claimed no more -- catalogue.FIRMWARE_VERIFIED cites tests/avr/test_uno_board.py, which watches that one image.

THE ORACLE, and it is the reason this ticket is buildable where OH-50 stopped. avr8js 0.21.0, MIT, by the author of rp2040js -- which tools/lockstep_armv6m.mjs already drives for Armv6-M. Installed and probed 2026-08-26: avrInstruction(cpu) steps one instruction, cpu.data[0..31] is the register file, cpu.data[0x5F] is SREG, cpu.pc is the word address. The half-carry on `add r24,r24` came out correct, which is the flag most likely to be wrong.

catalogue.ORACLES already records \"simavr and avr-gdb exist; neither is hardware-captured\". avr8js is a third, hand-written from Microchip's datasheet rather than derived from gcc or simavr, so it is independent of anything this core was written from -- the property docs/architectures.md 4.2 says agreement needs.

AFTER THE ISA, the peripherals. delay() needs millis() needs timer0, so TCCR0A/TCCR0B/TIMSK0/TCNT0 have to tick. webui/boards/atmega328p.py currently calls configure() and stops -- it maps no registers at all, and an AVR data space has no holes, so those writes land in memory and read back as whatever was written. That is why an Arduino sketch would hang rather than fault even with a complete ISA: millis() would return 0 forever. That half is NOT in this ticket; file it separately once the ISA lands.

WHY THIS IS WANTED: it is the only path to "paste any Arduino sketch and it runs". The alternative -- a thin OpenHardware runtime over the peripherals each board models -- was spiked on 2026-08-26 and works today on the RP2040 (setup/loop, delay accurate to the microsecond, Serial into the UART pane), but it cannot run vendor libraries and is a different product.

Done when a real Arduino sketch compiled against framework-arduino-avr executes past its vector table and through setup(), verified in lockstep against avr8js, and the remaining gap is measured rather than assumed.

**Note 2026-08-26:** CLOSED 2026-08-26. Every mnemonic in STILL_MISSING implemented; the set is empty and the assertion now reads 'nothing in the corpus is refused', still failing in both directions.

EVIDENCE. tests/avr/test_arduino_sketch.py builds the stock Blink against framework-arduino-avr and drives it through webui/api.py: the reset jmp lands on its decoded target in one step, main at step 51, setup at 113, pinMode at 116 (DDRB bit 5 set), loop at 159, digitalWrite at 162 (PORTB bit 5 set), delay at 209. Fifty thousand steps with no Unimplemented. The image is built rather than committed because linking Arduino's core makes it LGPL-2.1-derived; the test skips loudly without the framework.

THE GAP, MEASURED. Stepping every distinct word of the 1,058-byte image leaves 18 refused, and avr-objdump calls every one of those 18 '.word' -- they are the pin tables in .progmem read as code by the scan. Nothing the image EXECUTES is refused. It stops in delay() -> micros() -> TCNT0, which webui/boards/atmega328p.py does not map. That is OH-59, not this.

CORPUS. 552 cases -> 570, all agreed, 0 refused, 0 wrong. Three gaps closed while there: no case skipped over a 32-bit instruction, Z pointed at extended IO so no store through Z was ever checked, and every lpm case had Z even.

A SECOND ORACLE DEFECT. avr8js never sets V for neg -- instruction.js:523 tests '128 === R' where R is '0 - value', a negative JS number that is never 128. No seed draws 0x80 into a neg operand so the corpus cannot say so; tests/avr/test_datasheet_edges.py asserts it against the manual, beside the known half-carry bug.

FOUND EN ROUTE. tests/avr was absent from pyproject.toml's testpaths, so bare pytest had never run the AVR suite. Fixed, with tests/rules/test_testpaths.py as the guard. CI is narrower still and is OH-60.
