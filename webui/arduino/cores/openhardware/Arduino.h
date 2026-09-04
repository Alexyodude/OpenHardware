/* OpenHardware - the Arduino surface of a described board, and nothing more.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## Why this core exists, when every chip here has a vendor core
 *
 * The vendor cores cannot execute on the boards `webui/boards/` describes.
 * Espressif's Arduino core is a face on ESP-IDF, which boots FreeRTOS and
 * calls into a mask ROM; Arduino's RP2040 core is a face on mbed, which
 * wants its scheduler. The descriptions model registers a compiled image
 * touches -- GPIO, and per part not much else -- so an image built on those
 * cores stops in its first hundred instructions, and a Build button whose
 * output does not run is the false affordance OH-140 removed from this UI.
 *
 * So this is the same answer `tools/model_from_datasheet.py` gives for
 * meshes nobody publishes: build the thing, cite every number, and say what
 * it is. **The API here is exactly what the board descriptions model.** A
 * function is present when every register it needs is mapped, and absent --
 * with a `Recipe.hints` row naming the modelling decision -- when one is
 * not. `digitalRead` is the worked example: `webui/boards/esp32c3.py`
 * leaves `GPIO_IN` unmapped on purpose (its comment says why), so this
 * header deliberately does not declare it, and reaching for it earns the
 * explanation at the moment gcc says "undefined reference".
 *
 * The pin NAMES are still the vendor's: each recipe puts the board's own
 * `pins_arduino.h` -- plain constants, freestanding -- on the include path,
 * so `D10` means what Seeed says it means without a copy here to drift.
 */

#ifndef OPENHARDWARE_ARDUINO_H
#define OPENHARDWARE_ARDUINO_H

#include <stdint.h>

#include "pins_arduino.h"  /* the vendor's names, via extra_includes */
#include "oh_board.h"      /* this board's modelled registers, cited */

#define LOW 0
#define HIGH 1

#define INPUT 0
#define OUTPUT 1

#ifdef __cplusplus
extern "C" {
#endif

/* The sketch's two halves, exactly as every Arduino core declares them. */
void setup(void);
void loop(void);

/* `pin` is the GPIO number, which on an ESP32-family variant is what the
 * vendor's D-constants already are. */
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);

/* A counted busy loop, because nothing on these boards models a timer.
 * What one millisecond COSTS is the variant's `OH_DELAY_LOOPS_PER_MS`,
 * and that constant's comment says what kind of number it is. */
void delay(unsigned long ms);

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus

/* `Serial`, present because the board's description maps a transmit FIFO --
 * the same rule as everything above: a function is here when every register
 * it needs is mapped. On the three ESP32 parts that is `OH_UART_FIFO`, a
 * *stream* rather than a register, and `OH_UART_CLK_CONF`'s transmit bit.
 *
 * **A class of this project's own, not Arduino's `HardwareSerial`.** That
 * one inherits `Print` and `Stream`, which bring `String`, virtual dispatch
 * and a receive path -- none of which this model has anywhere to put. The
 * methods below are the ones a sketch actually writes; anything else is a
 * missing symbol at the moment gcc says so, which is where this core prefers
 * to have the conversation.
 *
 * **No `read`, `available` or `peek`.** The description maps no receive
 * FIFO, nothing in this project drives RX, and a `read` that answered zero
 * would be a wrong value rather than a missing feature.
 *
 * `serial.cpp` says what `begin` does with the baud rate it is given, and why
 * ignoring it is a statement about the model. */
class OhSerial {
public:
    void begin(unsigned long baud);
    void end(void);

    void write(uint8_t byte);

    void print(const char* text);
    void print(char value);
    void print(int value);
    void print(long value);
    void print(unsigned int value);
    void print(unsigned long value);

    void println(void);
    void println(const char* text);
    void println(char value);
    void println(int value);
    void println(long value);
    void println(unsigned int value);
    void println(unsigned long value);
};

extern OhSerial Serial;

#endif /* __cplusplus */

#endif
