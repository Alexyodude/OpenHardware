---
id: OH-72
title: The vendor's own 3D model, tessellated at import time, so a board is a board
status: done
priority: P2
created: '2026-08-26'
touches:
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
- webui/static/board3d.js
- webui/static/board3d-panel.js
- webui/models/*
- webui/pinmap.py
- webui/emulator_server.py
- webui/static/models/*
- webui/static/emulator.css
- webui/static/emulator.html
- .gitignore
- CLAUDE.md
---

THE PIN VIEW DRAWS A FOOTPRINT EXTRUDED AND SAYS SO. OH-30 built it that way on the evidence available at the time, which was OH-29's census: a full git ls-tree of Seeed-Studio/OSHW-XIAO-Series found 0 .step, 0 .stp and 0 .wrl, and OH-29 recorded that Seeed publishes no board 3D at all.

THAT CENSUS LOOKED IN THE WRONG PLACE AND THIS IS THE CORRECTION. Seeed publishes a 3D model per board on the WIKI, not in the git repository. Measured 2026-08-26 by HTTP HEAD against files.seeedstudio.com:

  18,255,477  Seeeduino-XIAO/res/seeeduino-xiao-samd21-3d-model.zip
   3,399,090  XIAO-RP2040/res/seeed-studio-xiao-rp2040-3d-model.zip
   4,382,912  SeeedStudio-XIAO-ESP32S3/res/seeed-studio-xiao-esp32s3-3d_model.zip
   8,849,412  XIAO-BLE/seeed-studio-xiao-nrf52840-3d-model.zip

AND THE FOOTPRINTS ALREADY NAMED THEM, which is what makes this certain rather than a guess. Every .kicad_mod in third_party/seeed-xiao carries a (model "${AMZPATH}/3dmodels/AMz3D.3dshapes/...step") line naming five files -- Seeeduino XIAO SAMD21 v4.step, Seeed Studio XIAO RP2040 v26.step, Seeed Studio XIAO-ESP32-C3.step, XIAO-ESP32S3 v2.step and XIAO-nRF52840 v15.step. The first of those is EXACTLY the filename inside the SAMD21 zip above. AMZPATH is a KiCad environment variable pointing at a library the vendor does not ship, which is why the census saw nothing.

THE ESP32-C3 IS THE ONE GAP AND IT MUST BE SAID RATHER THAN SKIPPED. Its wiki links GrabCAD, not files.seeedstudio.com -- a third-party host behind a login with its own terms. So three runnable boards (XIAO-ESP32-C3-DIP, -DIP-SMD, -SMD) get no model, and the panel must go on saying footprint for them rather than quietly showing a different board's.

WHAT IS IN THE FILE, measured rather than assumed, for the SAMD21:

  AP214, 9,060,867 bytes, 116,841 entities, ST-DEVELOPER v19 out of Fusion
  2,228 faces: 1,078 PLANE, 992 B_SPLINE_SURFACE_WITH_KNOTS, 152
    CYLINDRICAL_SURFACE, 2 TOROIDAL_SURFACE
  no tessellated entities of any kind, and NO PCURVE, SURFACE_CURVE or
    DEFINITIONAL_REPRESENTATION -- every edge is 3D only
  5 solids: PCB 21.300 x 17.900 x 1.610 mm centred on the origin; an RF
    shield; a 0.089 mm decal on it; and a USB-C connector that overhangs
    to x 11.950, which is why the assembly bounding box is NOT the board

SO A HAND-WRITTEN TESSELLATOR IS NOT THE ROUTE AND THE NUMBERS SAY WHY. The two large solids are 52% and 47% B-spline, so a planes-and-cylinders mesher would render half of each and produce a board full of holes -- worse than the honest extrusion it replaces. With no pcurves, trimming means projecting 3D edge loops into parameter space by Newton iteration on 992 spline surfaces. That is a CAD kernel.

OPENCASCADE AT IMPORT TIME, chosen by the user 2026-08-26 over writing one. cadquery-ocp is a TOOL dependency and not a runtime one, exactly as tools/gen_avr_corpus.mjs needs node and avr8js: the importer exits 3 and says SKIPPED where OCP is absent, the emitted mesh is committed, and nothing the browser loads gains a dependency. Measured on the SAMD21: all 2,228 faces tessellate, 36,984 triangles and 40,816 vertices at 0.05 mm linear deflection, 0.3 s, about 1.4 MB raw.

COLOURS COME FROM THE FILE AND NOT FROM TASTE. XCAFPrs.CollectStyleSettings_s returns 1,014 styled shapes -- 5 solids and 1,009 faces -- across 16 colours, including #116517 for the PCB, #030303 on 714 faces and #ff9f37 on 176, which is the gold on the castellated pads. A model rendered in one grey would not be the board.

ALIGNMENT IS THE POINT AND OH-29 SAID SO FIRST: the pad at its recorded coordinate has to be the same pad in 3D, or the two views are separate pictures of nothing in particular. The anchor is the PCB solid's own XY extent, not the assembly box, because the USB connector overhangs. The residual against webui/boards/<board>.json must be REPORTED in millimetres rather than asserted to be zero.

Done when XIAO-SAMD21-DIP renders from Seeed's own STEP in the pin view with its pads still on it and the caption no longer claiming a footprint; when the alignment residual is printed in millimetres by the importer and pinned by a test; when the four reachable models are imported and the ESP32-C3's absence is stated in the page rather than inferred from a board that draws differently; and when the importer exits 3 and says SKIPPED with no OCP installed.

**Note 2026-08-27:** CLOSED 2026-08-27 in 5bcac3e. Every clause of the Done-when, and the ticket's own premise was the thing that turned out to be worth the most.

THE CORRECTION HELD AND IT WAS BIGGER THAN THE TICKET SAID. OH-29's census was not sloppy -- it was a full git ls-tree and it was right about the repository. Seeed publishes the models on the wiki, and the .kicad_mod files had been naming them all along through an AMZPATH the vendor does not ship. Four archives verified by HTTP HEAD, and the SAMD21's zip contains the exact string in the footprint, character for character.

THE AXIS DISCOVERY IS THE PART THAT WAS NOT PREDICTED. The ticket described one conversion, Z-up to Y-up. The four files use TWO conventions: SAMD21 and RP2040 are Z-up, ESP32-S3 and nRF52840 are Y-up, and the RP2040's board runs the short way across its own x. The first run reported the ESP32-S3's PCB as 7.300 x 4.200 x 8.940 mm -- a component, picked because the largest-XY-area rule was reading the wrong plane -- and NOTHING THREW. Frame now derives the up axis from the assembly's own thinnest extent, which is a property of a board rather than of a vendor. After the fix all four agree: 21.300 x 17.900, 21.000 x 17.500 and 20.955 x 17.780 twice, with DIP pad margins of 3.025/2.875/2.853 by 1.331/1.131/1.271 mm. Four independent files landing on the same margins is the alignment evidence, and it is stronger than the single number the ticket asked for.

GENERALISATION WORTH KEEPING: a converter that assumes an axis convention fails silently and shows a plausible picture. The check that caught it was printing the PCB extent beside the assembly extent for every file, which cost one line and would have been the last thing added if the ticket had not said to report rather than assert.

HANDEDNESS HAS ITS OWN NAMED FUNCTION for a test reason. A mirrored XIAO still has fourteen pads in two rows and still says SEEEDUINO on it, so it cannot be caught by looking; and frame_for needs a loaded shape, so it cannot be tested where there is no OpenCASCADE. handedness_of is the part that can be, and the test calls it rather than recomputing the parity -- which is the same defect OH-68 and OH-17 both recorded.

THE MESHES ARE NOT COMMITTED and that is a licence decision. Seeed's git repository is MIT and webui/boards/*.json records it; these come from the wiki's file server, which states no licence. rules/licence-hygiene.md section 4 says a dependency in a directory nobody exempted is a question for a person. webui/static/models/ is gitignored, the index degrades to an empty board table and every board draws the footprint, which is the same path the ESP32-C3 takes permanently.

TWO THINGS FIXED HERE THAT THE MODEL MADE VISIBLE, both reported by the user rather than found by a test. The page did not adapt to a wide window: board-run and sketch had no grid-area and fell where the grid put them, so at 2560px a third of the page was blank while the board was drawn in a 900 by 260 letterbox. And the pad markers were posts standing 0.9 units proud -- fine above an invented slab, and a visible mistake once the vendor's own gold castellations were underneath them.

NOT DONE, each for a stated reason: the XIAO ESP32-C3, because Seeed publishes that one on GrabCAD behind a login -- three runnable boards keep the footprint and the caption says so; the Arduino Uno, a different vendor entirely and not looked for; and no hover picking, which is OH-73's because a wire needs one.
