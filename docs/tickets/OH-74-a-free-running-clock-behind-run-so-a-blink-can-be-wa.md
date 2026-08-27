---
id: OH-74
title: A free-running clock behind Run, so a blink can be watched
status: done
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

**Note 2026-08-27:** CLOSED 2026-08-27 in 36a645a. Every clause of the Done-when, and the interesting part is how much SMALLER this turned out to be than the handoff predicted.

TWO OF THE HANDOFF'S PREMISES WERE WRONG, and measuring first is what found both. Section 6.1 said 'what is missing is a server side that keeps stepping, not a UI' and offered three server designs to weigh. All three assumed the transport cost something. It does not: a bare GET /api/board/state is 0.95 ms, and run(200,000) + state is 76.2 ms, which is 2,625,923 steps/s against the 2,688,248 the same board reaches in-process with no server at all. A loop in the PAGE runs at 97.7% of the core's maximum, so a thread, a renewed deadline and a budget-per-poll would each add a lifecycle that outlives the tab in exchange for nothing. The second wrong premise: the handoff cited emulator.js:909 as ALREADY polling /api/board/state. It does not -- that line is inside renderBoardState, which runs once per Build and once per Run press, and nothing in webui/static/ has a poll loop at all. The repaint PATH was real and is reused; the loop was never there.

THE DESIGN QUESTION DISSOLVED RATHER THAN BEING ANSWERED. 'What does a run mean when the page can disconnect' has content only if something is still running once the page is gone. The page IS the loop, so nothing outlives the tab, there is no stop route to forget, and MAX_RUN_STEPS keeps the exact property webui/api.py:689 wrote it for.

AND THIS REPOSITORY HAD ALREADY DECIDED IT, which is the thing worth carrying forward. emulator.js:200's runContinuously drives the i8086 from the page in bounded bursts and says why in as many words: one long request 'would hold the connection open for as long as it ran, and there would be no moment at which the Stop button could be noticed.' Written before the boards existed; the board panel simply never got the equivalent. Two copies of the shape now and NOT unified -- the house rule is to merge on the third, and the board's version does more (a rate, a fault detail, a reload interlock) for different reasons.

A BLINK IS WATCHABLE ON ONE BOARD AND BARELY ON THE OTHER, measured end to end on the pad a person actually looks at, four transitions each:
  Arduino Uno       8,000,000 steps per half period    2.98 s wall
  XIAO-SAMD21-DIP  24,000,000 steps per half period   14.5 s wall
Both are exactly clock x 0.5 s -- 16 MHz and 48 MHz -- so the emulated delay is right to the cycle and it is the WALL CLOCK that is 5.4x and 29x slow. A 29-second blink with nothing said about it reads as a broken sketch, so the rate is on screen and is part of the feature. Instructions per second and NOT a fraction of real time: only the ATmega328P records a nominal clock (F_CPU_HZ at atmega328p.py:287, and only to compute a baud divisor at :498), so '1/29 of a real SAMD21' would mean inventing the 48 MHz. A nominal clock per chip is a board-contract change and its own ticket.

THE LOOP IS A FILE WITH NO IMPORTS, after wires.js and for the same reason: a run loop's whole content is WHEN IT STOPS, and that cannot be asserted by grepping emulator.js. clock.js takes an injected run and an injected now, so tests/webui/test_clock.py hands it a board that faults on the third tick and asserts it stops on the third. Thirteen tests. Eight mutations, all caught, and after one round of fixing the mutations themselves each is caught by the test written for it -- the first attempt had one mutation that merely made clock.js a syntax error, which catches everything and proves nothing.

THE FAKE CLOCK IS WHY THE RATE ASSERTIONS ARE EXACT. fakeNow advances a fixed number of milliseconds per reading, so 1,000 steps per tick at 100 ms per tick is 10,000/s however many ticks are taken. Real time would have made every one of those a tolerance, and a tolerance wide enough to survive a loaded machine is wide enough to miss the bug.

A RELOAD WAITS FOR THE TICK IN FLIGHT, which was a bug being introduced rather than one found. stop() takes effect at the END of the current tick, so loadBoardImage, loadArtefact and buildSketch AWAIT the clock rather than merely asking it -- otherwise one more 200,000-step request lands on the freshly loaded image, and the page says 'entered at 0x00000000' beside a board that has already run past it. Asserted per FUNCTION rather than by counting a string, so a fourth route that loads an image cannot leak past it.

A TEST CAUGHT A COMMENT, AND THE TEST WAS RIGHT TO. test_the_page_asks_the_renderer_for_nothing_it_cannot_do_without scans emulator.js for window.boardPins and requires every one to use the optional chain. It does not exempt comments, and a sentence I wrote mentioning the hook by name read to it as an unguarded call. Reworded rather than widening this ticket into tests/webui/test_board3d.py, and the comment now says so. Whoever next writes prose in that file should know it is scanned.

VERIFIED IN A BROWSER, which is the acceptance test and it is visual: an Arduino Uno wired to a 5 mm LED on pad 13, ONE press of Run, 655,000,000 instructions at 2,503,759/s with nothing touched, pin 13 toggling every 3.25 s and the LED lighting and going dark with it (.playwright-mcp/clock-blink-high.png and clock-blink-low.png). Stop landed exactly one tick later -- 655,000,000 to 655,200,000, precisely TICK_STEPS -- and the counter then sat still for 2.5 s. Zero console messages at warning level or above.

NOT DONE, each for a stated reason: the deterministic 200,000-step advance that Run used to be is gone, because Run is a toggle now and the user chose that over a third control; no nominal clock per chip, above; and the core is not faster -- core/avr/abi.py:115 exposes avr_step and nothing bulk, so every instruction crosses ctypes, and a C-side run(n) would raise the ceiling this whole ticket runs against. That is a core change and its own ticket.
