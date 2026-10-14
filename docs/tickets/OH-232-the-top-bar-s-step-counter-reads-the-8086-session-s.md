---
id: OH-232
title: The top bar's step counter reads the 8086 session's count, so it says 0 steps
  beside a board that is running
status: in-review
priority: P3
created: '2026-10-13'
touches:
- tests/webui/test_clock.py
- tests/webui/test_editor.py
---

Seen by OH-161 step 4 on the page (2026-10-13, lane2's server, XIAO ESP32-C3 running a sketch): the top bar's step counter read "0 steps" throughout while the board ran and its console printed. Traced on master (bf9ab71): `#counter` (webui/static/emulator.html:107, title "instructions executed") is written only by `renderStatus` (webui/static/emulator.js:169, `state.steps`), which draws the 8086 session's state; the board's run path (the run clock's tick and `/api/board/run`, which answers `steps`) never writes it. So for every board the counter shows the 8086 session's count -- 0 when no 8086 program ran -- beside a board that has retired millions of instructions.

STEPS:
1. Decide what the counter shows while a board is loaded: the board session's retired count (as `/api/board/run` and `/api/board/state` report it), and the 8086's only when the 8086 view is the one shown.
2. Write it from the board's run and step replies, and clear it on a board load.
3. A page test that loads a board, runs it, and sees the counter show the board's count, seen to fail on today's code.

Claims: webui/static/emulator.js is OH-221's (in review); borrow it when that closes.


NOTE 2026-10-14 (lane4): done. `#counter` now shows the board's retired count while a board owns the panes. `showBoardSteps` in webui/static/emulator.js writes it: zero at each of the three loads (load, load-artefact, compile), clock total plus the count the clock started from at each run tick, plus one at a step that leaves the board running. `/api/board/state` does NOT carry steps (the ticket's text said it did), so the page adds the run replies up; a step reply carries none either, and a stopped step retires nothing, hence the status test. `renderStatus` never runs over a board: `refresh` returns first while `panes` is not i8086, and `loadSelected` hands the panes back before it redraws. No server change was needed.
Test: tests/webui/test_clock.py::test_the_top_bars_counter_shows_the_boards_instructions runs the real emulator.js under node against a fake page and fetch: load, run three ticks of 1000, step, reload. On the old code it fails: counter reads ['7 steps','7 steps','7 steps','7 steps'] against ['0 steps','3,000 steps','3,001 steps','0 steps']. Not checked in a real browser or against a live XIAO run (no headless browser here).
Counts: test_clock.py 15 passed; with test_emulator.py and test_editor.py 89 passed, 1 failed first time (test_a_state_poll_answers_while_a_build_runs, timing under load; passes alone, also with the change).

NOTE 2026-10-14 (lane4, fix round after review): (1) A step is now `/api/board/run {steps: 1}` and then the state read, and adds that reply's `steps`, so an instruction that retires and then stops the board counts 1 and a refusal 0; the "+1 if running" inference is gone. `/api/board/step` is the same `run(1)` plus the state, so nothing else changed; the cost is two requests, not one, with the clock stopped. test_editor.py's watch-on-step pin now asserts the step's state read goes through `boardStateUrl()`. (2) Run, Stop, Run: `runLoadedBoard` awaits the previous clock's completion before taking the base, and `stopBoardClock` no longer returns early on `running`, which `stop()` clears at once, so a load also waits for the tick in flight. (3) A refused load zeroes the old board's count (only when a board owns the panes); `loadSelected` stops the board clock first, which also stops a board tick from redrawing the board over the 8086's panes. (4) The test now covers Run-Stop-Run, the race with a held tick, scripted step replies (1 running, 1 stopped, 0 stopped), reload through load, load-artefact and compile, a refused load, and the whole route list. Mutants all red: no base, stopped step counted, old inference, no zeroing on compile, no zeroing on artefact (both lines), no wait for the previous clock, no zero on refusal. Zeroing after the artefact call alone is redundant with the one before it, so that single line is not detectable. Retired count in state() is left for OH-233.
