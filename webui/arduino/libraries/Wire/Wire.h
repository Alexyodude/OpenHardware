/* OpenHardware - Wire against the modelled I2C0 controller, and nothing more.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * Declared only where the board's `oh_board.h` defines `OH_I2C_*`, which is
 * the same rule `Arduino.h` states for `analogRead`: a function is here when
 * every register it needs is mapped. A board whose description maps no I2C
 * is not given this directory at all -- `webui/compile.py` carries a hint
 * row for it -- so the `#error` below is a second line, for a sketch that
 * reaches this header some other way.
 *
 * **A class of this project's own, not Arduino's `TwoWire`.** That one
 * inherits `Stream`, which brings `Print`, `String` and virtual dispatch;
 * `OhSerial` makes the same choice in `Arduino.h` and for the same reason.
 * It has no constructor and holds only zero-initialised state, so an image
 * linked `-nostdlib` needs no static initialiser to run before `setup`.
 * `Wire.cpp` says what each method does against the controller.
 */

#ifndef OPENHARDWARE_WIRE_H
#define OPENHARDWARE_WIRE_H

#include <stddef.h>

#include "Arduino.h"

#ifndef OH_I2C_CTR
#error "this board's oh_board.h defines no OH_I2C_*: its description maps no I2C controller, so Wire does not exist here"
#endif

class OhWire {
public:
    void begin(void);

    void setClock(uint32_t hz);

    void beginTransmission(uint8_t address);
    size_t write(uint8_t value);
    size_t write(const uint8_t* data, size_t length);
    /* The vendor reaches this through `Print::write(const char*, size_t)`
     * (`Print.h:70`), so `Wire.write(char_buffer, n)` compiles there. */
    size_t write(const char* data, size_t length) {
        return write(reinterpret_cast<const uint8_t*>(data), length);
    }

    /* The vendor's overloads (`Wire.h:136-155`), so `Wire.write(5u)`,
     * `Wire.write(5L)`, a `size_t` and a string literal all compile. Each
     * integer is cut to a byte, as the vendor cuts it; a string is its bytes
     * without the terminator. Inline, and with no `strlen`: this image links
     * `-nostdlib`. */
    size_t write(const char* text) {
        size_t length = 0;
        while (text != 0 && text[length] != '\0') {
            ++length;
        }
        return text == 0 ? 0 : write(reinterpret_cast<const uint8_t*>(text), length);
    }
    size_t write(unsigned long value) { return write(static_cast<uint8_t>(value)); }
    size_t write(long value) { return write(static_cast<uint8_t>(value)); }
    size_t write(unsigned int value) { return write(static_cast<uint8_t>(value)); }
    size_t write(int value) { return write(static_cast<uint8_t>(value)); }
    uint8_t endTransmission(bool stop = true);

    uint8_t requestFrom(uint8_t address, uint8_t quantity, bool stop = true);
    int available(void);
    int read(void);

private:
    /* **31 bytes here, against the vendor's 128** (`I2C_BUFFER_LENGTH`,
     * vendor `Wire.h:43`): 31 bytes and the address byte make the
     * controller's 32-byte FIFO (SOC_I2C_FIFO_LEN), and this model has no
     * interrupt to refill it mid-transaction. The vendor's `write` drops the
     * byte past its limit silently; here a byte past 31 is refused by
     * `write` (it returns 0) and `endTransmission` then returns 1, "data too
     * long", without sending anything. `requestFrom` reads at most 31 bytes. */
    enum { kBuffer = 31 };

    uint8_t tx_[kBuffer];
    uint8_t rx_[kBuffer];
    uint8_t tx_address_;
    uint8_t tx_length_;
    uint8_t rx_length_;
    uint8_t rx_index_;
    bool deferred_;
    bool overflow_;
};

extern OhWire Wire;

#endif
