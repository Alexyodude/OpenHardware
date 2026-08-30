---
id: OH-122
title: The Uno draws no silkscreen because eagle.py gathers no strokes
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims tools/eagle.py when it starts.

**From the 2026-08-30 model survey.** `eagle.read_board` constructs `Board`
with no `silk=` and no `silk_unread=`; both default to empty. So the composed
Uno prints `ink front 0, ink back 0` -- with no `not ink` line either --
while the XIAOs draw 81-1518 strokes a face. Counted in Arduino's own file:
428 layer-21 wires on placed packages plus 4 board-level, 16 rectangles, 5
circles. **Straight strokes -- no font needed.** The most recognisable board
here is the only composed one with no white ink at all: no part outlines, no
polarity marks, no "ARDUINO".

OH-110 recorded exactly this ("Arduino Uno 308 / 0 (EAGLE, none read)") and
scoped it out; its NOT IN SCOPE names TEXT and curves, not lines.

DONE WHEN eagle.py gathers layer 21/22 wires into Strokes the way
kicad._silk_of does -- transformed per element the way its pads already are
-- the unread remainder is counted, and the composed Uno draws its part
outlines. compose.artwork should need no change.
