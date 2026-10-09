// OpenHardware — the board in three dimensions, with its pins live.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this draws, and what it is careful not to claim
//
// **A footprint, extruded. Not a model of the board.** Every coordinate here
// comes from `webui/boards/<board>.json`, whose own `derivation` field says
// where it came from: "Pad centres are exact to three decimal places in
// millimetres ... Nothing here was measured off an image." So the pads are the
// vendor's and the outline is the vendor's courtyard.
//
// What is NOT the vendor's is the third dimension. There is no `.kicad_pcb`
// and no `.gltf` for any board in this repository -- OH-29 measured that and
// OH-30 was blocked on it for a day -- so the slab's thickness is a constant
// and there are no components on it. A reader must not mistake this for a
// render of the real thing, which is why the panel says so in words and why
// this comment is the first thing in the file.
//
// The distinction that matters: a shape invented from nothing would be the
// "generic rectangle" OH-30 forbids. A shape whose outline and pad positions
// are the vendor's, extruded by a stated constant, is a drawing of real data
// with one axis missing. Saying which is which is the whole job.
//
// ## Why the palette is read from CSS rather than written here
//
// OH-16 folded `targets.html` back into `emulator.html` precisely so there
// would not be two pages with two palettes drifting apart. A colour written as
// a hex literal in this file is a third palette, and it would be wrong in
// whichever theme it was not authored for. So every colour is read from the
// custom properties `emulator.css` defines, and `refreshTheme` re-reads them
// when the theme changes -- which is what makes "renders in both themes" a
// property of the stylesheet rather than a thing this file has to get right
// twice.
//
// ## The one thing this file decides on its own
//
// Nothing about *state*. Which pins exist, where they sit, what they are
// connected to and what each is doing all arrive from `webui/api.py`'s
// `pin_view` and `pin_levels`, which are Python and are tested. A pad drawn
// bright here is only ever a picture of a register this repository read.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Rope } from "./wires.js";
import { analyse } from "./circuit.js";
import { dressPart, makeTarget, setPartState, terminalPoint, BENCH_GAP,
         BENCH_PITCH } from "./parts.js";

//: World units per image pixel. The same 0.1 `scene3d.js` uses, so a 196px
//: XIAO becomes ~20 units and a 402px Uno ~40 -- both framed sanely by the
//: camera distance below without a per-board special case.
const SCALE = 0.1;

//: Millimetres, times `PX_PER_MM` times `SCALE`. A real 1.6 mm PCB at the
//: 8 px/mm the board JSONs were generated at.
//:
//: **This is the invented axis**, and it is one number rather than a shape so
//: that it is obvious which part of the drawing is not sourced.
const PX_PER_MM = 8.0;
const BOARD_MM = 1.6;
const BOARD_THICKNESS = BOARD_MM * PX_PER_MM * SCALE;

//: A header pin, as a disc lying on the board's top face.
//:
//: **It used to be a post standing 0.9 units proud, and that was a drawing of
//: a board nobody makes.** A XIAO's header pins are castellated pads: plated
//: half-holes in the edge of the PCB, flush with it. Once the vendor's own
//: model arrived and those pads were visible in gold underneath, fourteen grey
//: cylinders floating above them stopped reading as pins and started reading
//: as a mistake -- which is what they were.
//:
//: So the marker lies *on* the board now. `PAD_LIFT` is the gap that keeps it
//: from z-fighting with the surface it sits on, and it is the smallest number
//: that reliably does: at 0.001 the two planes flicker as the camera turns.
const PAD_RADIUS = 0.42;
const PAD_HEIGHT = 0.06;
const PAD_LIFT = 0.01;

//: Millimetres from a pad's centre that a triangle may be and still be that
//: pad's pin.
//:
//: **The pins are on a 2.54 mm pitch, so anything under 1.27 cannot reach a
//: neighbour** -- which is the only error that would matter, because it would
//: light the wrong pin and look entirely convincing. An Arduino Uno's header
//: pin is a 0.64 mm square post and a XIAO's castellation is a 1.0 mm plated
//: half-hole, so 1.1 covers both with room and still stops 0.17 mm short of
//: the midpoint between two pins.
//:
//: Measured on the shipped models, 2026-08-28: the Uno's `IOH` header holds
//: 440 gold vertices above the board in eleven columns at exactly 2.54 mm --
//: 44 per pin for ten pins -- and the XIAO-RP2040's PCB solid holds 1,660
//: near its long edges in seven columns of 228.
//:
//: **AND THE DISTANCE FROM EACH PAD TO THE PIN UNDER IT IS NOT ONE NUMBER**,
//: which is the thing this constant cannot fix and must not hide. On the
//: Arduino Uno, whose pad map is the one in this repository that was TRACED
//: off PICSimLab's artwork rather than generated from a footprint:
//:
//:      14 pads   0.05 - 0.07 mm    0-7, A0-A5, VIN -- exact
//:      11 pads   0.65 - 0.77 mm    8-13, 5V, 3V3, RESET, IOREF, NC
//:       5 pads   1.21 - 3.84 mm    GND, 6, SCL, AREF, SDA
//:
//: The middle group is two whole headers offset together. Widening this
//: constant to reach the last five would take it past 1.27 -- half the pitch
//: -- where a pad starts claiming its NEIGHBOUR's pin and lights the wrong
//: one convincingly. So it stays here and those five keep an invisible
//: collider.
//:
//: **AND IT IS NOT THE TRACED PAD MAP THAT IS WRONG**, which is what OH-96
//: settled and what this note said until it did. That map agrees with
//: Arduino's own EAGLE board file to a worst of 0.008 mm per axis -- and,
//: more to the point, to a worst of 0.072 mm under the SINGLE ISOTROPIC SCALE
//: this file applies at `group.scale.setScalar`, which is nine times smaller
//: than the smallest disagreement listed above.
//: `test_the_unos_traced_pads_agree_under_one_scale_too_which_is_what_the_page_uses`
//: holds both numbers.
//:
//: The cause was NONE of the estimators -- OH-115's own close note measured
//: the bounding-box estimate as costing seventeen MICROmetres -- it was the
//: image-y-to-scene-z mapping negating y twice, which mirrored every pad
//: onto the row opposite its pin, silently right 28 times out of 32 because
//: the rows share a grid. Fixed at the pad line above; the numbers in this
//: table are the mirror's fingerprint, kept as the record of what a wrong
//: sign looks like from the outside.
const PIN_REACH_MM = 1.1;

//: The group a board file gives a pad on the board's UNDERSIDE (OH-216):
//: `UNDERSIDE` in `tools/import_board.py`, which writes it, and the one place
//: here that spells it.
//:
//: **Such a pad's pin is under the board, so it is carved out of the metal
//: under the board or out of nothing.** A XIAO SMD footprint's test points
//: and battery pads are on the module's underside, and until this every one
//: of them took the topside metal standing over it -- a chip's leads, a
//: trace, a capacitor's end -- recoloured it as a pin and anchored the wire
//: there: 1557 to 5450 stray triangles a board on the six OH-215's review
//: counted. A pad on no stated side is a topside pad, as every pad was.
const UNDERSIDE = "underside";

//: How brightly a real pin glows in its state's colour.
//:
//: **The state is EMITTED, not painted on, and the first attempt got that
//: wrong.** Blending the state colour into the metal was tried first and
//: measured: brass `#dbbc7e` with `high` mixed 72% of the way in comes out
//: `#7c8a61`, a dull green, while `input` comes out `#90897b`. Two muddy
//: browns three pixels wide -- the pin had stopped looking like brass and the
//: state still could not be read. Measured under OH-95 on the brass's key
//: then, `#b58136`, as `#66744b` and `#7e726c`; recomputed for its key since
//: OH-214 by the same blend, which those two reproduce exactly: linear light,
//: into the light theme's `--changed` `#0b6e52` and `--muted` `#5e6c7a`.
//:
//: Emission is the right mechanism because it is the right metaphor: the pin
//: is still made of the metal the vendor published, and what changed is that
//: it is doing something. A lit pin is brass with a coloured light in it,
//: which reads at three pixels where a hue shift does not.
//:
//: 0.85 rather than 1.0 so a driven pin is clearly lit without blowing out to
//: flat colour under the tone curve, which would put it back where the
//: painted version was.
const PIN_GLOW = 0.85;

//: How far back the camera sits, as a multiple of the board's longest side.
//: Framing from the geometry rather than from a fixed distance is what lets
//: one number serve a 196px XIAO and a 402px Uno.
const CAMERA_PULL = 1.5;

//: WHICH WAY THE READER IS LOOKING FROM, and it is a direction so that
//: something else can be aimed at its reflection.
//:
//: **This used to be three literals inside `frameScene` and that is the whole
//: reason OH-92 existed.** The softbox sat at the zenith, which is where a
//: bench lamp goes and is not where a flat board sends its reflection: a
//: surface with normal +y returns what lies in the MIRROR of the view
//: direction, and the mirror of this vector about +y is `(-x, y, -z)`, or 48.3
//: degrees of elevation on the far side of the board. The softbox's own
//: half-angle is 14.5 degrees, so at the zenith it missed that by 27 -- the
//: clear coat OH-90 measured and the albedos OH-91 corrected were both
//: working, and both invisible at the only camera most readers ever see.
//:
//: So `studio()` reads this and puts the light where the board can return it.
//: Keeping them as two numbers that happened to agree would be a thing to get
//: out of step, and this file has already paid for that once: `#313d63` was
//: converted to linear in `readPalette` and not in the writer twenty lines
//: away, for as long as both have existed.
const CAMERA_FROM = { x: 0.1, y: 0.85, z: 0.75 };

//: Which way the key light comes from, as a direction rather than a place.
//:
//: **It used to be a position, `(12, 24, 10)`, and that was a bug waiting for
//: a shadow.** A `DirectionalLight` takes its direction from position minus
//: target, so a fixed position is a fixed direction only while the target
//: stays at the origin -- and the moment the light had to cast, the shadow
//: camera had to be moved out to where it could see the whole board. The
//: direction is what was meant; `frameScene` multiplies it by the scene's own
//: radius. High, over the reader's left shoulder, which is where a bench lamp
//: is and where the eye expects a shadow to fall away from.
//: The directions this scene is lit from, and EVERY ONE OF THEM CASTS.
//:
//: **This is the hemisphere sampled three times, and it must not be called
//: ambient occlusion.** It is the same integral -- how much of the sky a
//: surface can see -- estimated with three samples instead of none. A crevice
//: hidden from all three goes dark; one open to the side keeps that light. It
//: is crude where a per-pixel method is exact, and it is honest about which it
//: is.
//:
//: The alternative that was NOT taken is worth the two lines: baking occlusion
//: into vertex colours needs somewhere to write it, and the composed Arduino
//: Uno's PCB is 108 vertices over 68.6 x 53.3 mm -- one every six millimetres,
//: measured 2026-08-28. The 0.3 mm gap beside a DIP-28's leg has nowhere to
//: live. Its components have the density; the thing they sit on does not, and
//: it is the thing they sit on that needs the shadow.
//:
//: `share` sums to one and is multiplied by `LIGHT_TOTAL`, so the three can be
//: rebalanced without the scene changing brightness. The first is the key --
//: high, over the reader's left shoulder, which is where a bench lamp is. The
//: second is opposite and lower, so the side the key cannot reach is not black.
//: The third is shallow and from the front, which is what stops a component's
//: near face reading as a silhouette.
const LIGHTS = [
  { x: 0.42, y: 0.84, z: 0.35, share: 0.50 },
  { x: -0.62, y: 0.58, z: -0.52, share: 0.28 },
  { x: -0.18, y: 0.46, z: 0.87, share: 0.22 },
];

//: The bench, and the only light in this scene that comes from below.
//:
//: **Every one of the three above has a positive y, so until OH-110 gave the
//: board an underside worth seeing, nothing lit one.** A shot of the XIAO
//: ESP32-C3 from beneath measured a MEDIAN LUMINANCE OF ZERO against 82.6 from
//: above -- not "darker because it faces away", unlit. What is down there is
//: the vendor's own printing: 1,514 silkscreen strokes including the words
//: "Seeed Studio", the battery pads with their + and -, and 44 of the board's
//: castellated half-holes.
//:
//: **It does not cast, and that is measured rather than saved effort.** The
//: three above cast because they are a three-sample estimate of how much sky a
//: crevice can see. This is not sky -- it is the diffuse return off whatever
//: the board is lying on -- and there is nothing under the board to occlude
//: it: of the 1 to 21 parts each vendor places on the back, `CORRESPONDENCE`
//: draws NONE, so the underside is a flat plane of mask, copper and ink.
//:
//: **Its share is added to `LIGHT_TOTAL` rather than taken out of it.** The
//: three above sum to one and were balanced against the topside exposure OH-86
//: measured; a light from below contributes nothing to an upward-facing
//: surface, so sharing it out would darken a picture it cannot brighten. It is
//: nearly straight down for the same reason -- the 0.12 and 0.32 are there so
//: that a component's side face gets a hint of it, which is what bounce does,
//: and they are small enough that the topside statistics do not move.
//:
//: **0.25 was swept and measured, not chosen.** Five shares, each shot from
//: above and below on the ESP32-C3 against the running server, luminance over
//: every pixel that is not the page:
//:
//:      share    top median   under median   under p90   top mean
//:       0.00          82.6            0.0        34.4      115.6
//:       0.15          84.0           18.0       102.3      116.1
//:       0.25          85.0           34.0       132.1      116.2
//:       0.35          85.0           49.0       156.3      116.3
//:       0.50          86.0           66.0       180.5      116.4
//:
//: **The top mean moves 0.7% across the whole sweep**, which is the design
//: claim holding: a light from below cannot brighten a surface facing up, and
//: what does move is component side faces.
//:
//: 0.25 puts the underside's median at 41% of the topside's -- the shaded side
//: of a board lying over a bench, which is what it is -- while its 90th
//: percentile, the ink and the copper, stands at 3.9x the mask around it, so
//: the printing reads. At 0.50 the two sides are within a fifth of each other
//: and the board stops having a lit side at all.
const BOUNCE = { x: 0.12, y: -0.94, z: 0.32, share: 0.25, casts: false };

//: Their intensities added together.
//:
//: **Raised from the key's own 2.4 because the environment gave some back.**
//: An image-based light comes from every direction at once, so it casts
//: nothing and darkens no crevice: every unit of brightness that lives there
//: is a unit no shadow can ever subtract from. Moving some of it here is the
//: whole mechanism, and `ENVIRONMENT_SHARE` is the other half of the trade.
//:
//: **AND THEN BOTH WERE SCALED DOWN BY 0.62, WHICH IS A SEPARATE FACT.** This
//: was 5.2 against a room of 0.45, and at that exposure the Arduino Uno's
//: solder mask rendered with a median colour of rgb(150, 166, 206) -- against
//: the #313d63 = rgb(49, 61, 99) that `tools/compose_board_3d.py` read out of
//: PICSimLab's artwork. THREE TIMES ITS OWN ALBEDO, which is why a navy board
//: came out pale periwinkle and why the blacks came out grey: over-lighting
//: does not brighten a picture, it desaturates it. At 0.62 of that the median
//: is rgb(115, 129, 163), which is a lit navy rather than a washed-out one.
//:
//: The RATIO is what OH-86 measured and it is held to within one percent --
//: 5.2/0.45 is 11.56 and 3.2/0.28 is 11.43 -- so the crevice contrast that
//: ticket bought survives the rescale intact. Measured after: the tonal
//: entropy of the close-up went 4.855 to 5.635 bits and the darkest tenth of
//: the DIP-28 crop fell from 0.244 of its mean to 0.170.
const LIGHT_TOTAL = 7.0;

