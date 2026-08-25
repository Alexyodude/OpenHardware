# OpenHardware — USART0, and why it needs no interrupt.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The measurement this file exists because of
#
# OH-63 predicted that `Serial.print` would need a second interrupt source,
# because `HardwareSerial` drains its ring buffer from the USART_UDRE handler.
# That prediction was wrong, and the ticket said to check rather than assume.
#
# `HardwareSerial::write` has TWO paths:
#
#     if (_tx_buffer_head == _tx_buffer_tail && bit_is_set(*_ucsra, UDRE0)) {
#       *_udr = c;          // straight out, no interrupt involved
#       return 1;
#     }
#     ...                   // otherwise queue it and set UDRIE0
#
# Measured 2026-08-26 with UDRE0 reading clear: a `Serial.println` sketch took
# the second path, left UCSR0B at 0xB8 with UDRIE0 set, and waited forever.
# With UDRE0 reading set it took the first, UCSR0B came back 0x98 with UDRIE0
# **clear**, and the bytes arrived.
#
# So `core/avr` keeps exactly one interrupt source. Building a general table
# with no caller would have been the generalisation `.claude/CLAUDE.md` rule 6
# forbids, justified by a prediction that measurement refuted.
#
# ## What is asserted here rather than in test_arduino_sketch.py
#
# That file compiles a real sketch and needs the Arduino framework, so it
# skips where the framework is absent. These run anywhere the core builds.

import pytest

from core.avr import abi
from webui.boards import atmega328p as board

#: SREG in the data space. Written rather than assigned, as `test_timer.py`
#: does: the register is a byte of memory and there is no second way to it.
SREG = 0x5F

TXEN0 = 1 << board.TXEN0
UDRE0 = 1 << board.UDRE0
TXC0 = 1 << board.TXC0
U2X0 = 1 << board.U2X0


@pytest.fixture
def uno(cpu):
    """The `cpu` fixture with the board installed, which is what maps a USART."""
    board.install(cpu)
    return cpu


def enable(cpu) -> None:
    """What `Serial.begin` does that matters here: turn the transmitter on."""
    cpu.write_data(board.UCSR0B, TXEN0)


# --- the status register ----------------------------------------------------


def test_the_data_register_reads_as_ready(uno):
    """**The single most load-bearing bit in this file.** UDRE0 clear sends
    Arduino down the interrupt path and the sketch hangs. See the header."""
    assert uno.read_data(board.UCSR0A) & UDRE0


def test_transmission_reads_as_already_complete(uno):
    """TXC0, which is what `flush()` spins on. It has already happened here,
    because a byte written to this model is gone before the next
    instruction."""
    assert uno.read_data(board.UCSR0A) & TXC0


def test_the_status_register_still_remembers_what_was_written(uno):
    """The ready bits are ORed into the read, not substituted for it.

    U2X0 is the reason this matters: `Serial.begin` writes it and
    `board.baud_rate` reads it back to know whether the divisor is over 8 or
    over 16. A status register that answered a constant would lose it and
    report the wrong baud rate at every speed.
    """
    uno.write_data(board.UCSR0A, U2X0)
    got = uno.read_data(board.UCSR0A)
    assert got & U2X0, "the written bit was lost"
    assert got & UDRE0, "the ready bits were lost"


# --- transmitting -----------------------------------------------------------


def test_a_write_before_the_transmitter_is_enabled_is_discarded(uno):
    """A missing `Serial.begin()` is the commonest mistake in an Arduino
    sketch, and this is what makes it visible.

    The silicon discards it and `webui/boards/rp2040.py` models the same thing
    for its own UART. Buffering it instead would make the console show output
    from a program that never opened the port.
    """
    uno.write_data(board.UDR0, ord("A"))
    assert board.uart0_output(uno) == b""


def test_a_write_after_the_transmitter_is_enabled_is_transmitted(uno):
    enable(uno)
    uno.write_data(board.UDR0, ord("A"))
    assert board.uart0_output(uno) == b"A"


