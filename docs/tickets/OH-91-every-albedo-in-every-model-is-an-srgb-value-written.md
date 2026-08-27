---
id: OH-91
title: Every albedo in every model is an sRGB value written where glTF wants linear
status: done
priority: P1
created: '2026-08-28'
touches:
- tools/import_3d_model.py
- webui/static/board3d.js
- tests/rules/test_import_3d_model.py
- tests/webui/test_board3d.py
---

REPORTED BY THE USER, twice, and the second time after OH-90: "the board is
still matte and greyish". It is, and every measurement in OH-90 was taken
against a scene whose colours were wrong.

## THE BUG IS ONE LINE AND IT IS IN EVERY MATERIAL IN EVERY MODEL

`write_glb` in `tools/import_3d_model.py`:

    red = int(colour[1:3], 16) / 255

That is an sRGB byte divided by 255 and written into `baseColorFactor`, which
the glTF specification defines as LINEAR. The transfer function is never
applied, so every albedo in the corpus is too bright -- and, because the
function is non-linear, DIFFERENTLY too bright per channel, which flattens the
colour toward grey:

    surface           written -> should be        too bright   saturation
    Uno solder mask   .192 .239 .388 -> .031 .047 .125   6.3x 5.1x 3.1x   .51 -> .75
    SAMD21 mask       .067 .396 .090 -> .006 .130 .009  11.9x 3.0x 10.5x  .83 -> .96
    gold contact      .710 .506 .212 -> .462 .220 .037   1.5x 2.3x  5.7x  .70 -> .92
    black epoxy       .020 .020 .020 -> .002 .002 .002  12.9x each        .00 -> .00
    resistor body     .753 .463 .208 -> .527 .181 .036   1.4x 2.6x  5.8x  .72 -> .93

**BLACK EPOXY IS THIRTEEN TIMES TOO BRIGHT**, which is why the DIP-28 and the
barrel jack read as grey plastic. The Uno's mask is three to six times too
bright and half as saturated as it should be, which is the whole of "matte and
greyish".

## THE REPOSITORY ALREADY HAD THE RIGHT ANSWER, IN THE OTHER PLACE

`readPalette` in `webui/static/board3d.js` builds its colours with
`new THREE.Color("#313d63")`, and the string form calls `setStyle`, which DOES
apply the transfer function. So the extruded slab -- the board drawn for
anything with no published mesh -- has been correct all along, and the composed
board beside it has been three to six times too bright. Two answers to one
question, in one file's neighbourhood, disagreeing since the first model
landed.

## WHAT IT EXPLAINS BESIDES THE COMPLAINT

  * OH-90 measured the Uno's mask rendering at three times its own albedo and
    treated that as over-lighting. It was not: the albedo really was that
    bright, because it had been decoded wrong.
  * The exposure has been dialled down twice, once in OH-86 and once in OH-90,
    each time to compensate for surfaces that were too bright for a reason
    nobody had looked for.
  * A specular layer cannot show against a diffuse term that large, which is
    why OH-90's clear coat measured 1.3% before the softbox shrank.

## DONE WHEN

`baseColorFactor` carries linear values, every model is rebuilt, and the
rendered solder mask is measured against #313d63 rather than against a guess --
and the exposure that was lowered to hide this is put back to whatever the
corrected scene actually needs.
