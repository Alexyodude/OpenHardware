/* OpenHardware - pinMode, digitalWrite, millis, micros, delay and
 * delayMicroseconds against the modelled GPIO and SYSTIMER.
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
 * `-nostdlib` has no `__udivdi3` to divide 64 bits by anything else. A
 * variant whose rate is not a power of two stops here, by name, rather than
 * at the link with an undefined reference that names neither the rate nor
 * the header that set it. */
_Static_assert(OH_SYSTIMER_TICKS_PER_US != 0 &&
                   (OH_SYSTIMER_TICKS_PER_US & (OH_SYSTIMER_TICKS_PER_US - 1u)) == 0,
               "OH_SYSTIMER_TICKS_PER_US must be a power of two: micros() and millis() "
               "divide a 64-bit count by it, any other divisor calls __udivdi3, and "
               "a -nostdlib image does not link one");

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

/* Returns once `ms` milliseconds of SYSTIMER unit 0 -- `ms` times sixteen
 * thousand ticks -- have passed since the call, read through the same copy
 * millis() reads, so a sketch timing one with the other gets what it asked
 * for. One millisecond at a time and in the count's low 32 bits: the whole
 * wait as one number would need `ms * 16000` in 64 bits, and a
 * millisecond's 16,000 ticks fit a 32-bit difference with room to spare.
 * Unsigned subtraction is then right across the low word's wrap at 2^32
 * ticks and across the counter's own at 2^52, a multiple of it. `start`
 * advances by whole milliseconds rather than being read again, so a poll
 * that lands late does not push the next millisecond later.
 *
 * It returns at the first poll that sees the count there, so it overruns by
 * up to one poll, and a blink built on it can be one poll longer in one
 * period than in the next: the count moves every few instructions, and the
 * poll and the tick fall in and out of step. */
void delay(unsigned long ms) {
    const uint32_t ticks_per_ms = OH_SYSTIMER_TICKS_PER_US * 1000u;
    uint32_t start = (uint32_t)oh_systimer_ticks();
    for (; ms; --ms) {
        while ((uint32_t)oh_systimer_ticks() - start < ticks_per_ms) {
        }
        start += ticks_per_ms;
    }
}

/* Returns once `us` microseconds of SYSTIMER unit 0 -- `us` times
 * `OH_SYSTIMER_TICKS_PER_US` ticks -- have passed since the call, on
 * delay()'s terms: the same copy, the count's low 32 bits, and `start`
 * advanced by what was waited rather than read again. The whole wait as one
 * number passes 32 bits past 2^28 microseconds, so it goes as delay()'s
 * does, a millisecond of ticks at a time, and then the microseconds left
 * over, under a thousand: no piece comes near 32 bits, and the split is the
 * M extension's 32-bit `divu` and `remu`, so nothing calls libgcc. */
void delayMicroseconds(uint32_t us) {
    const uint32_t ticks_per_ms = OH_SYSTIMER_TICKS_PER_US * 1000u;
    const uint32_t rest = (us % 1000u) * OH_SYSTIMER_TICKS_PER_US;
    uint32_t start = (uint32_t)oh_systimer_ticks();
    for (uint32_t ms = us / 1000u; ms; --ms) {
        while ((uint32_t)oh_systimer_ticks() - start < ticks_per_ms) {
        }
        start += ticks_per_ms;
    }
    while ((uint32_t)oh_systimer_ticks() - start < rest) {
    }
}
