---
id: OH-110
title: A composed board draws no copper and no silkscreen, so it is a slab with boxes
  on it
status: done
priority: P1
created: '2026-08-30'
touches:
- tools/kicad.py
- tools/eagle.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tests/rules/test_kicad.py
- CLAUDE.md
---

Asked for by the user, twice, in the same words both times: **"still poor 3d
model. fix them."** OH-100 through OH-109 answered that with parts -- the
RP2350's processor, eight slabs, two receptacles -- and the answer was always
one more box on the same bare slate. This is what was actually wrong.

## THE COMPARISON THAT SETTLES IT

Both of these are in `.playwright-mcp/`, shot at the same camera on the user's
own server:

    oh102-vendor-lm20a.png     XIAO-nRF54LM20A-DIP, the vendor's own KiCad
                               assembly export, IMPORTED
    oh102-composed-rp2350.png  XIAO-RP2350-DIP, COMPOSED by this tool

| | imported | composed |
|---|---|---|
| castellated half-holes | 28 barrels down both edges | none, a plain black edge |
| copper pads | under every component | none |
| silkscreen | outlines, and the letters R and B | none |
| what it reads as | a printed circuit board | a slate with boxes on it |

**Twelve of the twenty-five boards are composed and every one of them looked
like the right column.** That is not a modelling problem, it is three missing
layers.

## AND ALL THREE ARE IN THE FILE ALREADY PARSED

Counted 2026-08-30 with `tools/kicad.py`, which has read every one of these
for months and handed none of them on:

    board        pads   silk strokes on the board   text (not drawn)
    RP2350        316                            7                99
    ESP32-C6      279                          705                72
    ESP32-C3      211                         1597                47
    ESP32-C5      337                            6                74
    nRF54L15      362                          948                96
    Arduino Uno   308                            0     (EAGLE, none read)

The RP2350 and the C5 print almost nothing but text on the front; the C3 and
the nRF54L15 print hundreds of strokes. Both are the vendor's own answer and
neither is this tool's to improve.

## WHAT IT NEEDS THAT IS NOT THERE YET

  * **`kicad.Pad` carries no shape and no rotation.** 224 of the RP2350's 316
    pads are turned, and 253 of the 1,679 pads across the five composed XIAOs
    are round rather than rectangular. A pad drawn as an axis-aligned
    rectangle is the wrong shape more often than not.
  * **The stored rotation is ABSOLUTE**, which has to be measured rather than
    assumed: of the 20 pads in footprints placed at 90 degrees, all 20 say 90.
    Adding the placement's rotation to it turns every pad on a rotated part by
    twice the angle.
  * **Copper has to be cut to the board edge.** 44 of the RP2350's 316 pads
    cross the outline and 42 of them are castellations. Drawn whole they hang
    in the air beside the board, which is exactly what OH-101's wrong
    receptacle looked like.
  * **`tools/eagle.py` reads neither shape nor angle either**, so the Uno gets
    nothing without the same work on the other reader.

## DONE WHEN

Every composed board draws the copper and the ink its vendor drew; no copper
vertex lies outside the outline; and the two colours -- which a `.kicad_pcb`
does not state, because a surface finish is a fabrication order -- say they
are judgements, as `BOARD_MASK` does.

## NOT IN SCOPE, AND SAID SO

Traces and copper pours (the routing, not the lands); silkscreen TEXT, which
needs a font shipped; the arcs, circles and polygons on the silkscreen, which
are 2 to 16 per board and are counted in the caption; and the PCB artwork as a
raster texture, which is still blocked on the GPL question in
`rules/licence-hygiene.md`.

**Note 2026-08-30:** DONE in 86de055. Every composed board draws its vendor's copper and silkscreen. Pad rotation is ABSOLUTE in the file, measured rather than assumed; copper is clipped to the outline where it is convex and dropped-and-counted where it is not; eagle.py learned shapes and angles so the Uno draws its 400 pads. Found while checking: pad rings wind CCW and stroke rings CW, so the ink was back-facing -- flat() normalises now. Left out and printed: text (47-99 a board, needs a font), and 2-16 arcs/circles/polys.
