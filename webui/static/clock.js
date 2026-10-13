// OpenHardware — a board that keeps running, so a blink can be watched.
//
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 the OpenHardware authors. See LICENSE.
//
// ## What this solves for its caller
//
// **Turns a board's bounded run request into a run that continues until
// something stops it.** It knows nothing about boards, pads, the DOM or
// `fetch`: it is handed a function that runs some instructions and a function
// that says what time it is, which is what lets `tests/webui/test_clock.py`
// run it under node against a fake server and assert what it *does*.
//
// That is the second file here written without imports for that reason, after
// `wires.js`. The alternative -- a loop inside `emulator.js`, checked by
// grepping `emulator.js` for the word "interval" -- proves nothing about
// whether the loop stops when a program faults.
//
// ## Why the page drives the clock, and nothing steps behind the server
//
// **This repository already answered this question, for the i8086, before the
// boards existed.** `emulator.js`'s `runContinuously` runs that core in
// bounded bursts from the page, and says why in as many words: one long
// request "would hold the connection open for as long as it ran, and there
// would be no moment at which the Stop button could be noticed." The board
// panel simply never got the equivalent.
//
// The measurements agree, and they are the reason no server-side thread was
// written. Against a real socket on 2026-08-27, an Arduino Uno:
//
//     a bare GET /api/board/state       0.95 ms
//     POST run(200,000) + state        76.2 ms  ->  2,625,923 steps/s
//     POST run(50,000)  + state        20.3 ms  ->  2,467,728 steps/s
//     POST run(20,000)  + state         9.2 ms  ->  2,162,408 steps/s
//
// against 2,688,248 steps/s for the same board stepped in-process with no
// server at all. **A loop in the page reaches 97.7% of what the core can do**,
// so the transport buys a thread nothing.
//
// And the design question the handoff posed -- what does a run mean when the
// page can disconnect? -- has no content once the page *is* the loop. Nothing
// outlives the tab, there is no deadline to renew and no stop route to forget,
// and `MAX_RUN_STEPS` keeps the exact property `webui/api.py` wrote it for.
//
// ## What a person sees, and why the rate is not a garnish
//
// A `delay(500)` is emulated to the cycle -- 8,000,000 instructions on a
// 16 MHz Uno, 24,000,000 on a 48 MHz SAMD21, 80,000,000 on a 160 MHz ESP32-C3
// (120,000,000 on the C5's 240 MHz) -- but the wall clock is several times
// slower than the real chip. Those counts are derived from the boards' own
// clocks and `tests/webui/test_clock.py` holds them. The rates below are
// **not held by any test**: one machine's (an 8-thread AMD, Windows), the
// Release core, 2026-10-13, measured through `BoardSession.run` in
// 200,000-instruction ticks like this loop's, and they move with the machine.
// About 3.8 M instructions/s on the C3, so its delay(500) is about 21 s (42x);
// about 3.5 M on the Uno, 2.3 s (4.5x); about 3.2 M on the SAMD21, 7.6 s
// (15x). A 21-second blink with nothing said about it reads as a broken
// sketch. So a run reports the rate it actually reached, and `emulator.js`
// puts it beside the button. The figures this paragraph carried from
// 2026-08-27 (5.4x and 29x) were taken on the Debug core every Windows build
// made until OH-220.
//
// It is deliberately **instructions per second and not a fraction of real
// time**, because the page is not told a board's clock. Where the repository
// records one in a board's module it is `CPU_HZ` in each
// `webui/boards/esp32c*.py` (cited there, with the rate it sets for the
// SYSTIMER) and `F_CPU_HZ` in `atmega328p.py` (which only computes a baud
// divisor). The SAMD21's module, `samd21.py`, records none; its 48 MHz is the
// build's `-DF_CPU` in `webui/compile.py`. None of these reaches the page: no
// route carries a clock, which `emulator.js`'s `runLine` says and what to add
// (OH-221).

/** Instructions per request.
 *
 *  200,000 rather than the 50,000 that would repaint four times as often:
 *  measured above, this reaches 97.7% of the core's maximum rate against
 *  91.8%, and the 13 repaints a second it leaves are already more than a
 *  three-second blink needs. The cost is that a Stop press waits up to one
 *  tick -- 76 ms on an Uno, which is below the threshold of noticing.
 *
 *  It is also the ceiling `webui/api.py` will accept in one call, so a larger
 *  number here would not be a slower repaint, it would be a refusal. */
