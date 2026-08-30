---
id: OH-129
title: A wire made while the model is in flight keeps a pad mesh carvePins disposes
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 wire survey.

`loadModel` is deliberately not awaited; `beginWire` stores the pad MESH in
`wire.post`; `carvePins` then releases that mesh and swaps the bucket slot.
A wire made during the fetch keeps a detached, disposed cylinder: `anchorOf`
still reads it (a null-parented `getWorldPosition` returns board-local), the
head stops tracking, and no later `setLevels`/`refreshTheme` pass can repair
it because `view.pads` no longer holds it. Distinct from OH-128 and not fixed
by it -- the wire holds the OBJECT, not the slot.

DONE WHEN carvePins repoints any wire whose `post` it replaces, or a wire
holds the (pin, index) key and resolves late; either way a wire made before
the model arrives follows the carved pin afterwards.
