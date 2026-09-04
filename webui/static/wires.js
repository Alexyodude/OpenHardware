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
    //: Half the thickness of the lead, in the same units. Plain data the
    //: caller supplies, exactly like `colliders` -- this file has never seen
    //: the tube that is drawn around these points and is not about to start.
    //:
    //: **Zero is the default and it is the old behaviour**, so a caller that
    //: draws nothing still gets the centreline solver, and every test written
    //: before OH-162 still describes what it did.
    //:
    //: What it buys, in one sentence: `collide` keeps a node's CENTRE this far
    //: off every surface, so the tube rests ON a chip rather than half inside
    //: one. Measured 2026-09-04 on a settled 28-unit wire over a 12 x 3.5 x 6
    //: box -- the OH-132 probe read `proud` 0.16, the whole radius, with the
    //: solver unaware of it.
    this.radius = 0;

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
   *
   * **What is pushed out is the tube and not the centreline** (OH-162). Every
   * surface below is offset by `radius` rather than the node being tested
   * against the surface itself: the bench rises by it, the sphere and the box
   * grow by it. That is the standard way to collide a sphere with a solid, and
   * is why there is one number here and no per-shape special case.
   *
   * **And it runs twice, because a radius is a preference and being outside a
   * solid is a requirement.** Growth is per solid and resolution is
   * sequential, so a node ejected onto solid B's grown face can land inside
   * solid A's real box, and with A already done nothing pushes it out again.
   * That is not a corner case: a chip sitting flush on a board has its grown
   * bottom face a radius BELOW the slab's top. Measured 2026-09-04 on a wire
   * pinned to two pads over a board with one chip on it -- `inside` went from
   * 0 to 0.16, the number this file itself calls the fault. So the wanted
   * radius is resolved first, then the UNGROWN solids are resolved again,
   * which is character for character the guarantee this file had before
   * OH-162 and restores that same 0.
   *
   * The second pass is skipped for a node the first one never pushed, which
   * is most of them: a node outside a grown solid is outside the real one, so
   * there is nothing for it to find. Measured on that fixture, it ran on
   * 133,885 of 336,000 node visits. **Skipping on that condition rather than
   * on the node having MOVED is the review's second finding, and the
   * difference is a fixed point**: two solids 0.05 apart push a node out and
   * straight back within one pass, so its coordinates come out identical to
   * what they went in as while both pushes really happened. A net-position
   * guard sees nothing to do and leaves the node 0.11 inside the first
   * solid, for ever, because it is a fixed point. Whether a push EXECUTED
   * cannot be fooled that way, and it is the same skip rate.
   */
  collide() {
    // The bench is a plane, so the centre stops a radius above it. Written as
    // its own name rather than folded into `this.floor`, because the caller's
    // floor is where the bench is and not where a wire's middle may go.
    const bench = this.floor + this.radius;
    for (let i = 1; i < this.count - 1; i++) {
      const at = i * 3;
      if (this.position[at + 1] < bench) this.position[at + 1] = bench;
      if (this.outOfSolids(at, this.radius)) this.outOfSolids(at, 0);
    }
  }

  /**
   * Push one node clear of every collider, each grown by `r`.
   *
   * Returns whether any of them pushed, which is what `collide` gates its
   * second pass on. **Not short-circuited**: every solid is asked even after
   * one has moved the node, because a node ejected by one may now be inside
   * the next.
   */
  outOfSolids(at, r) {
    let pushed = false;
    for (const solid of this.colliders) {
      const moved = solid.kind === "sphere"
        ? this.outOfSphere(at, solid, r)
        : this.outOfBox(at, solid, r);
      pushed = pushed || moved;
    }
    return pushed;
  }

  /**
   * Push one node clear of a sphere, as though the node had radius `r`.
   *
   * `r` is the caller's and not `this.radius`, because `collide` runs this
   * twice at two different radii -- see its second paragraph. Returns whether
   * it pushed, which is what gates that second pass.
   */
  outOfSphere(at, solid, r) {
    // Two spheres touch when their centres are a radius plus a radius apart,
    // so the whole of this function is the old one with `solid.r` replaced by
    // that sum -- which at `r` 0 is the same number, and so the same answer.
    const reach = solid.r + r;
    const dx = this.position[at] - solid.at[0];
    const dy = this.position[at + 1] - solid.at[1];
    const dz = this.position[at + 2] - solid.at[2];
    const length = Math.hypot(dx, dy, dz);
    if (length >= reach) return false;
    // A node exactly at the centre has no direction to leave by; up is as
    // good as any and cannot be a division by zero.
    if (length === 0) {
      this.position[at + 1] += reach;
      return true;
    }
    const scale = reach / length;
    this.position[at] = solid.at[0] + dx * scale;
    this.position[at + 1] = solid.at[1] + dy * scale;
    this.position[at + 2] = solid.at[2] + dz * scale;
    return true;
  }

  /**
   * Push one node clear of an axis-aligned box, by the shortest way, as
   * though the node had radius `r`.
   *
   * Shortest rather than "the way it came": a node that has been pushed deep
   * by its neighbours has no memory of a way in, and choosing the face it is
   * nearest is what makes a wire drape over a board rather than squirt out of
   * its side.
   *
   * **The box this sees is the drawn one grown by `r` on every axis**
   * (OH-162), which keeps the tube out rather than the centreline. `r` is the
   * caller's rather than `this.radius` because `collide` runs this twice at
   * two different radii; see its second paragraph for why. At `r` 0 every line
   * below is the arithmetic this had before OH-162.
   *
   * The price of a grown box is square corners where a swept tube would have
   * round ones, so a node passing a chip's corner clears it by up to
   * `r * (sqrt(3) - 1)` more than it needs to -- 0.117 units at the 0.16 a
   * lead is drawn at, and smaller than the tube whose position is in question.
   *
   * **In millimetres that is 0.208 on the Uno and 0.146 on a generated board**,
   * and getting this conversion wrong is easy enough that it is worth writing
   * out: `view.mmScale` is scene units PER MILLIMETRE, and the Uno's is
   * `5.638 px/mm * SCALE` = 0.5638, not 5.638. A review caught this comment
   * dividing by the px/mm figure and stating 0.021 mm, ten times too small.
   * The same slip is older than this change and is in
   * `test_a_wire_resting_on_a_box_reports_the_contact_the_collider_resolved`
   * and in OH-132's own ticket.
   *
   * Rounding the corner properly means clamping to the box and pushing along
   * the residual, which is a different function; it can arrive when a picture
   * shows this one.
   *
   * **A box with no thickness on an axis becomes a `2 * r` obstacle** where
   * it used to be nothing, since the early-out below is `<=`/`>=` and could
   * never be entered before. Latent rather than live: measured 2026-09-05,
   * the eleven shipped board models carry 775 solids between them, none
   * degenerate on any axis, and the thinnest real one is 0.23 mm -- the
   * height of an 0201 resistor on the XIAO ESP32-C3.
   *
   * Returns whether it pushed, which is what gates `collide`'s second pass.
   */
  outOfBox(at, solid, r) {
    for (let axis = 0; axis < 3; axis++) {
      if (this.position[at + axis] <= solid.min[axis] - r) return false;
      if (this.position[at + axis] >= solid.max[axis] + r) return false;
    }
    let bestAxis = 0;
    let bestDepth = Infinity;
    let bestTo = 0;
    for (let axis = 0; axis < 3; axis++) {
      const here = this.position[at + axis];
      const under = solid.min[axis] - r;
      const over = solid.max[axis] + r;
      const below = here - under;
      const above = over - here;
      if (below < bestDepth) {
        bestDepth = below;
        bestAxis = axis;
        bestTo = under;
      }
      if (above < bestDepth) {
        bestDepth = above;
        bestAxis = axis;
        bestTo = over;
      }
    }
    this.position[at + bestAxis] = bestTo;
    return true;
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

  /**
   * How this wire sits against the solids it was solved against.
   *
   * **Three numbers, because the one number this replaces stood for three
   * different facts and reported the wrong one.** `outOfBox` snaps a
   * colliding node exactly onto the face and `step` runs `collide` LAST in
   * every pass, so at the end of a step no free node is strictly inside
   * anything -- and a probe that asks "how far inside is the worst node"
   * answers 0 for precisely the nodes the collider handled. Measured
   * 2026-09-04, a settled 28-unit wire over a 12 x 3.5 x 6 box: 0.0000, with
   * node 5 sitting at x = -6.000, flush in the box's -X face.
   *
   *   `inside`  worst depth of a FREE node strictly inside a solid. A fault,
   *             and the number OH-78 meant to be watching. Zero is the pass.
   *   `proud`   worst distance a node's TUBE reaches past a face while its
   *             centre is on or outside it. **Contact, not interpenetration**
   *             -- and until OH-162 it was unavoidable: `collide` moved node
   *             centres, so a lead resting on a chip had half its tube inside
   *             it by construction and calling that a fault would have failed
   *             every wire that worked. **A FREE node of a wire the solver
   *             was given a `radius` for reads 0 here**, and that is OH-162
   *             step 1 as a number.
   *
   *             **The wire as a whole does not, and an earlier draft of this
   *             line claimed it did.** This loop runs `0` to `count`, so the
   *             pinned ends are measured for `proud` as well -- the `pinned`
   *             bucket only takes them when they are strictly INSIDE -- and
   *             `collide` never moves an end. A pad's centre sits 0.04 above
   *             the board slab, so a head anchored there has 0.12 of a 0.16
   *             tube in the board by construction. Measured 2026-09-04 on a
   *             wire pinned to two pads over a slab: 0.12, from the head and
   *             from no free node at all. What a free node still reports is
   *             a place a tube does not fit, such as a gap narrower than two
   *             radii. Whether a pinned end belongs in this bucket is
   *             OH-132's question and not this change's.
   *
   *             Bounded by `radius`.
   *   `pinned`  worst depth of a PINNED end inside a solid. `collide` skips
   *             the two ends (see its loop bounds), so nothing in this file
   *             ever moves them: a number here is a fault in whoever chose
   *             the anchor -- OH-128's carved pad reporting the group origin,
   *             inside the PCB slab -- and reporting it as the wire's
   *             penetration is what the "0.289 mm" record was doing.
   *
   * `radius` is the drawn tube's, and defaults to 0 so a caller that does not
   * draw gets centres only. This file still knows nothing about three.js.
   *
   * **It is a separate argument from `this.radius` on purpose.** That one is
   * the tube the solver keeps out; this one is the tube being measured, and
   * `penetration()` in `board3d.js` deliberately passes nothing so that
   * `inside` is a statement about centres. They are the same number whenever
   * the caller means them to be.
   *
   * @param {number} radius
   * @returns {{inside: number, proud: number, pinned: number}}
   */
  contact(radius = 0) {
    const worst = { inside: 0, proud: 0, pinned: 0 };
    for (let i = 0; i < this.count; i++) {
      const at = i * 3;
      const p = [this.position[at], this.position[at + 1], this.position[at + 2]];
      const pinned = i === 0 || i === this.count - 1;
      for (const solid of this.colliders) {
        const depth = solid.kind === "sphere"
          ? depthInSphere(p, solid)
          : depthInBox(p, solid);
        if (depth > 0) {
          const key = pinned ? "pinned" : "inside";
          worst[key] = Math.max(worst[key], depth);
          continue;
        }
        // Outside, or exactly on a face. How far does the tube reach in?
        if (radius <= 0) continue;
        const over = solid.kind === "sphere"
          ? radius - (distance(p, solid.at) - solid.r)
          : proudOfBox(p, solid, radius);
        if (over > 0) worst.proud = Math.max(worst.proud, Math.min(over, radius));
      }
    }
    return worst;
  }
}

