---
id: OH-144
title: 'The pin table reads backwards, and no pin answers the pointer'
status: open
priority: P3
created: '2026-08-31'
touches:
- webui/static/emulator.html
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

Two reader-facing complaints about the pin panel, reported together
(2026-08-31, "fix the pad and pin. also make the pins highlight when
hovered over").

  * **The table's first two columns read swapped to the audience the page
    serves.** The header says `Pad | Pin | State` and a row says
    `13 | PB5 | input`. To anyone who has written `digitalWrite(13, ...)`,
    "13" IS the pin, and PB5 is the chip's own name for it -- the very
    field the API calls `chip_pin`. The column labelled "Pin" holding the
    chip name while the column holding the pin name is labelled "Pad" is
    technically defensible and reads backwards.
  * **Nothing on the canvas answers the pointer.** A pad or a part
    terminal can be grabbed, and the only way to learn that is to try.
    On the boards drawn as a bare footprint it is worse than quiet:
    `board3d.js` says it itself -- "a wire can still be started from a pad
    nobody can see".

DONE WHEN the table names the pin column "Pin" and the chip's own name
"Chip pin"; resting the pointer on a pad or a part terminal lights it and
turns the cursor; leaving takes both back, including for a pad whose only
body is an invisible collider; and the source pins hold the hover to the
same `padUnder() ?? terminalUnder()` order the drag itself uses.

---

**CLOSED 2026-08-31.**

  * `emulator.html`: the headers are `Pin | Chip pin | State`. No code
    change -- the columns' CONTENTS were always pin name, chip name, state;
    only the words over them were backwards.
  * `board3d.js`: `hover()` lights whatever `padUnder() ?? terminalUnder()`
    answers -- the same order a press grabs, so what glows is exactly what
    a drag would take -- with a neutral `HOVER_GLOW` emissive (grey for the
    same reason the studio's light is: a tint would shift the vendor's
    metal, and the cue claims "this one", not a state). An invisible pad
    post is made visible for the stay, which is the one moment the page
    can honestly point at a pad on a bare-footprint board. `dehover()`
    restores emissive, visibility and cursor, and runs from every path
    that could invalidate the lit mesh: drag start, `releasePart`,
    `clearBoard`, `carvePins` (which swaps posts for carved pins), and the
    pointer leaving the canvas.
  * Verified: two source-pin tests (headers exact and `Pad` gone; hover
    body holds the order, the glow, the restore, and every dehover site);
    mutations -- hover call dropped from the move handler, restore dropped
    from dehover -- both killed; a real-browser pass drove pointer moves
    over pin 13 and a terminal, watched emissive and cursor go on and off,
    and confirmed a drag still lands a wire afterwards.
