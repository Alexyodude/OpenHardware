/* OpenHardware - link a bare-metal blink into SAMD21 flash.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * At 0x00000000, and that is the interesting line in this file. The RP2040
 * sibling links at 0x10000100 -- an XIP window, plus 256 bytes of boot2 in
 * front of the vector table. A SAMD21 has neither: flash is the reset address
 * space, so the vector table a Cortex-M0+ reads at power-on is simply the
 * first eight bytes of the image.
 */
MEMORY {
  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 256K
  RAM  (rwx) : ORIGIN = 0x20000000, LENGTH = 32K
}
ENTRY(_start)
SECTIONS {
  .vectors : {
    LONG(0x20008000);          /* initial stack pointer, top of 32K SRAM */
    LONG(_start + 1);          /* reset vector, Thumb bit set */
  } > FLASH
  .text : { *(.text*) *(.rodata*) } > FLASH
  .data : { *(.data*) } > RAM
  .bss  : { *(.bss*) *(COMMON) } > RAM
}
