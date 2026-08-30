---
id: OH-125
title: What the composer measures stops at stdout and reaches no reader
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 model survey.

`compose` prints artwork tallies, `not ink`, `not cu`, cutouts, unpinned
turns, dropped elements -- and the extras dict carries none of it, so
`board3d-panel.js` can only say "Not drawn: Y1, Y2" about an Uno also missing
four LEDs, 432 silkscreen strokes and 99 unmapped placements. This is the
mechanism that let OH-119 and OH-122 sit unnoticed; the file's own principle
says "a gap that is measured is a gap somebody can close, and a gap that is
silent is one nobody knows about" -- and the measurement stops at stdout.

DONE WHEN the tallies ride in extras and the panel shows them, so the page's
claim about what is not drawn is the composer's own measurement.
