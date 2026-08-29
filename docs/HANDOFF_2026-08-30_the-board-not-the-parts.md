# Handoff — it was never the parts, it was the board

    date          2026-08-30
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          e5c6b4f  chore(tickets): file and close OH-114, the Type-C
                           that was a box
    previous      89fb302  docs: handoff for every board but one (2026-08-30)
    gate          1,850 passed, 17 skipped   (was 1,808 at 89fb302)
    checkers      all eight exit 0
    ruff          `ruff check tools/` -> 37, the same as at HEAD~12
    ticket held   none
    server        the user runs `python webui/emulator_server.py` on
                  127.0.0.1:8088. Started BEFORE this session and NOT
                  restarted. `board3d.js` is re-read per request and the
                  `.glb` files are served from disk with `Cache-Control:
                  no-store`, so it is serving everything this session made.
                  Verified with `curl` against the file's own md5.
    models        REGENERATED THIS SESSION AND MUST BE in a fresh checkout.
                  Twelve `.glb` and thirteen `.obj`, all gitignored.
                  Runbook §3.

**Six tickets closed. Every one of them was reported by the user in one line,
and every one of them was right.**

    "still poor 3d model. fix them"     -> OH-110
    "improve"                           -> OH-111, OH-112
    "uno ethernet port is poor"         -> OH-113
    "c5 usb port is bloccky"            -> OH-114

The last session and the ten tickets before it answered "the model is poor" by
adding **parts** — a processor, eight slabs, two receptacles. Every one of them
put another box on the same bare slate. **The board itself was never drawn.**
That is the one thing to carry out of this document.

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| The USB-C is the part the vendor states, not the one KiCad publishes | ACHIEVED | `4fdebca`; both land patterns modelled, `BODY_ALLOWANCE_MM` deleted |
| A model anchored on legs lands on the holes those legs go into | ACHIEVED | `4fdebca`; `anchor_of`, `Arduino-Uno.glb` byte-identical at the time |
| A composed board draws its own copper | ACHIEVED | `86de055`; 203–324 front pads a board, worst vertex 0.000 mm outside |
| A castellated half-hole is half a hole | ACHIEVED | `86de055`; `clipped_to`, exact against a convex outline |
| A composed board draws its own silkscreen | ACHIEVED | `86de055`; 3–97 front strokes, 3–1,518 back |
| The Arduino Uno draws copper too | ACHIEVED | `86de055`; `tools/eagle.py` learned pad shape and angle, 400 pads |
| Something lights the underside | ACHIEVED | `8e7f64d`; median luminance 0.0 → 34.0 against a top of 85.0 |
| A composed board draws its routing | ACHIEVED | `99945af`; 312–501 front traces, 82–307 vias, both faces |
| An airwire is not drawn as copper | ACHIEVED | `99945af`; EAGLE layer 19, the Uno's two |
| The Uno's USB-B has the two corners a Series-B has | ACHIEVED | `8e495ab`; hexagonal opening, both bevels asserted off the mesh |
| The Type-C shell is an obround | ACHIEVED | `7e49503`; no metal within 0.5 mm of an envelope corner |
| A copper POUR is drawn | NOT STARTED | OH-112 §NOT IN SCOPE; 11–48 zones a board, 26,368 points |
| Silkscreen TEXT is drawn | NOT STARTED | needs a font shipped; 47–99 pieces a board |
| A symmetric part cannot be half a turn out | BLOCKED ON A GENERAL PIN-1 READER | OH-106, carried |
| The nRF54LM20A draws the same colour as its siblings | BLOCKED ON OVERRIDING A STATED COLOUR | OH-99, carried |
| The Uno's pad map agrees with its model | BLOCKED ON DECIDING WHICH SOURCE IS RIGHT | OH-96, carried |

---

## 2. Root causes

### 2.1 "still poor 3d model" was not about the models at all

**Symptom, verbatim.** *"still poor 3d model. fix them"* — said after a session
that had just modelled two USB-C receptacles and put 25 of 26 boards on vendor
CAD.

**Wrong hypothesis, and it is the one that cost ten tickets.** Every previous
answer to this complaint added a PART. OH-100 the RP2350's processor, OH-104
eight slabs, OH-102 two receptacles. Each was a real absence and each made the
picture slightly better and still poor.

