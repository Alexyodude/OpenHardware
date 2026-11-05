// OpenHardware — how far a lead's SEGMENTS reach into a solid.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this measures that `contact()` cannot
//
// `Rope.contact()` in `wires.js` reports three numbers, and all three are
// about NODES. A lead is a chain of nodes with straight segments between
// them, and `collide` pushes nodes out of solids -- so a solid narrower than
// the gap between two nodes falls BETWEEN them and the lead threads through
// it, with `inside`, `proud` and `worstStretch` all reading clean (OH-165).
// On an Arduino Uno pin header at the Uno's own scale, a 28-unit lead's
// worst segment passes through the header's exact centre while every one of
// those numbers says nothing is wrong.
//
// So this asks the question about the segments instead: over every point of
// every segment, how deep is the deepest one inside any solid. Its depth is
// measured the way `contact()`'s `inside` is -- distance to the NEAREST face
// of a box, or in from a sphere's surface -- so for a segment that is a
// single point the two answers are the same number.
//
// ## Why it is its own file
//
// Only because `wires.js` is OH-162's to edit while that ticket is open, and
// this ticket's rule is that no two open tickets claim one file. It imports
// nothing, as `wires.js` imports nothing, and reads a rope by duck type --
// `position`, `count` and `colliders` -- so it can move beside `contact()`
// unchanged once the solver is free to be edited.
//
// It is a probe and not a collider: nothing here moves a node.

/**
 * The worst depth any point of any segment of `rope` reaches inside any of
 * its colliders, or 0 if none does.
 *
 * **Every segment, the two at the pinned ends included.** A segment whose
 * pinned end is itself inside a solid reports at least that end's depth --
 * the same number `contact().pinned` gives -- because a probe that skipped
 * those two would be blind to a lead whose end is fine and whose first
 * segment is not.
 *
 * @param {{position: Float64Array, count: number,
 *          colliders: Array<object>}} rope
 * @returns {number}
 */
export function segmentThroughSolid(rope) {
  let worst = 0;
  const P = rope.position;
  for (let i = 0; i < rope.count - 1; i++) {
    const a = [P[i * 3], P[i * 3 + 1], P[i * 3 + 2]];
    const b = [P[i * 3 + 3], P[i * 3 + 4], P[i * 3 + 5]];
    for (const solid of rope.colliders) {
      const depth = solid.kind === "sphere"
        ? segmentInSphere(a, b, solid)
        : segmentInBox(a, b, solid);
      if (depth > worst) worst = depth;
    }
  }
  return worst;
}

/**
 * The deepest any point of the segment `a`-`b` lies inside a box, measured
 * to the box's nearest face, or 0 if no point of it is strictly inside.
 *
 * **Exact, not sampled.** A point's depth is the least of six signed
 * distances, one per face, and each is a linear function of the parameter
 * `t` along the segment. The least of linear functions is concave, so its
 * maximum over `t in [0, 1]` is at an end or where two of the six cross --
 * fifteen crossings and two ends, every one of them evaluated. Sampling
 * would be cheaper to write and would miss exactly the case this file is
 * for: a solid thinner than the spacing of the samples.
 *
 * @param {number[]} a
 * @param {number[]} b
 * @param {{min: number[], max: number[]}} solid
 * @returns {number}
 */
export function segmentInBox(a, b, solid) {
  // Face k's signed distance at t is `offset[k] + slope[k] * t`, positive
  // on the box's side of that face.
  const offset = [];
  const slope = [];
  for (let axis = 0; axis < 3; axis++) {
    const d = b[axis] - a[axis];
    offset.push(a[axis] - solid.min[axis], solid.max[axis] - a[axis]);
    slope.push(d, -d);
  }
  const depthAt = (t) => {
    let least = Infinity;
    for (let k = 0; k < 6; k++) least = Math.min(least, offset[k] + slope[k] * t);
    return least;
  };
  let best = Math.max(depthAt(0), depthAt(1));
  for (let j = 0; j < 6; j++) {
    for (let k = j + 1; k < 6; k++) {
      const turn = slope[j] - slope[k];
      if (turn === 0) continue;
      const t = (offset[k] - offset[j]) / turn;
      if (t > 0 && t < 1) best = Math.max(best, depthAt(t));
    }
  }
  // On a face is not inside, matching `depthInBox` in `wires.js`.
  return best > 0 ? best : 0;
}

/**
 * The deepest any point of the segment `a`-`b` lies inside a sphere, or 0
 * if no point of it is strictly inside: the radius less the distance from
 * the centre to the segment's nearest point.
 *
 * @param {number[]} a
 * @param {number[]} b
 * @param {{at: number[], r: number}} solid
 * @returns {number}
 */
export function segmentInSphere(a, b, solid) {
  const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const w = [solid.at[0] - a[0], solid.at[1] - a[1], solid.at[2] - a[2]];
  const dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
  // A zero-length segment is a point, and its nearest point is itself.
  let t = dd === 0 ? 0 : (w[0] * d[0] + w[1] * d[1] + w[2] * d[2]) / dd;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  const gap = Math.hypot(w[0] - d[0] * t, w[1] - d[1] * t, w[2] - d[2] * t);
  return gap >= solid.r ? 0 : solid.r - gap;
}
