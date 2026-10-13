# OpenHardware — the free-running clock, checked by running it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file runs node
#
# The same reason `tests/webui/test_wires.py` does, and the reason
# `webui/static/clock.js` imports nothing. A run loop's whole content is *when
# it stops*: when a person presses Stop, when the core refuses an instruction,
# when the server goes away. None of that can be asserted by grepping
# `emulator.js` for the word "interval", and all of it can be asserted by
# handing the real file a board that faults on the third tick.
#
# So each test writes a few lines of ES module into `tmp_path`, imports the
# real `clock.js`, prints JSON and asserts on it. It skips where node is
# absent, as `test_wires.py` and `tools/gen_avr_corpus.mjs` do.
#
# ## The two fakes, and why the clock takes them as arguments
#
# `fakeBoard` answers `/api/board/run`'s shape -- `{steps, status, detail}` --
# and records what it was asked for and how many calls were ever in flight at
# once. `fakeNow` advances a fixed number of milliseconds per reading, which
# makes the rate an exact number rather than a range: real time would make
# every assertion here a tolerance, and a tolerance wide enough to survive a
# loaded machine is wide enough to miss the bug.

import json
import pathlib
import shutil
import subprocess
import textwrap

import pytest

from webui.boards import atmega328p, esp32c3, esp32c5

CLOCK = (pathlib.Path(__file__).resolve().parents[2]
         / "webui" / "static" / "clock.js")
EMULATOR = CLOCK.with_name("emulator.js")

#: Handed to every probe. A board that answers instantly and a clock that does
#: not tick would both hide an ordering bug, so the board always yields and the
#: clock always advances.
PRELUDE = """
/** A board that runs `steps` per tick and stops after `faultAfter` of them. */
function fakeBoard({ steps = 1000, faultAfter = null, detail = "" } = {}) {
  const asked = [];
  let inFlight = 0;
  let most = 0;
  return {
    asked,
    get mostInFlight() { return most; },
    async run(count) {
      inFlight += 1;
      most = Math.max(most, inFlight);
      asked.push(count);
      // A real request is not synchronous, and a fake that resolves without
      // yielding cannot show two calls overlapping even when they do.
      await Promise.resolve();
      inFlight -= 1;
      const done = faultAfter !== null && asked.length >= faultAfter;
      return done
        ? { steps, status: "stopped", detail }
        : { steps, status: "running", detail: "" };
    },
  };
}

/** Milliseconds, `step` further on at every reading. */
function fakeNow(step) {
  let at = 0;
  return () => { const was = at; at += step; return was; };
}
"""


