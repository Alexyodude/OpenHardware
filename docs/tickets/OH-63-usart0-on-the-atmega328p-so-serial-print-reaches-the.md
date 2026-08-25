---
id: OH-63
title: USART0 on the ATmega328P, so Serial.print reaches the console pane
status: open
priority: P1
created: '2026-08-26'
touches:
- webui/boards/atmega328p.py
- core/avr/*
- tests/avr/*
---

An Arduino IDE without a serial monitor is not one. Serial.begin/print/println is the first thing anybody types after digitalWrite, and on this board it currently writes into memory and stops.

WHAT IS ALREADY THERE. OH-43 built the console: webui/static/emulator.js renders it from uart.present on the wire, and webui/boards/rp2040.py feeds it through map_stream on the UART data register with an enable mask -- 'the emulated data register discards writes made while UARTEN is clear, exactly as the silicon does'. So the pane, the wire and the mechanism SHAPE all exist. What does not exist is any of it on AVR: core/avr has no map_stream, and webui/boards/atmega328p.py maps exactly one peripheral, timer 0, added by OH-59.

WHAT IS NEEDED, from iom328p.h -- read the addresses there, do not trust this list:

    UDR0    the data register: a write is a byte of output
    UCSR0A  status; TXC0, UDRE0 and RXC0 are what HardwareSerial polls
    UCSR0B  TXEN0/RXEN0 enable, and the interrupt enables
    UCSR0C  frame format -- written by begin() and never read back
    UBRR0H/L the baud divisor -- likewise

THE TRAP, and it is the one that will cost the afternoon: **HardwareSerial is interrupt-driven, not a busy-wait.** Serial.write() puts a byte in a ring buffer and enables UDRIE0; the USART_UDRE interrupt drains it. So a model that only makes UDR0 a stream will see nothing at all -- the byte never leaves the buffer, because the interrupt that would move it is never delivered. Arduino's own code does have a fallback path that polls UDRE0 when interrupts are off, and that is worth reading before deciding, but assume the interrupt is required and check.

**core/avr delivers exactly one interrupt today** -- OH-59 built the timer's, deliberately as one concrete Timer struct rather than a table, and wrote down why: 'a second source is a second ticket, and splitting this then is cheaper than un-generalising a table that only ever held one row'. This is that second ticket. Splitting core/avr/cpu.h's Timer into a counter and a general InterruptSource list is the expected shape and it is now justified, because there will be three sources (TIMER0_OVF, USART_UDRE, USART_RX) rather than one.

ALSO NOTE. Vector numbers are _VECTOR(n) in iom328p.h and the table stride on this part is 2 WORDS, not 1 -- a part over 8 KB of flash uses jmp. OH-59's TIMER0_OVF_VECTOR = 16 * 2 = 32 is the worked example, confirmed against a real image's disassembly rather than derived.

Done when a sketch calling Serial.begin(9600) and Serial.println("hello") shows 'hello' in the board console, watched by a named test, with the baud divisor read and reported rather than ignored -- and when a write made before Serial.begin() is discarded, as it is on the silicon and as rp2040.py already models.
