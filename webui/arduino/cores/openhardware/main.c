/* OpenHardware - the whole of what a crt0 does on a described board.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The same `_start` the blink fixtures use, for the same reasons their
 * comments give: `core/riscv32/machine.py` enters a raw image at its lowest
 * loaded address, so `_start` must be the first byte (the linker script
 * keeps it there), and an RV32 part does not load its stack pointer from
 * anywhere, so the first instruction sets it.
 *
 * What a real crt0 also does -- copy `.data` from load address to RAM, zero
 * `.bss` -- is deliberately absent, and the linker script is what makes
 * that sound: `.data` links INTO the flash window, which this model's
 * regions accept stores to (a stated liberty; real XIP flash would not),
 * and `.bss` lands NOLOAD in a RAM region the model fills with zero.
 */

#include "Arduino.h"

/* setup() once, loop() forever: the Arduino contract, and small enough to
 * state rather than import.
 *
 * **Not static**, which is the whole reason it is reachable: `_start`
 * gets here with a `tail` to the symbol by name, and a static function
 * may be renamed or inlined out from under one. */
void oh_run(void) {
    setup();
    for (;;) {
        loop();
    }
}

__attribute__((naked, section(".text.start"), used)) void _start(void) {
#if defined(__riscv)
    __asm__ volatile(
        "li sp, %0\n"
        "tail oh_run\n"
        :: "i"(OH_STACK_TOP)
    );
#else
#error "no _start for this architecture yet; add its branch when its recipe arrives"
#endif
}

