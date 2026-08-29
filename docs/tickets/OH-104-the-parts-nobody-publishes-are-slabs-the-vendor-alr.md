---
id: OH-104
title: The parts nobody publishes are slabs the vendor already gave the size of
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/model_from_datasheet.py
- tools/blender/*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Raised by the user: the ESP32-C6 "is missing some of its parts".

It is. So are the RP2350 and the nRF54L15, and the biggest thing missing from
two of them is the **chip antenna** -- 5.2 x 2 x 1.1 mm, the largest object on
either board after the USB socket and the main chip.

## WHAT IS MISSING, AND WHY IT WAS

    package                             boards        largest side
    ANT2P-5.2x2x1.1MM                   C6, L15         5.20 mm
    MIC6P-0.94-4X2X1.1MM                L15             4.27
    WLCSP47-0.3-2.451X2.245X0.42MM      L15             2.45   <- the nRF54L15
    SW4-SMD-2.8-2.6X1.6X0.53MM          C6, RP2350      2.60   <- the buttons
    WLCSP20-0.4-2.4X1.9X0.5MM_SMALL     L15             2.45
    IPEX-GEN4-SMD-1.7X1.7X1.0MM         L15             1.70
    LED4-0.8-1.6X1.5X0.55MM             RP2350          1.60
    LED4-0.85-1.6X1.5X0.6MM             RP2350          1.60

Every one is absent for the same honest reason: no library publishes that
part, and this repository does not draw a part it cannot source. OH-93
recorded each with the library it searched.

## WHAT CHANGED: THE VENDOR STATES THE WHOLE BODY

OH-100 modelled the RP2350's QFN-60 from Seeed's own footprint and established
the standard: **every number is the vendor's or cited.** Applying the same
reading to these, Seeed give the complete body of each in two places:

  * **`F.Fab`** -- KiCad's assembly layer, readable since OH-103 -- gives the
    plan outline to three decimals, for the parts that draw one.
  * **The footprint NAME** gives length, width AND height:
    `ANT2P-5.2x2x1.1MM`, `SW4-SMD-2.8-2.6X1.6X0.53MM`,
    `IPEX-GEN4-SMD-1.7X1.7X1.0MM`. A moulded package's height is the one
    dimension a land pattern cannot express, so a footprint states it in the
    name or nowhere -- the same argument OH-100's 0.900 mm rests on.

Where both exist they agree: the nRF54L15's `ANT2P` names 5.2 x 2 and its
F.Fab measures 5.20 x 2.00.

So these need no invented dimension at all. A moulded chip package IS a slab;
drawing its stated envelope is not an approximation of the part, it is the
part.

## WHAT STAYS ABSENT, AND WHY

  * **`BUTTON_TD1183SA`** (the C3's and nRF54L15's buttons). Its name states
    no height and no layer carries one. A button STANDS PROUD -- its height is
    the whole point of it -- so a slab of invented thickness is exactly the
    defect this project keeps re-learning. It keeps its `ABSENT` entry.
  * **`PMOS_...`, `DFN1006-2L`, `ESD-0201/0402`, `BGA6`, `WLCSP4`,
    `DFN6-0.4`, `X2SON4`** -- all under 1.5 mm. Nothing forbids them; they are
    not what a person notices, and each added part is another line of
    judgement to keep true.
  * **Test points and logos.** Not components.

## DONE WHEN

The C6 draws its antenna, the RP2350 its buttons and LEDs, and the nRF54L15
its own processor; each is marked `modelled` so the page says it was built
here; every dimension traces to `F.Fab` or to the vendor's own footprint name,
with a test that says which; and a package whose name states no height is
still refused rather than guessed at.

## DONE, 2026-08-29

Eight packages, thirteen placements across three boards:

    board                modelled parts
    XIAO-ESP32-C6-DIP    ANT1 antenna, K1 and K2 buttons
    XIAO-RP2350-DIP      K1, K2, D4 and LED1, plus OH-100's QFN-60
    XIAO-nRF54l15-DIP    ANT1 antenna, U6 the processor, U4, ANT2, U8 the mic

**The name and the assembly outline agree, which is what makes reading a
dimension out of a string safe:**

    package                            F.Fab plan      name says       apart
    ANT2P-5.2x2x1.1MM                  5.200 x 2.000   5.2 x 2 x 1.1   0.000
    SW4-SMD-2.8-2.6X1.6X0.53MM         2.600 x 1.600   2.6 x 1.6 x .53 0.000
    MIC6P-0.94-4X2X1.1MM               2.257 x 4.267   4 x 2 x 1.1     0.267
    WLCSP47-0.3-2.451X2.245X0.42MM     2.440 x 2.240   2.451 x 2.245   0.011
    WLCSP20-0.4-2.4X1.9X0.5MM_SMALL    1.950 x 2.450   2.4 x 1.9 x 0.5 0.050
    IPEX-GEN4-SMD-1.7X1.7X1.0MM        1.700 x 1.700   1.7 x 1.7 x 1.0 0.000
    LED4-0.8-1.6X1.5X0.55MM            1.500 x 1.600   1.6 x 1.5 x .55 0.000
    LED4-0.85-1.6X1.5X0.6MM            1.600 x 1.530   1.6 x 1.5 x 0.6 0.030

`NAMED_BODY_TOLERANCE_MM` is 0.5, against a worst case of 0.267.

**Every one was accepted by `silk_miss`**, which OH-103 had just switched on
for these boards -- so each landed within 1.5 mm of where Seeed's own assembly
drawing puts it, checked rather than looked at.

### WHAT STAYS ABSENT, AND THE ONE THAT MATTERS

`ABSENT` falls from 9 entries to 5: `QS`, `RESONATOR`, both spellings of the
load switch, and **`BUTTON_TD1183SA`**.

That last one is the interesting refusal. It has an `F.Fab` outline -- 3.01 x
2.61 mm -- so its plan is known, and its height is not: the name states none
and no layer carries one. A button STANDS PROUD of the board, which is the
entire point of it, so a slab of invented thickness would be exactly the
defect this whole area exists not to draw. Its entry now says which number is
missing, so the next reader does not model it from the outline it does have.

The C6's and RP2350's switches ARE drawn, because `SW4-SMD-2.8-2.6X1.6X0.53MM`
states 0.53 mm. Two buttons, one modelled and one not, on the same rule.

### NOT DRAWN, AND NOT WORTH A LINE EACH

Everything remaining is under 1.5 mm -- the load switches, `DFN1006-2L`, the
ESD diodes, `BGA6`, `WLCSP4`, `DFN6-0.4`, `X2SON4` -- plus test points and
logos, which are not components. Nothing forbids them; they are not what a
person notices, and each is another judgement to keep true.

8 new tests. Gate: 1,800 -> 1,804 passed, 17 skipped; all eight checkers
exit 0. `ruff check tools/` reports the same 38 findings before and after.
