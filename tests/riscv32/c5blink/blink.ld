/* OpenHardware - where a bare-metal ESP32-C5 blink is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The same job the C3's and C6's scripts do, for the same one reason:
 * **`_start` has to be the first byte of the image**, because
 * `core/riscv32/machine.py` enters a raw `.bin` at the lowest address it
 * loads at, and without a script the linker put `main` first.
 *
 * 0x42000000 is SOC_IROM_LOW,
 * `components/soc/esp32c5/include/soc/soc.h` (ESP-IDF v5.5.0, `8c750b0`),
 * and is what `webui/boards/esp32c5.py` maps as its executable region.
 *
 * LENGTH is 32M, which is the C5's own figure rather than the C6's 16M:
 * `soc.h` writes SOC_IROM_HIGH as 0x44000000 on this part, and
 * `webui/boards/esp32c5.py`'s IROM_SIZE is that same subtraction.
 */

MEMORY {
  irom (rx) : ORIGIN = 0x42000000, LENGTH = 32M
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))    /* _start, and it must come first */
    *(.text .text.*)
    *(.rodata .rodata.*)
  } > irom
}
