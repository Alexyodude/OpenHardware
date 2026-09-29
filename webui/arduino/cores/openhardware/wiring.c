/* OpenHardware - pinMode, digitalWrite and delay against the modelled GPIO.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * Every register named here is one the board's description maps, through
 * the variant's `oh_board.h`, whose addresses a test holds equal to the
 * description's own constants. The writes go through the W1TS/W1TC aliases
 * rather than read-modify-write on OUT -- the same registers ESP-IDF's own
 * GPIO driver uses, and the shape `core/riscv32`'s `map_alias` exists to
 * model.
 */

#include "Arduino.h"

/* A pin at or past the chip's GPIO count, `OH_GPIO_PIN_COUNT` from the
 * variant's `oh_board.h`, is no GPIO, so it writes no bit: not the bit of a
 * GPIO the part does not have, and not, past 31, another GPIO's bit through
 * the shift. Every count here fits the one 32-bit bank these registers are. */
_Static_assert(OH_GPIO_PIN_COUNT <= 32, "the GPIO registers here are one 32-bit bank");

static uint32_t mask_of(uint8_t pin) {
    return pin < OH_GPIO_PIN_COUNT ? (1u << pin) : 0u;
}

/* `pinMode` and `digitalWrite` in `Arduino.h` call these two. */
void oh_pin_mode(uint8_t pin, uint8_t mode) {
    if (mode == OUTPUT) {
        OH_REG(OH_GPIO_ENABLE_W1TS) = mask_of(pin);
    } else {
        OH_REG(OH_GPIO_ENABLE_W1TC) = mask_of(pin);
    }
}

void oh_digital_write(uint8_t pin, uint8_t value) {
    if (value) {
        OH_REG(OH_GPIO_OUT_W1TS) = mask_of(pin);
    } else {
        OH_REG(OH_GPIO_OUT_W1TC) = mask_of(pin);
    }
}

void delay(unsigned long ms) {
    for (; ms; --ms) {
        for (volatile uint32_t spin = OH_DELAY_LOOPS_PER_MS; spin; --spin) {
        }
    }
}
