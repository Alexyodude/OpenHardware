---
id: OH-63
title: USART0 on the ATmega328P, so Serial.print reaches the console pane
status: done
priority: P1
created: '2026-08-26'
touches:
- webui/boards/atmega328p.py
- core/avr/*
- tests/avr/*
- tools/gen_avr_corpus.mjs
- tests/avr/corpus/isa.json
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

**Note 2026-08-26:** CLOSED 2026-08-26.

RESULT, read through webui/api.py's uart_view rather than off the core: uart0_output b'hello\r\n', baud_rate 9615, UCSR0B 0x98.

THE TICKET'S CENTRAL PREDICTION WAS WRONG, and it said to check rather than assume. It warned that HardwareSerial is interrupt-driven and that USART_UDRE would have to be delivered, and named splitting core/avr's Timer into a general InterruptSource list as the expected shape. Measurement refuted it. HardwareSerial::write has a fast path: if the ring buffer is empty AND UDRE0 is set, it writes the byte straight to UDR0 and returns. With UDRE0 reading clear the sketch took the buffered path, left UCSR0B at 0xB8 with UDRIE0 set, and waited forever. With UDRE0 reading set it took the fast path, UCSR0B came back 0x98 with UDRIE0 CLEAR, and the bytes arrived. So core/avr still delivers exactly ONE interrupt and the general table was not built -- it would have had no caller, which is what CLAUDE.md rule 6 forbids. The prediction is preserved in tests/avr/test_usart.py's header so it is not made again.

FOUR INSTRUCTIONS CAME OFF exec.cc's absent list on the way: ijmp, icall, sbrc, sbrs. The sketch stopped on 0x9409 -- IJMP -- because Print::write is virtual and gcc compiles that tail call to an indirect jump. Corpus 570 -> 597 cases, all agreed. Z is a WORD address for ijmp and a BYTE address for lpm, which is the clearest single reason cpu.h keeps the two spaces apart.

THE STATUS REGISTER READS STORED-OR-READY, not a constant, and U2X0 is why: begin() writes it and baud_rate reads it back to know whether the divisor is over 8 or over 16. A constant would be wrong by exactly a factor of two at every speed and still look plausible.

9,615 AND NOT 9,600. begin(9600) writes 207 with double-speed set and 16e6/(8*208) is 9,615. Reporting 9,600 would be reporting the request rather than the configuration.

A COLLISION I CAUSED AND THE GUARD CAUGHT: I claimed webui/static/emulator.js, which OH-62 already owns. Not needed -- uart_view finds uart0_output by getattr, so the console appeared with no UI change at all. Claim removed.

Reception is absent on purpose: nothing is wired to the other end, so RXC0 is not among the ready bits and Serial.available() answering false is the truth rather than a gap.

Gate: 1,388 passed, 17 skipped; all eight checkers exit 0.
