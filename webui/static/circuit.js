// OpenHardware — a circuit, solved, so that a part lights when current says so.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this solves for its caller
//
// **What is on the bench in; what current flows through each part out.** It
// knows nothing about boards, three.js, meshes or the DOM — it takes pad names,
// pin states and wires as plain data, and it imports nothing at all, so
// `tests/webui/test_circuit.py` runs it under node and checks its arithmetic
// against numbers. That is the same reason `webui/static/wires.js` and
// `webui/static/clock.js` import nothing, and both of them say so in their own
// headers.
//
// ## Why this exists
//
// `board3d.js` used to light a part like this: read the pad the wire came from,
// read its logic level, drive the part. No second terminal, no ground and no
// current anywhere in it — so an LED with one leg on D13 and the other in
// mid-air lit up, and so did one wired backwards. The user reported it in
// exactly those terms, and named the cause: *"not physically simulating the
// properties of the datasheet and components"*.
//
// ## Modified nodal analysis, and the diodes
//
// Unknowns are the node voltages plus one current for each ideal source; every
// other element stamps a conductance and a current injection. A diode is
// **piecewise linear**: off is a leakage conductance, on is `forwardVolts` in
// series with `seriesOhms`, stamped as its Norton companion so that turning one
// on does not change the size of the matrix. The states start all-off and are
// iterated to consistency — a pass that flips nothing has found the answer.
//
// **A solve that does not converge says so and the caller reports nothing.**
// A piecewise-linear network of this size settles in a handful of passes; if it
// ever oscillates, `ok` is false and the page must say it could not answer
// rather than draw the last guess.
//
// ## Every number here makes the current a LOWER bound, deliberately
//
// The drive resistances the caller passes in are derived from the *guaranteed*
// corners of a datasheet — the worst VOL and VOH at the stated test current —
// so they are upper bounds on the real output resistance, so the current
// computed through them is a lower bound on the real current. The same choice
// is made for the LED's forward drop and series resistance in
// `tools/import_3d_model.py`.
//
// **That asymmetry is the whole point and it constrains what may be said.** A
// lower bound that exceeds a rating is a fact: the real current is larger
// still. A lower bound that sits under a rating is not a clean bill of health,
// because the real current may be anywhere above it. So this file emits a
// warning and never an all-clear.

//: A pad label that names its own voltage. **The silkscreen is the source**:
//: `5V` is five volts because that is what the vendor printed on the board, and
//: `webui/api.py` sends the pad's label as its name, so these arrive as
//: themselves without a table anybody here maintains.
//:
//: **`VBUS`, `VIN`, `IOREF`, `AREF`, `RESET` and `EN` are deliberately absent.**
//: `VIN` is whatever somebody plugged into the barrel jack and this simulation
//: has no barrel jack; `VBUS` is five volts only while a USB cable is in, and
//: there is no cable either; `IOREF` is a reference output rather than a rail
//: to draw from; the last three are pins. A part wired to one of those reaches
//: a node nothing drives, which is the truth about it.
export const RAILS = {
  GND: 0.0,
  "5V": 5.0,
  "3V3": 3.3,
  "3V3_OUT": 3.3,
};

//: Amps at which a red indicator LED is unambiguously alight.
//:
//: A 5 mm red LED is faintly visible in a dark room somewhere below a tenth of
//: a milliamp and is plainly on by one. Half a milliamp is inside that band and
//: it is a judgement made once, here, rather than in three places: no circuit
//: this bench can build lands anywhere near it, because there is no resistor on
//: the bench to build a dim one with.
export const LIT_AMPS = 5e-4;

//: Siemens from every node to ground. **SPICE's own trick, for SPICE's own
//: reason**: a node with no DC path anywhere — a part with one leg wired and
//: one in mid-air, which is precisely the case this file exists for — leaves
//: the matrix singular. A conductance far below every real one in the circuit
//: makes it solvable and changes no answer: against the 40 ohms of an AVR
//: output it is one part in 2.5e10.
export const GMIN = 1e-12;

//: Ohms across a diode that is off. Reverse leakage is real — the ATmega's own
//: input leakage is specified at a microamp — and a finite number here is what
//: keeps an off diode from disconnecting a node entirely.
export const OFF_OHMS = 1e9;

//: How many times the diode states may flip before this gives up. A
//: piecewise-linear network settles in about as many passes as it has diodes;
//: forty is far past that and short of a hang.
export const MAX_PASSES = 40;

