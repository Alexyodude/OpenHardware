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

//: glTF's four-byte magic, `glTF`, and its two chunk types.
const GLB_MAGIC = 0x46546c67;
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;

//: glTF component types, for the two this reader accepts.
const FLOAT = 5126;
const UNSIGNED_INT = 5125;

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
    group.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: new THREE.Color(red, green, blue),
      roughness: material.pbrMetallicRoughness.roughnessFactor,
      metalness: material.pbrMetallicRoughness.metallicFactor,
      side: THREE.DoubleSide,
    })));
  }
  return { group, extras: json.asset.extras ?? {} };
}

//: Everything mutable, in one object rather than eight module-level `let`s.
//: `dispose` empties it, and a reader can see the whole lifetime at once.
const view = {
  renderer: null,
  scene: null,
  camera: null,
  controls: null,
  board: null,
  model: null,       // the vendor's mesh, once it has arrived
  pads: new Map(),   // pin name -> the marker drawn for it
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
export function showBoard(layout, model = null) {
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
  const top = BOARD_THICKNESS / 2 + PAD_LIFT + PAD_HEIGHT / 2;
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
    post.userData.label = pad.label;
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

/** Put a loaded model where the footprint was, and stand the pads on it. */
function placeModel(loaded, layout) {
  const { group, extras } = loaded;
  const pcb = extras.pcb;
  if (!pcb) throw new Error("the model does not say how thick its PCB is");

  const width = layout.width * SCALE;
  const depth = layout.height * SCALE;
  // The model is millimetres and the scene is image pixels; the board JSONs
  // were generated at a stated 8 px/mm, which is the same `PX_PER_MM` the
  // slab's thickness uses.
  const scale = PX_PER_MM * SCALE;
  group.scale.setScalar(scale);

  // **The model is always landscape and half these pad maps are not.** Every
  // model is emitted with the PCB's long side along x; `XIAO-SAMD21-SMD` and
  // its three siblings are taller than they are wide. A quarter turn about the
  // vertical is the whole correction, and it is decided from the data rather
  // than tabulated per board.
  if (layout.height > layout.width) group.rotation.y = Math.PI / 2;

  // Centre it on the pads rather than on the image. The pad map's extent
  // includes a courtyard margin that is a footprint artefact and is not the
  // board; the pads are the thing both sources measured.
  const placed = layout.pads.filter((pad) => pad.x !== null);
  const xs = placed.map((pad) => pad.x);
  const ys = placed.map((pad) => pad.y);
  const centreX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const centreY = (Math.min(...ys) + Math.max(...ys)) / 2;
  group.position.set(
    centreX * SCALE - width / 2,
    -BOARD_THICKNESS / 2,
    depth / 2 - centreY * SCALE
  );

  const [slab, edges] = view.board.children;
  slab.visible = false;
  edges.visible = false;
  view.board.add(group);
  view.model = group;

  // Raise every pad to the real board's top face. See the note in `showBoard`.
  const top = -BOARD_THICKNESS / 2 + pcb.thickness * scale
              + PAD_LIFT + PAD_HEIGHT / 2;
  for (const post of view.pads.values()) post.position.y = top;
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
  // **The vendor's model is deliberately not repainted.** Its colours are
  // measurements -- #116517 for that board's solder mask, #ff9f37 for the gold
  // on its castellated pads -- and tinting them to match a UI theme would turn
  // the one part of this picture that is sourced into decoration. The pads
  // stay theme-coloured because they are this repository's own reading of a
  // register, which is exactly the distinction the palette is for.
  for (const post of view.pads.values()) repaint(post);
}

function clearBoard() {
  if (!view.board) return;
  view.board.traverse((object) => {
    if (object.isMesh || object.isLineSegments) release(object);
  });
  view.scene.remove(view.board);
  view.board = null;
  view.model = null;
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
