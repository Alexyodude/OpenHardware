---
id: OH-98
title: The vendor names its own component models and nothing here reads them
status: done
priority: P2
created: '2026-08-29'
---

CLAIMS NOTHING, for the reason OH-97 records: these are OH-93's files while
that ticket is open, and a second open claim on the same paths is a lock
nobody is using.

`tools/kicad.py` says, of a `.kicad_pcb`:

> Absent: `(model ...)` blocks -- Seeed strips them -- so a placement names a
> FOOTPRINT and not a mesh, and the step from one to the other is a judgement
> that has to be confirmed against pad geometry rather than trusted.

**That is true of exactly one of the four boards read so far, and it is the
one the pipeline was built on.** Counted 2026-08-29:

    ESP32-C3      0 model blocks     <- the board OH-93 US-1..US-4 was written against
    ESP32-C6     59
    RP2350       57
    nRF54L15     83

So for three boards in four the correspondence `tools/compose_board_3d.py`
derives by measurement is **stated outright by the people who made the board**,
in the form `(model "${KICAD7_3DMODEL_DIR}/Capacitor_SMD.3dshapes/
C_0402_1005Metric.step")`. Reading it would turn most of `CORRESPONDENCE` from
a judgement into a reading.

## WHY THIS WAS NOT SIMPLY DONE IN OH-93 5.1

Because the statements are **evidence and not proof**, and every one of the
four ways they can be wrong was found in the four files already on this disk:

  * **Most name files the vendor does not publish.** `IPEX GEN4`,
    `BUTTON_TD1183SA`, `WLCSP20`, `ANT_KH5220-A36 v3`,
    `320011419_ST-USB-3316T.stp` -- Seeed's own library under `${AMZPATH}`,
    which `tools/kicad.py` already records as a path they do not ship. Only
    the `${KICAD7_3DMODEL_DIR}` ones can be fetched at all.
  * **A named model may not exist.** The RP2350 asks for
    `Crystal_SMD_SeikoEpson_FA238-4Pin_2.5x2.0mm`; KiCad's library holds no
    such file, and the `FA238V` it does hold is a 2.0 x 1.6 mm part.
  * **A statement may be about the picture and not the part.** The RP2350
    gives its ESD diode `R_0201_0603Metric` -- a RESISTOR -- and gives `L0603`
    both `L_0603_1608Metric` and `R0603` in the same file.
  * **A statement may be catastrophically wrong and enabled.** Their
    `MOUDLE14P-XIAO-HALF-HOLE` footprint carries five alternates, each a
    WHOLE XIAO BOARD. Four are `(hide yes)`. **`Seeeduino XIAO SAMD21 v4.step`
    is not**, so a reader that took the vendor at their word would stand a
    complete SAMD21 board on top of the RP2350.

That last one is the ticket. A naive read is not merely imperfect, it is
worse than the measurement it would replace -- and it looks like a rendering
bug rather than a data bug.

## WHAT THE SHAPE PROBABLY IS

`confirm` already exists and already refuses a model that does not span its
pads; it is what makes a stated model usable. So: prefer the vendor's
statement where it names a `${KICAD7_3DMODEL_DIR}` path that resolves, skip
`(hide yes)`, **and put it through `confirm` exactly as a table entry is**,
falling back to `CORRESPONDENCE` otherwise. The `(offset ...)` and
`(rotate ...)` a model block may carry are non-identity in 4 and 5 places per
board and would have to be applied, which is the real work here.

## DONE WHEN

A board's stated models are used where they resolve and are confirmed;
`CORRESPONDENCE` shrinks to the boards and packages that state nothing; the
SAMD21-on-the-RP2350 case is a test rather than a paragraph; and the claim in
`tools/kicad.py` quoted at the top is corrected either way.

## DONE, 2026-08-30 -- and the measurement inverts this ticket's premise

`tools/kicad.py` reads the blocks: `StatedModel` and `_models_of`, with the
path, the `(hide yes)` flag and the `(offset)` / `(rotate)` / `(scale)`
transforms. `Placement.models` carries them, hidden ones included.

**`CORRESPONDENCE` does not shrink, because reading the statements would
change almost nothing.** This ticket says reading them "would turn most of
`CORRESPONDENCE` from a judgement into a reading". Counted across all five
KiCad boards, by (board, package) pair:

    17   name a model that can actually be fetched -- and ALL 17 already
         AGREE with what the table derived by measurement
    43   state nothing usable: silent, or naming Seeed's own ${AMZPATH}
     3   state a model where this repository draws nothing
     1   DISAGREES

**The one disagreement is one where the VENDOR is wrong.** The C6 states
`USB_C_Receptacle_GCT_USB4105-xx-A_16P` for its `USB2.0-TYPE-C`, and that
model is 7.78 mm deep where the same footprint's own `Description` says 7.3 --
which is what OH-102 modelled the part over. So acting on the statements would
change nothing except in the single place where it would make the picture
worse.

That is the honest answer to "prefer the vendor's statement where it
resolves": there is nothing to prefer. The blocks are now READ and REPORTED,
which is what makes the claim checkable, and the correspondence stays a
measurement.

## THE FOUR WAYS THEY GO WRONG, NOW GUARDED OR PINNED

  * **Unpublished libraries.** `StatedModel.variable` is the guard, and it is
    the one that matters: only `${KICAD7_3DMODEL_DIR}` is fetchable at all.
  * **The whole-XIAO alternates.**
    `test_a_whole_xiao_board_is_never_a_usable_model_for_a_part_on_one` is the
    test this ticket asked for. **What stops the catastrophe is the PATH and
    not the hide flag** -- all five alternates are `${AMZPATH}`, and the one
    Seeed left visible is `Seeeduino XIAO SAMD21 v4.step`.
    `test_the_visible_alternate_on_the_half_hole_footprint_is_the_wrong_board`
    pins that so the guard above cannot quietly stop being interesting.
  * **A named file the library does not hold**, and **a statement about the
    picture rather than the part** (a resistor's mesh on a diode): both are
    covered by not acting on the statements at all.

## THE CLAIM AT THE TOP IS CORRECTED

`tools/kicad.py` said `(model ...)` blocks were absent because "Seeed strips
them". **True of the ESP32-C3, and only of it** -- which is the board the
pipeline was built on. The other four carry 59, 57, 91 and 83. The header now
says so, and says what reading them turned out to be worth.

Four mutations, all killed.
