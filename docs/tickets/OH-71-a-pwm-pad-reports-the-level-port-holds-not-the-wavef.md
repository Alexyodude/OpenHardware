---
id: OH-71
title: A PWM pad reports the level PORT holds, not the waveform the timer drives
status: open
priority: P3
created: '2026-08-26'
touches: []
---

SPLIT OUT OF OH-70 RATHER THAN SMUGGLED INTO IT, and the measurement is already done. 2026-08-26: analogWrite(3, 128) compiled against framework-arduino-avr and run on webui/boards/atmega328p.py left DDRD 0b00001000, PORTD 0b00000000 and TCCR2A 0b00100001 -- COM2B1 set, so the timer's compare output has taken the pad. webui/boards/atmega328p.py's pin_states reads DDRD then PORTD and answers 'low'. The part is driving a 50% square wave. A confident wrong answer, which is the class this repository ranks below a loud one, and OH-70 pins it as a limitation instead of fixing it.

WHY IT WAS NOT DONE IN OH-70. It needs the COM bits of three timers -- TCCR0A, TCCR1A and TCCR2A, none of which this board models today -- and a digital-pin-to-timer table. It would also change pins 9, 10 and 11, which are PORTB and therefore outside a ticket about PORTC and PORTD. Two changes, so two tickets.

THE HONEST ANSWER IS 'unknown' AND NOT A SIMULATED WAVEFORM. core/avr models no PWM and this repository's four-state vocabulary already has the word for 'this model cannot say'. Reporting a duty cycle would be a different and much larger ticket, and it would need a peripheral nobody has asked for yet.

SIX PADS ARE AFFECTED, the ones the Uno's silkscreen marks with a tilde: ~3 and ~11 are timer 2 (OC2B, OC2A), ~5 and ~6 are timer 0 (OC0B, OC0A), ~9 and ~10 are timer 1 (OC1A, OC1B). From framework-arduino-avr/variants/standard/pins_arduino.h:196-232, the digital_pin_to_timer_PGM table.

NOT REACHABLE THROUGH THE IDE TODAY, which is why it is P3 and not P2. webui/compile.py's Uno recipe does not compile wiring_analog.c, so analogWrite does not link -- 'undefined reference to analogWrite', measured. The lie needs a hand-linked image to produce. A ticket that adds wiring_analog.c to that recipe makes this reachable and should say so, which is the reason to have this filed before then.

Done when a named test builds an analogWrite sketch, runs it, and watches pin_states report unknown for the pad the timer owns while the pads beside it still report the level PORT holds -- and when test_a_pwm_pad_reports_the_port_bit_and_not_the_waveform in tests/avr/ fails, because that test exists to pin the current behaviour and its failure is the notification.

NARROWED OFF EVERY PATH THE DAY IT WAS FILED, and this is not bookkeeping. Two open tickets may not claim the same file, and the only two files this needs -- webui/boards/atmega328p.py and tests/avr/ -- are the ones OH-70 is holding. Since this ticket cannot start before OH-70 lands anyway (its Done-when names a test OH-70 writes), giving the claims up costs nothing and keeps tools/check_ticket_claims.py honest. **It re-claims both when OH-70 closes.** OH-64 was narrowed the same way and for the same reason on 2026-08-26.
