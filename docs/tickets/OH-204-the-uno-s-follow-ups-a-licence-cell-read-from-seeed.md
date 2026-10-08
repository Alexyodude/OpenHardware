---
id: OH-204
title: 'The Uno''s follow-ups: a licence cell read from Seeed''s tree, source''s two
  meanings, duplicate tests, an unquoted licence file, a moved citation'
status: open
priority: P3
created: '2026-10-08'
---

Found by OH-201's two reviews (2026-10-08). OH-201 gave the Arduino Uno a `source` naming Arduino's own board file and a test file that holds the artwork pads to it; each item below sits in a file OH-201 did not claim.

1. The ASSETS licence cell in `tools/inventory.py` (`_licence_cell`, `VENDOR_DIR`) searches only `third_party/seeed-xiao`, so the Uno's CC BY-SA 4.0 is reported `present` on the strength of `third_party/seeed-xiao/LICENSE`, and so is every manifest board's. Resolve the tree from the board file's `source.registry`; `third_party/arduino-uno/License.txt` would then back the Uno's for the right reason, and each manifest board its own.
2. `source` now means two things. For every other board with one it names the file the pads were read from; for the Uno it names the file they are checked against, while PROVENANCE.md §2b correctly says the coordinates were measured from PICSimLab's GPL artwork. Say so in PROVENANCE §2b, and correct the comment in `tools/inventory.py` that says `source` is absent on hand-written boards.
3. `tests/rules/test_import_board.py` holds older Uno tests that the new `tests/rules/test_uno_geometry.py` now duplicates. Retire `test_the_unos_traced_pads_still_agree_with_the_vendors_board_file` (weaker: a 0.1 mm bound, a dated docstring). Retire `test_the_unos_pad_labels_are_the_nets_the_vendor_put_them_on` (a hand-typed label table) now that the new file closes the label set. Retire `test_the_unos_artwork_is_not_uniformly_scaled_and_the_file_says_so` only together with removing the two scales from the board file's `assumption`; it is one of the three tests holding the row spacing, so whatever replaces it must still hold that. Keep `test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses` (OH-96's evidence, and the bound on the row spacing that rests on no sentence) and `test_the_arduino_unos_thirty_two_pads_come_off_its_four_headers` (it tests the reader).
4. The registry's `arduino-uno` row in `tools/board_sources.py` names no licence file, so `licence_evidence` cannot be generated for the Uno. Add `file="License.txt"` with its quoted words; `third_party/arduino-uno/License.txt` reads "This project's hardware is licensed under the Creative Commons Attribution-ShareAlike 4.0 International License".
5. `webui/boards/atmega328p.py`: `SUPPLY` cites `content/hardware/02.uno/boards/uno-rev3/tech-specs.yml` in arduino/docs-content, which now returns 404; the file is at `content/hardware/uno/boards/uno-rev3/tech-specs.yml`, and its "I/O Voltage: 5V" still holds. Re-cite it with a commit, as OH-201 cited the datasheet's JANALOG table. The comment above `HEADER` says AREF, RESET, 5V and the GNDs "have no MCU pin behind them"; they reach the ATmega's AREF, RESET, VCC and GND pins (ZU4 in Arduino's board file). Only NC, 3V3 and VIN reach none.

Done when each item is fixed with a test that fails when it is reverted where the item is behaviour, or, where it is prose, the sentence says only what the files show.