**How it was ruled out.** By putting a composed board next to an IMPORTED one at
the same camera, on the user's own server:

    .playwright-mcp/oh102-vendor-lm20a.png     XIAO-nRF54LM20A-DIP, the
                                               vendor's own KiCad assembly
                                               export, IMPORTED
    .playwright-mcp/oh102-composed-rp2350.png  XIAO-RP2350-DIP, COMPOSED

| | imported | composed |
|---|---|---|
| castellated half-holes | 28 barrels down both edges | none, a plain black edge |
| copper pads | under every component | **none** |
| silkscreen | outlines, and the letters R and B | **none** |

**Root cause.** Twelve of the twenty-five boards are composed and every one of
them was a bare slate with boxes standing on it. Three layers were missing, and
`tools/kicad.py` had been PARSING ALL THREE for months and handing none of them
on — 211 to 362 pads and 47 to 232 board-level silkscreen strokes per board.

**Fix.** `86de055`, and the numbers are in §4.

**Generalization.** **When one answer to a complaint has failed several times,
the complaint is about something else.** The way to find out is a controlled
comparison against a known-good example of the same thing, at the same camera —
not another increment of the answer that has already failed. This is the fourth
member of a family this repo keeps re-learning; the previous three were about
searches (`docs/research/board-models/README.md` §1).

### 2.2 The stored pad rotation is absolute, and the obvious reading doubles it

**Symptom.** None — this was caught before it shipped, by asking rather than
assuming.

**The two readings.** KiCad could store a pad's `(at x y rot)` angle either
relative to its footprint or absolute in the board. The obvious code is
`pad.rotation_deg + placed.rotation_deg`.

**How it was settled.** Counted on Seeed's RP2350:

    footprint rot    pad rot    count
        90.00          90.00       20      <- every one
       180.00         180.00       79      <- every one
       -90.00         270.00       75
         0.00           0.00       53

**It is ABSOLUTE.** Adding the placement's rotation turns every pad on a rotated
part by twice the angle, which on a chip land lays the rectangle across its own
pair. 224 of that board's 316 pads are turned, so this is the common case.

**The test that holds it** is
`test_a_pad_is_drawn_at_the_angle_its_own_footprint_gives_it`, and it does not
assert the convention — it asserts a fact about the PART: on every two-terminal
chip land ever made, each pad's long axis is square to the line joining the two.

**Generalization.** A file-format convention with two plausible readings is a
coin toss until it is counted. Counting took one command.

### 2.3 Two windings in one mesh, and half of it faced backwards

**Symptom.** The C3's silkscreen rendered as a faint grey wash where it should
have been white ink.

**Root cause.** `pad_outline` walks counter-clockwise; `stroke_outline` walked
clockwise, because the offset that turns a line into a rectangle naturally goes
left and then right. Emitted as they came, the ink was back-facing while the
copper was not.

**Why it is nasty.** It is visible from one side of the board and gone from the
other, so it looks correct in exactly the view the author is using.

**Fix.** `flat()` normalises every ring with `signed_area(ring) < 0` before
emitting it, `tools/compose_board_3d.py`.

**Generalization.** Two builders of the same kind of geometry will disagree
about winding. Normalise at the point of emission, not at each source.

### 2.4 A trace is not exposed copper, and blending toward copper greys a navy board

**Symptom.** The Arduino Uno rendered with SILVER tracery on a blue board.

**Root cause, arithmetic.** The first model blended the board's own mask 30%
toward `COPPER`. Copper's blue channel is 83 and the Uno's navy mask's is 99, so
the blend pulled blue DOWN while pushing red and green up:

    rgb(49, 61, 99)  ->  rgb(94, 91, 94)      a neutral grey

**The right model.** Soldermask is a translucent film: light goes through it,
reflects off what is underneath, and comes back through. Copper returns far more
than bare laminate. So what changes is LIGHTNESS and not hue.

    rgb(49, 61, 99) x 1.55  ->  rgb(76, 95, 153)   a lighter navy

**Fix.** `mask_over_copper` scales, `tools/compose_board_3d.py`.

**Generalization.** A colour operation has a physical model behind it, and
"blend toward the other thing" is almost never it. The picture found this one:
the number looked fine and the board looked wrong.

