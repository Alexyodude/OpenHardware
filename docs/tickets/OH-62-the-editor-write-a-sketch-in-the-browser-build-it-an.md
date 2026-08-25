---
id: OH-62
title: 'The editor: write a sketch in the browser, build it, and watch it run'
status: done
priority: P1
created: '2026-08-26'
touches:
- webui/static/emulator.html
- webui/static/emulator.js
- webui/static/emulator.css
- tests/webui/test_editor.py
---

The half of the IDE a person actually sees. BLOCKED ON OH-61, which is what turns source into an image; this ticket is the pane, the button and the loop.

WHAT EXISTS TO BUILD ON, and it is most of the page already. webui/static/emulator.html has a board picker with 26 boards and 12 enabled, a register pane, a memory hexdump, a disassembly listing with a current-instruction marker, step and run controls, and -- since OH-43 -- a board console fed by uart.present on the wire. What it does not have is anywhere to type. A person picks a FILE.

SO THE CHANGE IS: a source pane, a Build and Run button, and the compile result routed to the two places it can go -- an image into the loader, or the compiler's own errors into a pane that shows them against line numbers.

THE MAIN LOOP IS ALREADY REAL and this is worth saying because the user's request named it: 'code runable in a main loop if wanted'. On the Uno that loop is Arduino's own -- main() calls setup() then loop() forever, and tests/avr/test_arduino_sketch.py watches it happen. Nothing here needs to invent a runtime for that board. Run is the existing free-run control, and the sketch keeps running until it is stopped.

WHAT TO GET RIGHT.

Editing while running is the obvious trap: a build has to stop the machine, reload, and re-enter, in that order, or the image is overwritten under a running PC. webui/boards/atmega328p.py's install() docstring records the same ordering hazard from the other side -- install, load, enter, and reversing the first two erases the image.

A build takes a second or two of wall clock. The button has to say so and refuse to be pressed twice, or a person gets two compilers racing for one temp directory.

NO CDN, no editor library fetched at run time. webui/static/vendor/ holds three.js because that decision was already made once; a textarea with a monospace font and line numbers is enough for the first slice and is a decision, not a limitation -- say so in the file rather than leaving it looking like an omission.

AND THE THING THAT WILL BE ASKED FOR IMMEDIATELY: Serial.print. It needs USART0 on the ATmega328P, which is OH-63, and the console pane it would print into already exists. Without that the editor is real and Serial output is silent, which is a bad first impression of a working thing -- prefer landing OH-63 first if both are open.

Done when a person opens the page, picks Arduino Uno, edits the delay in a Blink sketch, presses Build and Run, and sees PB5 change period -- with a deliberate syntax error showing avr-gcc's message against the line it is on, and with a build while running leaving the machine in a defined state rather than a half-loaded one.

**Note 2026-08-26:** CLOSED 2026-08-26. Verified in a real browser, listener count checked as 1 first.

WHAT A PERSON DOES NOW: opens the page, picks Arduino Uno, presses Build and run on the default Blink -> 1,946 bytes, entered at 0x00000000, Run enabled, board report names the chip and core. Replaces the sketch with a broken one -> 'Did not compile. The board is unchanged.', the location rendered red and clickable, the source quoted with a caret under the offending character. 0 console messages at warning level or above.

STOP, LOAD, ENTER. running=false before the request; the server replaces the board only on a build that succeeded. test_a_failed_build_leaves_the_board_exactly_as_it_was uses the PC as the witness, because a reload re-enters at the reset vector -- a step count would not have proved it.

A BUG THE BROWSER FOUND AND THE TESTS DID NOT. renderDiagnostics appended the quoted source straight after the location, which put the caret ABOVE the sentence explaining it. Fixed, and guarded by position in the source since Python cannot render the pane. This is the second time this repository has recorded 'a pane can be wrong in a way only a reader sees' -- the first was renderMemory's mutation surviving 371 tests.

THE PAGE QUOTES THE SOURCE, NOT THE COMPILER, and that is downstream of OH-61's #line trade: correct line numbers cost gcc's own quoted line, because it can no longer map a reported line back to a physical one. The textarea is a better source for the quote anyway -- it is the text in front of the reader.

NO EDITOR LIBRARY, nothing fetched at run time. test_nothing_is_fetched_from_another_host greps src=, href=, @import and fetch( against an external host across html, js and css. Syntax highlighting is a real want and a real dependency; not this ticket's.

Gate: 1,418 passed, 17 skipped; all eight checkers exit 0.
