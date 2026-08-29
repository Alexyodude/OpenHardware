---
id: OH-103
title: The check that knows which way a part faces never ran on a KiCad board
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/kicad.py
- tools/compose_board_3d.py
- tests/rules/test_kicad.py
- tests/rules/test_compose_board_3d.py
---

Raised by the user: "the c three components are not all in the correct
orientation."

**Measured, they are** -- see below -- but the reason nobody could say so is
that the check which would answer the question has been dormant on every
composed KiCad board since OH-93 built them.

## THE GAP

`silk_miss` opens with:

> **This is the check that knows which way a part faces**, and it exists
> because nothing else did. `confirm` measures a model against the pads, and
> `place` anchors it on them -- both of which are blind to a part turned
> 180 degrees, because a pin field is very often symmetric about its own
> centre.

Its first line is `if element.silk is None: return None`, and
`compose_board_3d.from_kicad` **never sets `silk`**. It builds
`eagle.Element(name, library, package, pads, x_mm, y_mm, rotation, mirrored)`
and the field defaults to `None`.

So the Arduino Uno is checked and the nine composed XIAO boards are not. The
one bug this exists to catch -- a part 180 degrees out, which measures
perfectly against symmetric pads -- cannot be caught on any of them.

## WHAT KiCAD PUTS THERE INSTEAD

EAGLE draws a body on layers 21 and 51. KiCad has a layer reserved for exactly
this: **`F.Fab`**, the assembly drawing, which is the part's own body outline
rather than the silkscreen printed around it. OH-100 already relies on that
convention to read the RP2350's 7.000 x 7.000 mm body.

Run by hand over the four composed boards, comparing each placed mesh against
its footprint's `F.Fab`:

    board                bodies   worst miss
    XIAO-ESP32-C3-DIP        46    0.000 mm
    XIAO-ESP32-C6-DIP        52    2.181 mm   USB1 only
    XIAO-RP2350-DIP          48    1.452 mm   USB1 only
    XIAO-nRF54l15-DIP        61    1.872 mm   USB1 only

**Every part on the C3 is within a thousandth of a millimetre of where Seeed
drew it**, and the only outliers anywhere are the USB-C receptacles, whose
miss is the known OH-102 length error rather than a rotation.

## WHY THIS IS WORTH DOING ANYWAY

The measurement above is a thing somebody ran once. `SILK_TOLERANCE_MM` is
1.5, and the C3's worst is 0.000 -- so the guard would sit with three orders
of magnitude of headroom on the boards that are right, and would have caught
the Uno's 7.50 mm barrel jack. It is the difference between "I checked" and
"it is checked".

The USB-C's 1.45-2.18 mm miss is the awkward part: it exceeds the 1.5 mm
tolerance on three boards. That is a real disagreement between a published
model and the vendor's own body outline, not a false alarm -- see OH-102 --
and it has to be recorded rather than tolerated by widening the number.

## DONE WHEN

`silk_miss` runs on a KiCad board; the C3's 0.000 mm is a test rather than a
paragraph; and the USB-C's known length error is admitted in one place instead
of quietly raising the tolerance for every part on every board.

## DONE, 2026-08-29

`silk_miss` runs on a KiCad board. `kicad.Placement` carries a `body` read
from `*.Fab`, and `from_kicad` hands it to `eagle.Element.silk` negated into
the composer's y-up frame like every pad beside it.

**The answer to the question that raised this: the ESP32-C3 is correctly
oriented.** 49 of its 68 placements carry a body outline and it composes with
the check live, so every one of them is inside 1.5 mm of where Seeed drew it.
The measurement that says so is now a run rather than a paragraph.

    board                bodies read   composes with the check
    XIAO-ESP32-C3-DIP        49/68     yes
    XIAO-ESP32-C6-DIP        56/83     yes, with the USB-C allowance
    XIAO-RP2350-DIP          67/85     yes
    XIAO-nRF54l15-DIP        84/102    yes, with the USB-C allowance
    Arduino Uno              unchanged, still from EAGLE layers 21 and 51

Every `.glb` is byte-identical, which is what says this is a guard and not a
change to the geometry.

### THE USB-C IS ADMITTED, NOT TOLERATED

`BODY_ALLOWANCE_MM` is keyed by PACKAGE and holds the two USB-C footprints,
each with its measurement. It is not a wider `SILK_TOLERANCE_MM`: every other
part on those boards is still held to 1.5 mm, and the C3's worst is 0.000. Its
docstring says what retires it, which is OH-102 -- both published receptacles
are longer than the `L7.35` part Seeed name and do not publish.

### TWO THINGS THE MUTATIONS FORCED

  * **`body_allowance` is a one-line function** because the lookup was an
    expression inside `compose`, which needs OpenCASCADE and a whole board to
    reach. A mutation replacing it with `max(BODY_ALLOWANCE_MM.values())` --
    handing every part on every board the widest allowance in the table --
    survived the entire suite. Same reason `colour_key` exists.
  * **The y-negation is tested against a fixture and not a board.** Across the
    four composed XIAOs, 256 parts carry a body and the most off-centre in y
    misses by 0.127 mm, so a sign flip moves it a quarter of a millimetre. The
    fixture puts a body 1 mm off its own origin, where a flip moves it 2.

11 mutations, 11 killed. 8 new tests. Gate: 1,792 -> 1,800 passed, 17 skipped;
all eight checkers exit 0.
