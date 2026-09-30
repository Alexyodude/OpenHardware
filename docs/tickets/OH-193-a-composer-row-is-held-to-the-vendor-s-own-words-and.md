---
id: OH-193
title: A composer row is held to the vendor's own words, and the manifest boards are
  composed under test
status: in-review
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
