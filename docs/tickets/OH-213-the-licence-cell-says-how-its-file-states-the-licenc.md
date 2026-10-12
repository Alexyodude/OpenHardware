---
id: OH-213
title: The licence cell says how its file states the licence, and the Thing Plus C6
  reads its own board file
status: open
priority: P3
created: '2026-10-09'
touches:
- tools/inventory.py
- tests/rules/test_inventory.py
- tools/board_sources.py
- tests/rules/test_board_sources.py
- tests/rules/test_board_manifest.py
---

Found by OH-212's review (2026-10-09). Since OH-212 a registry board's ASSETS licence cell names the file its registry row reads the licence from. Four edges remain.

1. The cell drops the registry's grade. `tools/board_sources.py` grades each licence (`Evidence`: e.g. STATED where a README or a board frame states the licence, OPENED where a licence text is read), and `tests/rules/test_board_sources.py` says a README asserting a licence is not the licence; the board files carry "graded stated" in `licence_evidence`. The inventory shows the Glyph C3 and C6 and both Olimex boards (README sentences) and the Qwiic Pocket and Thing Plus C5 (a board frame's text) exactly as it shows Adafruit's licence text. Carry the grade into the cell's detail, and say in both report blocks that the file may state the licence rather than hold its text, the registry grading which. Recast the hard sentence "the file the registry row the board file's source.registry names reads its licence from".
2. The SparkFun Thing Plus ESP32-C6 reads `absent` because its registry row names no file and cites a sibling repository's LICENSE.md, while its own fetched board file, `Hardware/Thing_Plus_ESP32_C6.brd`, holds "Released under the Creative Commons Attribution Share-Alike 4.0 License" (the sentence the Qwiic Pocket and C5 rows quote), and `tools/board_manifest.py`'s row and the board file's `licence_evidence` already read it (FRAME1). Give the registry row that file and quote, graded as the others are. `tests/rules/test_inventory.py`'s test of a row that names no file pins this live row (`thing.licence.file == ""`): give it a synthetic source instead.
3. The markdown table shows an absent licence cell's class without its detail, so a row that names no file reads as if its file were missing. Show the detail on absent licence cells, or say in both prose blocks what an absent licence cell means.
4. The docstring says a row naming no file reads `absent` whether or not its tree is fetched; only the fetched half is tested. Test the unfetched half.

Done when each cell says how its file states the licence, the Thing Plus C6 reads its own file, an absent cell's reason reaches the page, and both halves of the no-file case are tested.

**Note 2026-10-12:** 2026-10-12: claims tests/rules/test_board_manifest.py (unclaimed), whose test_a_row_whose_licence_is_stated_nowhere_is_refused pins the live Thing Plus C6 row as reading its licence from no file; item 2 gives that row its own board file, so the test moves to a synthetic registry row.
