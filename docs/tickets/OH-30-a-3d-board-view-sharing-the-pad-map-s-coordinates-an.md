---
id: OH-30
title: A 3D board view, sharing the pad map's coordinates and the UI's palette
status: done
priority: P1
created: '2026-08-25'
touches:
- webui/static/board3d.js
- webui/static/board3d.css
- tests/webui/test_board3d.py
- webui/static/emulator.html
- webui/static/emulator.js
- webui/static/emulator.css
- tests/webui/test_pin_view.py
- webui/api.py
- webui/emulator_server.py
- webui/boards/samd21.py
- webui/boards/atmega328p.py
- webui/static/board3d-panel.js
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

**Note 2026-08-26:** UNBLOCKED 2026-08-26, and the block was answered rather than waived. The reason recorded for blocking was 'no board here has a mesh': Seeed publishes 37 .kicad_mod and zero .kicad_pcb, tools/import_3d.py reads a .kicad_pcb Edge.Cuts outline, and there is no .gltf or .glb outside third_party. All of that is still true.

WHAT WAS MISSED IS THAT A MESH IS NOT THE ONLY SOURCE OF GEOMETRY. Every one of the 26 boards already carries exact pad coordinates in webui/boards/<board>.json -- 550 pads in total -- and each file's own derivation field says where they came from: 'Pad centres are exact to three decimal places in millimetres, scaled at 8.0 px/mm ... Nothing here was measured off an image.' Twenty-five of them also carry an SVG outline traced from the vendor's F.SilkS and F.CrtYd. So the courtyard extent and every pad position are vendor data that is already committed.

AND THE WEBGL DECISION IS ALREADY MADE. This ticket says the renderer 'is a decision this ticket makes explicitly rather than by npm install'. It was made: three.module.js, three.core.js and OrbitControls.js are vendored under webui/static/vendor and webui/static/scene3d.js already draws a PCB slab with a real header on the bridge page. Nothing new is fetched.

WHAT THIS CHANGES ABOUT THE HONEST-DEGRADATION RULE, which stands. A slab at the vendor's own courtyard extent with the vendor's own pad positions is not the generic rectangle this ticket forbids -- but it is also NOT a model of the board: no components, no connector, no real thickness. So the view has to say, in the page and not only here, that it is a footprint extruded and not a board model. An absent thing is still reported absent; what changed is which thing is absent.

SCOPE WIDENED, because OH-69 merged into this. That ticket was filed on 2026-08-26 after a browser session found there is nowhere on the emulator page a pin appears at all, and it carries the reason this is P1 rather than P3: three boards can be built for now and two of them cannot print, so on a XIAO the only feedback a person gets is an instruction count. A picture of a board with dead pads would not fix that, so the live state is part of this ticket rather than a follow-up to it.

THE SHAPE, decided before any body was written. Each board module gains pin_states(cpu) -> {label: 'high'|'low'|'input'}, found by getattr the way webui.api.uart_view finds uart0_output -- so the chip-specific register addressing stays in the chip module and a label this board cannot answer for is ABSENT from the result. webui.api.pin_view joins that to webui/pinmap.py's coordinates and reports an absent label as 'unknown', which is a claim about the model where 'low' would be a claim about the program. That distinction is the whole reason this is not two lines of JavaScript.

**Note 2026-08-26:** CLOSED 2026-08-26 in b581584. Every clause of the Done-when, and the one that needed the most care is the third.

ONE BOARD RENDERS IN BOTH THEMES -- three do, over two chips, and both themes were checked with screenshots rather than assertions. That is not belt and braces: BOTH theme bugs found here were invisible to the DOM, because the table beside the canvas was correct the whole time. refreshTheme repainted the slab and not the posts, so the light theme gave a white board carrying dark-theme pins; and the state ramp was ordered by lightness, which flips between themes, so in the light theme a pin driven low and a pin nobody models were two nearly identical whites on a white board. Ordering by CONTRAST against the board fixes both at once, because --ink is defined as the colour that reads against --surface in whichever theme is on.

SELECTION IS SHARED BETWEEN THE VIEWS -- and it is shared by both views reading one payload rather than by a selection mechanism, which is the smaller thing that turned out to be the right one. api.pin_view returns the pads once and the state poll returns levels many times a second; the canvas and the table render the same array, so they cannot disagree about which pin is which. There is no hover-to-highlight, and that is scope held rather than scope met: nothing in the emulator page has anything to select a pin FOR yet, because there are no parts to wire it to.

A BOARD WITHOUT A MODEL IS VISIBLY A BOARD WITHOUT A MODEL, and the wording matters more than it looks. No board here publishes a 3D model, so this is not the case of one board degrading -- it is every board. The panel says 'A footprint, extruded -- not a model of the board' above the canvas, names what IS the vendor's (the outline and every pad centre, exact to three decimals) and what is not (a 1.6 mm constant, and no components). test_the_panel_says_it_is_a_footprint_and_not_a_model_of_the_board is what keeps that sentence there.

THE FOURTH STATE IS THE PART THAT WAS NOT IN THE TICKET. A pad can be high, low, input or UNKNOWN, and only the first three are claims about the program. The Uno answers for six of its thirty-two pads because webui/boards/atmega328p.py models PORTB and neither PORTC nor PORTD -- so twenty-six pads read 'not modelled' and the panel says '6 of 32 answerable' rather than showing twenty-six dark pads that look exactly like a sketch that has driven nothing.

A THIRD BUG, in the tests, found by mutation rather than by looking. The check that every custom property the renderer reads is one the stylesheet defines matched only literal read("--x") calls -- and the four state colours reach the stylesheet through read(name) inside a loop, so they matched nothing. A deliberate typo of --changed left all eleven tests green. Both patterns are now asserted non-empty, which is the shape that makes a silently-empty pattern impossible rather than unlikely.

WHAT THIS DELIBERATELY IS NOT. No drag-to-wire: that is the bridge page's and it has parts to wire to. No PCB artwork, though 25 board SVGs exist: the Uno's lives in PICSimLab's share tree and is absent on a clean checkout, so texturing would work on 25 boards and silently not on the one most people start with. No hover picking, per above.

TWO RESIDUALS worth a later ticket rather than a fix here. The Uno's PORTC and PORTD would take 20 of its 26 unknown pads live and are a board-model change that wants an image reaching them first, which is this repository's own growth rule. And Run is a fixed 200,000-instruction budget, so a blink is watched by pressing Run repeatedly rather than by watching it move -- the pins are live, the clock is not free-running.
