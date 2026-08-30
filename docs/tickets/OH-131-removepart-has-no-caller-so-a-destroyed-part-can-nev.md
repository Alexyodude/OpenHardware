---
id: OH-131
title: removePart has no caller, so a destroyed part can never leave the bench
status: open
priority: P2
created: '2026-08-30'
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
