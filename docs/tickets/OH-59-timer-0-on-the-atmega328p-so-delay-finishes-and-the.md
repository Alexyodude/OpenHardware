---
id: OH-59
title: Timer 0 on the ATmega328P, so delay() finishes and the Uno actually blinks
status: done
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

**Note 2026-08-26:** CLOSED 2026-08-26, the same day it was filed. A stock Arduino Blink toggles PB5 at 500.0 ms of modelled time, twice running.

    transition 0   step        198   HIGH
    transition 1   step  8,000,293   LOW
    transition 2   step 16,000,434   HIGH
    half-periods:  8,000,095 and 8,000,141 instructions

WHAT WAS BUILT. core/avr grew a Timer struct, one map_timer call, and interrupt delivery. ABI 1 -> 2: avr_map_timer, avr_timer_count, avr_interrupt_inhibited. One concrete peripheral rather than a general interrupt table -- rule 6, and there is exactly one source.

THE COUNTER AND THE VECTOR ARE ONE MECHANISM. The ticket asked for a counter and named the interrupt as an open question; the answer is that neither works alone. micros() reads TCNT0 AND an overflow count that only an interrupt maintains, so a counter without a vector wraps every 256 ticks and delay() computes the same elapsed time forever. The flag byte is what couples them, which is why it is one struct and not three calls.

FOUR RULES, each with its own test in tests/avr/test_timer.py (19 tests): the overflow flag is set whether or not the interrupt is enabled, because micros() reads it directly to catch an overflow that landed inside a cli(); TIFR0 is write-one-to-clear, and storing the byte would let a program SET a pending interrupt with the bit it meant to acknowledge; the vector is taken instead of an instruction rather than after one, so the pushed address is the word that never ran; sei and reti each protect one following instruction.

TWO THINGS REFUSED RATHER THAN FAKED. A write to TCNT0 faults, because the count is derived from executed() and accepting the write would mean ignoring it. A map_timer with any address outside the sized space is refused with its numbers, because the step path indexes data memory without bounds checks and cannot afford to.

THE APPROXIMATION, STATED. One retired instruction is one clock cycle; on silicon it is one, two or three. Virtual time therefore runs roughly 1.5x slow against a real Uno and this model does not claim cycle accuracy -- the same paragraph rp2040.py writes about its TIMER. TCCR0B is written by Arduino's init() and never read back, so a sketch choosing a different prescaler would be believed and ignored. Recorded in core/avr/cpu.h beside the struct.

NOT CHANGED, DELIBERATELY. catalogue.FIRMWARE_VERIFIED still cites tests/avr/test_uno_board.py rather than the new sketch test: that one builds its image and skips without framework-arduino-avr, and a claim whose evidence can skip is not evidence.

RESIDUAL, not fixed here: core.avr.abi.Cpu after close() segfaults the interpreter instead of raising, because the handle is None and ctypes calls through it. Cost me one confusing traceback. Two lines to fix, in nobody's ticket.

Gate: 1,371 passed, 17 skipped; all eight checkers exit 0.
