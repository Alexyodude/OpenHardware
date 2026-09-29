---
id: OH-179
title: A manifest board compiles against its own variant and shows only its own pads,
  not a XIAO sibling's
status: done
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-179-*
- webui/compile.py
- tests/webui/test_compile.py
- webui/api.py
- webui/boards/catalogue.py
- tools/board_manifest.py
- tools/import_pindefs.py
- webui/boards/SparkFun*
- webui/boards/Adafruit*
- rules/board-claims.md
- tools/check_board_claims.py
- tests/rules/test_board_claims.py
- tests/webui/test_board_catalogue.py
- tests/rules/test_board_manifest.py
- tests/rules/test_import_pindefs.py
- tests/webui/test_pin_view.py
- tests/webui/test_feather_esp32c6_board.py
- tests/webui/feather_esp32c6/**
---

Part of OH-174, found by OH-176. The page picks a board's compile recipe and its pin module by chip. For the XIAO boards that was the same thing as picking by board. For the SparkFun Thing Plus ESP32-C6 it is not: per OH-176's report, the page would build a sketch for it with the XIAO ESP32-C6 variant and list XIAO labels such as D0 and LED as its on-board pins. Those are another board's pins presented as this one's.

Also from OH-176: the board file's `image.file` names an SVG that is not generated. Nothing reads the field today, and a field naming a file that does not exist is still a false statement in the file.

Make both follow the board, not the chip: a board from the manifest compiles against its own variant and shows only its own pads. Where the board has no variant the compiler knows, refuse with a message naming what is missing, rather than falling back to a sibling's. Decide `image` for manifest boards: generate the outline as the XIAO importer does, or drop the field for them and say why.

Before claiming this works on the page, check it against a running server, not only the code (the 2026-09-06 handoff records a report that was true of the source tree and false of the process the user was looking at).

Done when the pilot compiles against `sparkfun_esp32c6_thing_plus` or is refused naming it, the pin view lists the pilot's 28 pads and no XIAO label, and a test fails if either regresses.

**Paths this will need**, claimed when the ticket is started (they are held by other tickets at filing): `webui/compile.py`, `webui/api.py`, `tests/webui/test_compile.py`.

**Note 2026-09-29:** 2026-09-29: COMPILE (9c839eb). recipe_for gives a board_manifest row its chip's recipe with the row's own arduino-esp32 variant as the only pin table (own_variant: extra_includes emptied, bsp_includes replaced; a chip whose recipe compiles a variant's sources, SAMD21, is refused). unmet reads the row's pins_arduino.h and refuses, naming each gap, where a quoted #include is on none of the build's include directories or a static const initialiser uses a name no reached header defines (through the macros it names). Held to the compiler: built anyway, each row builds exactly when unmet is empty and fails on the first thing it names. Feather ESP32-C6 builds; the pilot is refused naming arduino-esp32 variants/sparkfun_esp32c6_thing_plus/pins_arduino.h and SOC_GPIO_PIN_COUNT (its LED_BUILTIN); the QT Py is refused for soc/soc_caps.h, on none of the C3 build's include directories, and SOC_GPIO_PIN_COUNT. XIAO unchanged: every board's recipe, every command of a blink build and the image bytes recorded before and after, identical for the 10 boards that build; the 16 other refusals word for word. PIN VIEW (87f333d). For a row, pin_levels answers from api.row_levels (the chip module's GPIO_ENABLE/GPIO_OUT read at each pad's own chip_index, keyed by its own label) and pad_view never captions from the chip's PIN_NAMES; esp32c*.py untouched. Before, a running Thing Plus listed 12 more pins, first D0; now its 28 pads and no XIAO label, each row checked running. row_levels equals each chip module's pin_states on every shared GPIO over four register states. The rows' assumption now says so. RUNS (0ea09e0). BOARD_FIRMWARE_VERIFIED in catalogue.py maps a row to its own test; FIRMWARE_VERIFIED unchanged for other boards. Adafruit Feather ESP32-C6 -> tests/webui/test_feather_esp32c6_board.py: rebuilds feather_esp32c6/blink.bin (206 bytes, SDA blink) byte for byte against its own variant, loads it by board name, steps 110,000 and watches GPIO19 alternate at one period through the pad labelled SDA; 19 is read from its pins_arduino.h and equals that pad's chip_index; the XIAO table's SDA (GPIO22) is read too and never enabled or driven. Red with the image built against the XIAO variant. check_board_claims reads the board register (absent is an error), holds it to checks 4 and 5, and requires the test to name its board. rules/board-claims.md s7. Pilot and QT Py withheld: their tables do not compile here. IMAGE (a610fe9): rows drop image.file (nothing reads it; nothing writes an EAGLE outline SVG). LIVE, own server on :54144, stopped after: /api/boards Feather buildable and verified, the other two not, with firmware_withheld; /api/board/pins 28/28/14 pads, no XIAO label; compile of the pilot 400 naming its variant and SOC_GPIO_PIN_COUNT, of the QT Py 400 naming soc/soc_caps.h; the Feather built 206 bytes and loaded, state.pins keyed by its own 13 labels, SDA high/low alternating over 12 runs of 13,000 steps. Not a rendered browser view. 31 mutants, all red (one first survived; the pin was tightened). TWINS: 9 of 29 hold all four; geometry 28, model 25, pins 21, runs 13. Full pytest: 2 failed (the OCP pair), 2201 passed, 31 skipped; all checkers and checkall's other rows OK. For OH-161: webui/compile.py and tests/webui/test_compile.py return to it; the Feather's table now also reads webui/arduino/variants/xiao_esp32c6/soc/soc_caps.h, whose comment speaks only of Seeed's.

**Note 2026-09-29:** 2026-09-29: approved by an independent review (18 reviewer mutants all red; Feather image rebuilt byte-identical and shown to read the core's GPIO_OUT; XIAO recipes, commands and image md5s identical for the 10 building boards, 16 refusals word-for-word). Suite at 108bfa9: 2 failed (the OCP pair, OH-163), 2201 passed, 31 skipped. TWINS: 9 of 29, runs 13. Follow-ups (two MEDIUM: a prose run-claim about a manifest board is not caught; unmet's regex reading of C misjudges 2 of 404 variants and constructed cases) filed as OH-183.
