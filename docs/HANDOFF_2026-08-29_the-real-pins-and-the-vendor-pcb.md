# Handoff — the real pins, and the vendor's PCB

    date          2026-08-29
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          cfad913  feat(tools): a XIAO's board is black, and the colour
                           is labelled a judgement
    previous      b09a171  docs: handoff for the resistor and the colour space
    gate          1,772 passed, 17 skipped   (was 1,723 at b09a171)
    checkers      all eight exit 0
    ticket held   none
    server        the user runs `python webui/emulator_server.py` on
                  127.0.0.1:8088 and it was RESTARTED this session at their
                  request. It is running current code and was left RUNNING.
    models        REGENERATED THIS SESSION AND MUST BE. Every `.glb` built
                  before `cfad913` has a grey PCB, and there is a NEW one.
                  See runbook step 2.

Four tickets closed, one large one advanced by four stories, two filed. **Three
of the five things fixed were reported by the user in four words each**, and in
every case the four words were right and the cause was one layer below where it
looked.

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| The PCB has a visible sheen at the camera a reader gets | ACHIEVED | `13cc72b`; the coat alone moves the mask's brightest tenth 134.4 → 210.7, **+56.8%**, against +0.2% before |
| Changing the board changes the 3D view | ACHIEVED | `ea7d2d1`; mean pixel difference 35.2 (Uno↔RP2040), 55.2 (Uno↔MG24), and 0.00 returning to the Uno |
| A board draws before any firmware is loaded | ACHIEVED | `ea7d2d1`; `XIAO-MG24-DIP` draws 24 pads with no core built |
| A board with no core can be chosen at all | ACHIEVED | `ea7d2d1`; `option.disabled` removed, label keeps "— no core" |
| A wire connects to the vendor's own pin | ACHIEVED | `7bac2eb`; 25 of the Uno's 30 pads are carved header pins |
| No cylinder is drawn on any board | ACHIEVED | `7bac2eb`; `post.visible = false` at creation |
| A `.kicad_pcb` can be read | ACHIEVED | `d699d0d`; 68 placements, outline 20.955 × 17.780 mm, agreeing with a second vendor file to 0.020 mm |
| A KiCad board composes like an EAGLE one | ACHIEVED | `54d5881`; adapter, no mode flag below the reader |
| The ESP32-C3 boards have a 3D model | ACHIEVED | `f906e33`; 54 components, 26,485 triangles, `webui/static/models/XIAO-ESP32-C3-DIP.glb` |
| All ten XIAOs draw the same colour board | ACHIEVED | `cfad913`; `BOARD_MASK` on the PCB solid's faces only |
| Five more chips get a composed model | NOT STARTED | OH-93 §6.1 — C6, MG24, RP2350, nRF54LM20A, nRF54L15 |
| The Uno's pad map agrees with its model | BLOCKED ON DECIDING WHICH SOURCE IS RIGHT | OH-96; 5 pads out by 1.21–3.84 mm |
| ESP32-C5 and STM32C5 get a model | BLOCKED ON THE VENDOR | nothing published; `docs/research/board-models/README.md` §5 |

**13 of 26 boards now have a 3D model, up from 10.**

---

## 2. Root causes

### 2.1 The clear coat measured nothing because it was aimed past the reader

**Symptom.** Carried from the last handoff: three user reports that the board
looked flat, and OH-90's clearcoat measuring 132.7 → 132.9 at the default
camera — a null result that was read as "the coat is weak".

**Root cause.** `studio()` hung the softbox at `(0, STUDIO_SIZE * 0.62, 0)` —
overhead, where a bench lamp goes. A flat board returns what lies in the
**mirror** of the view direction, and `frameScene` sits the camera at 48.3°
elevation, **read back live from `describe()` rather than assumed**. The mirror
of that is 48.3° on the far side. The softbox's own half-angle is
`atan(0.16/0.62)` = 14.5°, so it missed by 27°.

    switching only the coat, default camera
    before   132.7 -> 132.9    +0.2%
    after    134.4 -> 210.7   +56.8%

