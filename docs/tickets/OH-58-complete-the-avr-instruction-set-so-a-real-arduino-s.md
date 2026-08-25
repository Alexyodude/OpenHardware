---
id: OH-58
title: Complete the AVR instruction set, so a real Arduino sketch runs on the Uno
status: open
priority: P1
created: '2026-08-26'
touches:
- core/avr/*
- tests/avr/*
- tools/lockstep_avr.mjs
- docs/architectures.md
- tools/gen_avr_corpus.mjs
- tests/avr/corpus/isa.json
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
