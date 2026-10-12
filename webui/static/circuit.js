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
//
// ## Except through a pin whose drive is only typical (OH-161)
//
// An ESP32's datasheet guarantees no output corner -- its VOH and VOL are
// measured into no load at all -- and states a pin's current only as typical,
// so `webui/boards/esp32c3.py`'s `SUPPLY` is typical and says so. A current
// that runs through one of its driven pins is then typical too: it is said as
// "about", and no rating is checked against it, because a typical figure over
// a limit is not a fact and one under it is no reassurance. A current that
// reaches no driven pin -- a part between two rails -- is still a lower bound
// and is still judged.
//
// ## And the other direction: what the bench drives onto an input (OH-161)
//
// `analyse` also says, for every pin the program leaves as an input, what the
// bench puts on it: "high" or "low" where its solved voltage is past the level
// the chip is guaranteed to read that way, and "open" where nothing reaches
// it, where it sits between the two, or where a value nobody published would
// decide it. `board3d.js` posts that map to the board, which is the only way a
// level enters a running sketch, and this file only ever answers it from the
// solve: it invents no level, and "open" stays open. A board whose supply
// states no input levels gets an empty map, and nothing is posted to it.

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
//:
//: **`3.3V` and `+3.3V` are the manifest boards' spellings of the same rail**
//: (OH-161): Adafruit's and SparkFun's board files name the pad `3.3V`, and
//: Olimex's and PCBCUPID's KiCad nets `+3.3V`. `+5V` is absent for VBUS's
//: reason: on a QT Py and an Olimex devkit it is the USB cable's five volts.
export const RAILS = {
  GND: 0.0,
  "5V": 5.0,
  "3V3": 3.3,
  "3V3_OUT": 3.3,
  "3.3V": 3.3,
  "+3.3V": 3.3,
};

//: Amps at which a red indicator LED is unambiguously alight.
//:
//: A 5 mm red LED is faintly visible in a dark room somewhere below a tenth of
//: a milliamp and is plainly on by one. Half a milliamp is inside that band and
//: it is a judgement made once, here, rather than in three places.
//:
//: **This used to say no circuit could land anywhere near it, because there was
//: no resistor on the bench to build a dim one with. OH-80 put one there.** The
//: claim is now a measurement rather than an absence: the dimmest ordinary
//: circuit is a 220 ohm resistor and an LED on a XIAO SAMD21, whose pin is
//: specified to source 2 mA -- 1.1 / (330 + 231 + 30) = 1.86 mA, still nearly
//: four times this. Crossing it takes eight resistors in series on that board,
//: which is not a thing anybody wires by accident.
//: `test_a_resistor_on_the_weakest_pin_is_still_well_clear_of_the_threshold`
//: pins both halves, so the next part that narrows the margin fails a test
//: rather than quietly making this paragraph false.
export const LIT_AMPS = 5e-4;

//: Where the wiper stands, as a fraction of the element from lead A. **A
//: stated constant, not a measurement**: the bench has no knob to turn yet,
//: so the trimmer sits at the middle of its travel and this is the one line
//: that says so. Turning it is page UI for a ticket of its own; solving for
//: any position already works, because the stamp below multiplies by it.
export const POT_TRAVEL = 0.5;

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
 * Returns `{ok, volts, amps, passes, on}`; `volts` is indexed by node, `amps`
 * is a plain object keyed by element id, and `on` says which diodes conduct,
 * keyed the same way.
 */
