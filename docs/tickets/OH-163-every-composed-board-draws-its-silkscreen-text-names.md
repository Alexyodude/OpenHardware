---
id: OH-163
title: Every composed board draws its silkscreen text, names its default-finish colours,
  and stops double-reporting its test points
status: open
priority: P2
created: '2026-09-04'
touches:
- tools/model_from_datasheet.py
- tests/rules/test_import_3d_model.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
---

Twenty-five of twenty-six boards draw a vendor file or a board composed from the vendor's PCB, every placement is drawn or refused with a reason (OH-150), and what a person sees is still short of a photograph in four measurable ways. This ticket is those four, counted from `python tools/compose_board_3d.py --check` on 2026-09-04 (11 composed boards) and from the shipped .glb files.

    1. Silkscreen TEXT is drawn on no board. Per board: 47 to 99 text items "not
       drawn -- text needs a font", plus a handful of arcs, circles and polygons.
       The pin labels, "Seeed Studio", the version string: all of it. OH-111 lit
       the underside because that is where the labels are printed; they are
       still not there to light.
    2. 6 to 10 colour groups per board fall to DEFAULT_FINISH -- "nothing says
       what this is" -- metalness 0.1, roughness 0.6. On the RP2350 and the C5
       that is 10 of ~19 groups; #2a2a2a alone is 5,126 triangles on the C5.
       They render as the same matte grey whatever they are.
    3. 4 to 6 placements per board are ABSENT with a stated reason: the two
       Seeed logos (silkscreen artwork), the MOUDLE14P module outline, and 12 +
       36 test points across the five KiCad XIAOs. Explained, but not drawn.
    4. One board, XIAO-XIAO STM32C5-SMD, draws an extruded footprint: no vendor
       page, no PCB, no board-support package (OH-26: 0 of 35 pads).

Also counted and left alone on purpose, because the reason still holds: inner copper layers and zone fills (inside the laminate), and the two 1.270 x 0.508 mm cutouts per XIAO.

Comparison, read 2026-09-04: Xplora3D draws a generic breadboard (choice of colours), snaps pins, exports GLB/PNG, and its parts are library models of generic components; it has no vendor board geometry at all. Simulator86 has no 3D view. This repository's differentiator is that every millimetre is the vendor's; the gaps above are the labelling and the materials on top of that geometry, not the geometry.

STEPS, each with its own evidence:

1. Silkscreen text. KiCad renders its own text with a stroke font, and the text items the composer skips carry the vendor's font size and thickness in the PCB file. Draw them with a stroke font as ink strokes, the same way tracks are drawn -- which needs a font file with a licence this repository can carry; establish which (KiCad's own stroke font ships under its licence, to be checked, not assumed) before writing a glyph. Done when the "text N" count in --check reaches 0 on every board and a pin label is readable in the screenshot.
2. The default-finish colours. Same method as FINISHES' own entries: load every model that contributes each colour, tally triangles per package, and name the material from what the package is -- a QFN body, a crystal can, a connector shell -- with the evidence in the entry's `why`. A colour that cannot be named stays default and is listed as such in the page's own inventory rather than silently grey.
3. The absent classes, decided per class not per placement: a logo is silkscreen artwork (an SVG or polygon in the PCB -- draw it as ink if the file carries the geometry, refuse if it is a bitmap); test points are bare copper pads and are ALREADY drawn as copper by OH-110 -- so their "absent" is a double report to remove; the module outline is a courtyard with nothing to draw, and should stop being counted as a placement.
4. The STM32C5 board: docs/research/board-models/ records that Seeed publishes no wiki page for it. Re-check the vendor once, dated; if still nothing, the footprint extrusion is the honest picture and the page already says so.

Every number above is from --check; do not restate the counts in prose anywhere else (CLAUDE.md's inventory rule) -- the generator is the record.

**Note 2026-09-29:** Found 2026-09-29 by the OH-175 review, not caused by it. Two tests in tests/rules/test_import_3d_model.py fail with ModuleNotFoundError: No module named 'OCP' on a machine where the cached part-R_Axial STEP files exist and OCP is not installed for the python running pytest. Their guards (lines 529 and 726 at 4f5b2dd) skip only when the cached STEP is missing, while the file's header (lines 23-25) says those tests skip unless BOTH OCP is installed and the archive is on disk. Reproduced at f77cfc4 in a temporary worktree, so it predates OH-175 and OH-176. The fix is the guard, not the header: check for OCP the same way the header describes.

**Note 2026-09-29:** 2026-09-29: tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py lent to OH-180 (compose the manifest boards from their own EAGLE board files, as the Uno is), nobody holding this ticket. Add both back with tickets set OH-163 --touch when OH-180 closes. Nothing in this ticket's four items is changed by the loan.

**Note 2026-09-29:** 2026-09-29: tools/import_3d_model.py also lent to OH-180, for three rows in COMPOSED: test_the_two_lists_of_composed_boards_agree requires COMPOSED to equal the boards in compose_board_3d.COMPOSITIONS, and OH-180 adds the three manifest boards there. Add it back with the other two when OH-180 closes.

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py, tests/rules/test_compose_board_3d.py and tools/import_3d_model.py returned to this ticket; OH-180 is done.

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py, tests/rules/test_compose_board_3d.py and tools/import_3d_model.py lent to OH-186 (master red: the KB2040 is composed by construction and missing from COMPOSED and EXPLAINS) and then OH-187 (passives drawn as the wrong kind), in that order. Return them when OH-187 closes.

**Note 2026-09-30:** 2026-09-30: OH-186 and OH-187 are done; the composer loan passes straight to OH-189 (tools/compose_board_3d.py, tests/rules/test_compose_board_3d.py, tools/import_3d_model.py). Return them here when OH-189 closes.

**Note 2026-09-30:** 2026-09-30: the composer, its tests and the importer return here; OH-189 is done. Composer tickets waiting for them: OH-184 (back-side silkscreen), OH-190 (diode test and the Uno's MiniMELFs), OH-191 (the Uno's fuse and varistors), OH-193 (rows held to the vendor's words).

**Note 2026-09-30:** 2026-09-30: the composer, its tests and the importer lent again, to OH-191, OH-190 and OH-193 in that order (one worker, lane2). Return them when OH-193 closes.

**Note 2026-09-30:** 2026-09-30: the composer, its tests and the importer return here; OH-190, OH-191 and OH-193 are done. Composer tickets waiting: OH-184 (back-side silkscreen), OH-195 (KiCad manifest composition), OH-197 (the Uno's diodes), OH-199 (low edges).

**Note 2026-09-30:** 2026-09-30: the composer, its tests and the importer lent to OH-195 (KiCad manifest composition). Return when OH-195 closes.

**Note 2026-10-08:** 2026-10-08: the composer, its tests and the importer return here; OH-195 is done (merged at a2428d1).

**Note 2026-10-08:** 2026-10-08: the composer, its tests and the importer lent to OH-198, whose phase 2 composes the Olimex ESP32-C6-EVB, a KiCad 5 board: kicad_statements must read through kicad.board_tree, or it finds no statements in a KiCad 5 file (OH-198's review). Return when OH-198 closes.
