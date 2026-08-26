---
id: OH-73
title: Physical wires and the parts they connect, so a pin drives something
status: done
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
- tests/rules/test_import_3d_model.py
- tools/import_3d_model.py
---

THE PIN VIEW SHOWS STATE AND CONNECTS NOTHING. OH-30 left hover picking out on the stated grounds that nothing on the page had anything to select a pin FOR. OH-72 put the vendor's own board in the scene, and the user asked for the other half: a physical simulated wire, and peripherals to connect it to.

TWO DECISIONS, BOTH THE USER'S, 2026-08-27.

  WIRE PLUS OUTPUT PARTS. A wire runs from a pad to a part; the part is driven by the pin state webui/api.py's pin_levels already reports. An LED on D0 lights when the sketch drives D0 high. NOTHING FLOWS BACK INTO THE CPU and that boundary is the reason this needs no core change: the part is a consumer of a state this repository already measures and tests. Input parts -- a button pulling a pin low -- are explicitly NOT in scope, because they would need PINB, PINC and PIND on AVR and PORT_IN on the SAMD21, which are precisely the registers webui/boards/atmega328p.py records as returning a stored zero rather than the pin. That is its own ticket and it is core work.

  FULL ROPE SIMULATION, not a catenary and not a bezier. Verlet particles with distance constraints and gravity, so a cable swings, settles and can be flicked. The cost is stated rather than discovered: it needs a FIXED-TIMESTEP accumulator, or the cable behaves differently on a 60 Hz and a 144 Hz display and no test can pin either; and its state cannot be recovered from its endpoints, so a test asserts invariants -- segment length, endpoint pinning, energy not growing -- rather than positions.

DO NOT REUSE THE PAD MAP'S pin FIELD. Every webui/boards/*.json says in its own assumption field that every pin is null, that the field is the simulator's pin index defined by a PICSimLab board implementation, and that a pad with pin null draws and REFUSES A WIRE. That rule is about the bridge page and PICSimLab's parts. A wire here is between a pad and a part this repository draws, so the identity it needs is the board module's own -- the pin name pin_levels is keyed by, which every answerable pad has. Wiring the two concepts together would make every XIAO unwireable for a reason that has nothing to do with this feature.

BUILD IT VERTICALLY. One part, one wire, end to end first: add an LED, drag from a pad to its terminal, watch it light when the sketch drives that pin. Then widen to more parts. A parts palette with three kinds and no working wire is a horizontal layer in disguise.

WHAT THE RENDERER ALREADY HAS. Pad markers lie flush on the board with userData.pin and userData.label on each, at known world positions -- they were lowered onto the board in OH-72 and are already the anchor a wire wants. The board group carries userData.board. OrbitControls is mounted and will have to be disabled while a wire is being dragged, or the camera turns instead.

Done when a named test pins the rope's invariants under a fixed timestep; when a browser session shows an LED wired to D0 dark and then lit by a sketch that drives D0, with a screenshot of each; when dragging a wire does not turn the camera; and when a board with no vendor model still wires, because the pads are the anchor and the slab is still under them.

**Note 2026-08-27:** CLOSED 2026-08-27 in fcce44c. All four clauses of the Done-when, and the physics is the part worth reading about.

THE ROPE IS ARITHMETIC IN A FILE WITH NO IMPORTS, which is the decision everything else here rests on. Every other JavaScript test in this repository greps its source, because a WebGL scene cannot be rendered from Python and there was nothing else to do. wires.js imports nothing -- not three.js, not the DOM -- so tests/webui/test_wires.py runs it under node and asserts what it DOES: energy falls to 3.8e-12 rather than growing, segments stay within 1% of rest, pinned ends do not move at all, and 60 Hz and 144 Hz agree to 3.5e-5 after five seconds. Ten tests, and seven mutations against them all went red.

