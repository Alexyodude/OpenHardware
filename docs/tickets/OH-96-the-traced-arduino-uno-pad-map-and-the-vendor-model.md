---
id: OH-96
title: The traced Arduino Uno pad map and the vendor model disagree by up to 3.8 mm
status: done
priority: P2
created: '2026-08-29'
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

## DONE, 2026-08-30

**Established: NEITHER source is wrong, and the title of this ticket is the
mistake.** The traced pad map and the vendor's board file do not disagree.

Measured independently of the `derivation` field that already claimed it,
by pairing all 32 pads by row and order and fitting out the frame difference:

    one scale and offset PER AXIS      median 0.0045 mm   worst 0.0084 mm
    ONE isotropic scale, both axes     median 0.032 mm    worst 0.072 mm
    what the browser reported          0.65 mm to 3.84 mm

**The middle row is the one that settles it.** The per-axis fit is the honest
one, but it is not what the page performs: `webui/static/board3d.js` calls
`group.scale.setScalar(...)`, a single number for both axes. The artwork is
anisotropic by 0.41% -- 5.6616 px/mm across against 5.6382 down -- so the
question worth asking is whether the two sources still agree under THAT
simplification. They do, to 0.072 mm, which is nine times smaller than the
smallest disagreement the browser reported.

So the millimetres are introduced downstream, between two sources that agree,
and this ticket's "which of the two is wrong" has no answer because its
premise is false.

## WHERE THEY COME FROM, AND IT IS NOW ITS OWN TICKET

**OH-115.** Both estimates in `placeModel` are two-point: `scaleFromPads`
takes the scale from a bounding box on one axis, and the alignment is that
box's midpoint. Thirty-two pads are available and four of them decide
everything.

## WHAT LANDED HERE

  * `test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses`
    in `tests/rules/test_import_board.py`, which pins the single-scale
    residual. It exists so the pad map is never "corrected" into agreement
    with a placement bug -- which is exactly what this ticket would have led
    somebody to do.
  * The note beside `PIN_REACH_MM` said the last five were "pads the traced
    map puts somewhere the model has no pin at all". That is now known to be
    false and it is corrected in place, with both numbers and a pointer to
    OH-115.

`PIN_REACH_MM` is unchanged at 1.1, which this ticket forbade widening and
which remains right for the reason it gives.

## WHAT WOULD STILL BE WORTH DOING, AND IS NOT THIS

Measuring a real board. Both sources here are drawings by the same vendor, and
they agree; a caliper on an actual Uno would be a third and independent one.
Nothing depends on it, because the residual after OH-115 is expected to be a
tenth of a millimetre.
