// OpenHardware — a jumper lead, simulated rather than drawn.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this solves for its caller
//
// **Two endpoints and an elapsed time in; a settled chain of points out.** It
// knows nothing about boards, pads, parts, three.js or the DOM, and that is
// what lets `tests/webui/test_wires.py` run it under node and assert what it
// actually does instead of reading its source for the shape of it.
//
// Every other JavaScript test in this repository checks a rendering rule by
// grepping the file, because a WebGL scene cannot be rendered from Python and
// there was nothing else to do. This one does not have that excuse: a rope is
// arithmetic, so it is arithmetic in a file with no imports.
//
// ## Verlet, and why the timestep is fixed
//
// Position Verlet: each node remembers where it was, velocity is implied by
// the difference, and a constraint that moves a node also changes its velocity
// for free. That last property is the whole reason to use it here -- the
// segments are enforced by projection, and projection in Verlet is stable
// where a spring of the same stiffness explodes.
//
// **The substep is fixed at 1/120 s and the accumulator is the reason this is
// testable at all.** Integrating by the frame's own delta makes a cable that
// hangs differently on a 60 Hz and a 144 Hz display, and there is no assertion
// that is true of both. A fixed step with a bounded catch-up gives the same
// cable everywhere, and gives a test a number of steps rather than a duration.
//
// `MAX_SUBSTEPS` is the other half: a tab that was in the background for a
// minute reports a sixty-second frame, and without a cap that is 7,200 steps
// in one go -- a freeze, followed by a cable that has swung wildly for a
// minute. Dropping the excess makes the simulation lag reality after a stall,
// which is the right trade for a picture of a wire.

//: Seconds per physics step. 1/120 rather than 1/60 so that a 60 Hz display
//: takes two steps a frame and a 144 Hz display takes one and banks the
//: remainder -- both stable, neither starved.
export const SUBSTEP = 1 / 120;

//: How many steps one call may take. Eight is 1/15 s of catch-up: enough to
//: ride out a slow frame, far short of a background tab's minute.
export const MAX_SUBSTEPS = 8;

//: Scene units per second squared, downward. **Not 9.81**: the scene's unit is
//: an image pixel at 8 px/mm, so a real metre is 8,000 units and real gravity
//: would be 78,480 -- a wire that falls a board's width in three milliseconds.
//: This is the value at which a 20 mm jumper lead settles in about a second,
//: which is what a wire that length looks like on a bench.
export const GRAVITY = -36;

//: Velocity kept per step. Air, and the cable's own stiffness, neither of
//: which is modelled: a rope with none of this never stops swinging.
export const DAMPING = 0.982;

//: Constraint passes per step. Below about eight the cable stretches visibly
//: when an end is dragged fast; above about twenty nothing changes and it is
//: the most expensive loop here.
export const ITERATIONS = 14;

//: Nodes in a wire. Twenty-two segments bend smoothly enough at the radius
//: these are drawn at, and the cost is linear in this number times
//: `ITERATIONS`.
export const NODES = 22;

//: How hard the wire resists being bent, from 0 to 1.
//:
//: **A jumper lead is not a rope and this is the difference.** A chain of
//: distance constraints alone has no opinion about angle: it hangs in a
//: catenary, folds on itself where it is slack, and lies flat in a puddle when
//: an end is moved close. A real lead has a copper core in a sleeve -- it
//: springs, it holds a bend, and it stands off a board rather than pooling on
//: it.
//:
//: Modelled as a second distance constraint between every node and the one two
//: along, whose rest length is what it would be if the wire were straight.
//: Weighting that correction is what makes the wire springy rather than rigid:
//: at 1 it is a welding rod, at 0 it is the rope it was before.
export const STIFFNESS = 0.4;

//: Rest length as a multiple of the straight-line gap when a wire is made.
//: A real jumper lead is bought by length and used wherever it reaches, so it
//: is nearly always slack. 1.35 is the sag of a lead spanning about three
//: quarters of its length.
export const SLACK = 1.35;

/**
 * A wire between two points, as a chain of nodes under gravity.
 *
 * Both ends are pinned: `head` is the pad it was pulled from and `tail` is
 * wherever the other end has got to. Everything between is free.
 */