//: Ohms stood in for a part whose electrical behaviour nobody published — see
//: `analyse`, which refuses to report a current for any bench containing one.
//: It exists to make such a part a conductor rather than a break, so that a
//: circuit through it still closes.
export const ASSUMED_OHMS = 1000;

// --- the linear solver ------------------------------------------------------

/**
 * Solve `A x = z` by Gaussian elimination with partial pivoting.
 *
 * Returns null when the matrix is singular, which the caller must treat as "no
 * answer" rather than as zeros. `A` is an array of rows and is consumed.
 */
function gauss(A, z) {
  const n = z.length;
  for (let col = 0; col < n; col++) {
    // Partial pivoting, and it is not optional here: the rows a ground-
    // referenced source produces have a zero on the diagonal by construction.
    let best = col;
    for (let row = col + 1; row < n; row++) {
      if (Math.abs(A[row][col]) > Math.abs(A[best][col])) best = row;
    }
    if (Math.abs(A[best][col]) < 1e-14) return null;
    if (best !== col) {
      const swap = A[best]; A[best] = A[col]; A[col] = swap;
      const held = z[best]; z[best] = z[col]; z[col] = held;
    }
    const pivot = A[col][col];
    for (let row = col + 1; row < n; row++) {
      const factor = A[row][col] / pivot;
      if (factor === 0) continue;
      for (let k = col; k < n; k++) A[row][k] -= factor * A[col][k];
      z[row] -= factor * z[col];
    }
  }
  const x = new Float64Array(n);
  for (let row = n - 1; row >= 0; row--) {
    let sum = z[row];
    for (let k = row + 1; k < n; k++) sum -= A[row][k] * x[k];
    x[row] = sum / A[row][row];
  }
  return x;
}

/**
 * Node voltages and branch currents for one network.
 *
 * `net` is `{nodes, elements}`. Node 0 is ground and is not an unknown. Every
 * element names `a` and `b`; a positive current is one flowing from `a` to `b`
 * inside the element.
 *
 *   `{kind: "resistor", id, a, b, ohms}`
 *   `{kind: "current",  id, a, b, amps}`   -- forced, from a to b
 *   `{kind: "source",   id, a, b, volts}`  -- ideal: V(a) - V(b) = volts
 *   `{kind: "diode",    id, a, b, volts, ohms}`  -- a is the anode
 *
 * Returns `{ok, volts, amps, passes}`; `volts` is indexed by node and `amps` is
 * a plain object keyed by element id.
 */
