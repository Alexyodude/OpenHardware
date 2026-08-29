# Handoff — every board but one, and the turn nothing was checking

    date          2026-08-30 (work spans 2026-08-29 01:50 to 2026-08-30 00:01)
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          84a3a2b  docs(research): the STM32C5's absence, searched
                           with a control this time
    previous      7c31cc9  docs: handoff for the real pins and the vendor PCB
    gate          1,808 passed, 17 skipped   (was 1,772 at 7c31cc9)
    checkers      all eight exit 0
    ticket held   none
    server        the user runs `python webui/emulator_server.py` on
                  127.0.0.1:8088. It was started BEFORE this session and was
                  NOT restarted; nothing in `webui/` changed, so that is fine.
                  Verified serving 25 boards from the current index.
    models        REGENERATED THIS SESSION AND MUST BE in a fresh checkout.
                  Twelve `.glb` and eleven `.obj`, all gitignored. Runbook §3.

**Twenty-five of the twenty-six boards now draw a vendor file, up from
thirteen.** The twenty-sixth is a footprint for a board nobody ships.

Nine tickets closed, five filed. **Four of the nine were reported by the user
in one line each**, and in every case they were right and I was wrong — twice
in a row on the same part. The last of those produced the only structural
change in the session: `Component.turn` stopped being a claim and became a
measurement.

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| The five remaining chips get a model | ACHIEVED | `28294f3`; C6/RP2350/nRF54L15 composed, MG24/nRF54LM20A imported |
| A board's outline is found wherever the vendor drew it | ACHIEVED | `28294f3`; `kicad._fp_graphics`, all four boards 20.955 × 17.780 mm |
| A vendor's 5 µm drawing gap does not refuse a board | ACHIEVED | `28294f3`; `CHAIN_TOLERANCE_MM = 0.02`, bounds 0.00559 and 0.19079 measured |
| The RP2350 draws its own processor | ACHIEVED | `d8a5fee`; `QFN_60_7x7_P0.4`, 804 triangles, nothing below the board |
| A soldered contact lands on the board | ACHIEVED | `d58c5b3`; worst gold at board level is −0.152 mm, i.e. inside, on all five |
| Each USB-C land pattern gets its own receptacle | ACHIEVED | `0452e53`; GCT for four tabs, Amphenol for two board locks |
| A composed part is checked against the vendor's body drawing | ACHIEVED | `f51e564`; `silk_miss` runs on KiCad boards for the first time |
| The parts a person notices are drawn | ACHIEVED | `4d054e5`; 8 packages, 13 placements, antenna/buttons/LEDs/processor |
| A part's TURN is checked, not asserted | ACHIEVED | `d58c5b3`; `contact_miss`, 270 wins by 2–5× on all four boards |
| The ESP32-C5 gets a model | ACHIEVED | `52dec47`; 74 parts, from a PCB the survey said did not exist |
| The STM32C5 gets a model | BLOCKED ON THE VENDOR SHIPPING THE BOARD | `84a3a2b`; controlled negative, three queries, §2.6 |
| The nRF54LM20A draws the same colour as its siblings | BLOCKED ON DECIDING WHETHER TO OVERRIDE A STATED COLOUR | OH-99 |
| The Uno's pad map agrees with its model | BLOCKED ON DECIDING WHICH SOURCE IS RIGHT | OH-96, carried |

---

## 2. Root causes

### 2.1 Two of the five "missing" meshes were inside the PCB archives

**Symptom.** `docs/research/board-models/sources.json` recorded `"mesh": null`
for the MG24 and the nRF54LM20A, and the plan was to compose both.

**Ruled out — the survey was not lazy.** It read the wiki's own sitemap (2,766
pages), filtered per chip, and ran a positive control that found all four known
meshes at the exact URLs `tools/import_3d_model.py` already held. That control
is why its negatives were believed.

**Root cause.** It **classified the LINKS on each page and never opened an
archive.** Both meshes are KiCad assembly exports sitting beside the board file
inside the zip whose link text says PCB:

    MG24         XIAO_MGM240S_KICAD_Prj.step    4,144,806 bytes    21 solids
    nRF54LM20A   XIAO nRF54LM20A.step          17,170,992         677 solids

The control could not catch it, because all four known meshes are behind links
whose text says *model*.

