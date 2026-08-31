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
 * Two of the three things a real crt0 also does are deliberately absent,
 * and the linker script is what makes that sound: `.data` links INTO the
 * flash window, which this model's regions accept stores to (a stated
 * liberty; real XIP flash would not), so it needs no copy; and `.bss` lands
 * NOLOAD in a RAM region the model fills with zero, so it needs no zeroing.
 *
 * **The third is here, because no liberty of the model can supply it.** A
 * global C++ constructor is code, and running code is the one thing a
 * memory region cannot do on its behalf -- so `oh_init_array` below walks
 * the table the linker script keeps. OH-151 is what measured the cost of
 * its absence: a sketch whose global had a constructor built, reported ok,
 * and never ran it.
 */

#include "Arduino.h"

/* The bounds of the constructor table, as `link.ld` PROVIDEs them.
 *
 * Declared as arrays rather than as pointers so that `end - start` counts
 * entries and not bytes, which is the shape every crt0 uses and the one
 * that cannot be got wrong by four.
 *
 * They are extern to a section that may be empty, and that is the normal
 * case: with no global constructors the two symbols are equal, the loop
 * body never runs, and nothing is linked in. */
extern void (*__init_array_start[])(void);
extern void (*__init_array_end[])(void);

/* What `__libc_init_array` would do, written out because this image links
 * `-nostdlib` and there is no libc to take it from. */
static void oh_init_array(void) {
    for (void (**entry)(void) = __init_array_start;
         entry != __init_array_end; ++entry) {
        (*entry)();
    }
}

/* setup() once, loop() forever: the Arduino contract, and small enough to
 * state rather than import.
 *
 * **Not static**, which is the whole reason it is reachable: `_start`
 * gets here with a `tail` to the symbol by name, and a static function
 * may be renamed or inlined out from under one. */
void oh_run(void) {
    /* Before setup(), which is where the Arduino contract puts it and where
     * a sketch expects its globals to already be built. */
    oh_init_array();
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

