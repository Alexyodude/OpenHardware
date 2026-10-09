---
id: OH-216
title: The page sets each model by the pads both sides name, and carves only metal
  on a pad's own side
status: open
priority: P2
created: '2026-10-09'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
- tools/import_board.py
- tests/rules/test_import_board.py
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-*.json
---

Follow-ups from OH-215 and its review (2026-10-09). OH-215 fixed the page's quarter turn by comparing two stated outline orientations (the board file's pad map and the model's `extras.pcb`). Three things remain, all in how the page sets a model on a board.

1. A turn chosen from pads, not from shapes. The comparison cannot tell an exactly square board (the Qwiic Pocket is placed right only because both comparisons tie; a near-square board could flip) or a half turn. Have the composer write its header pads into the model's extras (e.g. `header_pads: [[x, z, w, h, name], ...]` in model millimetres, named by net or pad number as the board file names them) and have `placeModel` choose the turn that lands the board file's pads on them, refusing by name when none does. The Glyph Mini's 0.73 mm centring offset (the composer centres on 46 pads of J3, J4 and J5, the board file on its 23) belongs here too: centre on the pads both sides name. `extras.pcb`'s `long` and `short` now mean the x and z extents, not sorted sizes, and the comment at `tools/import_3d_model.py` ~1718 still says "long side, short side": correct it, since sorting them would break the six boards again.
2. XIAO underside pads carve topside metal. The XIAO SMD and RP2350-DIP board files include underside pads, all tagged `header-top`, so `carvePins` gives each the topside metal above it and recolours it as a pin (OH-215's review: C3-SMD 1557 stray triangles, C6-SMD 3186, C5-SMD 2930, RP2350-SMD 5083, nRF54l15-SMD 5450, RP2350-DIP 3134), and that metal becomes the wire's anchor. The side a pad is on has to be stated in the board file (the importer reads it from the footprint's layers) and honoured by `carvePins`.
3. Fetched XIAO meshes carve little or nothing (SAMD21 0 of 14 and 0 of 20; RP2040, S3 and nRF52840 DIPs 0 of 14): on the SAMD21 the castellation copper tops out at 1.22 mm under a stated 1.61 mm PCB, so the "above the PCB top" filter excludes it. The pads stay as invisible colliders, the documented fallback; decide whether the filter or the stated PCB thickness is wrong.

Done when the page chooses each model's turn and centre from pads both sides name, every pad carves only metal on its own side, and each fetched mesh's castellations carve or say why not, each held by a test over every board.
