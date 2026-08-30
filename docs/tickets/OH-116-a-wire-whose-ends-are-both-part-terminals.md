---
id: OH-116
title: A wire whose ends are both part terminals
status: done
priority: P3
created: '2026-08-30'
touches:
- webui/static/board3d.js
- webui/static/circuit.js
- webui/static/board3d-panel.js
- tests/webui/test_circuit.py
- tests/webui/test_board3d.py
---

_No description yet._

CLAIMS NOTHING yet. `webui/static/board3d.js` and `webui/static/circuit.js`,
and it re-claims when it starts.

**OH-84's first option, split out because it is a data-model change and OH-84
chose the sentence.** That ticket asked whether two parts can be wired to each
other; the answer shipped is a note telling a reader to borrow a spare input
pin as the junction, and this is the feature that would make the note
unnecessary.

## WHY IT IS NOT A SMALL EDIT, WHICH OH-84 UNDERESTIMATED

OH-84 says "the netlist already copes -- the union-find in `analyse` joins
keys and does not care what they name -- so the change is a wire model with a
nullable pad". The union-find does cope. Everything around it does not,
because **a wire is `{pad, part, terminal}` and a part-to-part wire touches
two parts**:

  * `analyse` builds its `wired` set with `wired.add(wire.part)` -- one part
    per wire.
  * `reaching` is `wire.part === index && wire.terminal === name`.
  * `blind` is `wire.part === index && padState.get(wire.pad) === "unknown"`,
    which has no meaning for a wire with no pad.
  * the busiest-pin search near the end is `wire.part !== index` again.
  * in `board3d.js`, `beginWire(pad, end)` takes the rope's start from
    `pad.getWorldPosition`, and a wire carries `pin: pad.userData.pin`.
    `connections()`, `disconnect`, `removePart` and the drag all read one or
    the other.

So the honest shape is a wire with two ENDS, each either a pad or a terminal,
and every reader above taught to walk both. That is worth doing and it is not
three lines.

## AND ONE PART OF IT CANNOT BE VERIFIED THE WAY THE REST CAN

`webui/static/circuit.js` imports nothing and `tests/webui/test_circuit.py`
runs it under node, so the netlist half is testable exactly as the rest of it
is. **The drag is not**: starting a wire on a terminal is a THREE.js raycast
against the bench, and there is no headless harness for it. That asymmetry is
the reason to plan the change rather than start it -- a netlist that supports
a wire the UI cannot create is dead code, which `.claude/CLAUDE.md` rule 6
forbids, so the two halves have to land together.

## DONE WHEN

A reader can drag from one part's terminal to another's; `analyse` reports a
series pair correctly with no pad between them; the junction note OH-84 added
stops being shown for a bench that has done it; and the drag is covered by
whatever harness exists by then, or its absence is stated.

---

**CLOSED 2026-08-31, both halves landing together as the ticket
demanded.**

**The shape is the one this ticket named**: a wire has two ends, and the
far end is a pad OR another part's terminal. On the bench wire that is a
`from: {part, terminal}` present exactly when `pad` is not; in
`board3d.js` the wire's `post` is the object the drag began on -- a pad
mesh or a terminal anchor -- and `pin` is undefined for the latter, which
is the one bit every reader branches on.

Each of the listed call sites was taught to walk both ends: the
union-find joins whichever pair exists; `wired` collects the from-part
(load-bearing in the test where the resistor is ONLY ever a from-end);
`reaching` counts both directions; `blind` and the busiest-pin search
were already safe for a wire with no pad and stayed untouched;
`beginWire` starts from either object; the drop refuses the wire's own
starting anchor; `removePart` takes the wires that BEGIN on the part;
`connections` carries `fromLabel`/`fromTerminal` and the panel chip says
"anode ↔ 220 Ω resistor's lead A" where a pad wire says "anode on 13".

**The junction note narrows rather than dies**: it still teaches the
borrowed-input trick, now alongside the direct drag, and it retires on
any bench holding a part-to-part wire -- a page must not tell a reader it
cannot do the thing it just did. The two tests that pinned the old
"cannot be joined" wording moved to the new sentence.

**The series pair the ticket asked for**: D13 → LED → (direct wire) →
231 Ω → GND solves at 9.302 mA through both -- hand-worked, 2.8/301, the
same current as the borrowed-pin bench with one wire fewer.

**The drag**: covered at the source with comments stripped (press falls
through to `terminalUnder`, self-anchor refused), because a THREE.js
raycast has no headless harness here -- the same stated absence
`carvePins` carries on OH-128's record.

Six mutations, all killed; the survivor found on the first run (the
from-side `wired` add unexercised) got the bench that makes it
load-bearing, which is the mutation discipline doing its job.
tests/webui 637 passed.
