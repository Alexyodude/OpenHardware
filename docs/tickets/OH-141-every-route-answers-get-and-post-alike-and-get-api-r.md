---
id: OH-141
title: Every route answers GET and POST alike, and GET /api/reset mutates
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/emulator_server.py
- tests/webui/test_emulator.py
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

---

**CLOSED 2026-08-31.** `ROUTE_METHODS` is the per-route method column the
module docstring promised: nine mutating routes POST-only, seven read-only
routes on both verbs (a POST-shaped read mutates nothing and refusing it
would break no attack). `_api` checks the verb before anything runs --
before even the unlocked compile prelude -- and refuses with 405 naming
the verbs the route answers. The loopback-and-Origin posture is unchanged,
as the ticket frames it: this is a gap inside the posture, closed.

The img-src case is the behavioural test: GET /api/reset answers 405, the
step count SURVIVES the refused request, and the same route still answers
POST. A second test holds the table complete against the dispatch -- every
`route == "/api/..."` literal in the module must have a row, so a new
route without a stated verb fails by name instead of shipping with
whatever verb reaches it first.

/api/target is in the table as POST-only while it lives; whether it lives
is OH-142's question, not this one's.

Four mutations, all killed: the guard deleted, reset opened to GET, a
route dropped from the table, and the 405 demoted to a 400.
