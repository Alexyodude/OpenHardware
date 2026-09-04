---
id: OH-164
title: A picked board says its pins are in use elsewhere while nothing is running
status: open
priority: P2
created: '2026-09-04'
touches:
- webui/static/board3d-panel.js
- webui/api.py
- tests/webui/test_pin_view.py
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
