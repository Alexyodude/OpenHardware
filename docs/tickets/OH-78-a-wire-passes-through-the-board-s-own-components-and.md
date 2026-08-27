---
id: OH-78
title: A wire passes through the board's own components, and a bench part is drawn
  at the wrong scale
status: open
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
