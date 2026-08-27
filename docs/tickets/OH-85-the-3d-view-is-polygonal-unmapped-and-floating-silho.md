---
id: OH-85
title: 'The 3D view is polygonal, unmapped and floating: silhouette, tone mapping
  and contact shadows'
status: done
priority: P2
created: '2026-08-28'
touches:
- tools/import_3d_model.py
- tools/compose_board_3d.py
- webui/static/board3d.js
- tests/rules/test_import_3d_model.py
- tests/webui/test_board3d.py
---

ASKED FOR BY THE USER: "make the 3d model and 3d view realistic". OH-82 gave
every surface a material and put a room in front of the metal to reflect, which
was the largest single step. Three things are left and they are independent.

## 1. THE SILHOUETTE IS POLYGONAL, AND THE KNOB NOBODY WAS LOOKING AT IS THE
## ONE THAT CONTROLS IT

`tools/import_3d_model.py` has two tessellation controls. `DEFLECTION = 0.05`
carries a paragraph of reasoning measured on the SAMD21; `ANGULAR = 0.5` says
only "OCC's own default; named here so that both knobs are visible rather than
one". **The reasoning is attached to the knob that does not bind.** Measured
2026-08-28, re-reading the STEP for each setting because `BRepMesh` caches its
triangulation on the shape and a second call with the same shape is a no-op --
which is itself a trap worth writing down:

    5 mm LED        defl 0.05 ang 0.5      461 tri
                    defl 0.01 ang 0.5    1,627 tri   (5x finer chord: 3.5x)
                    defl 0.05 ang 0.2    1,509 tri   (2.5x coarser angle: 3.3x)
                    defl 0.05 ang 0.1    4,959 tri

    220 ohm axial   defl 0.05 ang 0.5    1,950 tri
                    defl 0.01 ang 0.5    2,876 tri
                    defl 0.05 ang 0.2    9,352 tri
                    defl 0.05 ang 0.1   36,220 tri

0.5 rad is 29 degrees between facets, so a cylinder gets about twelve sides and
a dome gets fewer. That is what makes the barrel jack, the electrolytics and
the LED domes read as CAD.

DONE WHEN `ANGULAR` carries the measurement and `DEFLECTION`'s comment stops
claiming a conclusion it was not testing, and the cost of whatever value is
chosen is recorded in bytes for every shipped model.

## 2. NOTHING IS TONE MAPPED

`webui/static/board3d.js` never sets `renderer.toneMapping`, so it is
`NoToneMapping`: every value above 1.0 is clipped flat. That is the default
that matters least on a diffuse scene and most on this one, because OH-82 put
an environment in front of nine metal surfaces and a specular highlight on
metal is exactly the thing that goes above 1.0. The vendored three.js exports
`ACESFilmicToneMapping`, `AgXToneMapping`, `NeutralToneMapping`,
`CineonToneMapping` and `ReinhardToneMapping`.

DONE WHEN whichever is chosen is chosen against a measurement of the picture --
clipped-pixel count, or the tonal entropy the last session used -- and not
because it is the popular one.

## 3. FIFTEEN COMPONENTS FLOAT

Carried from `docs/HANDOFF_2026-08-27_the-circuit-and-the-layout.md` 6.2. A
contact shadow is what says "this is attached to that", and there is none:
`renderer.shadowMap` is untouched and no mesh casts or receives. The board has
been one object since it was an extruded slab and stopped being one the day
OH-75 put components on it.

Two routes and they are not the same effect. A SHADOW MAP gives the component's
shadow cast on the board, which is the one that fixes floating; BAKED AMBIENT
OCCLUSION gives crevice darkening, is view-independent and free at runtime, and
would go in vertex colours because these meshes have no UVs (`attributes` are
`NORMAL` and `POSITION`, zero textures). The first is a few lines and needs
bias tuning against 0.05 mm features on a 70 mm board; the second is an import
change and regenerates every model.

## NOT IN THIS TICKET

The PCB artwork as a texture, which would be the biggest single jump and is
blocked on the licence question `rules/licence-hygiene.md` raises: the Uno's
`board.svg` is not in the tree, `webui/assets.py` reads it out of the user's
PICSimLab install at runtime, and PICSimLab is GPL. Answer that first.

