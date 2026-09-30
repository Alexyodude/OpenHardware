/* OpenHardware - a bare-metal RP2040 blink on a pin a board's own variant names.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * tests/cortexm0/blink/blink.c, the RP2040's own evidence, with one change:
 * the pin. That one toggles GP25, the Pico's LED. This one toggles WATCHED,
 * a name given on the command line (-DWATCHED=MOSI), which is defined by
 * the one header included here: the pins_arduino.h of the board's own
 * arduino-pico variant, found through -I on that variant's directory. So
 * a build for one board against another board's variant toggles the other
 * board's pin, and nothing in this file or in its build numbers a GPIO
 * (rules/board-claims.md s11).
 *
 * No pico-sdk, no Arduino core, no boot ROM, for the reason blink.c gives.
 * stdint.h comes first because a sketch's Arduino.h includes it before the
 * variant, and a variant may rely on that: seeed_xiao_rp2040's declares
 * uint8_t constants and includes nothing.
 */

#include <stdint.h>
#include <pins_arduino.h>

#define RESETS          0x4000c000u
#define RESETS_RESET    (RESETS + 0x00u)
#define RESETS_DONE     (RESETS + 0x08u)
#define ALIAS_CLR       0x3000u

#define RESET_IO_BANK0  (1u << 5)
#define RESET_PADS_BANK0 (1u << 8)

#define SIO             0xd0000000u
#define GPIO_OUT_XOR    (SIO + 0x1cu)
#define GPIO_OE_SET     (SIO + 0x24u)

#define REG(a) (*(volatile unsigned int *)(a))

void _start(void) {
    REG(RESETS_RESET + ALIAS_CLR) = RESET_IO_BANK0 | RESET_PADS_BANK0;
    while ((REG(RESETS_DONE) & (RESET_IO_BANK0 | RESET_PADS_BANK0))
           != (RESET_IO_BANK0 | RESET_PADS_BANK0)) {
    }

    REG(GPIO_OE_SET) = 1u << WATCHED;

    for (;;) {
        REG(GPIO_OUT_XOR) = 1u << WATCHED;
        for (volatile int i = 0; i < 64; i++) {
        }
    }
}
