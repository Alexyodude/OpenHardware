/* OpenHardware - where a bare-metal ESP32-C6 blink is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The same job `tests/riscv32/c3blink/blink.ld` does, and it exists for the
 * same one reason: **`_start` has to be the first byte of the image.**
 *
 * `core/riscv32/machine.py` enters a raw `.bin` at the lowest address it loads
 * at, because a raw binary carries no entry point to read. Without a script the
 * linker placed `main` first and `_start` after it, so the stack setup was
 * simply skipped and the first push faulted -- an image that looks right,
 * links cleanly, and runs the wrong instruction first.
 *
 * 0x42000000 is SOC_IROM_LOW, `components/soc/esp32c6/include/soc/soc.h:154`,
 * and is what `webui/boards/esp32c6.py` maps as its executable region. It is
 * the one address a C3 and a C6 agree on.
 *
 * LENGTH is 16M rather than the C3's 8M, and that number is a *build option*
 * on this part rather than a constant: `soc.h:155` writes the top as
 * `SOC_IROM_LOW + (SOC_MMU_PAGE_SIZE << 8)`, and `SOC_MMU_PAGE_SIZE_CONFIGURABLE`
 * is 1 in `soc_caps.h:298`. 16M is that formula at the header's own default
 * page size of 0x10000 (`ext_mem_defs.h:19`), which is the same figure
 * `webui/boards/esp32c6.py` maps and says the same thing about.
 */

MEMORY {
  irom (rx) : ORIGIN = 0x42000000, LENGTH = 16M
}

ENTRY(_start)

SECTIONS {
  .text : {
    KEEP(*(.text.start))    /* _start, and it must come first */
    *(.text .text.*)
    *(.rodata .rodata.*)
  } > irom
}
