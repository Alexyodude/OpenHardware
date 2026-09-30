/* OpenHardware - a bare-metal RP2040 blink on a pin a board's own variant names.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * tests/cortexm0/blink/blink.c, the RP2040's own evidence, with two changes.
 *
 * The pin. That one toggles GP25, the Pico's LED. This one toggles WATCHED,
 * a name given on the command line (-DWATCHED=MISO) and numbered by the
 * board's own arduino-pico variant, reached through the one board header
 * included here: its pins_arduino.h, found through -I on that variant's
 * directory. The name may be declared there or in the generic/common.h that
 * file includes -- MISO is common.h's, set to the variant's PIN_SPI0_MISO --
 * and either way the number is the variant's. So a build for one board
 * against another board's variant toggles the other board's pin, and
 * nothing in this file or in its build numbers a GPIO
 * (rules/board-claims.md s11).
 *
 * And it selects SIO on that pin's pad first, as silicon requires: RP2040
 * Datasheet build-version 3184e62, Table 280 (PDF p.239), "The SIO
 * function (F5) must be selected for the processors to drive a GPIO"; the
 * select is FUNCSEL, bits 4:0 of GPIO<n>_CTRL, at IO_BANK0 0x40014000 plus
 * 0x004 + 8n (s2.19.6.1, PDF p.245; Table 285, PDF pp. 249-250).
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

#define IO_BANK0        0x40014000u
#define GPIO_CTRL(n)    (IO_BANK0 + 0x004u + 8u * (n))
#define FUNCSEL_SIO     5u

#define SIO             0xd0000000u
#define GPIO_OUT_XOR    (SIO + 0x1cu)
#define GPIO_OE_SET     (SIO + 0x24u)

#define REG(a) (*(volatile unsigned int *)(a))

void _start(void) {
    REG(RESETS_RESET + ALIAS_CLR) = RESET_IO_BANK0 | RESET_PADS_BANK0;
    while ((REG(RESETS_DONE) & (RESET_IO_BANK0 | RESET_PADS_BANK0))
           != (RESET_IO_BANK0 | RESET_PADS_BANK0)) {
    }

    REG(GPIO_CTRL(WATCHED)) = FUNCSEL_SIO;
    REG(GPIO_OE_SET) = 1u << WATCHED;

    for (;;) {
        REG(GPIO_OUT_XOR) = 1u << WATCHED;
        for (volatile int i = 0; i < 64; i++) {
        }
    }
}
