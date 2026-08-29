---
id: OH-100
title: The RP2350 draws with a hole where its own chip goes
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/model_from_datasheet.py
- tools/blender/*
- tools/compose_board_3d.py
- tests/rules/test_model_from_datasheet.py
- tests/rules/test_compose_board_3d.py
---

`XIAO-RP2350-DIP.glb` draws 50 parts and the RP2350 is not one of them. The
centre of the board is empty, which is the most conspicuous absence of
anything left off any board here.

OH-93 5.1 put it in `ABSENT` with a reason, and the reason is still true:

> Sixty-one pads spanning 6.800 x 6.800 mm, which is a QFN-60 on 0.4 mm pitch
> in a 7 x 7 mm body. **KiCad's `Package_DFN_QFN` holds no QFN-60 at all** --
> 191 files listed on 2026-08-29, and the nearest is
> `QFN-56-1EP_7x7mm_P0.4mm`. That is the right body and the right pitch with
> four leads missing, and drawing it would put `U4 (QFN-56...)` in this
> model's own parts list, which is a false statement about what is on the
> board.

That stands. **The QFN-56 must not be used.** What changes is that "no
published model" is not the end of the list.

## THE SEARCH, SO NOBODY REPEATS IT

`CLAUDE.md` states four sources in order of preference. The first three are
exhausted, checked 2026-08-29:

  1. **The vendor's own mechanical model.** Seeed ship a STEP inside the PCB
     archive for the MG24 and the nRF54LM20A and NOT for the RP2350 --
     `step=0` when its archive is listed.
  2. **A published model of the same package.** KiCad's `Package_DFN_QFN` has
     no QFN-60 among 191 files; nothing in the library matches `-60[-_]`; and
     all 115 top-level `.3dshapes` directories were listed for a Raspberry Pi
     or MCU-specific library, of which there is none.
  3. **The manufacturer's own STEP.** Raspberry Pi publish KiCad reference
     designs for the RP2350A and RP2350B minimal viable boards and the VGA
     carrier, and **no STEP, STP or 3D package model for the chip**.

So it is source 4, `tools/model_from_datasheet.py`, which exists for exactly
this and has one part in it.

## WHY THIS IS THE STRONGEST KIND OF SOURCE-4 PART

That file's rule is "every number is either the vendor's or cited", and for
this part **all but one are the vendor's, read out of their footprint rather
than typed here**:

    body            fp_rect on F.Fab, -3.5..3.5 both axes   7.000 x 7.000 mm
    leads           60 pads, 0.6 x 0.18 mm, ring at +-3.400 mm
    per side        15, pitch 0.400 mm, spanning -2.800..2.800
    exposed pad     pad 61, 3.45 x 3.45 mm, centred
    pin-1 marker    fp_circle on F.Fab at (-3.170, -3.173), r 0.127

`F.Fab` is KiCad's own convention for the part's body outline, so the 7 x 7 is
a READING and not a parse of the package name.

The one number that is not geometry is the **0.900 mm height**, and it is
still Seeed's: it is in the footprint name, `QFN60-0.4-7X7X0.9MM`. It goes in
`cited` saying exactly that, so a reader can see which number came from a
drawing and which from a name.

## THE TRAP

The USB-B was built from an EAGLE package, whose y runs UP. This is a KiCad
footprint, whose y runs DOWN, and `compose_board_3d.from_kicad` negates y for
every pad it reads. **A model built without that negation is mirrored**, and a
QFN body is four-fold symmetric so it draws perfectly -- except for the pin-1
marker, which ends up in the wrong corner and is the only thing on the part
that says which way round it is.

## DONE WHEN

The RP2350 draws its own chip; `U4` names a model whose name does not claim a
lead count the part does not have; the part is marked `modelled` so the page
says so; `QFN60-0.4-7X7X0.9MM` leaves `ABSENT`; and the mirror above is a test
rather than a paragraph.

## DONE, 2026-08-29

`U4 (QFN_60_7x7_P0.4)` is drawn. The RP2350 goes from 50 parts to 51 and from
22,640 to 23,444 triangles; `XIAO-RP2350-DIP.glb` is 973,664 bytes.

**It is the second modelled part in the repository and the first on a XIAO**,
so it appears in the model's `modelled` list as well as its `drawn` one and
the page says it was built here rather than fetched.

    QFN_60_7x7_P0.4    804 triangles, 3 colours
    body               7.000 x 7.000 x 0.900 mm
    leads              60, flush at z 0..0.230, NONE below the board
    pin-1 dot          (-3.170, +3.173), the -x +y corner

`confirm` accepts it: it spans the 6.800 x 6.800 mm pad field, and having
nothing below the board it passes the mounting check a surface-mount part has
to.

### THE MIRROR HAPPENED, AND THE FIRST TEST OF IT WAS WRONG TOO

`pack_geometry` negates y, as `from_kicad` does for pads. The first version of
the test asserted the pin-1 dot's NEAREST lead is lead 1 -- and it is lead 60,
by four microns:

    dot -> lead  1    0.438 mm
    dot -> lead 60    0.434 mm

A corner dot sits between the last lead of one side and the first of the next,
so "nearest" is noise and a test built on it passes or fails on rounding. What
mirroring actually changes is the SIGN of y, so the assertion is the QUADRANT,
plus that the two nearest leads are the pair meeting at that corner.

### WHAT THE MUTATIONS FOUND

10 mutations, 9 killed, and three of the five that survived the first run were
real gaps rather than bad mutations:

  * **The lead ring cannot show the mirror.** It is symmetric about y, so
    negating it or not gives the same SET of positions and an identical mesh.
    Only a pad-by-pad comparison sees it, and that is now a test.
  * **`F.Fab` and `F.CrtYd` differ in y only** -- -3.51..3.49 against
    -3.50..3.50, the same 7.000 mm span shifted by a hundredth. The first
    test asserted x and passed on both.
  * **Nothing tied the 0.9 mm height to where it came from.** It now has to
    equal the last field of the vendor's own footprint NAME.

The one survivor left is equivalent rather than a gap: an exposed pad is
centred, so `-0.0 == 0.0` and no test can see that negation. Said in the code
so nobody hunts it twice.

`USB_B_PN61729.obj` is byte-identical before and after `run_blender` was
extracted, which is what says the refactor moved nothing.

6 new tests. Gate: 1,783 -> 1,790 passed, 17 skipped; all eight checkers
exit 0.