export const TICK_STEPS = 200_000;

/** A board kept running by whoever is watching it. */
export class Clock {
  /**
   *  `run(steps)` resolves to `{steps, status, detail}` -- exactly what
   *  `/api/board/run` answers. `now()` gives milliseconds. `onTick(report)` is
   *  **awaited**, which is the whole of the back-pressure design: the caller
   *  refreshes and repaints inside it, and cannot fall behind the stepping
   *  because the next tick does not start until it returns.
   *
   *  All three are injected rather than reached for, so that a test can run
   *  this file with no server, no DOM and no real time.
   */
  constructor({ run, now, onTick = async () => {} }) {
    this.run = run;
    this.now = now;
    this.onTick = onTick;
    this._running = false;
    // Both stamped rather than left undefined, so `snapshot()` answers before
    // the first run as well as after it -- 0 steps in 0 seconds at no rate,
    // which is true, where `NaN` seconds would be an arithmetic accident
    // rendered onto the page.
    this._startedAt = 0;
    this._lastAt = 0;
    this._steps = 0;
    this._status = "running";
    this._detail = "";
  }

  get running() {
    return this._running;
  }

  /** Instructions per second over the whole run, or `null` before there is
   *  one.
   *
   *  **Cumulative rather than smoothed over a window**, which is not a
   *  preference: a window needs a length, a length is a number somebody has to
   *  justify, and this reading exists to answer "is this emulator fast or
   *  slow" rather than "is it fast right now". Total over total converges and
   *  has nothing to tune.
   *
   *  `null` and not 0 before any time has passed, because a rate of zero is a
   *  claim that the board is stopped and "not measured yet" is a different
   *  fact. The caller shows nothing rather than a wrong number. */
  get rate() {
    return this._elapsed > 0 ? this._steps / this._elapsed : null;
  }

  get _elapsed() {
    return (this._lastAt - this._startedAt) / 1000;
  }

  /** Everything a caller needs to draw one line about the run. */
  snapshot() {
    return {
      steps: this._steps,
      seconds: this._elapsed,
      rate: this.rate,
      status: this._status,
      detail: this._detail,
      running: this._running,
    };
  }

  /** Run until stopped, faulted, or thrown at. Resolves to the last snapshot.
   *
   *  Three ways out, and each is a different thing to say afterwards:
   *
   *    * `stop()`, which is a person pressing a button;
   *    * a `status` that is no longer `running`, which is the core refusing an
   *      instruction and having composed a sentence about which access at
   *      which address -- reported, never raised, exactly as `BoardSession.run`
   *      decided;
   *    * `run` itself throwing, which is the server gone or the request
   *      refused. That **propagates**: a clock that swallowed a dead server and
   *      sat there looking like a stopped board would be the worst of the
   *      three to debug.
   */
  async start() {
    if (this._running) {
      throw new Error("this clock is already running; stop it first");
    }
    this._running = true;
    this._startedAt = this.now();
    this._lastAt = this._startedAt;
    this._steps = 0;
    this._status = "running";
    this._detail = "";
    try {
      for (;;) {
        const result = await this.run(TICK_STEPS);
        this._steps += result.steps;
        this._lastAt = this.now();
        this._status = result.status;
        this._detail = result.detail;

        // Before the stop checks, so the final state of a program that just
        // faulted is drawn. A board that halts on its last instruction would
        // otherwise leave the page showing the instruction before it.
        await this.onTick(this.snapshot());

        // `_running` is re-read here rather than at the top of the loop
        // because `stop()` can land during either await above, and a tick that
        // has already been paid for should not be followed by another.
        if (!this._running) break;
        if (result.status !== "running") break;
      }
    } finally {
      this._running = false;
    }
    return this.snapshot();
  }

  /** Ask it to stop. Takes effect at the end of the tick already in flight,
   *  which is why `TICK_STEPS` is a latency and not only a rate. */
  stop() {
    this._running = false;
  }
}
