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
- tools/kicad.py
- tests/rules/test_kicad.py
- tools/eagle.py
- PROVENANCE.md
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

**Note 2026-10-08:** 2026-10-08: the composer, its tests and the importer return here; OH-198 is done (merged at 9780c25). Left by its reviews for this ticket: (1) a quarter turn on a two-pad part is invisible to confirm() (SPAN_TOLERANCE_MM=3 against pad-centre spans; a D_SMA model turned 90 degrees on a 5 mm land passes), so such a part's turn rests on its row alone; (2) tools/model_from_datasheet.py walks (footprint ...) itself and cannot open a KiCad 5 board: it should read through kicad.board_tree; (3) the shared USB-C ABSENT reason omits the vendor's own tag that A40-00119-A52-12 is fully compatible with GCT's USB4105-GF-A; (4) KiCad 5 custom-pad (primitives (gr_arc ...)) are not respelled (nothing reads primitives yet).

**Note 2026-10-08:** 2026-10-08: the composer, its tests and the importer lent to OH-184 (back-side silkscreen mirrored twice). Return when OH-184 closes.

**Note 2026-10-08:** 2026-10-08: OH-184 is done (243d22a); the composer, its tests and the importer pass from it to OH-211 (EAGLE MR90/MR270 placed in the wrong order, whose fix also moves from_kicad's back rotation). Return when OH-211 closes.

**Note 2026-10-08:** 2026-10-08: the composer, its tests and the importer return here; OH-211 is done (706cf14). From its review, for the composer: angles are truncated to int before eagle.place (compose_board_3d.py ~4682 and ~4773 build the spelling with str(int(element.rotation)); tools/eagle.py:609-610 likewise), so a fractional angle would turn ink, outline and mark differently from pads; none on disk today.

**Note 2026-10-09:** Step 1 (silkscreen text), 2026-10-09, lane2. FONT LICENCE, checked not assumed: KiCad ships newstroke in common/newstroke_font.cpp under a GPL-2-or-later header (tags 8.0.0 and 10.0.7; CJK added 2019 by MIT code from Source Han Sans, SIL OFL 1.1), so vendoring KiCad's table would put GPL in the MIT tree. The font's author, Vladimir Uryvaev, releases it under CC0 (http://vovanium.ru/sledy/newstroke/en; README.txt in newstroke-font.tgz: "Now released under CC0 licence"). EAGLE's CAM processor draws all text in EAGLE's internal vector font (EAGLE help, TEXT, as Debian's non-free eagle 4.16-5 ships it), inside an executable no part of which may be altered (CadSoft terms in that package's debian/copyright), published nowhere as a font. Hershey not needed. DECISION: fetch, not vendor. NEWSTROKE in tools/compose_board_3d.py fetches the author's tgz (210,057 bytes, sha256 checked) into git-ignored third_party/newstroke/ and reads glyphs from font.lib/symbol.lib/charlist.txt; U+0020-U+007E reproduce the archive's own generated table exactly, which matches KiCad 8.0.0 and 10.0.7 there except '~' (refused). PROVENANCE.md section 4 records it. DONE: tools/kicad.py reads gr_text, fp_text AND footprint property fields (never counted before: the C3's 67 references) as kicad.Text with size, pen, angle (absolute, as KiCad stores it), justify, mirror, keep-upright, bold, italic, face, knockout; hidden text counted as 'hidden text'. compose_board_3d.letter lays them out with KiCad 8.0.0's arithmetic and draws each segment as ink. Held to vendor Gerbers at 1 um: XIAO ESP32-C6 73 texts, 4,178 strokes, all on Seeed's KiCad 8.0.0 plot; Olimex ESP32-PoE rev M 188 texts, 5,956 strokes, all on Olimex's KiCad 7.0.9 plot. --check: no KiCad board has a 'text N' unread; every XIAO letters all its text; refused by name: PCBCUPID's 145 Lexend TrueType texts (the file's render_cache holds their outlines: a follow-up could draw them), Olimex C3-DevKit-Lipo's 33 knockouts, EAGLE boards' text (font). Composed .glb: only silkscreen triangles added, every old triangle kept, no other material changed; extras gain artwork 'text front/back', 'text stroke off the board' and not_drawn.text. Pin labels read on the composed XIAO ESP32-C6's back (raster of the .glb). LEFT: CLAUDE.md's composed-board paragraph still says text 'needs a font shipped' (CLAUDE.md is OH-149's); steps 2-4.

**Note 2026-10-09:** Step 1 evidence, 2026-10-09: commits 315d59c (readers, composer, tests) and cbd2634 (PROVENANCE). Per board, --check before -> after (text lettered of read; refused by reason; silkscreen triangles added, no other material changed): XIAO C3 DIP/SMD 'text 47' unread (and 67 property references uncounted) -> 114 of 114, +5,540; XIAO C6 72 -> 73 of 73, +1,624; XIAO RP2350 99 -> 174 of 174, +6,570; XIAO C5 74 -> 74 of 74, +1,614; XIAO nRF54L15 96 -> 96 of 96, +1,944; PCBCUPID Glyph Mini RP2040 49 -> 0 of 49, 49 refused (Lexend), +0; Glyph C3 50 -> 0 of 48, 48 refused (Lexend), +0; Glyph C6 50 -> 2 of 50, 48 refused (Lexend), +50; Olimex C3-DevKit-Lipo 111 -> 65 of 98, 33 refused (knockout), +5,422; Olimex C6-EVB 211 -> 207 of 207, +12,196; SparkFun Thing Plus C5 (KiCad) none shown, 130 hidden now counted, +0; EAGLE boards unchanged and their text refused for EAGLE's font: Uno 24, QT Py C3 1, Feather C6 5, KB2040 1 (SparkFun Thing Plus C6, Pro Micro C3, Qwiic Pocket C6 count none on layers 21/22). Hidden text, formerly inside 'text', is now 'hidden text'. Each new test seen red by a named break (in the session report). Suite: python -m pytest -q -p no:cacheprovider -> '2 failed, 2547 passed, 39 skipped in 489.46s'; the 2 are the known OCP pair in tests/rules/test_import_3d_model.py under a python without OCP. checkall: every row PASS but 'the test suites pass', for that pair. Found while here, not counted anywhere: an EAGLE board's names and values on layers 25 and 27 (tNames, tValues); eagle._ink reads 21 and 22 only, and whether each vendor's CAM job prints 25 was not checked.

**Note 2026-10-09:** Step 1 review fixes, 2026-10-09, lane2 (the review: MERGE AFTER FIXES, licence clean). DONE: (1) the font is an input, not a fetch -- compose() reads it through newstroke_font() and a KiCad board with text and no font is SKIPPED naming the font and 'python tools/compose_board_3d.py --fetch-font', exit 3; only that flag downloads; _inputs_missing names it, so test_composing_refuses_a_part_turned_the_wrong_way and test_the_manifest_boards_compose_under_test skip offline instead of raising URLError (0144db5). A different choice from the KiCad models, which a composer run still fetches: the review asked for an explicit fetch. (5) urlopen timeout 60 s; a download failing size or sha256 is deleted, named; every read checks the archive's sha256 and each unpacked file against the archive's copy (0144db5). (7) zip(strict=True), the point count checked first (9f67b1a). (3) a silkscreen dimension's text is read as board text wherever the dimension sits, as KiCad 8.0.0 writes it, and its lines counted as 'dimension'; the Glyph C3's and C6's 'Antenna Here!' is Noto Sans and refused by name (257aeba). (6) hidden text rides in extras under 'hidden', not not_drawn.ink, and --check prints it on its own line (2a0f52e). (2) six layout tests -- right justification, top alignment, default pen, bold default pen, pen clamp, italic -- against strokes derived by hand from KiCad 8.0.0's arithmetic, each seen red by breaking its branch (1030b29). (4) PROVENANCE.md 2i (a1fa7fa). STILL REFUSED, by name, for later: PCBCUPID's TrueType text, Lexend and the Noto Sans dimension text (each text's outline polygons are in the file's render_cache; drawing them is new geometry); Olimex C3-DevKit-Lipo's knockout text; EAGLE boards' text (EAGLE's vector font), and EAGLE's tNames and tValues, layers 25 and 27, which eagle._ink does not read (whether each vendor's CAM job prints them is unchecked). NOT DRAWN, counted: a dimension's lines (leader, arrow, text frame). NOT MATCHED: KiCad plots a stroke with round ends and the composer draws each as the rectangle its width sweeps, stopping at its end points (stroke_outline); KiCad 9 boards are laid out with 8.0.0's arithmetic, which the review read as identical at 9.0.0. LATENT, as the review named them, not checked board by board: %R and %V (KiCad 5's reference and value shorthands) drawn literally; KiCad's UnescapeString not applied to a string; an fp_text user's default thickness; back-side footprint text that KiCad 8 mirrors without '(justify mirror)'; face 'KiCad Font', which KiCad draws in its stroke font and the composer refuses as TrueType; a plot setting of 'plotfptext no'; KiCad 5's keep-upright range; private_layers. LEFT: CLAUDE.md's composer commands do not list --fetch-font (CLAUDE.md is OH-149's). Steps 2 to 4 remain; status stays in-progress.

