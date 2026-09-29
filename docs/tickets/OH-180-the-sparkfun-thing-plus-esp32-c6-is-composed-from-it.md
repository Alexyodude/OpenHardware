---
id: OH-180
title: The SparkFun Thing Plus ESP32-C6 is composed from its own EAGLE board file,
  as the Uno is
status: in-review
priority: P2
created: '2026-09-29'
touches:
- docs/tickets/OH-180-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/eagle.py
---

Part of OH-174. The SparkFun Thing Plus ESP32-C6 draws an extruded footprint, so its model layer fails in the OH-175 scorecard. SparkFun publishes no mesh in the repository the registry fetches, and does publish its EAGLE board file, which is exactly the Arduino Uno's situation. The Uno is composed from its `.brd` by an entry in `COMPOSITIONS` in tools/compose_board_3d.py.

Add the pilot as a composition from the same `.brd` and the same header elements its manifest row selects, so the model and the pad map are centred on the same pads. Every value the entry needs that the `.brd` does not state (thickness, mask colour) either cites where it was read or is marked a judgement, as `BOARD_MASK` is. Parts that cannot be drawn are refused with a reason and counted, as for every other composed board.

Better still if the entry is derived from the manifest row rather than restated in a second table: a board whose row exists and whose layout is EAGLE or KiCad should not need a second hand-written entry to be composed. If that is more than this ticket, say so and leave the restatement guarded by a test that the two agree.

**Claim conflict.** tools/compose_board_3d.py and its tests are claimed by OH-163 (open, unheld). Whoever takes this ticket coordinates: either OH-163 is taken and finished first, or its claim is narrowed. Do not edit the file under this ticket while OH-163 claims it.

Done when the pilot draws a composed model, the scorecard's model layer reads composed for it, and the refusal count for its parts is printed.

**Note 2026-09-29:** 2026-09-29, lane3 (local, not merged): widened from the SparkFun pilot to all three manifest boards (899b916). Each row of tools/board_manifest.py is composed by `manifest_composition`: the row's own .brd, centred on the elements the row selects; nothing restated except what a row cannot carry (MANIFEST_STATED). Colour: SparkFun's .brd states red twice, a tDocu note ('Soldermask: Red') and a manufacturing-preview mask of 0xC8FF0000, drawn as that preview draws it over the file's substrate; both Adafruit files carry 0xC8008000, the Uno file's own unset value, so they take BOARD_MASK as a judgement. Thickness: SparkFun's note states 1.6 mm; the Adafruit design rules are the Uno's stack, so the Uno's 1.6 is reused. Tests read every figure the sources quote back out of the files. The two ESP32-C6 modules are Espressif's own STEP and footprint (pinned commit), placed over their own pads by `pads_origin`; every other part is a KiCad model or refused in ABSENT with what was listed. Two underside bugs the Uno never exercised were fixed on the way (tools/eagle.py claimed for it): a mirrored element's surface pads stayed on the top face, and `place` stood a mirrored part on top of the board. What each board draws and refuses: `python tools/compose_board_3d.py --check`; the model column: `python tools/inventory.py`.

BLOCKER: tools/import_3d_model.py needs three rows added to COMPOSED, and claiming that file for OH-180 was denied by the permission check, so it was not edited:
    ("SparkFun Thing Plus ESP32-C6", "ESP32-C6", "SparkFun-Thing-Plus-ESP32-C6"),
    ("Adafruit QT Py ESP32-C3", "ESP32-C3", "Adafruit-QT-Py-ESP32-C3"),
    ("Adafruit Feather ESP32-C6", "ESP32-C6", "Adafruit-Feather-ESP32-C6"),
Until they are in, tests/rules/test_compose_board_3d.py::test_the_two_lists_of_composed_boards_agree fails on lane3, and `python tools/import_3d_model.py --all` rewrites index.json without the three boards (the composer's own run writes them back). Left for OH-163 item 2: the red mask and Espressif's module colours fall to DEFAULT_FINISH. On close, tools/compose_board_3d.py, tests/rules/test_compose_board_3d.py and tools/import_3d_model.py go back to OH-163.
