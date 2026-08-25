---
id: OH-59
title: Timer 0 on the ATmega328P, so delay() finishes and the Uno actually blinks
status: open
priority: P1
created: '2026-08-26'
touches:
- webui/boards/atmega328p.py
- core/avr/*
- tests/avr/*
---

MEASURED 2026-08-26, immediately after OH-58 closed. A stock Arduino Blink now executes past its vector table, through setup(), into loop(), and calls digitalWrite(13, HIGH) -- and then never returns from delay(500).

It is not the instruction set. tests/avr/test_arduino_sketch.py watches loop() entered exactly once and micros() entered 5,878 times in 50,000 steps, and TCNT0 still reading 0.

WHY IT HANGS RATHER THAN FAULTS. webui/boards/atmega328p.py calls configure() and maps no registers at all. An AVR data space has no holes, so TCCR0A/TCCR0B/TIMSK0/TCNT0 are ordinary bytes of memory: a write stores and a read returns what was stored. micros() reads TCNT0 and the overflow counter that timer 0's interrupt maintains, gets the same number forever, and delay() spins. A missing peripheral on this core reads zero instead of faulting, which is the failure class this repository ranks worst -- and atmega328p.py's own header says so about PINB already.

WHAT IS NEEDED, and core/avr does not have it. rp2040.py's TIMER is the shape: a counter register that advances with executed instructions. core/avr has no map_register, map_constant, map_stream or map_counter equivalent -- webui/boards/atmega328p.py's Cpu protocol is one method wide. So this ticket is a mechanism as well as a description.

AND THE INTERRUPT. millis() is maintained by __vector_16, the TIMER0_OVF handler. Either the core delivers that interrupt -- which is OH-5's subject on the i8086 side and does not exist here at all -- or the overflow counter is advanced by the timer model itself, which is a different and smaller claim that should be written down as such rather than blurred.

Done when a stock Blink compiled against framework-arduino-avr toggles PB5 at a measured period, watched by a named test, with the period compared against 500 ms at 16 MHz rather than asserted to be 'steady'.
