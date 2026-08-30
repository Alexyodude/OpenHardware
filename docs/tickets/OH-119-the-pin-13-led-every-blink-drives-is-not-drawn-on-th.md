---
id: OH-119
title: The pin-13 LED every Blink drives is not drawn on the Uno, and nothing says
  so
status: done
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

## DONE, 2026-08-30

**The Uno draws 47 elements, up from 15.** Twelve CORRESPONDENCE rows with
measured spans: the four CHIP-LED0805 indicators including L, eleven
C0603-ROUND, both R0603-ROUND, the four CAY16 arrays
(R_Array_Convex_4x0603), both MINIMELF diodes, the SMB, the L1812 polyfuse,
both 0805 ferrites, the Z1/Z2 varistors, T1's SOT-23, U2's SOT-23-5 and
U5's MSOP-8. `confirm` accepted every span on the first compose except one:

**KiCad's Fuse library stops at 1210** -- checked against GitLab's own tree,
28 files -- so F1's 1812 body is borrowed from `C_1812_4532Metric`, the same
part-vs-moulding argument the varistars make with the 0603 capacitor body,
stated in both whys.

Four ABSENT rows close the world: 61 test points (0.8 mm bare pads), three
fiducials (1.016 mm discs), two solder jumpers, the schematic frame -- each
with its measurement and each saying no library was searched because there
is no body to look for.

**The closed-world test is the DONE-WHEN**:
`test_every_uno_package_is_drawn_or_its_absence_is_explained` fails by name
on any package in neither table, so the silent-drop path cannot reopen on
this board. The pin-13 LED is pinned by name on the shipped mesh besides.
(The general per-board counting of silent drops stays OH-125.)

Two knock-ons, both recorded: the silk/box coverage counts moved 15 -> 47
(both tests updated with the note), and a fetched LED lens brought in
#0000ff, a FIXED POINT of the sRGB transform -- linear(255) is 1.0 -- which
an albedo test asserted must differ from its bytes. It cannot; the guard now
exempts pure-0x00/0xff colours with the argument, and the equality half
still covers them.

Two mutations (the LED row deleted; the test points' ABSENT row deleted),
both killed. The composed Uno screenshot is
`.playwright-mcp/oh119-uno-parts.png`: a populated board -- DIP-28,
electrolytics, QFN, MSOP-8, diodes, arrays, ferrites, LEDs -- on navy with
routing and shining pads.
