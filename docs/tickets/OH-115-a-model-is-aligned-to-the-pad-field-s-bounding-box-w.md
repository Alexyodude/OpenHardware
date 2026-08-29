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

## CORRECTION, 2026-08-30: the cause named above is DISPROVED

**I filed this ticket on a hypothesis and then measured it three ways. It is
wrong.** The bounding-box estimators are not what puts the Uno's pads away
from its pins. Left open, because the symptom is real and reproduced -- but
the next person should not start where this ticket told them to.

### What was ruled out, and how

**1. The bounding-box estimator is accurate.** Fitting the model's own header
pads onto the page's, paired by row and order, over all 32:

    bbox scale + bbox midpoint  (what placeModel does)  median 0.041  worst 0.093 mm
    bbox scale + centroid                               median 0.043  worst 0.095
    RMS scale  + centroid       (least squares)         median 0.041  worst 0.076

Zero pads over 1.1 mm by any of the three. The two-point estimate costs about
seventeen MICROmetres against the least-squares answer, and the scales differ
by 0.094%. **A fit over all thirty-two pads would change nothing.**

**2. The mesh has metal on every pad.** Reproducing `carvePins` offline in the
model's own frame -- 11,908 metal vertices above the 1.6 mm top face, against
the vendor's own 32 header pads:

    every pad is 0.2263 mm from metal. No 0.7 mm group. No 3.8 mm group.

**3. The anisotropy is not it either**, which OH-96 already showed: 0.41% over
a 68.58 mm board is 0.28 mm, and the single-scale fit absorbs it to 0.093.

### What IS reproduced, in the browser

`describe()` on the running page, Arduino Uno:

    30 pads, 25 with real pins -- missing 6, AREF, GND, SCL, SDA

Exactly OH-96's five. Converting the page's pad positions back into the
model's own frame through `model.position`, `model.scale` and `model.rotationY`
puts those five 1.24 to 3.05 mm from the nearest metal, while the vendor's own
pads are 0.23 mm from it. **So the page is putting those five pads somewhere
the vendor does not put them** -- and it is per-pad, not a transform, because
a wrong transform would move all thirty.

Note that a pad which DID find its pin reports position (0,0) afterwards:
`carvePins` replaces its cylinder with carved geometry whose own transform is
identity. Only the missing ones still report where they are, which is
convenient here and a trap for the next measurement.

### THE FIRST THING TO LOOK AT

The board file holds 32 pads and `view.pads` holds 30. Two are lost, both
GND -- see **OH-117**, which is its own defect and may or may not be related
to these five. Start by making the count agree, then re-measure: a Map keyed
on label is already known to drop entries, and whatever else it does to pads
that share a name is unmeasured.

**Do not start by rewriting `scaleFromPads`.** That was this ticket's own
advice and it is now measured to be worth 17 micrometres.
