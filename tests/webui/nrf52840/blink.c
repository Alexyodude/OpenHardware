/* OpenHardware - a bare-metal nRF52840 blink, the first Cortex-M4 image run here.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `tests/cortexm0/m4/probe.c` is read and never run. This one is run: it is the
 * image `tests/webui/test_nrf52840_board.py` watches blink, and the image
 * `tools/m4_oracle.py` runs in Unicorn and icicle in lockstep to produce the
 * trace the core is held to instruction by instruction.
 *
 * No nRF5 SDK, no Zephyr, no bootloader, for the reason `tests/cortexm0/samd21/blink.c`
 * gives: everything an SDK does before `main` is something this would then
 * have to model, and none of it is what is under test.
 *
 * ## The three LEDs, and why it is all three
 *
 * A XIAO nRF52840 has one RGB LED on three pins of port 0 -- red P0.26, green
 * P0.30, blue P0.06, from Seeed's own variant file -- and **each is wired
 * active low**: the pin sinks the LED's current, so clearing the bit lights
 * it. A blink of one pin would be compiled to a handful of narrow encodings
 * and a `mov.w`. Walking a table of three, with the delay a function call,
 * gets the compiler to reach for the wide loads, the `ldr.w` with a shifted
 * index and the `bl`, so the lockstep trace covers more than the delay loop.
 *
 * ## PIN_CNF rather than DIRSET
 *
 * Nordic's own HAL configures an output by writing `PIN_CNF[n]` -- DIR in bit
 * 0, INPUT in bit 1 -- not by writing `DIRSET`, and the register is the same
 * bit seen twice: the product specification (nRF52840 PS v1.7, 6.9.2) says
 * DIR "is the same as" PIN_CNF[n].DIR. So this writes PIN_CNF the way vendor
 * code does, and the board model has to make DIR follow it.
 *
 * Compiled `-mcpu=cortex-m4 -mthumb -mfloat-abi=soft -Os`. Soft float for the
 * reason `tests/cortexm0/m4/probe.c` gives.
 */

#define P0              0x50000000u
#define P0_OUTSET       (P0 + 0x508u)
#define P0_OUTCLR       (P0 + 0x50cu)
#define P0_PIN_CNF(n)   (P0 + 0x700u + 4u * (n))

#define REG(a) (*(volatile unsigned int *)(a))

/* DIR = output, INPUT = disconnect: the value Nordic's `nrf_gpio_cfg_output`
 * writes for a push-pull pin with no pull. */
#define CNF_OUTPUT      3u

static const unsigned char leds[3] = {26u, 30u, 6u};

/* Not inlined, so the trace holds a `bl` and a return. */
__attribute__((noinline)) static void wait(unsigned int count) {
    for (volatile unsigned int i = 0; i < count; i++) {
    }
}

void _start(void) {
    for (unsigned int n = 0; n < 3u; n++) {
        REG(P0_PIN_CNF(leds[n])) = CNF_OUTPUT;
        REG(P0_OUTSET) = 1u << leds[n];        /* off: active low */
    }
    for (unsigned int n = 0;; n = n == 2u ? 0u : n + 1u) {
        REG(P0_OUTCLR) = 1u << leds[n];        /* on */
        wait(40u);
        REG(P0_OUTSET) = 1u << leds[n];        /* off */
        wait(40u);
    }
}
