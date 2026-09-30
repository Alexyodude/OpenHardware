---
id: OH-193
title: A composer row is held to the vendor's own words, and the manifest boards are
  composed under test
status: done
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-193-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Found by OH-189's review (2026-09-30). Three mutations of the composer's table each compose cleanly and pass the whole suite, putting a false part on a board:

- the ESP32-C3-MINI-1 row pointed at the ESP32-C6-MINI-1 model and footprint;
- the JST04_1MM_VERT row pointed at KiCad's horizontal SM04B model;
- the Pocket's underside module row given flip=True, so the module is drawn on top of the board.

Two gaps let them through. Nothing compares a row's model name with what the vendor's own package and value words state (VERT, a module's chip, a lead count), and no test composes the manifest boards at all: the composer's own turn and silkscreen refusals (a C3-MINI-1 turned 180 misses the vendor's body drawing by 5.23 mm and the composer exits) never run under pytest.

Hold a row to the vendor's words where the words state something checkable, with a closed, pinned vocabulary (orientation words, a module's chip name, a stated lead count), and refuse a row that contradicts them. Compose the manifest boards in the test suite where the inputs and OCP are present, and skip naming what is missing where they are not, so the composer's own refusals reach CI's view.

Done when each of the three mutations above fails a test.

**Note 2026-09-30:** 2026-09-30, lane2 (local, not merged): 534da1b. contradiction(element, row): where the vendor's package name or value states an orientation (tokens VERT, VERTICAL, RA, HORIZONTAL), a chip (ESP32-C3, -C5, -C6, -H2, -S2, -S3, RP2040, RP2350) or a lead count (QFN/MLF/DFN/SON n, SOT23-n, MSOPn, DILn, two-digit 1Xnn/2Xnn headers), the row's model name and a manufacturer's STEP and footprint file names must not state otherwise; the vocabularies are closed and pinned by a test. compose() exits on a contradiction, and on a placed part whose height puts it on the other side of the board's mid-plane from the one its mirrored element or its row's flip says (underside parts measured at -0.97 mm or lower, topside at +0.57 or higher, on every board). Of 951 drawn placements across all 17 composed boards, 56 are held to an orientation, a chip or a count, and none contradicts. test_the_manifest_boards_compose_under_test composes each manifest board (check only) wherever its files, every model it draws and OCP are present, naming what is missing otherwise (about 12 s here); the composer's exits become failures. The ticket's three mutations, each applied to the source and the whole composer test file run: C3-MINI-1 row -> C6 model and footprint fails test_every_row_agrees_with_its_vendors_words and the composing test; JST04_1MM_VERT -> horizontal SM04B fails both; the Pocket's module row flip=True fails the composing test. Unit cases red on purpose for each vocabulary (VERT vs Horizontal, RA vs Vertical, a C3 package with C6 files, a C3 value under a PICO-MINI package, QFN56 vs a 60-lead name, 2X03 vs 2x04; a 2X2MM body read as no header). Every board's --check output unchanged. Composer and importer rule files under miniconda: 221 passed. Full default suite in lane2: 2369 passed, 37 skipped, 2 failed -- the OCP pair. tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py return to OH-163 when this closes.

**Note 2026-09-30:** 2026-09-30: review round. lane2 rebased onto master (OH-192). The composer and its tests go to OH-191, then OH-190, for their fixes, and come back here for this ticket's.

**Note 2026-09-30:** 2026-09-30, review round (lane2, rebased on master with OH-192): e6e501f. (6) test_compose_refuses_a_row_its_vendors_words_contradict drives compose() on the Pro Micro with its vertical land on KiCad's horizontal SM04B (the exit fires before any model is read, so no OCP), and test_compose_refuses_a_flip_on_a_mirrored_element drives it on the Pocket with a box for its module, unflipped (composes) and flipped (exits 'a flip on a mirrored element turns it back over'); each fails with its exit deleted. (7) The side guard is described as what it is: place() turns a part under the board for a mirrored element or a flipped row, each a half turn, so both together put it back on top, which is the case it refuses. (8) A lead count is at most three digits and not followed by a digit, an X or a point, vendor and model side alike: DFN1006-2L and QFN-3X3 state no count (test_a_body_code_is_not_a_lead_count, red with the old pattern). (9) The Glyph Mini, refused by name after the rebase, is reported with MANIFEST_REFUSED's reason and no longer makes the composing or the bodyless test skip as if unfetched. The ticket's three mutations re-run after the round: each still fails a test. Every board's drawn list unchanged; the Uno recomposed. Composer and importer rule files under miniconda: 226 passed. Full default suite in lane2: 2388 passed, 37 skipped, 2 failed -- the OCP pair. tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py return to OH-163 when this closes.

**Note 2026-09-30:** 2026-09-30: approved by independent review over two rounds (before/after --check on all 17 boards; mutants; for OH-191 the stem table's cases, for OH-190 band offsets against the 20% floor on every drawn diode, for OH-193 both composer exits pinned). Merged to master by fast-forward (a83fa48); the Uno recomposed in the main checkout: 44 drawn, F1/Z1/Z2 refused by its schematic. Low-severity edges collected in OH-199.
