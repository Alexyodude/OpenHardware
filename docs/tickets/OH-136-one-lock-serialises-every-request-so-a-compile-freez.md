---
id: OH-136
title: One lock serialises every request, so a compile freezes the page for its whole
  build
status: open
priority: P2
created: '2026-08-30'
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
