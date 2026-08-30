---
id: OH-142
title: 'API cleanup: the cold-page 400, a dead endpoint, cross-served pages, an unmetered
  artefact load'
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; cleanup bundle, each
item small and measured.

  * THE COLD-PAGE 400, CAUSE FOUND: fillBoardPicker calls /api/board/pins
    with no ?board=, the server refuses deliberately, the client swallows it.
    Send the picker value or add a no-board response shape. (This retires the
    "one console 400 is expected" line from the handoffs.)
  * /api/target is dead: no caller, only accepts the value already selected.
    Remove route + Selection state, or say why it stays.
  * Both servers serve each other's static pages, each broken there:
    :8088/index.html dials a websocket :8088 does not speak. Serve only your
    own page or say so.
  * /api/board/load-artefact skips MAX_IMAGE_BYTES; the docstring claims a
    ceiling on the artefact path. Enforce or reword.
  * DEFAULT_SKETCH is the one sketch no test compiles -- the exact criticism
    emulator.js makes of the old hard-coded samples. One test.