### 2.5 Every light in the scene had a positive y

**Symptom.** Measured, not seen — luminance over every pixel that is not the
page, XIAO ESP32-C3:

    from above    median 82.6    p90 229.9    mean 115.6
    from below    median  0.0    p90  34.4    mean  12.5

**The median pixel on the underside was pure BLACK.** Not darker because it faces
away. Unlit.

**Why it started mattering.** OH-110 put the vendor's own printing down there:
44 back pads and 1,514 back silkscreen strokes on the C3, and those strokes are
the words **"Seeed Studio"**, the battery pads marked + and −, and the outlines
around both header rows.

**The intensity was swept, not chosen.** Five shares, each shot from above and
below against the running server:

    share   top median   under median   under p90   top mean
     0.00         82.6            0.0        34.4      115.6
     0.15         84.0           18.0       102.3      116.1
     0.25         85.0           34.0       132.1      116.2
     0.35         85.0           49.0       156.3      116.3
     0.50         86.0           66.0       180.5      116.4

**The top mean moves 0.7% across the whole sweep**, which is the design claim
holding: a light from below cannot brighten a surface facing up. So its share is
ADDED to `LIGHT_TOTAL` rather than taken out of the three — sharing it out would
darken a picture it cannot brighten.

**It does not cast**, and that is measured: of the 1 to 21 parts each vendor
places on the BACK of these boards, `CORRESPONDENCE` draws NONE. They are 64 test
points, five logos and one solder jumper, and not one has a body.

**Three existing tests went red and every one was right to.**
`test_every_light_in_the_scene_casts_a_shadow` is now
`..._that_samples_the_sky_...` and holds the part still true: a light in the
UPPER hemisphere may not quietly opt out.

**Generalization.** An invariant that narrows is not an invariant that failed.
Narrow it WITH the argument, in the test's own docstring, and add the assertion
that stops the narrowing being abused.

### 2.6 "uno ethernet port is poor" — there is no ethernet on an Uno

**Symptom, verbatim.** *"uno ethernet port is poor."*

**The Uno has no ethernet.** The large metal socket is its USB-B — and a reader
taking it for an RJ45 IS the defect, stated exactly.

**Root cause.** The shell was five plates forming a plain rectangular tube with
the mouth a dark box 0.4 mm behind the front face: a painted rectangle on a box,
which is what an ethernet jack looks like. **The two upper corners of a Series-B
opening are cut off at 45°, and the bevel is the KEY** — a Series-B plug's shell
has the same two corners cut, which is what makes the pair mate one way up.

**Ruled out: Arduino's own package cannot supply the shape.** `PN61729` in
`third_party/arduino-uno/UNO-TH_Rev3e.brd` draws four silkscreen wires forming a
plain 11.8 × 15.75 mm rectangle, six pads, and nothing else. Verified by dumping
it. The opening's shape is the standard's or it is nowhere.

**Two further defects, and BOTH were found by rendering the part on its own
rather than on the board:**

  * the cavity started at the front plane, coplanar with the frame, so the two
    chamfer triangles fought it for the same surface and only ONE won. One
    bevelled corner and one square is worse than none;
  * the cavity was a solid box filling the interior and swallowed the tongue.

**Generalization, and this is the reusable one.** **Render the part alone.** A
scratch Blender render of one `.obj` took two minutes to write and found two
bugs that a board screenshot could not show, because on the board the connector
is 12 mm of a 68 mm picture at an angle nobody chose. The scratch script is not
committed; rewrite it, it is thirty lines.

### 2.7 An identical screenshot after a recompose is not necessarily a stale cache

**Symptom.** After rebuilding `Arduino-Uno.glb` the page screenshot came back
**byte-identical** — same md5.

**Wrong hypothesis.** Browser or server cache. Ruled out in one command:

```bash
curl -s -D - -o /tmp/served.glb http://127.0.0.1:8088/models/Arduino-Uno.glb | head -8
md5sum webui/static/models/Arduino-Uno.glb /tmp/served.glb
```

`Cache-Control: no-store`, and the two md5s match. The server was serving the
new file.

**Root cause.** The change was entirely on the connector's FRONT FACE, and the
camera was top-down. A pixel-identical PNG was the correct answer.

