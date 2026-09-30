---
id: OH-189
title: 'The Pro Micro ESP32-C3 and Qwiic Pocket ESP32-C6 composed whole: their own
  colour and thickness, every part drawn or reasoned'
status: in-progress
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-189-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
---

Part of OH-174, from OH-188. OH-188 made the SparkFun Pro Micro ESP32-C3 and the SparkFun Qwiic Pocket ESP32-C6 manifest rows with geometry, pins and runs, and left the model layer to the composer's owner. With OH-186's derived COMPOSED list, both boards compose with no edit, and OH-188 reports four things still wrong with the result:

1. Neither board has a MANIFEST_STATED entry, so both are drawn in the default mask colour at 1.6 mm, and test_a_manifest_boards_colour_is_read_where_its_file_states_one and test_a_manifest_boards_thickness_is_its_own_note_or_the_unos_stack fail. OH-188's report records board notes stating a red mask and a thickness (0.8 mm on the Pro Micro, 1.6 mm on the Pocket) and preview colours; read them from the files, as the Thing Plus's are read, rather than from that report.
2. Most placements on both boards are neither drawn nor refused with a reason: the modules (the Pro Micro's ESP32-C3-MINI-1; the Pocket's C6-MINI-1 under SparkFun's own package name), the pin headers, the 0402 passives and the test points. Each is drawn from a published model or refused with its own reason, and test_each_board_explains_the_parts_it_leaves_off holds both boards.
3. The refusal texts printed for J1 and J5 are the Thing Plus's wording; each board's refusal names its own part.
4. Passives follow OH-187's rule for kind.

Run after OH-187, on a branch that carries OH-188's rows. Done when both boards' model cells read composed on master with every placement drawn or reasoned, their own colour and thickness, and the composer and importer test files pass.

**Note 2026-09-30:** 2026-09-30, lane2 (local, not merged): 6c46fa7 and 9a48dca. Colour and thickness from each board's own file: the Pro Micro's layer-51 note reads 'Board thickness: 0.8mm' and 'Soldermask: Red', its preview mask 0xC8AA0000 over substrate 0xFF786E46; the Pocket's note 1.6mm and Red, mask 0xC8FF0000; both MANIFEST_STATED entries are read back by the colour and thickness tests (red with the Pro Micro at 1.6 mm, the Pocket at 0.8, the Pro Micro in the Pocket's red or in BOARD_MASK). Rows: 0402-TIGHT resistor and capacitor, chosen by the stated kind; Espressif's ESP32-C3-MINI-1 and ESP32-C6-MINI-1 STEP and footprint at the pinned commit (KiCad's RF_Module has neither), placed by pads_origin, the Pocket's mirrored under the board as its file places it, a half turn refused by silk_miss at 5.23 and 5.30 mm; the Pro Micro's JST04_1MM_VERT as KiCad's vertical BM04B-SRSS-TB, pin 1 at -x in both, counted as a turn nothing can see. Bodyless: 1X09_CASTELLATED, 1X06_NO_SILK (no PROD_ID where every fitted part has one), USB-SOLDER-PADS, PAD.03X.05, PAD.03X.03. The Thing Plus's USB-C, JST-2-SMD, FIDUCIAL-MICRO and both jumper reasons now describe SparkFun's land (they named J2, J3, I2C and the jumpers on the Thing Plus), so each board's absent line names its own part; the Thing Plus's drawn list is unchanged and only those five reason lines moved. Pro Micro: drawn 19, refused 1 (J1 USB-C), bodyless 17, no model 0. Pocket: drawn 30, refused 3 (J1 USB-C, J5 battery socket, C6 DNP), bodyless 14, no model 0. EXPLAINS: Pro Micro {USB-C}; Pocket {USB-C, JST-2-SMD, 1X06_NO_SILK} (red without the header holes' reason). REFUSED_BY_SCHEMATIC: Pro Micro none, Pocket C6. The diode band test holds the Pocket's D3. Uno, XIAO, QT Py, Feather and KB2040 --check output unchanged. TWINS in lane2: before 11 of 32 (model 27, 4 not built here), after composing all six manifest boards 14 of 32, model 31; Pro Micro file/composed/12+1/13/ESP32-C3, Pocket file/composed/8/8/ESP32-C6. Composer and importer rule files under miniconda: 216 passed. Full default suite in lane2: 2365 passed, 36 skipped, 2 failed -- the OCP pair (OH-163); the four composer tests OH-188 tripped pass.
