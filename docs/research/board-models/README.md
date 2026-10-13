# What geometry each unmodelled board actually has

Measured 2026-08-28 for OH-93. `sources.json` beside this file is the machine
copy, and every byte count in it is a `Content-Length` the file server returned
while the survey ran rather than a figure transcribed out of a terminal.

> ## CORRECTION, 2026-08-29 — two of the meshes exist
>
> **The MG24 and the nRF54LM20A each ship a full KiCad assembly export INSIDE
> the archive this table calls their PCB**, and both are now imported by
> `tools/import_3d_model.py` rather than composed:
>
>     MG24         XIAO_MGM240S_KICAD_Prj.step    4,144,806   21 solids
>     nRF54LM20A   XIAO nRF54LM20A.step          17,170,992  677 solids
>
> §1 below is right about what it measured and wrong about what it concluded.
> The survey **classified the LINKS on each wiki page and never opened an
> archive**, so a mesh behind a link whose text says PCB was invisible to it —
> and the positive control could not catch that, because all four known meshes
> are behind links whose text says model.
>
> That is the third time this shape of miss has happened here: OH-29 read
> GitHub when the files were on the wiki; OH-93 read a GitHub census that said
> Seeed publish no PCB; this read the wiki, but only its surface. **A control
> proves the search finds what it looks at. It says nothing about what the
> search never looked at**, and every one of the three was found by somebody
> opening a file for an unrelated reason.
>
> Both byte counts here were re-checked on 2026-08-29 and both archives are
> unchanged, so nothing else in this document has gone stale.

Sixteen of the twenty-six boards draw an extruded slab. This is the answer to
"what could be drawn instead", per chip, and to the prior question nobody had
asked in one place: **what does Seeed publish at all?**

## The result

The `mesh` column is corrected per the note above; everything else is as
measured on 2026-08-28.

| chip | boards | mesh | vendor KiCad PCB | outline | how it is drawn |
|---|---|---|---|---|---|
| ESP32-C3 | 3 | — | 339,671 | DXF 115,093 | composed |
| ESP32-C6 | 2 | — | 1,126,886 | — | composed |
| MG24 | 2 | **4,144,806, in the PCB zip** | 1,583,091 | — | **imported** |
| RP2350 | 2 | — | 1,145,969 | DXF 1,418,153 | composed |
| nRF54LM20A | 2 | **17,170,992, in the PCB zip** | 4,307,651 | — | **imported** |
| nRF54L15 | 2 | — | 1,305,099 | — | composed |
| ESP32-C5 | 2 | — | **865,127, in `res/`** | — | composed |
| STM32C5 | 1 | — | — | — | slab |

Twenty-five of the twenty-six boards are drawn from a vendor file. One is not, and §4 says what
that means. **The vendor's own mechanical model is preferred wherever one
exists** — the order `CLAUDE.md` states — so the two chips that turned out to
have one are imported rather than composed, and their correspondence
judgements were never needed.

## 1. There is no mesh, and here is why that is a finding and not a shrug

The search reads the wiki's own `sitemap.xml` — 2,766 pages — and filters it
per chip, rather than guessing page names. Guessing is what makes this kind of
survey wrong: the wiki names pages `XIAO_ESP32C3_Getting_Started`,
`getting-started-xiao-rp2350` and `xiao_mg24_getting_started`, and no single
pattern catches all three.

**The negative was not believed until the positive control passed.** The same
query, pointed at the four chips this repository already imports meshes for,
finds all four at the exact URLs `tools/import_3d_model.py` holds:

    SAMD21     18,255,477   Seeeduino-XIAO/res/seeeduino-xiao-samd21-3d-model.zip
    RP2040      3,399,090   XIAO-RP2040/res/seeed-studio-xiao-rp2040-3d-model.zip
    ESP32-S3    4,382,912   SeeedStudio-XIAO-ESP32S3/res/...-esp32s3-3d_model.zip
    nRF52840    8,849,412   XIAO-BLE/seeed-studio-xiao-nrf52840-3d-model.zip

A negative result from an uncontrolled search is a measurement of the search.
This repository has already paid for that once — see §3.

## 2. The footprints' own model references are a copy-paste, not a mapping

