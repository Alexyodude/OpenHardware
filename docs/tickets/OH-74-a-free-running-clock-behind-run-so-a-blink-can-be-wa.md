---
id: OH-74
title: A free-running clock behind Run, so a blink can be watched
status: open
priority: P2
created: '2026-08-27'
touches:
- webui/static/clock.js
- webui/static/emulator.js
- webui/static/emulator.html
- webui/static/emulator.css
- tests/webui/test_clock.py
---

MEASURED FIRST, AND THE MEASUREMENT OVERTURNS THE HANDOFF'S FRAMING. docs/HANDOFF_2026-08-27_the-bench.md section 6.1 says "what is missing is a server side that keeps stepping, not a UI", and offers three server designs to weigh: a deadline renewed on each poll, a budget-per-poll, or a background thread with a stop route. All three put the loop behind HTTP because the transport was assumed to cost something. It does not. Measured 2026-08-27 against a real socket on 127.0.0.1:8099, median of twelve rounds:

  a bare GET /api/board/state       0.95 ms
  POST run(200,000) + state        76.2 ms  -> 2,625,923 steps/s,  13.1 repaints/s
  POST run(50,000)  + state        20.3 ms  -> 2,467,728 steps/s,  49.4 repaints/s
  POST run(20,000)  + state         9.2 ms  -> 2,162,408 steps/s, 108.1 repaints/s

against 2,688,248 steps/s for the same board stepped in-process with no server at all. So a loop in the PAGE issuing run(200,000) back to back runs the board at 97.7% of the maximum the core can reach, and there is no rate argument anywhere for a server-side thread.

THE DESIGN QUESTION DISSOLVES RATHER THAN BEING ANSWERED. "What does a run mean when the page can disconnect" only has content if something is still running once the page is gone. If the page IS the loop, nothing outlives the tab, MAX_RUN_STEPS keeps the exact property it was written for -- webui/api.py:689, "without a ceiling one request pins the caller" -- and there is no thread, no deadline, no stop route and no orphaned board to reason about. This is the simplest thing that satisfies the requirement, and it deletes a lifecycle rather than adding one.

A BLINK IS WATCHABLE ON ONE BOARD AND BARELY ON THE OTHER. Measured end to end on the pad a person is actually looking at, four transitions each, discarding the first:

  Arduino Uno        8,000,000 steps per half period    2.98 s of wall clock
  XIAO-SAMD21-DIP   24,000,000 steps per half period   14.5 s of wall clock

Both are exactly clock x 0.5 s -- 16 MHz and 48 MHz -- so the emulated delay is right to the cycle and it is the WALL CLOCK that is slow: 5.4x slower than a real Uno, 29x slower than a real SAMD21. A 29-second "blink" with nothing said about it reads as a broken emulator or a broken sketch. That is this repository's recurring defect in a new place -- the page saying something untrue by saying nothing -- so the rate is part of the feature and not a garnish. The clock reports instructions per second, cumulative over the run, beside the button.

WHAT IS NOT ON THE WIRE AND IS NOT BEING INVENTED. Only the ATmega328P names a nominal clock -- webui/boards/atmega328p.py:287, F_CPU_HZ = 16_000_000 -- and it exists solely to compute a baud divisor at :498. The SAMD21 and the RP2040 name none. So the page can honestly say "2,600,000 instructions/s" on every board and cannot honestly say "1/29 of real time" on any board but one. Putting a nominal clock on every chip description is a board-contract change and its own ticket.

THE HANDOFF IS ALSO WRONG THAT THE PAGE ALREADY POLLS. Section 6.1 cites webui/static/emulator.js:909 as "ALREADY polls /api/board/state". It does not: that line sits inside renderBoardState, which runs once per Build and once per Run press. Nothing in webui/static/ contains a poll loop -- no setInterval, no chained setTimeout -- and webui/static/board3d-panel.js:220 describes the intent in a comment, "many times a second", that nothing fulfils. The repaint PATH is real and reusable, which is the useful half of the claim. The loop is not there.

THE LOOP IS ARITHMETIC IN A FILE WITH NO IMPORTS, following wires.js and for the same reason. webui/static/clock.js takes an injected run function and an injected now, so tests/webui/test_clock.py can run the real file under node against a fake server and assert what it DOES -- that it never has two runs in flight, that a fault stops it, that Stop stops it, that the rate is total steps over total wall clock -- rather than grepping emulator.js for the word "interval".

Done when pressing Run once on an Arduino Uno wired to a 5 mm LED makes that LED blink with no further input; the same button then reads Stop and stops it; a program that faults stops the clock and says which access at which address; the achieved rate is on screen; and tests/webui/test_clock.py runs the real clock.js under node.

NOT IN THIS TICKET, each for a stated reason: a nominal clock per chip, above; any server-side stepping, measured unnecessary above; and making the core faster -- core/avr/abi.py:115 exposes avr_step and nothing bulk, so every single instruction crosses ctypes, and a C-side run(n) is a core change with its own ticket.
