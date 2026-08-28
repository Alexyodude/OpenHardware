---
id: OH-93
title: A 3D model for every board whose vendor publishes a PCB but no mesh
status: open
priority: P1
created: '2026-08-28'
touches:
- tools/kicad.py
- tools/compose_board_3d.py
- tools/board_sources.py
- docs/research/board-models/*
- tests/rules/test_kicad.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
---

**16 of the 26 boards draw an extruded slab.** Ten have a model: the Arduino
Uno, composed by OH-75 from Arduino's EAGLE board file, and nine XIAOs sharing
the four meshes OH-72 imported from Seeed's wiki. The other sixteen span eight
chips and have had nothing to draw.

## WHAT IS PUBLISHED, MEASURED RATHER THAN ASSUMED

**No mesh exists for any of the eight.** Searched the wiki's own sitemap --
2,766 pages -- rather than guessing page names. **The search was proved to work
before its negative was believed:** the identical query finds all four models
this repository already imports, at the exact URLs `tools/import_3d_model.py`
holds. A negative result with no positive control is a measurement of the
scraper, which is the shape of mistake OH-29 made here once already.

**The footprints' own `(model ...)` lines are not evidence.** All 37
`.kicad_mod` in `third_party/seeed-xiao` name the same five STEP files under
`${AMZPATH}` -- one boilerplate list copy-pasted into every footprint. So
`XIAO-ESP32-C5-DIP.kicad_mod` naming `Seeed Studio XIAO-ESP32-C3.step` says
nothing whatever about a C5 model, and reading it as a per-board mapping would
have sent someone looking for six files that do not exist.

**But Seeed publishes the vendor KiCad PCB project for six of the eight**, and
a PCB layout is exactly what `tools/compose_board_3d.py` turns into a board for
the Uno -- which has no published mesh either. `get_board_sources.py` records
`publishes no pcb_layout` for Seeed because that survey read the GitHub
repository; these files are on the wiki. **Same miss as OH-29's, in the same
place, for the same reason**, and OH-29's line should be corrected rather than
left to mislead a third time.

| chip | boards | mesh | vendor PCB | outline |
|---|---|---|---|---|
| ESP32-C3 | 3 | no | `XIAO_ESP32C3_v1.3_KiCad_260116.zip` 339,671 | DXF |
| ESP32-C6 | 2 | no | `XIAO_ESP32_C6_v1.0_SCH&PCB_260114.zip` 1,126,886 | -- |
| MG24 | 2 | no | `XIAO_MG24_v1.0_KiCad_260114.zip` 1,583,091 | -- |
| RP2350 | 2 | no | `XIAO_RP2350_v1.0_SCH&PCB_240626.zip` 1,145,969 | DXF |
| nRF54LM20A | 2 | no | `XIAO_nRF54LM20A_V1.0_SCH&PCB_260508.zip` 4,307,651 | -- |
| nRF54L15 | 2 | no | `nRF54L15_KICAD.zip` 1,305,099 | -- |
| **ESP32-C5** | **2** | **no** | **none** | **none** |
| **STM32C5** | **1** | **no** | **none** | **none** |

Verified by downloading rather than by trusting a hyperlink: the C3 zip holds
`XIAO ESP32C3_v1.3.kicad_pcb`, version 20241229, **68 footprint placements and
21 `Edge.Cuts` graphics.**

## THE PART THAT IS NOT FREE

**The PCB files carry no `(model ...)` blocks** -- Seeed stripped them -- and
the footprint library ids are Seeed's own rather than KiCad canonical:

    28x  XIAO ESP32C3_v1.3:C0201        1x  XIAO ESP32C3_v1.3:QFN32G-0.5-5X5MM
    14x  XIAO ESP32C3_v1.3:R0201        1x  XIAO ESP32C3_v1.3:USB2.0-TYPE-C
     2x  XIAO ESP32C3_v1.3:SOT-25       1x  XIAO ESP32C3_v1.3:SOD-523

So the mapping from a placement to a real mesh is a table of **judgements**,
exactly as the Uno's `CORRESPONDENCE` is, and it gets the same treatment:
`confirm()` measures the element's own pads against the mesh it was handed and
refuses one that does not span them. `C0201` is a 0201 capacitor and
`Capacitor_SMD:C_0201_0603Metric` is the KiCad model of one -- but a mapping
believed because the names rhyme is the `DIL28-3` to `DIP-8` failure, which
draws a plausible little part in the right place and is wrong.

## THREE BOARDS CANNOT BE DONE AND MUST SAY SO

`XIAO-ESP32-C5-DIP`, `XIAO-ESP32-C5-SMD` and `XIAO-XIAO STM32C5-SMD`. The C5
has a wiki page and publishes neither mesh nor PCB nor outline; the sitemap has
no XIAO STM32 page at all. **The XIAO family shares a 21 x 17.5 mm outline and
that is exactly why substituting a sibling's mesh is forbidden here** -- it
would be plausible, correctly sized, in the right place, and a drawing of a
different board.

## DONE WHEN

Thirteen of the sixteen draw a model composed from their vendor's own PCB, with
every component's position, rotation and height off a published source and none
typed in; the remaining three keep the extruded slab and the panel names that as
the source; and the survey above lives in `docs/research/board-models/` rather
than in one session's memory.

Built vertically -- the ESP32-C3 end to end first, then the other five.
