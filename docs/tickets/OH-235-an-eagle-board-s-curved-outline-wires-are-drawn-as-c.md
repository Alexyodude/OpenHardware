---
id: OH-235
title: 'An EAGLE board''s curved outline wires are drawn as chords: the QT Py ESP32-C3''s
  rounded corners are 45-degree chamfers'
status: in-review
priority: P3
created: '2026-10-13'
touches:
- tools/eagle.py
- tests/rules/test_eagle.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Found by OH-229's comparison (2026-10-13): Adafruit's own whole-board STEP of the QT Py ESP32-C3 (Adafruit_CAD_Parts @ c128bceb, MIT) has four true r = 2.54 mm rounded corners, and the composed model draws 45-degree chamfers there -- visible in C:/Users/Alexyodude/scratch/oh229/shots/composed-qtpy-default.png against vendor-qtpy-default.png. The cause is that tools/eagle.py takes an EAGLE wire's endpoints and ignores its `curve` attribute (the bulge in degrees): `extent_mm` says so for the bounding box (eagle.py ~345-352), and the routed copper counts curved wires as unread (~937-953) -- but the board OUTLINE built from Dimension wires is drawn through the chord with nothing printed.

STEPS:
1. Read a Dimension wire's `curve` into arc points at ARC_CHORD_MM (the same chord rule KiCad arcs and drilled holes use, never larger than the true arc), so the outline is the vendor's shape; do the same for silkscreen and copper strokes where a curve is today counted unread, or leave those counted and say so.
2. Hold it to an oracle: the QT Py's rounded corners against Adafruit's own STEP outline (the r = 2.54 cylinders), and the outline's area against the arc-exact area within the chord bound; every EAGLE composed board whose outline carries a curve is listed by the test, and the count is printed, not written here.
3. Recompose; --check before/after shows only the boards with curved outlines move.

Claims: tools/eagle.py and tools/compose_board_3d.py are OH-163's; borrow them when this starts.

**Note 2026-10-14:** 2026-10-14: starts in lane4; borrows tools/eagle.py from OH-163 (returned on close) and claims tests/rules/test_eagle.py (unclaimed). tools/compose_board_3d.py and its tests are lent to OH-231 at the same time, so this ticket changes the reader and holds the outline in test_eagle.py; a change the composer or its tests need waits for OH-231 to close and is listed here.

**Note 2026-10-14 (done, in review):** `tools/eagle.py` now reads a Dimension wire's `curve` (`arc_points`, `ARC_CHORD_MM = 0.2`) into the points of its arc; `extent_mm` is exact for arcs because the points where an arc crosses an axis are vertices; `tests/rules/test_eagle.py` is new (11 tests). Sign: positive `curve` is counter-clockwise from the first point to the second in EAGLE's y-up frame; held by Adafruit's own STEP (the four r = 2.54 mm corner cylinders), where the wrong sign puts the centre outside the board. Silkscreen curves (counted `arc`) and routed-copper curves (counted `curved`) are left counted ON PURPOSE, said in the code: drawing them would move boards whose outline is straight (the Uno's DIP notch; `_silk_mark` also reads those wires as pin-1 marks). Two chord constants now exist, `eagle.ARC_CHORD_MM` and `compose_board_3d.ARC_CHORD_MM`, with a test that they agree; unify when OH-231 returns the composer.

Boards with a curved Dimension wire, computed by `test_every_board_with_a_curved_outline_is_listed_and_counted`: 5 of 8 fetched .brd (Feather ESP32-C6, HUZZAH32, QT Py ESP32-C3, Uno, Thing Plus ESP32-C6). Composed boards whose `--check` output changed: Arduino Uno (outline 12 -> 33 points), SparkFun Thing Plus ESP32-C6 (8 -> 84), Adafruit QT Py ESP32-C3 (8 -> 84), Adafruit Feather ESP32-C6 (8 -> 84), and nothing else but their triangle and finish counts. (HUZZAH32 is not a composed board.) Tests that failed first on the old reader: 10 of the 11 new ones.

**Left for OH-231's close (composer test, not edited):** `tests/rules/test_compose_board_3d.py::test_the_unos_outline_is_the_size_arduino_publishes` pins `len(ring) == 12, "the Uno's silhouette has twelve corners"` and now fails with `assert 33 == 12`: the Uno's three 90-degree chamfers are r-curved arcs in Arduino's file. No reader change can keep it green; its count should become the arc-flattened ring's (33), or the test should count corners (direction changes above a turn threshold). The size assertions before it pass. Full run of eagle, composer, import_3d_model, import_board, import_pindefs, import_schematic, board_manifest, uno_geometry, inventory, kicad and kb2040 tests: 878 passed, 2 skipped, 1 failed (that one).

**Note 2026-10-14:** 2026-10-14 borrows tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py (OH-163's, passed on from OH-231 at its close) for the follow-up: the Uno outline test's rounds/sharp-corners assertion, and compose_board_3d.ARC_CHORD_MM = eagle.ARC_CHORD_MM with the equality test dropped. They go back to OH-163 at close.
