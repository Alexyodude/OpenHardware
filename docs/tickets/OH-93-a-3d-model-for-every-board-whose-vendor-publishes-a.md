---
id: OH-93
title: A 3D model for every board whose vendor publishes a PCB but no mesh
status: done
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

## DONE, 2026-08-29

**Twenty-three of the twenty-six boards draw a vendor file.** The three that do
not are the two ESP32-C5s and the STM32C5, exactly as the section above says.

The DONE-WHEN said "thirteen of the sixteen draw a model COMPOSED from their
vendor's own PCB", and that is not what happened, because the premise moved:

    imported from a vendor mesh    13 boards   SAMD21, RP2040, ESP32-S3,
                                               nRF52840, MG24, nRF54LM20A
    composed from a vendor PCB     10 boards   Uno, ESP32-C3, ESP32-C6,
                                               RP2350, nRF54L15
    extruded slab                   3 boards   ESP32-C5 x2, STM32C5

### THE MG24 AND THE nRF54LM20A HAVE MESHES, INSIDE THE PCB ARCHIVES

    MG24         XIAO_MGM240S_KICAD_Prj.step    4,144,806    21 solids
    nRF54LM20A   XIAO nRF54LM20A.step          17,170,992   677 solids

Both are full KiCad assembly exports -- the same class of file as the four this
repository already imports -- and `docs/research/board-models/sources.json`
recorded `"mesh": null` for both. That survey **classified the LINKS on each
wiki page and never opened an archive**, so a mesh behind a link whose text
says PCB was invisible; and its positive control could not catch it, because
all four known meshes are behind links whose text says model. Corrected in
place, both files, with the reason.

`CLAUDE.md` states the preference order and the vendor's own mechanical model
is first, so these two are imported. Their correspondence tables were never
needed.

### THE OUTLINE WAS NOT WHERE THE C3 PUT IT

`read_board` took `Edge.Cuts` from the top level only. The C6, the RP2350 and
the nRF54L15 draw their **silhouette inside the `MOUDLE14P-XIAO-HALF-HOLE`
footprint** -- 4 `fp_line` and 4 `fp_arc` -- and leave only the two routed
slots at the top level. Reading the top level alone measured the ESP32-C6 as
**1.270 x 12.954 mm**: its slots, and nothing else, which is a plausible small
board rather than an error. The C3, the board the pipeline was built on, is
the one that draws everything at the top level.

So `read_board` now transforms a footprint's own `Edge.Cuts` graphics into
board space, by the same rule `from_kicad` already applied to its pads. All
four then measure 20.955 x 17.780 mm, as does the imported MG24's PCB solid --
four boards, two entirely different file kinds, one number.

### AND THE VENDOR'S DRAWING HAS HOLES IN IT

The RP2350 and the nRF54L15 miss by **0.005 mm** where a slot's arc meets its
line, four times each. `_near` demanded a tenth of a micron. The bounds are
measured and two orders apart -- largest gap that must close 0.00559 mm,
closest endpoints that must not join 0.19079 mm -- and `CHAIN_TOLERANCE_MM` is
0.02, with the ceiling set by this file's own `ARC_CHORD_MM` rather than by a
vendor.

### WHAT IS DRAWN, AND WHAT IS NOT

    XIAO-ESP32-C6-DIP    59 parts   27,221 triangles   1,116,000 bytes
    XIAO-RP2350-DIP      50 parts   22,640 triangles     924,168 bytes
    XIAO-nRF54l15-DIP    62 parts   25,436 triangles   1,050,404 bytes
    XIAO-MG24-DIP        imported   39,545 triangles   1,571,336 bytes
    XIAO-nRF54LM20A-DIP  imported  225,798 triangles   8,262,812 bytes

Every mapping was accepted by `confirm`. Six new `ABSENT` entries say what is
not drawn and where the search for it went -- including **the RP2350 itself**,
because KiCad's `Package_DFN_QFN` holds no QFN-60 among its 191 files and its
QFN-56 would put a false part name in the model's own parts list. The C3 also
gained the two reasons the 2026-08-29 handoff recorded as "left undrawn"
without one.

### FILED, NOT DONE

  * **OH-98** -- three of the four boards DO carry `(model ...)` blocks naming
    KiCad's own library. Not read, because their `MOUDLE14P` footprint carries
    five whole-XIAO alternates of which `Seeeduino XIAO SAMD21 v4.step` is not
    hidden: a naive reader stands a SAMD21 board on top of an RP2350.
  * **OH-99** -- the nRF54LM20A draws green, from a separate soldermask solid
    the KiCad exporter coloured by default. Its own `.kicad_pro` says
    `pcb_color: rgba(0,0,0,0.000)`, alpha zero, which is the UNSET that OH-97
    already refused to read as a claim.

18 mutations, 16 killed; the two survivors reword a sentence without changing
a claim. Gate: 1,772 -> 1,780 passed, 17 skipped; all eight checkers exit 0.
