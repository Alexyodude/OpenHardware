---
id: OH-176
title: A board that is not a XIAO footprint is a row in a table, and the SparkFun
  Thing Plus ESP32-C6 is the first row
status: in-review
priority: P1
created: '2026-09-29'
touches:
- tools/board_manifest.py
- tools/import_board.py
- tools/import_pindefs.py
- webui/boards/catalogue.py
- webui/boards/SparkFun*
- README.md
- tests/rules/test_board_manifest.py
- tests/rules/test_import_pindefs.py
- tests/webui/test_pin_view.py
- webui/compile.py
- tests/webui/test_compile.py
- rules/board-claims.md
- webui/emulator_server.py
- tests/webui/test_board_catalogue.py
- PROVENANCE.md
---

Part of the digital-twin program ticket. Today a board that is not a Seeed XIAO footprint is a hand-written exception in several places: `chip_for` in webui/boards/catalogue.py raises unless the name starts `XIAO-` or is in `IRREGULAR`; tools/import_pindefs.py's table is keyed on XIAO names (the Uno's pindefs say "by hand; this board is not in tools/import_pindefs.py"); the Uno's pads came off PICSimLab's board.svg and were only checked against the vendor's .brd afterwards. At that cost, "all open-source hardware" means one bespoke change per board, forever.

Make a board a row in a table. One row names: the registry source (tools/board_sources.py), the CAD file inside it, which placed elements carry the header pads (import_board.py's `--select`), the chip, and the BSP variant that defines its pins. Everything else is generated from that row by code that already exists: import_board.py for pads, import_pindefs.py for chip pins, catalogue.py for the chip. Adding a board means adding a row. A row whose inputs are not on disk fails loudly, naming what is missing, and never writes a board with guessed values.

Pilot: the SparkFun Thing Plus ESP32-C6. Every input is already on disk: third_party/sparkfun-thing-plus-esp32-c6/Hardware/Thing_Plus_ESP32_C6.brd (EAGLE, CC BY-SA 4.0 per the registry row) and third_party/bsp/arduino-esp32/variants/sparkfun_esp32c6_thing_plus/. ESP32-C6 is in FIRMWARE_VERIFIED, so this board can reach every layer except the 3D model, which is its own ticket.

Keep the XIAO path working unchanged: the 25 XIAO files must regenerate byte-identical. Moving the Uno onto the table is welcome if it falls out; if its derivation or pindefs would change, say what changed and why rather than forcing it.

Done when the pilot board file is generated from its row, its pads trace to the vendor's .brd coordinates, its signal pads name chip pins from the arduino-esp32 variant with the file that named each, the README board list and every existing test agree, and a row pointing at a missing file has been shown to fail.

**Note 2026-09-29:** 2026-09-29: tools/board_manifest.py holds one row (source, CAD, --select, chip, package, variant, opted-in labels); import_board.py writes the pads, import_pindefs.py the pins, catalogue.chip_for reads the chip. webui/boards/SparkFun Thing Plus ESP32-C6.json: 28 pads off J1 of Thing_Plus_ESP32_C6.brd, labels = the vendor's nets; 5 name a chip pin (IO6/SDA, IO7/SCL, IO16/TX, IO17/RX, IO19/SCK) from arduino-esp32 variants/sparkfun_esp32c6_thing_plus/pins_arduino.h @ 2787dab, each agreeing with the IO number in the net name. The variant's A0-A5, MOSI, MISO name no pad label here (the schematic's J1 pin names do: A0 is on net IO0), so those pads stay null; joining them needs the .sch, not done. A row with a missing CAD and variant exits 2 naming both files. The 25 XIAO files and 4 module HEADER blocks regenerate identical to their HEAD blobs. Full pytest: 4 failed, 2124 passed, 31 skipped. 2 are test_check_facts: CLAUDE.md says 25 of 26 boards draw a model and the one left is the STM32C5; now 27 boards and the SparkFun board has no model. CLAUDE.md is OH-149's, not edited. 2 are test_import_3d_model (No module named OCP), which fail the same way at f77cfc4. No SVG is generated for the new board.

**Note 2026-09-29:** 2026-09-29 review fixes: (1) recipe_for refuses a board_manifest row with UnknownBoard naming its own variant, the ESP32-C6 recipe's XIAO_ESP32C6 and OH-179; catalogue gives such a row firmware_evidence None with firmware_withheld saying why; /api/boards buildable asks recipe_for; rules/board-claims.md 6. (2) check() runs the variant reader on the row's labels; write() builds the whole file from pads staged in a temp dir; main catches PindefError; a bad-label row exits 2 with or without the check, leaving a scratch copy of the committed file byte-identical. (3) FLAT_PACKAGES maps package to its boards.txt part key (build.mcu / build.chip, menus included); rpipico as RP2040 passes, as RP2350 is refused. (4) Row.reasons: ESP_EN (U1 EN), VREG_EN (U2 EN, RT9080-33GJ5), LED_DO (jumper RGB to WS2812 D5 DO), each read back from the .sch by a test; pilot now 5 chip_pin, 4 supplies, 3 reasons, 16 generic. (5) package-refusal test asserts its own words. (6) licence_evidence quotes FRAME1's CC BY-SA 4.0 sentence from the .brd, checked; derivation names board_manifest.py; pads keyed by element and number; failure tests use tmp_path; row-over-BOARDS and IRREGULAR-and-row raise; SUPPLY_LABELS comment names the Uno test's eight; README and PROVENANCE 2c. XIAO files identical to HEAD blobs. Full pytest: 5 failed, 2135 passed, 31 skipped: check_facts x2 (CLAUDE.md, OH-149), OCP x2 (same at f77cfc4), test_a_failed_build_leaves_nothing_behind once on a build dir gone by the time it was inspected; test_compile.py alone 62 passed.
