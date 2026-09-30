---
id: OH-193
title: A composer row is held to the vendor's own words, and the manifest boards are
  composed under test
status: open
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-193-*
---

Found by OH-189's review (2026-09-30). Three mutations of the composer's table each compose cleanly and pass the whole suite, putting a false part on a board:

- the ESP32-C3-MINI-1 row pointed at the ESP32-C6-MINI-1 model and footprint;
- the JST04_1MM_VERT row pointed at KiCad's horizontal SM04B model;
- the Pocket's underside module row given flip=True, so the module is drawn on top of the board.

Two gaps let them through. Nothing compares a row's model name with what the vendor's own package and value words state (VERT, a module's chip, a lead count), and no test composes the manifest boards at all: the composer's own turn and silkscreen refusals (a C3-MINI-1 turned 180 misses the vendor's body drawing by 5.23 mm and the composer exits) never run under pytest.

Hold a row to the vendor's words where the words state something checkable, with a closed, pinned vocabulary (orientation words, a module's chip name, a stated lead count), and refuse a row that contradicts them. Compose the manifest boards in the test suite where the inputs and OCP are present, and skip naming what is missing where they are not, so the composer's own refusals reach CI's view.

Done when each of the three mutations above fails a test.
