/* OpenHardware - a bare-metal ATmega328P blink, for proving an AVR core works.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * No Arduino core and no avr-libc startup, for the reason the Arm fixtures
 * give: a vendor runtime brings code this project would then have to model
 * before the thing under test ever runs.
 *
 * Addresses from the toolchain's own iom328p.h, which is Microchip's:
 *
 *     #define DDRB  _SFR_IO8(0x04)
 *     #define PORTB _SFR_IO8(0x05)
 *
 * `_SFR_IO8(x)` is `x + 0x20` in the data space, so DDRB is 0x24 and PORTB is
 * 0x25. Writing them as literals rather than including <avr/io.h> keeps the
 * fixture free of the toolchain's headers, exactly as tests/cortexm0/blink
 * does.
 *
 * PB5 is the Uno's LED -- digital pin 13.
 */

#define DDRB  (*(volatile unsigned char *)0x24)
#define PORTB (*(volatile unsigned char *)0x25)

#define LED 5

int main(void) {
    DDRB |= (1 << LED);

    for (;;) {
        PORTB ^= (1 << LED);
        for (volatile unsigned int i = 0; i < 100; i++) {
        }
    }
}
