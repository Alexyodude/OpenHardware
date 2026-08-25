/* OpenHardware - where the Cortex-M4 decode probe is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `_start` first, the same reason `tests/riscv32/c6blink/blink.ld` gives:
 * without a script the linker orders sections however it likes, and a fixture
 * whose bytes move when the compiler feels like it is a fixture that cannot be
 * committed and compared.
 *
 * **This one is never entered**, so the ordering is about reproducibility
 * rather than about correctness -- nothing executes a Cortex-M4 image here.
 * See `probe.c`.
 *
 * 0x00010000 is nRF52840 flash, which starts at zero; the offset leaves room
 * for the vector table a real image would put there and keeps every branch
 * target in the listing five hex digits wide, so a target that lost its base
 * would be obvious rather than plausible.
 */

MEMORY {
  flash (rx) : ORIGIN = 0x00010000, LENGTH = 512K
  ram   (rw) : ORIGIN = 0x20000000, LENGTH = 128K
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))
    *(.text .text.*)
    *(.rodata .rodata.*)
  } > flash

  .bss (NOLOAD) : {
    *(.bss .bss.* COMMON)
  } > ram
}
