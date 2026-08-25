---
id: OH-30
title: A 3D board view, sharing the pad map's coordinates and the UI's palette
status: blocked
priority: P3
created: '2026-08-25'
touches:
- webui/static/board3d.js
- webui/static/board3d.css
- tests/webui/test_board3d.py
parent: OH-29
---

Draw the ingested mesh in the emulator UI, with pads live: hovering a pin in 3D is the same selection as hovering it in the 2D map, because both read the same board JSON.

Two constraints the repository has already paid for. OH-16 folded targets.html back into emulator.html precisely so there would not be two pages with two palettes drifting apart -- so this is a view the existing toolbar switches to, not a second page, and its rules go in emulator.css rather than beside them. And a WebGL renderer is a new dependency in a project that currently has none; whether it is vendored, fetched, or hand-written against raw WebGL is a decision this ticket makes explicitly rather than by npm install.

Degrade honestly. A board with no 3D model shows the 2D map and says no model was published for this board -- it does not show a generic rectangle. The repository's habit is that an absent thing is reported absent.

Done when one board renders in both themes, pin selection is shared between the 2D and 3D views, and a board without a model is visibly a board without a model.

Depends on the 3D ingest ticket for meshes, and on OH-22 for the emulator.html and emulator.js hook it needs.

**Note 2026-08-26:** BLOCKED 2026-08-26, on source material rather than on effort. Measured, not inferred.

THE DONE-WHEN CANNOT BE MET FOR ANY BOARD IN THIS REPOSITORY. It requires 'one board renders' with 'pin selection shared between the 2D and 3D views'. The 2D side is webui/boards/*.json, twenty-six pad maps. The 3D side needs a mesh for one of those same boards, and there is none:

  * Seeed publishes 37 .kicad_mod footprints and ZERO .kicad_pcb. Counted across the whole vendor tree today.
  * tools/import_3d.py -- which OH-29 shipped -- reads a .kicad_pcb Edge.Cuts outline. It has nothing to read for any XIAO.
  * A .kicad_mod is the MODULE's footprint, not a board outline. It carries pads, not Edge.Cuts. This is the same distinction that defeated OH-65's pad-geometry line of enquiry, and it defeats this one for the same reason.
  * No .gltf or .glb exists anywhere outside third_party/.
  * OH-29's own note already said it: 'none of the 26 boards currently in this repository has a 3D model; a board that does must be imported first.'

WHAT ALREADY EXISTS AND IS NOT THIS. webui/static/scene3d.js and models3d.js draw a 3D view today, and app.js has a working 2D/3D toggle -- but that is the PICSimLab BRIDGE page, and models3d.js's hasModel() answers about PERIPHERALS on a workbench, not about boards. Reusing it here would render parts, not the board, which is not what this ticket asks for.

AND THE 2D HALF IS ALSO ABSENT. emulator.html has no pad map at all -- no pinmap, no pads, no SVG board art. 'Shared selection between the two views' therefore needs both views built, and this ticket claims neither emulator.html nor emulator.js.

WHAT WOULD UNBLOCK IT, cheapest first: import a board that a vendor publishes 3D for. OH-23's survey found five, of which only two publish an assembled board -- Raspberry Pi's Pico-R3.step (1.7 MB) and Waveshare's RP2040_Zero.stp (9.5 MB) -- and both are STEP, which needs NURBS evaluation in a repository with zero third-party runtime dependencies. The cheaper route is a vendor publishing .kicad_pcb, which import_3d.py already reads; none of the 26 boards' vendors does.

NOT ATTEMPTED, and deliberately: drawing a generic extruded rectangle for boards with no model. The ticket forbids it in its own words -- 'it does not show a generic rectangle' -- and rules/board-claims.md is the general form of the same rule.

Left open rather than closed: the work is wanted and the ticket is right. It is waiting on a board, not on a decision.
