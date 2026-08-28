---
id: OH-96
title: The traced Arduino Uno pad map and the vendor model disagree by up to 3.8 mm
status: open
priority: P2
created: '2026-08-29'
touches: []
---

**Found by OH-95, which could not have found it any other way.** While the pad
marker was a cylinder this repository drew, it was drawn at the pad map's
position and there was nothing to compare it against. OH-95 replaced the
marker with the vendor's own pin, which meant looking for a pin under each pad
-- and five of them have none.

Measured in the browser on the composed Uno, as the distance from each pad to
the nearest metal above the PCB:

    14 pads   0.05 - 0.07 mm    0-7, A0-A5, VIN
    11 pads   0.65 - 0.77 mm    8-13, 5V, 3V3, RESET, IOREF, NC
     5 pads   1.21 - 3.84 mm    GND 1.208, 6 2.196, SCL 2.710,
                                AREF 3.155, SDA 3.843

**Three groups, and the shape of them is the evidence.** Fourteen pads agree
to within a twentieth of a millimetre, which is what a correct pad map looks
like. Eleven more are out by a consistent 0.7 mm, and they are exactly two
headers -- `IOH`'s digital half and `POWER` -- so that reads as two components
placed together rather than as noise. The last five are out by more than a pin
is wide, and four of them (`SCL`, `SDA`, `AREF`, `GND`) are the far end of the
same ten-pin header whose other six are in the 0.7 mm group.

## WHY THIS BOARD AND NOT THE OTHER TWENTY-FIVE

`webui/static/board3d.js` says it in `placeModel`: the Uno's is "the one pad
map in this repository that was traced rather than generated". Every other
board's pads come out of the vendor's own KiCad footprint through
`tools/import_board.py`, exact to three decimals. This one was measured off
PICSimLab's artwork by hand.

## WHAT IS NOT KNOWN YET

Which of the two is wrong. The model's headers come from Arduino's own EAGLE
placements and KiCad's published meshes, both of which
`tools/compose_board_3d.py` confirms against pad spans -- but `confirm` checks
that a mesh SPANS its element's pads, which a 0.7 mm shift passes easily.

**Do not "fix" this by widening `PIN_REACH_MM`.** Half the pin pitch is
1.27 mm, and past that a pad claims its neighbour's pin and lights the wrong
one convincingly. The constant carries this table beside it for that reason.

## DONE WHEN

It is established which source is right -- by measuring a real board, or by
reading Arduino's own drawing against PICSimLab's artwork -- and the wrong one
is corrected or annotated. Until then the five pads keep an invisible collider
and a wire can still be dragged from them; they simply do not light.
