---
id: OH-92
title: The softbox is at the zenith and the default camera's mirror direction is not
status: done
priority: P1
created: '2026-08-28'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

THE USER SAID "needs shine and reflection", THEN "the board is still matte and
greyish", AND THE SECOND ONE WAS A COLOUR BUG (OH-91) THAT IS NOW FIXED. The
colours are right: the Uno's mask renders at rgb(77, 93, 144) against the
`#313d63` the repo sourced, saturation 0.465, and the DIP-28 and the barrel
jack are black rather than grey. **The shine is still missing**, and this is
the ticket for the half of the complaint that OH-90 and OH-91 did not close.

## IT IS NOT THAT THE COAT DOES NOTHING. IT IS AIMED PAST THE READER.

`studio()` puts the softbox at `(0, STUDIO_SIZE * 0.62, 0)` -- straight up,
centred on the board. Its half-angle from the board is `atan(0.16/0.62)` =
**14.5 degrees**, so it occupies elevation 75.5 to 90.

`frameScene` puts the camera at `(0.1, 0.85, 0.75) x reach`. Read back live out
of `describe()` on a loaded Uno: position (6.03, 51.29, 45.23), target
(0, 0.035, 0), which is **elevation 48.3 degrees**, azimuth 7.6.

A flat board has normal +y, so it returns what lies in the mirror of the view
direction about +y: **elevation 48.3 degrees, azimuth 187.6** -- that is, 27
degrees BELOW the softbox's nearest rim, and on the far side of the board
toward -x -z. The reflection of the only bright thing in the room lands
somewhere the default camera is not.

**Measured, same board, same scene, only the camera moved:**

    camera elevation    mask mean    mask brightest tenth    saturation
    48.3 (the default)      93.9            119.2              0.465
    90.0 (top-down)        154.7            192.7              0.220

The top-down frame has an obvious soft highlight sweeping across the board and
the default frame has none -- and the saturation FALLING as the mean rises is
the signature of a specular highlight rather than more diffuse light.
Screenshots: `.playwright-mcp/oh92-default.png`, `.playwright-mcp/oh92-topdown.png`.

So OH-90's clearcoat works, OH-91's albedos are right, and the picture a reader
actually gets is still a flat blue slab. **Nothing above this ticket was
wasted; all of it is invisible at 48 degrees.**

## WHAT IS NOT THE ANSWER, AND IT IS ALREADY MEASURED

**Making the softbox bigger so it covers both directions.** That was the
previous setting and OH-90 measured it: radius 0.50 gave the coat +1.3% on the
board's brightest tenth, against +16.3% at radius 0.16. A source wide enough to
cover every camera angle is a source too wide to be a highlight. The comment
above `SOFTBOX` carries the table and it stands.

## DONE WHEN

The board seen at the DEFAULT camera carries a highlight -- measured as the
clearcoat's effect on the mask's brightest tenth at that camera, switching only
the coat, which today is +6.5% -- and the top-down and oblique views do not
lose theirs to pay for it. And a test pins the softbox to the camera's mirror
direction rather than to a literal, so the next person who moves `CAMERA_PULL`
or the camera vector finds out.

Not a colour change: `FINISHES` and the palette are measurements and this
ticket does not touch them.

## DONE, 2026-08-28

**The softbox is derived from the camera now, not placed beside it.**
`CAMERA_FROM` is the one place the view direction is written down;
`frameScene` reads it, and `studio()` reflects it about +y to place the disc.
The two cannot drift apart, which is the failure this ticket is an instance of
and the sRGB bug was another.

**The coat alone, at the default camera, switching nothing else:**

    before (softbox overhead)   132.7 -> 132.9    +0.2%   (OH-90's measurement)
    after                       134.4 -> 210.7   +56.8%

**And the first fix was wrong in an instructive way.** Aiming the 0.16-radius
disc at the mirror direction lit the WHOLE face evenly -- quiet board rgb(101,
112, 154), saturation 0.344 against 0.469 -- because perspective sweeps the
board's own mirror direction through 34 degrees and the source subtended 28.9.
That is the same "wide and mild" the constant's own comment rejects, reached
from the other side: at the zenith it was too wide AND missed, so being too
wide never showed. Radius 0.08 subtends 14.7 and crosses the board instead.

`sheen` below is the mask's brightest tenth over the mean of its own darker
half -- how far the highlight stands above the board carrying it. It is a
ratio, so dimming the picture cannot fake it, and the two halves separate the
colour claim from the shine claim, which one median hides:

    camera      sheen before -> after     brightest tenth
    default        1.356 -> 2.341          119.2 -> 210.7
    top-down       1.424 -> 1.564          192.7 -> 127.9
    oblique        1.585 -> 1.630          123.2 -> 109.5

**Every camera improved on the ratio**, so the default view did not buy its
highlight from the others. The absolute falls at top-down and oblique are
`ENVIRONMENT_SHARE` 0.61 -> 0.35, and that share bought the colour back
everywhere: top-down's quiet board went rgb(129, 138, 174) saturation 0.259 ->
rgb(67, 82, 131) saturation **0.489**, which is the closest to the sourced
`#313d63` this scene has measured.

At the default camera the quiet board goes rgb(76, 92, 143) saturation 0.469 ->
rgb(82, 95, 138) saturation 0.406. **That is the cost and it is real light**:
the board desaturates exactly where the highlight sits on it, which is what a
coated surface does. It is paid at one camera and refunded at the other two.

OH-86's judgement that the metals fail below 0.45 was RE-CHECKED rather than
inherited, because its premise changed -- the softbox is four times brighter
and now aimed usefully. At 0.35 the USB shell, both capacitor lids and the
barrel jack still read as metal; at 0.30 the shell goes flat and grey. The knee
moved, it did not vanish.

Evidence: `.playwright-mcp/oh92-default.png` (before), `oh92-final.png`
(after), `oh92-topdown.png` and `oh92-new-topdown.png` for the pair that made
the diagnosis. 4 new tests; 12 mutations, 12 killed, and one recorded as
equivalent -- moving `CAMERA_FROM` moves the softbox with it, which is the
derivation working rather than a gap.

Gate: 1,723 passed, 17 skipped. All eight checkers exit 0.
