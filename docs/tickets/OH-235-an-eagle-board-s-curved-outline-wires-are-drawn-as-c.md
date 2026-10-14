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

**Note 2026-10-14 (done, in review):** `tools/eagle.py` now reads a Dimension wire's `curve` (`arc_points`, `ARC_CHORD_MM = 0.2`) into the points of its arc; `extent_mm` is exact for arcs because the points where an arc crosses an axis are vertices; `tests/rules/test_eagle.py` is new (11 tests). Sign: positive `curve` is counter-clockwise from the first point to the second in EAGLE's y-up frame; held by Adafruit's own STEP (the four r = 2.54 mm corner cylinders), where the wrong sign puts the centre outside the board. Silkscreen curves (counted `arc`) and routed-copper curves (counted `curved`) are left counted ON PURPOSE, said in the code: drawing them would move boards whose outline is straight (the KB2040, SparkFun Pro Micro ESP32-C3 and Qwiic Pocket ESP32-C6, which are straight-outline boards with silkscreen arcs). Two chord constants now exist, `eagle.ARC_CHORD_MM` and `compose_board_3d.ARC_CHORD_MM`, with a test that they agree; unify when OH-231 returns the composer.

Boards with a curved Dimension wire: listed and counted by `test_every_board_with_a_curved_outline_is_listed_and_counted`, which prints them. Composed boards whose `--check` output changed: Arduino Uno (outline 12 -> 33 points), SparkFun Thing Plus ESP32-C6 (8 -> 84), Adafruit QT Py ESP32-C3 (8 -> 84), Adafruit Feather ESP32-C6 (8 -> 84), and nothing else but their triangle and finish counts. (HUZZAH32 is not a composed board.) Against the old reader, the segment-count and area tests raise AttributeError (they call `arc_points`) and only the STEP test fails behaviourally; with a shim for `arc_points`, 7 fail behaviourally.

<<<<<<< HEAD
**Left for OH-231's close (composer test, not edited):** `tests/rules/test_compose_board_3d.py::test_the_unos_outline_is_the_size_arduino_publishes` pins `len(ring) == 12, "the Uno's silhouette has twelve corners"` and now fails with `assert 33 == 12`: the Uno's three 90-degree chamfers are r-curved arcs in Arduino's file. No reader change can keep it green; its count should become the arc-flattened ring's (33), or the test should count corners (direction changes above a turn threshold). The size assertions before it pass. Full run of eagle, composer, import_3d_model, import_board, import_pindefs, import_schematic, board_manifest, uno_geometry, inventory, kicad and kb2040 tests: 878 passed, 2 skipped, 1 failed (that one).

**Note 2026-10-14:** 2026-10-14 borrows tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py (OH-163's, passed on from OH-231 at its close) for the follow-up: the Uno outline test's rounds/sharp-corners assertion, and compose_board_3d.ARC_CHORD_MM = eagle.ARC_CHORD_MM with the equality test dropped. They go back to OH-163 at close.
=======
**Left for OH-231's close (composer test, not edited):** `tests/rules/test_compose_board_3d.py::test_the_unos_outline_is_the_size_arduino_publishes` pins `len(ring) == 12, "the Uno's silhouette has twelve corners"` and now fails with `assert 33 == 12`: the Uno's file has three r = 1 mm quarter-rounds, at (1,1), (1,52.34) and (65.04,1); its 45-degree chamfers are separate straight wires. No reader change can keep it green; its count should become the arc-flattened ring's (33), or the test should count corners (direction changes above a turn threshold). The size assertions before it pass. The reviewer's replacement for that assertion was run against this reader in a scratch copy and holds (three r = 1 corners of 9 points each, 6 sharp corners, ring of 33): for `len(ring) == 12` put `rounds = [(1.0, 1.0), (1.0, 52.34), (65.04, 1.0)]`; `on` = the ring's points at distance 1.0 (abs 1e-9) from each; assert each has more than 2 points and `sharp` (points in none of them) has exactly 6. It lands, with `compose_board_3d.ARC_CHORD_MM = eagle.ARC_CHORD_MM` (after which the equality test goes), when OH-231 returns the composer files.

**Note 2026-10-14 (review round):** the sign is cited in `arc_points` (Autodesk UL_WIRE help: positive is counter-clockwise; KiCad `eagle_parser.cpp:512-534`). Axis crossings now split the sweep, each piece is cut by `ceil(length / chord)`, and a crossing within `AXIS_EPS_MM` = 0.05 mm of a wire's end is dropped (extent error at most eps^2 / 2r, 0.0005 mm at r = 2.54), so no segment is near zero. A bad `curve` (not finite, or beyond +-360) and an arc with no radius are refused naming the file and wire. The area oracle is two-sided. New tests: reflex arc past 2 pi, two-segment floor, rotated-arc segment length over `CHAIN_TOLERANCE_MM` and one composer ring, bad curve. Mutants: the 52d16b1 reader fails the short-arc, segment-length and bad-curve tests; no floor of two fails the short-arc test; crossings only over 0..2 pi fails the reflex and only-arcs extent tests; no eps drop fails the segment-length and the clockwise-corner tests. `--check` is identical to the first fix: the same four boards and the same point counts, because every fetched curved wire starts and ends on an axis. Silkscreen-arc example is now the straight-outline boards (KB2040, Pro Micro ESP32-C3, Qwiic Pocket ESP32-C6).
<<<<<<< HEAD
>>>>>>> 6021826 (fix(eagle): arc points split at axis crossings, no sliver segments; sign cited; bad curve refused (OH-235))
=======

**Note 2026-10-14 (confirmation LOWs):** a bad coordinate now names the file once (floats read before the `try`); the two remaining sub-tolerance cases (arc under 0.04 mm, crossings under 0.02 mm apart) are named in the `AXIS_EPS_MM` comment; the two earlier note sentences above are corrected.
>>>>>>> ce57817 (fix(eagle): a bad coordinate names the file once; tiny-arc limits named (OH-235))
