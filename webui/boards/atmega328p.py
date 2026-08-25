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

**Where that stops being true, and it does:** `PINB` reads the *electrical
level on the pins*, so on a pin driven as an output it follows `PORTB`, and on
a pin driven as an input it follows whatever is wired to it. This model returns
the stored zero. That is a wrong answer rather than a fault, which is the
failure class this repository ranks worst -- and unlike `samd21.py`, which
could leave its `PORT_IN` unmapped so a read faults instead of lying, there is
nothing to unmap here: every byte of the data space exists.

So it is written down instead. `PINB` is exported below so a test can name it,
`test_reading_the_input_register_is_not_yet_modelled` pins the limitation
rather than the behaviour, and the fix -- a mirror of `PORTB` masked by `DDRB`
-- needs a mapping mechanism this core does not have. Nothing has read `PINB`
yet; the day something does, that is the first claim to re-check.

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

#: PORTB and its two companions, as **data** addresses. From `iom328p.h:54,64,74`:
#:
#:     #define PINB  _SFR_IO8(0x03)
#:     #define DDRB  _SFR_IO8(0x04)
#:     #define PORTB _SFR_IO8(0x05)
#:
#: `_SFR_IO8(x)` is `x + 0x20` in the data space, so an `in`/`out` instruction
#: uses the small number and everything else uses the one below. **That +0x20
#: is the likeliest off-by-something in an AVR model**, which is why both forms
#: are written out here rather than one being derived at the call site.
PINB_IO, PINB = 0x03, 0x23
DDRB_IO, DDRB = 0x04, 0x24
PORTB_IO, PORTB = 0x05, 0x25

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

#: Bit numbers within those, from `iom328p.h:739,743,744,751`.
U2X0 = 1     #: double-speed; halves the divisor, so it changes the baud rate
UDRE0 = 5    #: data register empty -- what Arduino's fast path tests
TXC0 = 6     #: transmit complete -- what `flush()` waits for
TXEN0 = 3    #: transmitter enable, in UCSR0B

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
