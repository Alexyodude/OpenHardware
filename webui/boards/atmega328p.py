#!/usr/bin/env python3
# OpenHardware - the ATmega328P as two sized address spaces over the AVR core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Describe an ATmega328P to a `core.avr` CPU.

The third board here and the first that is not Arm, which makes it the one
worth reading against the other two. `webui/boards/rp2040.py` and `samd21.py`
are 400 and 230 lines of memory-mapped registers; this is half that, and almost
none of it is registers. That difference is the architecture and not an
omission -- see "One peripheral, and why only one" below.

## Where these numbers come from

The toolchain's own `iom328p.h`, which is Microchip's, shipped inside
`toolchain-atmelavr@3.70300.220127` and fetched with PlatformIO:

    ~/.platformio/packages/toolchain-atmelavr/avr/include/avr/iom328p.h

Every constant below cites the file and line it was read from, the same shape
`samd21.py` cites its CMSIS headers. There is no research directory for this
part; the header *is* the source, and it is generated from the same device
description the datasheet is.

The board is the **Arduino Uno**, per `webui/boards/catalogue.py`'s `IRREGULAR`
table -- the one board in the catalogue that is not a Seeed XIAO.

## Two spaces, sized rather than mapped

`install(cpu)` calls `configure(program_words, data_bytes)` and then maps one
peripheral. There is no `add_region`, because there are no regions: an AVR has
exactly two address spaces, both starting at zero, and the only thing a board
chooses is how big each is. A Cortex-M0+ board must place flash (0x00000000 on a SAMD21,
0x10000000 on an RP2040) because that part is genuinely a decision; here it
is not.

**The data space is one span and not three.** 0x0000-0x001F is the register
file, 0x0020-0x00FF is the IO window, and SRAM starts at `RAMSTART` 0x0100 --
but they are consecutive addresses in one space, and `lds r0, 0x0025` reads
PORTB exactly as `in r0, 0x05` does. Modelling them separately would invent a
boundary the instruction set does not have.

## One peripheral, and why only one

`rp2040.py` and `samd21.py` both spend most of their length on `map_register`
and `map_alias`, and this file has neither. On this part it mostly does not
need them: `DDRB` and `PORTB` are bytes of the data space, so a write to 0x24
stores and a read returns what was stored, which is what the silicon does for
those two registers.

**OH-70 is what that claim buys.** Making all three ports answer for their
pins added nine constants and no mapping at all, because `DDRC`, `PORTC`,
`DDRD` and `PORTD` were already storing correctly -- the sketch that proved it
is quoted beside them. A board on either Arm part would have needed the
registers built first.

**Two peripherals are the exception, and each is exactly one call.** `TCNT0` cannot be a
stored byte -- it has to answer something different each time it is read, or
`delay()` never returns. OH-59 measured that: with the instruction set
complete, a stock Arduino Blink reached `loop()`, drove PB5 high, and then
spun in `micros()` forever. So `core/avr` grew a counter and the one interrupt
it raises, and this file is where the addresses for them are written down.

**USART0 is the other**, added by OH-63 for the same reason: a
`Serial.println` sketch wrote into a data register that stored the byte and
told nobody. See `core/avr/cpu.h`'s `Timer` and `Usart` for what each models
and what neither does.

**Where that stops being true, and it does:** `PINB`, `PINC` and `PIND` read
the *electrical level on the pins*, so on a pin driven as an output each
follows its `PORTx`, and on a pin driven as an input it follows whatever is
wired to it. This model returns the stored zero. That is a wrong answer rather
than a fault, which is the failure class this repository ranks worst -- and
unlike `samd21.py`, which could leave its `PORT_IN` unmapped so a read faults
instead of lying, there is nothing to unmap here: every byte of the data space
exists.

So it is written down instead. All three are exported below so a test can name
them, `test_reading_the_input_register_is_not_yet_modelled` pins the
limitation rather than the behaviour, and the fix -- a mirror of `PORTx`
masked by `DDRx` -- needs a mapping mechanism this core does not have. Nothing
has read any of the three yet; the day something does, that is the first claim
to re-check.

