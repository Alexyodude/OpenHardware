---
id: OH-88
title: Two renderer settings are written down and a third value is what runs
status: done
priority: P2
created: '2026-08-28'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

FOUND BY OPENING THE PAGE AS A READER DOES, while answering "why is the 3D
model not loading". The model loads. What the console shows is two settings this
repository writes down and the renderer does not use, both introduced by OH-85:

    THREE.sigmaRadians, 0.06, is too large and will clip, as it requested
    30 samples when the maximum is set to 20

    THREE.WebGLShadowMap: PCFSoftShadowMap has been deprecated.
    Using PCFShadowMap instead.

## 1. `STUDIO_BLUR` IS 0.06 AND THE PREFILTER APPLIES 0.04

`PMREMGenerator._blur` computes `samples = 1 + floor(STANDARD_DEVIATIONS *
sigmaPixels)` and refuses to exceed `MAX_SAMPLES = 20`
(`webui/static/vendor/three.module.js:3224`). Samples scale linearly with
sigma, and the warning's own numbers give the conversion: 0.06 asks for 30, so
**0.04 asks for exactly 20 and is the ceiling.** That is why three.js's own
`RoomEnvironment` uses 0.04, and why this constant was 0.04 before OH-85 raised
it.

So every picture measured and committed under OH-85 was rendered at the 0.04
blur while the source said 0.06. Nothing rendered is wrong; the file is.

## 2. `PCFSoftShadowMap` IS DEPRECATED IN r185

`webui/static/vendor/three.module.js:9150` warns and substitutes
`PCFShadowMap`. So the shadows shipped in OH-85 are PCF, the source says
PCFSoft, and `test_the_scene_casts_shadows_and_everything_in_it_takes_part`
asserts the string that is not in effect -- a test agreeing with a comment
rather than with the program.

## WHY THIS IS ITS OWN TICKET AND NOT A FOOTNOTE

`CLAUDE.md` records that this repository has twice caught rule prose drifting
out of sync with the checker beside it. This is the same failure inside one
file: two constants whose stated values are not the values used, one of them
pinned by a test that therefore proves nothing. Both were introduced with
measurements attached, which is what makes them worth writing down -- the
measurements were real and the settings they were attributed to were not.

## DONE WHEN

The page loads with the console clean apart from the one known `X4122` float
warning from the D3D backend, both constants say what the renderer uses, and
the tests assert the effective values rather than the written ones. And the
rendered frame is unchanged, because if it changes then one of these was doing
something after all.
