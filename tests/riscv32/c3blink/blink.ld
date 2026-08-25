/* OpenHardware - where a bare-metal ESP32-C3 blink is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The same job `tests/cortexm0/blink/blink.ld` does for the Arm fixtures, and
 * it exists for one reason: **`_start` has to be the first byte of the image.**
 *
 * `core/riscv32/machine.py` enters a raw `.bin` at the lowest address it loads
 * at, because a raw binary carries no entry point to read. Without a script the
 * linker placed `main` first and `_start` after it, so the stack setup was
 * simply skipped and the first push faulted -- an image that looks right,
 * links cleanly, and runs the wrong instruction first.
 *
 * 0x42000000 is SOC_IROM_LOW from Espressif's soc.h:219, the flash execute
 * window, and is what `webui/boards/esp32c3.py` maps as its executable region.
 */

MEMORY {
  irom (rx) : ORIGIN = 0x42000000, LENGTH = 8M
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))    /* _start, and it must come first */
    *(.text .text.*)
    *(.rodata .rodata.*)
  } > irom
}
