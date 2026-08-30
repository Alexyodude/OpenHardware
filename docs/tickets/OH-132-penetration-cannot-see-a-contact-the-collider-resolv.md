---
id: OH-132
title: penetration() cannot see a contact the collider resolved, and the 0.289 record
  misreads it
status: open
priority: P2
created: '2026-08-30'
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
