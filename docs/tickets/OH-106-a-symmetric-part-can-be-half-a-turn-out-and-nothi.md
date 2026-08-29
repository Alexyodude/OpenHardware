---
id: OH-106
title: A symmetric part can be half a turn out and nothing sees it
status: open
priority: P2
created: '2026-08-29'
touches: []
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