**Fix.** Two `Model` entries in `tools/import_3d_model.py` pointing at the PCB
archives; `extract_step` takes them unchanged, each holding exactly one STEP.

**The nRF54LM20A's STEP header names the wrong board** — `FILE_NAME('XIAO
nRF54l15.step')` — so it was settled by content instead: it holds
`RGB4P-0.65-1X1X0.85MM` and `USON8-0.5-3X2MM`, both on the LM20A's `.kicad_pcb`
and on **neither** the L15's, and its four board solids are named
`XIAO nRF54LM20A_PCB/_pad/_silkscreen/_soldermask`.

**Generalization.** A control proves the search finds what it *looks at*. It
says nothing about what the search never looked at. Every one of the four misses
in this family was found by somebody opening a file for an unrelated reason.

### 2.2 The board outline was not where the C3 put it

**Symptom.** The ESP32-C6's outline measured **1.270 × 12.954 mm**. A XIAO is
20.955 × 17.780.

**Ruled out.** Not a parse failure: `read_board` found 20 `Edge.Cuts` entities,
the same count as the C3 which reads correctly.

**Root cause.** The C6, RP2350 and nRF54L15 draw their **silhouette inside the
`MOUDLE14P-XIAO-HALF-HOLE` footprint** — 4 `fp_line` + 4 `fp_arc` — leaving
only the two routed slots at the top level. `read_board` took `gr_*` only, so
it measured the slots. **1.270 × 12.954 is a plausible small board, not an
error**, which is what makes it dangerous. The C3, the one board the pipeline
was built against, draws everything at the top level.

**Fix.** `kicad._fp_graphics` + `kicad._on_board` transform a footprint's own
`Edge.Cuts` into board space, by the rule `from_kicad` already applied to its
pads. All four then measure 20.955 × 17.780 mm — as does the imported MG24's
PCB solid, from an entirely different file format.

### 2.3 The vendor's own drawing has 5 µm holes in it

**Symptom.** `the outline does not chain: 81 segment(s) left and none touches
(101.504, -66.635)` on the RP2350 and the nRF54L15, with byte-identical entity
counts to the C6 that works.

**Root cause.** Where a routed slot's arc meets its line, Seeed write `66.6404`
against `66.6354` — **0.005 mm**, four times per board. `_near` demanded 1e-4.

**The bounds are measured, not chosen**, across all five composed boards:

    largest gap that MUST close       0.00559 mm   nRF54L15
    closest endpoints that must NOT   0.19079 mm   nRF54L15
                                      1.41421 mm   Arduino Uno

**Fix.** `CHAIN_TOLERANCE_MM = 0.02` — 3.6× the first, 9.5× below the second.
The ceiling is this file's own `ARC_CHORD_MM`, not a vendor's: those near
misses are consecutive points along an arc some *other* entity was expanded
into. `Arduino-Uno.glb` is byte-identical before and after.

### 2.4 "the usb plug is orientated in the wrong way" — wrong three times

**Symptom, verbatim, over three messages:** *"it still looks broken"*, then
*"the usb plug is orientated in the wrong way"*, then *"still wrong usb c
orientation. fix it and fix root cause."*

**The user was right every time and I was wrong twice.** The turn went 0 →
90 → 270.