`tools/import_3d_model.py` says the `.kicad_mod` files in
`third_party/seeed-xiao` "have been naming them the whole time", which is true
of the four that exist and misleading about the rest. All 37 footprints name
**the same five** STEP files:

    ${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeeduino XIAO SAMD21 v4.step
    ${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeed Studio XIAO RP2040 v26.step
    ${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeed Studio XIAO-ESP32-C3.step
    ${AMZPATH}/3dmodels/AMz3D.3dshapes/XIAO-ESP32S3 v2.step
    ${AMZPATH}/3dmodels/AMz3D.3dshapes/XIAO-nRF52840 v15.step

`XIAO-ESP32-C5-DIP.kicad_mod` names the C3 model. `XIAO-MG24-DIP.kicad_mod`
names it too. It is one boilerplate list pasted into every footprint in the
library, so **reading it as a per-board mapping would send someone hunting for
files that do not exist** — and would suggest a C5 model is available when
nothing of the sort is published.

The one genuinely new name in that list, `Seeed Studio XIAO-ESP32-C3.step`,
lives under `${AMZPATH}` — a KiCad path variable pointing at a library Seeed
does not ship — and appears nowhere on the file server.

## 3. The PCB files were missed the same way the meshes were

`docs/research/board-sources/sources.json` records `model_3d: no` and
`pcb_layout: no` for Seeed, and `tools/get_board_sources.py` prints
"publishes no schematic_source, schematic_pdf, pcb_layout, model_3d,
board_support".

**That survey read `Seeed-Studio/OSHW-XIAO-Series` on GitHub. These files are
on the wiki.** It is precisely the error OH-29 made about the meshes — a census
of the git repository, reported as a census of the vendor — and it has now
misled twice in the same place. `import_3d_model.py`'s own docstring narrates
the first occurrence at length; this is the second.

The correction: **Seeed publishes a full KiCad project — schematic and PCB —
for six of these eight chips.** Verified by downloading rather than by
trusting a hyperlink. `XIAO_ESP32C3_v1.3_KiCad_260116.zip` contains

    202003511_XIAO ESP32C3_v1.3_SCH&PCB_260116/XIAO ESP32C3_v1.3.kicad_pcb

at version 20241229, with **68 footprint placements and 21 `Edge.Cuts`
graphics** — a real outline and a real position and rotation for every part.
That is the same class of source as Arduino's EAGLE `.brd`, which is what
`tools/compose_board_3d.py` already turns into the Uno.

## 4. What is *not* free about it

**The PCB carries no `(model ...)` blocks.** Seeed stripped them, so a
placement names a footprint and not a mesh. And the footprint library ids are
Seeed's own rather than KiCad canonical:

    28x  XIAO ESP32C3_v1.3:C0201       1x  XIAO ESP32C3_v1.3:QFN32G-0.5-5X5MM
    14x  XIAO ESP32C3_v1.3:R0201       1x  XIAO ESP32C3_v1.3:USB2.0-TYPE-C
     6x  XIAO ESP32C3_v1.3:TP-D45MIL   1x  XIAO ESP32C3_v1.3:SOD-523
     2x  XIAO ESP32C3_v1.3:SOT-25      1x  XIAO ESP32C3_v1.3:X4-SMD-2.0X1.6X0.5MM

So the step from a placement to a drawable mesh is a table of **judgements**,
exactly as the Uno's `CORRESPONDENCE` is, and it gets the same treatment:
`confirm()` measures the element's own pads against the mesh it was handed and
refuses one that does not span them. `C0201` is a 0201 capacitor and
`Capacitor_SMD:C_0201_0603Metric` is KiCad's model of one — but a mapping
believed *because the names rhyme* is the `DIL28-3`-to-`DIP-8` failure, which
draws a plausible little part in exactly the right place and is wrong.

## 5. The one that cannot be drawn (it was three)

**`XIAO-ESP32-C5-DIP`, `XIAO-ESP32-C5-SMD`** — ~~the C5 has wiki pages, and
they offer the shared `New_XIAO_Series_Footprints.zip` and nothing else. No
mesh, no PCB, no DXF, no dimensioned drawing.~~

**WRONG, corrected 2026-08-29 by OH-108.** Seeed publish the whole KiCad
project at
`files.seeedstudio.com/wiki/XIAO_ESP32C5/res/Seeed_Studio_XIAO_ESP32C5.zip`,
865,127 bytes, holding a 1.4 MB `.kicad_pcb` with 98 placements. Both boards
are composed now.

It is on the getting-started page, among the twenty `files.seeedstudio.com`
links this survey says it classified — so **the classifier saw it and did not
recognise it**, because that archive is named after the BOARD where the C6's
says `SCH&PCB` and the MG24's says `KiCad`. The shared footprint library was
a decoy, and it was opened this time: it does hold
`XIAO-ESP32-C5-DIP.kicad_mod`, whose five `(model ...)` blocks name the
RP2040, SAMD21, C3, S3 and nRF52840 STEPs — the boilerplate list §2 already
describes, and not one of them a C5.

**`XIAO-XIAO STM32C5-SMD`** — the last board without a model, and the only
one whose absence has been searched with a CONTROL. Every query below was run
twice on 2026-08-29, once for it and once for the ESP32-C5 whose PCB is now
composed:

    query                                    ESP32-C5        STM32C5
    the wiki's sitemap, 2,766 pages          14 pages        0 pages
    files.seeedstudio.com/.../res/*.zip      200, 865,127    403
    Seeed-Studio/OSHW-XIAO-Series, 778 paths 5 paths         1 path

The wiki has 241 XIAO pages and not one is an STM32; its five STM32 pages are
a LoRa-E5, two ODYSSEY boards, a SOM and an ADC hat.

**The one path is a footprint**, `XIAO-STM32C5-SMD.kicad_mod`, and that is
where this board entered our catalogue —
`webui/boards/XIAO-XIAO STM32C5-SMD.json` names that repository and that
footprint as its source, and the doubled `XIAO-XIAO` is the footprint's own
name rather than a typo. So this is not a board whose vendor has not published
its CAD; it is a footprint for a board that appears never to have shipped.

Its 709 KB looks promising until it is measured: `User.1` holds 2,225 lines of
median length 0.117 mm and `User.2` another 1,216 at 0.086 mm. Thousands of
tenth-of-a-millimetre strokes is a traced PICTURE of the board, with no
height, no part identity and no solid in it. See OH-109.

**CORRECTED 2026-10-13 (OH-163 step 4's dated re-check; OH-231): everything
above about the STM32C5 was true on 2026-08-29 and is not true now.** It is kept
as the record of that day, as the C5 paragraph above is. Seeed has since
published the board:

- the wiki has a getting-started page,
  `wiki.seeedstudio.com/xiao_stm32c5_getting_started/` (200), and five siblings
  in its sitemap (`_pin_multiplexing`, `_application`, `_canfd_usage`,
  `_with_micropython`, `_with_stm32cubeide`); the product page is
  `seeedstudio.com/XIAO-STM32C5-p-7011.html`;
- the KiCad project is
  `files.seeedstudio.com/wiki/XIAO_STM32C5/res/XIAO_STM32C5_v1.0_SCH%26PCB.zip`,
  1,559,346 bytes, sha256
  `676070c1e35935869c39a52a624dec7cb937850e6d6e12401b061786aab35b1b`, holding
  `XIAO STM32C5.kicad_pcb` and six `.kicad_sch` files (the files are dated
  2026-07-27 to 07-31). It holds no STEP;
- the schematic PDF is `.../res/Seeed-Studio-XIAO-STM32C5-v1.0.pdf`, 1,397,144
  bytes, sha256 `6e32a6515372feb5b5c6e16864d37423c9d938b442907b26ea556fc93f35ce21`,
  with no text layer;
- Seeed's Zephyr board is `zephyr/stm32/boards/seeed/xiao_stm32c5/` in
  `Seeed-Studio/platform-seeedboards` at
  `57250b6f9157a5600eb2b232cc90618b3ed1b3be` (2026-10-08), "extracted from
  schematic 04 XIAO Header&STM32C5.kicad_sch"; the MCU is STM32C5A3CG in a
  UFQFPN48.

`XIAO-STM32C5-pinout_sheet.xlsx` is not a source: its XIAO column is misaligned
against the ST table (it puts `BAT_EN` on PE2, where the PCB puts `D8`/`SPI_SCK`
and puts `BAT_EN` on PA15).

So "a footprint for a board that appears never to have shipped" is retracted,
and so is "these three keep the extruded footprint": the board has a vendor PCB
to be composed from (OH-231 step 3, which waits on OH-226). What this
paragraph does not settle is the archive's licence: its schematic sheets carry
a `LOGO_CC_BY-SA_4.0` symbol, as the sheets of the C3, C5, C6, MG24 and
nRF54LM20A archives do, and it holds no licence file. That is recorded in
`sources.json` as seen, not as a grant.

**Every XIAO shares a 21 × 17.5 mm outline and a 14-pad castellated edge, and
that is exactly why a sibling's mesh must not be substituted.** It would be
plausible, correctly sized, correctly placed, and a drawing of a different
board — which is the one failure mode this repository's geometry rules exist to
prevent. These three keep the extruded footprint, and the panel says so.
