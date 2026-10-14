---
id: OH-233
title: 'The page could say how far behind real time a board runs, but no route sends
  it the board''s clock: as_json gains cpu_hz'
status: open
priority: P3
created: '2026-10-13'
---

OH-221's step 3, decided and left (2026-10-13): the page shows "N steps/s" beside the run button, and for a board whose description records a clock it could say how far behind real time that is -- a C3's delay(500) takes about 21 s of wall time on the Release core on one machine (webui/static/clock.js holds the dated measurement). It does not, because no route sends the page a clock: `/api/board/load` answers `BoardSession.as_json` (board, chip, core, format, bytes, entry, notes) and `/api/board/run` answers steps, status and detail.

STEPS:
1. `BoardSession.as_json` in webui/api.py gains `cpu_hz`: the board module's `CPU_HZ` (esp32c3/c5/c6) or `F_CPU_HZ` (atmega328p), the SAMD21's from the build's `-DF_CPU` in webui/compile.py, and null where none is recorded (e.g. the RP2040) -- read, not listed by hand.
2. emulator.js's `runLine` prints "about 1/N of real time" from the measured rate and `cpu_hz`, and nothing where `cpu_hz` is null; the comment at its LEFT paragraph (emulator.js ~876-890) is replaced by what it now does.
3. Tests: the route's `cpu_hz` for one board of each kind and a null, each seen to fail first; a page test that the line appears only with a clock.

Claims: webui/api.py is OH-172's (lent to OH-161), webui/static/emulator.js OH-221's (done); borrow when this starts.

**Note 2026-10-14:** 2026-10-14, from OH-232's review: when a route gains cpu_hz, also give the page the board's own retired count. BoardSession.retired (webui/api.py ~1394, incremented ~1436 and ~1617) is authoritative but only the /api/board/drive reply carries it (emulator_server.py ~682). OH-232 made the top bar's counter add up run replies on the page (a base kept across Run presses, plus each step's count) because webui/api.py and emulator_server.py are OH-161's and were changing in lane2. Putting 'retired' in state() lets renderBoardState write the counter directly and retires the page's arithmetic and its races. Do it after OH-161's slice 1a merges.
