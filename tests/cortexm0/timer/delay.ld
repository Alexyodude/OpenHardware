/* OpenHardware - link a bare-metal timer delay into RP2040 flash.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * At 0x10000100, not 0x10000000: the first 256 bytes of flash are boot2, the
 * XIP setup blob, and the emulator starts at the vector table that follows it.
 *
 * Identical to ../blink/blink.ld, and duplicated rather than shared. Two
 * fixtures linking through one script would mean a change made for one
 * silently relinking the other, and a linker script is six lines.
 */
MEMORY {
  FLASH (rx) : ORIGIN = 0x10000100, LENGTH = 2M - 0x100
  RAM  (rwx) : ORIGIN = 0x20000000, LENGTH = 264K
}
ENTRY(_start)
SECTIONS {
  .vectors : {
    LONG(0x20042000);          /* initial stack pointer, top of SRAM */
    LONG(_start + 1);          /* reset vector, Thumb bit set */
  } > FLASH
  .text : { *(.text*) *(.rodata*) } > FLASH
  .data : { *(.data*) } > RAM
  .bss  : { *(.bss*) *(COMMON) } > RAM
}
