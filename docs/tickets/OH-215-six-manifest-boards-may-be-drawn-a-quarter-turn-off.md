---
id: OH-215
title: Six manifest boards may be drawn a quarter turn off their own pads by the page
status: in-progress
priority: P1
created: '2026-10-09'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

Found by OH-163 step 2's review-fix worker (2026-10-09), from pad positions only; not yet seen in a browser. Six manifest boards may be drawn by the page a quarter turn off their own pads: SparkFun Pro Micro ESP32-C3, Adafruit QT Py ESP32-C3, SparkFun Thing Plus ESP32-C6, SparkFun Thing Plus ESP32-C5, PCBCUPID Glyph Mini RP2040 and Olimex ESP32-C3-DevKit-Lipo.

Their board files' pad maps are taller than wide. `webui/static/board3d.js`'s `placeModel` scales, turns a quarter and centres the composed model onto the pad map; placed that way, none of each board's pads lands on the composer's header pads, while without the quarter turn they land within 0.01 mm (the Glyph Mini within 0.73 mm). So the pin panel's pads and the drawn board would disagree by a quarter turn on exactly these boards, and `carvePins`, which turns metal triangles within 1.1 mm of a pad into a pin, would carve the wrong triangles.

Confirm it first: in the running page (`python webui/emulator_server.py`), load each board and see whether its pads sit on its drawn headers; and from code, read how `placeModel` decides the turn (a pad map's aspect? a rule written for the XIAOs, whose maps are wider than tall?). Then make the turn come from what the board file and the model state, not from a shape heuristic, and hold it with a test that, for every board with a composed model, places the model as the page does and finds each header pad on the model's own pad (the composer knows where its header pads are).

Done when every board's pads land on its drawn pads as the page places them, held by a test over every board, and the six boards are seen right in the page.
