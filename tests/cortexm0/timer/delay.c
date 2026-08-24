/* OpenHardware - a bare-metal RP2040 blink whose delay is a TIMER, not a loop.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * ## What this proves that ../blink/blink.c does not
 *
 * The blink delays by counting to 64 in a volatile local. That terminates on
 * any emulator, correct timer or not, because nothing outside the core is
 * involved. This one waits on TIMERAWL -- so if the timer does not advance,
 * the loop never exits and the LED never toggles a second time.
 *
 * That distinction is the whole reason a counter had to exist. A register that
 * does not advance is a hang that cannot be made loud: the address is
 * modelled, the read answers, and the answer is simply always the same.
 *
 * The wait is the one pico-sdk's timer_busy_wait_us_32() performs:
 *
 *     while (timer->timerawl - start < delay_us) { tight_loop_contents(); }
 *
 * Unsigned subtraction, so it stays correct across the 32-bit wrap.
 */

#define RESETS          0x4000c000u
#define RESETS_RESET    (RESETS + 0x00u)
#define RESETS_DONE     (RESETS + 0x08u)
#define ALIAS_CLR       0x3000u

#define RESET_IO_BANK0   (1u << 5)
#define RESET_PADS_BANK0 (1u << 8)

#define SIO             0xd0000000u
#define GPIO_OUT_XOR    (SIO + 0x1cu)
#define GPIO_OE_SET     (SIO + 0x24u)

#define TIMER           0x40054000u
#define TIMERAWL        (TIMER + 0x28u)

#define LED             25u

/* Emulated microseconds. Small enough that a test can watch several toggles,
 * large enough that it cannot be satisfied by a handful of instructions. */
#define DELAY_US        200u

#define REG(a) (*(volatile unsigned int *)(a))

static void busy_wait_us(unsigned int us) {
    unsigned int start = REG(TIMERAWL);
    while (REG(TIMERAWL) - start < us) {
    }
}

void _start(void) {
    REG(RESETS_RESET + ALIAS_CLR) = RESET_IO_BANK0 | RESET_PADS_BANK0;
    while ((REG(RESETS_DONE) & (RESET_IO_BANK0 | RESET_PADS_BANK0))
           != (RESET_IO_BANK0 | RESET_PADS_BANK0)) {
    }

    REG(GPIO_OE_SET) = 1u << LED;

    for (;;) {
        REG(GPIO_OUT_XOR) = 1u << LED;
        busy_wait_us(DELAY_US);
    }
}
