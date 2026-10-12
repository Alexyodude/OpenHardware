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

//: How hard a lit lens glows: the radiance of its brightest channel, in the
//: lens's own hue. Not a colour -- the colour is the part's own, from the file
//: -- and not the colour's gain, which `setPartState` takes from each lens and
//: which cannot pass one over its brightest channel. This is the one number
//: chosen for the look (OH-217).
//:
//: **1.2 is the middle, to a tenth, of the window two bounds leave**, each
//: run on every lens a part names by `tests/webui/test_lit_lens.py`, through
//: OH-227's proxy under the light the page was measured putting on each lens:
//:
//: - **from 0.92**, lit and unlit 3:1 apart in luminance, the bar WCAG sets
//:   for a state change on the same pixels (SC 2.4.13, Focus Appearance;
//:   the test cites it). The buzzer's mark sets it;
//:   KiCad's LED lens clears it from 0.59.
//: - **to 1.49**, lit at least as colourful as unlit. Past that the tone
//:   curve presses the buzzer's orange mark toward peach, and past 2.67 the
//:   red LED toward pink: the clip to white this comment used to warn of.
//:
//: **Seen in the page 2026-10-13**, the Arduino Uno blinking pin 13 into a
//: 5 mm LED and the 12 mm buzzer, in both themes alike: the LED went from a
//: dark red (100, 11, 7) to a bright one (248, 82, 77), 3.96:1, and the mark
//: from brown (134, 68, 20) to orange (249, 146, 90), 3.26:1.
//:
//: **It was 1.2 before as well, over a colour and an emission each 3.0 times
//: the lens's own** -- `LIT_GAIN`, fcce44c's, which put the LED lens's colour
//: at 1.34 and the buzzer's at 1.85 -- so each emitted 3.6 times its own
//: colour, 1.60 in the LED's red. That drew the LED salmon, (251, 105, 101), and the mark
//: peach, (252, 171, 135), less colourful lit (chroma 40.0) than unlit (46.6):
//: brighter, 4.59:1 and 3.97:1, by being whiter.
const LIT = 1.2;

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
//:
//: **`damaged` is its own word and not `lit`**, and it is the one the user
//: asked for: a part carrying more than its datasheet's absolute maximum is
//: not a working part with a caption beside it. Drawing it glowing while a
//: paragraph said it would be destroyed let the picture win the disagreement,
//: which is the same defect as the ungrounded LED in a smaller window.
//: `circuit.js`'s `destroys` decides it, and only an ABSOLUTE MAXIMUM can.
export const DRIVES = ["lit", "off", "unanswerable", "damaged"];

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
      // Lit, the lens is brightened by one over its brightest channel, and a
      // black lens has no hue to brighten.
      const peak = Math.max(...object.userData.baseColour.toArray());
      if (!(peak > 0)) {
        throw new Error(`${extras.chip}'s lens ${extras.lens} is ` +
                        `[${object.userData.baseColour.toArray()}] linear, ` +
                        `which has no hue to light`);
      }
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
    //: Absent for a part with no forward direction, which a resistor has none
    //: of: it conducts either way, and `analyse` takes the magnitude of its
    //: current rather than a signed one. `Electrical.forward` carries the
    //: argument on the Python side.
    from: spec.from,
    to: spec.to,
    forwardVolts: spec.forward_volts,
    seriesOhms: spec.series_ohms,
    //: The resistance of a part that is a resistance. **Named here or it is
    //: dropped in transit** -- `analyse` reads `model.ohms`, and a value the
    //: glTF carries but this function does not copy makes the part a conductor
    //: of unknown value that suppresses every current on the bench. That is
    //: exactly what happened to `absolute_amps` on its first pass, which is
    //: why `test_circuit.py`'s `JS_NAME` now checks every published number has
    //: a spelling here.
    ohms: spec.ohms,
    ratedAmps: spec.rated_amps,
    //: The only number that can license "destroyed". Absent for a part whose
    //: datasheet publishes no absolute maximum, and then nothing here will
    //: ever declare it dead however much current it carries.
    absoluteAmps: spec.absolute_amps,
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
  if (drive === "damaged") {
    // **`--halt`, flat and unlit.** Not the part's own colour darkened: `off`
    // is already dark, so dark is taken, and a broken LED that looked like an
    // LED which is merely not being driven would say nothing. `--halt` is
    // DEFINED as the colour that means "this went wrong" in whichever theme is
    // on, which is the contrast-not-lightness rule this file's neighbour
    // documents at length -- a hex literal for "charred" would be right in one
    // theme and invisible in the other.
    //
    // **Colour is the only channel there is at this size**, and it is not
    // enough on its own: a 5 mm LED is a few dozen pixels and a broken red one
    // and a lit red one are both red. The unambiguous statement is the panel's
    // -- a row that says which limit killed it, with the badge beside it. This
    // is the cue, not the claim.
    lens.material.color.copy(palette.halt);
    lens.material.emissive.set(0, 0, 0);
    lens.material.emissiveIntensity = 0;
    return;
  }
  if (drive === "lit") {
    // The same hue, as bright as a surface can be, plus its own light. A lit
    // LED is not a differently coloured LED.
    //
    // **The colour is an albedo, so no channel of it passes 1.0** (OH-217),
    // and its gain is the lens's own: one over its brightest channel, so that
    // channel is exactly 1.0. A gain shared by every lens -- one over the
    // brightest lens any part names, the buzzer's 0.617 red, so 1.62 -- holds
    // the bound too and was OH-214's; it is not used because a brighter lens
    // added to `PARTS` would then dim every other lens's colour. The glow is
    // `LIT`, chosen on its own, in the same hue.
    const peak = Math.max(base.r, base.g, base.b);
    lens.material.color.copy(base).multiplyScalar(1 / peak);
    lens.material.emissive.copy(lens.material.color);
    lens.material.emissiveIntensity = LIT;
    return;
  }
  lens.material.color.copy(base);
  lens.material.emissive.set(0, 0, 0);
  lens.material.emissiveIntensity = 0;
}
