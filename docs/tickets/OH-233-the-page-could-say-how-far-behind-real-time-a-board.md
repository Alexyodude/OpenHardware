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
