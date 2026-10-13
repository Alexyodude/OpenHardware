---
id: OH-232
title: The top bar's step counter reads the 8086 session's count, so it says 0 steps
  beside a board that is running
status: open
priority: P3
created: '2026-10-13'
---

Seen by OH-161 step 4 on the page (2026-10-13, lane2's server, XIAO ESP32-C3 running a sketch): the top bar's step counter read "0 steps" throughout while the board ran and its console printed. Traced on master (bf9ab71): `#counter` (webui/static/emulator.html:107, title "instructions executed") is written only by `renderStatus` (webui/static/emulator.js:169, `state.steps`), which draws the 8086 session's state; the board's run path (the run clock's tick and `/api/board/run`, which answers `steps`) never writes it. So for every board the counter shows the 8086 session's count -- 0 when no 8086 program ran -- beside a board that has retired millions of instructions.

STEPS:
1. Decide what the counter shows while a board is loaded: the board session's retired count (as `/api/board/run` and `/api/board/state` report it), and the 8086's only when the 8086 view is the one shown.
2. Write it from the board's run and step replies, and clear it on a board load.
3. A page test that loads a board, runs it, and sees the counter show the board's count, seen to fail on today's code.

Claims: webui/static/emulator.js is OH-221's (in review); borrow it when that closes.
