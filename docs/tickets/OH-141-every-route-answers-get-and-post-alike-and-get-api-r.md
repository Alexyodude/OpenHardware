---
id: OH-141
title: Every route answers GET and POST alike, and GET /api/reset mutates
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; reproduced live.

do_GET and do_POST funnel into the same table with no method check:
GET /api/reset answers 200 and resets the 8086. The Origin check permits a
MISSING Origin by design -- right for curl -- but a cross-site
img src pointing at /api/reset also sends none, so another tab can reset the
session or burn steps on a loaded board. No read-back (no CORS): state
corruption, not disclosure.

**This is a gap INSIDE the loopback-and-Origin posture, not a challenge to
it** -- the fix is a per-route method column in the route table the module
docstring already promises, mutating routes POST-only. The posture itself is
by design and stays.

DONE WHEN mutating routes refuse GET with 405 and a reason, the table states
each route's method, and the img-tag case is a test.