export class Rope {
  /**
   * @param {number[]} head three coordinates
   * @param {number[]} tail three coordinates
   * @param {number} nodes
   * @param {number} slack
   */
  constructor(head, tail, nodes = NODES, slack = SLACK) {
    if (nodes < 3) throw new Error("a rope needs at least three nodes");
    this.count = nodes;
    // Flat and preallocated. A rope is stepped up to eight times a frame and
    // an array of objects would allocate three vectors per node per pass.
    this.position = new Float64Array(nodes * 3);
    this.previous = new Float64Array(nodes * 3);
    this.time = 0;
    //: What the wire is not allowed to pass through. Plain data -- boxes and
    //: spheres in world coordinates -- supplied by the caller each frame,
    //: because this file is not allowed to know what a board or a part is.
    //: See `collide`.
    this.colliders = [];
    //: The height of the bench. A wire with nothing under it falls forever,
    //: and a wire that has left the scene is worse than one lying on a table.
    this.floor = -Infinity;

    const gap = distance(head, tail);
    // A rope whose ends coincide still needs a rest length, or every segment
    // is zero and the constraint divides by it.
    this.segment = Math.max(gap * slack, 1e-3) / (nodes - 1);

    // Laid out straight to begin with, then it falls. Starting it already
    // sagging would be a guess at the shape it is about to find anyway.
    for (let i = 0; i < nodes; i++) {
      const t = i / (nodes - 1);
      for (let axis = 0; axis < 3; axis++) {
        const value = head[axis] + (tail[axis] - head[axis]) * t;
        this.position[i * 3 + axis] = value;
        this.previous[i * 3 + axis] = value;
      }
    }
  }

  /** Move the pinned end at the pad. */
  moveHead(point) {
    this.position[0] = point[0];
    this.position[1] = point[1];
    this.position[2] = point[2];
    this.payOut();
  }

  /** Move the pinned end at the part, or at the pointer while dragging. */
  moveTail(point) {
    const last = (this.count - 1) * 3;
    this.position[last] = point[0];
    this.position[last + 1] = point[1];
    this.position[last + 2] = point[2];
    this.payOut();
  }

  /**
   * Lengthen the wire if its ends have been pulled further apart than it
   * reaches. **Measured, not anticipated:** dragging an end nine units beyond
   * reach left the worst segment 140% over its rest length -- a rubber band,
   * not a cable, and the constraint cannot fix it because there is no shape a
   * rope that short can take between those two points.
   *
   * A real bench has two answers to this and neither is stretching: the wire
   * pulls the part over, or you reach for a longer lead. The part is not
   * simulated as a body with mass, so this is the second one. **It only ever
   * grows** -- dragging back leaves the extra length as slack, which is what a
   * lead does once you have picked it up.
   *
   * **What is left after this is a transient, and it is worth the numbers.**
   * Paying out gives the rope a shape it *can* take; finding it takes several
   * frames, because a Gauss-Seidel pass carries a correction one node along
   * and there are twenty-two of them. Measured 2026-08-27, after teleporting
   * an end nine units: 82% over rest on the frame itself, under 2% within ten
   * frames, and settled by twenty-five. **A pointer never teleports** -- the
   * same nine units dragged smoothly across ninety frames never exceeds 1.66%,
   * which is the case that actually happens.
   */
  payOut() {
    const gap = distance(this.point(0), this.point(this.count - 1));
    // A shade longer than the gap rather than exactly it, or the rope is
    // perfectly taut and every rounding error reads as a stretch.
    const needed = (gap / 0.98) / (this.count - 1);
    if (needed > this.segment) this.segment = needed;
  }

  /**
   * Give the wire the slack a lead of this length would have.
   *
   * **Called when a wire is finished, and it is the fix for a wire that was
   * taut.** A wire begins with its two ends on the same pad -- the drag has
   * not gone anywhere yet -- so its rest length begins at nothing and `payOut`
   * only ever grows it to just span the gap. The result reached its terminal
   * as a straight line under tension, and a taut wire lying against a board
   * fights the contact that holds it up: measured 2026-08-27, 75.6% over rest.
   * With the slack a real lead has, the same wire settles at 0.4%.
   *
   * `payOut` stays as it is and does a different job: it is what stops a wire
   * being *stretched* while an end is dragged beyond its reach. This is what
   * gives it a shape once it has somewhere to hang between.
   */
  slacken(slack = SLACK) {
    const gap = distance(this.point(0), this.point(this.count - 1));
    this.segment = Math.max(gap * slack, 1e-3) / (this.count - 1);
  }

