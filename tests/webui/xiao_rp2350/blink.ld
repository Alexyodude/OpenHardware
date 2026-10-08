/* OpenHardware - where a bare-metal RP2350 blink is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The same job `tests/riscv32/c6blink/blink.ld` does, for the same reason --
 * `_start` has to be the first byte of the image, because a raw `.bin`
 * carries no entry point and `core/riscv32/machine.py` enters at the lowest
 * address an image loads at -- and one more: the IMAGE_DEF block has to be
 * inside the first 4 kB (RP2350 Datasheet 80d627281ed5, section 5.9.5,
 * PDF p.390), so it follows the code rather than the end of a large image.
 *
 * 0x10000000 is XIP_BASE, pico-sdk 2.3.0's
 * src/rp2350/hardware_regs/include/hardware/regs/addressmap.h:24. 2M is the
 * XIAO RP2350's flash, `build.flash_total=2097152` at arduino-pico 33201a6
 * boards.txt:36689 -- the window `webui/boards/rp2350.py` maps.
 */

MEMORY {
  flash (rx) : ORIGIN = 0x10000000, LENGTH = 2M
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))    /* _start, and it must come first */
    *(.text .text.*)
    *(.rodata .rodata.*)
    . = ALIGN(4);
    KEEP(*(.image_def))     /* within the first 4 kB, after the code */
  } > flash
}
