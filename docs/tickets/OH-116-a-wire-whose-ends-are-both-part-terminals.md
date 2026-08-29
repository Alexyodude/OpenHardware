---
id: OH-116
title: A wire whose ends are both part terminals
status: open
priority: P3
created: '2026-08-30'
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