**Wrong hypothesis 1 (OH-101), and it was a real bug but not this one.** Seeed
use two USB-C land patterns and OH-93 gave both the same model. The GCT part
has four shell tabs; the RP2350's land has **two board locks, both at the
back**, contacts 3.5 mm away. `place` anchors a through-hole part by matching
its legs' centre to the pad centre — right when both describe the same feature,
and these do not. The connector slid forward and its contact row ended 0.42 mm
past the board edge, in mid-air. Fixed by giving the two-lock land the Amphenol
receptacle (56 leg points against the GCT's 502). **Also tried and measured
worse:** anchoring on through-hole pads only moves it 2.263 mm, because the two
locks share one x.

**Wrong hypothesis 2 (OH-105), and this one shipped a worse answer.** The
receptacle *was* also a quarter turn out — its 8.940 mm WIDTH pointed off the
board edge where Seeed's `F.Fab` rectangle says 7.370 × 8.950, so a cable would
have gone in sideways. Correct. But choosing *which* quarter, I measured
triangle area in each end plane, reasoning a mouth is a rim and a back is a
filled face. **What that measured was the thin solder tails crossing the
plane** — 0.38 mm² of tail, not of rim — so it named the BACK as the mouth and
faced the socket into the board.

**Root cause, which is the structural one.** Every judgement in
`CORRESPONDENCE` is verified against vendor data except one:

    the MODEL is right      `confirm` measures its span against the pads
    the PLACE is right      `silk_miss` measures its body against F.Fab
    the TURN is right       nothing

And both checks are provably blind to it. `confirm` compares spans and a half
turn does not change a span — it missed the quarter turn by 0.54 mm.
`silk_miss` compares body CENTRES and a half turn preserves a centre: **the
USB-C reports the identical miss at 0 and at 180 on every board.**

**Fix.** `contact_miss` in `tools/compose_board_3d.py:1524`. A receptacle's
contacts leave at its back and solder to pads; the model says where its
contacts are and the footprint says where their pads are, so put one on the
other. Distance per turn, in mm:

    board                   0        90       180      270
    XIAO-ESP32-C3-DIP     1.861    2.465    1.861    0.922
    XIAO-ESP32-C6-DIP     1.871    2.478    1.874    0.935
    XIAO-RP2350-DIP       3.737    5.110    3.619    0.977
    XIAO-nRF54l15-DIP     3.784    5.191    3.664    0.896

`compose` refuses a stated turn that is not the best by `TURN_MARGIN_MM`, so
**both wrong answers this repo shipped are now rejected by the tool that
shipped them.** Verified by putting each back:

```bash
# turn=0 -> "contacts 1.861 mm from the pads they solder to -- and 270 puts them 0.922"
# turn=90 -> 2.465 mm, the worst of the four
```

**Generalization.** A metric that is *plausible* is not a measurement. The
end-area heuristic had a story attached ("a mouth is a rim") and was exactly
backwards; the tails-to-pads one has two vendor sources and no story. When a
judgement has been wrong twice, stop judging and find the datum.

### 2.5 The body outline the orientation check used had a keep-out in it

**Symptom.** With `silk_miss` newly running on KiCad boards (OH-103), the C6
and nRF54L15 reported a 12.5 mm body for a USB-C that is 8.95 mm wide.

**Root cause.** Those two draw **two** things on `F.Fab`: the body `fp_rect`,
and four loose `fp_line`s forming a 1.651 × 12.5 mm box behind the connector —
the room a cable needs. `_body_of` unioned them. **The RP2350 draws only the
rectangle, and that disagreement between two boards sharing a footprint is what
gave it away.**

**Fix.** `kicad._body_of` prefers a closed outline — `fp_rect` or `fp_poly` —
and reads loose lines only where a footprint draws no closed one, which is how
a chamfered body is drawn. All three then agree: 7.341 × 8.992, 7.370 × 8.950,
7.370 × 8.950 — the real USB-C, and `L7.35` is in Seeed's own part number.

**`BODY_ALLOWANCE_MM` had been measured against the polluted outline** and was
therefore excusing the very part that was wrong. That is the hazard of an
allowance, and it landed on its first outing. Both numbers re-measured.

### 2.6 The ESP32-C5's PCB was published all along

**Symptom.** The survey's §5: *"the C5 has wiki pages, and they offer the shared
`New_XIAO_Series_Footprints.zip` and nothing else. No mesh, no PCB, no DXF, no
dimensioned drawing."*

**Root cause.** Seeed publish the whole KiCad project at
`files.seeedstudio.com/wiki/XIAO_ESP32C5/res/Seeed_Studio_XIAO_ESP32C5.zip`,
865,127 bytes, holding a 1.4 MB `.kicad_pcb` with 98 placements. It is on the
getting-started page among the **twenty** `files.seeedstudio.com` links the
survey says it classified — so the classifier saw it and did not recognise it,
because the archive is named after the BOARD where the C6's says `SCH&PCB` and
the MG24's says `KiCad`.

**The shared footprint library was a decoy and it was opened this time.**
`XIAO-ESP32-C5-DIP.kicad_mod` is in it; its five `(model ...)` blocks name the
RP2040, SAMD21, C3, S3 and nRF52840 STEPs — the boilerplate list §2 of that
document already describes, not one of them a C5.

**The STM32C5, by contrast, is a controlled negative.** Every query run twice,
once for it and once for the C5:

    query                                    ESP32-C5        STM32C5
    the wiki's sitemap, 2,766 pages          14 pages        0 pages
    files.seeedstudio.com/.../res/*.zip      200, 865,127    403
    Seeed-Studio/OSHW-XIAO-Series, 778 paths 5 paths         1 path

The one path is `XIAO-STM32C5-SMD.kicad_mod`, **and that is where the board
entered our catalogue** — `webui/boards/XIAO-XIAO STM32C5-SMD.json` names that
repository and that footprint as its source, and the doubled `XIAO-XIAO` is the
footprint's own name. It is not a board whose CAD is unpublished; it is a
footprint for a board that appears never to have shipped. Its 709 KB is
`User.1`/`User.2` artwork — 2,225 and 1,216 lines of **median length 0.117 and
0.086 mm** — a traced picture, with no height, no part identity and no solid.

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. The gate.
python -m pytest -q
#    -> 1808 passed, 17 skipped in ~5m20s
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"
done
#    -> all eight exit 0

# 2. The tool dependencies. Blender is needed now, not just OpenCASCADE:
#    eleven parts are built rather than fetched.
pip install cadquery-ocp
#    Blender is found by tools/model_from_datasheet.py:BLENDER_HINTS; this
#    machine has "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"

# 3. REGENERATE. Non-optional: every mesh is gitignored.
python tools/model_from_datasheet.py          # 11 parts, ~1 min
#    -> QFN_60_7x7_P0.4.obj 66,265 bytes; QFN_48_6x6_P0.4.obj 54,049
python tools/import_3d_model.py --all         # 6 boards + 5 parts, ~8 min
#    -> MG24.glb 1,571,336; nRF54LM20A.glb 8,262,812
python tools/compose_board_3d.py              # 6 boards, ~4 min, FETCHES
#    -> XIAO-ESP32-C5-DIP.glb 1,197,288 bytes
#    -> 6,054,928 bytes of glTF; index names 25 boards

# 4. Serve it.
python webui/emulator_server.py
#    -> OpenHardware on http://127.0.0.1:8088/
```

**`compose_board_3d.py` downloads now.** `Composition.pcb_chip` makes
`fetch_pcb` reachable — before this session it had no caller anywhere, and a
missing layout printed the command that had just printed it. Six vendor
archives land in `third_party/seeed-pcb/`.

**In the browser:** pick any board from `#board-pick` and it draws with no
firmware and no core built. `XIAO-XIAO STM32C5-SMD` is the only one that draws
a bare slab, and the panel says so. The bench and wiring runbook are unchanged
from the 2026-08-28 handoff §3.

**If the 3D view does not change when you switch boards, the server is
stale** — `board3d.js` is re-read per request, `emulator_server.py` is not.

---

## 4. File inventory

### Changed this session

| File | What changed |
|---|---|
| `tools/kicad.py` | `Placement.body`; `_body_of` (closed outline beats loose lines); `_fp_graphics`, `_on_board` (a footprint's own `Edge.Cuts`) |
| `tools/compose_board_3d.py` | `contact_miss`, `body_allowance`, `CHAIN_TOLERANCE_MM`, `BODY_ALLOWANCE_MM`, `TURN_MARGIN_MM`, `CONTACT_COLOURS`; `Composition.pcb_chip`; four new `Composition`s; 20 new `CORRESPONDENCE` entries; `silk` fed from `F.Fab` |
| `tools/model_from_datasheet.py` | `ModelledPack` + `pack_geometry` + `build_pack`; `ModelledSlab` + `slab_geometry` + `build_slab`; `run_blender` shared with the USB-B |
| `tools/blender/qfn_flatpack.py` | NEW — body, lead ring, exposed pad, pin-1 dot |
| `tools/blender/moulded_slab.py` | NEW — one box, from `F.Fab` and the footprint name |
| `tools/import_3d_model.py` | MG24 and nRF54LM20A `Model`s; `COMPOSED` extended to 15 rows |
| `tests/rules/test_kicad.py` | +11 tests: footprint outlines, the transform, the body layer |
| `tests/rules/test_compose_board_3d.py` | +24 tests: chaining bounds, `EXPLAINS`, contacts, turns, slabs |
| `docs/research/board-models/README.md` | Two corrections, struck through rather than rewritten |
| `docs/research/board-models/sources.json` | `correction`, `correction_2`, `searched` for the STM32C5 |
| `CLAUDE.md` | 23 → 25 boards; two modelled parts, not one |

### Generated, gitignored, present on disk

| File | Bytes |
|---|---|
| `webui/static/models/nRF54LM20A.glb` | 8,262,812 |
| `webui/static/models/MG24.glb` | 1,571,336 |
| `webui/static/models/XIAO-ESP32-C5-DIP.glb` | 1,197,288 |
| `webui/static/models/XIAO-ESP32-C6-DIP.glb` | 1,117,564 |
| `webui/static/models/XIAO-ESP32-C3-DIP.glb` | 1,087,204 |
| `webui/static/models/XIAO-nRF54l15-DIP.glb` | 1,010,152 |
| `webui/static/models/XIAO-RP2350-DIP.glb` | 932,312 |
| `webui/static/models/Arduino-Uno.glb` | 710,408 |
| `third_party/modelled/QFN_60_7x7_P0.4.obj` | 66,265 |
| `third_party/modelled/QFN_48_6x6_P0.4.obj` | 54,049 |
| `third_party/seeed-pcb/RP2350.kicad_pcb` | 3,679,192 |
| `third_party/seeed-pcb/ESP32-C6.kicad_pcb` | 2,756,545 |
| `third_party/seeed-pcb/nRF54L15.kicad_pcb` | 1,643,753 |
| `third_party/seeed-pcb/ESP32-C5.kicad_pcb` | 1,420,973 |

Eight more slab `.obj` files are ~950 bytes each — one box apiece.

### The settled constants, and where

| Constant | Value | File:line |
|---|---|---|
| `CHAIN_TOLERANCE_MM` | 0.02 | `tools/compose_board_3d.py:1189` |
| `SPAN_TOLERANCE_MM` | 3.0 | `:902` — deliberately generous; see 2.4 |
| `CONTACT_COLOURS` | 4 golds | `:1513` |
| `TURN_FROM_CONTACTS_PADS` | 8 | `:1521` |
| `TURN_MARGIN_MM` | 0.3 | `:1577` — winners beat runners-up by 0.94–2.64 |
| `SILK_TOLERANCE_MM` | 1.5 | `:1584` |
| `BODY_ALLOWANCE_MM` | 2.3 / 1.6 | `:1614` — two USB-C packages only |
| `NAMED_BODY_TOLERANCE_MM` | 0.5 | `tools/model_from_datasheet.py:295` |
| `TOUCHING_THE_BOARD_MM` | 0.35 | `tests/rules/test_compose_board_3d.py:446` |
| `CONTACT_OVERHANG_MM` | 0.05 | `:463` |

---

## 5. Open work, highest priority first

### 5.1 OH-102: model the USB-C receptacle Seeed actually fit — *software-only, START HERE*

**Both published 16-pin receptacles are the wrong length**, and it shows on
every composed board:

    Seeed's part, from their own F.Fab and part number   7.37 mm deep
    KiCad GCT USB4105-xx-A_16P                           7.78   (+0.41)
    KiCad Amphenol 12401610E4-2A                         9.20   (+1.83)

That excess is the whole of what `BODY_ALLOWANCE_MM` still excuses, and it is
why two boards' contacts sit 0.16–0.27 mm past the outline instead of inside
it like the other three.

**Every number needed is already in hand**, which is why this is first:

  * the plan — sixteen contacts and two board locks — from the land pattern;
  * the length — `L7.35`, in `USB-31C-F-16P-L7.35.stp`, the name Seeed write
    into their own board file;
  * the width and height — fixed by the USB Type-C specification, the same
    argument the Uno's USB-B height already rests on.

So it is a `ModelledSlab`'s bigger sibling with no invented dimension.
`tools/blender/qfn_flatpack.py` is the nearest shape to copy. Start:

```bash
python tools/model_from_datasheet.py --list
grep -n "USB2.0-TYPE-C" tools/compose_board_3d.py
```

Done when `BODY_ALLOWANCE_MM` empties and `CONTACT_OVERHANG_MM` reaches 0.

### 5.2 OH-106: a symmetric part can be half a turn out — *software-only*

`silk_miss` compares body centres and a half turn preserves one, so any
symmetric part is invisible to it. A mutation turning the Uno's `DIL28-3` from
90 to 270 **survives the whole suite today.** `contact_miss` (2.4) fixed this
for parts with ≥8 surface-mount pads; a DIP has none. The ticket names three
candidates, cheapest first — the pin-1 marker, which OH-100 already reads for
the RP2350's QFN, is the general one.

### 5.3 OH-99: the nRF54LM20A draws green — *software-only*

It is the only board of the twenty-five that is not dark, and the green is a
separate soldermask solid the KiCad exporter coloured **by default** — its own
`.kicad_pro` says `pcb_color: rgba(0,0,0,0.000)`, the alpha-zero UNSET that
OH-97 already refused to read as a claim. Fixing it means overriding a colour
the file DOES carry, which reverses a stated invariant. Needs the care OH-97
got, not an edit.

### 5.4 OH-98: the vendors state their own component models — *software-only*

Three of the four new boards carry `(model ...)` blocks naming KiCad's library
(59, 57 and 83 of them), which would turn most of `CORRESPONDENCE` from a
judgement into a reading. Not done because their `MOUDLE14P` footprint carries
five whole-XIAO alternates and **`Seeeduino XIAO SAMD21 v4.step` is not
hidden** — a naive reader stands a complete SAMD21 board on top of the RP2350.

### 5.5 OH-96: which of the two Uno sources is right — *software-only*

Carried unchanged. Five pads sit 1.21–3.84 mm from any pin. **Do not close it
by widening `PIN_REACH_MM`.**

### 5.6 The render itself, if the user raises it again

They said *"the blender render is also not that great"*. **Blender does not
render anything here** — it is invoked `--background` purely to author geometry
and write OBJ, so neither Cycles nor EEVEE is involved. Every image is
three.js/WebGL in `webui/static/board3d.js`. One thing measured in passing and
not acted on: the board's **underside is unlit black**, with no fill from
below. No ticket; the user has not asked for it as work.

### 5.7 Carried unchanged

**OH-84**, **OH-71** (P3), the Uno's `Y1`/`Y2` in `compose_board_3d.ABSENT`,
**OH-8**, **OH-11**, **OH-36** (Cortex-M33, *held by a live session lock*
`agent-oh36` — do not steal it), **OH-64**, **OH-38**, **OH-9**. The PCB
artwork as a texture is still blocked on the GPL question in
`rules/licence-hygiene.md`.

---

## 6. Commits this session

```
84a3a2b docs(research): the STM32C5's absence, searched with a control this time
837bed0 chore(tickets): file OH-109, the STM32C5 is a footprint and not a board
52dec47 feat(tools): the ESP32-C5 draws, from a PCB the survey said did not exist
289c700 chore(tickets): file OH-108, the C5's PCB was published all along
d58c5b3 fix(tools): the turn is measured, not claimed, and the USB-C is 270
5b16993 chore(tickets): file OH-107, the turn nothing was checking
a19ce4a fix(tools): the USB socket faces off the board, so a cable could reach it
2c5f925 chore(tickets): file OH-105 and OH-106, the USB-C the user saw facing wrongly
4d054e5 feat(tools): the missing parts are slabs the vendor already gave the size of
65f0a61 chore(tickets): file OH-104, the parts the user noticed were missing
f51e564 feat(tools): a composed part is checked against the body its vendor drew
e868892 chore(tickets): file OH-103, the orientation check that never ran on a XIAO
0452e53 fix(tools): the USB-C sits on the board, instead of hanging off the end of it
37d282c chore(tickets): file OH-101 and OH-102, the USB-C the user saw hanging off
d8a5fee feat(tools): the RP2350 draws its own chip, modelled because nobody publishes one
cebf56f chore(tickets): file OH-100, the RP2350's own chip is the hole in its board
28294f3 feat(tools): five more XIAOs draw, and two of them had a mesh all along
46a768f chore(tickets): file OH-98 and OH-99, both found by OH-93 5.1 reading vendor files
```

Closed: **OH-93, OH-100, OH-101, OH-103, OH-104, OH-105, OH-107, OH-108,
OH-109.** Filed and left open: **OH-96 (carried), OH-98, OH-99, OH-102,
OH-106.** No core, no ABI and no board count changed.

**A ticket file is claimed by its own ticket**, so every filing is a separate
commit from the work — the pattern §8.3 of the last handoff records.

---

## 7. Visual verification

Every frame in `.playwright-mcp/`, re-shot at the CURRENT state after the last
turn fix, driven in Chrome through Python Playwright against the user's own
server.

**`oh93-XIAO-ESP32-C6-DIP.png`.** A black board. At the left edge a cream
ceramic block — the chip antenna, the largest thing on the board and absent
until this session. Above it the round gold U.FL socket. Centre, the ESP32-C6's
black QFN-32 with its lead ring. At the right edge a bright steel USB-C shell
lying with its long axis ALONG the edge, its row of gold solder tails inboard
on the board and the shell overhanging outward. A small black button lower
right, a yellow LED, and ~50 passives.

**`oh93-XIAO-RP2350-DIP.png`.** Black board; the RP2350's QFN-60 in the centre
with a visible lead ring on all four sides — modelled here, not fetched. A gold
crystal left of it, two black buttons on the left edge, the USON-8 flash above,
a white LED lower right. The USB-C at the right edge is the Amphenol and is
DARK rather than steel: `#1d1d1d` in its own STEP. That is the model author's
colour, not a bug — see OH-102.

**`oh93-XIAO-ESP32-C5-DIP.png`.** Black board, 74 parts. The QFN-48 processor
centre-left, the gold U.FL socket at the left edge, a crystal below it, the
dark USB-C at the right edge, two LEDs, and a dense field of 0201s. Composed
from a PCB this repository's own survey said did not exist.

**`oh93-XIAO-nRF54LM20A-DIP.png`.** The imported vendor assembly, and the
richest of the set: a GREEN board — the only one — with castellated half-holes
as grey cylinders down both long edges, a shielded can upper-left, a BGA ball
field visible as a dotted grid, a white LED, a button, a U.FL socket and a grey
USB-C shell. Green because the vendor's exporter coloured the soldermask solid
by default; OH-99.

**`c3usb-close.png` → `c3usb2-close.png`.** The one that took three attempts.
Before: the receptacle's gold contact row on the OUTER side, the shell facing
its closed back off the board. After: the tails sit inboard, landing on the
pads they solder to, with the shell overhanging the edge — the arrangement
`contact_miss` picked, not one judged by eye.

**`rp2350-close.png` → `rp2350fix-close.png`.** Before: the connector visibly
floating, its gold pins hanging in mid-air past the board edge. After: seated,
but dark — the geometry-right Amphenol in place of the good-looking wrong one.

---

## 8. Known limitations, and things not to waste time on

### 8.1 A stale server looks exactly like a bug in the page

Unchanged and it cost a round again. `emulator_server.py` loads once;
`board3d.js` is re-read per request. **Nothing in `webui/` changed this
session**, so the user's pre-existing server is serving current code — verified
at 25 boards.

### 8.2 Three mutations survive on purpose, and all three are equivalent

Recorded in the code beside each so nobody hunts them twice:

  * the exposed pad's y-negation in `pack_geometry` — an exposed pad is
    centred, so `-0.0 == 0.0`;
  * the contact centroid's z-negation in `contact_miss` — every part it runs on
    has its contact field on the board's centre line, within 0.044 mm;
  * `fp_text` in `_body_of` — text nodes carry `at`, not `start`/`end`, so
    adding the tag is structurally a no-op.

### 8.3 `tools/tickets.py` still derives a session id from the parent pid

Unchanged from §8.2 of the last handoff. **Set `OH_SESSION_ID` explicitly** for
every ticket command; every one this session did.

### 8.4 The one console 400 on a cold page is still expected

One request, one 400, same as before OH-94. Not a regression.

### 8.5 A heredoc patch to a scratch file failed silently three times

Editing a scratch script with `python - <<'PY'` + `str.replace` and no
assertion produced a no-op three times, and twice that showed up as a
*surviving mutation* that was really a broken mutation. Use `Edit`, or assert
the substitution took. This is the heredoc trap the last handoff records,
wearing different clothes.

### 8.6 Residuals unchanged

`X4122` from the D3D backend compiling three.js's PMREM shader; the capacitor
lid's straight terminator; wire penetration 0.289 mm; `PYI034` on `__enter__`
in all four cores; `core.avr.abi.Cpu` after `close()` segfaults; `#6f6651`
still unidentified. `ruff check tools/` reports 38 findings, **identical before
and after this session** — measured by stashing.
