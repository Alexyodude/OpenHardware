---
id: OH-171
title: One board is called XIAO-XIAO STM32C5-SMD, with its prefix doubled, and the
  name is the key everything joins on
status: done
priority: P3
created: '2026-09-06'
touches:
- webui/boards/XIAO-*STM32C5-SMD.*
- webui/boards/catalogue.py
- tests/webui/test_board_catalogue.py
- README.md
- docs/research/board-models/README.md
- docs/research/board-models/sources.json
---

One board is called `XIAO-XIAO STM32C5-SMD`, with the prefix doubled and a space where every sibling has a hyphen.

Every other XIAO file is `XIAO-<part>-<footprint>`: `XIAO-ESP32-C3-SMD`, `XIAO-RP2350-DIP`, `XIAO-nRF54LM20A-SMD`. This one reads `XIAO-XIAO STM32C5-SMD`, so its part is recorded as `XIAO STM32C5` rather than `STM32C5`.

OH-26 flagged it on 2026-08-25 -- "webui/boards/XIAO-XIAO STM32C5-SMD.json has a doubled name prefix, likely an OH-25 import bug" -- and nobody has picked it up in the twelve days since. OH-170 met it again from the other end and is filing it rather than carrying it a third time.

It is not cosmetic. The name is the key everything joins on:

  the file          webui/boards/XIAO-XIAO STM32C5-SMD.json
  the artwork       webui/boards/XIAO-XIAO STM32C5-SMD.svg, named to match
  the JSON's own    "board": "XIAO-XIAO STM32C5-SMD"
  `catalogue.chip_for` parses the name after `XIAO-` to get the part, so this
                    board's chip is the string `XIAO STM32C5`
  the 3D model      `docs/research/board-models` records this as the one board
                    with no mesh; the index is keyed by the same name

So a rename touches the file, the SVG, the JSON field, whatever `catalogue` and `IRREGULAR` say about it, `webui/static/models/index.json`, and any test naming it. That is why this is a ticket rather than a `git mv`.

**What is NOT claimed: which name is right.** Seeed's own wiki calls the part the XIAO STM32C5 in prose. Whether the file should be `XIAO-STM32C5-SMD` -- consistent with its twenty-five siblings -- or whether the vendor really does name this one differently is a question for whoever fixes it, and the answer belongs beside the change. Renaming it to match the pattern and finding the vendor calls it something else would be trading one wrong name for another.

STEPS:

1. Establish what Seeed call it, from a source rather than from the pattern. The board has no wiki page that `tools/get_board_sources.py` can name and no board-support package anywhere, which is the same absence that leaves all 26 of its non-power pads unresolved (OH-170 step 3) and leaves it the only board with no 3D model. If nothing states the name, say so and rename for consistency with a note that the consistency is the only argument.

2. Rename the file, the SVG, and the `board` field together, and check `catalogue.chip_for` gives the part the rest of the catalogue expects.

3. Grep the tree for the old string. `tests/rules/test_import_pindefs.py` names it in `test_the_boards_with_no_source_are_deliberate`, and OH-170's own counting test asserts twenty-six files exist.

4. A test that no board file's name repeats its own prefix, so the next importer that does this is caught by the suite rather than by a reader twelve days later.

Found while finishing OH-170. Not fixed there: a rename is not a pin definition, and OH-170's claim is on the pin data.

**Note 2026-10-14:** 2026-10-14 starts in lane3. Plan: C:/Users/Alexyodude/scratch/oh171/plan.md (opus design pass, read-only). Seeed's own files give the name: footprint file XIAO-STM32C5-SMD.kicad_mod (only its line 1 declares 'XIAO-XIAO STM32C5-SMD'), symbol XIAO-STM32C5-SMD, product 'XIAO STM32C5 v1.0', board file 'XIAO STM32C5.kicad_pcb'. The key becomes XIAO-STM32C5-SMD; the vendor's declared string is kept as source.declared_name. Borrows from OH-163 (compose_board_3d, import_3d_model, test_compose_board_3d, test_import_board), from OH-172 (import_pindefs, test_import_pindefs, test_inventory), test_pin_view from OH-161 and CLAUDE.md from OH-149; claims the unclaimed board files, catalogue, its test, README and the board-models research files.

**Note 2026-10-14:** 2026-10-14, b631153: the XIAO STM32C5 is filed as XIAO-STM32C5-SMD (files, JSON board and image.file, catalogue, composer, 3D index, pindefs registry, tests, README). Seeed's doubled declaration is kept in source.declared_name; source.footprint is the file name as for the 25 siblings; the IRREGULAR row is gone; the test_import_board .replace() is gone. No importer change (it already names a board after the file). Fail first, seen before the rename: test_no_xiao_board_is_named_rather_than_parsed -> AssertionError: assert ['XIAO-XIAO STM32C5-SMD'] == []; test_no_board_file_repeats_its_own_prefix -> AssertionError: a board file repeats its own prefix: ['XIAO-XIAO STM32C5-SMD']. Both pass after. import_pindefs --write-boards reports the renamed file unchanged. Inventory TWINS unchanged: geometry 38, model 38, pins 38, runs 26. git grep XIAO-XIAO outside tickets/HANDOFF lists only vendor-string files. Also fixed CLAUDE.md and board-models README s5 stale sentences (OH-231). Loans from OH-163, OH-172, OH-161, OH-149 still to be returned.

**Note 2026-10-14:** 2026-10-14 DONE. Merged to master (lane3, b631153). Review APPROVE: no key left behind (every remaining XIAO-XIAO is the vendor's declared string); the JSON's declared_name is what import_board.py writes; chip_for gives STM32C5; both guard tests fail on eec69aa. With cores rebuilt in lane3: tests/webui + test_import_board + test_import_pindefs + test_inventory gave 1266 passed, 20 skipped, 1 failed (OH-166's test_a_failed_build_leaves_nothing_behind). TWINS unchanged: geometry 38, model 38, pins 38, runs 26. LOWs not done: the CLAUDE.md paragraph's line wrapping is uneven; the JSON has no source.file, like its import_kicad_board-era siblings. Loans returned: compose_board_3d, import_3d_model, test_compose_board_3d and test_import_board to OH-163; import_pindefs, test_import_pindefs and test_inventory to OH-172; test_pin_view to OH-161; CLAUDE.md to OH-149.
