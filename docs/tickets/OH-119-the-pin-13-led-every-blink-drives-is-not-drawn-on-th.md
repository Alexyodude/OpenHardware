---
id: OH-119
title: The pin-13 LED every Blink drives is not drawn on the Uno, and nothing says
  so
status: open
priority: P2
created: '2026-08-30'
---

_No description yet._

CLAIMS NOTHING yet; re-claims tools/compose_board_3d.py when it starts.

**From the 2026-08-30 model survey.** `compose` drops any element whose
package is in neither `CORRESPONDENCE` nor `ABSENT` with no model and no
stated reason -- `component = by_package.get(element.package); if component
is None: continue`. Measured on the Uno: 99 of its 116 elements are dropped
silently. Past the 61 test points and 3 fiducials, the real parts:

    4x CHIP-LED0805    ON, RX, TX, and L -- the pin-13 LED every Blink drives
    11x C0603-ROUND    C1-C11        2x R0603-ROUND
    4x CAY16 (RN1-4)   2x MINIMELF (D2,D3)   1x SMB (D1)
    1x L1812 (F1)      2x 0805 (L1,L2)       2x CT/CN0603

**The project's stated purpose is watching a blink, and the LED that blinks
is absent.** The XIAOs already draw LEDs from `LED_0402_1005Metric` and
passives from the same KiCad libraries; only the EAGLE package names are
unmapped, so the fix is ~5-8 CORRESPONDENCE rows with measured spans in each
`why`, plus ABSENT rows for anything honestly refused.

DONE WHEN the Uno's four indicator LEDs and its large passives draw; every
still-dropped element is in ABSENT with a reason; and the drop-with-no-reason
path is counted the way `silk_unread` is (that half is OH-125).
