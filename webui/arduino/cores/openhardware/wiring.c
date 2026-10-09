/* OpenHardware - pinMode, digitalWrite, millis, micros and delay against
 * the modelled GPIO and SYSTIMER.
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

/* One read of SYSTIMER unit 0, the way ESP-IDF's own
 * `systimer_hal_get_counter_value` reads it (`components/hal/systimer_hal.c:46-62`
 * at v5.5): ask for a copy, wait until the copy is valid, then read its two
 * halves. ESP-IDF reads the low half twice
 * around the high one, because an interrupt may take a new copy between
 * them; nothing here interrupts, so one read of each IS the copy. */
static uint64_t oh_systimer_ticks(void) {
    OH_REG(OH_SYSTIMER_UNIT0_OP) = OH_SYSTIMER_UNIT0_UPDATE;
    while ((OH_REG(OH_SYSTIMER_UNIT0_OP) & OH_SYSTIMER_UNIT0_VALUE_VALID) == 0) {
    }
    const uint32_t high = OH_REG(OH_SYSTIMER_UNIT0_VALUE_HI);
    const uint32_t low = OH_REG(OH_SYSTIMER_UNIT0_VALUE_LO);
    return ((uint64_t)high << 32) | low;
}

/* A shift and not a division: the rate is sixteen, and an image linked
 * `-nostdlib` has no `__udivdi3` to divide 64 bits by anything else. */
unsigned long micros(void) {
    return (unsigned long)(oh_systimer_ticks() / OH_SYSTIMER_TICKS_PER_US);
}

/* Microseconds over a thousand, without the `__udivdi3` this image does
 * not link: split at bit 16 and divide each half with the M extension's
 * 32-bit `divu`. The count is 52 bits, so the microseconds are under 2^48
 * and `upper` fits in 32; `(rest << 16) | lower` is under 1000 * 2^16. The
 * shift of the upper quotient may carry past bit 31, and dropping that is
 * the wrap at 2^32 an `unsigned long millis()` makes anyway. */
unsigned long millis(void) {
    const uint64_t us = oh_systimer_ticks() / OH_SYSTIMER_TICKS_PER_US;
    const uint32_t upper = (uint32_t)(us >> 16);
    const uint32_t lower = (uint32_t)us & 0xFFFFu;
    const uint32_t rest = upper % 1000u;
    return ((upper / 1000u) << 16) + (((rest << 16) | lower) / 1000u);
}

void delay(unsigned long ms) {
    for (; ms; --ms) {
        for (volatile uint32_t spin = OH_DELAY_LOOPS_PER_MS; spin; --spin) {
        }
    }
}
