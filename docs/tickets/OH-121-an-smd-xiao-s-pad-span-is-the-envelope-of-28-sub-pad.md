---
id: OH-121
title: An SMD XIAO's pad_span is the envelope of 28 sub-pads, and the page pairs axes
  blind
status: done
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

## DONE, 2026-08-30

**A generated map states its scale as a FIELD, and the statement wins.**
Every derivation always ended "scaled at 8.0 px/mm" and only a person could
read it; `px_per_mm` now rides in the JSON, is emitted by
`tools/import_board.py` for future maps, was stamped into the 25 existing
generated maps FROM each file's own sentence (a migration that restates,
never invents -- and a test holds field to prose per file), is validated by
`pinmap.parse`, forwarded by the pins route, and preferred by `placeModel`
over the two-field fit. The traced Uno map states nothing on purpose -- its
artwork is anisotropic, it has no single true scale -- and keeps the fit,
which is exact there (0.093 mm).

The quarter-turn axis-pairing defect dies with the fit on every generated
map, which is every board but the Uno; `scaleFromPads` survives only as the
traced-map fallback.

**Verified in the browser on a fresh server instance** (the user's own was
not restarted; a second instance on 8091 served the changed Python and was
killed after):

    XIAO-RP2350-SMD     29 -> 30 of 30    scale 0.7272 -> 0.8000
    XIAO-ESP32-C3-SMD   20 -> 22 of 22
    XIAO-nRF54l15-SMD         34 of 34
    XIAO-RP2350-DIP           24 of 24    Arduino Uno  32 of 32, 0.5638 kept

**Every pad on every composed board now finds its own pin.** With OH-115
(the mirror), OH-117 (the lost GNDs), OH-118 (the DIP headers), OH-120 (the
copper finish) and this, the whole chain from board file to wirable pin is
measured end to end.

Three mutations, all killed. Gate 1,893 -> 1,900.
