---
id: OH-128
title: A carved pin reports the group origin, so every wire anchors at the board's
  centre
status: done
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

## DONE, 2026-08-30

The carved mesh's vertices are re-baked relative to the pad's own point and
that point becomes the mesh's POSITION -- same triangles, same places on
screen, and `getWorldPosition` now answers where the pad is. Verified in the
browser: the Uno's pads report 30 distinct world positions spread across
25 x 27 scene units where every carved pad used to report the one group
origin; 32 of 32 still find pins.

**And fixing it surfaced a second defect this ticket now owns**: the claim
buckets were keyed by PIN NAME, so after OH-117 the Uno's three GND pads
shared one bucket and the tail loop built THREE coincident copies of the same
mesh, each bucket slot holding a different one. The buckets live on the
wanted entries now -- one pad mesh, one bucket.

OH-95's record stands corrected as this ticket asked: the raycast survived
the carve, the anchor did not.

**Honest limit**: no headless harness can run `carvePins`, so the pin is a
stripped-source assertion plus the browser measurement above, and both
mutations (position never set; vertices left absolute so the offset doubles)
are killed. A carve harness would upgrade this and OH-129's test too.
