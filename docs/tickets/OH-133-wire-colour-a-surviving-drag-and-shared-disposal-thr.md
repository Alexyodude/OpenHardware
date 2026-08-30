---
id: OH-133
title: 'Wire colour, a surviving drag, and shared disposal: three small bench lifecycle
  defects'
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 wire survey; three small lifecycle
defects, one ticket because each is a few lines.

1. Wire colour indexes `view.wires.length`, so after any disconnect the next
   wire repeats a colour on the bench. `nextWireId` exists because "an index
   changes when an earlier wire is removed"; the colour never got the same
   treatment. Key colours off nextWireId.
2. `view.dragging` survives clearBench/clearBoard: a drag held across a board
   reload writes to a released wire and re-releases it (indexOf -1). Null it
   in clearBench.
3. `release()` on removePart/clearBench disposes geometry and materials
   SHARED by every clone of the same part kind and by the cache template --
   verified with the vendored three. GPU re-upload churn today. Release only
   what dressPart cloned, or refcount the cache.
