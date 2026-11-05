/* OpenHardware - where the Cortex-M4 decode probe is linked.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * `.text.start` first, the same reason `tests/riscv32/c6blink/blink.ld`
 * gives: without a script the linker orders sections however it likes, and a
 * fixture whose bytes move when the compiler feels like it is a fixture that
 * cannot be committed and compared.
 *
 * `_start` itself is NOT first: without `-ffunction-sections` GCC puts it in
 * plain `.text`, after the functions it calls. That did not matter while the
 * image was only disassembled; since OH-64 traces it from `_start`,
 * `tools/m4_oracle.py` pins the address as `PROBE_ENTRY` and checks a `push`
 * is there, so a rebuild that moved it fails loudly.
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
