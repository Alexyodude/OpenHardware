/* OpenHardware - a bare-metal RP2040 blink, for proving a board runs.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * No pico-sdk, no Arduino core, no boot ROM. Those bring a runtime that calls
 * into the RP2040 boot ROM within the first quarter-million instructions, and
 * that ROM is not redistributable -- see webui/boards/rp2040.py.
 *
 * What is left is the part that actually proves a board works: unreset the IO
 * block, enable an output, and toggle it. If the emulated pin changes state,
 * the core executed real compiled ARM code against real peripheral registers.
 */

#define RESETS          0x4000c000u
#define RESETS_RESET    (RESETS + 0x00u)
#define RESETS_DONE     (RESETS + 0x08u)
#define ALIAS_CLR       0x3000u

#define RESET_IO_BANK0  (1u << 5)
#define RESET_PADS_BANK0 (1u << 8)

#define SIO             0xd0000000u
#define GPIO_OUT_XOR    (SIO + 0x1cu)
#define GPIO_OE_SET     (SIO + 0x24u)

#define LED             25u

#define REG(a) (*(volatile unsigned int *)(a))

void _start(void) {
    /* Take IO_BANK0 and PADS_BANK0 out of reset through the atomic CLR alias,
     * then wait for RESET_DONE -- the mirror that makes this loop terminate. */
    REG(RESETS_RESET + ALIAS_CLR) = RESET_IO_BANK0 | RESET_PADS_BANK0;
    while ((REG(RESETS_DONE) & (RESET_IO_BANK0 | RESET_PADS_BANK0))
           != (RESET_IO_BANK0 | RESET_PADS_BANK0)) {
    }

    REG(GPIO_OE_SET) = 1u << LED;

    for (;;) {
        REG(GPIO_OUT_XOR) = 1u << LED;
        for (volatile int i = 0; i < 64; i++) {
        }
    }
}