//: How much of the room's own brightness survives, as `scene.environmentIntensity`.
//:
//: **Not zero, and it must never be.** The environment is what a metal
//: reflects -- turn it down to nothing and `metalness` is a lie again, which is
//: the whole argument OH-82 made. What it may not do is supply so much of the
//: light that a shadowed crevice is still fully lit.
//:
//: Four settings were rendered and measured on a 4x crop of the DIP-28 where it
//: meets the board, `LIGHT_TOTAL` raised each time to hold the exposure. The
//: mean of the darkest tenth is the statistic a few hundred crevice pixels can
//: actually move, and it is given against the crop's own mean so that dimming
//: the whole picture does not read as a win:
//:
//:      share    darkest tenth    over the crop's mean
//:      (before)     42.63              0.269
//:      0.62         37.03              0.244
//:      0.45         35.54              0.234
//:      0.30         33.91              0.223
//:
//: **Those shares were measured against `LIGHT_TOTAL` 5.2 and this is 0.28
//: because both were then scaled by 0.62** -- see that constant, which explains
//: why. The ratio between them is what this table is about and it is unchanged
//: to within one percent; the absolute level is a different question and was a
//: different mistake.
//:
//: **The knee is at 0.45, and the step past it is where this stops being free.**
//: Two thirds of the available darkening has happened by then; the remaining
//: third costs the metals the only thing they have to reflect, and at 0.30 the
//: capacitor lids and the barrel jack come out visibly duller than the moulded
//: plastic beside them -- which inverts the one relationship anybody can check
//: against a real board. That last sentence is a judgement and is written as
//: one. The numbers above it are not.
//:
//: **0.61 TO 0.35 UNDER OH-92, AND THE PREMISE OF THE PARAGRAPH ABOVE IS WHAT
//: CHANGED.** That judgement was measured with the softbox at the zenith and
//: `bright` at 18.0, where the environment was the only thing the metals had.
//: OH-92 aimed the softbox at the board's mirror direction and made it four
//: times brighter, so at a LOWER share the metals now have MORE to reflect
//: than they did at 0.45 before. Re-checked rather than inherited: at 0.35 the
//: USB shell, both capacitor lids and the barrel jack still read as metal, and
//: at 0.30 the shell goes flat and grey -- so the knee moved, it did not
//: vanish, and this sits one step above it.
//:
//: What it buys is the solder mask's colour back. The room is what washes a
//: coated board out, and with the softbox where the board reflects it, the
//: share is the only knob that separates the two claims:
//:
//:      share   sheen   the board where there is NO highlight
//:      0.61    2.086   rgb(101, 112, 154)  saturation 0.344
//:      0.45    2.252   rgb( 90, 102, 145)             0.379
//:      0.40    2.320   rgb( 87,  99, 142)             0.387
//:      0.35    2.341   rgb( 82,  95, 138)             0.406
//:      0.30    2.322   rgb( 78,  91, 135)             0.422
//:
//: `sheen` is the mask's brightest tenth over the mean of its own darker half
//: -- how far the highlight stands above the board carrying it, which is the
//: whole of what the user asked for and is a RATIO, so dimming the picture
//: cannot fake it. It is flat to within one percent across 0.30 to 0.40, so it
//: does not choose; the colour does, and the metals set the floor.
//:
//: **The ratio to `LIGHT_TOTAL` is 20.0 here against OH-86's 11.4, and that is
//: deliberate rather than drift.** OH-86 held that ratio because it was moving
//: light between two sources that did the same job. This moves it out of the
//: source that cannot cast a shadow and into one that can, which is the same
//: direction OH-86's own table wanted and stopped short of for a reason that
//: no longer applies.
const ENVIRONMENT_SHARE = 0.35;

//: The shadow map's resolution. 2,048 across a bounding sphere of about 45 mm
//: is a texel every 44 um, which is finer than the 0.05 mm chord error every
//: mesh in this scene was tessellated to -- so the shadow cannot resolve less
//: than the geometry does, which is the right place to stop.
const SHADOW_TEXELS = 2048;

//: Millimetres a surface is pushed along its normal before it is tested
//: against the shadow map, to stop it shadowing itself.
//:
//: **World units, which is why this is a number of millimetres and not a
//: mystery.** 60 um is larger than one shadow texel across the Uno and smaller
//: than a DIP-28's leg is thick, so a surface cannot shade itself and a shadow
//: cannot come unstuck from the thing casting it.
const SHADOW_BIAS_MM = 0.06;

//: **The one number in this file that is a colour and is not from the
//: palette, and it is not a palette colour.** It is illumination: white light
//: leaves every material the colour the stylesheet said. Tinting it would
//: shift all four pad states and the board together, which is the one way to
//: be wrong in both themes at once.
const NEUTRAL_LIGHT = 0xffffff;

//: State -> which CSS custom property paints it.
//:
//: **Ordered by CONTRAST against the board, not by lightness**, and that
//: distinction is the whole reason this comment is long. The board is
//: `--surface`:
//:
//:   high     `--changed`  the only hue in the scene
//:   low      `--ink`      maximum contrast -- driven, and driven off
//:   input    `--muted`    medium -- not driven at all
//:   unknown  `--line`     minimum -- barely separable from the slab
//:
//: **Lightness flips between the themes and contrast does not.** Two versions
//: of this got it wrong in opposite directions, and each was found by looking
//: at a screenshot rather than by any test:
//:
//:   1. board `--sunken` with `unknown` also `--sunken`: #0d1115 on #0d1115 in
//:      the dark theme, so the three power pads vanished into the slab.
//:   2. `low` as `--sunken` and `unknown` as `--line`: fine in the dark theme
//:      (#0d1115 against #2a333d) and collapsed in the light one, where they
//:      are #e4e8ed and #d3dae1 -- two nearly identical whites on a white
//:      board, so a pin driven low was indistinguishable from a pin nobody
//:      models.
//:
//: A contrast ramp has neither failure, because `--ink` is *defined* as the
//: colour that reads against `--surface` in whichever theme is on. The cost is
//: that a low pin is the brightest thing on a dark board, which looks briefly
//: backwards and is unambiguous -- and the table beside the canvas says the
//: word anyway.
//:
//: **`unknown` is recessive rather than red.** It is not an error and not a
//: low pin: it is a pad this repository cannot answer for, and every other
//: "not modelled" in this UI is quiet grey. See `webui/api.py`'s `PIN_STATES`.
const STATE_VARIABLE = {
  high: "--changed",
  low: "--ink",
  input: "--muted",
  unknown: "--line",
};

//: glTF's four-byte magic, `glTF`, and its two chunk types.
const GLB_MAGIC = 0x46546c67;
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;

//: glTF component types, for the two this reader accepts.
const FLOAT = 5126;
const UNSIGNED_INT = 5125;

//: The one glTF extension this reader understands.
//:
//: **A PCB is two layers and every other surface here is one.** Solder mask is
//: pigmented epoxy under a cured, near-transparent surface: the pigment
//: scatters and the surface over it reflects, which is why a board brightens
//: as you tilt it and a moulded body does not. `MeshStandardMaterial` has one
//: roughness and it has to describe the pigment, so the board had no sheen
//: whatever the environment did.
//:
//: Read here rather than by vendoring `GLTFLoader`: this file's reader is
//: deliberately the narrow slice `tools/import_3d_model.py` writes, and the
//: extension is two numbers.
const CLEARCOAT = "KHR_materials_clearcoat";

//: What a solder mask is made of, for the board this file draws ITSELF.
//:
//: **Duplicated from `FINISHES` in `tools/import_3d_model.py` on purpose, and
//: this is the one place that is defensible.** Every other material in this
//: scene arrives inside a mesh file, measured, and this file only reads them.
//: The extruded slab has no mesh and no measurement: it is drawn for a board
//: nobody publishes a model of, so there is nothing to read it out of. Copying
//: three numbers is better than importing a Python table into a browser or
//: teaching the API to serve it, and
//: `test_the_extruded_slab_is_the_same_substance_as_a_measured_one` is what
//: stops the two drifting apart.
const SOLDER_MASK = { roughness: 0.35, coat: 0.85, coatRoughness: 0.08 };

/**
 * One glTF material, as the three.js material it describes.
 *
 * **`MeshPhysicalMaterial` only where there is a coat to justify it.** It is a
 * superset of `MeshStandardMaterial` and a more expensive shader, and every
 * surface in this scene except the two solder masks is a single layer that the
 * cheaper one describes exactly. Building the expensive one everywhere would
 * cost the whole board to make two faces right.
 */
function surfaceOf(material, red, green, blue) {
  const pbr = material.pbrMetallicRoughness;
  const settings = {
    // **The name is load-bearing.** `tools/import_3d_model.py` writes the
    // colour there and `parts.js` finds a part's lens by it; three.js drops it
    // silently if it is not asked for, and a part would then never light.
    name: material.name ?? "",
    color: new THREE.Color(red, green, blue),
    roughness: pbr.roughnessFactor,
    metalness: pbr.metallicFactor,
    side: THREE.DoubleSide,
  };
  const coat = material.extensions?.[CLEARCOAT];
  if (!coat) return new THREE.MeshStandardMaterial(settings);
  return new THREE.MeshPhysicalMaterial({
    ...settings,
    clearcoat: coat.clearcoatFactor ?? 0,
    // glTF's default is 0 when the key is absent, which is a mirror-flat coat.
    // Written by the importer either way; defaulted here so a file from
    // somewhere else cannot turn the board into glass by omission.
    clearcoatRoughness: coat.clearcoatRoughnessFactor ?? 0,
  });
}

/**
 * Read the narrow slice of glTF that `tools/import_3d_model.py` writes.
 *
 * **Hand-written rather than `GLTFLoader`, and the reason is the narrowness
 * rather than the dependency.** This repository already vendors one three.js
 * addon, so vendoring a second would be no new kind of thing. What the loader
 * would buy is support for scene graphs, skins, animations, textures, sparse
 * accessors and a dozen KHR extensions -- none of which appears in a file this
 * repository generated ninety lines away. Sixty lines that accept exactly what
 * is written and **throw on anything else** are easier to be sure of than two
 * hundred kilobytes that accept everything.
 *
 * That last clause is the point: every unsupported case below is a `throw`,
 * because the file is ours, so anything unexpected means the writer changed
 * and the reader did not.
 */
function readGlb(buffer) {
  const head = new DataView(buffer);
  if (head.getUint32(0, true) !== GLB_MAGIC) throw new Error("not a glb");
  if (head.getUint32(4, true) !== 2) throw new Error("glTF 2.0 only");

  let offset = 12;
  let json = null;
  let bin = null;
  while (offset < buffer.byteLength) {
    const length = head.getUint32(offset, true);
    const kind = head.getUint32(offset + 4, true);
    const body = buffer.slice(offset + 8, offset + 8 + length);
    if (kind === CHUNK_JSON) json = JSON.parse(new TextDecoder().decode(body));
    else if (kind === CHUNK_BIN) bin = body;
    offset += 8 + length;
  }
  if (!json || !bin) throw new Error("a glb needs a JSON chunk and a BIN chunk");

  const read = (index, Kind, per) => {
    const accessor = json.accessors[index];
    if (accessor.sparse) throw new Error("sparse accessors are not written here");
    const view = json.bufferViews[accessor.bufferView];
    if (view.byteStride) throw new Error("interleaved buffers are not written here");
    const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
    return new Kind(bin, start, accessor.count * per);
  };

  const group = new THREE.Group();
  for (const primitive of json.meshes[0].primitives) {
    const geometry = new THREE.BufferGeometry();
    const position = json.accessors[primitive.attributes.POSITION];
    const normal = json.accessors[primitive.attributes.NORMAL];
    const index = json.accessors[primitive.indices];
    if (position.componentType !== FLOAT || normal.componentType !== FLOAT) {
      throw new Error("positions and normals are written as floats");
    }
    if (index.componentType !== UNSIGNED_INT) {
      throw new Error("indices are written as unsigned ints");
    }
    geometry.setAttribute("position", new THREE.BufferAttribute(
      read(primitive.attributes.POSITION, Float32Array, 3), 3));
    geometry.setAttribute("normal", new THREE.BufferAttribute(
      read(primitive.attributes.NORMAL, Float32Array, 3), 3));
    geometry.setIndex(new THREE.BufferAttribute(
      read(primitive.indices, Uint32Array, 1), 1));

    const material = json.materials[primitive.material];
    const [red, green, blue] = material.pbrMetallicRoughness.baseColorFactor;
    group.add(new THREE.Mesh(geometry, surfaceOf(material, red, green, blue)));
  }
  return { group, extras: json.asset.extras ?? {} };
}

//: Everything mutable, in one object rather than eight module-level `let`s.
//: `dispose` empties it, and a reader can see the whole lifetime at once.
const view = {
  //: What the pointer is resting on, with what `dehover` must put back.
  hovered: null,
  renderer: null,
  scene: null,
  camera: null,
  controls: null,
  lights: null,      // the three that light the scene, and all three cast
  board: null,
  model: null,       // the vendor's mesh, once it has arrived
  slab: null,        // the PCB alone, for collision; see refreshColliders
  //: A box per component the board carries, in the model's own frame. Empty
  //: for a fetched vendor model, which is a single mesh that never said where
  //: its components are -- so a wire keeps passing through those, and that is
  //: the honest default rather than a guess at where a chip might be.
  solids: [],
  //: The board's own LEDs that a pin drives, as `{label, mesh}` (OH-169).
  //: Refilled whenever a model is drawn, from the board module's `LED_PARTS`
  //: joined to `solids` on the component's name -- so a board that names no
  //: LED, or names one its model does not draw, gets an empty list and draws
  //: nothing. That is twenty-five of the twenty-six boards, so it is the
  //: ordinary path rather than the error path.
  leds: [],
  //: Scene units per millimetre, decided once when a board is drawn.
  //:
  //: **One number, because there were two and they disagreed.** The board's
  //: model derives its scale from the pad field it shares with the page;
  //: `addPart` used the constant 8 px/mm that generated board JSONs use. On
  //: the Arduino Uno, whose pad map was traced off artwork at 5.638, that drew
  //: every bench part 1.42 times too large beside a board drawn at its real
  //: size. Anything putting millimetres into this scene reads this.
  mmScale: PX_PER_MM * SCALE,
  colliders: [],     // what a wire may not pass through; see refreshColliders
  floor: -Infinity,  // the bench top
  //: What a pin of this board's chip can drive, from `/api/board/pins`, or
  //: null for a board whose module publishes no electrical model. Without it
  //: no circuit is solved and every wired part reports unanswerable, which is
  //: the same honest degradation the panel's three captions make about a
  //: board's 3D model.
  supply: null,
  //: The last thing `circuit.js` said about the bench, kept so that `parts()`
  //: can hand the page a sentence per part without solving again.
  circuit: null,
  //: Pin name -> EVERY marker drawn for it, and the plural is OH-117.
  //:
  //: **A name can mean more than one pad and this held one.** An Arduino Uno
  //: has three pads called GND -- the board file lists all three, at three
  //: places, because that is what the board has -- and a `Map` keyed by name
  //: kept whichever came last. The other two were never made: no raycast
  //: target, so no wire could start there, and no explanation on the page
  //: either. 32 pads went in and 30 came out, measured with `describe()`.
  //:
  //: They are one NET, which is what makes the name the right key: `analyse`
  //: says so at `groundOf`, and `webui/api.py` sends one level per name. So
  //: they light together and any of them can be wired.
  pads: new Map(),
  bench: null,       // parts and wires; outlives a board change
  parts: [],         // every part on the bench, in the order they arrived
  wires: [],         // every wire, connected or being dragged
  //: The same wires' ropes, refilled once a frame and handed to each of them
  //: as what it may not pass through. Derived, never the source of truth:
  //: see the animation loop, which is the only thing that writes it.
  ropes: [],
  dragging: null,    // the wire under the pointer, if there is one
  last: 0,           // the previous frame's timestamp, in milliseconds
  palette: {},
  frame: 0,
};