**And the first fix was wrong in the more useful way.** Aiming the existing
0.16-radius disc at the mirror direction lit the *whole* face evenly and read
exactly as flat. Perspective sweeps the board's own mirror direction through
34° between its far and near edges; the source subtended 28.9° and covered
nearly all of it. Radius 0.08 subtends 14.7° and crosses the board instead.
Swept at two room brightnesses so the peak is not an artefact of one.

**Fix.** `CAMERA_FROM` is now the one place the view direction is written down;
`frameScene` reads it and `studio()` mirrors it about +y.

**Generalization.** Two numbers that merely agree today are two numbers that
drift. This file had already paid for it: `readPalette` converted `#313d63` to
linear and the glTF writer twenty lines away did not, for as long as both
existed.

### 2.2 "why is there a select board and load" — the geometry rode the wrong endpoint

**Symptom, verbatim:** *"when changing boards why does the 3d view not change?"*

**Ruled out, and this is the part worth not repeating:** it was NOT a code bug
at the time it was reported. The user's server had been started at 02:58 and
the fix landed at 23:23 the same day. `board3d.js` is a static file re-read
from disk, so the browser already had the new `change` listener; `emulator_
server.py` loads once at startup, so it ignored `?board=` and answered for its
own session. Measured against their instance:

    asked XIAO-MG24-DIP    -> answered 'Arduino Uno'
    asked XIAO-RP2040-DIP  -> answered 'Arduino Uno'

**The underlying cause, which is real.** `#board-pick` had **no `change`
listener at all** — the only `addEventListener("change")` in `emulator.js` was
on the memory-address box. And `/api/board/pins` called `boards.require()`,
which refuses without a session, so the pin view existed only after a firmware
load. But `api.pin_view` joins two sources its own docstring separates:
position from `pinmap.load(board)` (needs a NAME) and state from
`pin_levels(runtime, cpu)` (needs a session).

**Fix.** `pad_view(board, description, live)`; `pin_view` is one line that calls
it with levels. `?board=` names the board and liveness is an **overlay**, merged
only when the session is running that same board.

**Two things found by pressing the control rather than reading the file:**

  * **The picker would not accept a XIAO-MG24.** `option.disabled =
    !board.runnable`, on the reasoning that offering one "would accept a click
    that cannot be honoured" — true while picking only chose a load target,
    expired the moment picking draws. 14 of 26 have pads and no core.
  * **A regression I introduced, caught in the browser.** The server keeps its
    board across page loads and `fillBoardPicker` defaults to the first
    RUNNABLE board. Making the drawing follow the picker meant reloading while
    an ESP32-C3 ran would draw an Uno and call its pins unanswerable — a
    confident lie where there had been a blank.

**Generalization.** When a symptom is reported against a long-running process,
check the process's age before reading the code. And a docstring that already
says two things are separable is telling you where the seam is.

### 2.3 The cylinder markers were hiding a 3.8 mm misalignment

**Symptom, verbatim:** *"the cylinderacal shapes for wire connections should
not exist and should use the real pins to connect the wires."*

**Root cause.** `showBoard` built a `CylinderGeometry` disc per pad and
`compose_board_3d.py` had already stood the vendor's header underneath it. The
marker did three jobs — state colour, raycast target, wire anchor — so it could
not be deleted; what it could stop being is invented.

**And looking for a pin under each pad measured something nobody had:**

    14 pads   0.05 - 0.07 mm    0-7, A0-A5, VIN
    11 pads   0.65 - 0.77 mm    8-13, 5V, 3V3, RESET, IOREF, NC  (two whole headers)
     5 pads   1.21 - 3.84 mm    GND, 6, SCL, AREF, SDA

The discs were drawn at the pad map's positions, **so they had been in the
wrong place all along** — which is why they read as blobs beside the pins. The
Uno's pad map is the one in this repository traced off artwork rather than
generated from a footprint. Filed as **OH-96**.

