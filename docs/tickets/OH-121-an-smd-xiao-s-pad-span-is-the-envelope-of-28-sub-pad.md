---
id: OH-121
title: An SMD XIAO's pad_span is the envelope of 28 sub-pads, and the page pairs axes
  blind
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims tools/compose_board_3d.py and
webui/static/board3d.js when it starts.

**From the 2026-08-30 model survey, RESCOPED: OH-118 landed mid-survey and
fixed the DIP variants** (their pad_span is now the DIP field and their pads
find 14/14 and 24/24 pins in the browser). What stands is the SMD half, and
it is browser-confirmed post-OH-118: XIAO-RP2350-SMD draws at 7.27 px/mm
against a map generated at 8, and finds 18 of 30 pads.

Cause as the survey measured it: `pad_span` for an SMD board is the envelope
of all 28 header SUB-pads (17.780 mm) while the page's map holds one pad per
castellation (15.240 -> 16.5 mm between centres); `scaleFromPads` then
divides pixels of one field by millimetres of another. Using pad CENTRES
drops the miss to 0.52-0.73 mm.

Second half, same file: `scaleFromPads` pairs pixels[i] with span[i] blind to
the quarter turn `placeModel` applies four lines later (+90 when height >
width, never -90, and nothing checks which). Wrong by construction, ~0.5%
today.

DONE WHEN every composed SMD variant's scale comes out at the map's own 8
px/mm; the axis pairing survives the quarter turn; and a portrait board
turned the wrong way fails a test.
