---
id: OH-78
title: A wire passes through the board's own components, and a bench part is drawn
  at the wrong scale
status: done
priority: P2
created: '2026-08-27'
touches:
- tools/compose_board_3d.py
- webui/static/board3d.js
- tests/rules/test_compose_board_3d.py
- tests/webui/test_board3d.py
---

REPORTED BY THE USER 2026-08-27: "wire is still going through the components and board." Both halves are real and they are two different defects with one shared cause -- something that is on screen is not something the physics knows about.

(1) THE BOARD'S COMPONENTS ARE NOT COLLIDERS. `webui/static/board3d.js`'s `refreshColliders` pushes exactly two kinds of solid: the PCB slab, from the model's own `pcb` extras, and a box around each part standing on the bench. The fifteen components OH-76 put ON the board -- the DIP-28, four headers, two ICSP blocks, the USB socket, the barrel jack -- are geometry in the mesh and nothing else. A wire dropped across the board passes straight through all of them.

That was invisible until OH-75, because before it there were no components: the board was an extruded slab and the slab WAS the collider. Drawing the parts made the collider set incomplete without changing a line of it.

**The boxes are already computed.** `tools/compose_board_3d.py` measures every placed component's extent to check it lands on the board; emitting the same numbers into `asset.extras` costs nothing and gives the renderer exactly what `refreshColliders` wants. A fetched vendor model has no such list and keeps today's behaviour, which is the honest default: nobody has told it where the components are.

(2) A BENCH PART IS 1.42x TOO BIG ON THIS BOARD. `addPart` scales a part by `PX_PER_MM * SCALE` -- the constant 8 px/mm that `tools/import_board.py` generates board JSONs at. The Arduino Uno's pad map was traced off PICSimLab's artwork instead and is 5.638. So a 5 mm LED is drawn 7.1 mm across beside a board drawn at its real 68.58, and 8 / 5.638 is exactly the 1.42 measured on screen.

This is the SAME defect OH-76 fixed for the board model and missed for the bench. `placeModel` learned to derive the scale from `pad_span`; `addPart` was never told. The fix is that there should be one number: the scene's millimetres-per-unit, decided once when the board is drawn and read by everything that puts millimetres into the scene.

WHAT THIS TICKET IS NOT. The user's second report -- an LED lighting while ungrounded -- is a much deeper problem and is its own ticket: it needs a circuit, not a collider. This one is geometry only.

Done when a wire dropped across the Arduino Uno rests ON its DIP-28 and headers rather than through them, a 5 mm LED beside the Uno measures 5 mm against the board's 68.58, and both are checked by numbers rather than by looking.

**Note 2026-08-27:** CLOSED 2026-08-27 in bd680cf. A wire rests on the board and on its components, and a bench part is the size it would be beside the real thing.

THE GENERALISATION, AND IT IS THE THIRD TIME THIS SESSION: a decision that was correct when it was made stops being correct when its premise changes, and nothing about it looks wrong in the meantime. `refreshColliders` collided a wire with the PCB slab, which WAS the whole board. OH-75 put fifteen components on it and the collider set became a description of a board that no longer existed, without a line of it being edited. The comment above the lighting says the same thing about shadows -- 'this scene has one object' -- and is now equally stale.

THE ONE THE USER COULD SEE was the slab in the wrong place. `placeModel` built it in absolute scene coordinates while the model group sits at the pad centroid. On a XIAO those agree, because the castellations run down both long edges -- so it was right for nine boards by coincidence. The Uno's group sits 4.545 units off the origin and the slab stopped 4.5 short of the right-hand edge: board x -22.00..+20.01 against slab -23.20..+15.46, and pads 0 to 13 are on exactly that edge.

Both are stated in the MODEL's frame now and go through `matrixWorld` in one function. That deleted the quarter-turn fix-up as a side effect -- two hand corrections that swapped the slab's axes and then its offset when a model was rotated. Each was right; each was a thing to keep true. A box in the model's frame turns with the model.

MEASURED RATHER THAN LOOKED AT, because a wire over a chip and a wire through it are the same picture from most angles. `penetration()` reports the worst node's depth inside anything the rope solved against: 2.248 mm inside the DIP-28 for a wire laid straight from pad 12, 0.000 mm once it settles. The before/after IS the test -- a zero from a probe that cannot see anything is worth nothing, and the screenshot that made this look fixed was taken before the colliders existed.

THE BENCH SCALE was the same defect OH-76 fixed for the board and missed for the bench: `addPart` kept the constant 8 px/mm while `placeModel` learned to derive it. One `view.mmScale` now.

AND A CORRECTION TO THE RECORD: the wiring bug reported at the end of the previous session does not exist. `connect()` works. The probe that found it called it after a fixed timeout instead of awaiting the async `addPart`, so the mesh had not loaded -- a bug in the test harness reported as a bug in the code, which is worse than not finding it.

AN ENVIRONMENTAL FAILURE WORTH KNOWING: `test_an_upload_from_another_origin_is_refused` fails while a dev server is running on 8088 and passes alone. Kill the server before trusting a full gate, the same way section 9 of the handoff says to count listeners before trusting the page.

NOT IN THIS TICKET: the LED that lights while ungrounded, which is the user's other report and needs a circuit rather than a collider -- it is the next ticket and the user has chosen a full nodal solver with datasheet parameters; and the lighting, which is two lights and no shadows on a scene that now has fifteen objects.
