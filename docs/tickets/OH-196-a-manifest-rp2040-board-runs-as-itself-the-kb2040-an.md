---
id: OH-196
title: 'A manifest RP2040 board runs as itself: the KB2040 and the Glyph Mini'
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-196-*
---

Part of OH-174. The Adafruit KB2040 and the PCBCUPID Glyph Mini RP2040 hold geometry and pins and read `RP2040:no` for runs: rules/board-claims.md §7 gives a manifest board its own run evidence only through a named test that compiles for that board against its own variant, runs the image, and watches a GPIO the variant names through the board's own pad. The ESP32 manifest boards meet that through the page's compile service. RP2040 has no compile recipe (compile.py's RECIPES), and the chip-level evidence for the RP2040 (`tests/cortexm0/test_blink.py`) is a bare-metal blink, because an Arduino/pico-sdk build calls into the RP2040 boot ROM, whose licence the 2026-08-24 notes record as not redistributable.

Decide, in rules/board-claims.md, what counts as a manifest RP2040 board's own evidence, and build it for both boards. The shape that keeps §7's point: a board-specific image whose watched GPIO is the one that board's variant names for one of its own pads (read by the preprocessor reader OH-181 built, not typed), built by the toolchain that builds the chip-level blink, loaded by board name, stepped on the cortexm0 core, and watched through the board's own pad; and it must differ from what a sibling board's variant would give (as OH-188's run tests check siblings from board_manifest.ROWS). If that is not the right shape, say why in the rule and build the one that is. It does not give these boards a page build; that is OH-161's compile service.

Done when both boards hold runs in TWINS through BOARD_FIRMWARE_VERIFIED entries that check_board_claims accepts, and a test fails if either board's image is built for a sibling's pin.