export function solve(net) {
  const sources = net.elements.filter((e) => e.kind === "source");
  const size = net.nodes - 1 + sources.length;
  if (size <= 0) {
    return { ok: true, volts: new Float64Array(net.nodes), amps: {}, passes: 0 };
  }
  // Which diodes are conducting. All off to begin with, because that is the
  // one starting point that does not depend on the order the parts were
  // dropped on the bench.
  const conducting = new Map();
  for (const element of net.elements) {
    if (element.kind === "diode") conducting.set(element.id, false);
  }

  let volts = null;
  let passes = 0;
  for (; passes <= MAX_PASSES; passes++) {
    const A = [];
    for (let row = 0; row < size; row++) A.push(new Float64Array(size));
    const z = new Float64Array(size);
    // `k` is the index of a node's row, or -1 for ground, which has no row.
    const k = (node) => node - 1;

    for (let node = 1; node < net.nodes; node++) A[k(node)][k(node)] += GMIN;

    const conductance = (a, b, g) => {
      if (a > 0) A[k(a)][k(a)] += g;
      if (b > 0) A[k(b)][k(b)] += g;
      if (a > 0 && b > 0) { A[k(a)][k(b)] -= g; A[k(b)][k(a)] -= g; }
    };
    const inject = (a, b, amps) => {
      // Amps forced from `a` to `b` inside the element: leaving `a`, so it is
      // a negative injection there and a positive one at `b`.
      if (a > 0) z[k(a)] -= amps;
      if (b > 0) z[k(b)] += amps;
    };

    let at = net.nodes - 1;
    for (const element of net.elements) {
      if (element.kind === "resistor") {
        conductance(element.a, element.b, 1 / element.ohms);
      } else if (element.kind === "current") {
        inject(element.a, element.b, element.amps);
      } else if (element.kind === "diode") {
        // **The Norton companion, so that a diode turning on does not change
        // the size of the matrix.** A branch carrying `Vf` in series with `R`
        // passes `i = (Va - Vb - Vf)/R`, which is a conductance `1/R` between
        // the two nodes plus a fixed `Vf/R` pushed from b to a.
        const g = 1 / (conducting.get(element.id) ? element.ohms : OFF_OHMS);
        conductance(element.a, element.b, g);
        if (conducting.get(element.id)) inject(element.a, element.b, -element.volts * g);
      } else if (element.kind === "source") {
        const column = at++;
        if (element.a > 0) { A[k(element.a)][column] += 1; A[column][k(element.a)] += 1; }
        if (element.b > 0) { A[k(element.b)][column] -= 1; A[column][k(element.b)] -= 1; }
        z[column] = element.volts;
      }
    }

    volts = gauss(A, z);
    if (volts === null) return { ok: false, volts: null, amps: {}, passes };

    // Consistency: a conducting diode that has ended up carrying current
    // backwards is not conducting, and a blocking one whose anode has risen
    // past its forward drop is.
    let flipped = false;
    for (const element of net.elements) {
      if (element.kind !== "diode") continue;
      const across = nodeVolts(volts, element.a, net.nodes)
                   - nodeVolts(volts, element.b, net.nodes);
      const on = conducting.get(element.id);
      const wants = on ? across - element.volts >= 0 : across > element.volts;
      if (wants !== on) { conducting.set(element.id, wants); flipped = true; }
    }
    if (!flipped) break;
  }
  if (passes > MAX_PASSES) {
    // Two diodes that each want the other's state. It has never been seen on
    // this bench; saying so beats reporting the last guess as an answer.
    return { ok: false, volts: null, amps: {}, passes };
  }

  const nodeVoltage = new Float64Array(net.nodes);
  for (let node = 1; node < net.nodes; node++) nodeVoltage[node] = volts[node - 1];

  const amps = {};
  let at = net.nodes - 1;
  for (const element of net.elements) {
    const across = nodeVoltage[element.a] - nodeVoltage[element.b];
    if (element.kind === "resistor") amps[element.id] = across / element.ohms;
    else if (element.kind === "current") amps[element.id] = element.amps;
    else if (element.kind === "source") amps[element.id] = volts[at++];
    else if (element.kind === "diode") {
      const on = conducting.get(element.id);
      amps[element.id] = on ? (across - element.volts) / element.ohms
                            : across / OFF_OHMS;
    }
  }
  return { ok: true, volts: nodeVoltage, amps, passes };
}

/** One node's voltage mid-solve, where ground is not in the unknown vector. */
function nodeVolts(x, node, _nodes) {
  return node === 0 ? 0 : x[node - 1];
}

// --- the bench --------------------------------------------------------------

/** Join terminals into nets. Plain union-find over string keys. */
function nets() {
  const parent = new Map();
  const find = (key) => {
    if (!parent.has(key)) parent.set(key, key);
    let root = key;
    while (parent.get(root) !== root) root = parent.get(root);
    while (parent.get(key) !== root) { const up = parent.get(key); parent.set(key, root); key = up; }
    return root;
  };
  return {
    find,
    join(one, other) { parent.set(find(one), find(other)); },
    keys() { return [...parent.keys()]; },
  };
}

/** How a number of amps reads in a sentence. */
export function milliamps(amps) {
  const mA = amps * 1000;
  if (mA >= 10) return `${mA.toFixed(0)} mA`;
  if (mA >= 1) return `${mA.toFixed(1)} mA`;
  return `${mA.toFixed(2)} mA`;
}

/**
 * What every part on the bench is doing, and why.
 *
 * `bench` is `{supply, pads, parts, wires}`:
 *
 *   supply  `{volts, sourceOhms, sinkOhms, ratedAmps, absoluteAmps, chip}`,
 *           or null for a board that publishes no electrical model
 *   pads    `[{name, state}]` — the four states `webui/api.py` defines
 *   parts   `[{label, model}]` — index is the identity, `model` may be null
 *   wires   `[{pad, part, terminal}]` — `part` is an index into `parts`
 *
 * Returns `{ok, note, parts}` with one entry per part, in the same order:
 * `{drive, amps, reason, warning}`. `drive` is one of `parts.js`'s three words.
 */