function readPalette() {
  const style = getComputedStyle(document.documentElement);
  const read = (name) => new THREE.Color(style.getPropertyValue(name).trim() || "#888");
  return {
    ground: read("--ground"),
    // The slab, and it is `--surface` rather than `--sunken` so that the
    // recessive pad states stay darker than the thing they stand on. See
    // STATE_VARIABLE.
    surface: read("--surface"),
    line: read("--line"),
    // What "this went wrong" is in whichever theme is on. `parts.js` paints a
    // part destroyed by its own absolute maximum with it.
    halt: read("--halt"),
    states: Object.fromEntries(
      Object.entries(STATE_VARIABLE).map(([state, name]) => [state, read(name)])
    ),
  };
}

//: Luminances for the studio below: the ceiling, the walls, the floor.
//:
//: **Numbers rather than colours, and that is not a dodge.** A greyscale
//: environment leaves every material the colour its own file said, which is the
//: same argument `NEUTRAL_LIGHT` makes two constants up -- tinting the light
//: would shift every material in the scene together and be wrong in whichever
//: theme it was not chosen for. `setScalar` takes a luminance, so there is no
//: colour written down here at all.
//:
//: Bright above, mid to the sides, dark below is what a bench under a ceiling
//: light looks like, and it is the gradient that makes a curved metal surface
//: read as curved: the top of a pin catches the ceiling and its flank catches
//: the wall, which is the whole reason to have an environment rather than
//: another ambient light.
const STUDIO = { ceiling: 1.0, wall: 0.38, floor: 0.06 };

//: How far the studio's walls sit from the origin. Only the ratios matter --
//: an environment map records direction and not distance -- so this is just
//: large enough to enclose the biggest board.
const STUDIO_SIZE = 60;

//: How far the prefilter blurs the room before storing it.
//:
//: **This used to be 0.04, and the comment beside it predicted the bug it then
//: had.** It said six flat planes meet at hard edges and a mirror-smooth
//: surface would reflect those edges as a visible box -- and that is exactly
//: what the Arduino Uno's two electrolytic cans did: each was cut by a
//: dead-straight diagonal seam, cream on one side and black on the other,
//: which is the corner between the ceiling and a wall seen in a polished
//: aluminium lid. Measured at 4x magnification on 2026-08-28.
//:
//: The room is a gradient now rather than a box, so there is no corner left to
//: reflect and this only has to take the edge off the softbox.
//:
//: **AND 0.04 IS A CEILING, NOT A PREFERENCE.** It was briefly 0.06, and the
//: prefilter clipped it back without the picture changing:
//: `PMREMGenerator._blur` computes `samples = 1 + floor(STANDARD_DEVIATIONS *
//: sigmaPixels)` and refuses to exceed `MAX_SAMPLES = 20`
//: (`vendor/three.module.js:3224`). Samples scale linearly with sigma, and the
//: console said 0.06 asked for 30 -- so 0.04 asks for exactly 20 and is the
//: most this generator can do. It is also what three.js's own
//: `RoomEnvironment` passes, for the same reason.
//:
//: Every frame measured under OH-85 was rendered at this blur while the source
//: claimed more, which is the defect and not the picture.
const STUDIO_BLUR = 0.04;

//: How many bands the graded sky is built from. A `SphereGeometry` at 24
//: latitude segments puts a vertex every 7.5 degrees, which is finer than
//: anything a prefiltered environment can resolve.
const SKY_BANDS = { around: 32, up: 24 };

//: The overhead softbox: how bright, how wide, and how high above the board.
//:
//: **Above 1.0 on purpose.** `PMREMGenerator` renders into a half-float
//: target, so a value brighter than white survives prefiltering and is what
//: gives a curved metal surface a highlight rather than a flat wash.
//:
//: **A DISC THAT FADES OUT AT ITS RIM, AND THE FADE IS THE WHOLE POINT.** The
//: first version of this was a bright rectangle, and it reproduced exactly the
//: fault it was written to remove: the Arduino Uno's electrolytic lids are
//: domed metal, a dome sweeps its reflection across a wide arc of the sky, and
//: any hard edge up there comes back as a dead-straight line drawn across the
//: lid. The old six-plane room drew that line with the corner between its
//: ceiling and its wall; a rectangular softbox drew the same line with its own
//: border. Measured on 2026-08-28 at 4x magnification, three times: the box,
//: the rectangle, and a sky with the gradient switched off -- the line
//: survived all three, and the only thing they had in common was an edge.
//:
//: So there is no edge anywhere in this room now. `bright` is the centre and
//: the rim falls to the ceiling's own luminance, so the disc has nothing to
//: reflect but its own gradient.
//:
//: **SMALL AND FIERCE RATHER THAN WIDE AND MILD, WHICH IS WHAT A HIGHLIGHT
//: IS.** It was radius 0.5 at 2.4, which at this height subtends about 78
//: degrees of sky -- most of it. A coated board reflecting that gets a wash
//: rather than a sheen, and the measurement is the same coat under two skies,
//: switched on and off under each:
//:
//:      sky            board's brightest tenth, coat off -> on
//:      radius 0.50        179.3 -> 181.6      +1.3%
//:      radius 0.16        148.0 -> 172.2     +16.3%
//:
//: **Twelve times the effect from the same two numbers in `FINISHES`.** A coat
//: can only return what is up there to be returned, so the source has to be
//: compact before a specular layer means anything -- a real softbox covers
//: perhaps 30 degrees and at 0.16 this one does. (The two pairs sit at
//: different exposures, so only the WITHIN-pair percentages are controlled;
//: those are the ones quoted.)
//:
//: `bright` rises with the square of the shrink so the room keeps roughly the
//: light it had: 0.5 to 0.16 is a nineteenth of the area, and 2.4 to 18.0 is
//: seven and a half times the intensity. The rest of the exposure is
//: `LIGHT_TOTAL`'s to settle, and it does.
//:
//: **`reach` IS A DISTANCE ALONG `CAMERA_FROM`'S MIRROR, NOT A HEIGHT**, and
//: the rename is the point of OH-92. It was `height: 0.62` and the disc hung
//: at `(0, 0.62 * STUDIO_SIZE, 0)`, which put a 14.5-degree source 27 degrees
//: away from the direction the board actually reflects toward the default
//: camera. `reach` is unchanged because it is half of what sets the half-angle
//: -- `atan(radius / reach)` -- and it is as far out as the disc can go and
//: stay inside the sky sphere, which is `STUDIO_SIZE` and drawn `BackSide`.
//:
//: **AND THEN THE RADIUS HALVED AGAIN, BECAUSE AIMING IT REVEALED THE REAL
//: SCALE.** At 0.16 the source subtends 28.9 degrees. Perspective makes the
//: board's own mirror direction sweep 35 to 69 degrees between its far and
//: near edges -- 34 degrees, measured from the camera `describe()` reports --
//: so a 28.9-degree source aimed at the middle covers very nearly the whole
//: face. That is not a highlight, it is a wash, and it is the same "wide and
//: mild" the table above rejects, arrived at from the other direction: at the
//: zenith the source was too wide to be a highlight and missed anyway, so the
//: fault was invisible.
//:
//: Radius swept at the default camera with `bright` held at the inverse square
//: so the comparison is of SHAPE and not exposure, at two different room
//: brightnesses so the peak is not an artefact of one:
//:
//:      radius  subtends   sheen at share 0.61   sheen at share 0.35
//:      0.160     28.9         1.612                  --
//:      0.110     20.1         2.005                2.017
//:      0.080     14.7         2.086                2.341
//:      0.055     10.1         2.037                2.288
//:
//: 0.08 is the peak under both, which is what makes it a setting rather than a
//: coincidence. Below it the source stops being able to cover the components'
//: curved faces; above it, it starts covering the board it should be crossing.
//:
//: `bright` still rises with the square of the shrink, 18.0 to 72.0, so the
//: room keeps the light it had -- the same rule as the 0.5-to-0.16 step above.
const SOFTBOX = { bright: 72.0, radius: 0.08, reach: 0.62, segments: 48 };

/**
 * A room, prefiltered into one texture, so that metal has something to reflect.
 *
 * **Built here rather than by vendoring `RoomEnvironment`.** That addon is not
 * in `webui/static/vendor/` and does not need to be: `PMREMGenerator` is
 * already exported by the vendored core, `fromScene` takes any scene, and what
 * RoomEnvironment does is put a handful of emissive boxes in one. Six planes
 * and three luminances is the whole of it, and it is easier to be sure of than
 * a file nobody in this repository would otherwise read.
 *
 * The result is installed as `scene.environment` and NOT as `scene.background`:
 * the background stays the palette's ground, because that is a UI surface and
 * has to agree with the page around it. This is illumination.
 */
function studio(renderer) {
  const room = new THREE.Scene();

  // **A graded sphere, where this used to be six flat planes.** The luminances
  // above are unchanged and so is the idea -- bright overhead, mid at the
  // horizon, dark below -- but a sphere has no corners, and a corner is what
  // the capacitor lids were reflecting as a hard black-and-cream seam. The
  // gradient is the whole point: a curved metal surface sweeping through it
  // gets a continuous ramp, which is what reads as curvature.
  const sky = new THREE.SphereGeometry(STUDIO_SIZE, SKY_BANDS.around,
                                       SKY_BANDS.up);
  const height = sky.getAttribute("position");
  const shade = new Float32Array(height.count * 3);
  for (let vertex = 0; vertex < height.count; vertex++) {
    // -1 at the floor, +1 at the ceiling. `smoothstep` rather than a straight
    // ramp so the horizon is a band rather than a crease -- a linear blend
    // still has a discontinuity in its slope, and a polished lid finds it.
    const up = height.getY(vertex) / STUDIO_SIZE;
    const t = Math.abs(up);
    const eased = t * t * (3 - 2 * t);
    const luminance = up >= 0
      ? STUDIO.wall + (STUDIO.ceiling - STUDIO.wall) * eased
      : STUDIO.wall + (STUDIO.floor - STUDIO.wall) * eased;
    shade[vertex * 3] = luminance;
    shade[vertex * 3 + 1] = luminance;
    shade[vertex * 3 + 2] = luminance;
  }
  sky.setAttribute("color", new THREE.BufferAttribute(shade, 3));
  room.add(new THREE.Mesh(sky, new THREE.MeshBasicMaterial({
    // Seen from the inside, and the colours are read as-is: a vertex colour is
    // already in the renderer's working space, which is where `setScalar`
    // leaves a luminance too. So the two halves of this room are on one scale.
    vertexColors: true, side: THREE.BackSide,
  })));

  // The softbox: a disc in the direction the board reflects the camera toward,
  // brightest at the middle and fading into the ceiling at its rim, so nothing
  // in this room has an edge. See `SOFTBOX` and `CAMERA_FROM`.
  const pool = new THREE.CircleGeometry(STUDIO_SIZE * SOFTBOX.radius,
                                        SOFTBOX.segments);
  const across = pool.getAttribute("position");
  const glow = new Float32Array(across.count * 3);
  const edge = STUDIO_SIZE * SOFTBOX.radius;
  for (let vertex = 0; vertex < across.count; vertex++) {
    const out = Math.hypot(across.getX(vertex), across.getY(vertex)) / edge;
    const fade = 1 - out * out * (3 - 2 * out);
    const luminance = STUDIO.ceiling
                    + (SOFTBOX.bright - STUDIO.ceiling) * fade;
    glow[vertex * 3] = luminance;
    glow[vertex * 3 + 1] = luminance;
    glow[vertex * 3 + 2] = luminance;
  }
  pool.setAttribute("color", new THREE.BufferAttribute(glow, 3));
  const light = new THREE.Mesh(pool, new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide,
  }));
  // **Where a flat board sends the default camera's reflection.** The board's
  // normal is +y, so the mirror of `CAMERA_FROM` about it is `(-x, y, -z)`:
  // the same elevation, the opposite side. Normalising first is what makes
  // `reach` a distance rather than a scale factor on an arbitrary vector, so
  // `atan(radius / reach)` stays the half-angle `SOFTBOX` was measured at.
  const facing = new THREE.Vector3(-CAMERA_FROM.x, CAMERA_FROM.y,
                                   -CAMERA_FROM.z).normalize();
  light.position.copy(facing).multiplyScalar(STUDIO_SIZE * SOFTBOX.reach);
  // `lookAt` and not a fixed rotation, because the direction is now derived.
  // A `CircleGeometry` lies in the xy plane facing +z, and `Object3D.lookAt`
  // on something that is not a camera or a light turns +z toward the target --
  // so the disc squares up to the board instead of being seen as a foreshort-
  // ened ellipse from it, which would shrink the source it was measured as.
  light.lookAt(0, 0, 0);
  room.add(light);

  const pmrem = new THREE.PMREMGenerator(renderer);
  const built = pmrem.fromScene(room, STUDIO_BLUR);
  pmrem.dispose();
  // The room itself is finished with the moment it has been prefiltered: what
  // survives is one cube texture. Leaving six planes and their materials alive
  // would be six leaks that nothing ever draws.
  room.traverse((object) => {
    if (object.isMesh) release(object);
  });
  return built.texture;
}

