---
id: OH-166
title: Three tests assert facts about the machine rather than the code, and fail when
  another session is working
status: open
priority: P3
created: '2026-09-05'
---

Three tests in tests/webui assert something that is not a property of this code, and each has now failed for a different session doing something else on the same machine.

None is a flake in the usual sense. Each asserts a fact about a resource the test does not own, so the failure is real and the assertion is what is wrong.

1. `test_compile.py::test_a_failed_build_leaves_nothing_behind` globs the SYSTEM temp directory for `openhardware-build-*` and asserts none exist. That is a global namespace: any concurrent build, any other pytest run, any `checkall.py`, any other session on the machine, and it fails. It also fails on a leftover from a run that was killed, which is not hypothetical -- the 2026-09-05 handoff's §9.1 records `checkall.py` being killed three times and twice leaving exactly that directory behind, and both had to be inspected and removed by hand before the suite would pass. The test is right that a build must clean up after itself; what it cannot do is tell its own leak from somebody else's.

2. `test_emulator.py::test_a_state_poll_answers_while_a_build_runs` asserts a wall-clock latency, `waited < 3.0`, while a real build runs. Recorded in the previous handoff's §9.2 after failing once during a session where a review agent's pytest and a mutation batch were running concurrently, and passing on every other run including alone.

3. `test_board_run.py::test_an_upload_from_another_origin_is_refused` failed twice on 2026-09-05 with `ConnectionAbortedError`, both times while node processes were running alongside it, and passed alone on every attempt afterwards.

Observed, 2026-09-05: (1) failed for one review session under two concurrent pytest runs; (3) failed twice for the session holding OH-162, under concurrent node probes. Different sessions, different loads, same shape.

**For (1) the mechanism is observed and not inferred.** Both of those concurrent runs were `pytest tests/webui`, which includes `test_compile.py`, and that file really does build on this machine -- 61 tests, none skipped, 54 seconds, and `compile.build` opens its directory as `tempfile.TemporaryDirectory(prefix="openhardware-build-")` at `webui/compile.py:767`. So two live builds shared the global temp namespace at the moment one of them asserted nothing of that name existed. (2) and (3) have no such account and are not given one here.

**What is NOT claimed: a single root cause.** A first reading was that all three are one shared temp path or port collision. Only the first is a temp path. The second is a clock and the third is a socket. What they share is the shape of the assertion and not its mechanism, and a ticket that guessed at one cause would send the next session looking for something that is not there.

STEPS:

1. The temp one is the one with a clean fix and the clearest harm. `compile.build` should create its directory under a root the caller controls rather than under `tempfile.gettempdir()`. The alternative -- asserting that the directory THIS build made is gone -- needs `build` to hand its path back, which is a test-visible surface added to production code to make a test honest; a caller-supplied root costs the same edit and leaves the API alone. Touches `webui/compile.py`.

2. The latency one wants a bound that is not a wall clock, or an explicit skip when the machine is loaded. Judgement either way, and it should be labelled.

3. The socket one has not been diagnosed at all. `ConnectionAbortedError` under load could be the server's accept backlog, a port already in use, or the client giving up; nobody has looked. It is the only one of the three where the failure might be a real defect in what is being tested rather than in the test.

4. And a check, since this repository's own position is that a check which has never failed is evidence of nothing: whatever is done, run the whole suite twice concurrently and confirm it passes, because that is the condition all three failed under.

Filed after two independent reviews of OH-162 step 3 each hit one of these while the other was running.
