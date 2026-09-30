---
id: OH-196
title: 'A manifest RP2040 board runs as itself: the KB2040 and the Glyph Mini'
status: in-progress
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-196-*
- rules/board-claims.md
- webui/boards/catalogue.py
- webui/boards/rp2040.py
- tests/webui/test_pin_view.py
- tests/webui/test_board_catalogue.py
- tests/rules/test_board_claims.py
- tests/webui/test_kb2040_board.py
- tests/webui/test_glyph_mini_rp2040_board.py
- tests/webui/rp2040_rows/**
- tools/check_board_claims.py
- webui/api.py
- tests/cortexm0/test_board_rp2040.py
---

Part of OH-174. The Adafruit KB2040 and the PCBCUPID Glyph Mini RP2040 hold geometry and pins and read `RP2040:no` for runs: rules/board-claims.md §7 gives a manifest board its own run evidence only through a named test that compiles for that board against its own variant, runs the image, and watches a GPIO the variant names through the board's own pad. The ESP32 manifest boards meet that through the page's compile service. RP2040 has no compile recipe (compile.py's RECIPES), and the chip-level evidence for the RP2040 (`tests/cortexm0/test_blink.py`) is a bare-metal blink, because an Arduino/pico-sdk build calls into the RP2040 boot ROM, whose licence the 2026-08-24 notes record as not redistributable.

Decide, in rules/board-claims.md, what counts as a manifest RP2040 board's own evidence, and build it for both boards. The shape that keeps §7's point: a board-specific image whose watched GPIO is the one that board's variant names for one of its own pads (read by the preprocessor reader OH-181 built, not typed), built by the toolchain that builds the chip-level blink, loaded by board name, stepped on the cortexm0 core, and watched through the board's own pad; and it must differ from what a sibling board's variant would give (as OH-188's run tests check siblings from board_manifest.ROWS). If that is not the right shape, say why in the rule and build the one that is. It does not give these boards a page build; that is OH-161's compile service.

Done when both boards hold runs in TWINS through BOARD_FIRMWARE_VERIFIED entries that check_board_claims accepts, and a test fails if either board's image is built for a sibling's pin.

**Note 2026-09-30:** 2026-09-30: in review. Commits c64ace4 (rp2040.py GPIO words, pin view), a9c4037 (KB2040 run test, blink.c), 90cd7bd (Glyph Mini run test), 1c9b487 (vendor statements), 817d6af (BOARD_FIRMWARE_VERIFIED entries), f0275ee (board-claims s11).
RULE (s11): with no RP2040 recipe in webui/compile.py RECIPES and a sketch that stops at the boot ROM, an RP2040 row holds its own entry by the chip's bare-metal blink made the board's. tests/webui/rp2040_rows/blink.c toggles WATCHED, given with -D, which only the board's own arduino-pico pins_arduino.h defines (-I on its variant; stdint.h first, as Arduino.h does); built by the chip blink's arm-none-eabi-gcc with its flags and tests/cortexm0/blink/blink.ld; committed and rebuilt byte for byte where the toolchain is. The GPIO is read by OH-181's reader with the board's build flags, so the compiler's reading (image) and the reader's (test) must agree. Loaded by name via api.load_firmware at FLASH+BOOT2_BYTES, stepped on cortexm0, watched through api.pin_levels at the pad's chip_index; the vendor names the GPIO too (Glyph: /GPIO-<n> net; KB2040: net MOSI, so its schematic's IC2 pin GPIO19). Siblings: other RP2040 rows plus the XIAO RP2040s' registered arduino-pico variant; the watched name numbers another GPIO in each, their pads read input throughout, and blink.c built against each sibling's variant, run on this board, moves that pad and leaves this board's input. No page build (OH-161). FUNCSEL (io_bank0.json: reset 0x1f) is not modelled, as for the chip's own blink.
PIN VIEW: webui/boards/rp2040.py names GPIO=SIO, GPIO_ENABLE=SIO_GPIO_OE, GPIO_OUT=SIO_GPIO_OUT, so api.row_levels reads RP2040 rows' pads (before: no level at all, while each board file's assumption said the pin view reads chip_index). test_pin_view: every row's module names the words, the RP2040 rows agree with rp2040.pin_states on shared GPIOs, the no-words branch held with a stand-in module.
KB2040: MOSI, GPIO19 (read from variants/adafruit_kb2040/pins_arduino.h + variants/generic/common.h), pad MOSI; kb2040_blink.bin 76 bytes; input, low 16, high 17, low 470, high 923, low 1376, high 1829, low 2282, high 2735. Siblings' MOSI: Glyph Mini 3, XIAO-RP2040-DIP/SMD 3 = pad D3, never enabled or driven, input throughout. Reasons asserted: PIN_LED (31) reaches no pad; the Glyph's variant numbers every D<n> the same.
GLYPH MINI: PIN_WIRE0_SDA (its SDA; the XIAO's SDA is a #define naming a macro the reader refuses), GPIO8 from variants/pcbcupid_glyph_mini_2040/pins_arduino.h, pad /GPIO-8; glyph_mini_blink.bin 76 bytes; same transitions. Siblings: KB2040 12, XIAO 6 = pads /GPIO-12, /GPIO-6, input throughout. Reasons asserted: own SDA == PIN_WIRE0_SDA; XIAO SDA refused; MOSI is the XIAO's (3); PIN_LED (16) on no pad.
RED ON PURPOSE (each restored): each image built against each sibling's variant (KB2040 vs Glyph, XIAO; Glyph vs KB2040, XIAO): all three tests of that board red; watched pad chip_index + 1: two red; a sibling row numbering the label as this board does: red; the KB2040 schematic's MOSI read as GPIO20: red; GPIO_OUT aliased to GPIO_OE: pin view agree test and both run tests red; GPIO words removed: run tests red; the KB2040 test loading XIAO-RP2040-DIP: check_board_claims red; the Glyph entry removed: the pin red.
TWINS: 15 of 33 (was 14), runs 19 (was 17). KB2040 file/composed/18+3/21/RP2040 (all four). Glyph Mini file/footprint:no source/20/20/RP2040 (model is OH-195's).
SUITE at f0275ee: 2 failed (the OCP pair, test_import_3d_model), 2384 passed, 38 skipped. All CLAUDE.md checkers OK, check_facts OK, ticket_guard --self-test 6/6.