  /** Node `index`, as a three-element array. */
  point(index) {
    const at = index * 3;
    return [this.position[at], this.position[at + 1], this.position[at + 2]];
  }

  /**
   * Advance by a real elapsed time, in whole substeps.
   *
   * Returns how many substeps were taken, which is what a test asserts on:
   * "one second of a 60 Hz frame" is a duration, and "one hundred and twenty
   * steps" is a fact.
   */
  advance(seconds) {
    // A negative delta is the browser's, not this code's, and a tab restored
    // from the background reports an enormous positive one.
    this.time += Math.max(seconds, 0);
    let taken = 0;
    while (this.time >= SUBSTEP && taken < MAX_SUBSTEPS) {
      this.step();
      this.time -= SUBSTEP;
      taken += 1;
    }
    // **The leftover is dropped, not banked, and there is one guard rather
    // than two.** The first version also clamped the accumulator before the
    // loop, which made the loop's own cap unreachable -- removing it changed
    // nothing at all, which a mutation found and no test could. Belt and
    // braces read as care and are two things to keep true; this is one.
    if (taken === MAX_SUBSTEPS) this.time = 0;
    return taken;
  }

  /** One substep: integrate, then project the segments back to length. */
  step() {
    const fall = GRAVITY * SUBSTEP * SUBSTEP;
    // The ends are pinned, so they are read but never integrated. Their
    // `previous` is kept level with their position so that dragging one does
    // not fling the rope: an end that moved ten units in a frame would
    // otherwise carry that as velocity into the next.
    for (let i = 1; i < this.count - 1; i++) {
      for (let axis = 0; axis < 3; axis++) {
        const at = i * 3 + axis;
        const here = this.position[at];
        const velocity = (here - this.previous[at]) * DAMPING;
        this.previous[at] = here;
        this.position[at] = here + velocity + (axis === 1 ? fall : 0);
      }
    }
    const last = (this.count - 1) * 3;
    for (let axis = 0; axis < 3; axis++) {
      this.previous[axis] = this.position[axis];
      this.previous[last + axis] = this.position[last + axis];
    }
    // Interleaved, with contact last in the pass so a node never ends a step
    // inside a solid. Resolving contact once at the very end instead was
    // measured and is worse -- 75.6% over rest against 16.3% -- because an
    // unopposed push leaves a shape the next step's constraints have to undo.
    for (let pass = 0; pass < ITERATIONS; pass++) {
      this.relax();
      this.stiffen();
      this.collide();
    }
  }

  /** One pass of the distance constraint, over every segment. */
  relax() {
    for (let i = 0; i < this.count - 1; i++) {
      const a = i * 3;
      const b = a + 3;
      const dx = this.position[b] - this.position[a];
      const dy = this.position[b + 1] - this.position[a + 1];
      const dz = this.position[b + 2] - this.position[a + 2];
      const length = Math.hypot(dx, dy, dz);
      if (length === 0) continue;
      // How far each end must move, halved -- except at a pinned end, where
      // the free neighbour takes the whole correction. Sharing it with a node
      // that cannot move is what makes a dragged wire stretch.
      const error = (length - this.segment) / length;
      const headPinned = i === 0;
      const tailPinned = i + 1 === this.count - 1;
      const share = headPinned || tailPinned ? 1 : 0.5;
      if (!headPinned) {
        const move = tailPinned ? 1 : share;
        this.position[a] += dx * error * move;
        this.position[a + 1] += dy * error * move;
        this.position[a + 2] += dz * error * move;
      }
      if (!tailPinned) {
        const move = headPinned ? 1 : share;
        this.position[b] -= dx * error * move;
        this.position[b + 1] -= dy * error * move;
        this.position[b + 2] -= dz * error * move;
      }
    }
  }

  /**
   * Resist bending: pull each node and the one two along toward straight.
   *
   * **Both ends of a bending pair may be free, unlike a segment**, so this one
   * shares its correction evenly and simply skips a pinned node -- there is no
   * "the other end takes it all" case, because a bend at the very end of a
   * wire is exactly where a real lead is stiffest and it should not be
   * specially floppy there.
   */
  stiffen() {
    if (STIFFNESS <= 0) return;
    const rest = this.segment * 2;
    for (let i = 0; i < this.count - 2; i++) {
      const a = i * 3;
      const b = a + 6;
      const dx = this.position[b] - this.position[a];
      const dy = this.position[b + 1] - this.position[a + 1];
      const dz = this.position[b + 2] - this.position[a + 2];
      const length = Math.hypot(dx, dy, dz);
      if (length === 0) continue;
      const error = ((length - rest) / length) * STIFFNESS * 0.5;
      if (i !== 0) {
        this.position[a] += dx * error;
        this.position[a + 1] += dy * error;
        this.position[a + 2] += dz * error;
      }
      if (i + 2 !== this.count - 1) {
        this.position[b] -= dx * error;
        this.position[b + 1] -= dy * error;
        this.position[b + 2] -= dz * error;
      }
    }
  }

