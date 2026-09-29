---
id: OH-181
title: An arduino-pico board's pins are read through common.h, so the KB2040 and every
  RP2040 variant can be a row
status: in-progress
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-181-*
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- tools/board_manifest.py
- tests/rules/test_board_manifest.py
- webui/boards/Adafruit KB2040.json
- tools/board_sources.py
---

Part of OH-174, found by OH-177. The Adafruit KB2040 and the PCBCUPID Glyph Mini RP2040 have registry rows and fetched board files, and no manifest row, because `check()` refuses both before anything is written:

    pins_arduino.h: no D<n> constants among the 21 found     (KB2040)
    pins_arduino.h: no D<n> constants among the 29 found     (Glyph Mini)

OH-177's report says arduino-pico defines its Arduino pin numbers in `variants/generic/common.h`, which each board's `pins_arduino.h` includes, behind `#ifdef __PIN_D<n>` and `#if defined(PICO_RP2040)` style guards, and that tools/import_pindefs.py reads only the board's own `pins_arduino.h`. Verify that against the files at the cited arduino-pico revision before building on it.

Read what an arduino-pico board's pins actually are, including what `common.h` contributes, by evaluating the guards the way the preprocessor would for that board and chip, not by pattern-matching past them. If the honest reader needs the real preprocessor (the compile toolchain is already installed for the compile service), say so and use it rather than approximating one.

This unblocks every RP2040 and RP2350 board in arduino-pico, not only these two, so measure how many of arduino-pico's variants resolve before and after.

The Glyph Mini has two further gaps that are not this ticket's: its nets are named `/GPIO-n`, which is OH-178's kind of source, and tools/import_board.py does not read a whole-board `.kicad_pcb`. Say which of the two boards this ticket gets to a row, and why the other stops where it does.

Done when the KB2040 is a manifest row with its pins read through `common.h`, a variant whose guard is deliberately inverted is shown to resolve differently or be refused, and the XIAO RP2040 and RP2350 files still regenerate byte-identical.
