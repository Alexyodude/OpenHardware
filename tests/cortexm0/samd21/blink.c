/* OpenHardware - a bare-metal SAMD21 blink, for proving a second board works.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * No Arduino core, no ASF, no bootloader. The sibling under `../blink/` says
 * why at length for the RP2040; the reason is the same here and one reason
 * shorter, because the SAMD21 has no unshippable mask ROM to avoid.
 *
 * Toggles PA17, which is the XIAO SAMD21's user LED -- Seeed's own variant
 * table maps LED_BUILTIN to pin 13 and pin 13 to { PORTA, 17 }.
 *
 * ## Why there is no unreset dance here
 *
 * The RP2040 blink opens by clearing IO_BANK0 and PADS_BANK0 in RESETS and
 * spinning on RESET_DONE, because on that part every peripheral comes up held
 * in reset. The SAMD21 does not work that way: PM->APBBMASK resets to
 * 0x0000007F with the PORT bit (bit 3) already set, so PORT is clocked before
 * the first instruction runs. Writing DIRSET straight away is correct, not a
 * shortcut -- and it is why webui/boards/samd21.py models no PM at all.
 */

#define PORT            0x41004400u
#define PORT_DIRSET     (PORT + 0x08u)
#define PORT_OUTTGL     (PORT + 0x1cu)

#define LED             17u   /* PA17 */

#define REG(a) (*(volatile unsigned int *)(a))

void _start(void) {
    /* Drive PA17: one write, no clock gating and no reset release first. */
    REG(PORT_DIRSET) = 1u << LED;

    for (;;) {
        REG(PORT_OUTTGL) = 1u << LED;
        for (volatile int i = 0; i < 64; i++) {
        }
    }
}