def probe(tmp_path: pathlib.Path, body: str) -> dict:
    """Run a fragment against the real `clock.js` under node, and parse it.

    A `file://` URL because node resolves a bare relative path against the
    *entry* module, and the entry module is in a temporary directory that
    knows nothing about this repository.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on PATH; clock.js is a run loop and needs one to "
                    "run")
    if not CLOCK.is_file():
        pytest.skip(f"no {CLOCK}")

    script = tmp_path / "probe.mjs"
    script.write_text(
        f"import {{ Clock, TICK_STEPS }} from {CLOCK.as_uri()!r};\n"
        + PRELUDE + textwrap.dedent(body),
        encoding="utf-8")
    # **Timed out rather than left to run**, unlike `test_wires.py`'s
    # equivalent, and the difference is what is being tested. A rope that is
    # wrong settles into a wrong shape and answers; a run loop that is wrong
    # does not stop, and without a bound here the failure is a node process
    # growing until the machine kills it. Every probe below finishes in well
    # under a second.
    try:
        done = subprocess.run([node, str(script)], capture_output=True,
                              text=True, timeout=60)
    except subprocess.TimeoutExpired as expired:
        raise AssertionError(
            "the clock never stopped: node ran the probe for 60 s and was "
            "killed. Every exit from the loop is broken, not just one."
        ) from expired
    if done.returncode != 0:
        raise AssertionError(f"node exited {done.returncode}\n{done.stderr}")
    # node warns about module type for a file outside any package; the answer
    # is the last line of stdout, so a stray log cannot break it.
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- when it stops ----------------------------------------------------------------


def test_a_clock_runs_until_it_is_stopped(tmp_path):
    """The whole feature in one assertion: Run is pressed once.

    Before this, `#board-go` ran one 200,000-instruction burst and stopped, so
    watching a blink meant pressing it again for every half period -- 40 presses
    for one flash of a `delay(500)` on an Uno.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        clock.onTick = async () => { if (board.asked.length === 25) clock.stop(); };
        const last = await clock.start();
        console.log(JSON.stringify({ ticks: board.asked.length, last }));
    """)
    assert result["ticks"] == 25
    assert result["last"]["running"] is False
    assert result["last"]["steps"] == 25_000


def test_a_clock_stops_when_the_program_faults(tmp_path):
    """A core that refuses an instruction ends the run, and says which.

    `BoardSession.run` reports a fault rather than raising it, on the stated
    reasoning that the message it composed -- which access, at which address,
    from which instruction -- is the most useful thing anyone gets all day.
    A loop that read only `steps` would throw that away and spin for ever on a
    board that had already stopped.
    """
    result = probe(tmp_path, """
        const board = fakeBoard({ faultAfter: 3, detail: "read of 0xffff0000" });
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        const last = await clock.start();
        console.log(JSON.stringify({ ticks: board.asked.length, last }));
    """)
    assert result["ticks"] == 3, "it kept running a board that had stopped"
    assert result["last"]["status"] == "stopped"
    assert result["last"]["detail"] == "read of 0xffff0000"


def test_the_faulting_tick_is_drawn_before_the_clock_gives_up(tmp_path):
    """The last thing a stopped program did is the thing worth looking at.

    Checking `status` before the repaint rather than after would leave the page
    showing the state *before* the fault -- one tick of up to 200,000
    instructions short of the address that actually broke.
    """
    result = probe(tmp_path, """
        const board = fakeBoard({ faultAfter: 2, detail: "bad opcode" });
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        const drawn = [];
        clock.onTick = async (report) => drawn.push(report.status);
        await clock.start();
        console.log(JSON.stringify({ drawn }));
    """)
    assert result["drawn"] == ["running", "stopped"]


def test_a_stop_inside_a_repaint_does_not_start_another_tick(tmp_path):
    """Stop lands during an await, which is where a press almost always lands.

    Both awaits in the loop -- the run and the repaint -- can be where the
    button is pressed, so `running` is re-read after them rather than only at
    the top of the loop.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        clock.onTick = async () => clock.stop();
        await clock.start();
        console.log(JSON.stringify({ ticks: board.asked.length }));
    """)
    assert result["ticks"] == 1


def test_a_dead_server_stops_the_clock_and_is_not_swallowed(tmp_path):
    """A refused request propagates, and leaves the clock stopped.

    A loop that caught this and carried on would show a board that looked
    paused with no reason on screen, which is the hardest of the three ways out
    to debug. `finally` is what guarantees the button goes back to Run.
    """
    result = probe(tmp_path, """
        const clock = new Clock({
          run: async () => { throw new Error("Failed to fetch"); },
          now: fakeNow(100),
        });
        let caught = "";
        try { await clock.start(); } catch (error) { caught = error.message; }
        console.log(JSON.stringify({ caught, running: clock.running }));
    """)
    assert result["caught"] == "Failed to fetch"
    assert result["running"] is False, "a thrown request left the clock running"


def test_a_clock_cannot_be_started_twice(tmp_path):
    """Two loops against one board would interleave requests on one core.

    The button is a toggle so this should not be reachable from the page, and
    it refuses by name rather than trusting that.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        let caught = "";
        clock.onTick = async () => {
          try { await clock.start(); } catch (error) { caught = error.message; }
          clock.stop();
        };
        await clock.start();
        console.log(JSON.stringify({ caught, ticks: board.asked.length }));
    """)
    assert "already running" in result["caught"]
    assert result["ticks"] == 1


# --- how it runs ------------------------------------------------------------------


def test_only_one_run_is_ever_in_flight(tmp_path):
    """One board, one core, one request at a time.

    `webui/emulator_server.py` guards every request with one lock, so
    overlapping runs would not corrupt anything -- they would queue, and the
    Stop press would wait behind all of them. The bound belongs here, where the
    requests are issued.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        clock.onTick = async () => { if (board.asked.length === 40) clock.stop(); };
        await clock.start();
        console.log(JSON.stringify({ most: board.mostInFlight }));
    """)
    assert result["most"] == 1


def test_a_repaint_is_finished_before_the_next_tick_begins(tmp_path):
    """The back-pressure, and the only reason `onTick` is awaited.

    A repaint that is started and not waited for lets the stepping outrun the
    drawing, and the page falls further behind the board for as long as it
    runs. Awaiting it makes the loop go exactly as fast as the slower of the
    two, which is also what makes the reported rate the rate a person sees.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const order = [];
        const clock = new Clock({
          run: async (count) => { order.push("run"); return board.run(count); },
          now: fakeNow(100),
        });
        clock.onTick = async () => {
          order.push("draw-start");
          await new Promise((resolve) => setTimeout(resolve, 1));
          order.push("draw-end");
          if (board.asked.length === 3) clock.stop();
        };
        await clock.start();
        console.log(JSON.stringify({ order }));
    """)
    assert result["order"] == ["run", "draw-start", "draw-end"] * 3


def test_every_tick_asks_for_the_whole_budget(tmp_path):
    """A smaller ask would repaint more often and run slower, both measured.

    200,000 reaches 97.7% of what the core can do against 91.8% at 50,000, and
    leaves 13 repaints a second, which is more than a three-second blink needs.
    """
    result = probe(tmp_path, """
        const board = fakeBoard();
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        clock.onTick = async () => { if (board.asked.length === 4) clock.stop(); };
        await clock.start();
        console.log(JSON.stringify({ asked: board.asked, budget: TICK_STEPS }));
    """)
    assert result["asked"] == [200_000] * 4
    assert result["budget"] == 200_000


# --- what it reports --------------------------------------------------------------


def test_the_rate_is_every_instruction_over_all_the_wall_clock(tmp_path):
    """Cumulative, and exact here because the clock is fake.

    1,000 instructions per tick and 100 ms per tick is 10,000 a second however
    many ticks are taken, which is the property a cumulative rate has and a
    windowed one does not: nothing to tune, and it converges.
    """
    result = probe(tmp_path, """
        const board = fakeBoard({ steps: 1000 });
        const clock = new Clock({ run: board.run, now: fakeNow(100) });
        const seen = [];
        clock.onTick = async (report) => {
          seen.push(report.rate);
          if (board.asked.length === 6) clock.stop();
        };
        const last = await clock.start();
        console.log(JSON.stringify({ seen, last }));
    """)
    assert result["seen"] == [10_000.0] * 6
    assert result["last"]["steps"] == 6000
    assert result["last"]["seconds"] == pytest.approx(0.6)


def test_a_clock_that_has_not_run_reports_no_rate_rather_than_zero(tmp_path):
    """A rate of zero is a claim that the board is stopped.

    "Not measured yet" is a different fact and the page draws nothing for it,
    which is the same distinction every pad in this repository keeps between
    `low` and `unknown`.
    """
    result = probe(tmp_path, """
        const clock = new Clock({ run: async () => {}, now: fakeNow(100) });
        console.log(JSON.stringify({ before: clock.snapshot() }));
    """)
    assert result["before"]["rate"] is None
    assert result["before"]["steps"] == 0
    assert result["before"]["seconds"] == 0, "an unstarted clock reported a duration"
    assert result["before"]["running"] is False


# --- against the server it talks to -----------------------------------------------


def test_the_tick_is_exactly_what_the_server_will_accept(tmp_path):
    """The one invariant that spans the two languages, so it is asserted.

    `webui/api.py` refuses a budget over `MAX_RUN_STEPS` by name. `clock.js`
    asks for `TICK_STEPS` on every single tick, so if either number moves
    without the other the page does not run slowly -- it stops running at all,
    on the first press, with `budget-refused`. Nothing else in either file
    would say so.
    """
    import re
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from webui import api

    source = CLOCK.read_text(encoding="utf-8")
    found = re.search(r"export const TICK_STEPS = ([0-9_]+);", source)
    assert found, "clock.js no longer declares TICK_STEPS where this can read it"
    assert int(found.group(1).replace("_", "")) == api.MAX_RUN_STEPS


def test_every_path_that_replaces_the_image_stops_the_clock_first():
    """Read out of `emulator.js`, because node cannot reach the wiring.

    A clock left running across a load is not a cosmetic problem. `stop()`
    takes effect at the *end* of the tick in flight, so the request already
    issued lands on whatever image the server holds when it arrives -- the new
    one. The page would then say "entered at 0x00000000" beside a board that
    had already run 200,000 instructions past it, and the console would carry
    both programs' output added together.

    Asserted per function rather than by counting occurrences of a string: a
    fourth route that loads an image is exactly the change this exists to
    catch, and a count would pass while the new one leaked.
    """
    import re

    source = (pathlib.Path(__file__).resolve().parents[2]
              / "webui" / "static" / "emulator.js").read_text(encoding="utf-8")
    #: The three routes that call `boards.replace`, from
    #: `webui/emulator_server.py`'s `handle_board_api`.
    replaces = ("/api/board/load", "/api/board/load-artefact",
                "/api/board/compile")

    starts = [(m.start(), m.group(1))
              for m in re.finditer(r"^(?:async )?function (\w+)\(",
                                   source, re.MULTILINE)]
    assert starts, "no top-level functions found in emulator.js"

    guilty = []
    for index, (at, name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(source)
        body = source[at:end]
        loads = [route for route in replaces if f'"{route}"' in body]
        if loads and "stopBoardClock" not in body:
            guilty.append(f"{name} posts {loads} without stopping the clock")
    assert not guilty, "; ".join(guilty)



# --- what the page says about a board's clock (OH-221) -------------------------


def comment_words(path: pathlib.Path) -> str:
    """A source file's words, with the comment markers and the line breaks
    between them gone, so a phrase wrapped over two lines is still a phrase."""
    return " ".join(w for w in path.read_text(encoding="utf-8").split()
                    if w not in ("//", "*"))


def delay_500_steps(description) -> int:
    """Instructions in a `delay(500)` on an ESP32, from the description's own
    SYSTIMER rate: a millisecond is `SYSTIMER_HZ // 1000` ticks, each
    `SYSTIMER_INSTRUCTIONS_PER_TICK` retired instructions (`wiring.c`'s
    `delay()` waits that many ticks)."""
    per_ms = description.SYSTIMER_INSTRUCTIONS_PER_TICK * (description.SYSTIMER_HZ // 1000)
    return 500 * per_ms


def test_the_pages_worked_delay_costs_are_the_boards_own_and_the_stale_claim_is_gone():
    """The page prices `delay(500)` in the Uno's and the C3's instructions, and
    says where a clock is recorded rather than that only the Uno has one.

    The counts are computed from the board modules and looked for in both
    comments, so a description that changes its clock leaves a comment that
    fails here rather than one that lies. The measured rates beside them are
    one machine's and are not held. Written after OH-161 gave the ESP32-C3,
    -C5 and -C6 a cited `CPU_HZ` and two comments went on saying "only the
    ATmega328P records a nominal clock"."""
    uno = atmega328p.F_CPU_HZ // 2
    c3 = delay_500_steps(esp32c3)
    c5 = delay_500_steps(esp32c5)
    assert (uno, c3, c5) == (8_000_000, 80_000_000, 120_000_000), (
        "the figures below are the page's; re-derive them if a clock moved")
    for path in (CLOCK, EMULATOR):
        words = comment_words(path)
        if "only the ATmega328P" in words:
            pytest.fail(f"{path.name} still says only the ATmega328P has a clock")
        for needed in (f"{uno:,}", f"{c3:,}", "`CPU_HZ`", "`F_CPU_HZ`"):
            if needed not in words:
                pytest.fail(f"{path.name} does not mention {needed}")
    if f"{c5:,}" not in comment_words(CLOCK):
        pytest.fail(f"clock.js does not price the C5's delay(500) at {c5:,}")
