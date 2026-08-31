/* OpenHardware - where a sketch for the XIAO ESP32-C3 is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The blink fixtures' script, grown the two sections a real sketch has and
 * a bare `_start` cannot set up:
 *
 *   `.data` links INTO the flash window, load address and run address one
 *   and the same, because there is no crt0 to copy it out -- and this
 *   model's regions accept stores wherever they are, a stated liberty
 *   (`core/riscv32/cpu.h`'s `add_region` gives every region storage; real
 *   XIP flash would fault the first write). An initialized global works
 *   because of that liberty, and this comment is where it stops being
 *   quiet.
 *
 *   `.bss` lands NOLOAD in DRAM, which the model fills with zero -- the
 *   flash region's own fill is 0xFF (`FLASH_ERASED`), which is why bss
 *   cannot live there.
 *
 * 0x42000000 / 8M is the C3's flash execute window and 0x3FC80000 / 384K
 * its DRAM, both as `webui/boards/esp32c3.py` maps them from ESP-IDF's
 * soc.h.
 */

MEMORY {
  irom (rwx) : ORIGIN = 0x42000000, LENGTH = 8M
  dram (rw)  : ORIGIN = 0x3FC80000, LENGTH = 384K
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))    /* _start, and it must come first */
    *(.text .text.*)
    *(.rodata .rodata.*)
    *(.srodata .srodata.*)
    *(.data .data.*)
    *(.sdata .sdata.*)
  } > irom

  .bss (NOLOAD) : {
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
  } > dram
}