/** Build the renderer, the scene and the camera. Idempotent. */
export function mount(canvas) {
  if (view.renderer) return;
  view.palette = readPalette();

  view.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  view.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // **Tone mapping, where there was none, and NOT the popular one.**
  // The default is `NoToneMapping`, which clips every value above 1.0 flat --
  // the default that matters least on a diffuse scene and most on this one,
  // because a specular highlight on metal is exactly what goes above 1.0 and
  // this board has nine metal surfaces. Measured on the Uno close-up: 0.30% of
  // pixels had a channel at 255 before the softbox went in and 6.82% after,
  // which is a picture whose brightest sixteenth carries no information.
  //
  // `NeutralToneMapping` rather than `ACESFilmicToneMapping` because THE
  // COLOURS IN THIS SCENE ARE MEASUREMENTS. #313d63 is the Uno's solder mask
  // read out of PICSimLab's own artwork, #ffcf80 is the XIAO's gold named in
  // `refreshTheme`, and `FINISHES` in `tools/import_3d_model.py` cites every
  // one of them. ACES is a film look: it shifts hue and desaturates on the way
  // through, which would quietly restate every sourced colour as something
  // else. Khronos PBR Neutral leaves an in-gamut colour alone and only
  // compresses what is too bright to show, which is the only part this page
  // has a right to change.
  view.renderer.toneMapping = THREE.NeutralToneMapping;

  // **Shadows, which this scene has never had.** The comment that used to sit
  // below said "this scene has one object" -- true when the board was an
  // extruded slab, false since OH-75 put fifteen components on it, and the
  // reason the DIP-28 and the headers met the board at a hard edge and looked
  // pasted on. A contact shadow is what says "this is attached to that".
  view.renderer.shadowMap.enabled = true;
  // **`PCFShadowMap`, because `PCFSoftShadowMap` IS DEPRECATED IN r185** and
  // the renderer substitutes this one anyway with a console warning
  // (`vendor/three.module.js:9150`). So the shadows shipped under OH-85 were
  // always PCF; what was wrong was the line saying otherwise, and a test that
  // asserted the string rather than the behaviour agreed with it.
  view.renderer.shadowMap.type = THREE.PCFShadowMap;

  view.scene = new THREE.Scene();
  view.scene.background = view.palette.ground;

  view.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 500);
  view.controls = new OrbitControls(view.camera, canvas);
  view.controls.enableDamping = true;
  // No panning: the board is the subject and there is nothing else in the
  // scene to pan to. Letting it slide off the screen would give a reader a way
  // to lose it with no way to find it again.
  view.controls.enablePan = false;

  // **An environment and one key light, where there used to be an ambient and
  // one key light.** An image-based light IS the ambient term, with direction:
  // it is what a metal reflects, and without it `metalness` is a lie -- a
  // mirror with nothing in front of it renders black. So the environment and
  // `FINISHES` in `tools/import_3d_model.py` are one change, and adding either
  // alone makes the picture worse.
  //
  view.scene.environment = studio(view.renderer);
  view.scene.environmentIntensity = ENVIRONMENT_SHARE;
  view.lights = [...LIGHTS, BOUNCE].map((sample) => {
    const light = new THREE.DirectionalLight(NEUTRAL_LIGHT,
                                             LIGHT_TOTAL * sample.share);
    light.userData.from = sample;
    // The bounce is the one that does not, and `BOUNCE` says why. It stays in
    // this list so that `castShadows` still POSITIONS it -- a directional
    // light aims from its position at its target, and a light left at the
    // origin shines from nowhere in particular.
    light.castShadow = sample.casts !== false;
    light.shadow.mapSize.set(SHADOW_TEXELS, SHADOW_TEXELS);
    // **`normalBias` and not `bias`, and the units are why.** `bias` is a
    // depth offset in the shadow camera's clip space, so its right value moves
    // with that camera's near and far -- and these are refitted to the scene
    // every time a board or a part changes size. `normalBias` is in WORLD
    // units and this scene's world units are millimetres, so 0.06 is 60 um:
    // larger than a shadow texel across the Uno, small enough not to lift a
    // shadow off the leg that casts it.
    light.shadow.normalBias = SHADOW_BIAS_MM;
    // A directional light aims at its target, and a target that is never added
    // to the scene keeps its default matrix -- so it would point at the origin
    // no matter where `frameScene` moves it. Adding it is the whole fix.
    view.scene.add(light.target);
    view.scene.add(light);
    return light;
  });

  view.bench = new THREE.Group();
  view.scene.add(view.bench);

  // **Capture phase, and that is the whole trick.** `OrbitControls` listens
  // for `pointerdown` on this same canvas, and a wire drag that let the event
  // through would turn the camera at the same time. Capture runs before any
  // bubbling listener whenever it was registered, so this sees the press
  // first and stops it going further when it starts a wire.
  canvas.addEventListener("pointerdown", onPointerDown, true);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointerleave", dehover);
  canvas.addEventListener("pointercancel", onPointerUp);

  resize();
  window.addEventListener("resize", resize);
  animate();
}

function resize() {
  if (!view.renderer) return;
  const canvas = view.renderer.domElement;
  const width = canvas.clientWidth || 1;
  const height = canvas.clientHeight || 1;
  view.renderer.setSize(width, height, false);
  view.camera.aspect = width / height;
  view.camera.updateProjectionMatrix();
}

function animate(now = 0) {
  if (!view.renderer) return;
  view.frame = requestAnimationFrame(animate);
  // **The timestamp `requestAnimationFrame` already hands us**, rather than
  // `THREE.Clock`, which this build deprecates in favour of `THREE.Timer` and
  // warns about in the console -- and this panel is held to no console message
  // at warning or above. It is also one subtraction against a whole class.
  //
  // Real elapsed seconds and not a frame count: `Rope.advance` banks it into
  // fixed substeps, so this is the one place the display's own rate enters and
  // the one place it stops.
  const delta = view.last ? Math.min((now - view.last) / 1000, 0.25) : 0;
  view.last = now;
  // **Which other leads a lead may not pass through, refreshed here rather
  // than where a wire is made** (OH-162 step 2). The set changes when a wire
  // is added, when one is dropped before it reaches a terminal, and when a
  // part is removed and takes its wires with it -- three places, each of
  // which would have had to remember. This loop already reads every wire once
  // a frame, so a list built here cannot be stale. One array, refilled and
  // shared: `offNeighbours` skips the rope it belongs to, so every wire can
  // hold the same one.
  view.ropes.length = 0;
  for (const wire of view.wires) view.ropes.push(wire.rope);
  for (const wire of view.wires) {
    wire.rope.moveHead(anchorOf(wire));
    if (wire.terminal) wire.rope.moveTail(vecArray(terminalPoint(wire.terminal)));
    wire.rope.neighbours = view.ropes;
    wire.rope.advance(delta);
    updateTube(wire.mesh.geometry, wire.rope, WIRE_RADIUS);
  }
  view.controls.update();
  view.renderer.render(view.scene, view.camera);
}

/**
 * Point the camera at everything there is, board and bench together.
 *
 * **Framed from the scene and not from the board**, which is the fix for a
 * part that was placed correctly and drawn off the edge of the canvas: the
 * board is about 18 units across and a part sits 6 beyond its edge, so a
 * camera pulled back by the board's own size cannot see one.
 *
 * The pull is a multiple of the whole extent rather than a distance, so one
 * number frames a bare XIAO, an Uno, and a XIAO with four parts beside it.
 */
function frameScene() {
  if (!view.renderer || !view.board) return;
  const box = new THREE.Box3().setFromObject(view.board);
  if (view.bench && view.parts.length) box.expandByObject(view.bench);
  const centre = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const reach = Math.max(size.x, size.z, size.y) * CAMERA_PULL;
  view.camera.position.set(centre.x + reach * CAMERA_FROM.x,
                           centre.y + reach * CAMERA_FROM.y,
                           centre.z + reach * CAMERA_FROM.z);
  view.controls.target.copy(centre);
  view.controls.update();
  castShadows(box, centre);
}

/**
 * Point the shadow camera at everything, and let everything cast into it.
 *
 * **Called from `frameScene` because that is already the one place that knows
 * how big the scene is**, and both jobs need exactly that: the camera has to
 * pull back far enough to see the board, and the shadow camera has to open
 * wide enough to cover it. A second traversal to compute the same box would be
 * a second answer that could disagree with the first.
 *
 * The flags are set here rather than at each place a mesh is made -- and there
 * are six of them, between the slab, the pads, the vendor's model, the parts,
 * the wires and the terminal targets. One traversal that runs after every
 * change cannot be forgotten by the seventh.
 */
function castShadows(box, centre) {
  if (!view.lights) return;
  const radius = box.getBoundingSphere(new THREE.Sphere()).radius || 1;

  for (const light of view.lights) {
    const from = light.userData.from;
    light.target.position.copy(centre);
    light.position.set(centre.x + from.x * radius * 3,
                       centre.y + from.y * radius * 3,
                       centre.z + from.z * radius * 3);
    const lens = light.shadow.camera;
    // A little wider than the sphere, so a part dropped on the bench at the
    // edge of the frame still has somewhere to cast.
    lens.left = -radius * 1.2;
    lens.right = radius * 1.2;
    lens.top = radius * 1.2;
    lens.bottom = -radius * 1.2;
    lens.near = radius * 0.5;
    lens.far = radius * 6;
    lens.updateProjectionMatrix();
  }

  view.scene.traverse((object) => {
    if (!object.isMesh) return;
    object.castShadow = true;
    object.receiveShadow = true;
  });
}

/** Throw away one object's geometry and material. */
function release(object) {
  object.geometry?.dispose();
  if (Array.isArray(object.material)) object.material.forEach((m) => m.dispose());
  else object.material?.dispose();
}

/**
 * Throw away what is THIS part's own, and only that (OH-133).
 *
 * `loadPart` hands out `clone(true)` of the cached template, and a three.js
 * clone SHARES geometry and materials with the template and every sibling
 * clone -- verified against the vendored three. `release` over the whole
 * tree therefore disposed buffers still in use: every sibling and the cache
 * template redrew from a fresh GPU upload after every removal. What IS
 * per-part is exactly two things: the lens material `dressPart` clones so
 * two LEDs light independently, and the terminal target spheres
 * `makeTarget` builds fresh, geometry and material both -- the targets are
 * the meshes carrying `userData.terminal`.
 */
function releasePart(part) {
  dehover();
  part.userData.lens?.material?.dispose();
  part.traverse((object) => {
    if (object.isMesh && object.userData.terminal !== undefined) release(object);
  });
}

/**
 * Draw a board.
 *
 * `layout` is `webui/api.py`'s `pin_view` verbatim. Pads with a null `x` are
 * skipped: a pin that is on the board rather than on the header has no
 * published position, and putting it somewhere plausible would be inventing
 * the one thing this file is careful not to invent. The panel lists them
 * beside the canvas instead.
 */
export function showBoard(layout, model = null) {
  if (!view.renderer) return;
  clearBoard();
  view.supply = supplyOf(layout);
  if (!layout || !layout.width || !layout.height) return;

  const width = layout.width * SCALE;
  const depth = layout.height * SCALE;

  // **The same substance as a real board's, because it is claiming to be
  // one.** This was roughness 0.85 and nothing else -- a matte dielectric --
  // while the two composed boards' solder masks are 0.35 under a clear coat.
  // A reader switching from a board with a model to one without should see a
  // different SHAPE, which is what the caption says, and not different
  // physics. The colour stays the palette's, because a board with no model has
  // no measured colour to use and inventing one is what that caption refuses.
  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(width, BOARD_THICKNESS, depth),
    new THREE.MeshPhysicalMaterial({
      color: view.palette.surface, roughness: SOLDER_MASK.roughness,
      metalness: 0.0, clearcoat: SOLDER_MASK.coat,
      clearcoatRoughness: SOLDER_MASK.coatRoughness,
    })
  );
  view.board = new THREE.Group();
  // Which board this group is, so a mesh that arrives after the reader has
  // picked a different one is dropped rather than drawn on the wrong pads.
  view.board.userData.board = layout.board;
  view.board.add(slab);

  // A wire outline in the accent colour, so the courtyard reads as an edge
  // rather than as the place the fill stops.
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(slab.geometry),
    new THREE.LineBasicMaterial({ color: view.palette.line })
  );
  view.board.add(edges);

  // **The pads stand on whichever board is showing.** With the vendor's model
  // loaded that is its own PCB, which is 1.61 mm on a SAMD21 and 1.20 mm on an
  // RP2040 -- so a height fixed to the assumed 1.6 would sink four pads into
  // one board and float them above another. `placeModel` raises them when the
  // mesh arrives; until then they sit on the slab, which is also where they
  // stay on a board with no model.
  // An underside pad lies on the board's underside, mirrored across it.
  const top = BOARD_THICKNESS / 2 + PAD_LIFT + PAD_HEIGHT / 2;
  view.underside = [];
  for (const pad of layout.pads) {
    if (pad.x === null || pad.y === null) continue;
    const under = pad.group === UNDERSIDE;
    const post = new THREE.Mesh(
      new THREE.CylinderGeometry(PAD_RADIUS, PAD_RADIUS, PAD_HEIGHT, 20),
      new THREE.MeshStandardMaterial({
        color: view.palette.states[pad.state] ?? view.palette.states.unknown,
        roughness: 0.4,
        metalness: 0.1,
      })
    );
    // Image y maps to scene z with the SAME sign, and the sign was measured
    // rather than argued (OH-115). This line negated it -- "image y grows
    // downward, so y is negated" -- and its own comment warned that getting
    // it wrong "mirrors the header end for end". It was wrong, and the
    // warning came true silently: a composed model's pins land at
    // z = -board_y with image y ALREADY the negation of board y, so negating
    // again put every pad on the row OPPOSITE its pin. `carvePins` then
    // matched 28 of the Uno's 32 pads to the wrong row's pins -- pin 13's
    // marker carved SCK's opposite number -- and the five whose opposite x
    // has no pin were OH-96's "five pads with no pin at all". Measured: under
    // this sign every one of the 32 lands on its OWN pin within 0.1 mm,
    // against a 1.27 mm half-pitch.
    post.position.set(pad.x * SCALE - width / 2, top, pad.y * SCALE - depth / 2);
    if (under) post.position.y = -top;
    // **Never drawn. OH-95.** This disc is a collider and an anchor, not a
    // picture: `placeModel` replaces it with the vendor's own pin wherever
    // there is one, and where there is not, a cylinder standing on a board
    // that has no pins is the thing the reader objected to. Raycasting does
    // not test visibility -- `Raycaster.intersectObjects` calls `raycast` on
    // whatever it is handed -- so a wire can still be started from a pad
    // nobody can see, on the sixteen boards drawn as a bare footprint.
    post.visible = false;
    post.userData.pin = pad.pin;
    post.userData.label = pad.label;
    post.userData.underside = under;
    // **The state is kept on the mesh, not only in the colour it produced.**
    // A colour cannot be turned back into a state, so a theme change had
    // nothing to recolour from -- see `refreshTheme`, which is where that bug
    // was and what this field is for.
    post.userData.state = pad.state;
    view.board.add(post);
    addPad(pad.pin, post);
  }

  view.scene.add(view.board);

  // The extruded footprint's own slab, until a vendor model replaces it.
  view.mmScale = PX_PER_MM * SCALE;
  view.solids = [];
  // **An extrusion has no components, so it has no LED to light.** The list
  // is emptied rather than left, because a board drawn as a footprint after
  // one drawn from a model would otherwise keep the old board's lamp.
  view.leds = [];
  view.slab = { local: false,
                min: [-width / 2, -BOARD_THICKNESS / 2, -depth / 2],
                max: [width / 2, BOARD_THICKNESS / 2, depth / 2] };
  refreshColliders();
  frameScene();

  // Last, and not awaited: a board with a vendor model is drawn twice --
  // once as the footprint, then again when a megabyte and a half of mesh has
  // arrived. Waiting for it would leave the panel blank on a slow connection
  // for the sake of a picture, and the table beside it is already correct.
  if (model && model.file) loadModel(layout, model);
}

/**
 * Replace the extruded slab with the vendor's own model.
 *
 * **A board with no model keeps the slab, and that is the whole degradation
 * story.** The caller decides: `tools/import_3d_model.py` writes an index
 * naming every board it has a model for, `board3d-panel.js` reads it, and
 * three XIAO ESP32-C3 boards are absent from it because Seeed publishes that
 * one on GrabCAD rather than on its own wiki. The panel says which of the two
 * a reader is looking at rather than leaving them to notice that one board
 * looks different from its neighbours.
 */
