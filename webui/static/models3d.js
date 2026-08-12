// OpenHardware — procedural 3D component models.
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation; either version 2, or (at your option) any later version.
//
// PICSimLab ships no 3D geometry of any kind -- no OpenGL, mesh, .obj or .gltf
// anywhere in src/ -- so every model here is built from primitives at runtime.
// That is a deliberate choice over fetching a model library: KiCad's packages
// are CC-BY-SA-4.0, which would put a share-alike obligation on this tree, and
// a 2 GB download for a dev tool is its own problem.
//
// A part with no builder falls back to a PCB slab textured with its own
// `part.svg`, and reports `kind: "textured"` so the UI can say which parts are
// really modelled rather than implying all of them are.
//
// Dimensions are in world units where 1 unit is roughly 1 mm at the board's
// scale. They are shaped to read clearly at the default camera distance, not
// to match a datasheet -- nothing here is a mechanical drawing.

import * as THREE from "three";

const M = {
  pcb: () => new THREE.MeshStandardMaterial({ color: 0x1f6b45, roughness: 0.65 }),
  pcbDark: () => new THREE.MeshStandardMaterial({ color: 0x14523a, roughness: 0.7 }),
  plastic: (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.55 }),
  metal: (c) => new THREE.MeshStandardMaterial({ color: c, metalness: 0.85, roughness: 0.3 }),
  glass: (c) =>
    new THREE.MeshStandardMaterial({
      color: c,
      roughness: 0.15,
      transparent: true,
      opacity: 0.85,
    }),
};

/** A lit LED lens: emissive scales with the value the simulator reported. */
export function setGlow(mesh, intensity) {
  if (!mesh.material.emissive) return;
  mesh.material.emissive.setHex(mesh.userData.glowColour ?? 0xff3b30);
  mesh.material.emissiveIntensity = intensity;
}

function lens(colour, radius = 1.5, height = 2.6) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, height, 20),
    M.glass(colour),
  );
  body.position.y = height / 2;
  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2),
    M.glass(colour),
  );
  dome.position.y = height;
  group.add(body, dome);
  group.userData.glow = [body, dome];
  return group;
}

/** Tactile push button: metal can with a coloured cap. */
function tactile(capColour = 0x2b2f3a) {
  const group = new THREE.Group();
  const can = new THREE.Mesh(new THREE.BoxGeometry(4.2, 1.6, 4.2), M.metal(0xb9bfc9));
  can.position.y = 0.8;
  const cap = new THREE.Mesh(
    new THREE.CylinderGeometry(1.2, 1.3, 1.4, 16),
    M.plastic(capColour),
  );
  cap.position.y = 2.2;
  group.add(can, cap);
  group.userData.press = cap;
  return group;
}

function potKnob() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(6, 3, 6), M.metal(0x9aa4b4));
  body.position.y = 1.5;
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(1.6, 1.6, 2.4, 16),
    M.plastic(0x2b2f3a),
  );
  shaft.position.y = 4.2;
  const pointer = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.4, 1.7), M.plastic(0xe8e8e8));
  pointer.position.set(0, 5.3, 0.8);
  group.add(body, shaft, pointer);
  return group;
}

function sevenSegDigit() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(9, 2.2, 14), M.plastic(0x14161c));
  body.position.y = 1.1;
  const face = new THREE.Mesh(
    new THREE.BoxGeometry(7.4, 0.3, 12),
    M.plastic(0x2a0d0d),
  );
  face.position.y = 2.3;
  group.add(body, face);
  return group;
}

function buzzer() {
  const group = new THREE.Group();
  const can = new THREE.Mesh(new THREE.CylinderGeometry(5, 5, 4.5, 24), M.plastic(0x14161c));
  can.position.y = 2.25;
  const vent = new THREE.Mesh(
    new THREE.CylinderGeometry(0.9, 0.9, 0.6, 12),
    M.plastic(0x05070a),
  );
  vent.position.y = 4.6;
  group.add(can, vent);
  return group;
}

function servo() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(12, 11, 6), M.plastic(0x1a4fa0));
  body.position.y = 5.5;
  const ears = new THREE.Mesh(new THREE.BoxGeometry(18, 1.2, 6), M.plastic(0x1a4fa0));
  ears.position.y = 8.5;
  const hub = new THREE.Mesh(
    new THREE.CylinderGeometry(2.2, 2.2, 2.6, 16),
    M.plastic(0xe8e8e8),
  );
  hub.position.set(-3, 12.3, 0);
  const horn = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.8, 11), M.plastic(0xe8e8e8));
  horn.position.set(-3, 13.4, 3.5);
  group.add(body, ears, hub, horn);
  group.userData.spin = horn;
  return group;
}

