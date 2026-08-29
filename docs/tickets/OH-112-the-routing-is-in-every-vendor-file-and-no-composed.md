---
id: OH-112
title: The routing is in every vendor file and no composed board draws a trace
status: done
priority: P1
created: '2026-08-30'
touches:
- tools/kicad.py
- tools/eagle.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- CLAUDE.md
---

Asked for by the user in one word: **"improve."** OH-110 gave every composed
board its pads and its silkscreen and left the space between them bare, which
is the last large piece of vendor data nobody draws.

## WHAT IS THERE

Counted 2026-08-30, per board:

    board          F.Cu   B.Cu   arcs   vias   inner   zones
    Arduino Uno     501    337      0     82       -       -
    ESP32-C5        428    259     15    307     190      18
    XIAO-RP2350     338    206      0    171     149      48
    nRF54L15        322    108      3    281     381      12
    ESP32-C6        313    242     43    146     148      17
    ESP32-C3        308     83      1    128      58      11

Both readers already walk the file that holds it. `tools/kicad.py` skipped
every top-level `segment`, `arc` and `via`; `tools/eagle.py` read
`<signals><signal>` for net NAMES and dropped its `<wire>` and `<via>` on the
floor.

## THE TRAP IN THE EAGLE FILE

**Layer 19 is `Unrouted`** and the Uno carries two wires on it. An airwire is
a connection the router has NOT made -- a straight line from pad to pad
through whatever is in the way. Drawn as copper it is indistinguishable from a
trace, and it is a trace that does not exist.

## A TRACE IS NOT A PAD

Exposed copper is metal; a trace is metal under a translucent film. The first
version blended the board's mask 30% toward `COPPER` and the Arduino Uno
rendered with SILVER tracery on a blue board -- copper's blue channel is 83
and the Uno's navy mask's is 99, so the blend pulled blue down while pushing
red and green up, and rgb(49,61,99) came out rgb(94,91,94), a neutral grey.

The right model is that the film has filtered the light both ways and what
changed is what is behind it: **the mask's own hue, lifted**. rgb(49,61,99)
becomes rgb(76,95,153), which is what an Arduino's routing looks like.

## DONE WHEN

Every composed board draws its outer-layer routing and its vias, on both
faces; a trace is drawn UNDER the pads it runs into, because a pad is what a
reader is looking for; curved track is flattened rather than dropped; and what
is not drawn is counted and printed.

## NOT IN SCOPE

**Inner copper**, 58 to 381 segments a board, which is inside the laminate
where nothing can see it. **A zone's filled polygon** -- 11 to 48 zones a
board, up to 26,368 points across the RP2350's 95 polygons, each a keyhole
outline that walks into every thermal relief and back out again. Ear-clipping
a polygon with coincident edges is a different problem from ear-clipping a
board outline, and a ground pour under mask is a shade rather than a shape.

**Note 2026-08-30:** DONE in 99945af. Outer-layer track, curved track and vias, from both readers, on both faces, clipped to the outline and drawn UNDER the pads. A trace takes its board's own mask colour LIFTED rather than blended toward copper -- the blend greyed the Uno's navy, which is how the wrong model was caught. EAGLE layer 19 (Unrouted) excluded: the Uno has two airwires. Not drawn and counted: inner copper 58-381 a board, and zone fills up to 26,368 points.
