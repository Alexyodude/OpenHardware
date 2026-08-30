---
id: OH-129
title: A wire made while the model is in flight keeps a pad mesh carvePins disposes
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
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

---

**CLOSED 2026-08-30.** The first of the ticket's two remedies: `carvePins`
repoints any wire whose `post` it replaces, at the one place the swap
happens --

    bucket[bucket.indexOf(pad.post)] = pin;
    for (const wire of view.wires) {
      if (wire.post === pad.post) wire.post = pin;
    }

-- so a wire pulled during the model fetch follows the carved pin the moment
it lands. The drag in progress is in `view.wires` too (its wire is pushed by
`beginWire`, terminal still null), so the same loop covers a wire mid-drag
when the model arrives, which is the rawest form of the race.

The (pin, index)-key alternative was not taken: `wire.post` staying a mesh
keeps `anchorOf` a single `getWorldPosition` with no lookup, and the repoint
costs one walk of the wires per carved pad, at carve time only.

Asserted at the source with comments stripped, the OH-117 lesson, because no
headless harness can run `carvePins` (the gap OH-128's record owns): the
walk, the `wire.post === pad.post` guard, and the handover are each pinned.
Three mutations, all killed -- the loop deleted, the guard dropped, and the
fix commented out (the third is what the comment-stripping is FOR).

tests/webui/test_board3d.py 80 -> 81 passed.