function dcMotor() {
  const group = new THREE.Group();
  const can = new THREE.Mesh(new THREE.CylinderGeometry(6, 6, 16, 24), M.metal(0xa8b0bd));
  can.rotation.z = Math.PI / 2;
  can.position.y = 6;
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.9, 0.9, 6, 12),
    M.metal(0xd8dee9),
  );
  shaft.rotation.z = Math.PI / 2;
  shaft.position.set(11, 6, 0);
  group.add(can, shaft);
  group.userData.spin = shaft;
  return group;
}

function lcdModule(cols = 16) {
  const group = new THREE.Group();
  const board = new THREE.Mesh(new THREE.BoxGeometry(80, 1.6, 36), M.pcb());
  board.position.y = 0.8;
  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(71, 3.2, 25),
    M.plastic(0x2f6f4f),
  );
  glass.position.y = 3.2;
  group.add(board, glass);
  // Character cells, so it reads as a display rather than a green box.
  const cell = new THREE.BoxGeometry(3.2, 0.2, 5.4);
  const dark = M.plastic(0x1d5138);
  for (let i = 0; i < cols; i++) {
    for (let row = 0; row < 2; row++) {
      const c = new THREE.Mesh(cell, dark);
      c.position.set(-33 + i * 4.4, 4.9, -5 + row * 10);
      group.add(c);
    }
  }
  return group;
}

function ultrasonic() {
  const group = new THREE.Group();
  const board = new THREE.Mesh(new THREE.BoxGeometry(45, 1.6, 20), M.pcbDark());
  board.position.y = 0.8;
  for (const x of [-12, 12]) {
    const can = new THREE.Mesh(new THREE.CylinderGeometry(8, 8, 12, 24), M.metal(0xb9bfc9));
    can.rotation.x = Math.PI / 2;
    can.position.set(x, 10, 0);
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(6.6, 6.6, 0.6, 24),
      M.plastic(0x3a4150),
    );
    mesh.rotation.x = Math.PI / 2;
    mesh.position.set(x, 10, 6.2);
    group.add(can, mesh);
  }
  return group;
}

/**
 * A row of `count` identical modules spread across `widthPx` of the part's art.
 *
 * Peripherals in PICSimLab are strips -- eight buttons, eight LEDs -- and their
 * pin labels already sit under each element, so spreading the models the same
 * way lines the geometry up with the anchors.
 */
function strip(count, widthPx, make, scale) {
  const group = new THREE.Group();
  const span = widthPx * scale;
  const step = span / count;
  const items = [];
  for (let i = 0; i < count; i++) {
    const item = make(i);
    item.position.x = -span / 2 + step * (i + 0.5);
    group.add(item);
    items.push(item);
  }
  group.userData.items = items;
  return group;
}

//: LED colours in the order PICSimLab's own default config uses.
const LED_COLOURS = [0xff3b30, 0x34c759, 0x0a84ff, 0xffd60a, 0xff9f0a, 0xff375f,
                     0x30d158, 0x64d2ff];

/** Builders keyed by the exact `splist` name. */
const BUILDERS = {
  "LEDs": (w, s) =>
    strip(8, w, (i) => {
      const l = lens(LED_COLOURS[i % LED_COLOURS.length]);
      l.userData.glowColour = LED_COLOURS[i % LED_COLOURS.length];
      return l;
    }, s),
  "Push Buttons": (w, s) => strip(8, w, () => tactile(), s),
  "Switches": (w, s) => strip(8, w, () => tactile(0x9aa4b4), s),
  "Potentiometers": (w, s) => strip(4, w, () => potKnob(), s),
  "Potentiometers (Rotary)": (w, s) => strip(4, w, () => potKnob(), s),
  "7 Segments Display": (w, s) => strip(2, w, () => sevenSegDigit(), s),
  "7 Segments Display (Decoder)": (w, s) => strip(2, w, () => sevenSegDigit(), s),
  "Buzzer": () => buzzer(),
  "Servo Motor": () => servo(),
  "DC Motor": () => dcMotor(),
  "LCD hd44780": () => lcdModule(16),
  "Ultrasonic HC-SR04": () => ultrasonic(),
  "RGB LED": (w, s) => strip(1, w, () => lens(0xffffff, 2, 3.4), s),
  "LDR": (w, s) =>
    strip(1, w, () => {
      const g = new THREE.Group();
      const body = new THREE.Mesh(
        new THREE.CylinderGeometry(3, 3, 1.6, 20),
        M.plastic(0xe8d9a8),
      );
      body.position.y = 0.8;
      const trace = new THREE.Mesh(
        new THREE.TorusGeometry(1.8, 0.3, 8, 20),
        M.plastic(0x3a2f1a),
      );
      trace.rotation.x = Math.PI / 2;
      trace.position.y = 1.7;
      g.add(body, trace);
      return g;
    }, s),
};