**Painting the state onto brass was also wrong, and was measured.** Blending
`high` 72% into `#b58136` gives `#66744b`; `input` gives `#7e726c`. Two muddy
browns three pixels wide. The state is **emitted** now — `color` stays the
vendor's metal and `emissive` carries the state.

**Generalization.** A drawn stand-in for a real thing hides every disagreement
between them. Replacing it with the real thing is also a measurement.

### 2.4 "esp c3 types have no 3d stuff" — and my own change had made it worse

**Symptom, verbatim.** The C3 drew a **blank white slab**: no model, and since
OH-95 removed the pad discs, nothing at all on it.

**I sent the user a picture of that slab captioned as the MG24 "drawn".** It
was a featureless rectangle. Corrected in the same turn; recorded here because
the failure was not looking at an image before presenting it as evidence.

**Root cause.** The C3 is one of the 16 boards with no vendor mesh — but Seeed
publishes the whole KiCad project, which is the same class of source as the
EAGLE file the Uno is built from. `get_board_sources.py` says Seeed publishes
no `pcb_layout` because **that survey read GitHub and these files are on the
wiki** — the identical miss OH-29 made about the meshes.

**Fix.** `Composition.layout` takes either format, `read_layout` picks by
suffix, and twelve correspondence judgements were each proposed from a measured
pad span and then **accepted by `confirm`**, which measures the placement's own
pads against the mesh.

**It agrees with a source it was not built from**: the composed USB-C spans
exactly 8.94 mm and overhangs the edge by 0.99 mm, and `import_3d_model.py`
records a 1.3 mm overhang measured on Seeed's OWN meshes for sibling boards.

### 2.5 The board colour, and the bug the fix cost

**Symptom.** All ten XIAOs drew a neutral grey PCB. Every real XIAO is black.

**Ruled out, all four, so nobody repeats them:**

| Where | What it says |
|---|---|
| Seeed's STEP files | PCB is `#808080` = `UNSTYLED`; 16,682 of 18,723 vertices on the RP2040 |
| `XIAO ESP32C3_v1.3.kicad_pro` | `"pcb_color": "rgba(0, 0, 0, 0.000)"` — **alpha zero is KiCad's UNSET**, not a claim of black |
| the `.kicad_pcb` | no `(stackup ...)`; its only mask entries in 697 KB are `solder_mask_margin`, a clearance |
| Seeed's wiki, 2 pages | zero mentions of "black", "colour", "color", "matte", "glossy" |

So `BOARD_MASK = "#1b1b1b"` is a **judgement and says so in capitals**, with
what would retire it written beside it.

**It is not an override of `UNSTYLED`.** That constant means "nobody here knows
what this is" and its test still passes. A PCB is the one unstyled solid whose
material is not a mystery — `pcb_solid()` already identifies it by shape.
Verified: the painted group spans exactly the stated PCB (RP2040 21.00 × 17.50
× 1.20 mm) and everything standing on the board stayed grey.

**THE BUG THIS COST.** Rewriting `key = colour_of(...) or UNSTYLED` into an
explicit `is None` check **broke the import of every board**: `colour_of`
answers `""` for a face styled with nothing, and that reached `int("", 16)`.

**Nothing would have caught it** — the tests read the shipped `.glb`, which a
mutation does not regenerate, and `tessellate` needs OCP and a 34 MB download.
**That is the third time this exact gap has hidden a bug** (seam weld, sRGB,
this). Closed the same way: `colour_key(styled, is_board)`, eight lines with no
OpenCASCADE in them, driven by tests with `""` and `None`.

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. The gate.
python -m pytest -q
#    -> 1772 passed, 17 skipped in ~7m
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"
done
#    -> all eight exit 0

