---
id: OH-190
title: The Uno's two MiniMELF diodes lie across their pads, and the diode test covers
  only manifest boards
status: done
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-190-*
---

Found by OH-186's review round (2026-09-30). The Arduino Uno's D2 and D3, drawn with a MiniMELF model at turn 90, lie across their pads: the model's band sits the same distance from pad A as from pad C. Neither the pad-span check nor the silkscreen check notices, so the composed Uno shows two diodes turned a quarter off their land with every check green.

OH-186 added a test that a diode's band (its most off-centre colour) lands nearer the pad named C than the one named A, and ran it on the manifest boards only. Run on the Uno it reports these two.

Find the turn the vendor's own file states for these parts, check it against their pads the way the manifest boards' diodes are now checked, and extend that test to every composed board so a diode drawn across its land fails on any of them. If the band reading cannot decide a MiniMELF (a cylinder whose band may be a thin stripe), say what reads it instead rather than widening a tolerance.

Done when the Uno's D2 and D3 lie along their pads with the band at the cathode, the diode test covers every composed board, and it fails on a diode deliberately turned 90.

**Note 2026-09-30:** From OH-186's approving review (2026-09-30), for the diode test this ticket extends: (1) it averages vertex positions unweighted and takes the furthest-off-centre colour with no margin over the second; one 3-vertex #ffffff triangle at the anode end made the wrong turn pass and the right turn fail. Require the band to beat the next colour by a stated margin (e.g. 2x) and fail with 'no band to read' otherwise; consider weighting by triangle area. MiniMELF is the thin case (0.62 vs 0.31 mm). (2) In a partial checkout the test fails instead of skipping (it asserts the KB2040's D1 was checked); skip per board like the rest of the file. (3) The reviewer reproduced the Uno's D2/D3: band 1.81 mm from both A and C.

**Note 2026-09-30:** 2026-09-30, lane2 (local, not merged): b237850. Arduino's MINIMELF package lays C at -x and A at +x along its own x, and KiCad's D_MiniMELF puts pad 1, the cathode, at -x: the row's turn is 0, not the 90 read off pads the element's rotation had already turned. D2 and D3 now lie along their pads, band 1.08 mm from C and 2.32 from A (1.81 from both before). The band test runs on every composed board, skipping by name what is not fetched (no KB2040 assertion): band = the colour whose AREA-weighted centroid is furthest off the model's centre, by BAND_MARGIN 2x over the next, among colours covering MIN_BAND_SHARE 1% of the surface, else 'no band to read'; placed, the band must be nearer one pad than the other by at least its own offset (a diode across its land is equidistant), and at C where the pads are named A/C. Weighted, every diode model here clears the margin by 8x or more (the MiniMELF's stripe 0.620 vs 0.078). Red on purpose: MiniMELF at 90 and SOD-323F at 90 ('lies across its land'), the Thing Plus's SOD-323 at 180 ('band at pad A'), a stray #ffffff triangle at the SOD-323F's anode end with the share rule removed ('no band to read'; with the rule it is ignored). Observed, not asserted: the XIAOs' DFN1006 bands sit at Seeed's pad 2 and the C3's SOD-523 at its '-' pad; neither vendor name says which is the cathode, so only 'along' is held there. No placement list changed; the Uno recomposed. Composer and importer rule files under miniconda: 218 passed.

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py passed on to OH-193.

**Note 2026-09-30:** 2026-09-30, review round (lane2, rebased on master): the note above says every diode model 'clears the margin by 8x or more'; the ratio is 8.0, which clears the 2x margin by 4x -- corrected here. Fixes: BAND_FLOOR, the band must sit at least 20% of the model's half-length off its centre (the margin cannot fire when the next colour sits exactly on the centre, and a MiniMELF with its stripe painted as glass read 0.019 mm of tessellation as its band); one colour clearing MIN_BAND_SHARE is 'no band to read' instead of an IndexError. The reading moved to _read_band; test_a_model_with_no_band_says_so builds one colour alone, end caps on the centre with the body 0.02 mm off (a ratio of infinity), and the same cylinder with a real stripe, which reads. Red on purpose: the floor removed, the count guard removed (IndexError), the real MiniMELF with its stripe painted as glass ('no band to read' on the Uno's D2). Composer and importer rule files under miniconda: 221 passed, 2 skipped.

**Note 2026-09-30:** 2026-09-30: approved by independent review over two rounds (before/after --check on all 17 boards; mutants; for OH-191 the stem table's cases, for OH-190 band offsets against the 20% floor on every drawn diode, for OH-193 both composer exits pinned). Merged to master by fast-forward (a83fa48); the Uno recomposed in the main checkout: 44 drawn, F1/Z1/Z2 refused by its schematic. Low-severity edges collected in OH-199.
