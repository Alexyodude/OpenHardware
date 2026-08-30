---
id: OH-138
title: On the XIAO SAMD21 the obvious Serial line fails with a bare scope error
status: done
priority: P2
created: '2026-08-30'
touches:
- webui/compile.py
- tests/webui/test_compile.py
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

---

**CLOSED 2026-08-30.** `Recipe` grew `hints`: (substring, note) pairs for
errors the recipe itself CAUSED. A failed compile's diagnostics are passed
through `_hinted`, which appends the note under any error whose substring
appears -- appended, never rewritten, because the compiler's words carry
the line number and the caret, and a hint that replaced them would trade
the where for the why.

One row exists, the SAMD21's: `'Serial' was not declared` gets "this build
has no USB device on purpose -- `Serial` on a XIAO is USB-CDC, and an
emulated board has no host to enumerate to. The UART this page's console
shows is `Serial1`." The old refusal ended "did you mean 'Serial_'?",
which sends a person to a USB type that is MORE wrong. The Uno's row is
`hints=()` -- its `Serial` is the hardware USART and simply compiles, and
a test holds that too.

The diagnostics pane needed nothing: it prints `Build.diagnostics`
verbatim, and the note rides in it, server-side and testable.

Three tests (the note lands under the compiler's words; it does not fire
on an unrelated error; the Uno still just works). Five mutations, all
killed: the hint row deleted, the needle broadened to always-match, the
application dropped, the compiler's words dropped, the append neutered.
