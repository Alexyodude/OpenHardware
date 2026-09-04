/* OpenHardware - Serial against the modelled transmit FIFO, and nothing more.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## What this is a face on
 *
 * One address: `OH_UART_FIFO`, which the board's description maps as a
 * *stream* rather than as a register (`core/riscv32`'s `map_stream`, added
 * for exactly this). Every byte written to it is kept, so a print arrives
 * whole; a register there would hold the last character and a reader would
 * see a plausible letter instead of a wrong answer.
 *
 * ## Which of the board's two serial ports this is, because it is not the
 * default one
 *
 * UART0, and on a real XIAO that is **not** where Arduino's `Serial` goes
 * unless you say so. Seeed's own page for the C3
 * (`XIAO_ESP32C3_Pin_Multiplexing.md:112-126`) says USB serial is enabled by
 * default and that using UART0 instead means wiring `D6` as TX and `D7` as RX
 * to a USB-serial adapter and setting USB CDC On Boot to Disabled; the C6's
 * page documents the same two pins. The default path is USB_SERIAL_JTAG at
 * 0x60043000, which no description here maps -- so a program reaching for it
 * faults at a named address rather than printing somewhere it would not have.
 *
 * So a sketch that prints here models the vendor's documented *alternative*
 * wiring, and the console pane shows what that adapter would have received.
 * `webui/boards/esp32c3.py` carries the citations, including the research
 * file that recorded this in August.
 *
 * ## What `begin` does, and what it deliberately does not
 *
 * It sets the transmit clock bit, and that is all. The vendors set that bit
 * out of reset -- `UART_TX_SCLK_EN` is `default: 1` on all three parts -- so
 * a sketch that never calls `begin` still prints, exactly as it would on the
 * silicon. `begin` is here because every Arduino sketch writes it and a
 * missing symbol would fail the build for a line that is not the problem.
 *
 * **The baud rate is ignored, and this is the honest half of that.** The
 * board's description maps no divisors: nothing here has a wire or a bit
 * rate, so a number written to one would mean nothing and reading it back
 * would answer a question this model cannot answer. Bytes appear in the
 * console the instant they are written, at every baud rate, and the pane
 * shows what was transmitted rather than what a receiver would have decoded.
 *
 * ## Why the numbers are formatted here
 *
 * `-nostdlib`: there is no `itoa`, no `printf`, no `libc` at all. Nine lines
 * of long division is the whole cost, and it keeps the API surface equal to
 * what the model maps -- the rule `Arduino.h` states.
 */

#include "Arduino.h"

namespace {

/* The widest decimal an unsigned 32-bit value needs, plus a sign. */
constexpr unsigned kDigits = 11;

void put(uint8_t byte) { OH_REG(OH_UART_FIFO) = byte; }

void put_unsigned(unsigned long value) {
    char digits[kDigits];
    unsigned length = 0;
    do {
        digits[length++] = static_cast<char>('0' + (value % 10u));
        value /= 10u;
    } while (value != 0u && length < kDigits);
    while (length != 0u) {
        put(static_cast<uint8_t>(digits[--length]));
    }
}

}  // namespace

OhSerial Serial;

void OhSerial::begin(unsigned long baud) {
    /* The baud is accepted and unused; see this file's header for why that
     * is a statement about the model rather than an oversight. `(void)` so
     * the compiler does not warn about a parameter the API requires. */
    (void)baud;
    OH_REG(OH_UART_CLK_CONF) = OH_REG(OH_UART_CLK_CONF) | OH_UART_TX_SCLK_EN;
}

void OhSerial::end(void) {
    /* Clearing the gate is what stops the part transmitting, and the board
     * description gates its stream on the same bit -- so after this, bytes
     * written to the FIFO are discarded rather than queued. */
    OH_REG(OH_UART_CLK_CONF) = OH_REG(OH_UART_CLK_CONF) & ~OH_UART_TX_SCLK_EN;
}

void OhSerial::write(uint8_t byte) { put(byte); }

void OhSerial::print(const char* text) {
    if (text == 0) {
        return;
    }
    while (*text != '\0') {
        put(static_cast<uint8_t>(*text++));
    }
}

void OhSerial::print(char value) { put(static_cast<uint8_t>(value)); }

void OhSerial::print(long value) {
    if (value < 0) {
        put('-');
        /* Negated as unsigned, so LONG_MIN does not overflow on the way --
         * `-value` on the most negative long is undefined behaviour, and this
         * is the standard way round it.
         *
         * A sketch cannot reach that value with a literal: -2147483648 does
         * not fit a 32-bit `long`, so C++ types it `long long` and the call
         * is ambiguous across these overloads. `-2147483647L - 1L` is how the
         * bounds test writes it, and how anyone else would have to. */
        put_unsigned(0ul - static_cast<unsigned long>(value));
    } else {
        put_unsigned(static_cast<unsigned long>(value));
    }
}

void OhSerial::print(int value) { print(static_cast<long>(value)); }

void OhSerial::print(unsigned long value) { put_unsigned(value); }

void OhSerial::print(unsigned int value) {
    put_unsigned(static_cast<unsigned long>(value));
}

/* Arduino's line ending is CR LF, and both vendor cores on this machine say
 * so in the same words: `framework-arduinoespressif32/cores/esp32/Print.cpp:
 * 169-172` and `framework-arduino-avr/cores/arduino/Print.cpp:126-129` each
 * write "\r\n" from `println(void)`.
 *
 * Worth citing precisely because a console that split lines on LF alone would
 * render either choice identically -- this is one of the places a wrong
 * answer is invisible, so it follows the vendor rather than what happens to
 * look right. */
void OhSerial::println(void) {
    put('\r');
    put('\n');
}

void OhSerial::println(const char* text) {
    print(text);
    println();
}

void OhSerial::println(char value) {
    print(value);
    println();
}

void OhSerial::println(long value) {
    print(value);
    println();
}

void OhSerial::println(int value) {
    print(value);
    println();
}

void OhSerial::println(unsigned long value) {
    print(value);
    println();
}

void OhSerial::println(unsigned int value) {
    print(value);
    println();
}
