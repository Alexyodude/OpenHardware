---
id: OH-134
title: Typing s or r in the sketch editor steps the 8086 instead
status: done
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims webui/static/emulator.js when it starts.

**From the 2026-08-30 API/IDE survey. Very likely the whole "ide is broken"
report, and it is one line.** The page-level keydown handler skips INPUT and
SELECT but not TEXTAREA; the sketch editor is a textarea; "s" and "r" call
preventDefault() and step or run the 8086. So typing "void setup" single-steps
the emulator on the s and never writes it: Serial, setup, return, for,
digitalWrite are all unwritable and the default sketch cannot be edited.

DONE WHEN TEXTAREA joins the guard, every printable key reaches the editor, a
test covers the guard's element list, and the register pane no longer redraws
while typing a sketch.

## DONE, 2026-08-30

TEXTAREA joined the keydown guard, before the key checks. One line, plus the
test that holds all three text-entry elements in the guard and the guard
before the shortcuts. The mutation removing TEXTAREA again is killed.

The register pane stops redrawing while a sketch is typed because the s and r
never reach preventDefault from inside the editor any more.
