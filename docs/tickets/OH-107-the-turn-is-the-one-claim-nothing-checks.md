---
id: OH-107
title: The turn is the one correspondence claim nothing checks
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Reported by the user, twice: "still wrong usb c orientation. fix it and fix
root cause."

They are right on both counts. **The USB-C is still wrong** -- it wants 270
and OH-105 gave it 90 -- and the reason it took three attempts is the root
cause: `Component.turn` is the only claim in `CORRESPONDENCE` that nothing
measures.

## THE ROOT CAUSE

Every other judgement in that table is verified against the vendor's own data:

    the MODEL is right      `confirm` measures its span against the pads
    the PLACE is right      `silk_miss` measures its body against F.Fab
    the TURN is right       nothing

And the two checks that exist are provably blind to it:

  * `confirm` compares spans, and a half turn does not change a span. It
    catches a QUARTER turn only when the part is far from square -- it missed
    OH-105's by 0.54 mm.
  * `silk_miss` compares body CENTRES, and a half turn preserves a centre.
    Measured: the USB-C reports the identical miss at 0 and at 180 on every
    board (OH-106).

So the turn has been settled three times by a person looking at a picture, and
been wrong three times: 0 (OH-93, a quarter out), 90 (OH-105, a half out from
there), and only now 270.

**The last attempt failed on a plausible metric that was backwards.** OH-105
found the open end by measuring triangle area in each end plane, reasoning
that a mouth is a rim and a back is a filled face. What it actually measured
was the end where thin solder tails cross the plane -- 0.38 mm2 of tail, not
0.38 mm2 of rim -- so it named the BACK as the mouth and turned the part to
face inward.

## THE MEASUREMENT THAT SETTLES IT

A receptacle's contacts leave at the back and solder to pads. So the model's
plated contacts must land on the footprint's own contact pads -- two vendor
sources, no judgement. Distance between them, per turn:

    board                   0        90       180      270
    XIAO-ESP32-C3-DIP     1.861    2.465    1.861    0.922
    XIAO-ESP32-C6-DIP     1.871    2.478    1.874    0.935
    XIAO-RP2350-DIP       3.737    5.110    3.619    0.977
    XIAO-nRF54l15-DIP     3.784    5.191    3.664    0.896

270 on all four, by a factor of two to five. It is not close, and no reading
of a picture was involved.

## DONE WHEN

`turn` is checked the way the model and the place already are: the stated turn
must be the best of the four by this measurement, and `compose` refuses one
that is not. Then the GCT's 270 is a consequence rather than another guess,
and the next part cannot be turned wrongly without something failing.

## DONE, 2026-08-29

`contact_miss` measures how far a model's plated contacts land from the pads
they solder to, and `compose` refuses a stated turn that is not the best of
the four by `TURN_MARGIN_MM`. The GCT receptacle is 270, like the Amphenol
beside it.

**The turn is now a consequence rather than a claim**, which is the whole
point: it is checked the way `confirm` checks the model and `silk_miss`
checks the place. Driving every wrong answer through `compose`:

    turn=0    refused -- contacts 1.861 mm from their pads, 270 gives 0.922
    turn=90   refused -- 2.465 mm, the worst of the four
    turn=180  refused -- 1.861 mm

Those first two are what this repository actually shipped, in OH-93 and
OH-105.

### AND THE CONTACTS ARE ALL ON THE BOARD NOW

`test_no_soldered_contact_hangs_off_the_board` had no notion of HEIGHT and
passed only because every receptacle was turned wrongly at the time. A USB-C's
contacts do not all end on the board and should not: the tails sit on the
pads, then the same contacts run forward onto the tongue, which is inside a
shell that overhangs the edge. So the check now looks only at gold within
0.35 mm of the board's top face -- a tail that has missed its pad -- and every
board is INSIDE the outline:

    Arduino Uno         -2.093 mm
    XIAO-RP2350-DIP     -1.146
    XIAO-ESP32-C3-DIP   -0.372
    XIAO-nRF54l15-DIP   -0.156
    XIAO-ESP32-C6-DIP   -0.152

`CONTACT_OVERHANG_MM` falls from 0.3 to 0.05, and 0.05 is a hair for a contact
drawn flush with the edge rather than an allowance for one hanging off it.

### WHAT THE MUTATIONS FORCED

9 mutations, 8 killed.

  * **The guard was untested while the measurement was not.** Replacing
    `compose`'s call to `contact_miss` with `None` survived every test,
    because they all called the function directly. There is now one that
    drives the refusal through `compose` itself, which is where all three
    wrong turns actually got out.
  * **`TURN_MARGIN_MM` could be negated** and every comparison became
    vacuously true. It is now asserted to lie between zero and the smallest
    winning margin on any board.

The survivor is equivalent rather than a gap: every part this runs on has its
contact field on the board's own centre line, so the centroid's z is within
0.044 mm of zero and a sign flip moves it less than the margin. Said in the
code so nobody hunts it twice.

3 new tests. Gate: 1,808 -> 1,807 passed, 17 skipped -- one FEWER, because
OH-105's inverted mouth test was replaced by two that measure the right thing.
All eight checkers exit 0.