export function hasModel(partName) {
  return partName in BUILDERS;
}

/**
 * Build a peripheral.
 *
 * Returns `{ group, kind }` where kind is "model" for real geometry and
 * "textured" for the art-on-a-slab fallback. The caller shows the difference
 * rather than letting a flat slab pass as a modelled component.
 */
export function buildPart(partName, widthPx, heightPx, svgUrl, scale) {
  const group = new THREE.Group();

  // Every peripheral sits on its own little PCB, textured with its art so the
  // silkscreen and pin numbers stay readable from above.
  const w = widthPx * scale;
  const h = heightPx * scale;
  const art = new THREE.MeshBasicMaterial({ map: loadTexture(svgUrl) });
  const edge = M.pcbDark();
  const board = new THREE.Mesh(new THREE.BoxGeometry(w, 1.2, h), [
    edge, edge, art, edge, edge, edge,
  ]);
  group.add(board);

  const builder = BUILDERS[partName];
  if (!builder) return { group, kind: "textured", board };

  const parts = builder(widthPx, scale);
  parts.position.y = 0.6;
  group.add(parts);
  return { group, kind: "model", board, parts };
}

// --- board furniture ---------------------------------------------------------
//
// Every board's `.map` already locates its components: `B_PB_*` is a push
// button, `O_LD_*` an LED, `I_SW_PWR` the power jack, `O_IC_*` an IC package.
// Surveyed across all 21 shipped maps, those families cover 460 of the 486
// regions, so modelling by family gives real geometry on every board without
// authoring anything per board.
//
// A region whose family has no builder is simply not furnished -- the art
// underneath still shows it, so nothing disappears.

function smdLed(w, h) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(Math.max(w, 0.8), 0.7, Math.max(h, 0.8)),
    M.glass(0xffd60a),
  );
  body.position.y = 0.35;
  g.add(body);
  g.userData.glow = [body];
  g.userData.glowColour = 0xffd60a;
  return g;
}

function icPackage(w, h) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(w, 2.2, h),
    M.plastic(0x1b1d24),
  );
  body.position.y = 1.1;
  // Pin 1 dimple, so the package reads as an IC rather than a black box.
  const dot = new THREE.Mesh(
    new THREE.CylinderGeometry(Math.min(w, h) * 0.09, Math.min(w, h) * 0.09, 0.3, 10),
    M.plastic(0x3a4150),
  );
  dot.position.set(-w / 2 + w * 0.14, 2.25, -h / 2 + h * 0.16);
  g.add(body, dot);
  return g;
}

function barrelJack(w, h) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(w, 5.2, h), M.plastic(0x14161c));
  body.position.y = 2.6;
  const bore = new THREE.Mesh(
    new THREE.CylinderGeometry(1.5, 1.5, 2.2, 16),
    M.plastic(0x05070a),
  );
  bore.rotation.x = Math.PI / 2;
  bore.position.set(0, 2.9, h / 2);
  g.add(body, bore);
  return g;
}

function pinHeaderBlock(w, h, cols = 3, rows = 2) {
  const g = new THREE.Group();
  const base = new THREE.Mesh(new THREE.BoxGeometry(w, 1.2, h), M.plastic(0x14161c));
  base.position.y = 0.6;
  g.add(base);
  const pin = new THREE.BoxGeometry(0.5, 3, 0.5);
  const gold = M.metal(0xd4a944);
  for (let c = 0; c < cols; c++) {
    for (let r = 0; r < rows; r++) {
      const p = new THREE.Mesh(pin, gold);
      p.position.set(
        -w / 2 + (w / cols) * (c + 0.5),
        2.4,
        -h / 2 + (h / rows) * (r + 0.5),
      );
      g.add(p);
    }
  }
  return g;
}

function dipSwitch(w, h) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(w, 1.6, h), M.plastic(0xc23b3b));
  body.position.y = 0.8;
  const lever = new THREE.Mesh(
    new THREE.BoxGeometry(w * 0.5, 0.6, h * 0.55),
    M.plastic(0xe8e8e8),
  );
  lever.position.set(0, 1.85, -h * 0.15);
  g.add(body, lever);
  return g;
}

