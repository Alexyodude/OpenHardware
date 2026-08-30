---
id: OH-125
title: What the composer measures stops at stdout and reaches no reader
status: done
priority: P2
created: '2026-08-30'
touches:
- tools/compose_board_3d.py
- webui/static/board3d-panel.js
- tests/rules/test_compose_board_3d.py
- tests/webui/test_board3d.py
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 model survey.

`compose` prints artwork tallies, `not ink`, `not cu`, cutouts, unpinned
turns, dropped elements -- and the extras dict carries none of it, so
`board3d-panel.js` can only say "Not drawn: Y1, Y2" about an Uno also missing
four LEDs, 432 silkscreen strokes and 99 unmapped placements. This is the
mechanism that let OH-119 and OH-122 sit unnoticed; the file's own principle
says "a gap that is measured is a gap somebody can close, and a gap that is
silent is one nobody knows about" -- and the measurement stops at stdout.

DONE WHEN the tallies ride in extras and the panel shows them, so the page's
claim about what is not drawn is the composer's own measurement.

---

**CLOSED 2026-08-31.** The measurement now reaches a reader.

`extras` carries two new keys on every composed board: `artwork` (the
drawn tallies, verbatim) and `not_drawn` -- unread ink by kind, unread
copper by kind, cutout count, the turn-unseen placements by name, and
`unmodelled`: placements with no model and no ABSENT entry, which until
now fell through a bare `continue` without even becoming a number. That
silent skip was the mechanism this ticket names, and it is also printed
per board now ("no model N placement(s) ...").

The panel builds its caption's gap clauses from `model.not_drawn`, one
compact clause per kind, after the absent list it already showed -- so
"Not drawn: Y1, Y2" on a board also missing its silkscreen text now says
so in the composer's own numbers.

ABSENT packages are NOT counted as unmodelled (the absent list already
explains them), and a mutation pins that distinction.

All eleven boards regenerated with the tallies aboard; the artifact test
reads `not_drawn` back out of the shipped Uno and requires the text gap
OH-122's close note records. Five mutations, all killed -- the extras
mutation is killed by the SOURCE pin, deliberately: a shipped-artifact
test that no mutation regenerates is the exact survivor class section 2.6
of the morning handoff warns about.
