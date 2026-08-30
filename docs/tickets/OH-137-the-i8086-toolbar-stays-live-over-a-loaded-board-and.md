---
id: OH-137
title: The i8086 toolbar stays live over a loaded board and overwrites its panes
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/emulator.js
- webui/static/emulator.html
- tests/webui/test_editor.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey.

The i8086 toolbar (#step/#run/#stop/#reset) and the #at memory box stay live
when a BOARD is loaded, and they drive the 8086 routes: press Step over an
Uno and the AVR's 34 named registers silently become ax/bx/cx/dx, the
disassembly becomes 8086, the hexdump jumps -- the panel-desync case.
#status/#counter never update for a board at all.

DONE WHEN loading a board disables or rebinds the 8086-only controls, the
panes always say which machine they are showing, and a test drives the
desync case.

---

**CLOSED 2026-08-30.** The shared panes have two writers and nothing said
whose turn it was. Now `panes` says, and it changes hands only through
`showMachine(name)`:

  * **A board hand stands the 8086 down**: step, run, stop, reset and the
    `#at` memory box disabled, and `running = false` -- the worst desync was
    not the Step button but a Run loop left going, which overwrote the
    board's panes on every 20,000-step burst.
  * **`refresh` itself refuses while a board owns the panes**, before the
    fetch, so the burst already in flight when the board loaded lands
    nowhere. `panes` leaves "i8086" only through `showMachine`, which also
    stops the loop, so the null return is never dereferenced.
  * **Every board redraw declares the owner** -- the call sits at the tail
    of `renderBoardState`, so a load, an artefact, and a clock tick all say
    so, and the toolbar cannot drift from the panes.
  * **The sample Load button is the way back** and stays enabled either
    way; `loadSelected` hands the panes to "i8086" and `renderStatus`
    re-derives step/run/stop from the run state on the next redraw.
  * **The panes say which machine they show**: `#machine` in the toolbar,
    written by every hand-over. `#where` was already per-machine (the
    board's pc renders there); the label is the half a reader could not
    deduce.

`#status`/`#counter` still describe only the 8086 -- the board state
carries no status word or step count on the wire, and inventing one here
would be a claim the server never made. They sit beside a label that now
says whose they are. If a board status line is wanted, it is server work
first, and a new ticket.

Suites: tests/webui/test_editor.py grew three tests. Seven mutations, all
killed: the refresh guard deleted, the owner declaration dropped, the run
loop left alive, the disable loop commented out (what the stripping is
for), the way back dropped, the label never written, the label element
removed.
