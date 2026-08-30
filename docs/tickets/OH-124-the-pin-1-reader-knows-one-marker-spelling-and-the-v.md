---
id: OH-124
title: The pin-1 reader knows one marker spelling and the vendors used five
status: open
priority: P2
created: '2026-08-30'
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