**Generalization.** Before blaming the pipeline, ask whether the change is
VISIBLE from where you are standing. A byte-identical render is evidence about
the camera at least as often as about the cache.

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. The gate.
python -m pytest -q
#    -> 1850 passed, 17 skipped in ~6m20s
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"
done
#    -> all eight exit 0
ruff check tools/ | grep '^Found'
#    -> Found 37 errors.   (unchanged for twelve commits; all RUF100/ISC004
#       and none in anything this session touched)

# 2. Tool dependencies. Blender AND OpenCASCADE, both.
pip install cadquery-ocp
#    Blender is found by tools/model_from_datasheet.py:BLENDER_HINTS; this
#    machine has "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"

# 3. REGENERATE. Non-optional: every mesh is gitignored.
python tools/model_from_datasheet.py          # 13 parts, ~1 min
#    -> USB2.0-TYPE-C.obj 24,320 bytes; USB2.0-TYPE-C_USB-31C-F-16P.obj 24,410
#    -> USB_B_PN61729.obj 16,978
python tools/import_3d_model.py --all         # 6 boards + 5 parts, ~8 min
python tools/compose_board_3d.py              # 6 boards, ~4 min, FETCHES
#    -> Arduino-Uno.glb 958,176; XIAO-ESP32-C5-DIP.glb 1,365,200
#    -> index names 25 boards

