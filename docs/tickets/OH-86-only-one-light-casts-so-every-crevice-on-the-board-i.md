---
id: OH-86
title: Only one light casts, so every crevice on the board is lit from inside
status: done
priority: P2
created: '2026-08-28'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

OH-85 gave the scene shadows and they land, but they are ONE light's shadows.
The environment supplies most of the illumination and an image-based light comes
from every direction at once, so it casts nothing and darkens nothing: the gap
under a header shroud, the slot beside a DIP-28's legs and the inside of the
barrel jack are all lit as brightly as open board. That is what is left of
"the components look pasted on".

## THE ROUTE THE LAST HANDOFF RECOMMENDED IS THE WRONG ONE FOR THIS CORPUS

`docs/HANDOFF_2026-08-27_the-circuit-and-the-layout.md` 6.2 argued for baking
ambient occlusion into VERTEX COLOURS at import time: view-independent, free at
runtime, and needs no UVs, which matters because these meshes have none. The
first two are true. The third is the problem. Measured on the composed Arduino
Uno, 2026-08-28, vertices per surface against the area they cover:

    #313d63  the PCB        108 vertices over 68.6 x 53.3 mm   33.87 mm2 each
    #a5a392  legs        10,436 vertices over 65.3 x 48.9 mm    0.31 mm2 each
    #050505  mouldings    5,033 vertices over 69.5 x 51.4 mm    0.71 mm2 each
    #b58136  header pins  3,456 vertices over 51.1 x 48.9 mm    0.72 mm2 each

**The one surface that most needs contact darkening has one vertex every six
millimetres.** The PCB is a box with a top face made of two triangles, and a
per-vertex bake there would resolve nothing at all: the shadow that should sit
in the 0.3 mm gap beside a DIP-28's leg has nowhere to be written. The
components have the density; the thing they sit on does not.

## SO THE QUESTION IS WHICH OF THREE, AND IT IS NOT OBVIOUS

  1. **SUBDIVIDE THE PCB TOP AND BAKE.** Honest and view-independent, and it
     makes the model carry its own lighting. A 68 x 53 mm face at 0.5 mm is
     about 14,000 vertices and 29,000 triangles -- roughly doubling the Uno --
     and 0.5 mm is still coarse next to a 0.3 mm gap.

  2. **SSAO OR GTAO AT RUNTIME.** Per-pixel, exactly where it is needed, and
     three.js ships both. It needs `EffectComposer` and its passes vendored --
     MIT, so `rules/licence-hygiene.md` is satisfied -- but it also moves the
     render into a target, and `mount` currently asks for `antialias: true` on
     the default framebuffer. Losing MSAA to gain occlusion is a trade this
     ticket must measure rather than assume.

  3. **SAMPLE THE HEMISPHERE WITH MORE SHADOWED LIGHTS**, and take the
     illumination for them out of `scene.environmentIntensity`, which r185
     supports. Not ambient occlusion and must not be called it: it is the same
     integral estimated with two or three samples instead of none. Uses only
     what is already vendored and reuses `castShadows`, which was written to
     fit a frustum to the scene and does not care how many lights ask.

## DONE WHEN

A crevice is measurably darker than open board, by a number taken from the
rendered frame rather than by eye -- and whichever route is taken, the two that
were not are recorded with the measurement that ruled them out.

**Note 2026-08-28:** **CLOSED 2026-08-28 by route 3, and the two that were not taken are recorded
with what ruled them out**, which is what the DONE WHEN asked for.

## WHAT WENT IN

Three directional lights instead of one, all casting, with the illumination for
them taken out of `scene.environmentIntensity` (1.0 -> 0.45) rather than added
on top. That last half is the whole mechanism: every unit of brightness living
in an image-based light is a unit no shadow can ever subtract from, because it
arrives from every direction at once. Moving some of it into lights that cast
is what lets a crevice go dark.

**It is not ambient occlusion and the source says so twice.** It is the same
integral -- how much of the sky a surface can see -- estimated with three
samples instead of none. A gap open to one side keeps that light, which is
right; a gap open to none of the three goes dark, which is also right; and
anything finer than three directions it cannot see.

## MEASURED, ON A 4x CROP OF THE DIP-28 WHERE IT MEETS THE BOARD

`LIGHT_TOTAL` was raised at each step to hold the exposure, and the dark tail is
given against the crop's own mean so that dimming the whole picture cannot read
as a win:

    environment share    darkest tenth    over the crop's mean    entropy
    1.00 (before)             42.63             0.269             4.92
    0.62                      37.03             0.244             4.84
    0.45  <- chosen           35.54             0.234             5.00
    0.30                      33.91             0.223             5.12

The entropy keeps rising past 0.45 and the picture stops improving: at 0.30 the
capacitor lids and the barrel jack come out duller than the moulded plastic
beside them, which inverts the one relationship anybody can check against a real
board. Two thirds of the available darkening has happened by 0.45 and the last
third costs the metals the only thing they have to reflect.

## THE TWO ROUTES NOT TAKEN

  * **BAKE INTO VERTEX COLOURS.** Ruled out by measurement before any code was
    written, and it is the route the previous handoff recommended. The composed
    Arduino Uno's PCB is 108 vertices over 68.6 x 53.3 mm -- ONE EVERY SIX
    MILLIMETRES. The components have the density (0.31 to 0.72 mm2 per vertex);
    the thing they sit on, which is where a contact shadow has to live, does
    not. The 0.3 mm gap beside a DIP-28's leg would have nowhere to be written.

  * **SSAO OR GTAO.** Not ruled out, and still the right answer if anyone wants
    this exact. Deferred rather than refused: `mount` asks for `antialias: true`
    on the default framebuffer, and moving the render into an `EffectComposer`
    target gives that up unless a multisampled target is configured -- so the
    first version of it would trade aliasing on every pin outline for occlusion
    in the crevices, which is not obviously a win and is not a thing to find out
    after vendoring seven files.

## WHAT IT COSTS

Three shadow maps at 2,048 square instead of one, so three depth passes of about
20,000 triangles per frame instead of one. No console errors and no measurable
stutter on this machine; `shadow.autoUpdate` is deliberately left on, because a
dragged wire moves geometry every frame and a stale map would freeze its shadow
in mid-air.