async function loadModel(layout, model) {
  let loaded;
  try {
    const response = await fetch(model.file);
    if (!response.ok) return;
    loaded = readGlb(await response.arrayBuffer());
  } catch (error) {
    // The footprint is still on screen, which is the point of drawing it
    // first. Reported once rather than swallowed.
    console.warn(`the vendor model for ${layout.board} did not load:`, error);
    return;
  }
  // `showBoard` may have run again while the mesh was in flight.
  if (!view.board || view.board.userData.board !== layout.board) return;
  placeModel(loaded, layout);
}

/** Scene units per model millimetre, from the pad field both sources describe.
 *
 *  The longer axis decides it: a header row 22.86 mm long measured against the
 *  same row in pixels is a far better lever arm than the 0 mm across a single
 *  row, and one of a board's two spans is often exactly that. Falls back to the
 *  constant when neither span is usable, which is a one-row board and not a
 *  case any board here presents. */
function scaleFromPads(xs, ys, span) {
  const pixels = [Math.max(...xs) - Math.min(...xs),
                  Math.max(...ys) - Math.min(...ys)];
  const best = span[1] > span[0] ? 1 : 0;
  if (!(span[best] > 0) || !(pixels[best] > 0)) return PX_PER_MM * SCALE;
  return (pixels[best] / span[best]) * SCALE;
}

/** Put a loaded model where the footprint was, and stand the pads on it. */
/**
 * Take the vendor's own pins out of the model and make them the pad markers.
 *
 * **OH-95: the marker used to be a `CylinderGeometry` disc this file drew, and
 * on an Arduino Uno it hovered over a gold header pin the model had already
 * put there.** Reported as "the cylindrical shapes for wire connections should
 * not exist and should use the real pins".
 *
 * The marker does three jobs -- it carries the state colour, it is the
 * raycast target that starts a wire, and it is the anchor a wire's end
 * follows -- so it cannot be deleted. What it can stop being is invented.
 * `view.pads` is still a `Map<pin, Mesh>` afterwards, so `repaint`,
 * `setLevels`, `refreshTheme`, `anchorOf`, `describe` and the drag all go on
 * working without knowing the geometry changed underneath them.
 *
 * **Only metal is carved, and that is what stops a header's shroud turning
 * blue.** A pin is a conductor; the black plastic around it is not. The
 * models say which is which -- `FINISHES` in `tools/import_3d_model.py` sets
 * `metalness` to 0 or 1 because a surface either conducts or does not -- so
 * this reads the material rather than guessing at a height above the board.
 *
 * The triangles are MOVED, not copied: left in place they would be drawn
 * twice, once in the vendor's colour and once in the state's, and two
 * coincident surfaces z-fight.
 *
 * Returns the pins it found, so the caller can say how many pads have real
 * geometry and how many are left as colliders nobody can see.
 */
function carvePins(group, pcbThickness) {
  dehover();
  const wanted = [];
  for (const [pin, posts] of view.pads) {
    for (const post of posts) {
      post.getWorldPosition(scratch);
      wanted.push({ pin, post, at: group.worldToLocal(scratch.clone()),
                    under: post.userData.underside });
    }
  }
  if (!wanted.length) return [];

  //: Triangles claimed by each pad: positions, normals, and the colour the
  //: VENDOR gave the surface they came out of -- which is the pin's own metal
  //: and not the state colour the cylinder happened to be wearing.
  //:
  //: **On the ENTRY, not in a map keyed by name** (OH-128). Three of an
  //: Uno's pads are called GND (OH-117), and a per-name bucket built the
  //: same mesh three times over -- three coincident copies z-fighting, each
  //: bucket slot holding a different one. One pad mesh, one bucket.
  for (const pad of wanted) {
    pad.positions = [];
    pad.normals = [];
    pad.metal = null;
  }
  const corner = new THREE.Vector3();
  const centre = new THREE.Vector3();

  group.traverse((object) => {
    if (!object.isMesh || !(object.material?.metalness > 0.5)) return;
    const geometry = object.geometry;
    const position = geometry.getAttribute("position");
    const normal = geometry.getAttribute("normal");
    const index = geometry.getIndex();
    if (!position || !index) return;

    const keep = [];
    const array = index.array;
    for (let at = 0; at < array.length; at += 3) {
      centre.set(0, 0, 0);
      for (let corner_ = 0; corner_ < 3; corner_++) {
        corner.fromBufferAttribute(position, array[at + corner_]);
        centre.add(corner);
      }
      centre.divideScalar(3);
      object.localToWorld(centre);
      group.worldToLocal(centre);

      // Above the PCB's own top face: a pin's tail passes through the board
      // and out of the underside, and carving that would take the solder
      // side of a part nobody is looking at. **And below its bottom face for
      // a pad on the underside, and only for one** (OH-216): each pad takes
      // metal on its own side of the board and never the other's.
      let mine = null;
      const below = centre.y < 0;
      if (below || centre.y > pcbThickness) {
        let nearest = PIN_REACH_MM;
        for (const pad of wanted) {
          if (pad.under !== below) continue;
          const gap = Math.hypot(centre.x - pad.at.x, centre.z - pad.at.z);
          if (gap < nearest) {
            nearest = gap;
            mine = pad;
          }
        }
      }
      if (mine === null) {
        keep.push(array[at], array[at + 1], array[at + 2]);
        continue;
      }
      const take = mine;
      take.metal ??= object.material.color.clone();
      for (let corner_ = 0; corner_ < 3; corner_++) {
        corner.fromBufferAttribute(position, array[at + corner_]);
        object.localToWorld(corner);
        group.worldToLocal(corner);
        take.positions.push(corner.x, corner.y, corner.z);
        if (normal) {
          corner.fromBufferAttribute(normal, array[at + corner_]);
          // A normal is a direction: rotated with the mesh, never translated.
          corner.transformDirection(object.matrixWorld).normalize();
          take.normals.push(corner.x, corner.y, corner.z);
        }
      }
    }
    if (keep.length !== array.length) {
      geometry.setIndex(keep);
    }
  });

  // **Which underside pads found metal under the board and which kept only
  // their invisible collider**, said rather than left to be inferred from
  // `realPins` (OH-216). `describe` reports it.
  view.underside = wanted.filter((pad) => pad.under).map((pad) => ({
    pin: pad.pin, label: pad.post.userData.label, carved: pad.positions.length >= 9,
  }));
  const found = [];
  for (const pad of wanted) {
    const { positions, normals, metal } = pad;
    if (positions.length < 9) continue;   // fewer than one triangle
    // **The pad's place lives on the MESH, not in the vertices** (OH-128).
    // Baked group-local, the mesh's own position was (0,0,0) and
    // getWorldPosition answered the model group's origin -- the pad-map
    // centroid on the board's UNDERSIDE -- for every carved pad. Every wire
    // on a board with vendor pins anchored there, pinned inside the PCB slab
    // collider, which is most of what "many issues with wire" was. So the
    // vertices are re-baked relative to the pad's own point and that point
    // becomes the mesh's position: the same triangles render in the same
    // places, and getWorldPosition answers where the pad is.
    for (let at = 0; at < positions.length; at += 3) {
      positions[at] -= pad.at.x;
      positions[at + 1] -= pad.at.y;
      positions[at + 2] -= pad.at.z;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position",
                          new THREE.Float32BufferAttribute(positions, 3));
    if (normals.length === positions.length) {
      geometry.setAttribute("normal",
                            new THREE.Float32BufferAttribute(normals, 3));
    } else {
      geometry.computeVertexNormals();
    }
    const pin = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      // The vendor's own finish, so a pin that is doing nothing looks like
      // the metal it is. `repaint` mixes the state into this.
      color: metal.clone(),
      roughness: 0.35,
      metalness: 1.0,
    }));
    pin.userData.pin = pad.pin;
    pin.userData.label = pad.post.userData.label;
    pin.userData.state = pad.post.userData.state;
    // **The vendor's colour is remembered, because a state cannot be undone.**
    // `repaint` blends toward the state colour, so blending twice would walk
    // the pin away from brass one call at a time.
    pin.userData.metal = metal.clone();
    pin.position.copy(pad.at);
    group.add(pin);
    release(pad.post);
    view.board.remove(pad.post);
    const bucket = view.pads.get(pad.pin);
    bucket[bucket.indexOf(pad.post)] = pin;
    // **A wire made while the model was in flight holds the pad MESH, not
    // the bucket slot** (OH-129). `loadModel` is deliberately not awaited,
    // and `beginWire` stores `post` as an object so the head follows one pad
    // among namesakes -- so a wire pulled during the fetch kept the cylinder
    // this just released: null-parented, `getWorldPosition` answering
    // board-local numbers, and unreachable from `view.pads` for any later
    // repair. Repointed here, at the one place the swap happens; the drag in
    // progress is in `view.wires` too, so one loop covers it.
    for (const wire of view.wires) {
      if (wire.post === pad.post) wire.post = pin;
    }
    pin.userData.carved = true;
    pin.userData.underside = pad.under;
    found.push(pad.pin);
  }
  return found;
}


function placeModel(loaded, layout) {
  const { group, extras } = loaded;
  const pcb = extras.pcb;
  if (!pcb) throw new Error("the model does not say how thick its PCB is");

  const width = layout.width * SCALE;
  const depth = layout.height * SCALE;
  // The model is millimetres and the scene is image pixels; the board JSONs
  // were generated at a stated 8 px/mm, which is the same `PX_PER_MM` the
  // slab's thickness uses.
  //
  // **Unless the model says otherwise, and one does.** 8 px/mm is what
  // `tools/import_board.py` generates a board JSON at, and PICSimLab's
  // Arduino Uno artwork -- the one pad map in this repository that was traced
  // rather than generated -- is about 5.66. A model carrying `pad_span` says
  // how many millimetres its own pad field covers, and dividing the pixels
  // this page has by the millimetres the model has gives the scale from the
  // two descriptions of the same pads. Composed at the constant instead, the
  // Uno came out 41% too large and stood its headers outside their markers.
  const placed = layout.pads.filter((pad) => pad.x !== null);
  const xs = placed.map((pad) => pad.x);
  const ys = placed.map((pad) => pad.y);
  // **A generated map STATES its scale, and the statement wins** (OH-121).
  // The fit below divides this page's pixel span by the model's `pad_span`,
  // and those are two different descriptions of two different pad fields on
  // an SMD XIAO -- 28 castellation SUB-pads on the model side against one
  // pad per castellation here -- so the quotient drew every composed SMD
  // model 9% small. Only the traced Uno map, which has no single true scale
  // (its artwork is anisotropic by 0.41%), leaves px_per_mm unset and takes
  // the fit; the fit is exact there, measured at 0.093 mm worst.
  const scale = layout.px_per_mm
    ? layout.px_per_mm * SCALE
    : extras.pad_span
      ? scaleFromPads(xs, ys, extras.pad_span)
      : PX_PER_MM * SCALE;
  group.scale.setScalar(scale);
  // Everything else that puts millimetres into this scene reads this, so a
  // bench part is the size it would be beside the real board.
  view.mmScale = scale;
  view.solids = extras.solids ?? [];

  // **Turned when the two frames disagree, and each frame is read from what
  // states it** (OH-215). The model states which way its PCB lies: `pcb.long`
  // along its x and `pcb.short` along its z -- the reading the collider slab
  // below makes. The board file states which way its own image lies. A
  // quarter turn about the vertical is the whole correction.
  //
  // This used to read the pad map alone, under "the model is always
  // landscape". That is true of every mesh the importer fetches, which it
  // emits long side along x, and of every composed XIAO -- and false of a
  // board whose vendor drew it upright: the composer keeps the vendor's own
  // frame, and such a board's pad map, read out of the same file, is upright
  // too. Each was turned a quarter off its own pads, and `carvePins` then
  // took whatever metal stood where the pads had been turned to.
  //
  // **A square board is placed right only because both comparisons tie.**
  // The SparkFun Qwiic Pocket ESP32-C6 is 25.4 x 25.4 mm on a 219 x 219 px
  // map, so both strict `>` are false and nothing turns -- which is right,
  // because both frames are its vendor's. A NEAR-square board can flip: a
  // map one pixel taller than wide over a model whose two sides are equal
  // reads as two frames disagreeing, and is turned a quarter that nothing
  // stated. Neither outline can say which way a square lies; only a pad
  // match could (OH-215).
  const mapUpright = layout.height > layout.width;
  const modelUpright = pcb.short > pcb.long;
  if (mapUpright !== modelUpright) group.rotation.y = Math.PI / 2;

  // Centre it on the pads rather than on the image. The pad map's extent
  // includes a courtyard margin that is a footprint artefact and is not the
  // board; the pads are the thing both sources measured.
  const centreX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const centreY = (Math.min(...ys) + Math.max(...ys)) / 2;
  group.position.set(
    centreX * SCALE - width / 2,
    -BOARD_THICKNESS / 2,
    // The same sign as the pads' own line, and the two must move together:
    // this is where the model's origin -- the centre of its pad field -- is
    // put on the centre of the page's, so the convention that places one has
    // to place the other. OH-115.
    centreY * SCALE - depth / 2
  );

  const [slab, edges] = view.board.children;
  slab.visible = false;
  edges.visible = false;
  view.board.add(group);
  view.model = group;
  // After `view.model` and `view.solids` are both set, because it joins them.
  placeLeds(layout.led_parts);

  // Raise every pad to the real board's top face. See the note in `showBoard`.
  //
  // **Or to the top of the header, when the board has one.** A XIAO's pads are
  // castellations on its edge and a marker on the PCB is exactly right. An
  // Arduino Uno's are inside a pin header, so a marker at board level is buried
  // by the very component that makes it a header -- invisible, and unreachable
  // by a drag. `pad_top` is the pin tip, measured off the header actually
  // placed there, and it is where a person clips a lead in any case.
  const top = -BOARD_THICKNESS / 2 + (extras.pad_top ?? pcb.thickness) * scale
              + PAD_LIFT + PAD_HEIGHT / 2;
  // An underside pad goes to the model's own bottom face, which is where the
  // group stands it (OH-216): the pin it is carved from is there, and so is
  // the place a wire to it is anchored.
  const bottom = -BOARD_THICKNESS / 2 - PAD_LIFT - PAD_HEIGHT / 2;
  for (const post of padMeshes()) {
    post.position.y = post.userData.underside ? bottom : top;
  }

  // **And then the drawn markers are replaced by the pins the vendor
  // published, wherever there is one.** OH-95. The raise above still matters:
  // it is what puts each cylinder at the pin tip so `carvePins` can find the
  // pin under it, and it is what a pad keeps when no pin is found.
  //
  // The world matrices have to be current for the search, which walks
  // triangles between the model's frame and each mesh's own, and nothing has
  // rendered since the group was added.
  view.board.updateWorldMatrix(true, true);
  const real = carvePins(group, pcb.thickness);
  view.realPins = real;
  // **What is left is not drawn.** A cylinder standing where the vendor drew
  // nothing is the thing this ticket removes; kept invisible it is still the
  // raycast target that starts a wire and the anchor the wire's end follows,
  // so the bench goes on working on the sixteen boards that have no pin
  // geometry at all. Nothing renders it.
  for (const post of padMeshes()) {
    if (!post.userData.carved) post.visible = false;
  }
  // The board just changed shape, so what a wire may not pass through changed
  // with it -- and it is the PCB that changed, not the assembly: a lead should
  // drape over the connector rather than be stopped by the box around it.
  // **The PCB, in the MODEL's own frame** -- not the scene's, which is the
  // distinction this got wrong twice. A model is positioned by the centre of
  // the pad map; on a XIAO that is also the centre of its board, because the
  // castellations run down both long edges, so a slab stated in absolute scene
  // coordinates happened to land correctly. It is not true in general. The
  // Arduino Uno's pads are on two edges of a board they are not centred on, so
  // its group sits 4.5 units off the origin and a slab that ignored that
  // stopped 4.5 units short of the board's right-hand edge -- exactly where a
  // wire dropped from pads 0 to 13 falls, and straight through the PCB.
  //
  // Stated in the model's frame and put through `matrixWorld` by
  // `refreshColliders`, the same as every component box, there is one
  // mechanism rather than two and no offset to forget.
  const offset = extras.pcb_offset ?? [0, 0];
  const halfLong = pcb.long / 2;
  const halfShort = pcb.short / 2;
  view.slab = {
    local: true,
    min: [offset[0] - halfLong, 0, offset[1] - halfShort],
    max: [offset[0] + halfLong, pcb.thickness, offset[1] + halfShort],
  };
  // **No rotation fix-up here any more, and its absence is the improvement.**
  // This used to swap the slab's x and z by hand when the model was turned a
  // quarter, and then swap the offset too -- two corrections, each right, each
  // one more thing to keep true. A box stated in the model's frame is turned
  // by `matrixWorld` along with everything else in it.
  refreshColliders();
}

