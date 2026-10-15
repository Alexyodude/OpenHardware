---
id: OH-233
title: 'The page could say how far behind real time a board runs, but no route sends
  it the board''s clock: as_json gains cpu_hz'
status: in-progress
priority: P3
created: '2026-10-13'
touches:
- webui/static/clock.js
- tests/webui/test_clock.py
- webui/api.py
- webui/static/emulator.js
- tests/webui/test_board_run.py
---

OH-221's step 3, decided and left (2026-10-13): the page shows "N steps/s" beside the run button, and for a board whose description records a clock it could say how far behind real time that is -- a C3's delay(500) takes about 21 s of wall time on the Release core on one machine (webui/static/clock.js holds the dated measurement). It does not, because no route sends the page a clock: `/api/board/load` answers `BoardSession.as_json` (board, chip, core, format, bytes, entry, notes) and `/api/board/run` answers steps, status and detail.

STEPS:
1. `BoardSession.as_json` in webui/api.py gains `cpu_hz`: the board module's `CPU_HZ` (esp32c3/c5/c6) or `F_CPU_HZ` (atmega328p), the SAMD21's from the build's `-DF_CPU` in webui/compile.py, and null where none is recorded (e.g. the RP2040) -- read, not listed by hand.
2. emulator.js's `runLine` prints "about 1/N of real time" from the measured rate and `cpu_hz`, and nothing where `cpu_hz` is null; the comment at its LEFT paragraph (emulator.js ~876-890) is replaced by what it now does.
3. Tests: the route's `cpu_hz` for one board of each kind and a null, each seen to fail first; a page test that the line appears only with a clock.

Claims: webui/api.py is OH-172's (lent to OH-161), webui/static/emulator.js OH-221's (done); borrow when this starts.

**Note 2026-10-14:** 2026-10-14, from OH-232's review: when a route gains cpu_hz, also give the page the board's own retired count. BoardSession.retired (webui/api.py ~1394, incremented ~1436 and ~1617) is authoritative but only the /api/board/drive reply carries it (emulator_server.py ~682). OH-232 made the top bar's counter add up run replies on the page (a base kept across Run presses, plus each step's count) because webui/api.py and emulator_server.py are OH-161's and were changing in lane2. Putting 'retired' in state() lets renderBoardState write the counter directly and retires the page's arithmetic and its races. Do it after OH-161's slice 1a merges.

**Note 2026-10-15:** 2026-10-15: taken in this session's lane4 for steps 1-3; borrows webui/api.py, webui/static/emulator.js, webui/compile.py and tests/webui/test_board_run.py from OH-161, claims webui/static/clock.js and tests/webui/test_clock.py. The retired-count note of 2026-10-14 is not in this pass.

**Note 2026-10-15:** 2026-10-15: steps 1-3 done in c7d7592. BoardSession.cpu_hz (webui/api.py) reads the board module's CPU_HZ or F_CPU_HZ, else compile.f_cpu_hz(board) (the recipe's -DF_CPU, SAMD21), else null (RP2040); as_json carries it, so /api/board/load, load-artefact and compile's board all do. runLine (emulator.js) prints ', about 1/N of real time' with N = cpu_hz / measured rate: nearest whole number from 10 up, one decimal below, 'about real time or faster' under 1.5; nothing where cpu_hz is null or absent. The arithmetic is in emulator.js, not clock.js, because clock.js is handed no board and window.BoardClock is set in emulator.html (unclaimed). Tests: test_the_load_reply_carries_the_boards_clock_where_one_is_recorded (C3, Uno, SAMD21, RP2040 null) and test_the_run_line_says_how_far_behind_real_time_only_where_a_clock_is_known, each seen to fail first. The retired-count note of 2026-10-14 is still open. Release the borrowed files back to OH-161 and drop the clock.js/test_clock.py claims when this closes.

**Note 2026-10-15:** 2026-10-15: review follow-ups done. The N in the run line is cpu_hz over the measured rate, which presumes one retired instruction per cycle. That is exact for the ESP32s (esp32c3/c5/c6.py SYSTIMER_INSTRUCTIONS_PER_TICK = CPU_HZ // SYSTIMER_HZ), and is the model's own clock for the Uno and the SAMD21, whose silicon averages more than one cycle per instruction, so on those two a real chip is slower than the model's clock says and 'about 1/N of real time' is N against the model's cycle, not against silicon.

**Note 2026-10-15:** 2026-10-15: the cpu_hz route test now ends SKIPPED, naming the kinds it matched and the images missing, when it could check only some kinds; a full run passes.

**Note 2026-10-15:** 2026-10-15: steps 1-3 merged to master; returns webui/api.py, webui/static/emulator.js, webui/compile.py and tests/webui/test_board_run.py to OH-161. Open for the 2026-10-14 note (the board's own retired count in state()).

**Note 2026-10-15:** 2026-10-15: the 2026-10-14 note taken in lane4: borrows webui/api.py, webui/static/emulator.js and tests/webui/test_board_run.py from OH-161.

**Note 2026-10-15:** 2026-10-15: the 2026-10-14 note done in 6af5c15. BoardSession.state() carries retired (webui/api.py), so /api/board/state and /api/board/step answer the board's own count; renderBoardState writes the top bar's counter from it and showBoardSteps throws, naming the value, on a reply with no integer. Gone from emulator.js: boardSteps, stepsBefore, the sum in the run tick and in stepLoadedBoard, and the post-load showBoardSteps(0) calls (the state read after each load answers 0); the pre-load clear for a refused load stays. The run and step replies need no retired: the page follows each with a state read. A run of one then the state read stays the step's shape (test_editor.py pins it); test_board_session_fault.py's PAGE_STUBS still declares let boardSteps, now unused and harmless, and is not this ticket's. Tests: test_the_state_reply_carries_the_boards_own_retired_count (route) and the own scenario of test_the_top_bars_counter_shows_the_boards_instructions (page, a fake board that counts steps the page never saw), each seen to fail first. run() adds its taken count after the loop, so a non-Abi exception out of the core mid-run loses that run's count from retired; nothing raises one today. Release webui/api.py, webui/static/emulator.js and tests/webui/test_board_run.py back to OH-161 and drop the clock.js/test_clock.py claims on close.

**Note 2026-10-15:** 2026-10-15: review fix in the commit before this note: showBoardSteps(state.retired) is now the last line of renderBoardState, so a state answer with no retired draws the pc, the watch note, the pins and the toolbar and then throws, naming the field and the value; test_clock.py's counter test has the case (seen to fail with the throw mid-function: where '0000:0000', machine 'i8086').
