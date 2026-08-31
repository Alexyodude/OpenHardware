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
 *   `.init_array` is KEPT, which is the one thing above that no liberty of
 *   the model can supply: a global C++ constructor is code, and code that
 *   nothing calls does not run. See its section below for what was
 *   measured before it was placed.
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

  /* Every global constructor, in the order the linker laid them down.
   *
   * **KEEP is doing the work here and it is not belt and braces.** Before
   * OH-151 this section was an orphan and `--gc-sections` COLLECTED it: the
   * map file showed the four bytes the sketch object contributed, and
   * `readelf -S` on the linked ELF showed no `.init_array` at all, because
   * nothing referenced `__init_array_start` and nothing kept the section.
   * The constructor was not merely never called -- it was not in the image.
   * A sketch built, reported ok at 148 bytes, and silently skipped it.
   *
   * Naming the section here also gives it a stated home. As an orphan its
   * placement was ld's choice, and had that choice ever fallen after `.bss`
   * the flat image would have spanned the ~37 MB between the two regions.
   *
   * `SORT_BY_INIT_PRIORITY` is what `__attribute__((init_priority(n)))`
   * means; it costs nothing when nobody writes one.
   *
   * There is deliberately no `.fini_array`, and measuring showed there is
   * nothing for one to hold. On a sketch whose global HAS a destructor,
   * `readelf -S` of the sketch object lists `.text`, `.text.setup`,
   * `.text.loop`, `.text.startup._GLOBAL__sub_I_*` and `.init_array` -- no
   * `.fini_array`, and no destructor body anywhere -- while `nm -u` on the
   * same object names only `pinMode` and `digitalWrite`, so there is no
   * `__cxa_atexit` or `atexit` registration either. The compiler drops it
   * before the linker can see it, so nothing here is being discarded
   * quietly. (This paragraph first predicted the opposite -- an unresolved
   * `__cxa_atexit` and a loud link failure -- and it was written before the
   * measurement rather than after. It was wrong.)
   *
   * A global destructor never running is not this board being unusual: it
   * is what every Arduino target does on real silicon, because `loop()`
   * never returns and `main` never exits. */
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
  } > dram
}
