---
id: OH-124
title: The pin-1 reader knows one marker spelling and the vendors used five
status: done
priority: P2
created: '2026-08-30'
touches:
- tools/kicad.py
- tools/eagle.py
- tests/rules/test_kicad.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

_No description yet._

CLAIMS NOTHING yet; re-claims tools/kicad.py and tools/eagle.py when it
starts. From the 2026-08-30 model survey; extends OH-106 (done).

`kicad._mark_of` reads only `fp_circle` on `*.Fab`; `eagle._silk_mark` only
curved wires and circles on silk. The survey dumped all 15 "nothing here can
see" placements and found the vendors drew markers in four other spellings:

    fp_circle on F.SilkS   C3 U4 and C6 U4 -- THE ESP32 PROCESSORS, corner
                           dot 3.95 mm off origin, one layer from the reader
    fp_poly on F.Fab       C3 CHG0, C3 U2/U1 (SOT-25s)
    fp_poly on F.SilkS     C3 D1 (SOD-523), C3 ANT0 / C6 ANT2 (U.FL)
    fp_arc on F.SilkS      C3 CHG0, offset fraction 1.748 vs the 0.15 floor

Worse: `kicad._body_of` reads only fp_line/fp_rect/fp_poly on `*.Fab`, and C3
U4, C6 U4, D1, ANT0, ANT2 have NONE -- body None disables `silk_miss` AND
`mark_of`, so **the C3's and C6's own processors have no turn check of any
kind**. On the Uno, PANASONIC_D's polarity wire and SOT223's eight asymmetric
layer-51 rectangles are likewise unread.

DONE WHEN _mark_of also reads fp_poly and fp_arc, and F.SilkS where *.Fab is
silent; _body_of learns the same fallback; MARK_OFFSET_FRACTION stays the
safety rail; and the composer's per-board "turn N placement(s)" count drops,
with the C3/C6 processors checked by name in a test.

---

**CLOSED 2026-08-30, and the first thing the widened reader did was catch a
real quarter turn.**

`kicad._mark_of` now reads, per layer, circles first, then polys, then arcs
-- a circle is the unambiguous dot; a poly on Fab may equally be the body,
whose centroid sits at the centre and is REJECTED by the offset floor
rather than mistaken for a corner mark -- and consults `*.SilkS` only where
`*.Fab` yields nothing. `_body_of` learned the same fallback with the
preference INVERTED on silk (lines over closed shapes), because a silk
fp_poly in these libraries is a polarity mark and a 0.3 mm triangle taken
as the body would misstate the extent every offset divides by.

**The catch**: the C3's U4 -- its own processor, checkable for the first
time -- REFUSED. The vendor draws the QFN32G footprint with pad 1 entering
on a different edge than the C6's one-letter sibling (pad 1 local
(-1.75, 2.45) vs (-2.45, -1.75), axes swapped) and compensates in the
placement (-90 vs 0), so the C3's pairing needs `turn=90` where the C6's
needs none: turn 0 put the model's feature 4.621 mm from the vendor's dot
and 90 puts it 1.540, a ten-fold-margin win. The composed C3 had shown its
processor a quarter turn wrong since OH-93, invisible to a span, a centre
and a silk box alike. `COMPOSITIONS` carries the turn with this evidence.

**And a third case the margin rule had never met**: the U.FL antennas'
marks pass the offset floor (fraction 0.159), but the connector's nearly
four-fold-symmetric mesh puts every turn within 0.006 mm of every other.
OH-106's six packages all decided by 1.6 mm or more, so "not a decisive
win" and "a rival won" were one condition; they are now split -- a rival
winning by TURN_MARGIN_MM still refuses, nobody winning counts the part
UNSEEN with the reason in the comment. Two tests updated to the same rule,
each saying why.

**Counts, measured by `--check` before and after**: C3 turn 6 -> 5 (U4
decided; ANT0 moved to ambiguous), C6 4 -> 3 (U4 decided), C5 3,
nRF54l15 2, RP2350 0, all exit 0. The four still unseen on the C3
(CHG0/D1/U2/U1) are the floor doing its stated job: their poly centroids
land within 8.3% of centre -- measured 0.046-0.083 against the 0.15 floor
-- and a centred candidate carries no corner information.

The eagle half of the survey's findings (PANASONIC_D's polarity wire,
SOT223's layer-51 rectangles on the Uno) is recorded here and NOT built:
the DONE WHEN names the kicad readers, and the Uno's turn count is already
served by contact and silk checks.

Tests: the four spellings synthetic (hand-worked centroids), the
rank-keeper (Fab beats silk, dot beats poly -- with a body poly placed to
LOSE), and the C3/C6 processors by name against literals measured out of
the vendor files. Six mutations, all killed. tests/rules/test_kicad.py
42 -> 45; compose suite 170 green after the two rule updates.