export function analyse(bench) {
  const report = bench.parts.map(() => ({
    drive: "unanswerable", amps: null, reason: "not wired to anything", warning: null,
  }));
  const answer = (note) => ({ ok: true, note, parts: report });

  const wired = new Set();
  for (const wire of bench.wires) wired.add(wire.part);
  for (const index of wired) report[index].reason = "";

  if (!bench.parts.length) return answer(null);
  if (!wired.size) {
    return answer("Drag from a pad to a terminal. A part needs a complete " +
                  "circuit — two legs, and a return path — before anything here " +
                  "can say what it is doing.");
  }
  if (!bench.supply) {
    for (const index of wired) {
      report[index].reason =
        "this board publishes no supply or output-drive model, so nothing " +
        "here can say what a pin drives";
    }
    return answer("No electrical model for this board. `webui/boards/` " +
                  "publishes a supply for the chips whose datasheets have been " +
                  "read; the rest show a pad's level and no current.");
  }

  // One net per group of joined terminals, and ground is whichever net holds a
  // pad the vendor labelled `GND`. **Three GND pads on an Uno are one net**,
  // which is what they are on the board.
  const wiring = nets();
  const padState = new Map();
  for (const pad of bench.pads) {
    padState.set(pad.name, pad.state);
    wiring.find(`pad:${pad.name}`);
  }
  const terminalKey = (index, name) => `part:${index}:${name}`;
  for (const wire of bench.wires) wiring.join(`pad:${wire.pad}`, terminalKey(wire.part, wire.terminal));
  for (const [index, part] of bench.parts.entries()) {
    for (const name of terminalsOf(part)) wiring.find(terminalKey(index, name));
  }

  const node = new Map();
  let count = 1;
  const groundRoot = groundOf(wiring, bench.pads);
  const nodeOf = (key) => {
    const root = wiring.find(key);
    if (root === groundRoot) return 0;
    if (!node.has(root)) node.set(root, count++);
    return node.get(root);
  };
  for (const key of wiring.keys()) nodeOf(key);

  const elements = [];
  const shorted = [];
  const railAt = new Map();
  for (const pad of bench.pads) {
    const where = nodeOf(`pad:${pad.name}`);
    const rail = RAILS[pad.name];
    if (rail !== undefined) {
      // Two different rails on one net is a short across a supply, which is a
      // thing a person can build with two wires and which no solve of it can
      // describe. Named rather than left to come out as a singular matrix.
      if (railAt.has(where) && railAt.get(where) !== rail) shorted.push(pad.name);
      railAt.set(where, rail);
      if (rail !== 0) elements.push({ kind: "source", id: `rail:${pad.name}`, a: where, b: 0, volts: rail });
      continue;
    }
    if (pad.state === "high" || pad.state === "low") {
      // A driven pin, as its Thevenin equivalent: the rail behind the output
      // resistance the datasheet's worst corner implies. `low` is the same
      // thing at zero volts, which is a resistor to ground.
      const ohms = pad.state === "high" ? bench.supply.sourceOhms : bench.supply.sinkOhms;
      const g = 1 / ohms;
      elements.push({ kind: "resistor", id: `pin:${pad.name}`, a: where, b: 0, ohms });
      if (pad.state === "high") {
        elements.push({ kind: "current", id: `drive:${pad.name}`, a: 0, b: where,
                        amps: bench.supply.volts * g });
      }
    }
    // `input` is high impedance and stamps nothing, which is what a pin
    // configured as an input is. Its pull-up is not modelled and this is the
    // one place that would change if it were. `unknown` stamps nothing either,
    // and every part that reaches it is reported unanswerable below.
  }

  if (shorted.length) {
    for (const index of wired) {
      report[index].reason = "in a circuit that shorts two supplies together";
    }
    return { ok: false, parts: report,
             note: `${shorted.join(" and ")} is wired to another supply. That ` +
                   `is a short circuit, not a circuit this can solve.` };
  }

  let assumed = 0;
  for (const [index, part] of bench.parts.entries()) {
    if (!wired.has(index)) continue;
    const model = part.model;
    const names = terminalsOf(part);
    const a = nodeOf(terminalKey(index, names[0]));
    const b = nodeOf(terminalKey(index, names[1]));
    if (!model) { assumed++; elements.push({ kind: "resistor", id: `part:${index}`, a, b, ohms: ASSUMED_OHMS }); continue; }
    if (model.kind === "diode") {
      elements.push({ kind: "diode", id: `part:${index}`,
                      a: nodeOf(terminalKey(index, model.from)),
                      b: nodeOf(terminalKey(index, model.to)),
                      volts: model.forwardVolts, ohms: model.seriesOhms });
    } else {
      assumed++;
      elements.push({ kind: "resistor", id: `part:${index}`, a, b,
                      ohms: model.ohms ?? ASSUMED_OHMS });
    }
  }

  const solved = solve({ nodes: count, elements });
  if (!solved.ok) {
    for (const index of wired) report[index].reason = "in a circuit that could not be solved";
    return { ok: false, parts: report,
             note: "This circuit did not settle in " + MAX_PASSES + " passes. " +
                   "Nothing is being shown for it rather than a guess." };
  }

  for (const [index, part] of bench.parts.entries()) {
    if (!wired.has(index)) continue;
    const entry = report[index];
    const names = terminalsOf(part);
    const reaching = names.filter((name) =>
      bench.wires.some((wire) => wire.part === index && wire.terminal === name));
    // A part touching a pad this repository cannot answer for is a part this
    // repository cannot answer for. The same distinction every pad keeps.
    const blind = bench.wires.some((wire) =>
      wire.part === index && padState.get(wire.pad) === "unknown"
      && RAILS[wire.pad] === undefined);
    if (blind) {
      entry.reason = "wired to a pad this board description cannot answer for";
      continue;
    }
    if (reaching.length < 2) {
      entry.drive = "off";
      entry.reason = `only its ${reaching[0]} is wired, so no current can ` +
                     `return — ${names.filter((n) => n !== reaching[0]).join(" and ")} ` +
                     `is in mid-air`;
      continue;
    }
    const amps = solved.amps[`part:${index}`] ?? 0;
    const model = part.model;
    if (!model || model.kind !== "diode") {
      entry.drive = Math.abs(amps) > LIT_AMPS ? "lit" : "off";
      entry.reason = "no published electrical model for this part, so it is a " +
                     "conductor of unknown value and no current is claimed";
      continue;
    }
    if (amps <= LIT_AMPS) {
      // **No number for a part that is off**, and not the leakage the solve
      // actually produced. A nanoamp through a reverse-biased diode is an
      // artefact of `OFF_OHMS` being finite rather than a measurement of
      // anything, and printing it beside "off" would invite a reader to
      // believe it.
      entry.drive = "off";
      const across = solved.volts[nodeOf(terminalKey(index, model.from))]
                   - solved.volts[nodeOf(terminalKey(index, model.to))];
      entry.reason = across < 0
        ? `reversed: its ${model.to} is ${(-across).toFixed(2)} V above its ` +
          `${model.from}, and a diode blocks that way`
        : "no current: nothing is driving it";
      continue;
    }
    entry.drive = "lit";
    entry.amps = assumed ? null : amps;
    entry.reason = entry.amps === null
      ? "conducting, but a part with no electrical model is in the same circuit"
      : `at least ${milliamps(amps)} through it`;
    entry.warning = warn(amps, bench.supply);
  }

  return answer(assumed
    ? "One part on this bench publishes no electrical model, so no current is " +
      "reported for any of them: a value stood in for it would decide theirs."
    : null);
}

