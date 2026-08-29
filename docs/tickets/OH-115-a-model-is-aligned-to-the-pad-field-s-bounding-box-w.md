---
id: OH-115
title: A model is aligned to the pad field's bounding box where thirty-two pads are
  available
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; `webui/static/board3d.js` is the only file, and this
re-claims when it starts.

**Split out of OH-96, which was filed against the wrong suspect.** That ticket
measured, in the browser, that the Arduino Uno's pads sit up to 3.84 mm from
the nearest pin the vendor's model puts there, and asked which of the two
sources was wrong. Neither is:

    per axis, fitted        worst 0.008 mm
    ONE isotropic scale     worst 0.072 mm      <- what this page applies
    the browser reported    0.65 to 3.84 mm

`test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses`
holds the middle row, which is the one that matters: the traced pad map and
Arduino's own board file agree to a tenth of what the page disagrees by, even
under the page's own simplification. So the millimetres are introduced between
them.

## WHERE, AND IT IS TWO TWO-POINT ESTIMATES

Both are in `placeModel`, and both throw away thirty pads out of thirty-two:

  * **`scaleFromPads` takes the scale from a bounding box on ONE axis** --
    `(max(xs) - min(xs)) / pad_span[longer]`. Two pads decide the scale for
    the whole board, and an error in either is multiplied along the row.
  * **The alignment is the bounding box's CENTRE** -- `(min + max) / 2` on
    each axis, put on the model's own origin. Again two pads per axis, and the
    midpoint of an extent is not the centroid of a field unless the field is
    symmetric.

A least-squares fit of the model's pad positions onto the page's, over all
thirty-two, is the obvious replacement and is what the tests above already do
offline. `scaleFromPads` has a docstring arguing for the lever arm of the
longer axis, which is a real argument for a two-point estimate and is worth
reading before replacing it.

## WHAT MUST NOT HAPPEN

**Do not widen `PIN_REACH_MM`.** Half the pin pitch is 1.27 mm and past that a
pad claims its neighbour's pin and lights the wrong one convincingly. That
constant carries the table for this reason and OH-96 said the same.

## DONE WHEN

Every Uno pad sits within a stated fraction of a millimetre of the pin under
it, measured in the browser the way OH-96 measured it; the twenty-five other
boards are unchanged or better; and the fit is over the pads rather than over
their extremes.