/**
 * What a pin of this board can drive, in the spelling `circuit.js` reads.
 *
 * The rename across the boundary is the same one `parts.js`'s `electricalOf`
 * makes and for the same reason: `webui/boards/atmega328p.py`'s `SUPPLY` spells
 * its keys the way Python does, and one place knows both conventions rather
 * than a third existing to reconcile them.
 *
 * **Null in, null out, and null is a real answer.** A board whose module
 * publishes no `SUPPLY` gets no circuit at all rather than a plausible default,
 * because a supply voltage guessed here would decide every current the page
 * then printed.
 */
function supplyOf(layout) {
  const spec = layout?.supply;
  if (!spec) return null;
  return {
    chip: spec.chip,
    volts: spec.volts,
    sourceOhms: spec.source_ohms,
    sinkOhms: spec.sink_ohms,
    ratedAmps: spec.rated_amps,
    absoluteAmps: spec.absolute_amps,
    cited: spec.cited ?? {},
  };
}

/**
 * Put a glow on every component this board lights from a pin (OH-169).
 *
 * **A user LED is a pin and not a pad**, so it has a state and no coordinate,
 * and until this the only place it appeared was the table beside the canvas.
 * A board's components are one merged mesh here, so nothing in the model can
 * be recoloured on its own -- what CAN be done is to put a small body at the
 * box the composer measured for that component and light that.
 *
 * **Added to the model group and not to the scene**, which is the whole
 * reason this is safe: `solids` are stated in the model's own frame, so a
 * child of that group is turned, scaled and moved with it and there is no
 * second transform to keep true. The board's quarter turn for a portrait pad
 * map is the case that would otherwise be got wrong.
 *
 * Which component is the LED comes from the board module and is traced out of
 * the vendor's board file -- see `atmega328p.LED_PARTS`, which is five hops
 * through Arduino's own netlist, because an Uno has four LEDs and three of
 * them are not the user's.
 */
function placeLeds(parts) {
  for (const led of view.leds) {
    led.mesh.parent?.remove(led.mesh);
    release(led.mesh);
  }
  view.leds = [];
  if (!parts || !view.model) return;
  for (const [component, label] of Object.entries(parts)) {
    // A board may name a component its model does not draw -- the SAMD21 and
    // the RP2040 have a user LED in the module and no LED in the mesh at all.
    // Nothing is drawn and nothing is said: an invented body at a guessed
    // place is exactly the failure this repository refuses elsewhere.
    const solid = view.solids.find((each) => each.name === component);
    if (!solid) continue;
    const size = [0, 1, 2].map((axis) => solid.max[axis] - solid.min[axis]);
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(...size),
      // **No colour of its own**, which the renderer's own tripwire insists
      // on: the body is the palette's `unknown` and the light it emits is the
      // palette's `high`, the same two the pads and the table use. An LED
      // that glowed a colour written down here would be the one thing in this
      // scene that did.
      new THREE.MeshStandardMaterial({
        color: view.palette.states.unknown,
        emissive: view.palette.states.high,
        emissiveIntensity: 0,
      }));
    mesh.position.set(...[0, 1, 2].map(
      (axis) => (solid.min[axis] + solid.max[axis]) / 2));
    view.model.add(mesh);
    view.leds.push({ label, mesh });
  }
}

/**
 * Light the board's own LEDs from the levels the table is reading.
 *
 * **`high` and nothing else.** `low` is a driven pin with the lamp off,
 * `input` is a pin nobody is driving, and `unknown` is a board nobody has
 * loaded -- a board sitting there glowing because its state is unknown is
 * OH-164's mistake in a different medium.
 */
function lightLeds(levels) {
  for (const led of view.leds) {
    const on = levels[led.label] === "high";
    led.mesh.material.emissiveIntensity = on ? PIN_GLOW : 0;
  }
}

/** Paint one post from the state recorded on it. */
function repaint(post) {
  const colour =
    view.palette.states[post.userData.state] ?? view.palette.states.unknown;
  // **A carved pin KEEPS the metal the vendor gave it and emits the state.**
  // It is still made of brass; what changed is that it is doing something.
  // Painting the state into the colour was tried first and measured -- see
  // `PIN_GLOW` -- and produced two indistinguishable muddy browns.
  //
  // `unknown` does not glow at all. It is most pads on most boards, and a
  // board whose every pin is lit says nothing; an unanswerable pad should
  // look like the plain metal it is, and the table beside the canvas is where
  // "cannot be answered for" is written in words.
  if (post.userData.metal) {
    post.material.color.copy(post.userData.metal);
    const live = post.userData.state && post.userData.state !== "unknown";
    // `setScalar(0)` rather than a black Color, and the tripwire in
    // `test_the_renderer_writes_down_no_colour_of_its_own` is right to insist:
    // black here is not a colour this file chose, it is the absence of light.
    if (live) post.material.emissive.copy(colour);
    else post.material.emissive.setScalar(0);
    post.material.emissiveIntensity = live ? PIN_GLOW : 0;
    return;
  }
  post.material.color.copy(colour);
}

/** Recolour without rebuilding. `levels` is `{pinName: state}`. */
export function setLevels(levels) {
  if (!view.renderer || !levels) return;
  for (const [pin, posts] of view.pads) {
    for (const post of posts) {
      post.userData.state = levels[pin] ?? "unknown";
      repaint(post);
    }
  }
  // **The board's own LEDs follow the same payload the table reads** (OH-169),
  // for the reason below: one place decides a pin's state, so the lamp on the
  // board and the row in the table cannot disagree. A user LED is a pin with
  // no pad, so it is not in the loop above and needs its own line.
  lightLeds(levels);
  // **The parts follow the pads and not the payload**, which is the join that
  // makes a wire mean anything: the circuit is solved from the states read
  // back off the pads, so there is exactly one place a pin state is decided
  // and the picture cannot disagree with the table.
  applyCircuit();
}

/** Re-read the stylesheet. Called when the theme changes.
 *
 *  **The pads are repainted here and that is not an afterthought.** The first
 *  version recoloured the slab and the outline and left the posts alone, so
 *  switching to the light theme produced a white board carrying dark-theme
 *  pins: `low` is `--sunken`, which is nearly black in one theme and nearly
 *  white in the other, and a pin driven low stayed black on white until the
 *  next state poll happened to arrive. Nothing in the DOM was wrong -- the
 *  table beside the canvas was correct throughout -- so only a screenshot
 *  showed it. */
export function refreshTheme() {
  if (!view.renderer) return;
  view.palette = readPalette();
  view.scene.background = view.palette.ground;
  if (!view.board) return;
  const [slab, edges] = view.board.children;
  slab.material.color.copy(view.palette.surface);
  edges.material.color.copy(view.palette.line);
  // **The vendor's model is deliberately not repainted.** Its colours are
  // measurements -- #49a954 for that board's solder mask, #ffcf80 for the gold
  // on its castellated pads -- and tinting them to match a UI theme would turn
  // the one part of this picture that is sourced into decoration. The pads
  // stay theme-coloured because they are this repository's own reading of a
  // register, which is exactly the distinction the palette is for.
  for (const post of padMeshes()) repaint(post);
}

function clearBoard() {
  dehover();
  // The wires go with the board, because each one names a pad on it. The
  // parts stay: they are on the bench, not on the board.
  if (view.bench) clearBench();
  if (!view.board) return;
  view.board.traverse((object) => {
    if (object.isMesh || object.isLineSegments) release(object);
  });
  view.scene.remove(view.board);
  view.board = null;
  view.model = null;
  // The meshes themselves were released by the traverse above -- they are
  // children of the model, which is a child of the board. What is dropped
  // here is the list holding them, which would otherwise be a handful of
  // freed geometries that `lightLeds` still writes to.
  view.leds = [];
  view.pads.clear();
}

/** Give the GPU its memory back. */
export function dispose() {
  if (!view.renderer) return;
  cancelAnimationFrame(view.frame);
  window.removeEventListener("resize", resize);
  clearBench({ parts: true });
  clearBoard();
  // The prefiltered environment is a render target's texture and is nobody
  // else's to free: it was made here and it dies here.
  view.scene.environment?.dispose();
  view.scene.environment = null;
  view.controls.dispose();
  view.renderer.dispose();
  view.renderer = null;
  view.scene = null;
  view.camera = null;
  view.controls = null;
}

/**
 * How deep the worst wire sits inside something it may not pass through,
 * counting FREE nodes only.
 *
 * **For a test, and it is the only honest way to check this one.** A wire
 * lying over a chip and a wire lying through it are the same picture from most
 * angles, and the screenshot that made this look fixed was taken before the
 * colliders existed. A number is not fooled by the camera.
 *
 * **Zero is what a working collider gives, and that is why this number alone
 * was never enough** (OH-132). `collide` runs last in every pass, so a wire
 * resting correctly on a chip and a wire with no colliders at all both report
 * 0 here. And this one now says BY STATEMENT what it excludes: the two pinned
 * ends, which `collide` never touches, so a depth there is the anchor's fault
 * and not the wire's. That exclusion is the "0.289 mm" residual, re-derived.
 *
 * **What `contact()`'s `proud` means changed at OH-162, and this comment used
 * to name the wrong thing.** It used to be the contact itself: the solver
 * moved node CENTRES onto a face, so a resting wire's free nodes read the
 * whole 0.16 and a wire in clear air read 0. The solver keeps the tube out
 * now, so a correctly resting FREE node reads 0 -- and what is left comes
 * from the PINNED head, which `collide` never moves and `Rope.contact`
 * measures anyway. A pad's centre is `PAD_LIFT + PAD_HEIGHT / 2` = 0.04 above
 * the slab's top face, and the slab is in every rope's list, so an app wire's
 * head has 0.12 of its tube in the board by construction.
 *
 * Measured 2026-09-04, wires pinned to two pads with the solver told 0.16 --
 * these are the reference numbers for reading the export:
 *
 *   over the slab                proud 0.12   the head; no free node
 *   over the slab and one chip   proud 0.16   a free node in the seam, where
 *                                             a 0.32-wide tube does not fit
 *   no colliders at all          proud 0
 *
 * So it still separates "solving against solids" from "solving against
 * none". It no longer separates "resting on a chip" from "clear of one",
 * because 0.12 of it is the anchor in both cases -- and `inside` is 0 in all
 * three, which is the pass. Excluding a pinned end from `proud` the way
 * `inside` already excludes it would fix that, and belongs to OH-132's
 * question rather than to OH-162's step 1.
 *
 * Reported in scene units; divide by `view.mmScale` for millimetres.
 */
export function penetration() {
  let worst = 0;
  // `rope.colliders`, not `view.colliders`: the same set the rope is actually
  // solving against, so this measures what happened rather than what should
  // have. `applyColliders` drops the part a wire is plugged into, because its
  // tail is inside that part by construction.
  for (const wire of view.wires) worst = Math.max(worst, wire.rope.contact().inside);
  return worst;
}

/**
 * The whole contact picture: interpenetration, surface contact, and the ends.
 *
 * See `Rope.contact` for what the three mean and why one number was not
 * enough. Scene units; divide by `view.mmScale` for millimetres.
 */
export function contact() {
  const total = { inside: 0, proud: 0, pinned: 0 };
  for (const wire of view.wires) {
    const one = wire.rope.contact(WIRE_RADIUS);
    for (const key of Object.keys(total)) total[key] = Math.max(total[key], one[key]);
  }
  return total;
}

/** Whether a board is currently drawn. For the page, and for a test. */
export function drawn() {
  return view.board !== null;
}

/**
 * A world point as canvas pixels, or null before anything is mounted.
 *
 * **For driving the pointer from a test.** OH-73's Done-when is that a drag
 * makes a wire and does not turn the camera, and a drag needs two screen
 * positions -- the pad it starts on and the terminal it ends on. Both are
 * known in world space and neither is reachable from the DOM, so this is the
 * one thing a test cannot work out for itself.
 */
export function toScreen(point) {
  if (!view.renderer) return null;
  const at = new THREE.Vector3(point[0], point[1], point[2]).project(view.camera);
  const box = view.renderer.domElement.getBoundingClientRect();
  return [box.left + ((at.x + 1) / 2) * box.width,
          box.top + ((1 - at.y) / 2) * box.height];
}

/**
 * Where everything actually is, in world space.
 *
 * **For a test and for a person debugging one.** A WebGL scene cannot be
 * asserted on from Python and a screenshot shows what a thing looks like
 * rather than where it is -- which is exactly the gap that let a board render
 * upside down while every DOM assertion passed. Numbers close that gap.
 */
