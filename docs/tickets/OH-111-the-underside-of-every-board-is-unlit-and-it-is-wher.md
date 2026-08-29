---
id: OH-111
title: The underside of every board is unlit, and it is where the pin labels are printed
status: done
priority: P1
created: '2026-08-30'
touches:
- webui/static/board3d.js
- tests/webui/test_board3d.py
---

Asked for by the user in one word: **"improve."**

The 2026-08-30 handoff §5.6 recorded this and left it: *"the board's underside
is unlit black, with no fill from below. No ticket; the user has not asked for
it as work."* OH-110 changed what that costs, by putting the vendor's own
printing down there.

## THE MEASUREMENT

Every light in `LIGHTS` has a positive y -- 0.84, 0.58, 0.46. Nothing in the
scene comes from below, so the underside gets only `ENVIRONMENT_SHARE`.
Luminance over every pixel that is not the page, XIAO ESP32-C3:

    from above    median 82.6    p90 229.9    mean 115.6
    from below    median  0.0    p90  34.4    mean  12.5

**The median pixel on the underside is pure black.** That is not "darker
because it faces away". That is unlit.

## AND IT IS NOT A BLANK SIDE

What OH-110 put there, per board:

    board                back pads   back silkscreen strokes
    XIAO-ESP32-C3-DIP           44                      1514
    XIAO-nRF54l15-DIP           68                       942
    XIAO-ESP32-C6-DIP           58                       608
    XIAO-ESP32-C5-DIP           58                         3
    XIAO-RP2350-DIP             62                         3
    Arduino Uno                154                         0

On the C3 those 1,514 strokes are the words **"Seeed Studio"**, the battery
pads marked + and -, and the outlines around both header rows. They render,
and nobody can see them.

## NOTHING DOWN THERE CASTS, AND THAT IS MEASURED

The three lights above cast because they are a three-sample estimate of how
much sky a crevice can see. A bounce off a bench is not sky. And there is
nothing under the board to occlude it: of the 1 to 21 parts each vendor places
on the back of these boards, `CORRESPONDENCE` draws **none** -- 36 test points,
16 more, 12 more, three Seeed logos, a CE logo and one solder jumper. Not one
has a body, and their copper and their ink are already drawn.

## DONE WHEN

One light comes from below; it does not cast; its share is ADDED to
`LIGHT_TOTAL` rather than taken out of the three, because a light from below
cannot brighten a surface facing up; and the intensity is swept and measured
rather than chosen.

## NOT IN SCOPE

The soldermask colour (`BOARD_MASK` is a stated judgement, and OH-99 is the
ticket that would reverse it); traces, vias and copper pours, which are the
next layer of vendor data nobody draws.

**Note 2026-08-30:** DONE in 8e7f64d. BOUNCE, one light from below, share 0.25 of LIGHT_TOTAL ADDED rather than shared out, not casting. Swept 0.00-0.50 and measured: the topside mean moves 0.7% across the whole range, which is the claim that a light from below cannot brighten an upward face. At 0.25 the underside median is 41% of the topside's and its p90 is 3.9x the mask around it, so the printing reads. Three existing tests went red and were narrowed with the argument rather than deleted.