**Note 2026-08-28:** **MEASURED 2026-08-28 BEFORE WRITING ANY CODE, AND IT REORDERED THE TICKET.**
Rendered the Uno at a fixed low camera and magnified the two electrolytics at
4x device scale. What is wrong with that picture is NOT what section 1 above
guessed:

  * THE CAN TOPS ARE ALREADY ROUND. Tessellation is not what makes them look
    unreal. Rebuilding the whole corpus at `ANGULAR` 0.2 costs 4,170,400 ->
    9,146,360 bytes (2.19x; the Uno alone 710,216 -> 1,792,336) and changes
    0.95% of the pixels in the board close-up. It is a real improvement on the
    5 mm LED and the axial resistor -- 4.41% of the pixels in the bench view --
    and it is nowhere near the largest thing wrong.

  * WHAT ACTUALLY LOOKS FAKE IS A DEAD-STRAIGHT DIAGONAL SEAM ACROSS EACH CAN,
    cream on one side and pure black on the other. That is the STUDIO ITSELF:
    `studio()` builds six flat planes and prefilters them at `STUDIO_BLUR`
    0.04, so a smooth metal surface reflects the box's own corner as a hard
    line. Its own comment predicted exactly this -- "six flat planes meet at
    hard edges, and a mirror-smooth surface would reflect those edges as a
    visible box" -- and 0.04 turned out not to be enough blur to hide it.

  * AND NOTHING TOUCHES ANYTHING. The DIP-28, the header shrouds and the pad
    markers meet the board at a hard edge with no darkening and no cast
    shadow, which is section 3 and is the largest of the three.

SO THE ORDER IS: the environment first, then tone mapping, then shadows, then
decide the tessellation question on whatever is still visible.

Evidence on disk: `.playwright-mcp/before-cans.png`, `before-dip.png`,
`before-close.png`.

**Note 2026-08-28:** **DONE 2026-08-28 for three of the four things, and the fourth turned out not
to be a defect.** Measured before and after at a fixed camera, on the Uno
close-up:

    clipped pixels   0.303%  ->  0.011%
    luminances used     217  ->     248
    tonal entropy     4.432  ->   5.0 bits (4.962)

## WHAT WENT IN

  1. `weld_seams` in `tools/import_3d_model.py`. Every B-rep face is meshed on
     its own, so a periodic surface -- a cylinder, a sphere -- comes back with
     its wrap line duplicated and each copy holding the average of only its own
     side. Measured on the Uno before: 509 coincident pairs in `#a5a392` and
     178 in `#050505` whose normals disagreed, the worst 22.1 degrees, which is
     a whole facet's worth of normal dropped on one edge. After: 12 and 4, and
     those are the points where three surfaces genuinely meet. **FREE IN
     BYTES** -- every `.glb` is byte-for-byte the size it was.

  2. A room with no edge in it. The six flat planes became a graded sphere and
     the softbox a disc that fades to the ceiling at its rim.

  3. Shadows, and a key light strong enough for them to read. An image-based
     light comes from every direction and so casts nothing; the key was 1.4 and
     is 2.4, because a shadow map against a room that bright is a shadow map
     paid for and not spent. `normalBias` in world units -- millimetres, in
     this scene -- rather than a clip-space `bias`, because the shadow camera is
     refitted to the scene every time a board or a part changes size.

  4. `NeutralToneMapping`, refusing ACES on the grounds that the colours here
     are measurements: #313d63 is the Uno's solder mask read out of PICSimLab's
     artwork and a film look would restate it as something else.

## THE STRAIGHT LINE ACROSS THE CAPACITOR LIDS IS NOT A BUG

This was the thing that looked worst and it cost five experiments. Ruled out,
each with a rendered pair on disk:

  * NOT the six-plane room's corner: it survived a graded sphere.
  * NOT a hard-edged softbox: it survived a softbox that fades to nothing.
  * NOT the environment at all: `envoff-cans.png` has no environment and the
    line is still there.
  * NOT a normal discontinuity: `mat-normal.png` paints the normal directly and
    the lid is smooth and uniform.
  * NOT two colour groups meeting: `mat-white.png` is unlit flat white and has
    no line.

What is left, and what every one of those is consistent with: **the lid is a
shallow CONE and the line is the key light's terminator on it.** A cone's
normal varies with azimuth and not along its generators, so a directional light
divides it into a lit half and an unlit half separated by a straight line
through the apex -- which is exactly the picture, and is correct rendering of
the geometry KiCad published. A real electrolytic has a flat stamped lid; the
simplification is the model's, not this repository's.

Not chased further. If anyone wants it gone the question is whether to use a
different capacitor model, not whether to change the renderer.

## LEFT UNDONE, DELIBERATELY

  * `ANGULAR` stays at 0.5. The measurement is now written down beside it, and
    the reason not to move it is that 0.2 costs 2.19x the bytes and buys 0.95%
    of the pixels -- most of which the weld got for nothing.
  * The PCB artwork as a texture, still blocked on the licence question.
  * Ambient occlusion. A shadow map darkens what the KEY light cannot reach and
    the environment still reaches everywhere, so a crevice is lit from inside.
    That is the next largest thing and it is its own ticket.
