---
id: OH-190
title: The Uno's two MiniMELF diodes lie across their pads, and the diode test covers
  only manifest boards
status: in-progress
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-190-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Found by OH-186's review round (2026-09-30). The Arduino Uno's D2 and D3, drawn with a MiniMELF model at turn 90, lie across their pads: the model's band sits the same distance from pad A as from pad C. Neither the pad-span check nor the silkscreen check notices, so the composed Uno shows two diodes turned a quarter off their land with every check green.

OH-186 added a test that a diode's band (its most off-centre colour) lands nearer the pad named C than the one named A, and ran it on the manifest boards only. Run on the Uno it reports these two.

Find the turn the vendor's own file states for these parts, check it against their pads the way the manifest boards' diodes are now checked, and extend that test to every composed board so a diode drawn across its land fails on any of them. If the band reading cannot decide a MiniMELF (a cylinder whose band may be a thin stripe), say what reads it instead rather than widening a tolerance.

Done when the Uno's D2 and D3 lie along their pads with the band at the cathode, the diode test covers every composed board, and it fails on a diode deliberately turned 90.

**Note 2026-09-30:** From OH-186's approving review (2026-09-30), for the diode test this ticket extends: (1) it averages vertex positions unweighted and takes the furthest-off-centre colour with no margin over the second; one 3-vertex #ffffff triangle at the anode end made the wrong turn pass and the right turn fail. Require the band to beat the next colour by a stated margin (e.g. 2x) and fail with 'no band to read' otherwise; consider weighting by triangle area. MiniMELF is the thin case (0.62 vs 0.31 mm). (2) In a partial checkout the test fails instead of skipping (it asserts the KB2040's D1 was checked); skip per board like the rest of the file. (3) The reviewer reproduced the Uno's D2/D3: band 1.81 mm from both A and C.