# 2. REGENERATE THE MESHES. Non-optional: they are gitignored, every .glb
#    built before cfad913 has a GREY PCB, and XIAO-ESP32-C3-DIP.glb is new.
pip install cadquery-ocp                 # a tool dependency, not a runtime one
python tools/import_3d_model.py --all
#    -> RP2040.glb 657,944 bytes, 5 colours (4 before: #1b1b1b is the PCB)
python tools/compose_board_3d.py
#    -> Arduino-Uno.glb          710,408 bytes
#    -> XIAO-ESP32-C3-DIP.glb  1,085,956 bytes, 54 components
#    -> 1,796,364 bytes of glTF; index names 13 boards

# 3. Serve it.
python webui/emulator_server.py
#    -> OpenHardware on http://127.0.0.1:8088/
```

**In the browser** — note that step 1 is now enough to see a board:

1. Pick **XIAO-ESP32-C3-DIP**. *It draws immediately: a black board with the
   ESP32-C3 QFN, a USB-C receptacle, the U.FL antenna socket and 44 passives.
   No firmware needed.* Pick **XIAO-MG24-DIP** — it also draws, with no core
   built, as a bare slab because nothing is published for it.
2. Pick **Arduino Uno**, **Choose file** `tests/avr/blink/blink.bin`, type
   **`0x0`** in the base box, **Load**, **Run**. Pin 13 blinks — and the pin
   that lights is the vendor's own brass header pin, glowing, not a disc.
3. The bench and the wiring runbook are unchanged from the 2026-08-28 handoff
   §3, including the D13 → 220 Ω → D12 → LED → GND circuit.

**If the 3D view does not change when you switch boards, the server is
stale.** Restart it. `board3d.js` is re-read from disk per request;
`emulator_server.py` is not.

---

## 4. File inventory

### Changed this session

| File | What changed |
|---|---|
| `webui/static/board3d.js` | `CAMERA_FROM`; `SOFTBOX` reach/radius; `carvePins`; `PIN_REACH_MM`; `PIN_GLOW`; `repaint` emits; markers invisible; `describe().realPins` |
| `webui/api.py` | `pad_view`, `description_for`; `pin_view` is one line |
| `webui/emulator_server.py` | `/api/board/pins?board=` with a liveness overlay |
| `webui/static/emulator.js` | picker `change` listener; options no longer disabled; `fillBoardPicker` asks what the server has, then draws |
| `webui/static/board3d-panel.js` | `reload()` names the board; start-up call moved out |
| `tools/kicad.py` | `read_board`, `Arc`, `Placement`, `Board`; `_pads_of` shared |
| `tools/compose_board_3d.py` | `from_kicad`, `arc_points`, `contours`, `outer`, `read_layout`; `Composition.layout/fetch_with/geometry/serves`; `fetch_pcb`; the C3 and 12 correspondences |
| `tools/import_3d_model.py` | `BOARD_MASK`, `colour_key`, `board_faces_of`; `write_index` takes the composed list |
| `docs/research/board-models/` | NEW: the survey — `docs/research/board-models/README.md` and `docs/research/board-models/sources.json`. **Not** the older `docs/research/board-sources/sources.json`, which is the one that says Seeed publishes no PCB |

### Generated, gitignored, present on disk

| File | Bytes |
|---|---|
| `webui/static/models/XIAO-ESP32-C3-DIP.glb` | 1,085,956 |
| `webui/static/models/Arduino-Uno.glb` | 710,408 |
| `webui/static/models/SAMD21.glb` | 1,435,288 |
| `webui/static/models/RP2040.glb` | 657,944 |
| `webui/static/models/nRF52840.glb` | 662,736 |
| `webui/static/models/ESP32-S3.glb` | 516,716 |
| `third_party/seeed-pcb/ESP32-C3.kicad_pcb` | 697,553 |

### The settled constants, and where

| Constant | Value | File |
|---|---|---|
| `CAMERA_FROM` | 0.1 / 0.85 / 0.75 | `webui/static/board3d.js:104` |
| `ENVIRONMENT_SHARE` | 0.35 (was 0.61) | `:234` |
| `SOFTBOX` | bright 72.0, radius 0.08, reach 0.62 | `:629` |
| `PIN_REACH_MM` | 1.1 | `:96` — must stay under 1.27, half the pitch |
| `PIN_GLOW` | 0.85 | `:~120` |
| `BOARD_MASK` | `#1b1b1b` | `tools/import_3d_model.py` — the one judgement |
| `ARC_CHORD_MM` | 0.2 | `tools/compose_board_3d.py` |

