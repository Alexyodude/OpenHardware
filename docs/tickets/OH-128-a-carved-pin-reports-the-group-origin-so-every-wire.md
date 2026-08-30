---
id: OH-128
title: A carved pin reports the group origin, so every wire anchors at the board's
  centre
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims webui/static/board3d.js when it starts.

**From the 2026-08-30 wire survey; runtime-verified against the vendored
three.js.** `carvePins` builds the replacement pad mesh with the pad's offset
BAKED INTO THE GEOMETRY and never sets `pin.position`, so `getWorldPosition`
on a carved pad returns the model group's origin -- the pad-map centroid at
the board's UNDERSIDE. Every consumer of a pad's position gets that point:
`anchorOf` (every frame), `beginWire`'s rope start, the drag plane, and
`describe().pads` -- which is why OH-115's own probes saw carved pads report
(0,0).

On the Uno all 32 pads are carved now, so EVERY wire's board end is pinned at
the board centre, inside the PCB slab collider -- the exact "constraint and
collider pull against each other forever" case `refreshColliders`' own
comment warns about, and very likely most of the user's "many issues with
wire".

**OH-95's record says the opposite and needs correcting in this ticket**: its
close note claims the anchor "goes on working without knowing the geometry
changed underneath". The raycast does; the anchor does not.

DONE WHEN a carved pad's world position is the pad's, not the group's; a wire
dragged from any Uno pad anchors at that pad in the browser; and the fix is
held by a test that would have caught this -- position-based, not a source
grep.
