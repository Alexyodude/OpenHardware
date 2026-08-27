---
id: OH-83
title: The layout reads the viewport's width and never its height or its shape
status: done
priority: P2
created: '2026-08-27'
touches:
- webui/static/emulator.css
- tests/webui/test_board3d.py
---

ASKED FOR BY THE USER 2026-08-27: "just use the original website and make the
website usable in different proportions and aspect ratios and resolutions."

MEASURED FIRST, ACROSS SEVEN VIEWPORTS, with the Arduino Uno built and drawn.
Every number below is `getBoundingClientRect` in Chromium, not an impression:

  viewport            canvas      page      note
  305 x 640           280 x 240   7.9 screens
  375 x 844           309 x 240   5.5 screens
  1065 x 1920         382 x 287   1.4 screens   PORTRAIT
  1351 x 768          547 x 410   3.4 screens   board panel is 1,548 px tall
  1585 x 620          359 x 269   2.9 screens   SHORT AND WIDE
  3425 x 1440        1037 x 778   1.2 screens   ULTRAWIDE

WHAT IS ALREADY RIGHT, and it is worth saying before the complaints: **nothing
overflows at any size.** `document.scrollWidth` equals the viewport width at
all seven, and zero elements escape a scrolling ancestor. The wide tables and
the disassembly scroll inside their own boxes, which is what they are supposed
to do. There are already breakpoints at 900 and 1500 px and the canvas already
uses `aspect-ratio` rather than a fixed height. This is not a page with no
responsive work in it.

**AND A MEASUREMENT THAT KILLED A COMPLAINT I WAS ABOUT TO FILE.** The pins
table is 154 px wide at every one of the seven sizes, which looked like a
column that never uses the room it is given. It is not: 154 px is the natural
width of `Pad | Pin | State`, the table is `flex: 0 1 auto`, and it reads
perfectly at that size in the screenshots. A compact table that stays compact
is correct. Dropped.

THE ACTUAL FAULT IS ONE SENTENCE: **the layout reads width and nothing else.**
`main`'s grid switches at 900 px and 1500 px and never consults the viewport's
height or its aspect ratio, so a 1065 x 1920 portrait monitor is handed exactly
the layout a 1065 x 700 laptop window gets. That is where the numbers above go
wrong:

1. **PORTRAIT WASTES THE SCREEN IT HAS.** On 1065 x 1920 the board -- the one
   panel whose content is a picture and the only one that gets better with
   area, as the existing comment in this stylesheet already says -- is drawn
   382 px wide. That is 36% of the width, on a display with 1,920 px of height
   going spare. The two-column grid is doing it, and two columns is the wrong
   answer for a tall narrow viewport whatever its width happens to be.

2. **SHORT AND WIDE IS WORSE THAN EITHER.** 1585 x 620 clears the 1500 px
   breakpoint, so it gets three columns -- and the board column is then narrow
   enough that the canvas comes out 359 x 269, smaller than on a 375 px phone
   in one dimension. `max-height: 62vh` caps it at 384 px on top of that. A
   window that is wide and short is treated as roomy.

3. **ULTRAWIDE LEAVES VOIDS.** At 3425 px the code panel is 437 px tall in a
   column that runs the full height of the page, so roughly a third of the
   left-hand side is empty while the reader scrolls. Nothing caps how wide a
   panel of prose may get either.

WHAT LANDS. `webui/static/emulator.css` only -- no markup change, no renderer
change, and the canvas keeps deriving its own height from `aspect-ratio` for
the reason its comment gives.

  * ASPECT-AWARE COLUMNS. A `(max-aspect-ratio: ...)` query so that a portrait
    or squarish viewport gets one column with the board full width, whatever
    its pixel width is. This is the whole of fault 1.
  * HEIGHT-AWARE COLUMNS. The 1500 px three-column rule gains a height
    condition, so a wide-and-short window keeps two columns and a board that
    is worth looking at rather than three thin ones. Fault 2.
  * A CEILING ON `main`, so an ultrawide stops stretching panels of prose and
    the voids stop growing with the display. Fault 3.
  * The canvas sized from the viewport in both directions rather than only
    from the column it lands in.

