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
    size_t write(int value);
    size_t write(const uint8_t* data, size_t length);
    uint8_t endTransmission(bool stop = true);

    uint8_t requestFrom(uint8_t address, uint8_t quantity, bool stop = true);
    int available(void);
    int read(void);

private:
    /* 31 bytes and the address byte make the controller's 32-byte FIFO
     * (SOC_I2C_FIFO_LEN). */
    enum { kBuffer = 31 };

    uint8_t tx_[kBuffer];
    uint8_t rx_[kBuffer];
    uint8_t tx_address_;
    uint8_t tx_length_;
    uint8_t rx_length_;
    uint8_t rx_index_;
    bool deferred_;
};

extern OhWire Wire;

#endif
