---
id: OH-142
title: 'API cleanup: the cold-page 400, a dead endpoint, cross-served pages, an unmetered
  artefact load'
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/board3d-panel.js
- webui/emulator_server.py
- webui/bridge.py
- tests/webui/test_artefacts.py
- tests/webui/test_emulator.py
- tests/webui/test_editor.py
- tests/webui/test_board3d.py
- tests/webui/test_board_catalogue.py
- tests/webui/test_board_run.py
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

---

**CLOSED 2026-08-31.** All five, each with its test and its mutation.

  * **The cold-page 400 is gone at the source**: `reload()` with an empty
    picker returns early with the 400 handler's exact outcome -- no board
    loaded, waiting caption, hidden canvas -- without the doomed
    round-trip. The handoffs' "one console 400 is expected" line retires.
  * **/api/target is removed**, and `Selection` with it: no caller
    anywhere, and it only ever accepted the value already selected. The
    `selected` echo in /api/targets went too (nothing read it);
    `_not_drivable` STAYS, because /api/targets uses it for each entry's
    detail. `handle_api` lost the parameter; eight test call sites across
    three files followed. OH-141's completeness test held the method table
    to the shrunken dispatch automatically.
  * **Each server refuses the other's ENTRY page**: :8088/index.html
    rendered and then hung dialing a websocket :8088 does not speak, and
    the bridge served emulator.html the mirror way. Assets stay common
    property; the entry pages name a transport each, and both refusals are
    one behavioural test.
  * **The artefact load meets the ceiling the docstring promises**:
    checked on `stat().st_size` before a byte is read, with the same
    sentence shape as the body path's refusal.
  * **DEFAULT_SKETCH compiles in a test**, read out of the page's own
    source so an edit is tested as edited -- the exact criticism
    emulator.js makes of the old hard-coded samples, no longer applicable
    to itself.

Five mutations, all killed -- including the sketch-rot detector (a typo
injected into the page's own DEFAULT_SKETCH fails the build test by name).
tests/webui 625 passed after the sweep.