function sevenSegCell(w, h) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(w, 1.8, h), M.plastic(0x14161c));
  body.position.y = 0.9;
  const face = new THREE.Mesh(
    new THREE.BoxGeometry(w * 0.82, 0.25, h * 0.85),
    M.plastic(0x2a0d0d),
  );
  face.position.y = 1.9;
  g.add(body, face);
  g.userData.glow = [face];
  g.userData.glowColour = 0xff3b30;
  return g;
}

//: family prefix -> builder taking the region's footprint in world units.
const FURNITURE = {
  O_LD: smdLed,
  O_SS: sevenSegCell,
  O_DS: sevenSegCell,
  O_IC: icPackage,
  O_SO: icPackage,
  O_MC: icPackage,
  O_LCD: (w, h) => {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(w, 3, h), M.plastic(0x2f6f4f));
    body.position.y = 1.5;
    g.add(body);
    return g;
  },
  B_PB: () => tactile(),
  I_PB: () => tactile(),
  O_PB: () => tactile(),
  B_KB: () => tactile(0x3a4150),
  B_PO: () => potKnob(),
  B_DP: dipSwitch,
  I_SW: barrelJack,
  I_PG: (w, h) => pinHeaderBlock(w, h),
  B_JP: (w, h) => pinHeaderBlock(w, h, 2, 1),
};

/**
 * Furnish a board from the regions its own `.map` declares.
 *
 * `toLocal(x, y)` maps image pixels into the board's local space and `topY` is
 * its top face. Returns a group plus the meshes that can glow, keyed by region
 * id so live values can drive them.
 */
export function buildBoardFurniture(regions, toLocal, topY, scale) {
  const group = new THREE.Group();
  const glowing = new Map();

  for (const region of regions) {
    const family = region.id.slice(0, region.id.indexOf("_", 2));
    const build = FURNITURE[family];
    if (!build) continue;

    const w = Math.max((region.right - region.left) * scale, 0.6);
    const h = Math.max((region.bottom - region.top) * scale, 0.6);
    const item = build(w, h);
    const at = toLocal((region.left + region.right) / 2, (region.top + region.bottom) / 2);
    item.position.set(at.x, topY, at.z);
    group.add(item);

    if (item.userData.glow) glowing.set(region.id, item);
  }

  group.userData.glowing = glowing;
  return group;
}

/**
 * One peripheral pin: a gold square post in a black shroud, the same shape as
 * the board's header so the two ends of a wire look like the same connector.
 *
 * These were spheres, which read as floating beads rather than as something a
 * wire plugs into.
 */
export function buildPinPost() {
  const group = new THREE.Group();
  const shroud = new THREE.Mesh(
    new THREE.BoxGeometry(1.5, 1.1, 1.5),
    M.plastic(0x14161c),
  );
  shroud.position.y = 0.55;
  const post = new THREE.Mesh(
    new THREE.BoxGeometry(0.62, 3.0, 0.62),
    M.metal(0xd4a944),
  );
  post.position.y = 2.4;
  group.add(shroud, post);
  //: The wire attaches at the top of the post, not the centre of the group.
  group.userData.tip = 3.6;
  //: A generous invisible cylinder makes the post pickable without having to
  //: hit a 0.6-unit square. Interaction target and visible shape are allowed
  //: to differ; a fiddly hitbox is a worse lie than a slightly large one.
  const grab = new THREE.Mesh(
    new THREE.CylinderGeometry(1.25, 1.25, 4.4, 10),
    new THREE.MeshBasicMaterial({ visible: false }),
  );
  grab.position.y = 2.0;
  group.add(grab);
  group.userData.grab = grab;
  group.userData.post = post;
  return group;
}

/** A 0.1in header: black plastic base with a gold pin standing in each pad. */
export function buildHeader(pads, toLocal, topY) {
  const group = new THREE.Group();
  const pinGeo = new THREE.BoxGeometry(0.62, 3.2, 0.62);
  const baseGeo = new THREE.BoxGeometry(1.5, 1.3, 1.5);
  const gold = M.metal(0xd4a944);
  const black = M.plastic(0x14161c);
  const dead = M.plastic(0x3a4150);

  const pins = [];
  for (const pad of pads) {
    const at = toLocal(pad.x, pad.y);
    const base = new THREE.Mesh(baseGeo, black);
    base.position.set(at.x, topY + 0.65, at.z);
    const pin = new THREE.Mesh(pinGeo, pad.pin ? gold : dead);
    pin.position.set(at.x, topY + 2.6, at.z);
    pin.userData = { kind: "pad", pin: pad.pin, label: pad.label };
    group.add(base, pin);
    pins.push({ pad, mesh: pin, world: pin.position.clone() });
  }
  group.userData.pins = pins;
  return group;
}

function loadTexture(url) {
  const tex = new THREE.TextureLoader().load(url);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}
