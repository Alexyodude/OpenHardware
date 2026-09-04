---
id: OH-164
title: A picked board says its pins are in use elsewhere while nothing is running
status: done
priority: P2
created: '2026-09-04'
touches:
- webui/static/board3d-panel.js
- webui/api.py
- tests/webui/test_pin_view.py
- tests/webui/test_board3d.py
---

A board you have picked but not loaded tells you its pins are "in use elsewhere". Nothing is running, so nothing is using them.

Measured 2026-09-04 with `api.pad_view(board, api.description_for(board), None)` -- the call the page makes for a board that has been picked -- counting pads whose state is `unknown` and whose `chip_pin` is not null, which is exactly the input `unknownWords` reads:

    Arduino Uno          32 pads, 22 would read "in use elsewhere"
    XIAO-SAMD21-DIP      14 pads, 11
    XIAO-ESP32-C3-DIP    14 pads, 11
    XIAO-RP2040-DIP      14 pads, 11
    XIAO-MG24-DIP        24 pads,  0   (no module, so no chip_pin, so "not modelled" -- correct)

webui/static/board3d-panel.js:112 decides between two sentences on `chip_pin` alone:

    function unknownWords(pad) {
      return pad.chip_pin === null || pad.chip_pin === undefined
        ? NOT_MODELLED : IN_USE;
    }

and its own comment three lines above states the rule it is keeping: "a pad has a chip pin **if and only if** the board answered for it". That rule holds. What it does not cover is the third case -- the board COULD answer and no program is running -- and in that case every modelled pad takes the "in use elsewhere" branch. The two real sentences are about a running program; this one is about there being no program.

This is not new: it has been true for the Arduino Uno and the two XIAO SAMD21 files since OH-70 gave them a `PIN_NAMES`. OH-160 widened it from 3 board files to 12 by giving the ESP32-C3, C5, C6 and RP2040 modules a generated `HEADER`, and an independent review of OH-160 found it. It is filed here rather than fixed there because the fix is in the panel and its test belongs in `tests/webui/test_board3d.py`, which OH-162 claims.

The information needed is already known on the Python side and is not sent: `webui/api.pad_view` is called with `live=None` for a board that has been picked, and with a dict for one that is running. The page cannot tell those apart today -- inferring it from `unknown == pads.length` would be the re-derivation OH-121 already paid for once, when the 3D view recomputed a scale that the file could have stated.

STEPS:

1. State it rather than infer it: `pad_view` reports whether any levels were read at all -- one field, named for what it means, beside `unknown`. `pin_view` sets it from the same `live` it already has.
2. `unknownWords` takes that as its third case, with words that say what is true: no program is running, so no pin has a level. The pads that are genuinely unanswerable while a program runs keep "in use elsewhere", and the pads no module knows keep "not modelled".
3. The panel-side test goes in `tests/webui/test_board3d.py` beside `test_the_two_sentences_are_told_apart_by_the_pin_and_not_by_a_guess`, which asserts today's two-way rule and must gain the third. **That file is not in this ticket's `touches` because OH-162 claims it**; add it with `python tools/tickets.py set OH-164 --touch tests/webui/test_board3d.py` once OH-162 is done, or land the panel change with OH-162's holder. The API-side test goes in `tests/webui/test_pin_view.py`, which this ticket does claim. Include the clear-air case: an Uno with a program running and one pad taken by a timer still reads "in use elsewhere" for that pad and a level for the rest.