  /**
   * Push every free node out of anything it has got inside.
   *
   * **Run inside the constraint loop and not after it**, which costs fourteen
   * passes instead of one and is the difference between a wire that lies on a
   * board and a wire that sinks halfway into it: a node pushed to the surface
   * by the last pass is pulled straight back in by its neighbours if nothing
   * runs afterwards.
   *
   * The correction moves the position and leaves `previous` alone, so the
   * node loses the velocity it had into the surface -- which is what makes a
   * cable land and stay rather than bounce.
   */
  collide() {
    for (let i = 1; i < this.count - 1; i++) {
      const at = i * 3;
      if (this.position[at + 1] < this.floor) this.position[at + 1] = this.floor;
      for (const solid of this.colliders) {
        if (solid.kind === "sphere") this.outOfSphere(at, solid);
        else this.outOfBox(at, solid);
      }
    }
  }

  /** Push one node to the surface of a sphere it is inside. */
  outOfSphere(at, solid) {
    const dx = this.position[at] - solid.at[0];
    const dy = this.position[at + 1] - solid.at[1];
    const dz = this.position[at + 2] - solid.at[2];
    const length = Math.hypot(dx, dy, dz);
    if (length >= solid.r) return;
    // A node exactly at the centre has no direction to leave by; up is as
    // good as any and cannot be a division by zero.
    if (length === 0) {
      this.position[at + 1] += solid.r;
      return;
    }
    const scale = solid.r / length;
    this.position[at] = solid.at[0] + dx * scale;
    this.position[at + 1] = solid.at[1] + dy * scale;
    this.position[at + 2] = solid.at[2] + dz * scale;
  }

  /**
   * Push one node out of an axis-aligned box, by the shortest way.
   *
   * Shortest rather than "the way it came": a node that has been pushed deep
   * by its neighbours has no memory of a way in, and choosing the face it is
   * nearest is what makes a wire drape over a board rather than squirt out of
   * its side.
   */
  outOfBox(at, solid) {
    for (let axis = 0; axis < 3; axis++) {
      if (this.position[at + axis] <= solid.min[axis]) return;
      if (this.position[at + axis] >= solid.max[axis]) return;
    }
    let bestAxis = 0;
    let bestDepth = Infinity;
    let bestTo = 0;
    for (let axis = 0; axis < 3; axis++) {
      const here = this.position[at + axis];
      const below = here - solid.min[axis];
      const above = solid.max[axis] - here;
      if (below < bestDepth) {
        bestDepth = below;
        bestAxis = axis;
        bestTo = solid.min[axis];
      }
      if (above < bestDepth) {
        bestDepth = above;
        bestAxis = axis;
        bestTo = solid.max[axis];
      }
    }
    this.position[at + bestAxis] = bestTo;
  }

  /**
   * The sum of the squared speeds of the free nodes.
   *
   * **Here for a test rather than for the simulation**, and it is the one
   * number that says a rope is stable: a Verlet chain with too stiff a
   * constraint or too large a step gains energy every pass and leaves the
   * screen, and it does so silently -- the frames before it goes look fine.
   */
  energy() {
    let total = 0;
    for (let i = 1; i < this.count - 1; i++) {
      for (let axis = 0; axis < 3; axis++) {
        const at = i * 3 + axis;
        const velocity = this.position[at] - this.previous[at];
        total += velocity * velocity;
      }
    }
    return total;
  }

  /** How far the chain actually is from its rest shape, worst segment. */
  worstStretch() {
    let worst = 0;
    for (let i = 0; i < this.count - 1; i++) {
      const a = i * 3;
      const here = Math.hypot(
        this.position[a + 3] - this.position[a],
        this.position[a + 4] - this.position[a + 1],
        this.position[a + 5] - this.position[a + 2]
      );
      worst = Math.max(worst, Math.abs(here - this.segment) / this.segment);
    }
    return worst;
  }
}

function distance(a, b) {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}