---

## 5. Open work, highest priority first

### 5.1 OH-93: five more chips — *software-only, START HERE*

**The pipeline exists and is proven on the C3.** Each remaining chip is a
correspondence table, not new machinery. Add a `PCB_SOURCES` entry and a
`Composition`, run `--check`, and let `confirm` judge the mappings:

```bash
python tools/compose_board_3d.py --board XIAO-ESP32-C6-DIP --check
```

URLs and byte sizes for all five are in
`docs/research/board-models/sources.json`: ESP32-C6 1,126,886; MG24 1,583,091;
RP2350 1,145,969; nRF54LM20A 4,307,651; nRF54L15 1,305,099.

**What to expect from the C3, so it is not a surprise:** the footprint names
are the vendor's own, `confirm` will reject a wrong package by span, and the
parts that are NOT components (test points, castellations, the silkscreen
logo) are simply absent from `CORRESPONDENCE` and skipped. The C3's button and
its chip-scale PMOS were left undrawn; both are visible features and worth a
second look.

### 5.2 OH-96: which of the two Uno sources is right — *software-only*

Filed `4ec2f80`, claims nothing. Five pads sit 1.21–3.84 mm from any pin and
eleven more are out by a consistent 0.7 mm. **Do not close it by widening
`PIN_REACH_MM`** — past 1.27 a pad claims its neighbour's pin and lights the
wrong one convincingly. The constant carries the table.

### 5.3 The nine XIAOs' castellations are not carved — *software-only*

They are plated half-holes INSIDE the board's thickness and unstyled, so they
fail both the metal test and the `centre.y > pcbThickness` test in
`carvePins`. Measured separable, though: the RP2040's PCB solid holds 1,660
vertices near its long edges in **seven columns of 228 at 2.54 mm**. A second
carve rule keyed on the board edge would give nine more boards lit pins.

### 5.4 The 16 footprint boards show a bare slab — *software-only*

Since OH-95 there is no pad indication on them at all. The user chose "remove
markers everywhere" knowing this. Their footprints carry pad positions AND
sizes, so drawing the pads as part of the slab's own surface — copper, not a
floating cylinder — is available and was explicitly left out of OH-95.

### 5.5 Carried unchanged

* **OH-84** — two parts cannot be wired to each other.
* **OH-71** (P3) — a PWM pad reports the level `PORT` holds.
* **Y1 and Y2**, the Uno's two undrawn parts, in `compose_board_3d.ABSENT`.
* **OH-8**, **OH-11** — i8086 timing and microcode-exact muldiv.
* **OH-36** — Cortex-M33. Blocked on an oracle **and held by a live session
  lock** (`agent-oh36`). Do not steal it.
* **OH-64**, **OH-38**, **OH-9** — blocked, see their tickets.
* The PCB artwork as a texture is still blocked on the GPL question in
  `rules/licence-hygiene.md`; see the 2026-08-28 handoff §6.2.

---

## 6. Commits this session

```
cfad913 feat(tools): a XIAO's board is black, and the colour is labelled a judgement
f906e33 feat(tools): the XIAO ESP32-C3 has a 3D model, composed from Seeed's own PCB
4ec2f80 chore(tickets): file OH-96, found by OH-95 looking for a pin under each pad
7bac2eb fix(webui): a wire connects to the vendor's own pin, not a cylinder drawn here
ea7d2d1 fix(webui): a board you pick draws, instead of waiting for firmware
54d5881 feat(tools): a KiCad board, presented as the one the composer already builds
d699d0d feat(tools): read a .kicad_pcb, because the vendors publish PCBs and not meshes
13cc72b feat(webui): the softbox was at the zenith and the board reflects elsewhere
```

