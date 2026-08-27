---
id: OH-90
title: A PCB is a matte dielectric, so it has no sheen and nothing to reflect
status: done
priority: P2
created: '2026-08-28'
touches:
- tools/import_3d_model.py
- webui/static/board3d.js
- tests/rules/test_import_3d_model.py
- tests/webui/test_board3d.py
---

ASKED FOR BY THE USER: "the pcb board needs to be more realistic. needs shine
and reflection."

## WHAT THE BOARD IS MADE OF NOW

One number. `FINISHES` in `tools/import_3d_model.py` gives the Arduino Uno's
solder mask `#313d63` a `Finish(0.0, 0.35)` and the XIAO SAMD21's `#116517` the
same, and `showBoard` in `webui/static/board3d.js` builds the extruded slab --
the board every model-less board draws -- at roughness 0.85. So a PCB is a
matte dielectric that reflects nothing in particular, and the environment OH-85
put in front of it has nothing to catch.

## WHAT A PCB ACTUALLY IS, AND WHY ONE ROUGHNESS CANNOT SAY IT

Solder mask is a pigmented epoxy under a cured, near-transparent surface. That
is two layers with different behaviour, and `MeshStandardMaterial` has one: a
single roughness has to be either the colour's diffuse scatter or the coat's
specular, and it is currently set to the first. The visible consequence is the
one being reported -- no sheen, and in particular no grazing-angle brightening,
because Fresnel on a coat is exactly what a board does when you tilt it.

`MeshPhysicalMaterial` has `clearcoat` and `clearcoatRoughness` for this, and
glTF has `KHR_materials_clearcoat` to carry it. three.js r185 supports both.

## WHAT THIS NEEDS

  * `Finish` gains a coat, defaulting to none, so every existing entry keeps
    exactly the material it has and only the surfaces that are coated say so.
  * `write_glb` writes `KHR_materials_clearcoat` for those, and declares it in
    `extensionsUsed`.
  * `board3d.js` reads it. **Its glTF reader is this repository's own** and
    deliberately narrow -- `readModel` takes `baseColorFactor`, `metallicFactor`
    and `roughnessFactor` and nothing else -- so it has to learn the extension
    and build a `MeshPhysicalMaterial` when it is present.
  * the extruded slab in `showBoard` gets the same coat, because it is the same
    claim about the same material and a reader switching boards should not see
    the physics change.

## DONE WHEN

The board brightens at a grazing angle and does not at a normal one, measured
from two rendered frames rather than judged -- and every surface that is not a
PCB is byte-for-byte the material it was, because this ticket is about one
substance and not about making things shiny.

**Note 2026-08-28:** **CLOSED 2026-08-28, and the done-when's premise was wrong.**

It said the board should "brighten at a grazing angle and not at a normal one",
which is what Fresnel does in the open air. Measured with the coat switched off
and on and nothing else changed:

    camera      board's brightest tenth, off -> on
    top-down        148.0 -> 172.2     +16.3%
    default         132.9 -> 132.7      nothing
    oblique         132.3 -> 128.2      -3.1%

A coat returns what lies in the MIRROR direction. In this room the bright thing
is overhead, so a flat board shows its coat from ABOVE and loses a little as the
camera drops toward a wall dimmer than the ceiling. The done-when described a
board outdoors under a bright horizon. The coat is right; the prediction was
not, and the numbers are in the source beside the constant.

## AND THE COAT NEEDED A SOURCE BEFORE IT MEANT ANYTHING

The first working version moved the board's brightest tenth by 1.3%, which is
nothing anybody can see, because the softbox covered about 78 degrees of sky and
a coat reflecting most of the sky returns a wash. Same coat, two skies:

    sky            board's brightest tenth, coat off -> on
    radius 0.50        179.3 -> 181.6      +1.3%
    radius 0.16        148.0 -> 172.2     +16.3%

**One paragraph of the source credited the coat with the softbox's work** --
"the same coat then moves the brightest tenth by 15%" -- from two runs that had
both changed. Corrected before the commit; the table above is the controlled
pair, and only the within-pair percentages are quoted because the two pairs sit
at different exposures.

## THE LARGER FIND, WHICH WAS NOT IN THIS TICKET

Measuring the board's COLOUR to check the coat turned up something bigger than
the coat. At `LIGHT_TOTAL` 5.2 the Uno's mask rendered with a median of
rgb(150, 166, 206) against the #313d63 = rgb(49, 61, 99) that
`compose_board_3d.py` read out of PICSimLab's artwork -- three times its own
albedo. That is why a navy board came out pale periwinkle and the blacks came
out grey. Over-lighting does not brighten a picture, it desaturates it.

Lights and room both scaled by 0.62: median rgb(115, 129, 163), and the ratio
OH-86 measured held to within one percent so its crevice contrast survives.
Close-up tonal entropy 4.855 -> 5.635 bits; the DIP-28 crop's darkest tenth
0.244 -> 0.170 of its mean.

## WHAT IS STILL NOT REALISTIC ABOUT THE PCB

Both known, both bigger than anything above, and neither is this ticket's:

  * **No artwork.** The board is one flat colour with no silkscreen, no traces
    and no pads, because the Uno's `board.svg` is not in the tree --
    `webui/assets.py` reads it out of the user's PICSimLab install at runtime
    and PICSimLab is GPL. `rules/licence-hygiene.md` has to answer that before
    a texture can be built on it. It remains the single largest visual gap.
  * **No copper under the mask.** A real board's mask is slightly translucent
    over copper pour, which is what gives a PCB its faint mottling. That needs
    the artwork above before it means anything.
