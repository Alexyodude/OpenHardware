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
 * not. `analogWrite` is the worked example: no description maps the LEDC
 * peripheral, so this header deliberately does not declare it, and reaching
 * for it earns the explanation at the moment gcc says it was not declared.
 * `digitalRead` was the example until OH-161's step 3 mapped `GPIO_IN`, and
 * `analogRead` until its step 4 mapped ADC1's one-time sample; `analogRead`
 * is declared where the variant's `oh_board.h` defines that ADC.
 *
 * The pin NAMES are still the vendor's: each recipe puts the board's own
 * `pins_arduino.h` -- plain constants, and at most ESP-IDF's
 * `soc/soc_caps.h`, which the variant directory stands in for -- on the
 * include path, so `D10` means what the vendor says it means without a copy
 * here to drift.
 */

#ifndef OPENHARDWARE_ARDUINO_H
#define OPENHARDWARE_ARDUINO_H

#include <stdint.h>

#include "pins_arduino.h"  /* the vendor's names, via extra_ or bsp_includes */
#include "oh_board.h"      /* this board's modelled registers, cited */

#define LOW 0
#define HIGH 1

/* The four modes and their numbers as Arduino's own API declares them,
 * `ArduinoCore-API`'s `api/Common.h:39-42` at a1f668d. Not arduino-esp32's
 * numbers (`INPUT` 0x01, `OUTPUT` 0x03, `INPUT_PULLUP` 0x05,
 * `INPUT_PULLDOWN` 0x09, `cores/esp32/esp32-hal-gpio.h:46-53` at 2787dab),
 * which are bit fields for its own `gpio_config`; what this core takes from
 * them is the meaning -- an `OUTPUT` reads back its own level -- and not the
 * encoding. A sketch names the mode, so the numbers are this core's own. */
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define INPUT_PULLDOWN 3

#ifdef __cplusplus
extern "C" {
#endif

/* The sketch's two halves, exactly as every Arduino core declares them. */
void setup(void);
void loop(void);

/* `pin` is the GPIO number, which on an ESP32-family variant is what the
 * vendor's D-constants already are.
 *
 * A pin at or past the chip's GPIO count, `OH_GPIO_PIN_COUNT` in the
 * variant's `oh_board.h`, is no GPIO. `wiring.c` writes no bit for one, and
 * one the compiler knows -- a constant such as an RGB board's
 * `LED_BUILTIN`, which arduino-esp32 numbers `SOC_GPIO_PIN_COUNT` plus the
 * LED's pin -- stops the build at the call, where the recipe's hint says
 * what it is, rather than building a sketch that moves nothing. The three
 * functions are these inline checks in front of `wiring.c`'s own.
 *
 * `digitalRead` reads `GPIO_IN`, which reads the pins (OH-161 step 3):
 * what `pinMode` set the pad to, and what the outside drives it to.
 * Declared `int`, as arduino-esp32 declares it. */
void oh_pin_mode(uint8_t pin, uint8_t mode);
void oh_digital_write(uint8_t pin, uint8_t value);
int oh_digital_read(uint8_t pin);
void oh_pin_is_past_this_chips_gpio_count(void)
    __attribute__((error("the pin is at or past this chip's GPIO count")));

static inline __attribute__((always_inline)) void pinMode(uint8_t pin, uint8_t mode) {
    if (__builtin_constant_p(pin) && pin >= OH_GPIO_PIN_COUNT) {
        oh_pin_is_past_this_chips_gpio_count();
    }
    oh_pin_mode(pin, mode);
}

static inline __attribute__((always_inline)) void digitalWrite(uint8_t pin, uint8_t value) {
    if (__builtin_constant_p(pin) && pin >= OH_GPIO_PIN_COUNT) {
        oh_pin_is_past_this_chips_gpio_count();
    }
    oh_digital_write(pin, value);
}

static inline __attribute__((always_inline)) int digitalRead(uint8_t pin) {
    if (__builtin_constant_p(pin) && pin >= OH_GPIO_PIN_COUNT) {
        oh_pin_is_past_this_chips_gpio_count();
    }
    return oh_digital_read(pin);
}

#ifdef OH_ADC_ONETIME_SAMPLE
/* `analogRead` converts the pin's voltage on ADC1, through the one-time
 * sample the board's description maps (OH-161 step 4), at 12 dB as
 * arduino-esp32 does by default, and returns the 12-bit code. Declared
 * `uint16_t`, as arduino-esp32 declares it (`cores/esp32/esp32-hal-adc.h:42`
 * at 2787dab). A pin on no ADC1 channel -- `OH_ADC1_FIRST_GPIO` and the
 * `OH_ADC1_CHANNELS` after it -- reads 0, as arduino-esp32's does after
 * logging that it is no ADC pin, and one the compiler knows stops the
 * build at the call, where the recipe's hint says why. */
uint16_t oh_analog_read(uint8_t pin);
void oh_pin_is_on_no_adc1_channel(void)
    __attribute__((error("the pin is on no ADC1 channel of this chip")));

static inline __attribute__((always_inline)) uint16_t analogRead(uint8_t pin) {
    if (__builtin_constant_p(pin) &&
        (pin < OH_ADC1_FIRST_GPIO || pin >= OH_ADC1_FIRST_GPIO + OH_ADC1_CHANNELS)) {
        oh_pin_is_on_no_adc1_channel();
    }
    return oh_analog_read(pin);
}
#endif

/* Time since the board was installed, read from SYSTIMER unit 0, which the
 * board's description maps and `wiring.c` reads the way ESP-IDF does. Both
 * wrap at 2^32, as Arduino's own do. What a millisecond is in emulator steps
 * is the description's SYSTIMER_INSTRUCTIONS_PER_TICK times sixteen
 * thousand, and that constant's comment says what kind of number it is. */
unsigned long millis(void);
unsigned long micros(void);

/* Waits on the same SYSTIMER unit 0, so its millisecond is millis()'s: a
 * sketch timing a delay() with millis() reads what it asked for. */
void delay(unsigned long ms);

/* Waits on the same SYSTIMER unit 0, so its microsecond is micros()'s: a
 * sketch timing a delayMicroseconds() with micros() reads what it asked
 * for. Declared as arduino-esp32 declares it (`cores/esp32/esp32-hal.h:170`
 * at 2787dab). */
void delayMicroseconds(uint32_t us);

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