function distance(a, b) {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

/** How far a point is inside a box, or 0 if it is not. Nearest face. */
function depthInBox(p, solid) {
  let depth = Infinity;
  for (let axis = 0; axis < 3; axis++) {
    // `<=` and `>=`, matching `outOfBox`: a node the collider snapped ONTO a
    // face is not inside it. The old probe used `<` and `>` here and so
    // counted a snapped node as inside at depth exactly zero, which is the
    // shape its 0.0000 actually had. **Measured 2026-09-04: a strict
    // comparison here changes nothing today**, because a node on the face
    // then reaches a depth of 0 on the next line and `contact` only counts
    // `depth > 0`. The equality is written anyway, so this function's own
    // answer is right and not merely masked by its caller's gate.
    if (p[axis] <= solid.min[axis] || p[axis] >= solid.max[axis]) return 0;
    depth = Math.min(depth, p[axis] - solid.min[axis], solid.max[axis] - p[axis]);
  }
  return depth;
}

/** How far a point is inside a sphere, or 0 if it is not. */
function depthInSphere(p, solid) {
  const gap = distance(p, solid.at);
  return gap >= solid.r ? 0 : solid.r - gap;
}

/**
 * How far a tube of `radius` centred at `p` reaches past a face of `solid`,
 * given `p` itself is not inside it.
 *
 * **The other two slabs are the whole point.** A node level with the top of a
 * chip but a board's width off to its left is not touching it, and without
 * that test every wire in the scene would report contact with everything at
 * its own height.
 *
 * **And the NEAR face is the only face**, which the first version of this
 * got wrong and the OH-132 review caught: it took the larger of the two
 * face terms, so a node above the box was always measured against the
 * bottom face, always exceeded the radius, and always clamped to it -- a
 * wire settled 33 units clear of the fixture reported its whole tube in
 * contact. The measure is the tube radius less the gap from the centre to
 * the slab on this axis: `radius` for a node on the face, less for one just
 * off it, nothing once the gap exceeds the radius.
 *
 * **Being a slab test is also what makes it blind at an EDGE**, which
 * OH-162's review found and which is not fixed here. A centre 0.01 past both
 * the +X and the +Y face is 0.0141 from the box's edge, well inside a 0.16
 * tube, and satisfies neither axis's other-two-slabs test, so this answers 0.
 * For a FREE node that is harmless once `collide` has run: being outside the
 * grown box means some axis clears by a whole radius, and the distance to the
 * box is at least that. It bites a PINNED end, which `collide` never moves,
 * and any rope measured without having been solved.
 */
function proudOfBox(p, solid, radius) {
  let over = 0;
  for (let axis = 0; axis < 3; axis++) {
    let across = true;
    for (let other = 0; other < 3; other++) {
      if (other === axis) continue;
      if (p[other] <= solid.min[other] || p[other] >= solid.max[other]) across = false;
    }
    if (!across) continue;
    const gap = Math.max(solid.min[axis] - p[axis], p[axis] - solid.max[axis], 0);
    over = Math.max(over, radius - gap);
  }
  return Math.min(over, radius);
}