Closed: **OH-92, OH-94, OH-95, OH-97.** Advanced: **OH-93** (US-1 … US-4).
Filed and left open: **OH-96.** No core, no ABI and no board count changed.

---

## 7. Visual verification

Every frame in `.playwright-mcp/`, driven in Chrome through Python Playwright
directly.

**`oh92-default.png` → `oh92-final.png`.** Before: a uniform matte blue slab
with no highlight anywhere on its face; the gold pins catch specular and the
board does not. After: the same navy board with a soft bright pool sweeping
from the upper-middle down to the left, falling off to deep blue at the
corners. The DIP-28, barrel jack and header shrouds are black in both.

**`pins-before-headers.png` → `oh95-after-headers.png`.** Before: pale
blue-grey discs sitting over and beside the black header shrouds, overlapping
the gold pins rather than capping them. After: the discs are gone; the black
shrouds carry rows of brass pins standing in them, which is what an Arduino
header looks like.

**`c3-now.png` → `c3-composed.png` → `mask-c3.png`.** First: a featureless
white rectangle — no model, no pads, nothing. Second: a grey board carrying the
ESP32-C3 QFN, a large gold-shelled USB-C receptacle at the right edge, the
round U.FL antenna socket at the left, two black SOT-23-5 packages and dozens
of tiny passives. Third: the same board, now black with a semi-gloss sheen.

**`mask-rp2040.png`.** Seeed's own mesh, now with a black PCB: the white
silkscreen label with the Seeed logo and "XIAO - RP2040" reads clearly on it,
the castellated half-holes are visible as notches down both long edges, and the
USB-C shell overhangs the right edge.

**`oh94-XIAO-MG24-DIP.png`.** The MG24 drawn from the picker with no firmware
and no core built — a bare slab, which is the honest picture for a board whose
vendor publishes nothing. It is in the inventory because it is what §5.4 is
about.

---

## 8. Known limitations, and things not to waste time on

### 8.1 A stale server looks exactly like a bug in the page

`emulator_server.py` loads once; `board3d.js` is re-read per request. So a
running instance serves NEW JavaScript against OLD Python, and the page asks a
question the server does not understand. This cost a round this session.
**Check the process's age before reading the code.**

### 8.2 `tools/tickets.py` derives a session id from the parent pid

`session_id()` is `pid-<os.getppid()>`, and every Bash tool call here gets a
fresh parent — so `start` and `stop` run as different sessions. A `stop` this
session **released OH-22**, a stale lock from 2026-08-25 whose recorded pid
collided with that shell's. OH-22 is `done` so nothing was lost, but ~45 stale
locks sit in `.omc/ticket-locks/` and a collision with a LIVE ticket is
possible. **Set `OH_SESSION_ID` explicitly** for every ticket command.

### 8.3 Two open tickets may not claim the same path

`check_ticket_claims.py` fails on it, and the pre-commit hook refuses a write
into another ticket's files. OH-97's work landed inside OH-93's territory, so
OH-97 was set `touches: []` and the commit was made holding OH-93. That is the
pattern; OH-84 records the same lesson.

### 8.4 The one console 400 on a cold page is expected

With nothing loaded, `fillBoardPicker` asks the bare pin view whether the
server already has a board, and "no" arrives as a refusal. One request, one
400 — the same count as before OH-94. Not a regression.

### 8.5 Residuals unchanged

`X4122` from the D3D backend compiling three.js's own PMREM shader (one known
warning); the capacitor lid's straight terminator is the model's cone and not a
renderer bug (five experiments recorded in the 2026-08-28 handoff §2.3); wire
penetration 0.289 mm; `PYI034` on `__enter__` in all four cores;
`core.avr.abi.Cpu` after `close()` segfaults, carried from six handoffs ago;
`#6f6651` still unidentified.

### 8.6 Ruff is not the gate

The gate is `pytest` plus the eight checkers. `ruff check` reports 8 findings
on `tools/`, of which 6 pre-date this session; the two added are `RUF100`
unused-`noqa` markers matching the convention of the lines above them.
