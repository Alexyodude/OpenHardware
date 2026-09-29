---
id: OH-177
title: 'Four more boards on chips that already run: QT Py ESP32-C3, Feather ESP32-C6,
  KB2040 and Glyph Mini RP2040'
status: open
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-177-*
---

Part of OH-174. Once OH-176 makes a board a table row, the next boards are rows. These four are on chips that already run here, publish their PCB in a format this repo reads, and have a pin variant on disk. Surveyed and opened 2026-09-29; the files were fetched to scratch and parsed, not yet added to the registry.

| board | chip | CAD | header elements | licence | pin variant on disk |
|---|---|---|---|---|---|
| Adafruit QT Py ESP32-C3 | ESP32-C3 | adafruit/Adafruit-QT-Py-ESP32-C3-PCB, `Adafruit QT Py ESP32-C3.brd`, EAGLE XML | JP1, JP3 | CC BY-SA 3.0, license.txt read | arduino-esp32/variants/adafruit_qtpy_esp32c3 |
| Adafruit Feather ESP32-C6 | ESP32-C6 | adafruit/Adafruit-ESP32-C6-Feather-PCB, `Adafruit Feather ESP32-C6.brd`, EAGLE XML | JP1, JP3 | CC BY-SA 3.0, license.txt read | arduino-esp32/variants/adafruit_feather_esp32c6 |
| Adafruit KB2040 | RP2040 | adafruit/Adafruit-KB2040-PCB, `Adafruit KB2040.brd`, EAGLE XML | JP1, JP2 | CC BY-SA 3.0, license.txt read | arduino-pico/variants/adafruit_kb2040 |
| PCBCUPID Glyph Mini RP2040 | RP2040 | pcbcupid/glyph-mini-2040, `glyph-mini-rp2040.kicad_pcb`, KiCad | three castellated PinHeader footprints | MIT, LICENSE read | arduino-pico/variants/pcbcupid_glyph_mini_2040 |

Each needs a registry row in tools/board_sources.py (sparse fetch: the board file and the licence, nothing else) and a board row in OH-176's table. The header element names above were read from the files with ElementTree and grep; confirm each against the pads it produces, as the Uno's were.

The Glyph Mini is the first KiCad whole-board PCB through the table (the XIAOs are footprints). If the KiCad path in tools/import_board.py only reads footprints, that gap is this ticket's to close or to split out.

Not in this batch, and why, measured the same day: the Raspberry Pi Pico's published `.brd` is binary, not EAGLE XML, and nothing here reads it. Adafruit's Feather RP2040 has EAGLE CAD but no licence file in its repository. The SparkFun Thing Plus ESP32-C5 has KiCad and a variant, but its README points to a LICENSE.md that is not in the tree.

Done when all four board files are generated from their rows, each pad traces to its vendor file, each signal pad names a chip pin from its variant or says why not, and the OH-175 scorecard shows each board with its layers.

**Paths this will need**, claimed when the ticket is started (they are held by other tickets at filing): `tools/board_sources.py`, `tools/board_manifest.py`, `webui/boards/Adafruit*`, `webui/boards/PCBCUPID*`, `tests/rules/test_board_manifest.py`, `tests/rules/test_board_sources.py`, `README.md`.

**Note 2026-09-29:** First, before the four rows (from OH-176's approving review, 2026-09-29; all LOW, all in files this ticket takes over): (1) board_manifest.py ~333-335 passes modules_dir=BOARDS_DIR, the OUTPUT directory; the chip modules live in import_pindefs.BOARDS_DIR, and the two differ whenever BOARDS_DIR is redirected, as the tests do. With filled_board ignoring modules_dir, a real write produces a false assumption ('No board module describes ESP32-C6 here') and no test catches it before the file is written. Pass import_pindefs.BOARDS_DIR, and add one happy-path write() into tmp_path compared byte-for-byte with the committed file. (2) Menu-key handling in chips_building (~210) is untested: add rpipico2 -> ['rp2350','rp2350-riscv']. (3) The 'entry not in ROWS' guard in write() (~322) is untested. (4) test_the_pilots_reasons_are_what_its_schematic_says checks part and pin per net, not the prose's other facts (part value, U2 OUT on 3.3V, switch/jumper/WS2812 types, RGB.2 to D5.DO); read them or cut them from the reasons. (5) rules/board-claims.md s6 names two enforcing tests that its frontmatter mechanisms do not list, and states the SDA/SCL-to-IO22/IO23 mapping with no test reading it. (6) PROVENANCE.md s2c says every value can be re-read from source.file; chip_pin comes from the variant and the reasons from the .sch. (7) webui/compile.py:70 imports tools.board_manifest at module top without the sys.path fallback its siblings use; run check_layering on it. Items 5-7 touch files outside this ticket's list: claim them first or file them.
