---
id: OH-140
title: 'IDE affordances: no board step, no buildability signal, the sketch dies on
  reload'
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/emulator_server.py
- webui/static/emulator.js
- webui/static/emulator.html
- tests/webui/test_board_catalogue.py
- tests/webui/test_board_run.py
- tests/webui/test_editor.py
- tests/webui/test_emulator.py
- tests/webui/test_board3d.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; affordance bundle.

  * BoardSession.step() exists and no route exposes it: a board cannot be
    single-stepped from the page while the 8086 can.
  * Nothing says which boards have a compile recipe; the picker offers Build
    on all 26 and 9 runnable boards 400 only after the attempt. Surface
    buildability in the catalogue JSON and grey the button.
  * The editor resets to DEFAULT_SKETCH on every reload; localStorage holds
    only the theme. Any crash or reload eats the sketch, unwarned. No build
    shortcut either.
  * words= peripheral-register watch: route, validation and a long docstring
    argument exist; the UI never sends it.

DONE WHEN each affordance exists or its absence is stated on the page rather
than discovered by failure.

---

**CLOSED 2026-08-31.** All four affordances EXIST -- none took the
absence-stated escape hatch.

  * **/api/board/step**, POST-only in the method table, stepping
    `count` instructions and answering with the stepped state so the page
    redraws in one round-trip. `_board_state` is factored out of the state
    route so the two cannot drift, and `words=` rides the step exactly as
    it rides /state. The page's Step button lives and dies with Run's own
    enabling, and stops the clock before stepping so the step is the only
    thing that moves the machine.
  * **`buildable` rides /api/boards** -- stated at the route because
    `compile` imports the catalogue and layering points one way -- and
    `reflectBuildability` greys the Build button with the reason in its
    title, re-checked on fill and on every picker change. The 400-after-
    the-attempt flow is gone.
  * **The sketch survives a reload**: kept in localStorage on every input,
    read back ahead of DEFAULT_SKETCH, with the theme's own try/catch for
    private mode.
  * **words= finally reaches the wire**: the `#board-watch` box passes
    through `boardStateUrl()`, which every one of the four state fetches
    goes through (a source test holds the count and forbids the bare
    literal), and the watched words render beside the box on every
    redraw. The server's refusal for a bad address already names it.

The build shortcut the ticket floated was NOT added: Ctrl-Enter is an
editor-keymap decision tangled with OH-134's keydown guard, and a wrong
binding there re-opens the typing bug. If wanted, it is its own small
ticket.

Six mutations, all killed -- including the step route losing its method
row, which OH-141's completeness test catches by name.
