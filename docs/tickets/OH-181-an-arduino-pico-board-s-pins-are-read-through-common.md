---
id: OH-181
title: An arduino-pico board's pins are read through common.h, so the KB2040 and every
  RP2040 variant can be a row
status: in-review
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
- tests/webui/test_pin_view.py
- README.md
---

Part of OH-174, found by OH-177. The Adafruit KB2040 and the PCBCUPID Glyph Mini RP2040 have registry rows and fetched board files, and no manifest row, because `check()` refuses both before anything is written:

    pins_arduino.h: no D<n> constants among the 21 found     (KB2040)
    pins_arduino.h: no D<n> constants among the 29 found     (Glyph Mini)

OH-177's report says arduino-pico defines its Arduino pin numbers in `variants/generic/common.h`, which each board's `pins_arduino.h` includes, behind `#ifdef __PIN_D<n>` and `#if defined(PICO_RP2040)` style guards, and that tools/import_pindefs.py reads only the board's own `pins_arduino.h`. Verify that against the files at the cited arduino-pico revision before building on it.

Read what an arduino-pico board's pins actually are, including what `common.h` contributes, by evaluating the guards the way the preprocessor would for that board and chip, not by pattern-matching past them. If the honest reader needs the real preprocessor (the compile toolchain is already installed for the compile service), say so and use it rather than approximating one.

This unblocks every RP2040 and RP2350 board in arduino-pico, not only these two, so measure how many of arduino-pico's variants resolve before and after.

The Glyph Mini has two further gaps that are not this ticket's: its nets are named `/GPIO-n`, which is OH-178's kind of source, and tools/import_board.py does not read a whole-board `.kicad_pcb`. Say which of the two boards this ticket gets to a row, and why the other stops where it does.

Done when the KB2040 is a manifest row with its pins read through `common.h`, a variant whose guard is deliberately inverted is shown to resolve differently or be refused, and the XIAO RP2040 and RP2350 files still regenerate byte-identical.

