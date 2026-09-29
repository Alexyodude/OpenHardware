---
id: OH-186
title: 'Every manifest row is composed by construction: the KB2040 made whole, and
  the importer''s list derived rather than hand-kept'
status: in-review
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-186-*
- tools/import_3d_model.py
---

Part of OH-174. MASTER IS RED ON TWO TESTS BECAUSE OF THIS. Since OH-180 every manifest row is composed by construction, and OH-181 added the Adafruit KB2040 row, so the composer now composes it while `import_3d_model.COMPOSED` and the composer tests' `EXPLAINS` do not name it: test_the_two_lists_of_composed_boards_agree and test_each_board_explains_the_parts_it_leaves_off fail on master at 9f60dfd. Its model cell reads `footprint:no source`. Its vendor publishes an EAGLE `.brd` (CC BY-SA 3.0, fetched by the registry), which is the case the composer already handles for three manifest boards and the Uno.



Compose it from its own board file, centred on its manifest row's header elements, every part drawn from a published model or refused with a reason, its mask colour read from the file or marked a judgement, as OH-180 did. Whether a published model matches the RP2040's package on this land is for the composer's existing rules to answer, not for this ticket to assume.



Make `import_3d_model.COMPOSED` stop needing a hand edit for every manifest row: derive the manifest rows' entries from `tools/board_manifest.py`, so adding a row is adding a row; the hand-kept copy is what made this merge red. The KB2040's omissions are stated in `EXPLAINS` like every other composed board's, after reading what it actually leaves off.



Done when both tests pass, the KB2040's model cell reads composed, its drawn and refused lists are printed, and pin 1 of each turned part is checked against the vendor's marker as for the other composed boards.

**Note 2026-09-30:** 2026-09-30, lane3 (local, not merged): 627e900 derives the manifest rows' COMPOSED entries from board_manifest.ROWS (every .brd row, the row's chip, the composer's slug), so a row needs no edit in tools/import_3d_model.py; the hand-kept tuple holds the XIAOs and the Uno. test_the_two_lists_of_composed_boards_agree compares two independent derivations and was made to fail once (the importer's slug spelled with underscores). bc829f7 composes the KB2040: drawn 36, refused 2 (X6 USB_C_CUSB31-CFM2AX-01-X, LED1 SK6805_1515, both as on the QT Py), bodyless 6 (JP1/JP2 1X13_CASTEL, SJ1, TP1, two fiducials). IC2 is QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm by the exposed-pad rule (the land's pad is 3.2 mm), U5 DFN-8-1EP_4x4mm_P0.8mm_EP2.5x3.6mm by the same rule with a stated JUDGEMENT on height (USON names the ultra-thin class, the model is 0.92 mm); pin 1 of both is confirmed by the vendor's dot, the other turned parts are counted in the composer's own unseen line. New test_every_composed_boards_placements_are_drawn_or_explained failed on the KB2040's eleven orphans before the rows. test_the_rp2350_is_drawn_and_the_near_miss_is_still_refused forbade any QFN-56 model; it now checks a QFN/DFN/SON model's lead count plus its exposed pad equals the land's pads on every fetched board (half of OH-184's review item 2), made to fail once with a QFN-60 name on the KB2040's land. Composer and importer rule files under miniconda: 204 passed. TWINS: model 28 -> 29, the KB2040 reads composed (runs still RP2040:no). The KB2040's passives are drawn by package as the other Adafruit boards' are (R1-R12 as C_0402, C15 as R_0603, R8 FUSE as C_0805): OH-187. lane3's third_party/adafruit-kb2040 lacked the .sch the registry now wants; get_board_sources.py fetched it. check_facts reads COMPOSED's literal by ast and now sees the hand-kept part only (OH-149's file, not edited).

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py lent to OH-187 (passives drawn as the wrong kind), which follows this ticket on lane3 and edits both; a review change to them here goes through OH-187's claim. tools/import_3d_model.py stays with this ticket. All three return to OH-163 when OH-187 closes, per OH-163's own note.

**Note 2026-09-30:** 2026-09-30, review round (lane3): 3b00c54 refuses U5 (USON8_4X4 in ABSENT: USON names the ultra-thin class, KiCad's two 4 x 4 mm eight-lead parts are 0.92 and 0.82 mm; the name states no height) and adds it to the KB2040's EXPLAINS, which fails without the ABSENT entry; the KB2040 draws 35, refuses 3. fe07dd9: MODELS and COMPOSED asserted disjoint and held in webui/boards/ on the imported values (the KB2040 added to MODELS' RP2040 fails it); the importer's .brd filter pinned by loading it afresh over a KiCad row and an EAGLE row (deleting the filter fails it); a manifest board's diode lands its model's band nearer pad C than pad A (SOD-323F at turn 0 fails it on D3). mark_of was not widened: telling a cathode bar from an outline stroke is a new judgement, and the test decides the turn from the vendor's pad names and the model's own band instead. 91fe177: shared rows and reasons describe their land rather than their boards, SOD-323_MINI named right, the counts cut from mark_turns and half_turn_moves. FOUND, NOT FIXED (the Uno is not this ticket's board): the same band test run on the Uno puts D2 and D3 (MINIMELF, turn=90) ACROSS their pads -- pads 3.40 mm apart along the board's y, the 3.6 mm MiniMELF along x, the band equidistant from A and C; confirm's 3 mm tolerance and silk_miss both pass it. The Uno's D1 (SMB) is right. Composer suite under miniconda: 152 passed.

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py lent to OH-187 again for its review round.

**Note 2026-09-30:** 2026-09-30: of review item 5, the counts cut from mark_turns' docstring are restored under OH-187 (f576810): check_facts anchors CLAUDE.md's pin-1 paragraph to that function's source, and re-confirming the anchor writes OH-149's tools/facts_store.json. half_turn_moves keeps its cut. For OH-149's owner: re-read CLAUDE.md's 'Six packages qualify' paragraph against mark_turns, then cut the docstring's counts and --confirm claude-md:mark-turns.