DONE WHEN, and each of these is the same probe re-run rather than a look:
  * `scrollWidth == clientWidth` and zero escaping elements at all seven sizes,
    which is true today and must stay true;
  * on 1065 x 1920 the canvas is at least 70% of the content width, against
    36% today;
  * on 1585 x 620 the canvas is wider than it is on a 375 px phone by more
    than the rounding, which it currently is not by much;
  * on 3425 x 1440 no panel of prose is wider than about 1,200 px;
  * 1351 x 768 and 1920 x 1080, the two most ordinary sizes, are not made
    worse on any of those measures.

LEAST CONFIDENT:
  1. Whether to switch on `orientation` or on a numeric `max-aspect-ratio`.
     Orientation is the clearer word and is exactly a 1/1 threshold; a square
     window is a real shape and belongs on the portrait side of it, which
     argues for the numeric form with a threshold above 1.
  2. The ceiling on `main`. Too low wastes a large display, too high does
     nothing. It should be derived from the widest column that holds text
     rather than picked.

NOT IN THIS TICKET: the board panel being 1,548 px tall at 1351 px, which is
mostly its own caption prose and is a content question rather than a layout
one -- that caption is load-bearing and this ticket is not going to hide it
behind a disclosure to win a screenful.

**Note 2026-08-27:** CLOSED 2026-08-27 in 4727481. The layout reads the viewport's shape now, not only its width, and the board is between 15% and 160% wider at every size that was wrong.

THE FAULT IN ONE SENTENCE: a 1065 x 1920 portrait monitor is 1,065 px wide, past every threshold in the stylesheet, so it was handed the two-column layout meant for a laptop. Two columns costs WIDTH, and width is what a tall viewport has least of. The board came out 382 px, 36% of the page, on a display with 1,920 px of height going spare. It is 999 px and 94% now.

TWO OF MY OWN FIXES WERE MEASURED BACK OUT, and that is the part worth carrying forward. (1) Gating the three-column rule on 700 px of height made a short wide window scroll MORE -- 2.9 screens to 4.1 -- because two columns stack what three place side by side, and vertical room is exactly what a short window lacks. (2) A `max-width: 2100px` on `main` cost the board 47% of its width on a 3440 display, canvas 1037 -> 549, because a third of 2,100 is a much smaller column than a third of 3,425. Neither was a bad idea; both were beaten by the probe, within twenty minutes of being written. Re-measure after every layout change, including your own.

AND TWO COMPLAINTS DIED BEFORE THEY WERE FILED. Nothing overflows at any of the seven sizes -- `scrollWidth` equals the viewport width and zero elements escape a scrolling ancestor -- and the pin table's constant 154 px, which looked like a column that never uses its room, is the natural width of `Pad | Pin | State` and reads perfectly. Measure before filing.

THE TECHNIQUE, WHICH IS REUSABLE: a `window.__probe()` installed once in the page that reports, per viewport, the sideways scroll, the count of elements escaping every scrolling ancestor, the canvas box and its ratio, the longest text line, and the page height in screens. Then resize and call it. Seven sizes, one number each, and every claim in the commit message is one of them.

THE RULE THAT REPLACED A GUESS: `.pins-stage`'s flex basis decides whether the 32-row pin table sits beside the board or drops below it, and the honest form is 'only while the canvas can still be as big as the viewport would allow'. The canvas stops growing at `--stage` tall, so at 4:3 it stops needing width at `--stage * 4 / 3` -- ask for exactly that. Two hand-picked numbers were tried first and each fixed one size and missed another, because a number is not a reason.

WHAT IT COSTS: the table drops below the canvas at more sizes, so the pins panel is taller and the page scrolls more -- 1905 x 1080 goes 1.6 screens to 2.0, 3425 x 1440 goes 1.2 to 1.8. Stated rather than hidden. The board is what that panel is for.

STILL OPEN, AND DELIBERATELY NOT IN THIS TICKET: the board panel is 1,548 px tall at 1351 px and most of that is its own caption prose. That caption is the honest-degradation statement about a composed model and hiding it behind a disclosure to win a screenful would be trading the thing this repository is most careful about for a layout metric. If anybody does take it on, the question is whether the caption can be SHORTER rather than whether it can be HIDDEN.