FOUR PHYSICS BUGS, EVERY ONE FOUND BY MEASURING AND NONE BY LOOKING. Each looked plausible on screen.

  (a) A wire dragged nine units past its reach stretched 140% -- a rubber band, and the constraint cannot fix it because no rope that short has a shape between those two points. It pays out now, which is what a bench does: you reach for a longer lead. A pointer never teleports, and the same nine units dragged smoothly never exceeded 1.66%.

  (b) 161% over rest on a wire that had been still for two seconds, because its head was pinned to a pad INSIDE the board's collider. The bounding box a board casts includes its USB connector standing 2.4 mm proud, so every pad on the top face was inside it. The collider is the PCB slab now. The same failure arrives from the other end: a wire's tail is inside the part it is plugged into by construction, so a wire is never blocked by its own part.

  (c) Resolving contact once at the end of a step rather than inside the constraint loop was tried, on the reasoning that penetration is what must not survive: 75.6% against 16.3%. An unopposed push leaves a shape the next step has to undo.

  (d) A wire created already-connected began with all twenty-two nodes on the pad and one teleported to the terminal, and 27.8% survived two and a half seconds of settling. Laid out along its own line to begin with it settles at 2.3%. The generalisation: a solver's INITIAL state is part of its answer, and a transient that has to travel through a collider does not simply decay.

A MUTATION FOUND DEAD CODE RATHER THAN A WEAK TEST. Removing the loop's substep cap changed nothing, because the accumulator was already clamped above it -- two guards doing one job, which reads as care and is two things to keep true. One now, and the test that could not fail before catches it.

THE PARTS ARE REAL PARTS AND NOTHING HERE MODELS A SHAPE. The first version built an LED from a capsule and two cylinders and it looked like an LED drawn by somebody who had been told about one. They come from KiCad's kicad-packages3D through OH-72's importer, in KiCad's own folders because a taxonomy invented here would be one more thing to keep true: LED_THT holds three LEDs and Buzzer_Beeper holds a buzzer.

EVEN THE TERMINALS ARE READ OFF THE MESH -- the ring of vertices at each lead's tip, averaged -- which gives 2.540 mm for the LEDs and 7.600 for the buzzer. The first version took the single lowest vertex per side and returned -1.470 and +0.870 for a part whose leads are 2.54 apart: one answer on the lead's axis and one on its rim, with no way to tell which from the number. A lead spacing typed in from a datasheet would be a second source that can disagree with the geometry, and it would disagree silently -- a wire meeting nothing, a millimetre from the leg.

WHY THERE IS NO SWITCH IN THE CATALOGUE, though it is in the same library: it is an input, it would drive a pin, and that needs the PIN registers this repository has already written down as unmodelled. A switch on this bench would be a part that does nothing.

THE BUZZER'S MARK MEANS DRIVEN AND NOT SOUNDING, said in the source and in the panel. This page has no audio, so nothing can show what a buzzer is actually doing; lighting its polarity mark says the one thing that is true.

TWO THINGS FOUND BY LOOKING RATHER THAN BY A TEST, which is the third and fourth time this repository has recorded that. The bench note used the `.detail` class, which is the ERROR style -- so 'every part is wired' appeared as red text on a red wash, and a normal state read as a failure. And a failed setPointerCapture threw into the console while the drag it was decorating carried on working perfectly.

VERIFIED IN A BROWSER, all four clauses: a drag from a pad to a terminal makes a wire and the camera does NOT turn (capture phase, so OrbitControls never sees the press); the LED reads unknown, then high once the sketch drives D0; the list's x takes one wire off and the part goes back to UNKNOWN rather than to off, which is the same distinction every pad keeps; and an Arduino Uno, which has no vendor model, still wires -- 0.9% stretch, LED high on pin 13, and the caption still says footprint.

NOT DONE, each for a stated reason: no input parts, per the ticket; no audio, so a buzzer shows driven rather than sounding; parts cannot be dragged around the bench, only added and removed; and a wire dropped in mid-air is discarded rather than left dangling, because a connection the page could not explain is the thing this view exists not to draw.
