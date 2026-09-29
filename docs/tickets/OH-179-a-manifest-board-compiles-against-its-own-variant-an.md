---
id: OH-179
title: A manifest board compiles against its own variant and shows only its own pads,
  not a XIAO sibling's
status: open
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-179-*
---

Part of OH-174, found by OH-176. The page picks a board's compile recipe and its pin module by chip. For the XIAO boards that was the same thing as picking by board. For the SparkFun Thing Plus ESP32-C6 it is not: per OH-176's report, the page would build a sketch for it with the XIAO ESP32-C6 variant and list XIAO labels such as D0 and LED as its on-board pins. Those are another board's pins presented as this one's.

Also from OH-176: the board file's `image.file` names an SVG that is not generated. Nothing reads the field today, and a field naming a file that does not exist is still a false statement in the file.

Make both follow the board, not the chip: a board from the manifest compiles against its own variant and shows only its own pads. Where the board has no variant the compiler knows, refuse with a message naming what is missing, rather than falling back to a sibling's. Decide `image` for manifest boards: generate the outline as the XIAO importer does, or drop the field for them and say why.

Before claiming this works on the page, check it against a running server, not only the code (the 2026-09-06 handoff records a report that was true of the source tree and false of the process the user was looking at).

Done when the pilot compiles against `sparkfun_esp32c6_thing_plus` or is refused naming it, the pin view lists the pilot's 28 pads and no XIAO label, and a test fails if either regresses.

**Paths this will need**, claimed when the ticket is started (they are held by other tickets at filing): `webui/compile.py`, `webui/api.py`, `tests/webui/test_compile.py`.