Done when: for every one of the 26 boards, a picked-but-not-loaded board reports no pad as "in use elsewhere", and a running Uno still does for the pads its timers took (OH-71's case).

**Note 2026-09-05:** DONE 2026-09-05.

The fact is stated rather than inferred, which is step 1: `pad_view` reports `read_levels` beside `unknown`, true exactly when it was given levels to read. That is `live is not None` and nothing else -- `pin_view` always passes `pin_levels(...)`, so an empty dict is a program that drove nothing and not the absence of one. It is captured before `live = live or {}`, because after that line there is nothing left to tell the two apart with, which is the whole of this ticket.

Step 2: `unknownWords` takes it as a third case and the order is the point. A pin no module models keeps "not modelled" whether or not a program runs, because that is a fact about the board description rather than about the moment; only the other branch changes. So a picked board's unmodelled pads keep the words they had, and only the pads that could have been answered for now read "no program running".

**A first version had the state poll mark the layout as having levels, and the review was right that it must not.** `/api/board/state` carries no board identity, the picker does not stop the clock, and the panel is a module that can be showing board B while the session runs board A -- so marking on arrival made B claim a program was running on it, and B went straight back to "in use elsewhere". Nothing is needed there: `/api/board/pins` already decides it and decides it WITH the identity check the poll cannot make, returning `pin_view` only when `session.board == asked`, and `loadBoardImage` calls `reload()` at once so the answer is re-fetched exactly when it changes. The marking is gone and the test asserts both halves -- that `read_levels` does not appear in `levels()`, and that the route still makes the check the panel now depends on.

**And `pin_view` coalesces**, because `pin_levels` answers None for a description with no `pin_states`: a RUNNING board with no reader would have reported that nothing was running, with every modelled pad reading "no program running" while its program ran. Nothing has that shape today -- all six modules with PIN_NAMES have both -- but OH-160 generates PIN_NAMES from a HEADER and leaves pin_states hand-written, so it is exactly the shape that generator makes. A comment claimed the invariant lived in the type; it lives in `pin_view` now, and a stub description with names and no reader is the test.

Measured 2026-09-05 over `catalogue.board_names()`, all 26 boards, counting pads that are `unknown` with a `chip_pin` -- exactly the input `unknownWords` reads -- for a board picked and not loaded:

  Arduino Uno                1 board,  22 of 32
  XIAO-ESP32-C3-SMD          1 board,  15
  the other ten modelled    10 boards, 11 each
  no module at all          14 boards,  0 (no chip_pin, so "not modelled", which was already right)
                            --
                            26

Twelve of them, which is the number OH-160 made it. TWO modules answered before it -- `atmega328p` and `samd21`, over three board files, since the SAMD21 has a DIP and an SMD -- and it gave the ESP32-C3, C5, C6 and RP2040 a generated HEADER between them. An earlier draft of this note said three modules over four C3 files and tallied to 27; both were wrong and the review caught them.

Done-when, verified: for all 26 boards a picked-but-not-loaded view now reports `read_levels` false and no pad as "in use elsewhere" -- the Uno's 22 modelled pads read "no program running" and its 10 unmodelled ones still read "not modelled". A running Uno still reports the pins its timers took, which is the clear-air case and its own test.

Fourteen mutations run and each killed the test named for it, both files restored by hash. On the API side: the field never reported, always true, read AFTER the coalesce that loses the distinction, an empty poll counted as no program, and the coalesce removed. On the panel: the third sentence never reached, eating the second, the ternary swapped, the order inverted so an unmodelled pin loses its words, the table inferring the case from a count instead of reading the field, the chooser handed a literal instead of the value the table read, the fallback flipped to true, the poll marking the layout again, and words that name a state rather than say what is true.

**Four of my own assertions were wrong first, all in one way**, and it is the way this file is most prone to: looking for a string rather than for a use. One compared NOT_MODELLED against the PARAMETER `readLevels`, named in the signature before any sentence. One searched the whole panel for the guess it rejects, which its own docstring and the panel's block comment both spell out -- and `stripped` takes `//` lines only, so a `/** */` comment satisfied it. One asserted the table READS the field without asserting it HANDS it over, so `unknownWords(pad, true)` restored the entire defect with the suite green -- the review found that one and it was a blocker. And one pinned the order of the two sentences without pinning which branch reaches which, so swapping the ternary survived. All four are assertions about the call site or the branch now.

Two more came out of the same battery once those were added: the fallback flipped to `?? true` survived because `layout` is either null with no rows or a view carrying the field, so it is unreachable on screen -- asserted anyway, since the one time it would decide is the one time "a program is running" is the worst default there is. And removing the coalesce survived until the stub test existed.

`tests/webui/test_board3d.py` was added to this ticket's touches after OH-162 gave it back: steps 1 and 2 of that ticket needed it and are done, steps 3 and 4 are inside the solver, and no two open tickets may claim one file.
