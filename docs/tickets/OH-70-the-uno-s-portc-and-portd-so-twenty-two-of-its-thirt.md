---
id: OH-70
title: The Uno's PORTC and PORTD, so twenty-two of its thirty-two pads answer
status: done
priority: P2
created: '2026-08-26'
touches:
- webui/boards/atmega328p.py
- tests/avr/*
- tests/webui/test_pin_view.py
- webui/static/board3d-panel.js
- tests/webui/test_board3d.py
---

TWENTY-SIX OF THE ARDUINO UNO'S THIRTY-TWO PADS READ 'not modelled' in the pin view OH-30 built, and only ten of them deserve to. webui/boards/atmega328p.py's HEADER maps PORTB alone -- six pads, 8 through 13 -- so pins 0-7 (PORTD), A0-A5 (PORTC) and the R3 header's SDA and SCL (PC4 and PC5, the same silicon as A4 and A5) all report unknown. The panel says '6 of 32 pads answerable'. It should say 22, and the ten that remain are AREF, NC, IOREF, RESET, 3V3, 5V, VIN and three GNDs -- pads with no MCU pin behind them, where unknown is the truth.

MEASURED FIRST, 2026-08-26, and the measurement changes what this ticket is. A sketch driving pin 7, pin 3, A0 and reading pin 4 was built through webui/compile.py and run on this board: 1,766 bytes, no fault, 200,000 instructions. It left DDRD 0b10001000, PORTD 0b10000000, DDRC 0b00000001, PORTC 0b00000001 -- exactly right. So unlike OH-68, WHICH REGISTERS TO MODEL IS NOT THE QUESTION HERE: an AVR's whole data space already exists as stored bytes, PORTC and PORTD store and read back correctly today, and nothing in core/avr has to change. The entire gap is a label table.

iom328p.h:84,93,102 gives PINC/DDRC/PORTC as _SFR_IO8(0x06/0x07/0x08) and :111,121,131 gives PIND/DDRD/PORTD as _SFR_IO8(0x09/0x0A/0x0B) -- data addresses 0x26/0x27/0x28 and 0x29/0x2A/0x2B after the +0x20 the file already calls the likeliest off-by-something in an AVR model. The label map is pins_arduino.h:150-194, the same table HEADER already cites: PD0-7 for digital 0-7, PB0-5 for 8-13, PC0-5 for 14-19, and lines 48-51 make SDA digital 18 and SCL digital 19.

HEADER MUST BECOME (port, bit) LIKE THE SAMD21'S, because one integer cannot name three ports, and PIN_NAMES is derived so it follows for free.

TWO WAYS A NEWLY LIVE PAD CAN LIE, both measured rather than reasoned, and this is the part of the ticket that is not bookkeeping.

  (a) THE USART OWNS PD0 AND PD1 AND DDRD DOES NOT RECORD IT. Serial.begin(9600) followed by a println was built and run: it printed 'hi', left UCSR0B at 0b10011000 with RXEN0 and TXEN0 both set, and left DDRD at 0b00000000. So pins 0 and 1 would report 'input' -- nobody drives this -- while the transmitter is driving one of them. That is the confident-wrong-answer class this repository ranks worst, it is reachable through the IDE today, and it is about two of the pads this ticket makes live. IN SCOPE: report unknown for a pad the USART has taken.

  (b) A TIMER COMPARE OUTPUT OWNS A PWM PAD AND PORTD DOES NOT RECORD IT EITHER. analogWrite(3, 128) -- linked by hand, because wiring_analog.c is not in webui/compile.py's Uno source list, so analogWrite does not link through the IDE -- left DDRD 0b00001000, PORTD 0b00000000 and TCCR2A 0b00100001 with COM2B1 set. pin_states would say pin 3 is LOW while the part drives a 50% square wave. NOT IN SCOPE, and split rather than smuggled in: the fix needs the COM bits of TCCR0A, TCCR1A and TCCR2A and a pin-to-timer table, and it would change pins 9, 10 and 11 which this ticket does not otherwise touch. Pin it as a limitation the way test_reading_the_input_register_is_not_yet_modelled pins PINB, and file the follow-up.

PINC AND PIND INHERIT PINB'S LIMITATION exactly and it must be said in the same place: a read returns the stored zero rather than the electrical level. Nothing reads them yet.

NOT IN SCOPE: the ADC, so A0-A5 answer as digital pads and analogRead is still absent; pull-ups, so an input pin is 'input' and not 'high'; and no new register in core/avr, because the measurement above says none is needed.

Done when a named test builds a sketch through webui/compile.py that drives a PORTD pin and a PORTC pin, runs it, and watches both report the level they were driven to; when webui.api.pin_view on an Arduino Uno reports 22 of 32 pads answerable with the remaining ten named; and when the USART case reports unknown rather than input under a test that builds and runs a real Serial sketch.

**Note 2026-08-26:** CLOSED 2026-08-26 in e4ea0b1. Every clause of the Done-when, and the ticket's own headline prediction was the part that turned out to be wrong in an interesting way.

TWENTY-TWO OF THIRTY-TWO, measured in a browser and not only in a test: the panel reads '22 of 32 pads answerable' with pin 7 high on PD7, A0 high on PC0, 13 low on PB5 and A4 and SDA moving together as the one pad they are. The ten that stay unknown are AREF, NC, IOREF, RESET, 3V3, 5V, VIN and three GNDs, named in a test rather than counted, so that PORTC going missing while five supplies appeared could not keep the number right.

THE TICKET SAID WHICH REGISTERS TO MODEL IS NOT THE QUESTION HERE AND THAT HELD. Nine constants, no mapping. On an AVR the whole data space already exists as stored bytes, so PORTC and PORTD were storing correctly before a line was written -- the probe that proved it is quoted in the source beside them. OH-68 needed twenty-seven registers built to get one Arm board to setup(); this needed none. The difference is the architecture, and webui/boards/atmega328p.py now says so where it already explained why it has almost no map_register calls.

THE USART CASE WENT IN AND THE PWM CASE DID NOT, exactly as scoped. Serial.begin leaves no trace in DDRD -- UCSR0B 0b10011000, DDRD 0b00000000, measured -- so pins 0 and 1 report unknown rather than a confident 'input' about a pin the transmitter is driving. analogWrite is OH-71: it wants the COM bits of three timers and would move pins 9, 10 and 11, which is a second change. OH-71 was narrowed off every path the day it was filed, because two open tickets may not claim one file and it cannot start before this one lands anyway.

TWO PANEL BUGS THE BROWSER FOUND AND NO ASSERTION DID, and both are this ticket's doing rather than pre-existing. Before this, a pad was unknown because the board's table had no row for it, which never changes while a board is loaded. Making the USART take PD0 and PD1 partway through a sketch made 'unknown' a thing that MOVES, and two places had quietly assumed it could not. The row read '1 | PD1 | not modelled', naming the pin in the same breath as denying it; and the answerable count was read from the layout fetch, so it went on saying 22 beside two rows that had stopped answering. chip_pin is the discriminator for the first and it is exact rather than convenient -- webui/api.py fills it from PIN_NAMES, derived from the same HEADER that pin_states walks, so a pad carries a chip pin if and only if the board answered for it.

THE GENERALISATION WORTH KEEPING: a field that has always been constant acquires readers who assume it. The fix was cheap because the panel is small; the way to find it was to drive the page and read the words, which is the third and fourth time this repository has recorded a pane being wrong in a way only a reader sees.

TEN MUTATIONS, ALL RED. A0 pointing at PORTD, SDA drifting off A4, the USART branch removed, the direction register ignored, PORTD dropped from HEADER, pin 3 pointing at PD4, PIND aliased to PORTD, the two sentences collapsed into one, the chooser guessing from the pad group, and a state poll that stops recounting. Each was caught by the test that names the behaviour, which is the check that the tests are about what they say.

NOT DONE, each for a stated reason: no ADC, so A0-A5 answer as digital pads and analogRead is still absent; no pull-ups, so an input pin is 'input' and not 'high'; PINC and PIND inherit PINB's limitation exactly and read the stored zero rather than the pin, pinned by test_the_input_registers_of_the_new_ports_are_not_modelled_either.
