// OpenHardware — the things a pin can drive, and the honest limit of that.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What a part is here, and what it is not
//
// **A part is a consumer of a circuit's verdict and nothing else.**
// `webui/static/circuit.js` solves the bench and says this part is `lit`; this
// file makes it look lit. Nothing flows the other way: no part drives a pin, no
// part loads one, and no part changes what the CPU reads. That boundary is the
// reason this file needs no core change and it is not a shortcut -- it is the
// line between showing a measurement and inventing one.
//
// **This used to consume a pin state directly**, and the difference is the
// whole of OH-79: `high` on a pad lit whatever was wired to it, so an LED with
// one leg on D13 and the other in mid-air came on. A pin state is now one
// input to a circuit rather than an answer about a part.
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
// ## The third word, and why a part has to have one
//
// A part is `lit`, `off` or `unanswerable`. The first two are claims about a
// circuit; the third is a claim about this repository -- a pad, a board or a
// component it cannot answer for. **A part that was dark for that would be
// lying**, in exactly the way `webui/api.py`'s pin vocabulary exists to
// prevent: dark is what a real circuit carrying no current looks like, and
// "nobody here knows" is not that. So a part shows its own third state for it,
// and the panel says the word beside it.
//
// A pad reading `unknown` is one road into that third word; so is a board that
// publishes no supply, and so is a part nobody published a datasheet for.
// `circuit.js` decides which, and says which in a sentence.

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

//: What a part can be shown doing, and **a circuit decides which** --
//: `webui/static/circuit.js` solves the bench and hands one of these words per
//: part.
//:
//: This used to be a map from a pin state to one of these, so `high` lit an
//: LED whatever its other leg was doing -- or was not doing, which is how an
//: LED with one leg in mid-air came to light. A pin state is now an input to a
//: circuit rather than an answer about a part.
//:
//: **`unanswerable` is its own word and not `off`.** A part this page cannot
//: answer for is not a part that is dark, and showing them the same way would
//: collapse the one distinction `webui/api.py`'s four-value vocabulary exists
//: to keep. It reads as a part connected to nothing this page understands,
//: which is the truth.
export const DRIVES = ["lit", "off", "unanswerable"];

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
  group.userData.drive = "unanswerable";
  group.userData.electrical = electricalOf(extras);
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

  setPartState(group, "unanswerable", palette);
  return group;
}

/**
 * The part's own circuit model, in the spelling `circuit.js` reads.
 *
 * **Absent is an answer.** `tools/import_3d_model.py` writes this key only for
 * a part whose behaviour it can state, and its `Electrical` docstring says why
 * a made-up resistance for a generic buzzer would be worse than none: it would
 * decide every other part's current on the same bench.
 *
 * The rename across the boundary is deliberate and it is the whole of it: the
 * glTF is written by Python and spells its keys the way Python does, and this
 * is the one place that knows both. A part model shared by reference between
 * the two conventions would be a third convention.
 */
function electricalOf(extras) {
  const spec = extras.electrical;
  if (!spec) return null;
  return {
    kind: spec.kind,
    from: spec.from,
    to: spec.to,
    forwardVolts: spec.forward_volts,
    seriesOhms: spec.series_ohms,
    ratedAmps: spec.rated_amps,
    note: spec.note,
    cited: spec.cited ?? {},
  };
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
 * Show what the part is doing. `drive` is one of `DRIVES`.
 *
 * **It is not a pin state any more**, and that is this ticket's whole change:
 * the caller solves a circuit and passes the answer. A word this file does not
 * recognise falls back to `unanswerable`, which is the only safe direction to
 * fall -- lighting a part on a word nobody defined is exactly the failure the
 * circuit was added to stop.
 *
 * `palette` supplies `line` for the unanswerable case, so that a part nobody
 * can answer for is the same quiet grey as every other "not modelled" in this
 * UI rather than a colour of its own.
 */
export function setPartState(part, drive, palette) {
  if (!DRIVES.includes(drive)) drive = "unanswerable";
  part.userData.drive = drive;
  const lens = part.userData.lens;
  if (!lens) return;
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
