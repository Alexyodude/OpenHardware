---
id: OH-132
title: penetration() cannot see a contact the collider resolved, and the 0.289 record
  misreads it
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/wires.js
- webui/static/board3d.js
- tests/webui/test_wires.py
- tests/webui/test_board3d.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 wire survey; measured by running the
real wires.js under node.

`outOfBox` snaps a colliding node exactly onto the box face and `step` runs
collide LAST, so at the end of every step each free node is on-or-outside
every face and `penetration()` -- min distance INSIDE -- reports 0 for
exactly the nodes the collider handled. The only nodes it can report on are
the two pinned ends collide() skips. Measured: a settled 28-unit wire over a
12x3.5x6 box reports penetration 0.0000 while a node sits flush IN the box's
side face with half the tube's radius inside.

**So the long-standing "wire penetration 0.289 mm" residual is a pinned-end
artefact, not a contact tolerance** -- the handoff note explaining it as "the
rope's contact tolerance, under the wire's own radius" does not survive the
units either way (WIRE_RADIUS is 0.028 mm at Uno scale). OH-78's collider set
is fine; its evidence probe is blind. Interacts with OH-128: a head pinned at
the group origin is inside the PCB slab, which is exactly what this probe CAN
see -- fix OH-128 first, then re-measure.

DONE WHEN penetration() accounts for surface contact vs interpenetration
honestly (report proud-by-radius separately from inside-the-box), pinned ends
are measured or excluded BY STATEMENT, and the residual number in the docs is
re-derived with the fixed probe.

**Note 2026-09-04:** DONE 2026-09-04. Reproduced before anything was written, from the ticket's own fixture (a 28-unit wire settled over a 12 x 3.5 x 6 box, 600 frames): the shipped penetration() reported 0.0000 while node 5 sat at x = -6.000000 exactly, flush in the box's -X face with its whole 0.16-unit tube inside, and nodes 6, 8 and 9 sat at y = 3.500 exactly, the +Y face. Five nodes had a face within WIRE_RADIUS; zero were strictly inside. The blindness is structural: outOfBox assigns the face coordinate exactly (wires.js:407) and the probe's inside test used strict comparisons, so a snapped node counted as inside at depth exactly zero.



The 0.289 record, re-derived: the only thing that moves the old number is a PINNED end, which collide() never touches (its loop is 1..count-2). A head pinned at the box's centre reports 1.7500 units = 0.3104 mm at the Uno's 5.638 scale -- the same order and shape as the record. That the historical 0.289 came from that exact geometry is inferred; that the old explanation ("the rope's contact tolerance, under the wire's own radius") cannot be right is arithmetic: WIRE_RADIUS is 0.16 units = 0.0284 mm, so 0.289 read as millimetres is 10.2 radii and read as scene units is 1.8. The seven places the number survives are dated handoffs (08-27 to 08-30); both 08-31 handoffs had already dropped it, so no live document restates it and the dated ones are left as the records they are. OH-128, which the ticket said to fix first, was already done (its own 2026-08-30 close note).



The fix: the geometry moves into wires.js as Rope.contact(radius), because board3d.js imports three.js and can only ever be grepped -- which is exactly how a probe reporting 0.0000 for a half-buried wire survived four handoffs. Three numbers, because one stood for three facts and reported the wrong one: `inside` (a free node strictly inside a solid -- the fault OH-78 meant to watch; zero is the pass), `proud` (how far the TUBE reaches past a face while the centre is on or outside it -- contact, not interpenetration, bounded by the radius, and only when the centre lies within the other two slabs), and `pinned` (a pinned end inside a solid -- the anchor's fault, not the wire's, stated rather than folded in). penetration() is now one line through contact().inside and says BY STATEMENT that it excludes the two pinned ends; contact() is exported beside it with WIRE_RADIUS folded in. OH-78's original before-case (a wire laid straight through the box) still reads 1.75 through the narrowed probe.



Tests: test_a_wire_resting_on_a_box_reports_the_contact_the_collider_resolved runs the real wires.js under node and asserts inside == 0 AND proud > 0 on the same settled wire, which no single-number probe can satisfy; plus proud <= radius, pinned == 0 for a wire with both ends outside, pinned > 1.0 for the head-at-centre case, all zeros for a wire that never reaches the box, and proud == 0 with no radius given. test_board3d.py's grep now asserts the seam (penetration goes through rope.contact, contact uses WIRE_RADIUS) rather than arithmetic it cannot execute. Mutations run and restored byte-for-byte: contact never reporting proud, proudOfBox ignoring the other two slabs, pinned ends counted as free, penetration bypassing contact, and the whole fix reverted -- each turns a test red. One does NOT: depthInBox with strict comparisons passes everything, because a node on the face then reads depth 0 a line later and contact counts only depth > 0. The scout's report said that mutation would die; measured, it does not, and the comment and the test docstring now say so.

**Note 2026-09-04:** REVIEW FINDING, fixed 2026-09-04: the first proudOfBox took the larger of the near-face and far-face terms, so any node within the other two slabs was measured against the far face, exceeded the radius and clamped to it -- a wire 36.5 units clear of the box reported proud 0.16 (reproduced: above 0.16, 0.1-off-the-face 0.16, on-the-face 0.16). Now proud = radius - gap on the near face: measured above 0, 0.1 off 0.06, on the face 0.16. Regression test gained the clear-air and near cases; both the far-face formula and a gap-ignoring one fail it (mutations run, restored). The independent reviewer caught this; the author's own mutation set had not, because every fixture it used touched the box.

**Note 2026-09-04:** Two numbers in the note above corrected after review (2026-09-04): node 9 sits at y = 3.502051, not 3.500 exactly -- nodes 6 and 8 are the ones on the face; and the nodes with a face within the tube radius AND their centres within the other two slabs are four (5, 6, 8, 9), not five -- the fifth in the first count was node 13, 0.027 off the +X face but 4.7 above the box's top, which the slab rule excludes. Neither changes the finding.
