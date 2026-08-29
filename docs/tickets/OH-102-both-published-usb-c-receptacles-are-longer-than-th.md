---
id: OH-102
title: Both published USB-C receptacles are longer than the one Seeed actually fit
status: done
priority: P3
created: '2026-08-29'
touches:
- tools/compose_board_3d.py
- tools/model_from_datasheet.py
- tools/blender/usb_c_receptacle.py
- tests/rules/test_compose_board_3d.py
- CLAUDE.md
---

CLAIMS NOTHING; the same reason OH-97, OH-98 and OH-99 claim nothing.

Every composed XIAO draws a USB-C receptacle a millimetre and a half too long,
so it overhangs the board edge further than the real one does. Found while
fixing OH-101, and left because it is a fraction rather than a defect.

## THE VENDOR NAMES THE PART AND DOES NOT SHIP IT

    RP2350      USB-31C-F-16P-L7.35.stp
    nRF54L15    320011419_ST-USB-3316T.stp

**`L7.35` is the body length**, 7.35 mm. Against it:

    GCT USB4105-xx-A_16P        8.94 mm    +1.59
    Amphenol 12401610E4-2A      9.20 mm    +1.85

Those are the only two 16-pin USB-C receptacles in KiCad's 13-file
`Connector_USB`, so there is no third to try. Both are used today -- the GCT
for the four-tab land, the Amphenol for the two-lock one, see OH-101 -- and
both are long.

## AND THE AMPHENOL'S SHELL IS THE WRONG COLOUR

`#1d1d1d` in its own STEP, where the GCT's is `#a5a392` and a real receptacle
is bright stainless steel. It is the model author's colour and OH-97's rule
keeps it: a face the vendor DID colour is untouched. So the RP2350 and the
nRF54L15 draw a dark slab where the C3 and C6 draw a metal socket, and the
four boards look like they have two different connectors on them. They do not.

## WHY MODELLING IT IS DEFENSIBLE HERE

The same argument the Uno's USB-B rests on, and OH-100's QFN-60 after it:

  * **The plan is the vendor's**, read out of the land pattern -- sixteen
    contacts and two board locks, positions and sizes to three decimals.
  * **The length is the vendor's**, stated in the part number they wrote into
    their own board file.
  * **The rest is the USB Type-C specification**, which fixes a receptacle's
    outside because a cable from any maker has to enter a socket from any
    other -- exactly the reasoning behind the one cited number in the USB-B.

So it would be a modelled part with no invented dimension, and it would be
better than either published model rather than a step down from them.

## DONE WHEN

The composed XIAOs draw a 7.35 mm receptacle; the worst gold vertex outside
the PCB goes to 0.000 on all five boards, as it already is on three; and
`CONTACT_OVERHANG_MM` drops from 0.25 to whatever the exact part needs.

**Note 2026-08-30:** DONE. Seeed state the whole envelope in the footprint's own Description property -- `SMD USB TYPE C-W/P;12+4P-7.35*8.94*3.25mm` on the 16P land and `SMD USB Type-c;12P+4-8.9*7.3*3.2mm` on the four-tab one -- so the HEIGHT is the vendor's too and nothing had to be cited for it. Both agree with the F.Fab rectangle they drew, to 0.020 and 0.092 mm. Only the 8.34 x 2.56 mm opening is not theirs and it is the USB Type-C specification's. Both land patterns are modelled now; BODY_ALLOWANCE_MM is gone and CONTACT_OVERHANG_MM is 0.0. silk_miss 0.500/1.332/1.495 -> 0.350/0.275/0.275, the turn wins by 3.6x to 33x where it won by 2x to 5x.
