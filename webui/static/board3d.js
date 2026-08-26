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

//: A header pin, as a post standing on the top face. Radius is half the 0.1in
//: pitch's pad, which is what makes fourteen of them look like a header rather
//: than like fourteen dots.
const PAD_RADIUS = 0.42;
const PAD_HEIGHT = 0.9;

//: How far back the camera sits, as a multiple of the board's longest side.
//: Framing from the geometry rather than from a fixed distance is what lets
//: one number serve a 196px XIAO and a 402px Uno.
const CAMERA_PULL = 1.5;

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

//: Everything mutable, in one object rather than eight module-level `let`s.
//: `dispose` empties it, and a reader can see the whole lifetime at once.
const view = {
  renderer: null,
  scene: null,
  camera: null,
  controls: null,
  board: null,
  pads: new Map(),   // pin name -> the post drawn for it
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
    states: Object.fromEntries(
      Object.entries(STATE_VARIABLE).map(([state, name]) => [state, read(name)])
    ),
  };
}

/** Build the renderer, the scene and the camera. Idempotent. */
export function mount(canvas) {
  if (view.renderer) return;
  view.palette = readPalette();

  view.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  view.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  view.scene = new THREE.Scene();
  view.scene.background = view.palette.ground;

  view.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 500);
  view.controls = new OrbitControls(view.camera, canvas);
  view.controls.enableDamping = true;
  // No panning: the board is the subject and there is nothing else in the
  // scene to pan to. Letting it slide off the screen would give a reader a way
  // to lose it with no way to find it again.
  view.controls.enablePan = false;

  // Two lights and no shadows. A shadow map costs a second render pass to make
  // a flat green slab look slightly rounder, and this scene has one object.
  view.scene.add(new THREE.AmbientLight(NEUTRAL_LIGHT, 1.5));
  const key = new THREE.DirectionalLight(NEUTRAL_LIGHT, 2.0);
  key.position.set(12, 24, 10);
  view.scene.add(key);

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

function animate() {
  if (!view.renderer) return;
  view.frame = requestAnimationFrame(animate);
  view.controls.update();
  view.renderer.render(view.scene, view.camera);
}

/** Throw away one object's geometry and material. */
function release(object) {
  object.geometry?.dispose();
  if (Array.isArray(object.material)) object.material.forEach((m) => m.dispose());
  else object.material?.dispose();
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
export function showBoard(layout) {
  if (!view.renderer) return;
  clearBoard();
  if (!layout || !layout.width || !layout.height) return;

  const width = layout.width * SCALE;
  const depth = layout.height * SCALE;

  const slab = new THREE.Mesh(
    new THREE.BoxGeometry(width, BOARD_THICKNESS, depth),
    new THREE.MeshStandardMaterial({
      color: view.palette.surface, roughness: 0.85, metalness: 0.0,
    })
  );
  view.board = new THREE.Group();
  view.board.add(slab);

  // A wire outline in the accent colour, so the courtyard reads as an edge
  // rather than as the place the fill stops.
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(slab.geometry),
    new THREE.LineBasicMaterial({ color: view.palette.line })
  );
  view.board.add(edges);

  const top = BOARD_THICKNESS / 2 + PAD_HEIGHT / 2;
  for (const pad of layout.pads) {
    if (pad.x === null || pad.y === null) continue;
    const post = new THREE.Mesh(
      new THREE.CylinderGeometry(PAD_RADIUS, PAD_RADIUS, PAD_HEIGHT, 20),
      new THREE.MeshStandardMaterial({
        color: view.palette.states[pad.state] ?? view.palette.states.unknown,
        roughness: 0.4,
        metalness: 0.1,
      })
    );
    // Image space has y growing downward and three.js has z growing toward the
    // camera, so the board is centred and y is negated. Getting this wrong
    // mirrors the header end for end, which on a board whose two rows carry
    // different pins is a wrong picture rather than an ugly one.
    post.position.set(pad.x * SCALE - width / 2, top, depth / 2 - pad.y * SCALE);
    post.userData.pin = pad.pin;
    // **The state is kept on the mesh, not only in the colour it produced.**
    // A colour cannot be turned back into a state, so a theme change had
    // nothing to recolour from -- see `refreshTheme`, which is where that bug
    // was and what this field is for.
    post.userData.state = pad.state;
    view.board.add(post);
    view.pads.set(pad.pin, post);
  }

  view.scene.add(view.board);

  const reach = Math.max(width, depth) * CAMERA_PULL;
  view.camera.position.set(reach * 0.1, reach * 0.85, reach * 0.75);
  view.controls.target.set(0, 0, 0);
  view.controls.update();
}

/** Paint one post from the state recorded on it. */
function repaint(post) {
  const colour =
    view.palette.states[post.userData.state] ?? view.palette.states.unknown;
  post.material.color.copy(colour);
}

/** Recolour without rebuilding. `levels` is `{pinName: state}`. */
export function setLevels(levels) {
  if (!view.renderer || !levels) return;
  for (const [pin, post] of view.pads) {
    post.userData.state = levels[pin] ?? "unknown";
    repaint(post);
  }
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
  for (const post of view.pads.values()) repaint(post);
}

function clearBoard() {
  if (!view.board) return;
  view.board.traverse((object) => {
    if (object.isMesh || object.isLineSegments) release(object);
  });
  view.scene.remove(view.board);
  view.board = null;
  view.pads.clear();
}

/** Give the GPU its memory back. */
export function dispose() {
  if (!view.renderer) return;
  cancelAnimationFrame(view.frame);
  window.removeEventListener("resize", resize);
  clearBoard();
  view.controls.dispose();
  view.renderer.dispose();
  view.renderer = null;
  view.scene = null;
  view.camera = null;
  view.controls = null;
}

/** Whether a board is currently drawn. For the page, and for a test. */
export function drawn() {
  return view.board !== null;
}