## What is deliberately absent

Timers 1 and 2, timer 0's compare-match interrupts and PWM outputs, USART
reception, the ADC, the EEPROM. Same growth rule the other two boards keep: a
peripheral is added when a real image needs it and not before -- timer 0 is
here because a real image spun forever without it, and USART0's transmitter is
here because a real image printed into a register nothing read.

Reception is absent on purpose rather than by omission: nothing is wired to
the other end, so `Serial.available()` answering false forever is the truth
and not a gap.

Here the rule bites differently, because a missing peripheral on this core
does not fault -- it reads zero. `TCCR0A` and `TCCR0B` are the live example:
Arduino's `init()` writes a prescaler into them and this model never reads it
back, taking `INSTRUCTIONS_PER_TICK` as given. A sketch that chose a different
prescaler would be believed and ignored.
"""

from __future__ import annotations

import typing

#: Flash, from `iom328p.h:889`:
#:
#:     #define FLASHEND     0x7FFF
#:
#: The last **byte** address, so 32 KB, so 16,384 sixteen-bit words. The core
#: is configured in words because that is what the program counter counts.
FLASH_BYTES = 0x8000
PROGRAM_WORDS = FLASH_BYTES // 2

#: The data space, from `iom328p.h:883-884`:
#:
#:     #define RAMSTART     (0x100)
#:     #define RAMEND       0x8FF     /* Last On-Chip SRAM Location */
#:
#: `RAMEND` is the last address in the whole data space, not the last address
#: of SRAM alone -- the register file and the IO window are below `RAMSTART`
#: and are part of the same space. So the size is `RAMEND + 1`, which is 2,304
#: bytes: 32 registers, 64 IO registers, 160 extended IO registers, and 2 KB of
#: SRAM.
RAMSTART = 0x0100
RAMEND = 0x08FF
DATA_BYTES = RAMEND + 1

#: Where SP comes up. Not configured here -- `core/avr/cpu.cc`'s `reset()`
#: derives it from the size above -- but named because a bare-metal image built
#: with `-nostartfiles` never writes SP itself, so this is the value the first
#: `push` uses and a test asserts it.
STACK_TOP = RAMEND

#: The three ports and their nine registers, as **data** addresses. From
#: `iom328p.h:54,64,74`, `:84,93,102` and `:111,121,131`:
#:
#:     #define PINB  _SFR_IO8(0x03)    #define PINC  _SFR_IO8(0x06)
#:     #define DDRB  _SFR_IO8(0x04)    #define DDRC  _SFR_IO8(0x07)
#:     #define PORTB _SFR_IO8(0x05)    #define PORTC _SFR_IO8(0x08)
#:
#:     #define PIND  _SFR_IO8(0x09)
#:     #define DDRD  _SFR_IO8(0x0A)
#:     #define PORTD _SFR_IO8(0x0B)
#:
#: `_SFR_IO8(x)` is `x + 0x20` in the data space, so an `in`/`out` instruction
#: uses the small number and everything else uses the one below. **That +0x20
#: is the likeliest off-by-something in an AVR model**, which is why both forms
#: are written out here rather than one being derived at the call site.
#:
#: **Nine registers and not one line of new mapping**, which is the whole
#: shape of OH-70 and worth reading beside `samd21.py`'s twenty-seven. A
#: sketch driving pin 7, pin 3 and A0 was built and run before any of this was
#: written (2026-08-26, 1,766 bytes, 200,000 instructions, no fault) and it
#: left `DDRD` at 0b10001000 and `DDRC` at 0b00000001 -- correct, because on
#: this part they were already bytes of the data space that store what is
#: written to them. The gap OH-70 closed was a label table, not a peripheral.
PINB_IO, PINB = 0x03, 0x23
DDRB_IO, DDRB = 0x04, 0x24
PORTB_IO, PORTB = 0x05, 0x25

PINC_IO, PINC = 0x06, 0x26
DDRC_IO, DDRC = 0x07, 0x27
PORTC_IO, PORTC = 0x08, 0x28

PIND_IO, PIND = 0x09, 0x29
DDRD_IO, DDRD = 0x0A, 0x2A
PORTD_IO, PORTD = 0x0B, 0x2B

#: Port letter -> its direction and output registers, in that order.
#:
#: **The letter is the key rather than an index**, unlike `samd21.py`'s
#: `PORTA`/`PORTB` integers, and the difference is that this part's ports are
#: not evenly spaced -- `webui/boards/samd21.py` computes a group base with
#: arithmetic and this cannot. Keying by the letter the datasheet uses also
#: makes `PIN_NAMES` a one-line derivation and a `HEADER` row read as its own
#: documentation: `("D", 7)` is PD7 and needs no lookup to check.
#:
#: `PIN{B,C,D}` are deliberately not here. Nothing reads them, and the section
#: below says what happens when something does.
PORTS: dict[str, tuple[int, int]] = {
    "B": (DDRB, PORTB),
    "C": (DDRC, PORTC),
    "D": (DDRD, PORTD),
}

#: Timer 0, as **data** addresses. From `iom328p.h:141,221,229,237,438`:
#:
#:     #define TIFR0  _SFR_IO8(0x15)
#:     #define TCCR0A _SFR_IO8(0x24)
#:     #define TCCR0B _SFR_IO8(0x25)
#:     #define TCNT0  _SFR_IO8(0x26)
#:     #define TIMSK0 _SFR_MEM8(0x6E)
#:
#: **Read that list twice.** Four of them are `_SFR_IO8`, which adds 0x20, and
#: `TIMSK0` is `_SFR_MEM8`, which does not -- so TIMSK0 is 0x6E in the data
#: space and TIFR0 is 0x35 rather than 0x15. The two registers hold the same
#: bit number for the same event, which makes the asymmetry easy to smooth
#: over: TOV0 is bit 0 of TIFR0 and TOIE0 is bit 0 of TIMSK0.
TIFR0_IO, TIFR0 = 0x15, 0x35
TCCR0A_IO, TCCR0A = 0x24, 0x44
TCCR0B_IO, TCCR0B = 0x25, 0x45
TCNT0_IO, TCNT0 = 0x26, 0x46
TIMSK0 = 0x6E

#: The other two timers' control register A, for `TIMER_PINS` below. Neither
#: timer is MODELLED -- nothing here counts -- and these are read only to find
#: out whether a compare output has taken a pad away from its port.
#:
#: `#define TCCR1A _SFR_MEM8(0x80)` at `iom328p.h:516` and
#: `#define TCCR2A _SFR_MEM8(0xB0)` at 625. **Both are `_SFR_MEM8`, so the
#: number in the header is already the data-space address** -- unlike
#: `TCCR0A`, which is `_SFR_IO8(0x24)` and therefore 0x44. That is the same
#: 0x20 trap `TIFR0` records above, in the other direction.
TCCR1A = 0x80
TCCR2A = 0xB0

#: The two `COMnx1:COMnx0` bits of one compare output, as a mask.
#:
#: **Zero means the pin is the port's and anything else means it is the
#: timer's**, which is the whole of the test: the datasheet's table gives
#: `00` as "normal port operation, OCnx disconnected" and every other value
#: connects the compare output.
#:
#: The same two pairs of bit numbers in all three timers -- `COM0B0 4`,
#: `COM0B1 5`, `COM0A0 6`, `COM0A1 7` at `iom328p.h:224-227`, repeated exactly
#: at 519-522 for timer 1 and 628-631 for timer 2.
COM_B_MASK = (1 << 4) | (1 << 5)
COM_A_MASK = (1 << 6) | (1 << 7)

#: `#define TOV0 0` at `iom328p.h:142` and `#define TOIE0 0` at 439. The same
#: number in both registers, which is what lets the core carry one `bit`.
TOV0 = TOIE0 = 0

#: `#define TIMER0_OVF_vect _VECTOR(16)` at `iom328p.h:848`.
#:
#: A part with more than 8 KB of flash uses four-byte vectors -- a `jmp`, not
#: an `rjmp` -- so vector 16 is at byte 64 and **word 32**. Confirmed against a
#: real image rather than derived: `avr-objdump` on an Arduino sketch shows
#: `40: 0c 94 98 00  jmp 0x130  ; <__vector_16>`.
TIMER0_OVF_VECTOR_NUMBER = 16
VECTOR_WORDS = 2
TIMER0_OVF_VECTOR = TIMER0_OVF_VECTOR_NUMBER * VECTOR_WORDS

#: How many retired instructions make one tick of TCNT0.
#:
#: **A stated approximation, and not a measurement** -- the same one
#: `webui/boards/rp2040.py` makes for its TIMER, and it is worth reading that
#: file's paragraph beside this one. Arduino's `init()` sets timer 0's
#: prescaler to 64 (`sbi(TCCR0B, CS01); sbi(TCCR0B, CS00);`), so on the silicon
#: TCNT0 advances once per 64 clock cycles. This core models no cycle costs at
#: all, so 64 is exactly right only if every AVR instruction took one cycle --
#: which it does not: loads, stores and taken branches take two or three.
#:
#: So virtual time here runs somewhere around 1.5x slow against a real Uno, and
#: **this model does not claim cycle accuracy**. What it does guarantee is what
#: a busy-wait needs: time that is monotonic, deterministic, and an integer.
#:
#: The prescaler is this number and not a reading of TCCR0B. A sketch that set
#: a different one would be believed and ignored -- recorded in `core/avr/cpu.h`
#: beside the `Timer` struct, where the next reader of the mechanism will see it.
INSTRUCTIONS_PER_TICK = 64

#: USART0, as **data** addresses. From `iom328p.h:737,747,757,771,781,787`:
#:
#:     #define UCSR0A _SFR_MEM8(0xC0)
#:     #define UCSR0B _SFR_MEM8(0xC1)
#:     #define UCSR0C _SFR_MEM8(0xC2)
#:     #define UBRR0L _SFR_MEM8(0xC4)
#:     #define UBRR0H _SFR_MEM8(0xC5)
#:     #define UDR0   _SFR_MEM8(0xC6)
#:
#: All six are `_SFR_MEM8`, so none of them takes the +0x20 that PORTB and the
#: timer registers do. That is the opposite trap to timer 0's, where four of
#: five were `_SFR_IO8` and one was not.
UCSR0A = 0xC0
UCSR0B = 0xC1
UCSR0C = 0xC2
UBRR0L = 0xC4
UBRR0H = 0xC5
UDR0 = 0xC6

#: Bit numbers within those, from `iom328p.h:739,743,744,751,752`.
U2X0 = 1     #: double-speed; halves the divisor, so it changes the baud rate
UDRE0 = 5    #: data register empty -- what Arduino's fast path tests
TXC0 = 6     #: transmit complete -- what `flush()` waits for
TXEN0 = 3    #: transmitter enable, in UCSR0B
RXEN0 = 4    #: receiver enable, in UCSR0B; see `USART_PINS`, not `map_usart`

#: The bits of UCSR0A that always read set here, and the reason this board can
#: print at all.
#:
#: **Measured 2026-08-26.** `HardwareSerial::write` has two paths. If the ring
#: buffer is empty and UDRE0 is set it writes the byte straight to UDR0 and
#: returns; otherwise it queues the byte and enables the USART_UDRE interrupt to
#: drain it. With UDRE0 reading clear, a `Serial.println` sketch took the second
#: path, set UDRIE0, and waited forever for an interrupt this core does not
#: raise -- UCSR0B read 0xB8 and nothing was ever transmitted.
#:
#: TXC0 is here for `flush()`, which spins until transmission completes.
#:
#: Both are true of a transmitter whose byte is gone before the next
#: instruction, which is what this models. See `core/avr/cpu.h`'s `Usart`.
USART_READY = (1 << UDRE0) | (1 << TXC0)

#: The Uno's crystal. A fact about the BOARD, not the chip -- an ATmega328P
#: runs from 1 MHz internal by default and the Uno puts a 16 MHz crystal beside
#: it. Named because `baud_rate` divides by it.
F_CPU_HZ = 16_000_000

#: The Uno's user LED. From Arduino's own variant file,
#: `framework-arduino-avr/variants/standard/pins_arduino.h:54`, which defines
#: `LED_BUILTIN` as 13, and its pinout comment at line 99: `PB5 (D 13)`.
#:
#: A fact about the board rather than the chip, kept here because the blink
#: test needs a pin and an arbitrary one would prove less.
LED_PIN = 5

#: Header label -> the port letter and bit behind it.
#:
#: **From Arduino's own tables**, not from a pinout picture:
#: `framework-arduino-avr/variants/standard/pins_arduino.h:150-194`, where
#: `digital_pin_to_port_PGM` gives `PD` for digital 0-7, `PB` for 8-13 and `PC`
#: for 14-19, and `digital_pin_to_bit_mask_PGM` gives `_BV(0)` upwards within
#: each. The labels are the ones `webui/boards/Arduino Uno.json` carries --
#: bare numbers, because that is what the silkscreen says, and `A0`-`A5` and
#: `SDA`/`SCL` because that is what it says there too.
#:
#: **`SDA` and `SCL` are `A4` and `A5`**, not extra pins. `pins_arduino.h:48-51`
#: makes them digital 18 and 19, which is PC4 and PC5, and the R3 header simply
#: brings the same two pads out a second time beside `AREF`. Two labels, one
#: piece of silicon each, and a sketch driving `A4` moves both rows of the
#: picture -- which is the truth about the board rather than a duplication bug.
#:
#: **Twenty-two of thirty-two pads, and the other ten are the point.** `AREF`,
#: `NC`, `IOREF`, `RESET`, `3V3`, `5V`, `VIN` and three `GND`s have no MCU pin
#: behind them and never will, so they are absent here and `webui.api.pin_view`
#: reports them `unknown` -- a sentence about this board, where `low` would be
#: a sentence about the program.
#:
#: `13` is the one that matters most: it is `LED_BUILTIN`, it is PB5, and it is
#: what a stock Blink drives.
HEADER: dict[str, tuple[str, int]] = {
    "0": ("D", 0),    # RX -- see USART_PINS
    "1": ("D", 1),    # TX -- see USART_PINS
    "2": ("D", 2),
    "3": ("D", 3),
    "4": ("D", 4),
    "5": ("D", 5),
    "6": ("D", 6),
    "7": ("D", 7),
    "8": ("B", 0),
    "9": ("B", 1),
    "10": ("B", 2),
    "11": ("B", 3),
    "12": ("B", 4),
    "13": ("B", LED_PIN),
    "A0": ("C", 0),
    "A1": ("C", 1),
    "A2": ("C", 2),
    "A3": ("C", 3),
    "A4": ("C", 4),
    "A5": ("C", 5),
    "SDA": ("C", 4),  # the same pad as A4
    "SCL": ("C", 5),  # the same pad as A5
}

#: The same table read the other way: label -> the pin as the datasheet spells
#: it, `13` -> `PB5`. Derived from `HEADER` so the two cannot disagree.
#:
#: One digit and not two, unlike the SAMD21's: `iom328p.h` writes `PB5`, and
#: matching each part's own spelling matters more than matching each other.
PIN_NAMES: dict[str, str] = {
    label: f"P{port}{bit}" for label, (port, bit) in HEADER.items()
}

#: What a pin of this part can actually drive, so that a circuit can be solved.
#:
#: **Read out of the PDFs on 2026-08-27, not recalled.** `webui/api.py` sends
#: this to the page beside the pad map and `webui/static/circuit.js` builds a
#: netlist from it; a board that does not publish one gets no circuit and the
#: panel says so rather than showing a part lighting for reasons nobody can
#: state.
#:
#: **Every resistance here is an UPPER bound, and that is the whole design.**
#: Each is derived from a *guaranteed* corner of the datasheet -- the worst
#: output voltage at the stated test current -- so the real output resistance
#: is at most this, so the current computed through it is at LEAST what the
#: page reports. A lower bound over a rating is a fact; a lower bound under one
#: says nothing. That is why `circuit.js` may warn and may never reassure.
#:
#: `volts` is a fact about the BOARD and the rest are facts about the chip.
#: They are together because the Arduino Uno is the only ATmega328P board here
#: and splitting them would be a second file to keep in step for no reader's
#: benefit -- but the day a 3.3 V ATmega328P board arrives, `volts` is the
#: field that moves and the two 3 V rows quoted below are what it moves to.
SUPPLY: dict[str, object] = {
    "chip": "ATmega328P",
    "volts": 5.0,
    "source_ohms": 40.0,
    "sink_ohms": 45.0,
    "rated_amps": 0.020,
    "absolute_amps": 0.040,
    "cited": {
        "volts": (
            "Arduino's own tech specs for the UNO R3, `I/O Voltage: 5V` -- "
            "`content/hardware/02.uno/boards/uno-rev3/tech-specs.yml` in "
            "`arduino/docs-content`, read 2026-08-27. A fact about the board "
            "rather than the chip, which runs from 1.8 V to 5.5 V"
        ),
        "source_ohms": (
            "derived: (5.0 - 4.2) / 0.020. ATmega48A/PA/88A/PA/168A/PA/328/P "
            "datasheet DS40002061B (Microchip, 2020), Table 30-1 on page 323: "
            "VOH, Output High Voltage except RESET pin, min 4.2 V at "
            "IOH = -20 mA, VCC = 5 V, TA = 85 C. A MINIMUM output voltage is a "
            "MAXIMUM resistance. The 3 V row of the same table is "
            "IOH = -10 mA, VOH min 2.3 V -> 70 ohm"
        ),
        "sink_ohms": (
            "derived: 0.9 / 0.020. Same datasheet, Table 30-1 on page 322: "
            "VOL, Output Low Voltage except RESET pin, max 0.9 V at "
            "IOL = 20 mA, VCC = 5 V, TA = 85 C. The 3 V row is IOL = 10 mA, "
            "VOL max 0.6 V -> 60 ohm"
        ),
        "rated_amps": (
            "Arduino's tech specs again, `DC Current per I/O Pin: 20 mA`. It "
            "agrees with the datasheet's own test condition -- notes 3 and 4 "
            "of Table 30-1 say a port can source or sink more than 20 mA at "
            "VCC = 5 V but that VOH and VOL are then not ensured"
        ),
        "absolute_amps": (
            "DS40002061B section 30.1, Absolute Maximum Ratings, page 322: "
            "`DC Current per I/O Pin . . . 40.0mA`. A stress rating -- the "
            "page above it says operation at these conditions is not implied"
        ),
    },
}

#: Header label -> the `UCSR0B` bit that takes the pad away from PORTD.
#:
#: **`Serial.begin()` never writes `DDRD`, and this is the measurement that
#: says so.** 2026-08-26: a sketch calling `Serial.begin(9600)` and
#: `Serial.println` was built through `webui/compile.py`, run for 200,000
#: instructions, printed `hi`, and finished with `UCSR0B` at 0b10011000 --
#: `RXEN0` and `TXEN0` both set -- and `DDRD` still at 0b00000000. On the
#: silicon the USART has taken PD0 and PD1 by then; in the direction register
#: there is no trace of it.
#:
#: So without this, pins 0 and 1 would report `input`, which reads as "nobody
#: is driving this" about a pin the transmitter is driving. `unknown` is the
#: honest answer and the vocabulary already has it: `webui/api.py`'s four
#: states separate a claim about the program from a claim about this model,
#: and what this model cannot say is what the USART is doing to the pad.
#:
#: Bit numbers from `iom328p.h:751-752`.
USART_PINS: dict[str, int] = {"0": RXEN0, "1": TXEN0}

#: label -> the control register and COM mask of the compare output wired to
#: that pad. The six pins an Uno's silkscreen marks with a tilde.
#:
#: **The same argument `USART_PINS` makes, for a second peripheral.** A timer
#: that has taken a pad drives it from a compare unit this model does not
#: count, so `PORTx` says nothing about the level -- and reading `PORTx`
#: anyway answers `low` about a pin carrying a square wave. Measured
#: 2026-08-26: `analogWrite(3, 128)` leaves `DDRD` 0b00001000, `PORTD`
#: 0b00000000 and `TCCR2A` 0b00100001, `COM2B1` set.
#:
#: **`unknown` is the answer and a duty cycle is not.** `core/avr` models no
#: PWM, and this repository's four states already have the word for "this
#: model cannot say". Reporting a waveform would need a peripheral nobody has
#: asked for; reporting `low` is the confident wrong answer this ranks below a
#: loud one. OH-71.
#:
#: **Which pad belongs to which output is the vendor's own table**, not a
#: recollection: `digital_pin_to_timer_PGM` in
#: `framework-arduino-avr/variants/standard/pins_arduino.h:196-232` gives
#: TIMER2B, TIMER0B, TIMER0A, TIMER1A, TIMER1B and TIMER2A for 3, 5, 6, 9, 10
#: and 11, and nothing for the other fourteen.
TIMER_PINS: dict[str, tuple[int, int]] = {
    "3": (TCCR2A, COM_B_MASK),    # OC2B, PD3
    "5": (TCCR0A, COM_B_MASK),    # OC0B, PD5
    "6": (TCCR0A, COM_A_MASK),    # OC0A, PD6
    "9": (TCCR1A, COM_A_MASK),    # OC1A, PB1
    "10": (TCCR1A, COM_B_MASK),   # OC1B, PB2
    "11": (TCCR2A, COM_A_MASK),   # OC2A, PB3
}



class Cpu(typing.Protocol):
    """What this module needs of a core, which is two calls.

    Still narrower than either Arm board's protocol by every mapping method:
    `rp2040.py` needs seven and this needs one, because on this part almost
    every register really is a byte of the data space that stores what was
    written to it. The exception is the one below.
    """

    def configure(self, program_words: int, data_bytes: int) -> None: ...
    def map_timer(self, *, counter: int, flag: int, enable: int, bit: int,
                  vector: int, instructions_per_tick: int) -> None: ...
    def map_usart(self, *, data: int, status: int, control: int,
                  enable_bit: int, ready_mask: int) -> None: ...
    def usart_output(self) -> bytes: ...
    def read_data(self, address: int) -> int: ...


def install(cpu: Cpu) -> None:
    """Size both address spaces, and give the machine timer 0.

    **Postcondition, and `core/avr/machine.py` depends on it:** `configure`
    resets the machine -- data zeroed, program filled with the erased word
    0xFFFF, SP at `STACK_TOP`. `webui/api.py` writes the image *after* calling
    this and enters afterwards, so the order is install, load, enter, and
    reversing the first two would erase the image.

    **The timer is mapped after `configure` and not before**, for the same
    reason: `configure` resets, and a reset before a mapping is a mapping that
    survives while a reset after one is a mapping that does not need to.
    """
    cpu.configure(program_words=PROGRAM_WORDS, data_bytes=DATA_BYTES)
    cpu.map_timer(
        counter=TCNT0,
        flag=TIFR0,
        enable=TIMSK0,
        bit=TOV0,
        vector=TIMER0_OVF_VECTOR,
        instructions_per_tick=INSTRUCTIONS_PER_TICK,
    )
    cpu.map_usart(
        data=UDR0,
        status=UCSR0A,
        control=UCSR0B,
        enable_bit=TXEN0,
        ready_mask=USART_READY,
    )


def uart0_output(cpu: Cpu) -> bytes:
    """Everything USART0 has transmitted, oldest byte first.

    **The name is the contract.** `webui/api.py`'s `uart_view` finds this by
    `getattr(description, "uart0_output", None)` and reports `present: false`
    when it is absent -- which is a claim about the *model* rather than about
    the program, and is why an empty console and an unmodelled UART are
    different answers. `webui/boards/rp2040.py` exports the same name for the
    same reason.
    """
    return cpu.usart_output()


def pin_states(cpu: Cpu) -> dict[str, str]:
    """What every header pin this board knows about is doing, right now.

    The same contract `webui/boards/samd21.py` documents at length, and found
    the same way -- `getattr(description, "pin_states", None)`. Two boards over
    two different cores export one name, which is what keeps `webui/api.py`
    free of chip knowledge.

    **The direction register decides before the output register does.** On an
    AVR the same bit of `PORTx` means "drive high" for an output and "enable
    the pull-up" for an input, so reading it without `DDRx` reports a pull-up
    as a driven high -- a plausible, wrong answer of exactly the kind this
    repository ranks below a loud one. `input` is as far as this can honestly
    go, because this model has no pulls and nothing is wired to the far end.

    **A pad the USART has taken is `unknown` and not `input`**, which is the
    one place this function looks at something that is not a port. See
    `USART_PINS` for the measurement: `Serial.begin` leaves no trace in `DDRD`,
    so the direction register alone would answer confidently and wrongly about
    the two pins a `Serial` sketch is using.

    **And a pad a TIMER has taken is `unknown` too** (OH-71), which is the
    same argument for a second peripheral: `analogWrite(3, 128)` sets `DDRD`
    bit 3, leaves `PORTD` bit 3 clear and hands the pad to timer 2's compare
    output, so reading `PORTD` answers `low` about a pin carrying a square
    wave. See `TIMER_PINS` for the six pads and the vendor table they come
    from.

    **The direction register is asked FIRST, and that is not just ordering.**
    A compare output only reaches the pin when the DDR bit says output -- the
    datasheet is explicit that "the Data Direction Register bit for the OCnx
    pin must be set as output before the OCnx value is visible on the pin" --
    so a pad with `COM` bits set and DDR clear really is an input, and saying
    `unknown` about it would be this function's own confident wrong answer.
    """
    control = cpu.read_data(UCSR0B)
    states: dict[str, str] = {}
    for label, (port, bit) in HEADER.items():
        mask = 1 << bit
        enable = USART_PINS.get(label)
        if enable is not None and control & (1 << enable):
            states[label] = "unknown"
            continue
        direction, output = PORTS[port]
        if not cpu.read_data(direction) & mask:
            states[label] = "input"
            continue
        timer = TIMER_PINS.get(label)
        if timer is not None and cpu.read_data(timer[0]) & timer[1]:
            states[label] = "unknown"
            continue
        states[label] = "high" if cpu.read_data(output) & mask else "low"
    return states

def baud_rate(cpu: Cpu) -> int:
    """The baud rate the program asked for, from UBRR0 and U2X0.

    Reported rather than ignored, because the divisor is the one thing a
    `Serial.begin()` actually configures that this model could otherwise drop
    on the floor -- and a wrong baud rate is the classic reason a console shows
    nothing on real hardware. Reading it back is what makes the difference
    between modelling the register and merely accepting writes to it.

    `F_CPU / ((u2x ? 8 : 16) * (UBRR0 + 1))`, per the datasheet's own table.
    `Serial.begin(9600)` on a 16 MHz Uno gives UBRR0 = 207 with U2X0 set, which
    is 9,615 -- the 0.16% error the part really has, not 9,600.
    """
    divisor = cpu.read_data(UBRR0L) | (cpu.read_data(UBRR0H) << 8)
    prescale = 8 if cpu.read_data(UCSR0A) & (1 << U2X0) else 16
    return F_CPU_HZ // (prescale * (divisor + 1))
