/* OpenHardware - where a sketch for the XIAO ESP32-C5 is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The section layout is the C3's, and `variants/xiao_esp32c3/link.ld` is
 * where its reasons live -- why `.data` links INTO the flash window with
 * no crt0 to copy it (a stated liberty of this model's regions), why
 * `.bss` is NOLOAD in RAM, and what `--gc-sections` did to `.init_array`
 * before OH-151 KEPT it. None of that is per-part, so it is written once.
 *
 * What IS per-part is the two regions, and they are this part's own, as
 * `webui/boards/esp32c5.py` maps them from ESP-IDF's soc.h:
 *
 *   0x42000000 / 32M  the flash execute window, SOC_IROM_LOW..HIGH
 *   0x40800000 / 384K HP SRAM, SOC_DRAM_LOW..HIGH -- ONE window, where the
 *                     C3 has a separate DRAM alias; there is no second view
 *                     of this RAM to choose between.
 *
 * `tests/webui/test_compile.py` asserts both origins against the
 * description, so the script cannot quietly keep a neighbour's numbers.
 */

MEMORY {
  irom (rwx) : ORIGIN = 0x42000000, LENGTH = 32M
  sram (rwx) : ORIGIN = 0x40800000, LENGTH = 384K
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

  /* KEPT, and named, for the reasons the C3's script measured (OH-151). */
  .init_array : ALIGN(4) {
    PROVIDE_HIDDEN(__init_array_start = .);
    KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*)))
    KEEP(*(.init_array))
    PROVIDE_HIDDEN(__init_array_end = .);
  } > irom

  .bss (NOLOAD) : {
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
  } > sram
}
