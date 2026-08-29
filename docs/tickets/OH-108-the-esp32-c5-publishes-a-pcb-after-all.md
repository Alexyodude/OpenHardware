---
id: OH-108
title: The ESP32-C5 publishes a PCB after all, in a zip the survey never opened
status: done
priority: P1
created: '2026-08-29'
touches:
- tools/compose_board_3d.py
- tools/model_from_datasheet.py
- docs/research/board-models/*
- tests/rules/test_compose_board_3d.py
---

Asked for by the user: "get the c5 3d model."

`docs/research/board-models/README.md` §5 says of the two ESP32-C5 boards:

> the C5 has wiki pages, and they offer the shared
> `New_XIAO_Series_Footprints.zip` and nothing else. No mesh, no PCB, no DXF,
> no dimensioned drawing.

**That is wrong.** Seeed publish the whole KiCad project:

    https://files.seeedstudio.com/wiki/XIAO_ESP32C5/res/
        Seeed_Studio_XIAO_ESP32C5.zip                        865,127 bytes
        Seeed Studio ESP32C5.kicad_pcb                     1,420,973
        98 placements, outline 20.955 x 17.780 mm, 2 cutouts

It is on the getting-started page, in the board's own `res/` folder, under
exactly the naming every other XIAO uses.

## HOW THE SURVEY MISSED IT, WHICH IS THE THIRD TIME

`sources.json` records the method: "each page fetched and every
files.seeedstudio.com link classified". The C5's getting-started page carries
**twenty** such links, including this one. So the classifier saw it and did
not recognise it -- the archive is named after the BOARD rather than after its
contents, where the C6's says `SCH&PCB` and the MG24's says `KiCad`.

That is now three misses of the same family:

    OH-29    read GitHub when the files were on the wiki
    OH-93    read a GitHub census that said Seeed publish no PCB
    OH-93.1  classified wiki LINKS and never opened an archive (MG24, LM20A)
    OH-108   opened the wrong archive: took `New_XIAO_Series_Footprints.zip`
             at its word and never looked in `res/`

**The shared footprint library was a decoy and it was checked this time.**
`XIAO-ESP32-C5-DIP.kicad_mod` does exist in it, and its five `(model ...)`
blocks name the RP2040, SAMD21, ESP32-C3, ESP32-S3 and nRF52840 STEP files --
the same boilerplate list pasted into all 34 footprints, already recorded in
§2, and not one of them a C5.

## WHAT IT NEEDS

Twelve of its twenty-two packages are already in `CORRESPONDENCE`. The one
that is not and matters is its own processor:

    QFN48-0.4-6X6X0.9MM_small   49 pads spanning 5.850 x 5.850 mm, EP 3.7x3.7

KiCad publishes `UQFN-48-1EP_6x6mm_P0.4mm_EP4.45x4.45mm` -- right lead count,
right body, right pitch, and **a different part**: `UQFN` is the ultra-thin
height class at 0.6 mm or less where Seeed's own name says 0.9, and its
exposed pad is 4.45 mm against their 3.7. That is the QFN-60 situation from
OH-100, and `ModelledPack` was built for it.

## THE STM32C5 IS STILL NOT DRAWABLE, AND THAT WAS RE-CHECKED

The sitemap holds no XIAO STM32 page of any kind -- searched again on
2026-08-29, and the five STM32 pages it does have are a LoRa module, two
ODYSSEY boards, a SOM and an ADC hat. The board is in this repository's
catalogue and is not on the vendor's wiki. It keeps the extruded slab.

## DONE WHEN

Both ESP32-C5 boards draw a composed model; its processor is drawn from
Seeed's own footprint rather than from a part that is not it; the survey's §5
and `sources.json` say what is actually published; and **25 of the 26 boards
have a model**.

## DONE, 2026-08-29

Both ESP32-C5 boards are composed. **25 of the 26 have a model, up from 23.**

    XIAO-ESP32-C5-DIP   74 parts   28,823 triangles   1,197,288 bytes
                        outline 20.955 x 17.780 mm, 2 cutouts, 98 placements

Twelve of its twenty-two packages were already in `CORRESPONDENCE`; the only
new one is its own processor, and its buttons are its only stated omission --
`BUTTON_TD1183SA` again, which names no height.

Every check passed on the first compose, including OH-107's turn check and
OH-103's body check, which is what says the machinery generalised rather than
being fitted to four boards.

### THE PROCESSOR IS MODELLED, AND THE PUBLISHED PART IS REFUSED ON PURPOSE

    QFN48-0.4-6X6X0.9MM_small   49 pads spanning 5.850 x 5.850, EP 3.7 x 3.7
    body from F.Fab             6.000 x 6.000 mm
    height from the name        0.9 mm

KiCad's `UQFN-48-1EP_6x6mm_P0.4mm_EP4.45x4.45mm` has the right lead count,
body and pitch and is a different part: `UQFN` is the ultra-thin height class
at 0.6 mm or less where Seeed's own name says 0.9, and its exposed pad is
4.45 mm against their 3.7. Its only 6 x 6 neighbours are a Qorvo TQFN66 and a
52-lead VQFN.

### A READER THAT HAD BEEN SPLIT IN TWO

`pack_geometry` had its own `F.Fab` reader, written before `kicad._body_of`
existed, and it looked for an `fp_rect`. **The C5 draws its QFN's body as four
`fp_line`s**, so a part whose outline was perfectly present was refused as
absent -- "0 rectangles on F.Fab". Two readers of one layer meant only one of
them learned what OH-105 taught about closed outlines and keep-out lines, so
`pack_geometry` goes through `_body_of` now.

### AND THE STM32C5 REALLY IS THE LAST ONE

Re-searched 2026-08-29: the wiki's sitemap holds no XIAO STM32 page of any
kind. Its five STM32 pages are a LoRa module, two ODYSSEY boards, a SOM and an
ADC hat. It keeps the extruded slab and the panel says so.

2 new tests. Gate: 1,807 -> 1,808 passed, 17 skipped; all eight checkers
exit 0.