# 4. Serve it.
python webui/emulator_server.py
#    -> OpenHardware on http://127.0.0.1:8088/
```

**Expected `compose` output per board, so drift is visible.** These are the
tallies at HEAD:

    board                pads f/b   ink f/b    track f/b   vias   triangles
    Arduino Uno          247/153      0/0        501/337     82      22,549
    XIAO-ESP32-C3-DIP    203/ 44     81/1518     312/ 83    128      28,252
    XIAO-ESP32-C6-DIP    241/ 44     97/ 609     339/258    146      27,906
    XIAO-RP2350-DIP      272/ 48      4/   3     338/206    171      23,098
    XIAO-ESP32-C5-DIP    313/ 58      3/   3     454/267    307      31,637
    XIAO-nRF54l15-DIP    324/ 68      7/ 942     335/108    281      28,828

The Uno's `ink 0/0` is correct and stated: `tools/eagle.py` gathers no
silkscreen into strokes. The RP2350's and C5's `ink 4/3` and `3/3` are also
correct — those two boards print almost nothing but TEXT on the front, and text
is not drawn.

**To look at one part on its own** — the habit that found §2.6's two bugs —
write a thirty-line Blender script that imports one `.obj`, adds a camera with a
`TRACK_TO` constraint on an empty at the mesh's centre, three area lights and a
mid-grey world, and renders with `BLENDER_EEVEE_NEXT`. Do NOT compute the
camera's `rotation_euler` by hand; that was the first attempt and it rendered a
flat grey frame.

---

## 4. File inventory

### Changed this session

| File | What changed |
|---|---|
| `tools/kicad.py` | `Pad.shape/rotation_deg/layers` + `front`/`back`; `Stroke`; `Via`; `OUTER_COPPER`; `_silk_of`, `_stroke_width`, `_routing_of`; `Board.silk/silk_unread/traces/trace_arcs/vias/traces_unread`; `Arc.width_mm` |
| `tools/eagle.py` | `Pad.shape/rotation_deg/front/back`; `Stroke`; `Via`; `_EAGLE_PAD_SHAPES`, `COPPER_LAYERS`, `_routing`; `Board.silk/traces/vias/...` |
| `tools/compose_board_3d.py` | `anchor_of`; `COPPER`, `SILKSCREEN`, `TRACE_LIFT`, `mask_over_copper`, `COPPER_THICKNESS_MM`, `SILK_THICKNESS_MM`, `TRACE_PROUD_MM`, `ROUND_PADS`, `SQUARE_PADS`, `ROUND_PAD_SIDES`, `VIA_SIDES`; `pad_outline`, `convex`, `clipped_to`, `signed_area`, `flat`, `stroke_outline`, `artwork`, `point_in`; two `CORRESPONDENCE` entries modelled; `BODY_ALLOWANCE_MM` and `body_allowance` DELETED |
| `tools/model_from_datasheet.py` | `ModelledSocket`, `SOCKETS`, `SOCKET_COLOURS`, `socket_geometry`, `build_socket`, `_STATED_ENVELOPE`, `_SPEC_CONTACT`, `CONTACT_ROW_MM`, `SPEC_CONTACTS`; `--list` no longer dies on a slab; the USB-B's `mouth_chamfer` |
| `tools/blender/usb_c_receptacle.py` | NEW at `4fdebca`, then rebuilt as a TUBE: `obround`, `ring`, `skin`, `cap`, `CAP_STEPS` |
| `tools/blender/usb_b_receptacle.py` | `panel`; the front face as a frame of six polygons; the cavity as a back panel; the tongue centred and made an insulator |
| `webui/static/board3d.js` | `BOUNCE`, and `view.lights` built from `[...LIGHTS, BOUNCE]` |
| `tests/rules/test_compose_board_3d.py` | +47 tests |
| `tests/rules/test_kicad.py` | two `Pad` equality assertions now carry shape, rotation and layers |
| `tests/webui/test_board3d.py` | +3 tests; three existing light invariants narrowed with the argument |
| `CLAUDE.md` | the artwork paragraph; the modelled-parts count replaced by `--list` |

### Generated, gitignored, present on disk

| File | Bytes |
|---|---|
| `webui/static/models/nRF54LM20A.glb` | 8,262,812 |
| `webui/static/models/MG24.glb` | 1,571,336 |
| `webui/static/models/SAMD21.glb` | 1,435,288 |
| `webui/static/models/XIAO-ESP32-C5-DIP.glb` | 1,365,200 |
| `webui/static/models/XIAO-nRF54l15-DIP.glb` | 1,266,988 |
| `webui/static/models/XIAO-ESP32-C3-DIP.glb` | 1,249,956 |
| `webui/static/models/XIAO-ESP32-C6-DIP.glb` | 1,210,456 |
| `webui/static/models/XIAO-RP2350-DIP.glb` | 1,000,628 |
| `webui/static/models/Arduino-Uno.glb` | 958,176 |
| `third_party/modelled/*.obj` | 13 files |

### The settled constants, and where

| Constant | Value | File:line |
|---|---|---|
| `COPPER` | `#c8a253` | `tools/compose_board_3d.py` — a judgement, and must not be in `CONTACT_COLOURS` |
| `SILKSCREEN` | `#e9e9e4` | same |
| `TRACE_LIFT` | 1.55 | same — see §2.4 |
| `COPPER_THICKNESS_MM` | 0.035 | one ounce of copper |
| `SILK_THICKNESS_MM` | 0.015 | screen-printed epoxy |
| `TRACE_PROUD_MM` | 0.020 | BELOW the pads on purpose |
| `ROUND_PAD_SIDES` / `VIA_SIDES` | 12 / 8 | |
| `BOUNCE.share` | 0.25 | `webui/static/board3d.js` — swept, §2.5 |
| `CAP_STEPS` | 8 | `tools/blender/usb_c_receptacle.py` |
| `mouth_chamfer` | 2.4 | `tools/model_from_datasheet.py` — presence is the standard's, size is a drawing quantity |
| `CONTACT_OVERHANG_MM` | 0.0 | `tests/rules/test_compose_board_3d.py` |
| `TURN_MARGIN_MM` | 0.3 | `tools/compose_board_3d.py` — winners now beat by 2.6–6.4 mm |

---

## 5. Open work, highest priority first

### 5.1 OH-99: the nRF54LM20A draws green — *software-only, START HERE*

It is the only board of the twenty-five that is not dark, and it is now the most
conspicuous inconsistency on the page: every composed board got copper, routing
and ink this session and this one is an IMPORTED vendor mesh that did not.

The green is a separate soldermask solid the KiCad exporter coloured **by
default** — its own `.kicad_pro` says `pcb_color: rgba(0,0,0,0.000)`, the
alpha-zero UNSET that OH-97 already refused to read as a claim. Fixing it means
overriding a colour the file DOES carry, which reverses a stated invariant.
Needs the care OH-97 got, not an edit.

```bash
grep -n "pcb_color" third_party/seeed-3d/*.kicad_pro 2>/dev/null
python tools/import_3d_model.py --list
```

### 5.2 OH-106: a symmetric part can be half a turn out — *software-only*

`silk_miss` compares body centres and a half turn preserves one. A mutation
turning the Uno's `DIL28-3` from 90 to 270 **survives the whole suite today.**
`contact_miss` fixed this for parts with ≥8 surface-mount pads; a DIP has none.
The ticket names three candidates, cheapest first — the pin-1 marker, which
OH-100 already reads for the RP2350's QFN, is the general one.

### 5.3 The copper pour — *software-only, and it is a real piece of work*

11 to 48 zones a board, up to 26,368 points across the RP2350's 95 filled
polygons. Each `filled_polygon` is a KEYHOLE outline that walks into every
thermal relief and back out again, so `ear_clip` cannot take it as it stands —
coincident edges are a different problem from a concave board outline. The
payoff is a shade rather than a shape: a pour under mask is `mask_over_copper`
over most of the board's area.

Counted by `kicad._routing_of` and printed by `compose` as `not cu ... zone N`.

### 5.4 Silkscreen text — *software-only, needs a font shipped*

47 to 99 pieces a board, and on the RP2350 and the C5 it is nearly ALL of their
front silkscreen (`ink front 4` and `3`). KiCad stores `gr_text` as a string, a
size and a rotation; drawing it means shipping glyph outlines. Note that the
C3, C6 and nRF54L15 already draw their lettering, because those vendors exported
theirs as line strokes — which is why the underside says "Seeed Studio".

### 5.5 OH-98: the vendors state their own component models — *software-only*

Three of the four newer boards carry `(model ...)` blocks naming KiCad's library
(59, 57 and 83 of them), which would turn most of `CORRESPONDENCE` from a
judgement into a reading. Not done because their `MOUDLE14P` footprint carries
five whole-XIAO alternates and **`Seeeduino XIAO SAMD21 v4.step` is not
hidden** — a naive reader stands a complete SAMD21 board on top of the RP2350.

**And this session found the counter-example that makes it harder**: the C6
STATES `USB_C_Receptacle_GCT_USB4105-xx-A_16P` and that model is 7.78 mm deep
where the same footprint's own `Description` says 7.3. A vendor's statement and
a vendor's dimensions disagreed, and the dimensions were right.

### 5.6 OH-96: which of the two Uno sources is right — *software-only*

Carried unchanged. Five pads sit 1.21–3.84 mm from any pin. **Do not close it by
widening `PIN_REACH_MM`.**

### 5.7 Carried unchanged

**OH-84**, **OH-71** (P3), the Uno's `Y1`/`Y2` in `compose_board_3d.ABSENT`,
**OH-8**, **OH-11**, **OH-36** (Cortex-M33, *held by a live session lock*
`agent-oh36` — do not steal it), **OH-64**, **OH-38**, **OH-9**. The PCB artwork
as a RASTER texture is still blocked on the GPL question in
`rules/licence-hygiene.md` — note that this session drew the same information as
GEOMETRY out of the vendor's own MIT-licensed board file, which is a different
provenance and is not blocked.

---

## 6. Commits this session

```
e5c6b4f chore(tickets): file and close OH-114, the Type-C that was a box
7e49503 fix(tools): the Type-C shell is an obround, which is what stops it being a box
0d7b956 chore(tickets): file and close OH-113, the USB-B that read as an RJ45
8e495ab fix(tools): the Uno's USB-B gets the two corners a Series-B has
a7f5bc8 chore(tickets): file and close OH-112, the routing nobody drew
99945af feat(tools): a composed board draws the routing its vendor laid
404e3ff chore(tickets): file and close OH-111, the unlit underside
8e7f64d feat(webui): light the underside, which is where the board is printed
f189d4e chore(tickets): file and close OH-110, the three layers a composed board never drew
86de055 feat(tools): a composed board draws its own copper and its own silkscreen
6939d07 chore(tickets): close OH-102, the receptacle Seeed name is modelled now
4fdebca feat(tools): the USB-C is the one Seeed state, not the one KiCad publishes
```

Closed: **OH-102, OH-110, OH-111, OH-112, OH-113, OH-114.** No core, no ABI and
no board count changed.

---

## 7. Visual verification

Every frame is in `.playwright-mcp/`, driven in Chrome through Python Playwright
against the user's own server. **Two of the six are from an intermediate state
and say so** — nothing here was re-shot after OH-113 and OH-114 except the two
connector frames.

**`oh102-art-c3b.png` (181,193 bytes), top-down, current except the USB-C's
section.** A black XIAO ESP32-C3. Fourteen gold castellated half-holes along
each long edge, each cut flush at the board's outline with a full disc just
inboard of it. Copper under every component: the QFN's lead ring as a dashed
gold rectangle, 0201 pairs, the U.FL's three pads. A clean WHITE silkscreen
frame around the RF section with corner brackets at the buttons and the U.FL.
The USB-C at the right edge with twelve gold tails landing on their pads.

**`oh102-lift-ArduinoUno.png` (311,450 bytes), INTERMEDIATE — before OH-113.**
Blue board, gold pads everywhere, routing as lighter-blue tracery, the DIP-28
with its through-hole rings, two electrolytics, the barrel jack, four headers.
The USB-B in this frame is the plain box that was the whole of OH-113 — do not
read it as current.

**`oh102-lift-XIAO-RP2350-DIP.png` (178,749 bytes), INTERMEDIATE — before
OH-114.** Black board, castellations, copper, routing as faint grey-on-black
tracery with vias as small dots, the QFN-60 centre. The USB-C is the
square-cornered box that was the whole of OH-114.

**`oh102-lit-under-c3.png` (105,410 bytes), current.** The C3 seen from BELOW.
The words "Seeed Studio" in white silkscreen, mirrored because we are under the
board. Gold castellation half-discs along both edges with white silkscreen
frames around them. Two battery pads marked + and −. The mask still reads as
the shaded side — this is 41% of the topside's median, not a second key light.

**`oh102-usbb-final.png` (113,160 bytes), current.** The Uno's USB-B from a low
angle outside the board edge. The opening is a real hole with the Series-B bevel
visible on its upper-left corner, a dark interior, and the paddle inside it. The
shell renders dark here because at this angle its face is turned from the key
light; it is `#9ea1a8` steel in the file.

**`oh102-c5-usbc.png` (195,204 bytes), current.** The XIAO ESP32-C5. The Type-C
shell now has its rounded obround section — the corners are visibly radiused
against the square-cornered box in the RP2350 frame above. Twelve gold tails
inboard, castellations, copper, routing, the QFN-48 centre, the U.FL at the left
edge, two white silkscreen bars.

---

## 8. Known limitations, and things not to waste time on

### 8.1 The three-line habit that found four bugs this session

  1. **Compare against a known-good example at the same camera.** §2.1.
  2. **Render the part alone.** §2.6 — two bugs a board screenshot cannot show.
  3. **Measure the picture.** §2.5 — `PIL`, luminance over the non-background
     pixels. A median of 0.0 is an argument; "it looks dark" is not.

### 8.2 Camera-angle hunting in the page is a time sink

Finding a view that shows one connector's face cost eleven screenshots. The
canvas drag-to-orbit ratio is not documented and the zoom is a wheel delta.
**Render the part alone instead**, and use the page only for the final
whole-board frame.

### 8.3 A byte-identical screenshot is usually the camera

§2.7. Check `curl -D -` and md5 before suspecting a cache — the server sends
`Cache-Control: no-store`.

### 8.4 Three mutations survive on purpose, and all three are equivalent

Recorded in the code beside each: the exposed pad's y-negation in
`pack_geometry`; the contact centroid's z-negation in `contact_miss`; `fp_text`
in `_body_of`.

### 8.5 `tools/tickets.py` still derives a session id from the parent pid

**Set `OH_SESSION_ID` explicitly** for every ticket command; every one this
session did. `tickets.py set` takes `--touch`, not a positional `touches`.

### 8.6 The heredoc trap, again, in a new costume

A `cat >> file <<'PY'` block containing backticks and quotes died with
`unexpected EOF while looking for matching '`. Write the block with the `Write`
tool to a scratch file and `cat` it in, or assert the substitution took. This is
the third session to record this.

### 8.7 Residuals unchanged

`X4122` from the D3D backend compiling three.js's PMREM shader; the capacitor
lid's straight terminator; wire penetration 0.289 mm; `PYI034` on `__enter__` in
all four cores; `core.avr.abi.Cpu` after `close()` segfaults; `#6f6651` still
unidentified. One console 400 on a cold page is expected and is not a regression.
