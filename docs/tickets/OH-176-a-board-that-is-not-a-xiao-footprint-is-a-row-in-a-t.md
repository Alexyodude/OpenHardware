---
id: OH-176
title: A board that is not a XIAO footprint is a row in a table, and the SparkFun
  Thing Plus ESP32-C6 is the first row
status: open
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
---

Part of the digital-twin program ticket. Today a board that is not a Seeed XIAO footprint is a hand-written exception in several places: `chip_for` in webui/boards/catalogue.py raises unless the name starts `XIAO-` or is in `IRREGULAR`; tools/import_pindefs.py's table is keyed on XIAO names (the Uno's pindefs say "by hand; this board is not in tools/import_pindefs.py"); the Uno's pads came off PICSimLab's board.svg and were only checked against the vendor's .brd afterwards. At that cost, "all open-source hardware" means one bespoke change per board, forever.

Make a board a row in a table. One row names: the registry source (tools/board_sources.py), the CAD file inside it, which placed elements carry the header pads (import_board.py's `--select`), the chip, and the BSP variant that defines its pins. Everything else is generated from that row by code that already exists: import_board.py for pads, import_pindefs.py for chip pins, catalogue.py for the chip. Adding a board means adding a row. A row whose inputs are not on disk fails loudly, naming what is missing, and never writes a board with guessed values.

Pilot: the SparkFun Thing Plus ESP32-C6. Every input is already on disk: third_party/sparkfun-thing-plus-esp32-c6/Hardware/Thing_Plus_ESP32_C6.brd (EAGLE, CC BY-SA 4.0 per the registry row) and third_party/bsp/arduino-esp32/variants/sparkfun_esp32c6_thing_plus/. ESP32-C6 is in FIRMWARE_VERIFIED, so this board can reach every layer except the 3D model, which is its own ticket.

Keep the XIAO path working unchanged: the 25 XIAO files must regenerate byte-identical. Moving the Uno onto the table is welcome if it falls out; if its derivation or pindefs would change, say what changed and why rather than forcing it.

Done when the pilot board file is generated from its row, its pads trace to the vendor's .brd coordinates, its signal pads name chip pins from the arduino-esp32 variant with the file that named each, the README board list and every existing test agree, and a row pointing at a missing file has been shown to fail.
