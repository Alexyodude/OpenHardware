---
id: OH-109
title: The STM32C5 is a footprint in a library and not a board anybody ships
status: done
priority: P2
created: '2026-08-29'
touches:
- docs/research/board-models/*
---

`XIAO-XIAO STM32C5-SMD` is the last of the twenty-six boards without a 3D
model. **It cannot have one, and this time the negative is controlled** --
which matters, because the four before it were not:

    OH-29     read GitHub when the files were on the wiki
    OH-93     read a GitHub census that said Seeed publish no PCB
    OH-93.1   classified wiki LINKS and never opened an archive
    OH-108    opened the wrong archive and never looked in res/

## THE SEARCH, AND THE CONTROL THAT MAKES IT MEAN SOMETHING

Every query below was run twice on 2026-08-29: once for the STM32C5 and once
for the ESP32-C5, whose PCB this repository now composes. **The control finds
the C5 every time.**

    query                                    ESP32-C5        STM32C5
    the wiki's sitemap, 2,766 pages          14 pages        0 pages
    files.seeedstudio.com/.../res/*.zip      200, 865,127    403
    Seeed-Studio/OSHW-XIAO-Series, 778 paths 5 paths         1 path

The wiki has 241 XIAO pages and not one is an STM32. Its five STM32 pages are
a LoRa-E5 module, two ODYSSEY boards, a SOM and an ADC hat for the Pi. A web
search for the product returns ESP32-C5 results and nothing else.

## WHAT THE ONE PATH IS

`Seeed Studio XIAO Series Library/XIAO-STM32C5-SMD.kicad_mod` -- a footprint,
in the library, and that is the whole of it. **It is also where this board
entered our catalogue**: `webui/boards/XIAO-XIAO STM32C5-SMD.json` names its
source as that repository and that footprint, and the doubled `XIAO-XIAO` is
the footprint's own name rather than anybody's typo.

So this is not "a board whose vendor has not published its CAD". It is a
footprint for a board that appears never to have shipped, and our catalogue
lists it because `tools/import_board.py` derives boards from the library.

## AND THE ARTWORK IS NOT GEOMETRY

The footprint is 709 KB, by far the largest in the library, which looks
promising until it is measured:

    User.1   2,225 lines, median 0.117 mm, total 339 mm
    User.2   1,216 lines, median 0.086 mm, total 379 mm
    F.SilkS      7 lines, median 13.970 mm

Thousands of tenth-of-a-millimetre strokes is a traced PICTURE of the board,
not an outline of anything on it. There is no height, no part identity and no
solid -- extruding it would be exactly the invented geometry
`tools/model_from_datasheet.py` exists to refuse.

## DONE WHEN

The survey says this rather than "the sitemap contains no XIAO STM32 page",
which is true and is not the useful part; and nobody runs these three queries
again. **Twenty-five of twenty-six is the finished state**, not a gap.

What would retire it: Seeed shipping the board and publishing its project,
exactly as they did for the other seven.

## DONE, 2026-08-29

The survey records the three queries, their control, and what the one
surviving path actually is. Nobody needs to run them again.

**Twenty-five of the twenty-six boards have a 3D model, and that is the
finished state rather than a gap.** The twenty-sixth is a footprint.

No code changed. Gate unaffected at 1,808 passed, 17 skipped.
