// OpenHardware — the things a pin can drive, and the honest limit of that.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What a part is here, and what it is not
//
// **A part is a consumer of a pin state and nothing else.** `webui/api.py`'s
// `pin_levels` says a pad reads `high`, and an LED wired to that pad lights.
// Nothing flows the other way: no part drives a pin, no part loads one, and no
// part changes what the CPU reads. That boundary is the reason this file needs
// no core change and it is not a shortcut -- it is the line between showing a
// measurement and inventing one.
//
// The other direction is a genuinely different piece of work. A button pulling
// a pin low would have to reach `PINB`, `PINC` and `PIND` on an AVR and
// `PORT_IN` on a SAMD21, and `webui/boards/atmega328p.py` already records that
// all of those return the stored zero rather than the electrical level. OH-73
// says so in as many words and leaves it to its own ticket.
//
// ## The part is a real part
//
// **Nothing in this file models a shape.** The first version built an LED out
// of a capsule and two cylinders, and it looked like an LED drawn by somebody
// who had been told about one. The mesh now comes from KiCad's own
// `kicad-packages3D` library through `tools/import_3d_model.py` -- a 5 mm
// through-hole LED, 5.4 by 5.8 by 14.1 mm, with the flat on the cathode side
// and leads 2.54 mm apart.
//
// **Even the terminals are read off the mesh**, not typed in from a datasheet:
// the importer takes the ring of vertices at the bottom of each lead and
// averages it, which gave 2.540 mm spacing to three decimals. A lead spacing
// written down here would be a second source that could disagree with the
// geometry, and it would disagree silently -- a wire meeting nothing, a
// millimetre from the leg.
//
// ## The four states, and why a part has to answer for all of them
//
// A pin is `high`, `low`, `input` or `unknown`. Only the first three are
// claims about the program; `unknown` is a claim about this repository -- a
// pad it cannot answer for. **An LED that was dark for `unknown` would be
// lying**, in exactly the way `webui/api.py`'s vocabulary exists to prevent:
// dark is what a driven-low pin looks like, and "nobody here knows" is not
// that. So a part shows its own third state for it, and the panel's table says
// the word beside it.

import * as THREE from "three";

//: How far a part is dropped from the board's edge, and how far apart two
//: parts are placed. Beside the board rather than on it: a part standing on
//: the board would hide the pads a wire has to be dragged from.
export const BENCH_GAP = 5.0;
export const BENCH_PITCH = 6.0;

//: The emissive strength of a lit LED. Not a colour -- the colour is the
//: part's own, from the file -- but how hard it glows. Above about 1.4 the
//: bloom-free renderer clips to white and the LED stops looking coloured.
const LIT = 1.2;

//: How much brighter than the model's own dark red a lit lens is drawn.
//: KiCad's LED lens is `#720301`, which is the colour of an LED that is off;
//: one that is on is the same hue several times brighter, which is what a
//: real one does.
const LIT_GAIN = 3.0;

//: What each pin state does to a part.
//:
//: **`unknown` is its own answer and not `off`.** A pad this repository cannot
//: answer for is not a pad that is driven low, and a part that showed them the
//: same way would collapse the one distinction `webui/api.py`'s four-value
//: vocabulary exists to keep. It reads as a part connected to nothing this
//: page understands, which is the truth.
export const DRIVE = {
  high: "lit",
  low: "off",
  input: "off",
  unknown: "unanswerable",
};

/**
 * Turn a loaded mesh into a part: terminals, state and a lens to light.
 *
 * The caller loads the glTF, because loading is `board3d.js`'s job and this
 * file is not allowed to know how a mesh arrives -- which is also what keeps
 * the two from importing each other.
 *
 * `extras` is the glTF's `asset.extras`, which `tools/import_3d_model.py`
 * fills with the part's label, which colour is its lens, and where each lead
 * ends.
 */
export function dressPart(group, extras, palette) {
  group.userData.kind = extras.chip;
  group.userData.label = extras.label ?? extras.chip;
  group.userData.state = "unknown";
  group.userData.terminals = new Map();

  // The lens is named by colour because that is what the file has: a glTF
  // primitive carries a material and not a role, and the importer states which
  // material is the one that lights.
  group.userData.lens = null;
  group.traverse((object) => {
    if (object.isMesh && object.material?.name === extras.lens) {
      group.userData.lens = object;
      // Its own material, or two LEDs on the bench share one and lighting
      // either lights both.
      object.material = object.material.clone();
      object.userData.baseColour = object.material.color.clone();
    }
  });

  for (const terminal of extras.terminals ?? []) {
    // An anchor rather than a mesh: a wire ends at a point in the part's own
    // frame, and the lead it belongs to is one primitive among two hundred
    // triangles that cannot be picked apart by name.
    const anchor = new THREE.Object3D();
    anchor.position.set(terminal.at[0], terminal.at[1], terminal.at[2]);
    anchor.userData.terminal = terminal.name;
    anchor.userData.part = group;
    group.add(anchor);
    group.userData.terminals.set(terminal.name, anchor);
  }

  setPartState(group, "unknown", palette);
  return group;
}

/** Where a wire attaches to a terminal, in world space. */
export function terminalPoint(anchor, into = new THREE.Vector3()) {
  return anchor.getWorldPosition(into);
}

/**
 * A small sphere at each terminal, so a wire has something to be dropped on.
 *
 * **The lead itself is not pickable and that is a rendering fact, not a
 * choice**: it is a handful of triangles a millimetre across inside a mesh
 * that is one object per colour, so a raycast against it hits either the whole
 * LED or nothing. A target the size of a fingertip is what makes the drag
 * possible at all.
 */
export function makeTarget(anchor, palette) {
  const target = new THREE.Mesh(
    new THREE.SphereGeometry(TARGET_RADIUS, 10, 8),
    new THREE.MeshStandardMaterial({
      color: palette.muted ?? palette.line,
      roughness: 0.4,
      metalness: 0.4,
      transparent: true,
      opacity: 0.38,
    })
  );
  target.userData.terminal = anchor.userData.terminal;
  target.userData.part = anchor.userData.part;
  anchor.add(target);
  return target;
}

//: Scene units. Big enough to hit with a pointer on a 400 px canvas, small
//: enough that two of them 2.54 mm apart do not merge into one blob.
const TARGET_RADIUS = 0.55;

/**
 * Show what the pin is doing. `state` is one of `webui/api.py`'s four.
 *
 * `palette` supplies `line` for the unanswerable case, so that a part nobody
 * can answer for is the same quiet grey as every other "not modelled" in this
 * UI rather than a colour of its own.
 */
export function setPartState(part, state, palette) {
  part.userData.state = state;
  const lens = part.userData.lens;
  if (!lens) return;
  const drive = DRIVE[state] ?? DRIVE.unknown;
  const base = lens.userData.baseColour;

  if (drive === "unanswerable") {
    lens.material.color.copy(palette.line);
    lens.material.emissive.set(0, 0, 0);
    lens.material.emissiveIntensity = 0;
    return;
  }
  if (drive === "lit") {
    // The same hue, several times brighter, plus its own light. A lit LED is
    // not a differently coloured LED.
    lens.material.color.copy(base).multiplyScalar(LIT_GAIN);
    lens.material.emissive.copy(base).multiplyScalar(LIT_GAIN);
    lens.material.emissiveIntensity = LIT;
    return;
  }
  lens.material.color.copy(base);
  lens.material.emissive.set(0, 0, 0);
  lens.material.emissiveIntensity = 0;
}