export function solve(net) {
  const sources = net.elements.filter((e) => e.kind === "source");
  const size = net.nodes - 1 + sources.length;
  if (size <= 0) {
    return { ok: true, volts: new Float64Array(net.nodes), amps: {}, passes: 0,
             on: {} };
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
  return { ok: true, volts: nodeVoltage, amps, passes,
           on: Object.fromEntries(conducting) };
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

/**
 * Which node voltages the solve decided, and which nodes move together.
 *
 * `solve` gives every node a voltage, and some of them are artefacts: a node
 * nothing conducts to sits at zero through `GMIN`, and one reached only
 * through a part with no model sits wherever `ASSUMED_OHMS` put it. This
 * tells them apart, for `analyse`'s inputs and for whether a part's current
 * ran through a driven pin (OH-161).
 *
 * Two joins over what conducts. `decided` joins through everything, so a node
 * joined to ground's is decided by a source -- every source here is referred
 * to ground, a rail by an ideal source and a driven pin by its Thevenin
 * resistor. `group` stops at ground and at every rail, the `fixed` nodes,
 * because a fixed voltage carries no change across it: a node's group is
 * everything that can move it, and a fixed node has none. A diode that is off
 * does not conduct here -- its `OFF_OHMS` is an artefact, as `analyse` says of
 * its nanoamps. A part with no model conducts as `solve` stood it in, and
 * `analyse` marks every group it touches, so no node it reaches is read.
 */
function groups(elements, on, fixed) {
  const whole = nets();
  const local = nets();
  for (const element of elements) {
    if (element.kind === "current") continue;
    if (element.kind === "diode" && !on[element.id]) continue;
    whole.join(String(element.a), String(element.b));
    if (!fixed.has(element.a) && !fixed.has(element.b)) {
      local.join(String(element.a), String(element.b));
    }
  }
  const ground = whole.find("0");
  return {
    decided: (node) => whole.find(String(node)) === ground,
    group: (node) => (fixed.has(node) ? null : local.find(String(node))),
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
 *           or null for a board that publishes no electrical model; and
 *           `typical`, `inputHighVolts` and `inputLowVolts` where the board
 *           states them (OH-161)
 *   pads    `[{name, state}]` — the four states `webui/api.py` defines
 *   parts   `[{label, model}]` — index is the identity, `model` may be null
 *   wires   `[{pad, part, terminal}]` — `part` is an index into `parts`
 *
 * Returns `{ok, note, parts, inputs}` with one entry per part, in the same
 * order: `{drive, amps, reason, warning}`. `drive` is one of `parts.js`'s
 * three words. `inputs` is pad name -> "high", "low" or "open" for every pad
 * in state `input`, on a board whose supply states both input levels, and
 * empty on any other: the file header says what each word means.
 */
export function analyse(bench) {
  const report = bench.parts.map((part) => (part.destroyed ? {
    // **Latched, and it has to be.** A blink drives a pin high and then low; a
    // verdict that cleared on the next poll would show a destroyed LED as
    // healthy half a second later, which is the same lie in a smaller window.
    // It is also what an absolute maximum means -- past it is permanent -- so
    // the only thing that clears this is taking the part off the bench, which
    // is what a person does with a burnt LED.
    drive: "damaged", amps: null, destroyed: true, warning: null,
    reason: "destroyed earlier by more current than its absolute maximum. " +
            "What a destroyed part does electrically is not modelled, so the " +
            "circuit shown here is still the intact one",
  } : {
    drive: "unanswerable", amps: null, destroyed: false,
    reason: "not wired to anything", warning: null,
  }));
  // **Every input starts open, and only the solve below says otherwise**
  // (OH-161). Only on a board whose supply states both levels an input
  // reads: anywhere else there is nothing to hold a voltage against, and no
  // board description that reads input to send it to.
  const supply = bench.supply;
  const reads = supply?.inputHighVolts != null && supply?.inputLowVolts != null;
  const inputs = {};
  for (const pad of bench.pads) {
    if (reads && pad.state === "input") inputs[pad.name] = "open";
  }
  const answer = (note) => ({ ok: true, note, parts: report, inputs });

  // **A destroyed part is out of the reporting from here on.** Its verdict is
  // already decided and permanent; every branch below writes a verdict, so the
  // set they iterate is the wired parts that are still alive.
  const wired = new Set();
  for (const wire of bench.wires) {
    if (!report[wire.part]?.destroyed) wired.add(wire.part);
    // The from-end is a part too (OH-116), and a part reached only that way
    // is every bit as wired.
    if (wire.from !== undefined && !report[wire.from.part]?.destroyed) {
      wired.add(wire.from.part);
    }
  }
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
  for (const wire of bench.wires) {
    // A wire's far end is a pad OR another part's terminal (OH-116); the
    // union-find never cared which, and now the wire shape says so too.
    const far = wire.from === undefined
      ? `pad:${wire.pad}`
      : terminalKey(wire.from.part, wire.from.terminal);
    wiring.join(far, terminalKey(wire.part, wire.terminal));
  }
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
      // **One source per rail net** (OH-161): a board with two pads of one
      // rail -- an Adafruit Feather ESP32-C6's two `3.3V` -- has one net,
      // and two ideal sources across it leave the matrix singular.
      if (rail !== 0 && !railAt.has(where)) {
        elements.push({ kind: "source", id: `rail:${pad.name}`, a: where, b: 0, volts: rail });
      }
      railAt.set(where, rail);
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
    return { ok: false, parts: report, inputs,
             note: `${shorted.join(" and ")} is wired to another supply. That ` +
                   `is a short circuit, not a circuit this can solve.` };
  }

  let assumed = 0;
  for (const [index, part] of bench.parts.entries()) {
    if (!wired.has(index)) continue;
    const model = part.model;
    const names = terminalsOf(part);
    if (model?.kind === "potentiometer") {
      // **The first three-terminal part** (OH-126): electrically two
      // resistors sharing the wiper node -- names[1], the middle pin by
      // Bourns' own pinout. `POT_TRAVEL` places the wiper; either half at
      // zero would be a short the solver handles like any other resistor.
      const wiper = nodeOf(terminalKey(index, names[1]));
      elements.push({ kind: "resistor", id: `part:${index}:aw`,
                      a: nodeOf(terminalKey(index, names[0])), b: wiper,
                      ohms: model.ohms * POT_TRAVEL });
      elements.push({ kind: "resistor", id: `part:${index}:wb`,
                      a: wiper, b: nodeOf(terminalKey(index, names[2])),
                      ohms: model.ohms * (1 - POT_TRAVEL) });
      continue;
    }
    const a = nodeOf(terminalKey(index, names[0]));
    const b = nodeOf(terminalKey(index, names[1]));
    // `assumed` on the element too, so that no input is read off a node a
    // stood-in value moves (OH-161).
    if (!model) { assumed++; elements.push({ kind: "resistor", id: `part:${index}`, a, b, ohms: ASSUMED_OHMS, assumed: true }); continue; }
    if (model.kind === "diode") {
      elements.push({ kind: "diode", id: `part:${index}`,
                      a: nodeOf(terminalKey(index, model.from)),
                      b: nodeOf(terminalKey(index, model.to)),
                      volts: model.forwardVolts, ohms: model.seriesOhms });
    } else if (model.ohms) {
      // **A stated resistance is a published model like any other**, so this
      // does NOT count towards `assumed`. It used to: the branch was written
      // when no such part existed, and the first resistor on the bench would
      // have suppressed the current through every LED beside it -- the exact
      // opposite of what a current-limiting resistor is for.
      elements.push({ kind: "resistor", id: `part:${index}`, a, b,
                      ohms: model.ohms });
    } else {
      // A model that is neither a diode nor a resistance is a part whose
      // behaviour nobody has stated, whatever else it says about itself. It
      // stands in as `ASSUMED_OHMS` and takes every current on this bench with
      // it, which is what `assumed` means.
      assumed++;
      elements.push({ kind: "resistor", id: `part:${index}`, a, b,
                      ohms: ASSUMED_OHMS, assumed: true });
    }
  }

  const solved = solve({ nodes: count, elements });
  if (!solved.ok) {
    for (const index of wired) report[index].reason = "in a circuit that could not be solved";
    return { ok: false, parts: report, inputs,
             note: "This circuit did not settle in " + MAX_PASSES + " passes. " +
                   "Nothing is being shown for it rather than a guess." };
  }

  // Ground and every rail: the nodes a source holds. See `groups`.
  const fixed = new Set([0]);
  for (const element of elements) if (element.kind === "source") fixed.add(element.a);
  const grouped = groups(elements, solved.on, fixed);
  // The groups a driven pin can move, and the groups a value nobody
  // published can: a pad this board cannot answer for, or either end of a
  // part with no model (OH-161).
  const drivenGroups = new Set();
  const blindGroups = new Set();
  for (const pad of bench.pads) {
    if (RAILS[pad.name] !== undefined) continue;
    const group = grouped.group(nodeOf(`pad:${pad.name}`));
    if (group === null) continue;
    if (pad.state === "high" || pad.state === "low") drivenGroups.add(group);
    if (pad.state === "unknown") blindGroups.add(group);
  }
  for (const element of elements) {
    if (!element.assumed) continue;
    for (const end of [element.a, element.b]) {
      const group = grouped.group(end);
      if (group !== null) blindGroups.add(group);
    }
  }
  //: Whether a part's current ran through a pin whose drive is only
  //: typical: the file header says what is then said, and what is not.
  const typical = (index, names) => supply.typical === true
    && names.some((name) => drivenGroups.has(
      grouped.group(nodeOf(terminalKey(index, name)))));

  // **What each DRIVEN PIN carries, which is not what any one part carries.**
  // Two LEDs across one pad each draw 25 mA and the pad delivers 51 mA, so a
  // warning that measured the part's current against the pin's rating would
  // understate the pin by half -- found while writing the test for it. The
  // pin's own current comes straight out of the solve: for a pad driven high
  // it is the Thevenin source's, `(rail - node) / sourceOhms`, and for one
  // driven low it is `node / sinkOhms`.
  const pinAmps = new Map();
  for (const pad of bench.pads) {
    if (pad.state !== "high" && pad.state !== "low") continue;
    const volts = solved.volts[nodeOf(`pad:${pad.name}`)];
    pinAmps.set(pad.name, pad.state === "high"
      ? Math.abs(bench.supply.volts - volts) / bench.supply.sourceOhms
      : Math.abs(volts) / bench.supply.sinkOhms);
  }

  //: How many wired parts have one leg in mid-air. See `JUNCTION_NOTE`.
  let midAir = 0;
  //: Driven pins a surviving part warning names, so the bench-level pin note
  //: below says each fact once. A warning `destroys` nulled is NOT in here --
  //: the destroyed verdict names the part's current, not the pin's.
  const named = new Set();
  for (const [index, part] of bench.parts.entries()) {
    if (!wired.has(index)) continue;
    const entry = report[index];
    const names = terminalsOf(part);
    const reaching = names.filter((name) =>
      bench.wires.some((wire) =>
        (wire.part === index && wire.terminal === name)
        || (wire.from?.part === index && wire.from?.terminal === name)));
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
      // Counted for `JUNCTION_NOTE` below: a part with one leg wired beside
      // another part is what somebody trying to build a series circuit has in
      // front of them. See OH-84.
      midAir += 1;
      continue;
    }
    const model = part.model;
    // **A three-terminal part's number is its busiest leg** (OH-126): the
    // two halves carry different currents whenever the wiper is wired, and
    // the smaller one under-reports what the part is doing.
    const signed = model?.kind === "potentiometer"
      ? Math.max(Math.abs(solved.amps[`part:${index}:aw`] ?? 0),
                 Math.abs(solved.amps[`part:${index}:wb`] ?? 0))
      : (solved.amps[`part:${index}`] ?? 0);
    // **A diode's current is signed and a resistor's is not**, and that is a
    // fact about the parts rather than a convenience. A diode has a forward
    // direction, so the sign of its current says whether it is being driven or
    // reversed and the report below says which. A resistor conducts equally
    // either way and has no forward direction to be reversed against -- see
    // `Electrical.forward` in `tools/import_3d_model.py`, which is absent for
    // exactly this reason -- so its magnitude is the whole of what it does.
    const amps = model?.kind === "diode" ? signed : Math.abs(signed);
    // A part with no model at all, and a model that states neither a forward
    // drop nor a resistance, are the same thing to a reader: nothing here can
    // say what it does.
    if (!model || !(model.kind === "diode" || model.ohms)) {
      entry.drive = amps > LIT_AMPS ? "lit" : "off";
      entry.reason = "no published electrical model for this part, so it is a " +
                     "conductor of unknown value and no current is claimed";
      continue;
    }
    if (model.kind !== "diode" && amps <= LIT_AMPS) {
      // **Its own sentence rather than the diode's, and the branch earns its
      // place by saying something different.** A resistor carries current
      // exactly when there is a voltage across it, so "nothing is driving it"
      // understates what has been solved: its two leads are at one potential,
      // which is a fact about this circuit rather than a guess about what is
      // attached to it.
      //
      // Deleting this branch was tried and it PASSED: `model.from` is
      // undefined for a part with no forward direction, the subtraction below
      // is `NaN`, `NaN < 0` is false, and the fallthrough printed the right
      // words by accident. A correctness resting on which way round somebody
      // wrote a comparison is not one, so the case is handled where it belongs.
      entry.drive = "off";
      entry.reason = "no current: both its leads are at the same voltage";
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
    // **A typical current is said as one, and held to no limit** (OH-161):
    // neither a lower bound nor an upper one, so neither a warning nor a
    // verdict can rest on it.
    const rough = typical(index, names);
    entry.reason = entry.amps === null
      ? "conducting, but a part with no electrical model is in the same circuit"
      : rough
        ? `about ${milliamps(amps)} through it, at the ${supply.chip}'s ` +
          `typical drive -- not a bound, so no rating is checked against it`
        : `at least ${milliamps(amps)} through it`;
    // The busiest driven pin this part reaches. One part can touch two of
    // them -- an LED from a high pad to a low one -- and the one that is
    // closest to its limit is the one worth naming.
    let pin = null;
    for (const wire of bench.wires) {
      if (wire.part !== index || !pinAmps.has(wire.pad)) continue;
      const carrying = pinAmps.get(wire.pad);
      if (!pin || carrying > pin.amps) pin = { name: wire.pad, amps: carrying };
    }
    entry.warning = rough ? null : warn(amps, bench.supply, model, pin);
    // **The verdict, and it outranks the picture.** A part carrying more than
    // its datasheet's absolute maximum is not a lit part with a caption -- it
    // is a destroyed one, and drawing it glowing beside a paragraph saying so
    // lets the picture win the disagreement.
    const killed = assumed || rough ? null : destroys(amps, model);
    if (killed) {
      entry.drive = "damaged";
      entry.destroyed = true;
      entry.reason = killed;
      entry.warning = null;
    }
    if (entry.warning && pin && pinSentence(pin.name, pin.amps, bench.supply)) {
      named.add(pin.name);
    }
  }

  //: **How parts go in series, and this is where a reader finds out**
  //: rather than by trying and getting no explanation. OH-84 wrote this
  //: when two parts could NOT be wired to each other; OH-116 made the
  //: direct wire real, so the note now offers both routes and retires on
  //: any bench that has already joined parts directly.
  //:
  //: Every wire here runs from a BOARD PAD to a part terminal --
  //: `board3d.js`'s `connect(pin, part, terminalName)` looks the pin up in
  //: `view.pads` and refuses anything it cannot find, and a wire above is
  //: `{pad, part, terminal}`. There is no shape in either file for a wire
  //: between two parts, so a series circuit has to borrow a pin.
  //:
  //: **That is not a trick and it is worth saying why**: a pad the firmware
  //: leaves as an input is high impedance, stamps nothing into the netlist
  //: above, and is therefore exactly a floating node. The circuit OH-80 exists
  //: to make possible was verified that way.
  //:
  //: Shown only when there are two or more parts and one of them has a leg in
  //: mid-air, which is what somebody trying to chain them is looking at. On a
  //: bench with a single part the mid-air message is already the whole story
  //: and this would be noise.
  const JUNCTION_NOTE =
    "To put parts in series, drag from one part's terminal to another's --\n" +
    "a wire's ends may be two parts since OH-116 -- or borrow a pad the " +
    "firmware leaves as an INPUT as the junction: an input is high "
    + "impedance and stamps nothing into the netlist, so it is exactly a " +
    "floating node. D13 \u2192 resistor \u2192 D12 \u2192 LED \u2192 GND is a current-limited " +
    "LED wired the borrowed way.";

  const notes = [];
  // **A pin past a limit is named whether or not anything lights** (OH-130).
  // D13 driven high and wired with GND onto an LED's one wired leg is 5 V
  // through the pin's own 40 ohms -- at least 125 mA, past the 40 mA absolute
  // maximum -- and the whole report used to say only "off ... cathode is in
  // mid-air": `warn` was reachable only through a lit part, and nothing in
  // that circuit lights. The pin's current is already in `pinAmps` whatever
  // the parts do, so the check belongs to the pin. A pin a surviving warning
  // already names is skipped -- one sentence per fact, not one per place that
  // noticed it.
  for (const [name, amps] of pinAmps) {
    // A pin's own current is through its own drive, so on a typical supply
    // it is typical, and the file header says what that rules out (OH-161).
    if (named.has(name) || supply.typical === true) continue;
    const sentence = pinSentence(name, amps, bench.supply);
    if (sentence) notes.push(sentence);
  }
  notes.push(...readInputs(supply, inputs, nodeOf, solved, grouped,
                           blindGroups));
  if (assumed) {
    notes.push("One part on this bench publishes no electrical model, so no " +
               "current is reported for any of them: a value stood in for it " +
               "would decide theirs.");
  }
  if (bench.parts.length > 1 && midAir
      && !bench.wires.some((wire) => wire.from !== undefined)) {
    notes.push(JUNCTION_NOTE);
  }
  return answer(notes.length ? notes.join(" ") : null);
}

/**
 * Fill `inputs` from the solve, and return what the bench note must say
 * about it (OH-161). Called by `analyse` only once the circuit has solved.
 *
 * A pad is "open" until something decides it: a group a value nobody
 * published can move keeps it open, and so does a node no source reaches --
 * it is at zero only through `GMIN`. A decided voltage is held against the
 * two levels the chip guarantees an input reads: at or past `inputHighVolts`
 * it is "high", at or under `inputLowVolts` "low", and between the two the
 * datasheet promises neither, so it stays "open" and the note says where it
 * sits. Kept "open" rather than at the last level, because holding a level
 * would be a hysteresis these pads do not have by default.
 */
function readInputs(supply, inputs, nodeOf, solved, grouped, blindGroups) {
  const between = [];
  const blind = [];
  for (const name of Object.keys(inputs)) {
    const at = nodeOf(`pad:${name}`);
    const group = grouped.group(at);
    if (group !== null && blindGroups.has(group)) { blind.push(name); continue; }
    if (!grouped.decided(at)) continue;
    const volts = solved.volts[at];
    if (volts >= supply.inputHighVolts) inputs[name] = "high";
    else if (volts <= supply.inputLowVolts) inputs[name] = "low";
    else between.push(`${name} is at ${volts.toFixed(2)} V`);
  }
  const notes = [];
  if (between.length) {
    notes.push(`${between.join(" and ")}, between the ${supply.inputLowVolts} V ` +
               `the ${supply.chip} is guaranteed to read as low and the ` +
               `${supply.inputHighVolts} V it is guaranteed to read as high, so ` +
               `the board is told nothing drives it.`);
  }
  if (blind.length) {
    notes.push(`${blind.join(" and ")} would read whatever a part with no ` +
               `published model, or a pad this board cannot answer for, made ` +
               `of it, so the board is told nothing drives it.`);
  }
  return notes;
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
 *
 * **A rated current and an absolute maximum are different claims**, and this is
 * the distinction the whole of `damaged` rests on. A rated continuous current
 * is what a part is sold against: past it is outside its specification and is
 * not destruction. An absolute maximum is a stress rating, and the datasheets
 * say what that means in as many words -- DS40002061B, over the table this
 * repository reads the ATmega328P's 40.0 mA from: *"Stresses beyond those
 * listed under Absolute Maximum Ratings may cause permanent damage to the
 * device."* So one produces a sentence and the other produces a verdict.
 */
function warn(amps, supply, model, pin) {
  const said = [];
  if (model?.ratedAmps && amps > model.ratedAmps) {
    said.push(`No current limiting: at least ${milliamps(amps)} through it, ` +
              `past the ${milliamps(model.ratedAmps)} this part is rated for.`);
  }
  // **The PIN is measured by the pin's own current**, which is the sum of
  // everything hanging off it and not this part's share. It is also a separate
  // sentence because it is a separate object: the part may be inside its
  // ratings while the pad driving it is not.
  const sentence = pin ? pinSentence(pin.name, pin.amps, supply) : null;
  if (sentence) said.push(sentence);
  return said.length ? said.join(" ") : null;
}

/**
 * The sentence naming a driven pin past a limit, or null inside them.
 *
 * One function for the two places the sentence is said -- a lit part's
 * warning, and the bench-level note for a pin no surviving warning accounts
 * for (OH-130) -- so the two cannot drift apart and a reader meets one shape
 * either way.
 */
function pinSentence(name, amps, supply) {
  const over = [];
  if (supply.ratedAmps && amps > supply.ratedAmps) {
    over.push(`the ${milliamps(supply.ratedAmps)} this board rates a pin for`);
  }
  if (supply.absoluteAmps && amps > supply.absoluteAmps) {
    over.push(`the ${milliamps(supply.absoluteAmps)} absolute maximum in the ` +
              `${supply.chip}'s datasheet, which is permanent`);
  }
  if (!over.length) return null;
  return `Pin ${name} carries at least ${milliamps(amps)}, past ` +
         `${over.join(" and past ")}.`;
}

/**
 * Whether this current destroys this part, and the sentence saying which limit.
 *
 * **Only an absolute maximum answers yes**, and a part that publishes none can
 * never be declared destroyed here however much current it carries. That is not
 * caution for its own sake: the claim is that a physical object is ruined, and
 * the only number that supports it is the one whose datasheet says so.
 *
 * The arithmetic is safe in both directions at once. `amps` is a LOWER bound,
 * because every resistance behind it is a datasheet's worst corner; the limit
 * is an UPPER bound, because `tools/import_3d_model.py` picks the generous end
 * of the band for exactly this. A lower bound over an upper bound holds under
 * every reading of both.
 */
function destroys(amps, model) {
  if (!model?.absoluteAmps || amps <= model.absoluteAmps) return null;
  return `Destroyed: at least ${milliamps(amps)} through a part whose absolute ` +
         `maximum is ${milliamps(model.absoluteAmps)}. Past an absolute ` +
         `maximum is permanent, so it stays destroyed until it is taken off ` +
         `the bench.`;
}