export function describe() {
  if (!view.renderer) return null;
  const box = new THREE.Box3();
  const at = new THREE.Vector3();
  const pads = {};
  // One position per NAME, which is what every caller of this has ever
  // wanted; `padCount` beside it is the number of PADS, and the two differ
  // wherever a name means more than one. On an Arduino Uno that is 30 and 32.
  for (const [pin, posts] of view.pads) {
    pads[pin] = vecArray(posts[0].getWorldPosition(at));
  }
  return {
    camera: vecArray(view.camera.position),
    target: vecArray(view.controls.target),
    // **How many pads are the vendor's own pin rather than an invisible
    // collider.** OH-95 replaced a drawn cylinder with carved geometry, and
    // "the cylinders are hidden" and "the pins were found" are two different
    // claims -- the first is true even when the carve finds nothing. This is
    // the number that tells them apart, and it is what the test asserts.
    realPins: view.realPins ?? [],
    // Each underside pad, and whether it found metal under the board or kept
    // only its invisible collider (OH-216). Never topside metal: `carvePins`.
    underside: view.underside ?? [],
    // The number of PADS, against `pads` above which is keyed by NAME.
    // They differ wherever a name means several pads -- an Uno's three
    // GND, which OH-117 stopped losing. 32 against 30 there.
    padCount: padMeshes().length,
    terminals: view.parts.flatMap((part, index) =>
      [...part.userData.terminals.entries()].map(([name, anchor]) => ({
        part: index, name, at: vecArray(anchor.getWorldPosition(new THREE.Vector3())),
      }))),
    board: view.board ? vecArray(view.board.getWorldPosition(at)) : null,
    model: view.model
      ? { position: vecArray(view.model.getWorldPosition(at)),
          scale: view.model.scale.x,
          rotationY: view.model.rotation.y,
          box: (box.setFromObject(view.model),
                { min: vecArray(box.min), max: vecArray(box.max) }) }
      : null,
    pads,
    circuit: view.circuit
      ? { ok: view.circuit.ok, note: view.circuit.note,
          parts: view.circuit.parts }
      : null,
    supply: view.supply,
    parts: view.parts.map((part) => ({
      kind: part.userData.kind,
      drive: part.userData.drive,
      position: vecArray(part.getWorldPosition(at)),
      box: (box.setFromObject(part),
            { min: vecArray(box.min), max: vecArray(box.max) }),
    })),
    wires: view.wires.map((wire) => ({
      pin: wire.pin,
      connected: Boolean(wire.terminal),
      segment: wire.rope.segment,
      stretch: wire.rope.worstStretch(),
      head: wire.rope.point(0),
      tail: wire.rope.point(wire.rope.count - 1),
    })),
  };
}

// --- the bench: parts, wires, and the drag that joins them -------------------
//
// **The rule this section keeps is that nothing here reads a register.** A
// wire is geometry and a part is a lamp; what a pin is doing arrives from
// `webui/api.py` through `setLevels` exactly as it did before any of this
// existed. A part lit here is a picture of a state this repository measured,
// which is the same sentence the file's header makes about a pad.

//: How thick a jumper lead is drawn, and how many sides its tube has.
//: Six is enough at this radius: the wire is about a pixel and a half across
//: on screen and a heptagon would cost more triangles than it is worth.
const WIRE_RADIUS = 0.16;
const WIRE_SIDES = 6;

//: Classic jumper colours, cycled. **Written down rather than read from the
//: palette**, and it is the same argument the vendor's solder mask gets: the
//: UI's palette is for what this repository is *saying*, and a lead's colour
//: is a thing on a bench. They also have to be told apart from each other,
//: which a palette with one accent cannot do.
const WIRE_COLOURS = [0xd6402c, 0x2f7fd6, 0xe8b03a, 0x3fae62, 0xb266cc, 0xcfd6dd];

/**
 * A tube with the topology of a wire but no useful positions yet.
 *
 * **Built once and rewritten in place every frame.** `TubeGeometry` allocates
 * a new geometry each time it is constructed, and a wire is rebuilt sixty
 * times a second: eight wires would be five hundred allocations a second for a
 * shape whose triangle list never changes. Only the vertices move.
 */
function makeTube(nodes, sides) {
  const geometry = new THREE.BufferGeometry();
  const count = nodes * sides;
  geometry.setAttribute("position",
    new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  geometry.setAttribute("normal",
    new THREE.BufferAttribute(new Float32Array(count * 3), 3));

  const index = [];
  for (let i = 0; i < nodes - 1; i++) {
    for (let j = 0; j < sides; j++) {
      const a = i * sides + j;
      const b = i * sides + ((j + 1) % sides);
      index.push(a, b, a + sides, b, b + sides, a + sides);
    }
  }
  geometry.setIndex(index);
  return geometry;
}

const tangent = new THREE.Vector3();
const normal = new THREE.Vector3();
const binormal = new THREE.Vector3();
const here = new THREE.Vector3();
const next = new THREE.Vector3();

/**
 * Rewrite a tube's vertices to follow a rope.
 *
 * The ring at each node needs two axes across the wire, and picking them from
 * the tangent alone twists: a Frenet frame flips wherever the curve is
 * straight, which for a hanging cable is most of it. So the frame is carried
 * along from the previous ring and re-orthogonalised -- parallel transport,
 * which has no such discontinuity.
 */
function updateTube(geometry, rope, radius) {
  const positions = geometry.attributes.position.array;
  const normals = geometry.attributes.normal.array;
  // Any direction not along the first tangent will do to start; the transport
  // below makes every later ring agree with this one rather than with a fixed
  // axis.
  normal.set(0, 1, 0);

  for (let i = 0; i < rope.count; i++) {
    const at = i * 3;
    here.set(rope.position[at], rope.position[at + 1], rope.position[at + 2]);
    const other = i === rope.count - 1 ? i - 1 : i + 1;
    const to = other * 3;
    next.set(rope.position[to], rope.position[to + 1], rope.position[to + 2]);
    tangent.subVectors(next, here);
    if (i === rope.count - 1) tangent.negate();
    if (tangent.lengthSq() === 0) tangent.set(0, 0, 1);
    tangent.normalize();

    // Re-orthogonalise the carried normal against this tangent. If the two
    // have become parallel -- a wire doubled back on itself -- any other axis
    // restarts the frame without a visible seam.
    normal.addScaledVector(tangent, -normal.dot(tangent));
    if (normal.lengthSq() < 1e-6) normal.set(tangent.z, tangent.x, tangent.y);
    normal.normalize();
    binormal.crossVectors(tangent, normal);

    for (let j = 0; j < WIRE_SIDES; j++) {
      const angle = (j / WIRE_SIDES) * Math.PI * 2;
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      const out = (i * WIRE_SIDES + j) * 3;
      const nx = normal.x * cos + binormal.x * sin;
      const ny = normal.y * cos + binormal.y * sin;
      const nz = normal.z * cos + binormal.z * sin;
      normals[out] = nx;
      normals[out + 1] = ny;
      normals[out + 2] = nz;
      positions[out] = here.x + nx * radius;
      positions[out + 1] = here.y + ny * radius;
      positions[out + 2] = here.z + nz * radius;
    }
  }
  geometry.attributes.position.needsUpdate = true;
  geometry.attributes.normal.needsUpdate = true;
  geometry.computeBoundingSphere();
}

const scratch = new THREE.Vector3();

/** A three.js vector as the plain array `wires.js` speaks. */
function vecArray(vector) {
  return [vector.x, vector.y, vector.z];
}

/** Where a wire's board end is now, following the pad it was pulled from.
 *
 *  **The pad the wire was pulled from, not a pad with that name** (OH-117).
 *  This used to be `view.pads.get(wire.pin)`, which was exact while one name
 *  meant one pad and stopped being so the moment three of them did: an Uno
 *  has three GND pads, so a wire dragged from the one beside AREF would have
 *  had its end snap to the one on the power header.
 */
function anchorOf(wire) {
  if (!wire.post) return wire.rope.point(0);
  wire.post.getWorldPosition(scratch);
  return vecArray(scratch);
}

/**
 * Put a part on the bench, beside the board.
 *
 * Beside rather than on: a part standing on the board would cover the pads a
 * wire has to be dragged from, which is the one thing this view exists to make
 * possible.
 */
export async function addPart(kind) {
  if (!view.renderer) return null;
  const loaded = await loadPart(kind);
  if (!loaded) return null;
  const part = dressPart(loaded.group, loaded.extras, view.palette);
  for (const anchor of part.userData.terminals.values()) {
    makeTarget(anchor, view.palette);
  }
  const row = view.parts.length;
  // **Clear of the board, measured rather than assumed.** The first version
  // used a constant 6.0 and a XIAO is about 17 units across, so every part
  // was placed inside the board's own footprint and the first one landed on
  // the USB connector. The board's real half-width is the only number that
  // makes this right for a 196px XIAO and a 402px Uno at once.
  const edge = boardHalfWidth() + BENCH_GAP;
  part.position.set(edge + (row % 3) * BENCH_PITCH,
                    -BOARD_THICKNESS / 2,
                    -BENCH_PITCH + Math.floor(row / 3) * BENCH_PITCH);
  // Millimetres, like the board -- and at the board's OWN scale, which is not
  // always the 8 px/mm a generated board JSON uses. See `view.mmScale`.
  part.scale.setScalar(view.mmScale);
  view.bench.add(part);
  view.parts.push(part);
  refreshColliders();
  // A part that has just arrived is wired to nothing, and the circuit is what
  // says so -- this is also what puts an entry for it in `view.circuit`, so
  // the page's list can name it before a wire reaches it.
  applyCircuit();
  frameScene();
  return part;
}

//: A counter rather than an index into `view.wires`: an index changes when
//: an earlier wire is removed, and the page holds these across renders.
let nextWireId = 1;

//: Part meshes, fetched once each. A bench with six LEDs on it should ask
//: for one file, and `dressPart` clones what it needs per part anyway.
const partCache = new Map();

/** Fetch and parse one part's mesh, or null if it is not there. */
async function loadPart(kind) {
  if (!partCache.has(kind)) {
    partCache.set(kind, fetch(`/models/parts/${kind}.glb`)
      .then((response) => (response.ok ? response.arrayBuffer() : null))
      .then((buffer) => (buffer ? readGlb(buffer) : null))
      .catch((error) => {
        console.warn(`the model for ${kind} did not load:`, error);
        return null;
      }));
  }
  const loaded = await partCache.get(kind);
  if (!loaded) return null;
  // A clone per part: two LEDs on the bench are two objects, and they light
  // independently because `dressPart` clones the lens material too.
  return { group: loaded.group.clone(true), extras: loaded.extras };
}

//: How far below the board the bench top sits. A wire with nothing under it
//: falls out of the scene, which is a worse picture than one lying on a table.
const BENCH_DROP = 5.0;

/**
 * Tell every wire what it may not pass through.
 *
 * **Recomputed when the scene changes and not every frame.** Nothing here
 * moves on its own: the board is placed once, a part is placed when it is
 * added, and neither is dragged. Rebuilding three bounding boxes sixty times a
 * second would be work to arrive at the same three numbers.
 *
 * The board is one box and each part is one box, which is coarser than their
 * meshes and is the right coarseness: a wire that draped exactly around a USB
 * connector's chamfers would cost a triangle test per node per pass, and the
 * difference would be invisible at the size a lead is drawn.
 */
/**
 * One box the wire physics can use, from a box stated in the model's frame.
 *
 * `local` boxes go through the model's world matrix; anything else is already
 * in scene coordinates, which is the extruded footprint's own slab. Having one
 * function decide that is the point: the two used to be computed in two places
 * and one of them forgot the model's position.
 */
function boardSolid(solid) {
  if (!solid.local || !view.model) {
    return { owner: "board", kind: "box", min: solid.min, max: solid.max };
  }
  const lo = new THREE.Vector3(...solid.min).applyMatrix4(view.model.matrixWorld);
  const hi = new THREE.Vector3(...solid.max).applyMatrix4(view.model.matrixWorld);
  return {
    owner: "board",
    kind: "box",
    min: [Math.min(lo.x, hi.x), Math.min(lo.y, hi.y), Math.min(lo.z, hi.z)],
    max: [Math.max(lo.x, hi.x), Math.max(lo.y, hi.y), Math.max(lo.z, hi.z)],
  };
}


function refreshColliders() {
  const solids = [];
  const box = new THREE.Box3();
  if (view.board) {
    // **The PCB slab, not the board's bounding box.** The box a board casts
    // includes its USB connector, which stands 2.4 mm proud -- so every pad on
    // the top face was *inside* it, and a wire pinned to a pad inside a solid
    // is a wire the constraint and the collider pull against each other
    // forever. Measured before the fix: 161% over rest on a wire that had
    // been sitting still for two seconds.
    solids.push(boardSolid(view.slab));
    // **And everything standing on it.** The PCB alone was the whole board
    // until OH-75 put components on it; a wire dropped across the Uno went
    // straight through its DIP-28 and all six headers, because geometry in the
    // mesh is not geometry the physics knows about. The model states its own
    // boxes -- see `tools/compose_board_3d.py`, which measures them anyway --
    // and they are in its frame, so they scale and shift with it.
    for (const solid of view.solids) solids.push(boardSolid(solid));
  }
  for (const part of view.parts) {
    box.setFromObject(part);
    solids.push({ owner: part, kind: "box",
                  min: vecArray(box.min), max: vecArray(box.max) });
  }
  const floor = -BOARD_THICKNESS / 2 - BENCH_DROP;
  view.colliders = solids;
  view.floor = floor;
  for (const wire of view.wires) applyColliders(wire);
}

/**
 * Give one wire the solids it may not pass through.
 *
 * **A wire is never blocked by the part it is plugged into.** Its tail is
 * inside that part by construction -- a terminal is a point on the component
 * -- so leaving the part's own box in the list would eject the node next to
 * the tail on every pass and leave the cable permanently stretched. This is
 * the same failure the board's box had, arriving from the other end.
 *
 * **And how thick it is** (OH-162). `WIRE_RADIUS` was a drawing parameter and
 * the solver moved centrelines, so a settled lead lay with half its tube
 * inside whatever it rested on -- the OH-132 probe read `proud` 0.16, the
 * whole radius. This is the one place a wire is told about the scene, so it
 * is where the number crosses over.
 */
function applyColliders(wire) {
  const own = wire.terminal?.userData?.part ?? null;
  wire.rope.colliders = own
    ? view.colliders.filter((solid) => solid.owner !== own)
    : view.colliders;
  wire.rope.floor = view.floor;
  wire.rope.radius = WIRE_RADIUS;
}

/** Half the drawn board's width, or a sane default before one is drawn. */
function boardHalfWidth() {
  if (!view.board) return BENCH_GAP;
  const box = new THREE.Box3().setFromObject(view.board);
  return Math.max(Math.abs(box.min.x), Math.abs(box.max.x));
}

/** Which pin a part is wired to, or null. */
function connectionOf(part) {
  for (const wire of view.wires) {
    if (wire.terminal && wire.terminal.userData.part === part) return wire.pin;
  }
  return null;
}

/**
 * Every part on the bench, for the page's own list.
 *
 * **`reason` is the half of this that matters.** "off" is a picture a reader
 * has to interpret; "only its anode is wired, so no current can return" is a
 * sentence they can check against the board in front of them. `circuit.js`
 * writes both and this hands them over unchanged.
 */
export function parts() {
  const report = view.circuit?.parts ?? [];
  return view.parts.map((part, at) => ({
    kind: part.userData.kind,
    label: part.userData.label,
    drive: part.userData.drive,
    amps: report[at]?.amps ?? null,
    reason: report[at]?.reason ?? "",
    warning: report[at]?.warning ?? null,
    destroyed: part.userData.destroyed === true,
    pin: connectionOf(part),
  }));
}

/** What the last solve said about the bench as a whole, or null. */
export function circuit() {
  if (!view.circuit) return null;
  return { ok: view.circuit.ok, note: view.circuit.note,
           supply: view.supply };
}

/** Everything currently joined. For the page, and for a test. */
export function connections() {
  return view.wires
    .filter((wire) => wire.terminal)
    .map((wire) => ({
      id: wire.id,
      pin: wire.pin,
      // The other PART end, for a wire that has one instead of a pin
      // (OH-116): the panel's chip says "anode ↔ 220 Ω resistor's lead A"
      // where a pad wire says "anode on 13".
      fromLabel: wire.pin === undefined
        ? wire.post.userData.part.userData.label : undefined,
      fromTerminal: wire.pin === undefined
        ? wire.post.userData.terminal : undefined,
      // Which entry of `parts()` this wire lands on. **A part needs two wires
      // before anything can be said about it**, so the page groups them by
      // part, and grouping by label would put two identical LEDs in one row.
      part: view.parts.indexOf(wire.terminal.userData.part),
      kind: wire.terminal.userData.part.userData.kind,
      label: wire.terminal.userData.part.userData.label,
      terminal: wire.terminal.userData.terminal,
    }));
}

/**
 * Take one wire off, and leave the part where it is.
 *
 * **What the part then shows is the circuit's answer and not a special case
 * here.** It used to be: this function set the part back to `unknown` itself,
 * because nothing else could work it out. Re-solving says the same thing for a
 * part left with no wires -- and says something better for a part left with
 * one, which now goes dark for the reason it deserves rather than staying lit
 * on the pin its remaining wire happens to touch.
 */
export function disconnect(id) {
  const wire = view.wires.find((candidate) => candidate.id === id);
  if (!wire) return false;
  discardWire(wire);
  applyCircuit();
  return true;
}

/** Take a part off the bench, and any wire that reached it. */
export function removePart(index) {
  const part = view.parts[index];
  if (!part) return false;
  for (const wire of [...view.wires]) {
    // Either end (OH-116): a wire that lands on this part, and a wire that
    // BEGINS on one of its terminals -- `post` is that anchor.
    if (wire.terminal?.userData?.part === part
        || wire.post?.userData?.part === part) discardWire(wire);
  }
  releasePart(part);
  view.bench.remove(part);
  view.parts.splice(index, 1);
  refreshColliders();
  applyCircuit();
  frameScene();
  return true;
}

/**
 * Start a wire at a pad, optionally already reaching somewhere.
 *
 * **A wire made without an `end` begins with all of its nodes on the pad**,
 * which is right for a drag -- the lead is being pulled out and has not gone
 * anywhere yet. It is wrong for a wire that is created already connected: the
 * far end teleports to the terminal and the other twenty-one nodes have to
 * travel there through whatever is in the way, which on a board is a violent
 * transient that leaves a residue. Measured 2026-08-27: 27.8% over rest after
 * two and a half seconds, against 1.2% for the same wire laid out along its
 * own line to begin with.
 */
function beginWire(pad, end = null) {
  // The id first, and the colour keyed off it (OH-133): `view.wires.length`
  // shrinks when a wire is disconnected, so the wire after any disconnect
  // repeated a colour already on the bench. The id is the monotonic counter
  // that exists because "an index changes when an earlier wire is removed"
  // -- the colour needed the identical treatment.
  const id = nextWireId++;
  const start = vecArray(pad.getWorldPosition(scratch));
  const rope = new Rope(start, end ?? start.slice());
  const mesh = new THREE.Mesh(
    makeTube(rope.count, WIRE_SIDES),
    new THREE.MeshStandardMaterial({
      color: WIRE_COLOURS[(id - 1) % WIRE_COLOURS.length],
      roughness: 0.5,
      metalness: 0.05,
    })
  );
  // **`post` is the object this was actually pulled from and `pin` is its
  // name when it has one.** The two stopped being interchangeable at
  // OH-117 (three of an Uno's pads are called GND) -- and since OH-116 the
  // start may be a part TERMINAL instead of a pad, in which case `pin` is
  // undefined and the from-end is `post.userData.part`/`.terminal`. The
  // netlist reads whichever pair exists; the mesh is what the wire's end
  // has to follow either way.
  const wire = { id, pin: pad.userData.pin, post: pad, rope, mesh,
                 terminal: null };
  applyColliders(wire);
  view.bench.add(mesh);
  view.wires.push(wire);
  return wire;
}

/** Drop a wire that never reached a terminal. */
function discardWire(wire) {
  const at = view.wires.indexOf(wire);
  if (at >= 0) view.wires.splice(at, 1);
  view.bench.remove(wire.mesh);
  release(wire.mesh);
}

const pointer = new THREE.Vector2();
const raycaster = new THREE.Raycaster();
const dragPlane = new THREE.Plane();
const dragPoint = new THREE.Vector3();

/** Put the pointer into the -1..1 box a raycaster wants. */
function aim(event) {
  const box = view.renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - box.left) / box.width) * 2 - 1;
  pointer.y = -((event.clientY - box.top) / box.height) * 2 + 1;
  raycaster.setFromCamera(pointer, view.camera);
}