/** The two names a part's wires may land on. */
function terminalsOf(part) {
  return part.terminals ?? (part.model ? [part.model.from, part.model.to] : []);
}

/** Which net is ground: the one holding a pad the vendor labelled `GND`. */
function groundOf(wiring, pads) {
  for (const pad of pads) {
    if (RAILS[pad.name] === 0) return wiring.find(`pad:${pad.name}`);
  }
  return null;
}

/**
 * What to say about a current that is too large, or null.
 *
 * **Only ever too large.** Every resistance the caller supplies is the upper
 * bound a datasheet guarantees, so `amps` is a lower bound on the real current:
 * over a rating it is a fact, under one it says nothing.
 */
function warn(amps, supply) {
  const over = [];
  if (supply.ratedAmps && amps > supply.ratedAmps) {
    over.push(`the ${milliamps(supply.ratedAmps)} this board rates a pin for`);
  }
  if (supply.absoluteAmps && amps > supply.absoluteAmps) {
    over.push(`the ${milliamps(supply.absoluteAmps)} absolute maximum in the ` +
              `${supply.chip}'s datasheet`);
  }
  if (!over.length) return null;
  return `No current limiting: at least ${milliamps(amps)}, past ` +
         `${over.join(" and past ")}. A real one of these would destroy the pin.`;
}
