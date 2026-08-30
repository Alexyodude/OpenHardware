---
id: OH-138
title: On the XIAO SAMD21 the obvious Serial line fails with a bare scope error
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet. From the 2026-08-30 API/IDE survey; measured.

The SAMD21 recipe deliberately omits USB-CDC, so Serial -- the obvious thing
to type at a page that shows a UART console -- fails with "Serial was not
declared in this scope; did you mean Serial_?". The compiler choice is
documented in compile.py and is right; the defect is that the IDE never
tells anyone: no diagnostic rewrite, no hint that Serial1 is the UART the
console shows.

DONE WHEN that specific error is met by a diagnostic note naming Serial1 and
why, in the diagnostics pane, with a test on the rewrite.
