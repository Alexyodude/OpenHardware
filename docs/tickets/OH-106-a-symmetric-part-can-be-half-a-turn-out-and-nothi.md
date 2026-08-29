---
id: OH-106
title: A symmetric part can be half a turn out and nothing sees it
status: done
priority: P2
created: '2026-08-29'
---

CLAIMS NOTHING. Found by OH-105's mutation run, which is the only reason
anybody looked.

**`silk_miss` compares body CENTRES, and a 180-degree turn preserves a
centre.** So the check whose docstring says it "knows which way a part faces"
cannot see a half turn on any part whose body is symmetric about its own
anchor -- which is most of them.

Measured on the four composed XIAOs while OH-105 was open: the USB-C
receptacle reports the SAME miss at 0 and at 180 on every board.

    XIAO-ESP32-C6-DIP    turn   0   2.005 mm      turn 180   2.005 mm
    XIAO-RP2350-DIP      turn   0   1.448         turn 180   1.448
    XIAO-nRF54l15-DIP    turn   0   1.868         turn 180   1.868

A mutation turning the Arduino Uno's `DIL28-3` from 90 to 270 survives the
whole suite for the same reason.

## WHY IT MATTERED LESS THAN IT SOUNDS, UNTIL IT DID NOT

The Uno's barrel jack IS caught, because a barrel is entirely to one side of
its pins -- that asymmetry is what `silk_miss` was written against, and its
comment says so. What it cannot catch is the symmetric majority, and OH-105
found a real 90-degree error on four boards that every existing check passed.

## WHAT WOULD ACTUALLY SEE IT

A half turn moves features, not extents. Three candidates, cheapest first:

  * **The pin-1 marker.** OH-100 already reads Seeed's `fp_circle` on `F.Fab`
    for the RP2350's QFN and asserts its corner. Most footprints draw one, and
    KiCad's own models carry a matching dot or notch -- so the two could be
    compared rather than each trusted alone.
  * **The open end**, for a connector. OH-105 measures triangle area in each
    end plane -- an open mouth is a rim and a closed back is a filled face,
    0.38 mm2 against 4.26 -- and asserts the mouth faces off the board. That
    is specific to sockets and already written.
  * **Pad 1 against the model's own first lead**, which is general and needs
    the model's pad numbering, which KiCad's STEP files do not carry.

## DONE WHEN

A half turn on a symmetric part fails something; the two checks OH-100 and
OH-105 already wrote by hand are the general rule rather than two one-offs;
and the `DIL28-3` mutation dies.

## DONE, 2026-08-30, in e97e369

`mark_turns` reads the vendor's own pin-1 marker and asks where the model's
own asymmetric feature lands. The `DIL28-3` mutation dies, killed by three
tests including the composer's own refusal path.

**The ticket understated the problem and the measurement is worth keeping.**
It is not only symmetric parts: TWENTY placements moved under a half turn with
nothing able to see it, across eight packages, and `contact_miss` returned
`None` for every part on every board except the USB-C.

**And it overstated it too, which turned out to be the more useful half.** A
half turn that moves nothing is not a claim that can be wrong. Measured with
`place` itself rather than a model of what a turn does, **23 of the 43
packages placed do not move at all** -- every pin header, every 0201 chip
part. So the fix is not "make every turn checkable" but "measure whether there
is anything to check, then check what is left".

    moves under a half turn, and                 before   after
      the contacts decide it                          1       1
      the vendor's marker decides it                  0       6
      silk_miss would refuse the half turn            2       2
      NOTHING would                                  20      18

## THE MARKER IS THE VENDOR'S, IN BOTH CAD FORMATS

  * EAGLE spells it as a wire with a `curve` -- Arduino draw the DIP notch at
    x -18.542, the end their own pad 1 is at -- or as a `<circle>`, which is
    how their `MLF32` marks the corner.
  * KiCad spells it as an `fp_circle` on `F.Fab`. That is the same shape
    `tools/model_from_datasheet.py` already reads to decide which corner of a
    modelled QFN is pin 1, so OH-100's one-off became the general rule rather
    than being copied.

Against it goes the model's own asymmetric feature, found by asking which of
its vertices a half turn moves and where they are. **The feature is never
named and does not need to be**: on the DIP-28 it is 1.5 x 0.8 mm of `#050505`
notched into the top of the body, and the rule would hold as well for a bevel
or a dimple. Six packages qualify and the smallest margin is 1.6 mm against a
`TURN_MARGIN_MM` of 0.3.

## CURVATURE IS NOT A MARKER, AND THE COUNTER-EXAMPLES ARE ON THE SAME BOARD

`PANASONIC_D` draws an electrolytic can as two arcs whose centroid is the
package origin to 0.000 mm, and `TS42` draws a button as two concentric
circles at 0.021 of its size. Read as markers they would refuse a correct
turn. Real markers sit at 0.441 to 0.641 of their package's size off centre,
so `MARK_OFFSET_FRACTION = 0.15` is loose against both sides of a gap that was
measured rather than picked.

## WHAT IS STILL UNSEEN IS COUNTED AND PRINTED

Eighteen placements across eight packages -- `LED-0402`, `U-FL3P`, `SOT-25`,
`SOD-523`, `QFN32`, `QFN32G`, `SOT223`, `PANASONIC_D` -- and the RP2350 has
none. Printed per board for the reason `Board.silk_unread` is.

**The count asks whether an existing check would REFUSE the half turn**, not
whether some number changes. The barrel jack moves its silk miss from 0.013 to
7.496 mm and the USB-B from 0.400 to 8.860, so both are seen and neither is
counted -- counting them would have overstated the gap by the two parts this
family of checks was originally written for.

## NOT DONE

The eight packages above draw no marker in either vendor's file, so nothing
here can decide their turn and the count says so rather than the tool staying
quiet. The QFN32 is the interesting one: its SIBLINGS QFN48 and QFN60 carry an
`fp_circle` and it does not.

Gate 1,858 -> 1,868 passed, 17 skipped. Nine mutations, all killed. All six
meshes rebuild byte-identical -- this checks what is drawn and moves nothing.
