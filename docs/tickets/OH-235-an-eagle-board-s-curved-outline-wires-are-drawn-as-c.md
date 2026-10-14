---
id: OH-235
title: 'An EAGLE board''s curved outline wires are drawn as chords: the QT Py ESP32-C3''s
  rounded corners are 45-degree chamfers'
status: open
priority: P3
created: '2026-10-13'
touches:
- tools/eagle.py
- tests/rules/test_eagle.py
---

Found by OH-229's comparison (2026-10-13): Adafruit's own whole-board STEP of the QT Py ESP32-C3 (Adafruit_CAD_Parts @ c128bceb, MIT) has four true r = 2.54 mm rounded corners, and the composed model draws 45-degree chamfers there -- visible in C:/Users/Alexyodude/scratch/oh229/shots/composed-qtpy-default.png against vendor-qtpy-default.png. The cause is that tools/eagle.py takes an EAGLE wire's endpoints and ignores its `curve` attribute (the bulge in degrees): `extent_mm` says so for the bounding box (eagle.py ~345-352), and the routed copper counts curved wires as unread (~937-953) -- but the board OUTLINE built from Dimension wires is drawn through the chord with nothing printed.

STEPS:
1. Read a Dimension wire's `curve` into arc points at ARC_CHORD_MM (the same chord rule KiCad arcs and drilled holes use, never larger than the true arc), so the outline is the vendor's shape; do the same for silkscreen and copper strokes where a curve is today counted unread, or leave those counted and say so.
2. Hold it to an oracle: the QT Py's rounded corners against Adafruit's own STEP outline (the r = 2.54 cylinders), and the outline's area against the arc-exact area within the chord bound; every EAGLE composed board whose outline carries a curve is listed by the test, and the count is printed, not written here.
3. Recompose; --check before/after shows only the boards with curved outlines move.

Claims: tools/eagle.py and tools/compose_board_3d.py are OH-163's; borrow them when this starts.

**Note 2026-10-14:** 2026-10-14: starts in lane4; borrows tools/eagle.py from OH-163 (returned on close) and claims tests/rules/test_eagle.py (unclaimed). tools/compose_board_3d.py and its tests are lent to OH-231 at the same time, so this ticket changes the reader and holds the outline in test_eagle.py; a change the composer or its tests need waits for OH-231 to close and is listed here.