/** Every pad mesh on the board, whatever name it carries.
 *
 *  `view.pads` groups by name because a name is a NET; almost everything that
 *  touches a pad -- raising it, recolouring it, raycasting it, handing it to
 *  the solver -- wants the meshes and does not care about the grouping. One
 *  helper rather than `[...view.pads.values()].flat()` in six places.
 */
function padMeshes() {
  return [...view.pads.values()].flat();
}

/** Put one pad mesh under its name, keeping any already there. */
function addPad(pin, post) {
  const here = view.pads.get(pin);
  if (here) here.push(post);
  else view.pads.set(pin, [post]);
}

/** The nearest pad under the pointer, or null. */
function padUnder() {
  const hits = raycaster.intersectObjects(padMeshes(), false);
  return hits.length ? hits[0].object : null;
}

/** The nearest part terminal under the pointer, or null. */
function terminalUnder() {
  const targets = [];
  for (const part of view.parts) {
    for (const anchor of part.userData.terminals.values()) {
      targets.push(...anchor.children.filter((child) => child.isMesh));
    }
  }
  const hits = raycaster.intersectObjects(targets, false);
  // The target is a handle on the anchor; the anchor is what a wire ends at.
  return hits.length ? hits[0].object.parent : null;
}

//: A LUMINANCE, not a colour, for the reason STUDIO's numbers are: a tinted
//: emissive would shift the vendor's metal toward whichever hue was chosen,
//: and this cue only says "this one", never a state. `setScalar` takes it,
//: so nothing here joins the palette -- the no-own-colours test agrees.
const HOVER_GLOW = 0.6;

/**
 * Light whatever the pointer is resting on, so a reader learns it can be
 * pulled before trying (OH-144).
 *
 * **Pads first, then part terminals -- the same order the drag itself
 * uses**, so what glows is exactly what a press would grab. An invisible
 * pad post is made visible for the stay: on the boards drawn as a bare
 * footprint the pads are colliders nobody can see, and the hover is the
 * one moment the page can honestly point at one.
 */
function hover() {
  const over = padUnder() ?? terminalUnder();
  if (over === (view.hovered?.object ?? null)) return;
  dehover();
  if (!over) return;
  const meshes = (over.isMesh ? [over]
    : over.children.filter((child) => child.isMesh))
    .filter((mesh) => mesh.material?.emissive);
  if (!meshes.length) return;
  view.hovered = {
    object: over,
    meshes: meshes.map((mesh) => ({
      mesh,
      emissive: mesh.material.emissive.getHex(),
      visible: mesh.visible,
    })),
  };
  for (const { mesh } of view.hovered.meshes) {
    mesh.material.emissive.setScalar(HOVER_GLOW);
    mesh.visible = true;
  }
  view.renderer.domElement.style.cursor = "pointer";
}

/** Put back whatever `hover` lit -- emissive, visibility and cursor.
 *
 *  Called from every path that could invalidate the lit mesh, not only
 *  from the next pointer move: a drag beginning, `releasePart`,
 *  `clearBoard`, `carvePins` swapping a post for a carved pin, and the
 *  pointer leaving the canvas. A restore that only ran on the next move
 *  would leave a glow on a mesh whose material was already disposed. */
function dehover() {
  if (!view.hovered) return;
  for (const { mesh, emissive, visible } of view.hovered.meshes) {
    mesh.material.emissive.setHex(emissive);
    mesh.visible = visible;
  }
  view.hovered = null;
  const canvas = view.renderer?.domElement;
  if (canvas) canvas.style.cursor = "";
}

/**
 * Take or give back the pointer, and never throw doing it.
 *
 * **Pointer capture is what keeps a drag working past the edge of the canvas**
 * and it is not essential: without it a drag still works inside the canvas,
 * which is where a wire is dragged anyway. It can fail -- a synthesised event
 * has no active pointer behind it, and `setPointerCapture` throws
 * `NotFoundError` rather than returning false -- and a console error from a
 * nicety is worse than the nicety being absent.
 */
function capture(event, take) {
  const canvas = view.renderer?.domElement;
  if (!canvas) return;
  try {
    if (take) canvas.setPointerCapture(event.pointerId);
    else canvas.releasePointerCapture(event.pointerId);
  } catch {
    // No active pointer with that id. The drag works without it.
  }
}

/** Tell the page a wire appeared or went away, so it can redraw its list. */
function announce() {
  view.renderer?.domElement.dispatchEvent(
    new CustomEvent("wires-changed", { bubbles: true }));
}

function onPointerDown(event) {
  if (!view.renderer || event.button !== 0) return;
  aim(event);
  // A pad first, a part terminal second (OH-116): the pads carry the
  // levels, so where the two overlap on screen the pad wins, which is also
  // what every drag before part-to-part wiring existed did.
  const pad = padUnder() ?? terminalUnder();
  if (!pad) return;
  dehover();
  // Only now is the camera's press taken away, and only because a wire really
  // did start. A press that missed every pad still turns the board.
  event.stopPropagation();
  event.preventDefault();
  view.controls.enabled = false;
  view.dragging = beginWire(pad);
  // The plane the loose end slides on: through the pad, facing the camera, so
  // that dragging up the screen lifts the wire whatever angle the board is
  // seen from.
  view.camera.getWorldDirection(scratch);
  dragPlane.setFromNormalAndCoplanarPoint(scratch, pad.getWorldPosition(dragPoint));
  capture(event, true);
}

function onPointerMove(event) {
  if (!view.renderer) return;
  aim(event);
  if (!view.dragging) {
    hover();
    return;
  }
  if (raycaster.ray.intersectPlane(dragPlane, dragPoint)) {
    view.dragging.rope.moveTail(vecArray(dragPoint));
  }
}

function onPointerUp(event) {
  if (!view.dragging) return;
  aim(event);
  const terminal = terminalUnder();
  // Its own starting anchor is not a landing (OH-116): a wire from a
  // terminal to itself would be a self-loop the solver erases and the page
  // could not explain.
  if (terminal && terminal !== view.dragging.post) {
    view.dragging.terminal = terminal;
    view.dragging.rope.moveTail(vecArray(terminalPoint(terminal)));
    view.dragging.rope.slacken();
    applyColliders(view.dragging);
    applyCircuit();
  } else {
    // **Dropped in mid-air is dropped.** A wire left dangling would be a
    // connection the page could not explain, and this view's whole contract is
    // that everything drawn stands for something read.
    discardWire(view.dragging);
  }
  view.dragging = null;
  view.controls.enabled = true;
  capture(event, false);
  // **The page cannot know a wire was made with a pointer**, because the drag
  // happens entirely inside the canvas. An event rather than a callback so
  // that the renderer still knows nothing about the page.
  announce();
}

/**
 * Solve the whole bench, and show each part what the circuit says it is doing.
 *
 * **One solve for the bench and not one per wire**, because a part needs both
 * of its legs and the circuit they close before anything can be said about it.
 * The function this replaces read the pad one wire came from and drove the part
 * with its logic level, which lit an LED with its other leg in mid-air --
 * OH-79, and the user's own report.
 *
 * Called whenever the topology or the pin levels change: a wire made or
 * dropped, a part added or removed, a state poll. It is cheap -- a dozen nodes
 * and a Gaussian elimination -- and it is not on the frame loop, because
 * nothing about a circuit changes between two frames on its own.
 */
function applyCircuit() {
  const index = new Map(view.parts.map((part, at) => [part, at]));
  const report = analyse({
    supply: view.supply,
    pads: padMeshes().map((post) => ({
      name: post.userData.pin, state: post.userData.state,
    })),
    parts: view.parts.map((part) => ({
      label: part.userData.label,
      terminals: [...part.userData.terminals.keys()],
      model: part.userData.electrical,
      // **The latch, and it lives here rather than in the solver.** `analyse`
      // is a pure function of a bench and must stay one, or a test could not
      // ask it about a fresh circuit and a ruined one without a clock between
      // them. What persists across polls is the part object, which is this
      // file's to own -- so the verdict goes out with the bench and comes back
      // on the report, and this is the only line that remembers it.
      destroyed: part.userData.destroyed === true,
    })),
    wires: view.wires
      .filter((wire) => wire.terminal)
      .map((wire) => ({
        pad: wire.pin,
        // **The from-end, when the wire began on a part instead of a pad**
        // (OH-116). Exactly one of `pad` and `from` is meaningful, and
        // `analyse` joins whichever pair exists.
        from: wire.pin === undefined ? {
          part: index.get(wire.post.userData.part),
          terminal: wire.post.userData.terminal,
        } : undefined,
        part: index.get(wire.terminal.userData.part),
        terminal: wire.terminal.userData.terminal,
      })),
  });
  view.circuit = report;
  for (const [at, part] of view.parts.entries()) {
    // Set and never cleared: past an absolute maximum is permanent, and the
    // only thing that undoes it is `removePart`, which is what a person does
    // with a burnt LED.
    if (report.parts[at].destroyed) part.userData.destroyed = true;
    setPartState(part, report.parts[at].drive, view.palette);
  }
}

/**
 * Drop every wire, and every part if asked.
 *
 * A board change drops the wires and keeps the parts: a wire names a pad on
 * the board that has just gone, and a part is on the bench beside it and is
 * nobody's but the reader's.
 */
export function clearBench({ parts: alsoParts = false } = {}) {
  for (const wire of [...view.wires]) discardWire(wire);
  // The drag in progress was one of those wires (OH-133): a pointer held
  // across a board change otherwise keeps writing to a wire whose mesh was
  // just released, and the pointerup then discards it a second time.
  view.dragging = null;
  if (alsoParts) {
    for (const part of view.parts) {
      releasePart(part);
      view.bench.remove(part);
    }
    view.parts.length = 0;
  }
  // Every part left standing has just lost its wires, so every one of them is
  // back to being a part nothing can be said about. Solving says that; a
  // stale `view.circuit` would leave the page printing currents for wires
  // that no longer exist.
  applyCircuit();
}

/** Wire a pad to a part's terminal without a pointer. For the page and tests. */
export function connect(pin, part, terminalName) {
  // **The first pad of that name, and any of them would do** (OH-117). A
  // name can now mean several pads -- an Uno has three called GND -- and they
  // are one NET: `circuit.js` says so at `groundOf`, and `webui/api.py` sends
  // one level for the name. So a caller naming a pin is naming a net, and
  // which of its pads the wire lands on is a matter of where it looks best.
  // A person dragging picks one with the pointer, which `padUnder` answers.
  const pad = view.pads.get(pin)?.[0];
  const terminal = part?.userData?.terminals?.get(terminalName);
  if (!pad || !terminal) return null;
  const wire = beginWire(pad, vecArray(terminalPoint(terminal)));
  wire.terminal = terminal;
  applyColliders(wire);
  wire.rope.slacken();
  applyCircuit();
  return wire;
}
