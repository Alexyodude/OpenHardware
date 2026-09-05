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
    //: The other wires on the bench, as `Rope`s. Plain data the caller
    //: supplies each frame, exactly like `colliders` -- and the array it
    //: passes may include this rope, which `offNeighbours` skips, so a caller
    //: can hand every wire the same list.
    //:
    //: **Empty is the default and it is the old behaviour**: two leads laid
    //: across each other occupied the same space, which is what OH-162 step 2
    //: is about.
    this.neighbours = [];

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
    // **Wire against wire once a step and not once a pass** (OH-162 step 2).
    // Every segment against every segment is the first quadratic thing in
    // this solver, so where it runs is a decision and not a detail.
    //
    // Measured 2026-09-05, the SAME code in both positions -- eight leads
    // over a slab and eight component boxes, median of three runs of 1,500
    // steps after a 600-step warm-up. A 60 Hz frame is TWO substeps, not
    // eight: `advance(1/60)` returns 2, and `MAX_SUBSTEPS` is only reached
    // below 15 fps.
    //
    //                    us/rope-step   ms/frame   two crossed   twelve
    //   before step 2        23.1         0.37       0.2748      0.0053
    //   once a step          35.6         0.57       0.3704      0.3159
    //   once a pass         184.9         2.96       0.4917      0.3193
    //
    // The last two columns are the nearest centre-to-centre gap after three
    // thousand frames, against the 0.32 two tubes need; twelve leads crossed
    // at one point cannot all have it and 0.0053 is what "no wire-wire at
    // all" looks like. **Once a pass is 5.2 times dearer and buys nothing**,
    // and it is worse where it matters most: those twelve leads still carry
    // 0.233 of energy after three thousand frames where once a step has
    // 6.5e-15. Fourteen passes over neighbours that cannot answer within the
    // step keeps a crowded pile stirring.
    //
    // **An earlier draft of this comment justified the same decision with a
    // number that did not mean what it said**: 1,665 microseconds, measured
    // before the bounds rejections existed, so it compared two algorithms and
    // called it two placements. The review caught it. The decision survived
    // the honest measurement, which is luck rather than method.
    //
    // **And the solids run once more afterwards if anything moved**, because
    // a lead pushed off a lead can be pushed into the board -- which is the
    // same defect the review found in step 1, arriving from the other side.
    // A board is a harder thing to be inside than a wire, so the solids win
    // the last word and wire-wire is a preference within the step.
    //
    // **What shows this line is needed is a lead pinned LOW across another**,
    // not a crowd. Leads crossing each other in mid-air push each other
    // sideways and up; a lead whose own ends are pinned at the height the
    // lower one rests at has nowhere to send it but down. Measured
    // 2026-09-05, worst `contact().inside` over 600 frames, four such leads
    // over one resting on a slab: 0.085 without this line and 0 with it, and
    // 0.106 for ten of them. Six leads merely crossing give 0 either way,
    // which is what an earlier fixture here did and why it proved nothing.
    //
    // Running the wire pass twice here would not be wrong, and no test can
    // tell it apart: the second run refines the same answer rather than
    // giving a different one. Once is what the cost above paid for.
    //
    // `advance` calls this up to `MAX_SUBSTEPS` times a frame, so what a
    // reader should carry away is the middle column and not the first: at
    // 60 Hz the whole bench of eight wires costs 0.57 of a 16.7 millisecond
    // frame.
    if (this.offNeighbours()) this.collide();
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
   *
   * ## Why the rest length is straight and is not remembered
   *
   * OH-162 step 3 asked for plastic set -- "record the rest angle at each node
   * when a wire stops moving and relax toward it, so a bent lead stays bent",
   * with `if it earns its place` attached. It does not, and the reason is a
   * number rather than a preference. Measured 2026-09-05 on a 10-unit lead
   * with this file's own slack, sag of the settled shape:
   *
   *   with this function            4.0371
   *   with it doing nothing at all  4.0493
   *
   * **The bending constraint is worth 0.30% of the drape at `NODES` 22.** A
   * smooth catenary over twenty-two nodes is locally almost straight: every
   * pair of that same free-hanging lead settles within 0.104% of the
   * `segment * 2` below, and a lead draped over a part reaches 0.28% where it
   * leaves the edge. So the constraint is very nearly satisfied everywhere.
   *
   * **That 0.30% explains the parity below; it does not prove it**, and a
   * review was right to stop it carrying the argument. It is the gap between
   * a straight rest and no constraint at all, which is the straightening
   * direction only -- a remembered rest SHORTER than the current bend pushes
   * the other way, which the shipped constraint never does, and nothing
   * measures that bound. What is measured is the outcome.
   *
   * **It is the node count and not the mechanism.** The same memory, on the
   * same manoeuvre, keeps 0.452 units of shape on an 8-node lead, 0.230 on a
   * 12-node one, 0.0106 at the 22 this ships and 0.0009 at 40 -- and the part
   * lifted every one of them by between half a unit and three quarters, so
   * they were all bent by the same amount. A pair spanning two of seven
   * segments has authority over the shape; a pair spanning two of twenty-one
   * has none.
   *
   * And a memory that tracks the bend perfectly is worth nothing at all: the
   * constraint is then always satisfied, exerts nothing, and the wire lands on
   * the bendless one -- 4.0476 against 4.0493, 0.04% apart. **That is the step
   * 2 blocker's shape arriving again**, a correction that resolves itself
   * fully in one pass, and here it does not diverge, it evaporates.
   *
   * Swept from a rate of 1e-5 to 1 on the only manoeuvre a person can perform
   * -- a part arriving under a settled lead and later being taken away, since
   * a finished lead's two ends never move again -- **no rate keeps more shape
   * than it costs.** Kept over cost, at 3e-5, 1e-4, 3e-4, 1e-3, 2e-3, 5e-3
   * and 1: 0.90, 1.01, 1.18, 1.12, 0.60, 0.17, 0. The best of them is 1.18,
   * on 0.0106 units kept against 0.0095 units of drape given up by a lead
   * nobody has touched. That is the argument, and it does not depend on
   * picking a rate. `test_a_settled_lead_takes_the_shape_its_two_ends_give_it`
   * is the assertion that says so.
   *
   * **The ticket's own trigger is unsafe on top of that.** Its words are
   * "record the rest angle when a wire stops moving", and a wire threaded
   * through a solid narrower than it dips into is perfectly still: `energy()`
   * reads 3.7e-28 while a segment sits at 5.2 times its rest length. A
   * stillness gate fires on exactly the state that must not be remembered.
   *
   * What would change the answer is a wire whose bending mattered: `NODES`,
   * `STIFFNESS`, or a pair spanning further than two segments -- and each
   * changes the drape of every lead on every board. **A directional memory is
   * the one formulation nobody has measured**: the distance from a node to the
   * one two along is degenerate about the bend axis, so it can hold a lead
   * bunched but never bent in a chosen plane, and gravity picks the plane.
   *
   * It also needs a gesture. Nothing in this product bends a lead that is
   * connected at both ends, so step 3's own acceptance test describes an
   * interaction the interface does not have. OH-162 step 4's photograph is
   * about sag and retires `GRAVITY`, `DAMPING` and `SLACK`; it says nothing
   * about this. Reopening step 3 wants a different photograph -- a lead bent
   * by hand that stayed bent -- and a way to bend one here.
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
   * Push this wire's segments off every other wire's (OH-162 step 2).
   *
   * **A lead is a capsule and not a chain of points**, so the test is between
   * SEGMENTS and not between nodes: two leads crossing at right angles have
   * no node anywhere near each other and still occupy the same space. The
   * nearest pair of NODES there can be half a segment apart -- 0.9 units on
   * a 28-unit lead, whose segments are 1.8 -- while the segments themselves
   * touch. A node-to-node test would need a radius nearly six times the one
   * a lead is drawn at before it noticed, and would then report contact
   * between leads that are nowhere near each other.
   *
   * **This wire moves and the other does not**, which looks one-sided and is
   * not. Every wire on the bench is advanced every frame, in `board3d.js`'s
   * own loop, so each one pushes itself off the others in its own turn and
   * the pair separates. Writing into another rope's array instead would let
   * one rope's step change a rope the caller has ALREADY stepped this frame,
   * undoing work that is finished rather than adding to work that is not.
   *
   * It is not that the answer would start depending on the order the caller
   * steps in -- an earlier draft of this comment claimed that and it was
   * false, because each rope already reads its neighbours where they are
   * now, so `animate`'s iteration order changes the answer today. What is
   * true is the narrower thing above, and it is enough.
   *
   * **The separation is both radii**, so a thick lead crossing a thin one
   * parts by the sum, and a caller that told only one of them a radius gets
   * that one held off the other's centreline. Both zero is the old behaviour
   * and costs nothing: the pair is dropped before any geometry runs.
   *
   * The correction is shared between the segment's two ends by how near the
   * contact is to each, and a pinned end takes none of it -- the same rule
   * `relax` follows, for the same reason.
   *
   * Returns whether anything was pushed, which is what `step` gates its extra
   * solids pass on.
   */
  offNeighbours() {
    let pushed = false;
    for (const other of this.neighbours) {
      // The caller may hand every wire the same array, so this is not an
      // error to guard against; it is the expected way to call it.
      if (other === this) continue;
      const want = this.radius + other.radius;
      if (want <= 0) continue;
      // **Two rejections, and between them is why this is affordable.** The
      // first drops a whole pair of leads that are nowhere near each other,
      // for the cost of reading both ropes once per PAIR -- `mayReach` walks
      // this rope's own nodes again for every neighbour, which is a hoist
      // nobody has needed at the sizes measured. The second drops a pair of
      // SEGMENTS, which is what matters when the leads do cross: two wires
      // over one board overlap as boxes while only a handful of their 441
      // segment pairs are within a tube of one another.
      if (!this.mayReach(other, want)) continue;
      const mine = this.position;
      const theirs = other.position;
      for (let i = 0; i < this.count - 1; i++) {
        const a = i * 3;
        const b = a + 3;
        for (let j = 0; j < other.count - 1; j++) {
          const c = j * 3;
          const d = c + 3;
          let apart = false;
          for (let axis = 0; axis < 3; axis++) {
            const lo = Math.min(mine[a + axis], mine[b + axis]);
            const hi = Math.max(mine[a + axis], mine[b + axis]);
            const theirLo = Math.min(theirs[c + axis], theirs[d + axis]);
            const theirHi = Math.max(theirs[c + axis], theirs[d + axis]);
            if (theirLo - hi > want || lo - theirHi > want) {
              apart = true;
              break;
            }
          }
          if (apart) continue;
          if (this.partSegments(i, other, j, want)) pushed = true;
        }
      }
    }
    return pushed;
  }

  /**
   * Whether the two wires' bounding boxes come within `want`.
   *
   * **Read once per pair and then gone stale on purpose.** The pushes that
   * follow move this wire, so by the time a later neighbour is tested its
   * bounds are the ones from before those pushes -- and a lead shoved off one
   * neighbour can land within reach of a neighbour already passed over. What
   * that costs is one step of delay, 1/120 s, because the next step tests
   * again from where everything now is. Re-reading the bounds after every
   * push would make this quadratic in the thing it exists to keep linear.
   */
  mayReach(other, want) {
    for (let axis = 0; axis < 3; axis++) {
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = 0; i < this.count; i++) {
        const here = this.position[i * 3 + axis];
        if (here < lo) lo = here;
        if (here > hi) hi = here;
      }
      let theirLo = Infinity;
      let theirHi = -Infinity;
      for (let i = 0; i < other.count; i++) {
        const here = other.position[i * 3 + axis];
        if (here < theirLo) theirLo = here;
        if (here > theirHi) theirHi = here;
      }
      if (hi + want < theirLo || theirHi + want < lo) return false;
    }
    return true;
  }

  /**
   * Part this wire's segment `i` from `other`'s segment `j`, to `want`.
   *
   * Returns whether it pushed, which is what the tests count.
   */
  partSegments(i, other, j, want) {
    const a = i * 3;
    const b = a + 3;
    const c = j * 3;
    const d = c + 3;
    closestOnSegments(this.position, a, b, other.position, c, d);
    const s = CLOSEST[0];
    const t = CLOSEST[1];
    // The two closest points, and the axis between them.
    const mine = this.position;
    const theirs = other.position;
    let nx = along(mine, a, b, 0, s) - along(theirs, c, d, 0, t);
    let ny = along(mine, a, b, 1, s) - along(theirs, c, d, 1, t);
    let nz = along(mine, a, b, 2, s) - along(theirs, c, d, 2, t);
    let gap = Math.hypot(nx, ny, nz);
    if (gap >= want) return false;
    let push = want - gap;
    if (gap === 0) {
      // **Exactly crossing, so the positions hold no direction to part in.**
      // The way a crossing opens is perpendicular to both leads, which is
      // their cross product -- and two PARALLEL leads touching along their
      // length have no such axis at all. Those are left alone rather than
      // pushed somewhere invented; the next step's gravity parts them, and a
      // wire lying exactly along another to the last bit is not a picture
      // anybody is looking at.
      const ux = this.position[b] - this.position[a];
      const uy = this.position[b + 1] - this.position[a + 1];
      const uz = this.position[b + 2] - this.position[a + 2];
      const vx = other.position[d] - other.position[c];
      const vy = other.position[d + 1] - other.position[c + 1];
      const vz = other.position[d + 2] - other.position[c + 2];
      nx = uy * vz - uz * vy;
      ny = uz * vx - ux * vz;
      nz = ux * vy - uy * vx;
      gap = Math.hypot(nx, ny, nz);
      if (gap === 0) return false;
      push = want;
    }
    nx /= gap;
    ny /= gap;
    nz /= gap;
    // Shared by nearness, and a pinned end takes none of it.
    const wa = i === 0 ? 0 : 1 - s;
    const wb = i + 1 === this.count - 1 ? 0 : s;
    // **This is not the divisor guard it replaced, and it earns its line for
    // a different reason.** Two zero weights would add zero to both ends
    // anyway, so deleting it changes no position -- but it would then report
    // a push that did not happen, and `step` runs a whole extra solids pass
    // on that word. A contact exactly on a pinned node is the case: the wire
    // cannot answer it, and the other wire will in its own turn.
    if (wa === 0 && wb === 0) return false;
    // **The ends move by `push`, so the CONTACT moves by less, and that is
    // deliberate.** The contact point travels `wa(1-s) + wb·s` of whatever
    // the ends do, between a half and one for a segment with two free ends.
    // Dividing by that would resolve the whole overlap in a single pass, and
    // it is how this was first written -- but on a head segment `wa` is 0 and
    // the divisor is `s²`, so a contact near the pinned end sends the free
    // end `push / s` away. Measured before the review found it: two leads
    // pinned at one terminal reached a coordinate of 6.4e17 in six hundred
    // frames. Swept at 0.01, every separation from 0 to 0.31 blew up and the
    // worst of it is not the degenerate end but the band from 0.12 to 0.18,
    // which reaches 3.7e13.
    //
    // Under-correcting cannot do that: nothing is divided, so nothing is
    // unbounded, and the overlap is taken out over the following steps
    // instead of all at once.
    //
    // **What it costs is that the separation becomes approximate under a
    // sustained press**, because the resting state is where one pass's push
    // balances one frame of gravity rather than where the tubes exactly
    // touch. Measured 2026-09-05 at 1,200 frames, nearest centre to centre
    // against the 0.32 two tubes want: one lead pressing on another 0.3293,
    // four 0.3203, ten 0.3192. The worst of those is a quarter of one per
    // cent short and it is bounded, not drifting -- but "at least two radii"
    // is a statement about a lead left alone, not about one at the bottom of
    // a pile. It is better on SETTLING even where nothing was in danger,
    // and worse on exactness, which is the paragraph above:
    // a crossed pair settles to 1.9e-13 against 3.3e-8, and
    // twelve leads crossing at one place are down to 5.8e-6 by the third
    // thousand frames where the division was still at 0.316. Both do settle
    // in the end; the division takes about five orders of magnitude longer
    // to get there, which a first draft of this comment called "for ever".
    this.position[a] += nx * wa * push;
    this.position[a + 1] += ny * wa * push;
    this.position[a + 2] += nz * wa * push;
    this.position[b] += nx * wb * push;
    this.position[b + 1] += ny * wb * push;
    this.position[b + 2] += nz * wb * push;
    return true;
  }

  /**
   * The closest a free node of this wire comes to any other wire's segment.
   *
   * **Here for a test**, and it is to step 2 what `contact` is to step 1: the
   * number that says two leads are not in the same place. Centre to centre,
   * so a pass is `>= 2 * radius` and the caller does the comparing.
   *
   * Pinned ends are excluded, as everywhere else in this file -- a pad and a
   * terminal are placed by whoever placed them, and two wires plugged into
   * neighbouring pads are legitimately closer than their two tubes.
   */
  nearestNeighbour() {
    let nearest = Infinity;
    for (const other of this.neighbours) {
      if (other === this) continue;
      const theirs = other.position;
      for (let i = 1; i < this.count - 1; i++) {
        const at = i * 3;
        for (let j = 0; j < other.count - 1; j++) {
          const c = j * 3;
          const d = c + 3;
          // `at` twice: this end of it is a NODE, which the solver takes as
          // a segment of no length and answers `t` alone for.
          closestOnSegments(this.position, at, at, theirs, c, d);
          const t = CLOSEST[1];
          nearest = Math.min(nearest, Math.hypot(
            this.position[at] - along(theirs, c, d, 0, t),
            this.position[at + 1] - along(theirs, c, d, 1, t),
            this.position[at + 2] - along(theirs, c, d, 2, t)));
        }
      }
    }
    return nearest;
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

//: Where `closestOnSegments` leaves its two answers.
//:
//: **A module-level pair rather than a returned array**, for the reason the
//: constructor gives about `position`: this runs up to 21 x 21 times per wire
//: pair per constraint pass, fourteen passes a step and eight steps a frame,
//: and an array returned from it would be that many allocations a frame for
//: two numbers. Nothing here is re-entrant or asynchronous, so the one pair
//: is safe; read it before calling again.
const CLOSEST = [0, 0];

function clamped(value) {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * One axis of the point `f` of the way from `P[from]` to `P[to]`.
 *
 * Seven call sites between `partSegments` and `nearestNeighbour`, each of
 * which is otherwise the same forty characters with a different index.
 */
function along(P, from, to, axis, f) {
  return P[from + axis] + (P[to + axis] - P[from + axis]) * f;
}

/**
 * The closest pair of points on two segments, as parameters along each.
 *
 * `P[a..a+2]` to `P[b..b+2]` is the first, `Q[c..c+2]` to `Q[d..d+2]` the
 * second; the answers land in `CLOSEST` as `[s, t]`. Taking flat arrays and
 * offsets rather than points is the same allocation argument.
 *
 * The method is the standard one: minimise the squared distance over the
 * square `s, t in [0, 1]`, and where the unconstrained minimum falls outside
 * it, clamp one parameter and re-solve for the other. **Both degenerate cases
 * have to be handled and neither is hypothetical here** -- a rope whose two
 * ends coincide has zero-length segments at the moment it is made, and two
 * leads laid out straight and parallel are exactly the case with no unique
 * answer, where any point along the overlap is as close as any other.
 * Parallel takes `s = 0`, which is a point on the segment and is enough,
 * because a segment resolved at one end and still overlapping is offered
 * again on the next of fourteen passes.
 */
function closestOnSegments(P, a, b, Q, c, d) {
  const ux = P[b] - P[a];
  const uy = P[b + 1] - P[a + 1];
  const uz = P[b + 2] - P[a + 2];
  const vx = Q[d] - Q[c];
  const vy = Q[d + 1] - Q[c + 1];
  const vz = Q[d + 2] - Q[c + 2];
  const wx = P[a] - Q[c];
  const wy = P[a + 1] - Q[c + 1];
  const wz = P[a + 2] - Q[c + 2];
  const uu = ux * ux + uy * uy + uz * uz;
  const vv = vx * vx + vy * vy + vz * vz;
  const uw = ux * wx + uy * wy + uz * wz;
  const vw = vx * wx + vy * wy + vz * wz;
  if (uu === 0 && vv === 0) {
    CLOSEST[0] = 0;
    CLOSEST[1] = 0;
    return;
  }
  if (uu === 0) {
    CLOSEST[0] = 0;
    CLOSEST[1] = clamped(vw / vv);
    return;
  }
  if (vv === 0) {
    CLOSEST[0] = clamped(-uw / uu);
    CLOSEST[1] = 0;
    return;
  }
  const uv = ux * vx + uy * vy + uz * vz;
  const denominator = uu * vv - uv * uv;
  // Zero when the two are parallel, and then there is no unique answer.
  let s = denominator === 0 ? 0 : clamped((uv * vw - uw * vv) / denominator);
  let t = (uv * s + vw) / vv;
  // The unconstrained answer can leave the square on `t`. Pin it to the end
  // it left by and find the best `s` for that, which is a one-dimensional
  // problem and has a closed form.
  if (t < 0) {
    t = 0;
    s = clamped(-uw / uu);
  } else if (t > 1) {
    t = 1;
    s = clamped((uv - uw) / uu);
  }
  CLOSEST[0] = s;
  CLOSEST[1] = t;
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