**Note 2026-10-09:** 2026-10-09: STEP 1 MERGED to master by fast-forward at b65dc5e (lane2). Correction to the step-1 review-fix note above, which says only --fetch-font downloads: b65dc5e reverses that choice. A run of tools/compose_board_3d.py now fetches the font before composing, as it fetches KiCad's models, so a fresh checkout's plain run letters its boards; compose(), which tests call, still only reads it and SKIPS a KiCad board naming the fetch when the font is absent; --fetch-font fetches alone. Held by test_a_run_of_the_tool_fetches_the_font_before_it_composes (red with the fetch removed) and verified independently (PASS). Main recomposed with that run: it fetched the font and lettered every KiCad board (exit 0). CLAUDE.md's paragraph updated under OH-149 (b4e751e). REVIEW of step 1: an independent review (MERGE AFTER FIXES, licence ruled clean under rules/licence-hygiene.md) and its fix round (the missing-font tests skip, hand-derived layout tests, dimension text counted, PROVENANCE §2i, fetch robustness, hidden text keyed apart). VERIFIED on master at b4e751e: full suite 2 failed (the OCP pair), 2559 passed, 38 skipped; TWINS 26 of 38. Steps 2-4 (default-finish colours, the absent logo/module/test-point placements, the STM32C5) and the deferred text items above remain; status stays open.
