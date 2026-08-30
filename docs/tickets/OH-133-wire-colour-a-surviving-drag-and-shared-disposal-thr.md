---
id: OH-133
title: 'Wire colour, a surviving drag, and shared disposal: three small bench lifecycle
  defects'
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
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

---

**CLOSED 2026-08-30.** All three, in `webui/static/board3d.js`:

  1. **Colour off the id.** `beginWire` takes `const id = nextWireId++`
     first and keys the palette on `(id - 1) % WIRE_COLOURS.length` -- the
     fresh-bench sequence is unchanged (id 1 wears colour 0), and after a
     disconnect the next wire moves ON through the palette instead of
     repeating the colour the shrunken count pointed back at.
  2. **The drag dies with the bench.** `clearBench` nulls `view.dragging`
     right after discarding the wires -- the drag's wire was one of them,
     and a pointer held across a board change otherwise kept writing to a
     released mesh and discarded it a second time on pointerup.
  3. **`releasePart` knows what is the part's own.** `loadPart` hands out
     `clone(true)` of the cached template, and a three.js clone SHARES
     geometry and materials with the template and every sibling -- so the
     old blanket `release` over the whole tree forced a fresh GPU upload
     for every survivor on every removal. Per-part is exactly two things,
     and the helper releases exactly those: the lens material `dressPart`
     clones (so two LEDs light independently) and the terminal target
     spheres `makeTarget` builds fresh -- the meshes carrying
     `userData.terminal`. Both removal paths (`removePart`, `clearBench`)
     go through it.

OH-131's fresh duty-test was amended in the same change: it pinned
"release(object) appears in removePart", which was the blanket mechanism;
the duty (the part's meshes are released) now reads `releasePart(part)`
with the narrowing explained in place.

Suites: tests/webui/test_board3d.py 83 -> 86 passed. Seven mutations, all
killed: the colour re-keyed to the live count, the id no longer hoisted,
the drag fix deleted and commented out, removePart blanket-releasing
again, the lens dispose dropped, and the terminal guard dropped.