**Note 2026-09-30:** 2026-09-30: in review. Commits 7586239 (reader), 620bf28 (KB2040 row), ed84f4b (fix found by the all-variants comparison).
VERIFIED FIRST: at arduino-pico 33201a6, variants/adafruit_kb2040/pins_arduino.h numbers no D<n> or A<n> and ends `#include "../generic/common.h"`; common.h declares D0-D29 behind `#ifdef __PIN_D<n>` (default: the GPIO of the same number) and A0-A3 behind `#if defined(PICO_RP2040) || (defined(PICO_RP2350) && PICO_RP2350A)`, with an RP2350B branch (D30-D47, A0-A7) after it. PICO_RP2040 and PICO_RP2350 are not in boards.txt: they come from lib/<build.chip>/platform_def.txt, a response file platform.txt's recipe passes.
READER (tools/import_pindefs.py): the preprocessor answers. `pico_build` expands platform.txt's recipe.cpp.o.pattern with the one boards.txt board that builds the variant (every menu at its first option) and keeps what can change a macro (-D -U -m -f -std= -O and @response files). lib/ is outside Package.sparse, so response files are read from the checkout's commit with `git show`. `pico_constants` runs arm-none-eabi-g++ (PlatformIO's toolchain-gccarmnoneeabi, under webui/compile.py's PACKAGES) with `-E -P -dU` and `-E -dM` on `#include <pins_arduino.h>` with the variant directory on the include path. It refuses: a variant whose conditionals consult a macro the recipe builds from an arduino-cli property (-DARDUINO={runtime.ide.version}, -DARDUINO_ARCH_{build.arch}), which `-dU` lists; a D<n> or A<n> whose initialiser is not an integer. FALLBACK (no compiler installed, as on CI): a file whose only directives are #define and #pragma is read by hand; any #if/#include/#undef is refused, naming the install command. `--pico-variants` prints the survey.
MEASURED (`python tools/import_pindefs.py --pico-variants`, 151 variants): the old text reading gave 31 variants a D<n> and 32 an A<n>, 2 of them wrongly (pimoroni_plasma2040 and pimoroni_plasma2350 number D<n> only under `#if 0`). The preprocessor gives 135 a D<n> and 138 an A<n>, refuses 12, and is wrong on none; the 12 include a header outside the checkout (cyw43_wrappers.h, or Arduino.h via nina_pins.h). By hand: 16 and 17, refuses 134, and gives no answer the preprocessor does not (OH_SLOW=1 test_every_variant_the_fallback_reads_it_reads_as_the_preprocessor_does). That test failed first: challenger_2350_nbiot's `A5 = PIN_SPI0_SS` went missing by hand, and refusing it showed the preprocessor had also been dropping A5 on two sibling boards, where `(PIN_SPI0_SS)` becomes `((17u))`. ed84f4b fixes both.
INVERTED GUARD: with common.h's chip guard inverted in a copy, the KB2040 has no A0 and the row's A0 opt-in is refused. With `#ifdef __PIN_D0` inverted, D0 is `__PIN_D0` and is refused. The unchanged copy reads A0 = GPIO26 (the control).
XIAO BYTE-IDENTITY: the XIAO RP2040/RP2350 rows use the new reader. `--write-boards` and `--write-headers` leave every board file and the rp2040.py HEADER unchanged, with the row in and without it. test_the_xiao_variants_read_the_same_by_hand_and_preprocessed holds the two readers equal on both variants, so CI's fallback writes the same files.
KB2040 ROW (tools/board_manifest.py; the .sch is now fetched, tools/board_sources.py): JP1 and JP2 are two 13-pin castellated rows, one pin per castellation through the schematic's connects, 26 pads. It has an RP2040 QFN-56 pin table (RP2040 datasheet build 3184e62, pp. 613-615, Tables 615 and 617-621, PDF sha256 pinned). The new PinTable.footprint_pads reads the footprint's central pad P$1 as the page's 57 (GND); a test holds that P$1 is the one unnumbered pad, at the centre of pads 1-56, and that GND is refused without it. Result: 18 of 26 resolve, 0 disputed. Every D<n> and A<n> the variant gives through common.h agrees with the pad its copper reaches. SCLK resolves from the trace alone; its second statement is the schematic's IC2 pin GPIO18, which the second-statement test now also reads. D+ and D- trace through R3/R4 (27) to USB_DP/USB_DM, !RESET to RUN, 3.3V/GND to supply pads, and RAW to no chip pad; RAW is in SUPPLY_LABELS. It claims no run: inventory shows RP2040:no. The KB2040's D0-D10 are keys of rp2040.py's XIAO table (D0 = GPIO26 there, GPIO0 here), and test_no_row_pad_is_read_through_its_chips_module_table now checks api.pad_view's join rather than disjoint labels.
GLYPH MINI: not a row. Its variant now resolves (D0-D29 through common.h), but its pads are labelled by net (/GPIO-n), which no variant constant matches, and Row requires an EAGLE schematic for connects. A KiCad manifest row would need: `schematic` optional for a .kicad_pcb, whose pads already carry number and net (OH-182 merges one pin's pads without a schematic); and pins either from the RP2040 variant labels, which its pads do not carry, or from an OH-178-style trace of a .kicad_pcb to an RP2040 datasheet table (read_eagle_traced reads EAGLE only; RP2040_QFN56 exists now).
RED ON PURPOSE: each mutant restored. Reader: no -D kept (4 red); fallback reads past #if/#include (3); a non-integer D<n> left out (2); consulted macros unchecked (1); menus at the last option (1); footprint_pads unmapped (1); two boards per variant allowed (1); A<n> not refused (1); one paren level only (1); no balance check (1). Manifest: no schematic statement (1); variant names only opt-ins (1); no footprint_pads (1); pad_view joining a row through the module table (red on the KB2040). Pin view: rp2040.py given GPIO words (2 red); the KB2040 given a blink (1).
SUITE at 620bf28: 3 failed, 2306 passed, 33 skipped. Two are the OCP pair (test_import_3d_model, No module named 'OCP'), which is the baseline. The third is the known red one: tests/webui/test_compile.py::test_each_rows_verdict_is_the_compilers_own raises KeyError 'RP2040', because it indexes RECIPES by every row's chip. That file is lent to OH-185, whose rebase loops it over the rows whose chip has a recipe. After ed84f4b, test_import_pindefs, test_board_manifest and test_pin_view: 188 passed, 1 skipped (the slow one), and the slow one passes with OH_SLOW=1. All CLAUDE.md checkers OK.
