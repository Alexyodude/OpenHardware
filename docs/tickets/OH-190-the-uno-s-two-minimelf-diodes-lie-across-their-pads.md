---
id: OH-190
title: The Uno's two MiniMELF diodes lie across their pads, and the diode test covers
  only manifest boards
status: open
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-190-*
---

Found by OH-186's review round (2026-09-30). The Arduino Uno's D2 and D3, drawn with a MiniMELF model at turn 90, lie across their pads: the model's band sits the same distance from pad A as from pad C. Neither the pad-span check nor the silkscreen check notices, so the composed Uno shows two diodes turned a quarter off their land with every check green.

OH-186 added a test that a diode's band (its most off-centre colour) lands nearer the pad named C than the one named A, and ran it on the manifest boards only. Run on the Uno it reports these two.

Find the turn the vendor's own file states for these parts, check it against their pads the way the manifest boards' diodes are now checked, and extend that test to every composed board so a diode drawn across its land fails on any of them. If the band reading cannot decide a MiniMELF (a cylinder whose band may be a thin stripe), say what reads it instead rather than widening a tolerance.

Done when the Uno's D2 and D3 lie along their pads with the band at the cathode, the diode test covers every composed board, and it fails on a diode deliberately turned 90.
