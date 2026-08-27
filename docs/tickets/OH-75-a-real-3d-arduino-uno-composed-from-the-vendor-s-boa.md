---
id: OH-75
title: A real 3D Arduino Uno, composed from the vendor's board file and KiCad's component
  meshes
status: open
priority: P2
created: '2026-08-27'
touches:
- tools/import_board.py
- tools/eagle.py
- tools/compose_board_3d.py
- webui/boards/Arduino Uno.json
- webui/static/board3d-panel.js
- tests/rules/test_import_board.py
- tests/rules/test_compose_board_3d.py
- tests/webui/test_board3d.py
- tests/rules/test_kicad.py
- tests/rules/test_board_sources.py
- docs/research/board-sources/sources.json
---

ASKED FOR BY THE USER, 2026-08-27: "arduino uno 3d model is not proper. It's just a flat board." Confirmed in the browser -- describe() reports model: null, so the Uno takes the extruded-footprint path. It is the only BUILDABLE board still drawn that way and the one most people open first.

NOBODY PUBLISHES A MESH FOR IT, and here is exactly where that was checked so the next person does not repeat it -- section 3.1 of the 2026-08-27 handoff cost a day by recording a negative without its scope.

  * Arduino's own docs page for the Uno Rev3 links A000066-cad-files.zip, 303,265 bytes, CC-BY-SA-4.0 (License.txt inside says so). Downloaded and opened 2026-08-27: it holds UNO-TH_Rev3e.brd, UNO-TH_Rev3e.sch and the licence. **No STEP, no WRL, no mesh of any kind.**
  * KiCad's kicad-packages3D has no Arduino board model. Module.3dshapes holds exactly two files and both are a Wemos D1 Mini.
  * docs/research/board-sources/sources.json already recorded model_3d: no for Arduino on 2026-08-25, with the same evidence. This census agrees with it rather than replacing it.

SO THE MODEL IS COMPOSED, NOT FETCHED, AND NOTHING IS INVENTED. Two sources, both CC-BY-SA-4.0, both already known to this repository:

  * **geometry** from Arduino's EAGLE .brd -- an outline of 68.580 x 53.340 mm on layer 20 in 12 segments (which is the official 2.7 x 2.1 inch, to the micron), 4 mounting holes, and 116 element placements with package, position, rotation and mirror;
  * **component meshes** from KiCad's kicad-packages3D, which tools/import_3d_model.py ALREADY fetches OH-73's LEDs and buzzer from. Checked by listing each library 2026-08-27: DIP-28_W7.62mm.step exists (the ATmega328P), PinHeader_1x08_P2.54mm_Vertical.step and the 1x10 exist (IOL, POWER, AD and IOH), BarrelJack_CUI_PJ-063AH_Horizontal.step exists, CP_Radial_D6.3mm_P2.50mm.step exists (the electrolytics), Crystal_HC49 exists.

THE HEIGHT IS THE WHOLE REASON IT MUST BE MESHES AND NOT BOXES. **Zero of the 116 packages in the .brd declares a height** -- counted, not assumed. So an extruded box per component would need a thickness typed in per package, which is a second source that can disagree with the geometry and would disagree silently. That is section 3.6's lead-tip defect in a new place. Every height here comes off a real mesh or the component is not drawn.

ONE GAP, AND IT IS SAID ON THE PAGE RATHER THAN FAKED: the USB-B. Connector_USB.3dshapes holds five entries and two STEPs, a Micro-B and a Mini-B, and no USB_B_* at all. The Uno's most recognisable feature after the headers, and there is no honest mesh for it. Draw the rest and say which one is missing, the same way the ESP32-C3 says its model is on GrabCAD.

MOST OF THE READER ALREADY EXISTS, which is why this is P2 and not a research project. tools/eagle.py (503 lines) parses EAGLE .brd into placed pads, nets and an outline, with its placement order checked against routed copper on a SparkFun board -- 120 of 131 contacts within 0.01 mm, and the check is sensitive: dropping the mirror takes it to 104 and the worst residual to 10.7 mm. tools/import_board.py is the front end over it. Run against the Uno 2026-08-27 it already emits a correct board proposal, pads labelled IO7, IO6, IO5 from the vendor's own <signals> rather than from an assumed silkscreen order.

WHAT IT CANNOT DO YET: --select names ONE placed element, and the Uno has four headers -- IOH (1X10) at (30.23, 50.80), IOL (1X08) at (54.61, 50.80), POWER (1X08) at (36.83, 2.54) and AD (1X06) at (57.15, 2.54). 10 + 8 + 8 + 6 is the 32 pads webui/boards/Arduino Uno.json already has. It also emits pin: null throughout, and the existing file carries real simulator pin indices that must survive.

AND THE PAD MAP IS THE OTHER HALF OF THIS, approved by the user the same day. The Uno is **the only board of 26** whose pads were not derived from a vendor footprint: its derivation says "Pad centres extracted from board.svg: circle elements mapped through viewBox 0 0 27957 21193", and it carries an assumption field about the pad-to-label order. tools/import_board.py's own docstring names this file as the anti-pattern it was built to prevent, and then never re-imported it. Replacing it must REPORT the shift per pad rather than assert one: a large shift is the assumed silkscreen order being caught, and that is worth seeing either way.

THE CAPTION IS A SEPARATE LIE AND IS IN SCOPE. board3d-panel.js's FOOTPRINT_CAPTION is one fixed string shown for every board with no model, and it says "Every pad position and the outline are the vendor's own KiCad footprint, exact to three decimals." True of the three XIAO ESP32-C3 boards. False of the Arduino Uno, whose outline is a traced drawing -- so today the page states a provenance the board does not have.

TWO SLICES, each verified before the next starts, because this cannot be checked end to end in one pass:

  1. **Geometry.** Multi-element select, merged with the existing pin indices, outline from layer 20. Verified by: 32 pads matched, a printed shift per pad, and the page drawing the real outline. Landed and committed before slice 2 begins.
  2. **Components.** Placements joined to KiCad meshes and composed into a GLB. Verified by: the page drawing a DIP-28, four headers, the barrel jack, two electrolytics and a resonator, in a browser, with the USB-B named as absent.

Done when the Arduino Uno draws a board with components on it, every one of them from a published mesh; its pads come from the vendor's board file with the shift from the traced ones reported; the caption stops claiming a KiCad footprint the Uno does not have; and no height, spacing or position anywhere in the result was typed in from a datasheet.

NOT IN THIS TICKET: any other board's model (the three ESP32-C3s stay on GrabCAD, recorded); a USB-B mesh (none published under a licence this repository can take); and the .sch, which is a netlist and has no geometry in it at all.
