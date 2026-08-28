---
id: OH-95
title: The pad markers are cylinders this repo drew, standing where the model already
  has pins
status: done
priority: P1
created: '2026-08-28'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

**Reported: "the cylindrical shapes for wire connections should not exist and
should use the real pins to connect the wires."** They are right, and on the
Arduino Uno the fake and the real are in the same place: `showBoard` builds a
`CylinderGeometry` disc per pad, and `compose_board_3d.py` has already stood
the vendor's own header on the board underneath it. A reader sees a pale disc
hovering over a gold pin. `.playwright-mcp/pins-before-crop.png`.

## THE MARKER DOES THREE JOBS AND ONLY ONE OF THEM IS DRAWING

  * it carries the pin's state colour -- `repaint`, `setLevels`, `refreshTheme`
  * it is the raycast target that starts a wire -- `onPointerDown`
  * it is the anchor a wire's board end follows -- `anchorOf`

So it cannot simply be deleted. What can happen is that the OBJECT stops being
a cylinder this repository invented and starts being the pin the vendor
published, with `view.pads` still a `Map<pin, Mesh>` so every one of those
three keeps working unchanged.

## THE PINS ARE SEPARABLE, MEASURED RATHER THAN HOPED

**Arduino Uno**, gold `#b58136`, inside the `IOH` header's own solid and above
the board: 440 vertices, clustering into columns at exactly 2.54 mm pitch --
44 per pin for ten pins. Their top is `y = 10.14`, which is `pad_top` in the
model's own extras, which is where the marker is already placed. **The wire is
already anchored at the true pin tip; the disc is just a blob drawn there.**

**XIAO-RP2040**, inside the unstyled `#808080` PCB solid, near the long edges
(`|z| > 8.0`): 1,660 vertices in seven columns of 228 at 2.54 mm pitch. The
castellations. Seeed did not give them a colour of their own -- the whole PCB
is `#808080`, which is `UNSTYLED` -- but they are cleanly separable by
position.

So ten of the twenty-six boards have real pin geometry to use.

## THE SIXTEEN THAT HAVE NONE

The other sixteen draw an extruded footprint: a slab with no components and no
pins, because their vendor publishes no model. There is no real pin to use and
nothing to tint. **Decided: no cylinder is drawn there either.** The pads keep
an INVISIBLE collider so a wire can still be started and followed -- nothing
is rendered, and the bench does not stop working on sixteen boards -- and
their pin states are reported in the table beside the canvas, which already
writes a sentence per pad.

That is the cost of the change and it is written down rather than discovered:
on those sixteen boards a running sketch no longer shows on the picture.

## DONE WHEN

No `CylinderGeometry` is rendered on any board; on a board whose model has
pins, `view.pads` holds the vendor's own geometry and it takes the state
colour; a wire dragged from a pin starts and ends on that geometry; the
sixteen footprint boards still allow a wire to be made; and the panel says
which of those two a reader is looking at rather than leaving them to notice.

Not in scope: giving the extruded footprint real pad geometry of its own. That
is a different ticket and a different source question.

## DONE, 2026-08-29

No cylinder is rendered on any board. On the Arduino Uno, **25 of 30 pads are
now the vendor's own header pin**, carved out of the model and registered in
`view.pads`, so the raycast, the anchor, the state colour, the theme and
`describe` all went on working without knowing the geometry changed underneath
them. Verified in a browser with the blink running: `realPins` 25, pin 13
among them, "22 of 32 pads answerable", no console errors.
`.playwright-mcp/pins-before-headers.png` against `oh95-after.png`.

**Painting the state into the metal was wrong and was measured rather than
argued about.** Brass `#b58136` with `high` blended 72% of the way in came out
`#66744b`, and `input` came out `#7e726c` -- two muddy browns three pixels
wide, where the pin had stopped looking like brass and the state still could
not be read. The state is EMITTED now: the colour stays the metal the vendor
published and `emissive` carries the state, which reads at three pixels and is
the better metaphor -- the pin is made of the same brass and what changed is
that it is doing something. `unknown` does not glow at all, because it is most
pads on most boards and a board whose every pin is lit says nothing.

**The five that did not carve are a real defect this uncovered, not a
tolerance problem.** Measured as the distance from each pad to the nearest
metal above the PCB: fourteen pads agree to 0.05-0.07 mm, eleven are out by a
consistent 0.65-0.77 mm -- exactly two whole headers -- and five are out by
1.21 to 3.84 mm. **The cylinders were drawn at the pad map's positions, so
they had been in the wrong place all along, which is why they read as blobs
beside the pins rather than on them.** Filed as OH-96. Widening
`PIN_REACH_MM` past 1.27 would reach them and would let a pad claim its
NEIGHBOUR's pin, lighting the wrong one convincingly, so it stays at 1.1 and
the table carries the measurement.

**The nine XIAOs get no carved pins, and that is a limitation rather than a
decision.** Their castellations are plated half-holes inside the board's own
thickness rather than posts standing on it, and Seeed styles the whole PCB
`#808080` -- `UNSTYLED` -- so they are neither metal by the material test nor
above the board by the height test. Their pads keep invisible colliders. A
wire still connects; nothing lights.

8 mutations, 8 killed -- and one was the repository's own tripwire rather than
mine: `test_the_renderer_writes_down_no_colour_of_its_own` caught
`new THREE.Color(0x000000)`, correctly. Black there is not a colour this file
chose, it is the absence of light, and it is `setScalar(0)` now.

7 new tests. Gate: 1,757 -> 1,764 passed, 17 skipped; all eight checkers
exit 0.
