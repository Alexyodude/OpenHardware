---
id: OH-136
title: One lock serialises every request, so a compile freezes the page for its whole
  build
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/emulator_server.py
- webui/compile.py
- tests/webui/test_emulator.py
- tests/webui/test_compile.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; measured live.

One lock wraps every route; /api/board/compile runs the whole build inside
it. Measured: a GET /api/state issued 0.7 s into a SAMD21 build returned
after 15.79 s. During every build the state poll, the clock's run ticks and
the pin panel stall -- the page looks hung. And TIMEOUT_SECONDS=120 is per
SUBPROCESS: a SAMD21 build is ~24 invocations plus link and objcopy, so a
pathological toolchain holds the lock for the better part of an hour while
the module's comment claims the timeout stops it "holding the server's lock
forever".

DONE WHEN a compile runs outside the session lock (it touches no session
state until load), concurrent state polls answer during a build measurably,
and the timeout claim in the comment matches what is enforced -- a per-build
budget, stated.

---

**CLOSED 2026-08-30.** Both halves.

**The build runs before the lock is taken.** `prepare_compile` in
`emulator_server.py` is the unlocked half of /api/board/compile --
validation and the whole `compile_service.build` -- called by `_api` ahead
of `with self.lock`; the locked handler receives the finished build and
does only the load. The handler still prepares inline when driven directly
(the tests, any second transport), and a source-level test pins that it
CONSUMES the prepared build rather than rebuilding inside the lock --
the freeze in disguise. Measured live, before: a GET /api/state issued
0.7 s into a SAMD21 build answered after 15.79 s; after: the same poll
answers in milliseconds while the build is still running, asserted by a
test that requires the build to be alive when the poll lands (with one
retry for the vacuous cold-start case only -- a lock regression is
structural and fails both attempts; killing the prelude in mutation
testing did exactly that).

**The timeout claim is now true.** `TIMEOUT_SECONDS` was per INVOCATION
while its comment claimed it bounded the build -- ~24 invocations deep, a
pathological toolchain had the better part of an hour. `BUILD_BUDGET_
SECONDS = 300` is the whole-build wall clock, enforced by `_run` shrinking
every invocation's timeout to what remains; running out comes back as
returncode 124 with the budget and the command named, riding the same
nonzero rail every real compiler failure rides. A deadline already passed
runs nothing at all.

One near-equivalent mutation was considered and EXCLUDED rather than
chased: `if remaining > 0` flipped to `if True` still yields a fast 124
(the negative timeout kills the child at spawn) -- same observable
behaviour, one wasted process spawn.

Six mutations run, all killed -- including the prelude deleted (the poll
test re-froze and failed, which is the proof it measures the lock) and
the prepared build ignored. tests: compile suite 34, emulator suite 47,
all green.
