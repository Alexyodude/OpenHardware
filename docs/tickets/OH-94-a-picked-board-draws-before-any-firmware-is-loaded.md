---
id: OH-94
title: A picked board draws before any firmware is loaded
status: done
priority: P1
created: '2026-08-28'
touches:
- webui/api.py
- webui/emulator_server.py
- webui/static/emulator.js
- webui/static/board3d-panel.js
- tests/webui/test_pin_view.py
- tests/webui/test_emulator.py
- tests/webui/test_board3d.py
---

**Picking a board draws nothing, and the reason is an accident of which
endpoint the geometry rides on.** `#board-pick` has no `change` listener at
all -- the only `addEventListener("change")` in `webui/static/emulator.js` is
on the memory-address box. The picker is a value that `handleLoad` reads at
`emulator.js:446`, and nothing else.

The 3D view is redrawn by exactly one function, `reload()` in
`webui/static/board3d-panel.js:230`, called from four places and no others:
after `/api/board/load` (`emulator.js:488`), after `/api/board/load-artefact`
(`:582`), after `/api/board/compile` (`:745`), and once at startup
(`board3d-panel.js:552`). **All three of the first are firmware loads.** So the
model changes when an image is loaded and never when the board is chosen.

## THE COUPLING IS INCIDENTAL AND THE SPLIT IS ALREADY WRITTEN DOWN

`/api/board/pins` calls `boards.require()` (`webui/emulator_server.py:317`),
which refuses unless a board SESSION exists -- and a session is only made by
`/api/board/load`, which needs an image. So `reload()` takes its not-ok branch
and hides the canvas.

But `api.pin_view` (`webui/api.py:799`) joins two sources that its own
docstring already separates:

  * **position**, from `pinmap.load(board)` at `:838` -- a static read of
    `webui/boards/<board>.json`, needing only the board's NAME
  * **state**, from `pin_levels(runtime, cpu)` at `:819` -- needing a session

`pin_levels`' docstring says why they are apart: "where a pad is never
changes". Nothing about where a XIAO's pads sit depends on what is running on
it. The two are welded together only because one endpoint serves both and that
endpoint requires the session.

## WHY THIS IS THE CAUSE OH-89 DID NOT FIX

OH-89 was filed as "no 3D model on 127.0.0.1:8088", reported twice. It fixed
the SYMPTOM -- the panel now says what it is waiting for instead of showing a
blank rectangle -- and the fix was right. **The cause is that a board you have
selected could be drawn immediately and is not.** A reader picks "Arduino Uno",
sees a caption asking for firmware, and reasonably expects a board.

## SHAPE

One code path, not a mode. `/api/board/pins?board=NAME` answers "the pin view
for NAME", and liveness is an OVERLAY: if a session exists and it is running
that same board, its levels are merged in; otherwise every pad reads `unknown`,
which is a state the page already renders in words (`unknownWords`).

    def pad_view(board: str, description, live: dict[str, str] | None) -> dict

`pin_view(runtime, cpu, board)` becomes a caller of it, so the loaded and the
unloaded view are one implementation and cannot drift -- the failure this
repository has now paid for twice, most recently with the sRGB conversion that
lived in `readPalette` and not in the writer twenty lines away.

`runtime_for` is NOT what resolves the description here: it requires a BUILT
core, and only 12 of the 26 boards have one. A XIAO-MG24 has pads and no core,
and it must still draw.

## DONE WHEN

Choosing a board in the picker draws it, with no firmware loaded and without a
core built; loading an image onto it then lights its pins with no second
mechanism; a board with no pad map still says so rather than drawing nothing
silently; and the no-parameter form of `/api/board/pins` keeps working exactly
as it does today.

## DONE, 2026-08-28

Choosing a board draws it. Verified in a browser, not inferred: with nothing
loaded and no core built, picking `XIAO-MG24-DIP` draws its 24 pads and the
panel reads "0 of 24 pads answerable". Loading an image onto the picked board
then lights it -- "22 of 32 answerable" on an Uno -- through the same one code
path.

**Two things the plan did not know, and both were found by pressing the
control rather than by reading the file.**

**The picker would not accept a XIAO-MG24 at all.** `option.disabled =
!board.runnable`, on the recorded reasoning that offering one "would accept a
click that cannot be honoured". True while picking a board only chose what to
load onto; expired the moment picking draws. Fourteen of the twenty-six have
pads and no core and could never be looked at. Only `Load` cannot be honoured
and it already refuses by name, so the option is enabled and its label still
carries the reason.

**I introduced a regression and the browser caught it.** The server keeps its
board across page loads and `fillBoardPicker` defaults to the first RUNNABLE
board, which knows nothing about that. Making the drawing follow the picker
therefore meant reloading the page while an ESP32-C3 ran would draw an Arduino
Uno and report its pins as unanswerable -- a confident lie where there used to
be a blank. The picker now asks the bare pin view what the server has and
prefers it.

**And the start-up call moved out of the panel.** OH-89 put `reload()` at the
panel's module scope, correctly, because nothing else asked on a fresh page.
It runs before `/api/boards` fills the picker, so it can only ask about no
board in particular -- which is a second console 400 on every cold load beside
the picker's own probe. `fillBoardPicker` owns start-up now, and the count of
failed requests on a cold load is what it was before this ticket: one.

    fresh page, nothing loaded    2 requests, 1 refusal, board drawn
    fresh page, Uno loaded        2 requests, 0 refusals, pins live

`present` narrowed, and that is the behaviour change to look at: it meant "the
description reports pin states", which is false for twenty-four of the
twenty-six boards, so those drew nothing even when loaded. It now means "there
is something to draw". `tests/webui/test_pin_view.py` had a test that would
have gone on passing for a reason it no longer stated, and it says which
meaning it holds now.

15 mutations, 15 killed -- two only after new tests. Both survivors were
behaviours confirmed in the browser and pinned nowhere: that the default
selection draws itself, and that a board with no core is selectable.

11 new tests. Gate: 1,746 -> 1,757 passed, 17 skipped; all eight checkers exit 0.
Evidence: `.playwright-mcp/oh94-XIAO-MG24-DIP.png`, `oh94-Arduino-Uno.png`,
`oh94-fresh-nothing-loaded.png`.

## NOTED WHILE FILING, NOT PART OF THIS

`tools/tickets.py:400` derives a session id as `pid-<parent pid>`, and every
Bash tool call here gets a fresh parent. `tickets.py stop` therefore released
**OH-22** -- a stale lock from 2026-08-25 whose recorded pid collided with the
current shell's. OH-22 is `done` so nothing was lost, but 45 stale locks sit in
`.omc/ticket-locks/` and a collision with a LIVE ticket is possible. Working
around it here by setting `OH_SESSION_ID` explicitly.
