/* OpenHardware - link a bare-metal blink into nRF52840 flash.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * At 0x00000000, like `tests/cortexm0/samd21/blink.ld` and for the same reason: nRF52840
 * flash is the reset address space, so the vector table a Cortex-M4 reads at
 * power-on is the first eight bytes of the image. Unlike `tests/cortexm0/m4/probe.ld`,
 * which links at 0x10000 because it is never entered, this one is.
 *
 * The stack starts at the top of the part's 256 KB of RAM.
 */
MEMORY {
  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 1024K
  RAM  (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}
ENTRY(_start)
SECTIONS {
  .vectors : {
    LONG(0x20040000);          /* initial stack pointer, top of 256K SRAM */
    LONG(_start + 1);          /* reset vector, Thumb bit set */
  } > FLASH
  .text : { *(.text*) *(.rodata*) } > FLASH
  .data : { *(.data*) } > RAM
  .bss  : { *(.bss*) *(COMMON) } > RAM
}
