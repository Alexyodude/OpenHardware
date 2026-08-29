---
id: OH-105
title: Every composed USB-C is a quarter turn out, and the outline that would have caught it is polluted
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/kicad.py
- tools/compose_board_3d.py
- tests/rules/test_kicad.py
- tests/rules/test_compose_board_3d.py
---

Reported by the user: "the usb plug is orientated in the wrong way."

**It is, on all four composed boards, and it is 90 degrees and not 180.** The
connector lies with its WIDTH pointing off the board edge and its depth along
it -- so a cable would go in sideways.

## MEASURED

A USB-C receptacle is 8.95 mm wide by the standard that lets any cable enter
any socket, and Seeed's part is 7.37 mm deep -- `L7.35` in the part number they
write into their own board file, `USB-31C-F-16P-L7.35`. Their own `F.Fab`
assembly rectangle says the same on three boards independently:

    XIAO-ESP32-C6-DIP    7.341 x 8.992 mm
    XIAO-RP2350-DIP      7.370 x 8.950
    XIAO-nRF54l15-DIP    7.370 x 8.950

So the 8.95 belongs ALONG the edge and the 7.37 across it. What is drawn:

    board                placed off the edge   along the edge
    XIAO-ESP32-C3-DIP           8.940              7.780
    XIAO-ESP32-C6-DIP           8.940              7.780
    XIAO-RP2350-DIP             9.200             10.500
    XIAO-nRF54l15-DIP           9.200             10.500

Both models carry their width on their own local x, so both need a quarter
turn. Which quarter is settled by the MOUTH -- it has to face off the board so
a cable can reach it -- measured as the triangle area lying in each end plane,
because an open end is a rim and a closed one is a filled face:

    GCT USB4105        turn  90   inner 4.26  outer 0.38 mm2   mouth OUT
    Amphenol 12401610  turn 270   inner 14.89 outer 4.24 mm2   mouth OUT

Both are `turn=0` today.

## WHY NOTHING CAUGHT IT

  * **`confirm` came within half a millimetre.** It compares the model's span
    against the pad span IN ORDER, exactly so that a 90-degree error cannot
    hide -- the comment says so, quoting the Uno's headers. Turned wrongly the
    GCT spans 7.780 against a 10.240 mm land: 2.46 mm short, against a
    `SPAN_TOLERANCE_MM` of 3.0. It passed by 0.54 mm.
  * **`silk_miss` was comparing against the wrong outline.** The C6 and the
    nRF54L15 draw TWO things on `F.Fab`: the body rectangle, and four loose
    `fp_line`s forming a 1.651 x 12.5 mm box behind the connector -- a cable
    keep-out. `kicad._body_of` unions everything on the layer, so those two
    boards reported a 12.5 mm body and every comparison against it was
    meaningless. The RP2350 draws only the rectangle, which is why its number
    was the right one.
  * **`BODY_ALLOWANCE_MM`, added yesterday by OH-103, then excused the
    result.** It was measured against the polluted outline, so it granted 2.0
    and 2.2 mm on exactly the part that was wrong. That is the hazard of an
    allowance and it landed on its first outing.

## THE FIX HAS TWO HALVES

  * `_body_of` prefers a closed outline -- `fp_rect` or `fp_poly` -- and falls
    back to loose lines only where a footprint draws no closed one. A body is
    a shape; a stray line on the same layer is an annotation.
  * `CORRESPONDENCE` gives the GCT `turn=90` and the Amphenol `turn=270`.

With the outline read correctly the allowance should shrink or go entirely,
and whatever remains is the OH-102 length error rather than a rotation.

## DONE WHEN

All four boards draw a receptacle whose mouth faces off the board edge and
whose 8.95 mm width lies along it; the mouth direction is a test rather than a
measurement somebody ran once; and `BODY_ALLOWANCE_MM` holds only what a
correctly-read body outline still cannot explain.

## DONE, 2026-08-29

`USB2.0-TYPE-C` takes `turn=90` and `USB2.0-TYPE-C_USB-31C-F-16P` takes
`turn=270`. All four boards now place the receptacle's width along the board
edge with its mouth facing off it.

    board                 off the edge   along the edge   vendor F.Fab
    XIAO-ESP32-C3-DIP         7.780          8.940        (draws none)
    XIAO-ESP32-C6-DIP         7.780          8.940        7.341 x 8.992
    XIAO-RP2350-DIP          10.500          9.200        7.370 x 8.950
    XIAO-nRF54l15-DIP        10.500          9.200        7.370 x 8.950

The along-edge figure is what matters and it now matches the vendor to 0.05 mm
on the C6 and 0.25 on the other two. The off-edge excess on the Amphenol
boards is OH-102's length error, unchanged by this.

### AND THE CONTACTS CAME BACK ONTO THE BOARD

Worst gold vertex outside the PCB outline, before and after:

    Arduino Uno          0.000  ->  -2.093 mm
    XIAO-ESP32-C3-DIP    0.000  ->  -0.372
    XIAO-ESP32-C6-DIP    0.000  ->  -0.152
    XIAO-RP2350-DIP     +0.164  ->  +0.164
    XIAO-nRF54l15-DIP   +0.206  ->  +0.271

Negative is inside. Two boards that used to touch the edge exactly now have a
quarter of a millimetre of margin.

### `_body_of` PREFERS A CLOSED OUTLINE

Seeed draw the body as an `fp_rect` and, on two boards, four loose `fp_line`s
forming a 1.651 x 12.5 mm cable keep-out on the same layer. Unioning them
reported a 12.5 mm body and made every comparison against it meaningless.
Rectangles and polygons win; lines are read only where a footprint draws no
closed outline, which is how a chamfered body is drawn.

**`BODY_ALLOWANCE_MM` was measured against the polluted outline** and was
therefore excusing the very part that was wrong -- the hazard of an allowance,
landing on its first outing. Both numbers are re-measured.

### WHAT NOTHING STILL SEES

A mutation turning the Uno's `DIL28-3` from 90 to 270 survives. A DIP's body
and pins are symmetric under 180 degrees, so the only thing that moves is the
pin-1 notch, and no check reads it -- `silk_miss` compares body CENTRES, which
a half turn preserves. That is a pre-existing gap of the same shape as this
ticket and it is filed as OH-106 rather than fixed here.

8 mutations, 7 killed, the eighth being that. 5 new tests. Gate: 1,804 ->
1,808 passed, 17 skipped; all eight checkers exit 0.
