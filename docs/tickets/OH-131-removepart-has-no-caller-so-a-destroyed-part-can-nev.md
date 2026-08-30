---
id: OH-131
title: removePart has no caller, so a destroyed part can never leave the bench
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/static/board3d-panel.js
- webui/static/emulator.css
- tests/webui/test_board3d.py
- docs/tickets/OH-81-a-part-past-its-absolute-maximum-is-destroyed-and-th.md
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 wire survey.

`removePart(index)` is exported and nothing calls it: the panel wires only
addPart, disconnect and clearBench (which keeps parts). `destroyed` latches
permanently BY DESIGN, and the design's own justification is "the only thing
that undoes it is removePart, which is what a person does with a burnt LED"
-- a hatch that does not exist in the UI. Burn one LED and the bench carries
the dead row for the life of the page. **OH-81 (done) rests on this hatch
existing; note the correction there when this closes.**

DONE WHEN a part row carries a remove control wired to removePart, a burnt
part can actually be replaced, and a test drives the whole path.

---

**CLOSED 2026-08-30.** Every part row in the bench panel now carries a
`remove` control -- `bench-off bench-remove`, pushed to the row's far edge
by `margin-left: auto` so taking a part off is a deliberate reach and not a
slip beside the per-wire unwire chips -- wired to `scene.removePart(index)`
with a `renderBench()` behind it so the dead row leaves the list at once.
The control is on EVERY row, not only destroyed ones: taking a part off is
ordinary bench housekeeping, and gating it on a verdict would make the
common case impossible for no safety.

`removePart` itself needed nothing: it already discards the part's wires,
releases its meshes, and re-solves the circuit -- it just had no caller.
A second test pins those three duties so the hatch stays one.

**OH-81's record carries the correction this ticket asked for**: its latch
justification described a hatch that did not exist, and the note there now
says so. The latch design itself is unchanged and right.

Suites: tests/webui/test_board3d.py 81 -> 83 passed. Five mutations, all
killed: the control deleted, the control commented out (what the
comment-stripping is for), the redraw dropped, the accessible name dropped,
and removePart's re-solve deleted.