def test_bytes_arrive_in_the_order_they_were_written(uno):
    """Oldest first. A console that reordered output would be worse than one
    that showed none."""
    enable(uno)
    for byte in b"hello":
        uno.write_data(board.UDR0, byte)
    assert board.uart0_output(uno) == b"hello"


def test_output_is_cumulative_and_reading_it_does_not_drain_it(uno):
    """`webui/api.py`'s `uart_view` reports what is true rather than a delta,
    because two browser tabs polling a delta would each consume bytes the
    other never saw. This is the property that lets it."""
    enable(uno)
    uno.write_data(board.UDR0, ord("x"))
    assert board.uart0_output(uno) == b"x"
    assert board.uart0_output(uno) == b"x"


def test_binary_output_survives_unchanged(uno):
    """Firmware printing bytes that are not text is ordinary. Nothing here
    decodes, so nothing here can mangle -- `uart_view` is where the decoding
    decision lives, and it escapes rather than replaces."""
    enable(uno)
    for byte in (0x00, 0xFF, 0x80, 0x0A):
        uno.write_data(board.UDR0, byte)
    assert board.uart0_output(uno) == b"\x00\xff\x80\n"


def test_a_reset_clears_what_the_last_run_printed(uno):
    """A reset is a new run of the program. The MAPPING survives -- a board
    wires its peripherals once -- but the bytes do not, or a reloaded sketch
    would appear to print its predecessor's output."""
    enable(uno)
    uno.write_data(board.UDR0, ord("x"))
    uno.reset()
    board.install(uno)
    assert board.uart0_output(uno) == b""


def test_reading_the_data_register_answers_zero(uno):
    """Nothing is wired to the receiver, so there is nothing to read. RXC0 is
    deliberately not among the ready bits, which is what makes
    `Serial.available()` answer false -- the truth, not a gap."""
    enable(uno)
    uno.write_data(board.UDR0, ord("A"))
    assert uno.read_data(board.UDR0) == 0


# --- the baud rate ----------------------------------------------------------


def test_the_baud_rate_is_computed_from_the_divisor_and_the_speed_bit(uno):
    """207 with U2X0 set is what `Serial.begin(9600)` writes on a 16 MHz Uno,
    and 9,615 is what the part really runs at -- the 0.16% error is real
    silicon behaviour, not a rounding mistake here."""
    uno.write_data(board.UBRR0L, 207)
    uno.write_data(board.UBRR0H, 0)
    uno.write_data(board.UCSR0A, U2X0)
    assert board.baud_rate(uno) == 9615


def test_the_speed_bit_halves_the_divisor(uno):
    """The same divisor without U2X0 is half the rate. Asserted because
    reading UBRR0 and ignoring U2X0 would be wrong by exactly a factor of two
    and still look plausible."""
    uno.write_data(board.UBRR0L, 207)
    uno.write_data(board.UBRR0H, 0)
    uno.write_data(board.UCSR0A, 0)
    assert board.baud_rate(uno) == 4807


def test_the_high_byte_of_the_divisor_is_not_dropped(uno):
    """UBRR0 is twelve bits and slow rates use the top four. A model reading
    only UBRR0L would report a wildly wrong rate for any baud under 2400."""
    uno.write_data(board.UBRR0L, 0xFF)
    uno.write_data(board.UBRR0H, 0x03)
    uno.write_data(board.UCSR0A, 0)
    assert board.baud_rate(uno) == 16_000_000 // (16 * 1024)


# --- the mapping itself -----------------------------------------------------


def test_a_usart_outside_the_data_space_is_refused_with_its_numbers(uno):
    """`write_data` indexes the control register without a bounds check on the
    path of every store a program makes, so the check happens once at mapping
    time -- and names the value that was wrong."""
    with pytest.raises(abi.AbiError) as caught:
        uno.map_usart(data=0xFFFF, status=board.UCSR0A, control=board.UCSR0B,
                      enable_bit=board.TXEN0, ready_mask=board.USART_READY)
    assert "0xffff" in str(caught.value)
