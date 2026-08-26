---
id: OH-73
title: Physical wires and the parts they connect, so a pin drives something
status: open
priority: P2
created: '2026-08-27'
touches:
- webui/static/wires.js
- webui/static/parts.js
- webui/static/board3d.js
- webui/static/board3d-panel.js
- webui/static/emulator.html
- webui/static/emulator.css
- tests/webui/test_wires.py
- tests/webui/test_board3d.py
---

THE PIN VIEW SHOWS STATE AND CONNECTS NOTHING. OH-30 left hover picking out on the stated grounds that nothing on the page had anything to select a pin FOR. OH-72 put the vendor's own board in the scene, and the user asked for the other half: a physical simulated wire, and peripherals to connect it to.

TWO DECISIONS, BOTH THE USER'S, 2026-08-27.

  WIRE PLUS OUTPUT PARTS. A wire runs from a pad to a part; the part is driven by the pin state webui/api.py's pin_levels already reports. An LED on D0 lights when the sketch drives D0 high. NOTHING FLOWS BACK INTO THE CPU and that boundary is the reason this needs no core change: the part is a consumer of a state this repository already measures and tests. Input parts -- a button pulling a pin low -- are explicitly NOT in scope, because they would need PINB, PINC and PIND on AVR and PORT_IN on the SAMD21, which are precisely the registers webui/boards/atmega328p.py records as returning a stored zero rather than the pin. That is its own ticket and it is core work.

  FULL ROPE SIMULATION, not a catenary and not a bezier. Verlet particles with distance constraints and gravity, so a cable swings, settles and can be flicked. The cost is stated rather than discovered: it needs a FIXED-TIMESTEP accumulator, or the cable behaves differently on a 60 Hz and a 144 Hz display and no test can pin either; and its state cannot be recovered from its endpoints, so a test asserts invariants -- segment length, endpoint pinning, energy not growing -- rather than positions.

DO NOT REUSE THE PAD MAP'S pin FIELD. Every webui/boards/*.json says in its own assumption field that every pin is null, that the field is the simulator's pin index defined by a PICSimLab board implementation, and that a pad with pin null draws and REFUSES A WIRE. That rule is about the bridge page and PICSimLab's parts. A wire here is between a pad and a part this repository draws, so the identity it needs is the board module's own -- the pin name pin_levels is keyed by, which every answerable pad has. Wiring the two concepts together would make every XIAO unwireable for a reason that has nothing to do with this feature.

BUILD IT VERTICALLY. One part, one wire, end to end first: add an LED, drag from a pad to its terminal, watch it light when the sketch drives that pin. Then widen to more parts. A parts palette with three kinds and no working wire is a horizontal layer in disguise.

WHAT THE RENDERER ALREADY HAS. Pad markers lie flush on the board with userData.pin and userData.label on each, at known world positions -- they were lowered onto the board in OH-72 and are already the anchor a wire wants. The board group carries userData.board. OrbitControls is mounted and will have to be disabled while a wire is being dragged, or the camera turns instead.

Done when a named test pins the rope's invariants under a fixed timestep; when a browser session shows an LED wired to D0 dark and then lit by a sketch that drives D0, with a screenshot of each; when dragging a wire does not turn the camera; and when a board with no vendor model still wires, because the pads are the anchor and the slab is still under them.
