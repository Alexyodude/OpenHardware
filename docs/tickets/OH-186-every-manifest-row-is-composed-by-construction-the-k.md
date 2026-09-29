---
id: OH-186
title: 'Every manifest row is composed by construction: the KB2040 made whole, and
  the importer''s list derived rather than hand-kept'
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-186-*
---

Part of OH-174. MASTER IS RED ON TWO TESTS BECAUSE OF THIS. Since OH-180 every manifest row is composed by construction, and OH-181 added the Adafruit KB2040 row, so the composer now composes it while `import_3d_model.COMPOSED` and the composer tests' `EXPLAINS` do not name it: test_the_two_lists_of_composed_boards_agree and test_each_board_explains_the_parts_it_leaves_off fail on master at 9f60dfd. Its model cell reads `footprint:no source`. Its vendor publishes an EAGLE `.brd` (CC BY-SA 3.0, fetched by the registry), which is the case the composer already handles for three manifest boards and the Uno.

Compose it from its own board file, centred on its manifest row's header elements, every part drawn from a published model or refused with a reason, its mask colour read from the file or marked a judgement, as OH-180 did. Whether a published model matches the RP2040's package on this land is for the composer's existing rules to answer, not for this ticket to assume.

Make `import_3d_model.COMPOSED` stop needing a hand edit for every manifest row: derive the manifest rows' entries from `tools/board_manifest.py`, so adding a row is adding a row; the hand-kept copy is what made this merge red. The KB2040's omissions are stated in `EXPLAINS` like every other composed board's, after reading what it actually leaves off.

Done when both tests pass, the KB2040's model cell reads composed, its drawn and refused lists are printed, and pin 1 of each turned part is checked against the vendor's marker as for the other composed boards.
