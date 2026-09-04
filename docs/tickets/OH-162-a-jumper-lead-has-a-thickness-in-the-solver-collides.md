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
