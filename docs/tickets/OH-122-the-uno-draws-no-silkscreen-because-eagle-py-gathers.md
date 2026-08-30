---
id: OH-122
title: The Uno draws no silkscreen because eagle.py gathers no strokes
status: done
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

## DONE, 2026-08-30

`eagle._ink` gathers every straight silkscreen wire into strokes: board-level
`<plain>` wires as they are, package wires through `place` with the element's
own spelling -- and a MIRRORED element's ink swaps to the other face, because
EAGLE's MR puts the whole package on the underside. What is not read is
counted by kind, the contract `kicad._silk_of` keeps.

The composed Uno went from `ink front 0, ink back 0` with no explanation to:

    ink front 401, ink back 4
    not ink arc 21, circle 5, rectangle 16, text 24

Part outlines and polarity marks draw; the DIP notch (an arc) and the
lettering (text) are counted, not silently dropped. Layer 51 (tDocu) stays
out on purpose: `_silk_extent` reads it for a BODY extent, but as ink it
holds courtyards a real board does not print.

The traceability test pins ZU4's body line against HAND-WORKED numbers --
64.897 = 46.355 + 18.542 -- rather than against `place`, which would agree
with itself however wrong it was. Four mutations (mirror kept on front,
transform dropped, arcs drawn as chords, plain ink dropped), all killed.

Gate 1,902 -> 1,905. Frame `.playwright-mcp/oh122-uno-ink.png`.
