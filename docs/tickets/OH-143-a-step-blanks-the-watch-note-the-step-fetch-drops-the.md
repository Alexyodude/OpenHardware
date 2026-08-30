---
id: OH-143
title: 'A step blanks the watch note: the step fetch drops the words the server answers'
status: done
priority: P3
created: '2026-08-31'
touches:
- webui/static/emulator.js
- tests/webui/test_editor.py
- docs/HANDOFF_2026-08-31_the-queue-runs-dry.md
---

From the 2026-08-31 browser-verification pass (handoff §9): with an address
in the watch box, a single Step wipes the note beside it.

The server was built for this not to happen. The step route's own comment
says "`words=` rides it exactly as on /state", and it does — both routes
answer through `_board_state(boards, query)`. The page is the half that
drops it: every state fetch goes through `boardStateUrl()`, which appends
the watch box's `words=`, but the Step click posts a bare
`api("/api/board/step", {})`. The reply IS a state render
(`renderBoardState` consumes it), so the note is rewritten from
`state.words ?? []` — an empty join, a blanked note.

The cost is exactly the affordance OH-140 paired: "step once, type an
address into watch and see the word" cannot happen in that order today;
the word appears only on load and on run ticks, and every step erases it.

DONE WHEN a step's fetch carries the watch box's words the same way the
state fetches do, the note survives a step, and a source test forbids the
bare `/api/board/step` literal the way it already forbids the bare state
literal.

---

**CLOSED 2026-08-31.** The one builder finally serves every fetch whose
reply is a state render. `boardStateUrl()`'s body became `watchedUrl(route)`
— the same trim, the same encode, the route a parameter — with
`boardStateUrl()` a one-line delegation kept because four poll sites read
better as "the state" than as a literal, and the step click goes through
`watchedUrl("/api/board/step")`. No server change: the route read `words=`
from its query all along, as its own comment claimed.

Verified three ways. The source pin
(`test_a_step_carries_the_watch_so_the_note_survives_it`) requires the
builder call and forbids the bare step literal, mirroring OH-140's state
pin. Two mutations, both killed by it: the step reverted to the bare
literal, and the delegation inlined back to the old body — the second is
exactly the shape the OH-140 pin cannot see, which is why the new pin's
third assertion exists. And the behaviour in a real browser: type
`0x0000,0x0002`, build, step — the note reads `0x0 = 0x00000000
0x2 = 0x00000000` after the step, where the 2026-08-31 verification pass
had measured `''` on the same sequence.

The `words=`-dropping mutation inside `watchedUrl` itself (return the bare
route) is invisible to any source pin and killable only by that browser
run — the same stated absence as every behavioural half of this classic
script, which has no headless harness.
