---
id: OH-162
title: A jumper lead has a thickness in the solver, collides with other leads, and
  is checked against one photograph
status: open
priority: P2
created: '2026-09-04'
touches:
- webui/static/wires.js
- webui/static/board3d.js
- tests/webui/test_wires.py
- tests/webui/test_board3d.py
---

A jumper lead here is a chain of points. It falls, sags, springs and stays out of the chips -- and it has no thickness in the solver, passes straight through other wires, and settles with half its tube inside whatever it rests on. OH-132 just made that last fact measurable: every settled wire reports `proud` = the full radius, 0.16 units, because collide() pushes the node's CENTRE to the face and the tube is drawn around it afterwards.

What is modelled, all in webui/static/wires.js, all with its constants labelled as the judgements they are (GRAVITY -36 "not 9.81", DAMPING 0.982 standing in for air and stiffness, STIFFNESS 0.4 as a two-node bend constraint, SLACK 1.35, NODES 22, ITERATIONS 14, SUBSTEP 1/120): a Verlet rope pinned at both ends, colliding with the parts' boxes and spheres, the board slab and a floor, contact run last in each pass.

What is not, measured 2026-09-04:

1. The tube's radius is not in the solver. collide() and outOfBox() move points; WIRE_RADIUS (0.16, board3d.js) is a drawing parameter. A lead lying on a chip is drawn half-buried; the OH-132 probe reads proud = 0.16 on every resting node.
2. Wires do not collide with wires. wires.js has no reference to any other Rope; two leads laid across each other occupy the same space. There is no test asserting either way.
3. Bend stiffness is a two-node constraint and nothing holds a bend once made -- a real lead keeps the shape it was pushed into (plastic set), which is what makes a breadboard tidy; this one relaxes to the catenary every time.
4. No oracle. Every number is a stated judgement, which is allowed here (BOARD_MASK's rule), but nothing has been compared to a real lead: no photograph, no measured sag.

Comparison, read 2026-09-04: Xplora3D draws wires on a breadboard with "Auto Snap Pins" and exports GLB; its wire physics, if any, is inside an engine bundle that loads after login and was not inspected. Simulator86 has no 3D and no physics -- a 2D diagram with pins. Neither is an oracle either; a photograph of a real lead on a real XIAO is, and no such photograph exists in this tree.

STEPS, in the order that keeps each falsifiable:

1. Radius in the solver: collide() pushes a node to face + WIRE_RADIUS (and sphere r + radius), with the radius passed in from the caller so wires.js still knows nothing about three.js. The OH-132 contact() probe is the check: after this, a resting wire's `proud` reads 0 and `inside` stays 0. Expect the drape to change visibly on every board; screenshot before and after.
2. Wire-wire contact: capsule-capsule between node segments of different ropes, run in the same last-pass position as the solids, with the same radius. Test: two leads crossed at right angles settle with a centre gap of at least 2 x radius at the crossing.
3. Plastic set, if it earns its place: record the rest angle at each node when a wire stops moving and relax toward it, so a bent lead stays bent. Judgement, labelled; the test is that a lead dragged into an arc does not return to a catenary.
4. The oracle: one photograph of one lead of known length on one board, and the sag it shows against the sag this model gives for the same span. That single number is what would retire GRAVITY, DAMPING and SLACK as judgements, and it costs a phone.

Each step is a separate commit with its own mutation-tested assertion (OH-132's lesson: every fixture the author used TOUCHED the box, and the reviewer's clear-air fixture is what found the bug -- include one fixture that should report nothing).

**Note 2026-09-05:** Step 1 of four DONE 2026-09-05. Steps 2-4 (wire-wire contact, plastic set, the photograph oracle) are untouched and the ticket stays open.

The radius is plain data on the Rope, `this.radius = 0` beside `this.floor`, so wires.js still knows nothing about three.js and every test written before this still describes what the solver does for it. Every solid grows by it -- the bench plane, `outOfSphere` reaching `solid.r + r`, and `outOfBox` growing the box on each axis in BOTH its early-out and its face table. board3d.js's applyColliders is the crossing point, beside the colliders and the floor it already hands over, so there is one thickness and not two.

Measured on the ticket's own fixture, a 28-unit wire settled over a 12 x 3.5 x 6 box, 600 frames at 1/60:

  never told the radius:  proud 0.16 (the whole tube), inside 0, resting centres exactly ON the face (0.000000 above it)
  told 0.16:              proud 0,    inside 0, resting centres 0.16 above the face

and the two branches that fixture does not reach: a sphere of r 3 holds the nearest free centre at 3.000 before and 3.160 after; a bench at y 2 holds the lowest free centre at 2.000 before and 2.160 after. Worst stretch went 1.38% -> 1.51%, a thicker wire being a slightly longer path over the same box. proud is exactly 0 and not a residual: 3.5 + 0.16 less 3.5 is 0.16000000000000014, a hair MORE than the radius, so the tube reaches a negative distance in and contact()'s own `> 0` gate drops it.

**collide() runs twice, and the review is why.** Growth is per solid and resolution is sequential, so a node ejected onto solid B's grown face lands inside solid A's real box -- and a chip sitting flush on a board is the everyday case, its grown bottom face a radius BELOW the slab's top. Measured on a wire pinned to two pads over a slab with one chip: contact().inside went 0 before OH-162 and 0.16 with the first version of this change, which is the number this file itself calls the fault. So a radius is a preference and being outside a solid is a requirement: the grown solids are resolved, then the UNGROWN ones are resolved again, which is the guarantee the file had before OH-162 and restores that same 0. It restores the old invariant rather than improving on it -- two genuinely overlapping ungrown solids would still trap a node, exactly as before, and the reviewer measured 13 such pairs on the Uno alone (a through-hole body passing through the PCB) with no wire able to reach any of them.

**And the guard on that second pass had a fixed point, which was the review's second catch.** Skipping when the node had not MOVED is not the same as skipping when nothing PUSHED: two solids 0.05 apart push a node out and straight back inside one pass, so its coordinates come out identical while both pushes really happened, and the node stays 0.11 inside the first box for ever because it is a fixed point of the cycle. outOfSolids now returns whether a push executed and collide gates on that; outOfBox and outOfSphere return booleans. Verified on the reviewer's geometry: starting at the fixed point -0.135 now ends at -0.025, the same as starting anywhere else. Counted through the real collide: the second pass ran 133,885 times against the first pass's 336,000, 39.9%.

The cost of a grown box, stated because it is a real approximation: square corners where a swept tube has round ones, so a node passing a chip's corner clears it by up to radius * (sqrt(3) - 1) = 0.117 units more than it needs. Rounding it properly is a different function and can arrive when a picture shows this one.

**A number the review corrected, and it changes an argument elsewhere.** view.mmScale is scene units PER MILLIMETRE (board3d.js:567; PX_PER_MM 8.0 times SCALE 0.1), so the Uno's is 0.5638 and not 5.638. My comment had divided by the px/mm figure and said 0.021 mm; it is 0.208. The same slip is older than this change: test_wires.py's OH-132 docstring said 0.3104 mm for 1.75 units when it is 3.104, and that is fixed here because the file is this ticket's. The consequence is not cosmetic -- 0.16 units of tube is 0.284 mm, so the historical "0.289 mm" residual is 1.018 wire radii and not the 10.2 that OH-132's ticket computes, which means the arithmetic that ticket offered AGAINST the older "contact tolerance under the wire's own radius" reading does not hold. The pinned-end explanation still stands on its own evidence. **OH-132's ticket file and the 2026-09-04 handoff carry the same wrong figure and are NOT this ticket's paths to edit.**

**And a claim of mine that was false.** I wrote that a wire the solver was told a radius for reads proud 0. It reads 0 for its FREE nodes only: contact() measures the pinned ends too, and a pad's centre sits 0.04 above the slab, so a head anchored there has 0.12 of a 0.16 tube in the board by construction. Measured with heads on pads and the solver told 0.16 -- over the slab proud 0.12 from the head and no free node; over slab plus chip 0.16 from a free node in the seam, where a 0.32-wide tube does not fit; no colliders 0. Excluding a pinned end from proud the way inside already excludes it would be the fix and is OH-132's question, not this step's.

Two blind spots recorded and deliberately not fixed. proudOfBox is a slab test and so answers 0 at a box EDGE -- a centre 0.01 past both the +X and +Y faces is 0.0141 from the edge, inside a 0.16 tube, and satisfies neither axis's other-two-slabs test; harmless for a free node after collide, since being outside the grown box means some axis clears by a whole radius, and it bites a pinned end or an unsolved rope. And a box with no thickness on an axis becomes a 2*radius obstacle where the `<=`/`>=` early-out made it nothing; latent, because the eleven shipped board models carry 775 solids with no degenerate axis and the thinnest real one is 0.23 mm, an 0201's height on the C3.

Twenty-three mutations run and each killed the test named for it, both files restored by hash. Seventeen against wires.js: the ungrown face, the ungrown early-out, the radius defaulting to 0.16, the bench unoffset, outOfSphere reaching solid.r, the first pass at twice the radius, the whole change reverted, the second pass never running, the second pass at the same radius, the movement guard restored, outOfSolids short-circuiting once one solid has pushed, each axis's growth dropped in turn, the min faces growing without the max, and the sphere's at-the-centre branch pushing by solid.r and by r. Six against board3d.js: the hand-off deleted, replaced by 0.2, commented out, multiplied by zero, put behind a branch, and aimed at wire.radius. **Two survived first and both were test gaps.** Defaulting the field to 0.16 survived because the control fixture set radius = 0 explicitly and overwrote the value it was testing; the control now sets nothing, which is the state every pre-OH-162 rope is in. And the reviewer found that dropping the Z growth survived everything, because every fixture in the file was planar at z = 0.

NOT done, and it is the ticket's own words: "screenshot before and after". No browser picture was taken. The change is evidenced numerically on eleven fixtures instead, and this repository's own position is that Python cannot render a WebGL scene -- which is why the arithmetic was moved into wires.js at OH-132 to be executed rather than grepped.
