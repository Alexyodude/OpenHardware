# Handoff — a board that runs itself, and an Arduino Uno that looks like one

| | |
|---|---|
| **Date** | 2026-08-27, later the same day as `HANDOFF_2026-08-27_the-bench.md`. **Where this and that one disagree, this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `2edb71e` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed, no ticket held |
| **This session** | 11 commits from `54b978a`. **25 files, 4,174 insertions, 110 deletions** |
| **Cores built** | `build/lib/`: `avr.dll` 116,736 · `cortexm0.dll` 228,864 · `i8086.dll` 130,048 · `riscv32.dll` 146,432 — **unchanged, no core was touched** |
| **Gate** | **1,612 passed, 17 skipped** (was 1,557); all eight checkers exit 0 |
| **Boards** | 26 imported, 12 runnable — **unchanged**. Now **10 draw a 3D model**: 9 Seeed's own, and the Arduino Uno's, which is composed here |
| **Tickets closed** | OH-74, OH-75, OH-76, OH-77, OH-78. None filed and left open |

**Press Run once and the board keeps running.** Pick an Arduino Uno, build a
blink, press Run: pin 13 toggles every 3.25 s and does not stop. The Uno now
draws as a real board — PCB with its notch, the DIP-28, four headers, both
ICSP blocks, the USB socket, the barrel jack, two electrolytics, the 16U2, the
regulator and the reset button.

**Every piece of work after the first came from the user mid-turn.** Only
OH-74 came off the previous handoff.

**START HERE: §6.1. The user has chosen a full nodal circuit solver and it is
not started.** An LED lights while ungrounded, and that is a lie the page
tells.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| Press Run once, watch a blink | **ACHIEVED** | 655,000,000 instructions unattended at 2,503,759/s; `webui/static/clock.js`; `36a645a` |
| Run is a toggle, Stop stops it | **ACHIEVED** | Stop landed exactly one tick later: 655,000,000 → 655,200,000 = `TICK_STEPS` |
| The rate is on the page | **ACHIEVED** | "2,503,759/s" beside the button; `runLine` in `emulator.js` |
| The Uno's traced pad map is verified | **ACHIEVED** | 32/32 pair, **zero** label disagreements, residual median 0.005 mm; `2a80c94` |
| The Uno draws a real board | **ACHIEVED** | 15 components, 17,601 triangles; `tools/compose_board_3d.py`; `52a85c0` |
| Nothing in that model is invented | **ACHIEVED** | every height off a mesh; the one cited number is the USB shell, in `SPECS` |
| KiCad models come from the library | **ACHIEVED** | `KICAD_3D` → GitLab, not the GitHub mirror; `7f6e3bf` |
| The USB-B exists at all | **ACHIEVED** | modelled in Blender 4.5.4 from Arduino's own package; `tools/model_from_datasheet.py` |
| Every part faces the right way | **ACHIEVED** | worst silk miss 0.40 mm across 15; `silk_miss`; `100c13c` |
| A wire rests on the board | **ACHIEVED** | penetration 2.248 mm → **0.000 mm**; `penetration()`; `bd680cf` |
| A bench part is the right size | **ACHIEVED** | part and board scale bit-identical at 0.5638; `view.mmScale` |
| **An LED needs a circuit to light** | **NOT STARTED** | **§6.1, START HERE.** `applyState` reads one pad's level, full stop |
| Neon / realistic lighting | **NOT STARTED, QUESTION OPEN** | §6.2 — the user was asked and has not answered |
| Y1 and Y2 drawn | **NOT STARTED** | §6.3 — no model in any library; measurements recorded in `ABSENT` |
| i8086 cycle counts / IMUL | **BLOCKED, unchanged** | OH-8, OH-11 |
| 9 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36`; do not touch |

### What the Uno draws now

```
15 components, all placed from Arduino's own EAGLE board file
├── ZU4    DIP-28_W7.62mm                the ATmega328P
├── IOH IOL POWER AD                     the four headers, 10+8+8+6 = 32 pads
├── ICSP ICSP1 JP2                       2x03, 2x03, 2x02
├── X2     USB_B_PN61729                 MODELLED HERE -- nobody publishes one
├── X1     BarrelJack_Horizontal         turn 270, and §3.7 is why
├── PC1 PC2  CP_Elec_6.3x5.4             the electrolytics
├── U3     QFN-32-1EP_5x5mm              the ATmega16U2
├── U1     SOT-223                       the regulator
└── RESET  SW_SPST_B3S-1000              the tactile switch

2 not drawn, each with the measurement that rules the near miss out
├── Y1  QS         body 6.86 x 4.57 mm   KiCad's through-hole crystals are HC49 at 10.90/11.05
└── Y2  RESONATOR  body 3.20 x 1.60 SMD  KiCad's are 7 mm through-hole, 12.5 mm tall
```

---

## 2. What changed, in one paragraph each

**§6.1 of the previous handoff was wrong twice, and measuring is what found
it.** It said a server-side stepper was needed and that the page already
polled. Neither is true. §3.1.

**The Uno's traced pad map was right all along** — the one board of 26 measured
off an image agrees with the vendor's CAD to 0.008 mm. §3.2.

**Two CAD libraries disagree about which way a part lies, and about where it
begins.** Both cost a visibly wrong board. §3.3, §3.4.

**A check that was made insensitive to orientation could not report an
orientation error.** §3.5.

**The library this project fetches from was a partial mirror.** §3.6.

**A barrel jack pointed into the board and every check passed**, because a pin
field is symmetric about its own centre. §3.7.

**A wire went through the board because the collider was 4.5 units away from
it** — right for nine boards by coincidence. §3.8.

**I reported a bug that did not exist.** §3.9.

---

## 3. Root-cause narratives

### 3.1 A handoff's own premise, overturned by one measurement

**Symptom.** `HANDOFF_2026-08-27_the-bench.md` §6.1 says, of the free-running
clock: *"what is missing is a server side that keeps stepping, not a UI"*, and
offers three server designs to weigh — a renewed deadline, a budget-per-poll,
or a background thread with a stop route.

**Hypotheses ruled out, and how.** All three assume the transport is expensive.
Measured against a real socket on `127.0.0.1:8099`, median of twelve rounds:

```
a bare GET /api/board/state       0.95 ms
POST run(200,000) + state        76.2 ms  ->  2,625,923 steps/s,  13.1 repaints/s
POST run(50,000)  + state        20.3 ms  ->  2,467,728 steps/s,  49.4 repaints/s
POST run(20,000)  + state         9.2 ms  ->  2,162,408 steps/s, 108.1 repaints/s
```

against **2,688,248 steps/s** for the same board stepped in-process with no
server at all. A loop in the *page* reaches **97.7%** of what the core can do.

**Root cause.** There was nothing to fix on the server. And the design question
the handoff posed — *what does a run mean when the page can disconnect?* — has
no content once the page **is** the loop: nothing outlives the tab, there is no
deadline to renew and no stop route to forget.

**The second error in the same section:** it cites `emulator.js:909` as
*already* polling `/api/board/state`. It does not. That line is inside
`renderBoardState`, which runs once per Build and once per Run press. Nothing
in `webui/static/` contains a poll loop — `grep` for `setInterval` or a chained
`setTimeout` finds none.

**And the repository had already decided this**, for the i8086, before the
boards existed. `emulator.js:200`'s `runContinuously` says why in as many
words: one long request *"would hold the connection open for as long as it ran,
and there would be no moment at which the Stop button could be noticed."*

**Generalization.** *A handoff is a claim about the world at a moment, and its
predictions age faster than its measurements.* The numbers in that document
were all still true; the design advice built on top of them was not, because
nobody had priced the transport. Re-measure before adopting a plan you
inherited — the measurement is cheap and the plan was written without it.

### 3.2 A negative result that was worth more than a fix

**Symptom.** The Arduino Uno is the only one of 26 boards whose pad centres
were not derived from vendor CAD. Its `derivation` says *"Pad centres extracted
from board.svg: circle elements mapped through viewBox 0 0 27957 21193"*, and
it carried an `assumption` about which pad was which. `tools/import_board.py`'s
own docstring names that file as the anti-pattern it exists to prevent.

**Root cause — there was none.** Arduino's EAGLE board file settles it: all 32
pads pair by row and order with **zero** label disagreements. After fitting out
the one scale and offset per axis that separates artwork pixels from
millimetres, the residual is a **median of 0.005 mm and a worst of 0.008 mm**
against a 2.540 mm header pitch.

The three correspondences that look wrong and are not: D13–D10 carry `SCK`,
`MISO`, `MOSI`, `SS` because that is what those pins are on an Uno; A4 and A5
appear twice because the R3 repeats them beside AREF; `IOREF` sits on the `+5V`
net because the R3 ties it there.

**What was NOT done, deliberately, and the user was told.** The coordinates
were not replaced. Eight micrometres is not a correction, and those numbers are
in *artwork* space where they have to land on the drawing they are painted
over — swapping in vendor-derived ones would push every marker slightly **off**
`board.svg`.

**One real finding fell out:** `board.svg` is **not uniformly scaled**. 5.6616
px/mm across against 5.6382 down — a 0.41% anisotropy, 0.28 mm over the board's
68.58 mm width. That mattered within hours; see §3.8's third defect.

**Generalization.** *A verification whose result is "it was already right" is
not a wasted verification.* It converted a documented guess into a measured
fact and, in passing, produced a number nobody had — which two later bugs
turned on. Budget for checks that will probably pass.

### 3.3 Two libraries, two axis conventions, and every header across the board

**Symptom.** The first composed Uno measured **68.58 × 91.44 mm** on a board
that is 53.34 mm deep.

**Root cause.** EAGLE lays a `1X10` header's ten pads along **x**, spanning
22.86 × 0.00 mm. KiCad's `PinHeader_1x10_P2.54mm_Vertical` runs along **y**.
Every header stood across the board instead of along it, and the DIP-28 with
them.

**Fix.** `Component.turn` — degrees taking the KiCad model's own axes onto the
EAGLE package's, applied *before* the element's own rotation. All six were 90.

**Generalization.** *Two libraries describing the same part agree about what it
is and not about how it is drawn.* The name matched, the pin count matched, the
pitch matched. Only the orientation did not, and nothing in either file
declares one.

### 3.4 The same two libraries, disagreeing about where a package begins

**Symptom.** With the turns fixed, the six-pin analog header `AD` ran **2.54 mm
past the board's right-hand edge**.

**Root cause.** KiCad anchors a header on **pin 1**; EAGLE anchors it in the
**middle of the pin field**. `AD`'s pin 1 is 6.35 mm from its element origin,
so the model's pin 1 landed on EAGLE's centre.

**Fix, and it is better than a table.** Anchor on the **pads** — the one thing
both libraries describe. `place` puts the mesh's own footprint centre on the
element's pad centre, so no per-package offset is written down anywhere.

**Then that fix needed its own fix, for the barrel jack** — see §3.7 — and the
final form anchors a through-hole part on its **legs**, the geometry below the
board plane, which is exactly what the pads describe.

**Generalization.** *When two sources disagree about a convention, anchor on
the thing they both measure rather than translating between them.* A table of
offsets would have been correct and would have been one more thing to keep
true for every part added afterwards.

### 3.5 A check made insensitive to a difference could not report that difference

**Symptom.** §3.3's headers-across-the-board went undetected by `confirm`,
which exists precisely to refuse a model that does not fit its pads.

**Root cause.** It compared **sorted** spans. `22.86 × 2.54` sorts identically
to `2.54 × 22.86`. The sort was put there deliberately, to make the check
robust to which way round a part was — and that made it blind to the only
orientation error there is.

**Fix.** Compare in order, and separately check **mounting**: a through-hole
model on surface-mount pads is a different part whatever its footprint
measures. A mesh declares which it is by whether it has geometry below the
board plane (`leads_of`). That second check is what refuses KiCad's 12.5 mm
through-hole resonator on the Uno's 3.20 × 1.60 mm SMD pads — which the size
check *passed*, because 7 mm against 2 mm of pads is inside a tolerance that
must allow a body wider than its pins.

**Generalization.** *When a check keeps passing, ask what it is invariant
under, not whether it is strict enough.* Tightening the pad tolerance to a
micron would never have caught either of these. This is the most transferable
sentence in this document.

### 3.6 The library was a mirror, and the mirror was a different tree

**Symptom.** A conclusion in OH-75's committed code: *"Connector_USB.3dshapes
holds five entries."*

**Root cause.** Both mesh tools fetched from `KiCad/kicad-packages3D` on
GitHub. KiCad's library lives on **GitLab**, and the two are not the same tree.
Counted 2026-08-27:

```
Connector_USB          github  5 entries   gitlab 13
Connector_BarrelJack   github  4           gitlab  5
Button_Switch_THT      github 127          gitlab 82
```

It diverges in **both** directions, so it is not simply older. Every model
already imported was byte-for-byte identical — 885,081 / 356,629 / 286,283 /
215,953 / 185,520 / 125,561 — so nothing drawn was wrong. What the mirror cost
was **coverage**, and a sentence about the mirror was wearing the library's
name.

**The conclusion survived the better source**, which is worth recording: the
canonical `Connector_USB` is three USB-A, seven USB-C, one Micro-B and one
Mini-B. There is no type-B receptacle in KiCad's library at all.

**Fix.** One `KICAD_3D` constant in `tools/import_3d_model.py`, pointing at
GitLab.

**Generalization.** *A negative result inherits the authority of whatever you
searched, and a mirror has less of it than it looks like.* This is OH-29's
Seeed census again — that one stated its conclusion without its scope and
closed a question for a day.

### 3.7 A part 180 degrees out, and every measurement agreeing

**Symptom.** The user said "check your placements". The barrel jack `X1` was
drawn **7.50 mm** from where Arduino's own silkscreen puts it, with its barrel
pointing **into** the board instead of out over the left edge.

**Hypotheses ruled out.** Three checks existed and all three passed:

* `confirm` compares a model's footprint to the pad span — a jack turned 180°
  has the same footprint;
* `place` anchors a through-hole part on its legs, matched to the pad centre —
  a jack turned 180° has the same leg centre;
* two leg tests compare the placement back to those same pads.

**Root cause.** **A part whose pins are symmetric about their own centre can be
180 degrees out and satisfy every measurement taken from those pins.** All
three checks measure the same quantity, and that quantity is invariant under
the error.

**Fix.** The **silkscreen**. The pads say where a part's pins are; the
silkscreen says where its **body** is. Both are the vendor's, both go through
the same placement transform, and neither comes from a table written here.
Against it the four candidate turns for `X1` miss by **5.36, 7.50, 5.35 and
0.01 mm** — the right one is not a matter of taste.

`silk_miss` runs for every placed component and `compose` refuses one further
out than `SILK_TOLERANCE_MM = 1.5`. Before: fourteen of fifteen agreed to
0.40 mm and X1 was at 7.50. After: worst is 0.40, and that one is X2 — the USB
socket modelled here, whose body is this project's drawing measured against the
vendor's courtyard, so a small disagreement is the honest outcome.

**The sign of the flip was checked separately**, because `silk_miss` and
`place` could in principle share an error and cancel. The board JSON's pad map
is in *artwork pixels* and was verified to 0.008 mm in `2a80c94`; put into the
scene's frame **without reusing `place`'s flip**, each header encloses the pads
the page draws on it — IOL spans x 3.30..23.62 with pad `0` at 22.35, IOH spans
−23.62..1.78 with pad `13` at −12.20.

**Generalization.** *Two transforms that share no code and agree is evidence; one
transform checked against itself is not.* And when three checks all pass, count
how many distinct quantities they actually measure — here it was one.

### 3.8 Three ways the physics did not know about what was on screen

**(a) The board's components were not colliders — 2.248 mm.**
`refreshColliders` pushed the PCB slab and each bench part. That was the whole
board while a board was an extruded slab; OH-75 put fifteen components on it
and the collider set became a description of a board that no longer existed,
**without a line of it being edited**. Measured: a wire laid straight from pad
12 to an LED sits 2.248 mm inside the DIP-28.

**(b) The PCB slab was 4.5 units from the board — and this is the one the user
could see.** `placeModel` built it in absolute scene coordinates while the
model group sits at the pad centroid. On a XIAO those agree, because the
castellations run down both long edges — so it was right for nine boards by
coincidence. The Uno's pads are on two edges of a board they are not centred
on:

```
board   x -22.00 .. +20.01
slab    x -23.20 .. +15.46
```

which is exactly where a wire dropped from pads 0 to 13 falls, and straight
through the PCB.

**Fix for both:** every board solid is stated in the **model's** frame and put
through `matrixWorld` by one function, `boardSolid`. That also deleted the
quarter-turn fix-up — two hand corrections that swapped the slab's axes and
then its offset when a model was rotated. A box in the model's frame turns with
the model.

**(c) A bench part was 1.42× too big.** `addPart` scaled by the constant
8 px/mm that a *generated* board JSON uses; the Uno's was traced at 5.638 (§3.2).
`8 / 5.638 = 1.419`. This is the same defect OH-76 fixed for the board model
and missed for the bench. One `view.mmScale` now.

**Generalization.** *A decision that was correct when it was made stops being
correct when its premise changes, and nothing about it looks wrong in the
meantime.* Three instances in one session. **The next one is already visible:**
the comment above the lighting says *"Two lights and no shadows ... this scene
has one object"* — written when the board was a flat slab, and the scene now
has fifteen.

### 3.9 A bug I reported that did not exist

**Symptom.** The previous session's closing note said `connect(...)` returns
null and leaves a dropped LED unwired, and recommended looking before trusting
the bench.

**Root cause.** The probe called `scene.connect(...)` after a fixed
`setTimeout` instead of awaiting the async `addPart`, so the mesh had not
loaded and the part had no terminals yet. Verified on 2026-08-27 with a proper
`await`: `wireMade: true`, `13->anode`.

**Generalization.** *A test harness that races the thing it is testing reports
a defect in the code.* That is worse than not finding one, because it sends the
next session after a ghost. Await what you are measuring.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 2edb71e

python tools/build_core.py
#  -> avr 116736 · cortexm0 228864 · i8086 130048 · riscv32 146432 (unchanged)

python -m pytest -q                       # -> 1612 passed, 17 skipped (~7 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0
```

**Kill any dev server on 8088 first.** `test_an_upload_from_another_origin_is_refused`
fails while one is running and passes alone — this cost a false failure in this
session's gate. §9.

### The Uno's 3D model — optional, and gitignored

```bash
pip install cadquery-ocp                  # 7.9.3.1.1 here; ~81 MB wheel
python tools/get_board_sources.py arduino-uno
#  -> prints the URL; it is an https-archive, so download by hand into
#     third_party/arduino-uno/ and unzip it (as the Pico's is)

python tools/model_from_datasheet.py      # the USB-B, in Blender
#  -> third_party/modelled/USB_B_PN61729.obj  16,484 bytes
python tools/compose_board_3d.py
#  -> outline 12 points, 68.580 x 53.340 mm, 10 triangles
#  -> drawn 15, modelled 1 (X2), absent 2 (Y1, Y2)
#  -> webui/static/models/Arduino-Uno.glb  710,212 bytes
```

Report without writing anything:

```bash
python tools/compose_board_3d.py --check
python tools/model_from_datasheet.py --list   # every cited number and its source
```

### Driving the bench

```bash
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0 before starting
python webui/emulator_server.py
```

1. Pick **Arduino Uno**, type a blink on pin 13, press **Build and run**.
2. The board draws with its notch, chip, headers, USB socket and barrel jack.
3. Press **Run once**. Pin 13 toggles every ~3.25 s and does not stop. The
   button reads **Stop** and the report reads
   `Arduino Uno: N instructions, ~2,500,000/s. pc 0x...`.
4. **Add a part ▾** → `KiCad packages3D` → `LED_THT` → **5 mm LED**, drag from
   a pad to a lead. The wire rests **on** the chip and headers.

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `tools/compose_board_3d.py` | 48,319 | compose a board model from EAGLE placements + KiCad meshes |
| `tools/model_from_datasheet.py` | 13,407 | the fourth source: build a part in Blender, every number cited |
| `tools/blender/usb_b_receptacle.py` | 6,434 | the Blender script, driven headless |
| `webui/static/clock.js` | 8,188 | the free-running clock. **Imports nothing**, so a test runs it |
| `tests/rules/test_compose_board_3d.py` | 35,816 | 30 tests: outline, correspondence, silk, colliders, OBJ |
| `tests/webui/test_clock.py` | 16,654 | 13 tests, run under node against a fake board |
| `docs/tickets/OH-74..OH-78*.md` | — | five tickets, all closed |

### Modified

`webui/static/board3d.js` (+~200 — colliders, one scale, `boardSolid`,
`penetration`), `webui/static/emulator.js` (+151 — the Run toggle),
`webui/static/board3d-panel.js` (+~45 — the third caption),
`tools/import_3d_model.py` (+~50 — `KICAD_3D`, `COMPOSED`),
`tools/eagle.py` (+~80 — placement, `pad_extent`, `silk`),
`tools/import_board.py` (+~60 — multi-element `--select`),
`tools/board_sources.py` (+~65 — Arduino registered),
`webui/boards/Arduino Uno.json` (provenance only — **all 32 pads byte-identical**),
`tests/webui/test_board3d.py`, `tests/rules/test_import_board.py`,
`tests/rules/test_kicad.py`, `docs/research/board-sources/sources.json`,
`CLAUDE.md`, `webui/static/emulator.html`.

### Generated, and NOT in git

`webui/static/models/` and `third_party/` are gitignored.

| File | Bytes |
|---|---|
| `models/Arduino-Uno.glb` | 710,212 |
| `models/SAMD21.glb` | 1,434,248 |
| `models/nRF52840.glb` | 661,792 |
| `models/RP2040.glb` | 657,032 |
| `models/ESP32-S3.glb` | 515,776 |
| `models/parts/*.glb` | 70,868 / 23,972 / 16,700 / 14,468 |
| `third_party/modelled/USB_B_PN61729.obj` | 16,484 |
| `third_party/arduino-uno/UNO-TH_Rev3e.brd` | 707,996 |

### Evidence that is NOT durable

`.playwright-mcp/*.png` — gitignored. This session's:
`clock-blink-high.png`, `clock-blink-low.png`, `uno-composed.png`,
`uno-composed-aligned.png`, `uno-real-model.png`, `uno-with-usb.png`,
`uno-placements-fixed.png`, `bench-scale-wrong.png`, `wire-on-components.png`,
`wire-slab-fixed.png`. §8 describes each in words for that reason.

---

## 6. Open work, highest priority first

### 6.1 An LED lights while ungrounded — *software-only, START HERE*

**The user reported this and chose the fix.** Asked whether to build a
complete-circuit rule, a full nodal solver with datasheet parameters, or the
rule first and the solver next, they chose **"Solver now, datasheet parts"**.
It has **no ticket — file one first.**

**The defect, exactly.** `webui/static/board3d.js`'s `applyState`:

```js
function applyState(wire) {
  if (!wire.terminal) return;
  const pad = view.pads.get(wire.pin);
  const state = pad ? pad.userData.state : "unknown";
  setPartState(wire.terminal.userData.part, state, view.palette);
}
```

One wire, one pad's logic level, straight to `lit` via `parts.js`'s
`DRIVE = {high: "lit", low: "off", ...}`. There is **no second terminal, no
ground, no current**. An LED with one leg on D13 and the other in mid-air
lights.

**The user's own diagnosis, verbatim:** *"This issue stems from not physcially
simulating the properties of the datasheet and components."* They are right,
and `CLAUDE.md`'s own opening names **"analog circuit solving"** as a project
goal — so this is on the roadmap rather than a detour.

**What is already there, all verified 2026-08-27:**

- ground pads are identifiable: `webui/boards/Arduino Uno.json` has three
  `GND` pads, and `group` is `power` for the power header;
- `parts.js` `dressPart` builds `group.userData.terminals` — a `Map` of name →
  anchor, from the model's `extras.terminals`, which
  `tools/import_3d_model.py`'s `lead_tips` derives off the mesh (2.540 mm for
  the LEDs, 7.600 for the buzzer);
- `board3d.js` `connections()` already reports `{id, pin, kind, label,
  terminal}` per wire — the topology is all in the browser;
- pin levels arrive from `/api/board/state` on every clock tick.

**The design that follows the house pattern.** `webui/static/circuit.js`,
**importing nothing**, so `tests/webui/test_circuit.py` can run it under node
exactly as `test_wires.py` and `test_clock.py` do — that precedent is the
strongest one in this repository and both files say why in their headers.
Modified nodal analysis with piecewise-linear diodes, iterated to consistency:
real node voltages and real branch currents.

**Where the datasheet numbers go.** With the part, in
`tools/import_3d_model.py`'s `PARTS` table (which already carries `lens` and
`terminals`), written into the GLB extras so they travel to the page — and
**each with its citation**, exactly as `tools/model_from_datasheet.py`'s
`SPECS` does it. That file is the pattern to copy; see its module docstring on
why an uncited number is the defect this project keeps re-learning.

**What the page should then be able to say**, and this is the thing that earns
the whole exercise: an LED straight across a pin with no series resistor draws
more than its rating, and the page should say **"no current limiting: this
would destroy the LED"** instead of lighting it prettily. The bench makes that
circuit very easy to build by accident.

**Verify it visually:** wire a 5 mm LED from D13 with its other leg in mid-air
— it must **not** light. Wire the second leg to `GND` — it must light. Reverse
the polarity — it must not.

### 6.2 Lighting and "neon" — *software-only, QUESTION OPEN WITH THE USER*

**The user asked and has not answered.** They asked what renders the models,
whether it can look more realistic with neon lights, and what the choices of
engine and baked/dynamic lighting are. I answered in full and **did not act**;
the open question is whether to vendor `EffectComposer` and three
post-processing passes (~+60 KB) for real bloom, or take the free tier first.

**What is there now**, all in `board3d.js` `mount()`: three.js **r185**
(vendored, `three.module.js` 669,763 + `three.core.js` 1,503,063),
`WebGLRenderer({antialias: true})`, pixel ratio capped at 2,
`MeshStandardMaterial` throughout, and **two lights**:
`AmbientLight(white, 1.5)` + one `DirectionalLight(white, 2.0)`. **No shadows,
no tone mapping, no environment map, no textures.**

**The free tier, in payoff order** — none needs a new dependency:

1. `ACESFilmicToneMapping` — one line. Values over 1.0 currently clip to flat
   white, which is why a "lit" LED reads as a pale disc.
2. `RoomEnvironment` + `PMREMGenerator` — ~5 lines, both already in three.js.
   Every metal in the scene (USB shell, gold pins, DIP legs) has
   `metalness > 0` and reflects a void.
3. The LED lights by swapping `material.color`, not `emissive` — it cannot
   glow, cannot bloom and casts no light.

**Baked vs dynamic, and why baking is mostly wrong here:** the scene is
dynamic by construction — wires move every frame, parts arrive at runtime,
LEDs change from the emulator — and the models have **no UVs** at all
(`write_glb` emits positions, normals and a base colour). The one bake worth
doing is **ambient occlusion into vertex colours at import time**, which is
view-independent, survives everything, and would be computed where OpenCASCADE
already is.

**The stale comment to fix while you are there**, `board3d.js` `mount()`:
*"Two lights and no shadows. A shadow map costs a second render pass to make a
flat green slab look slightly rounder, and this scene has one object."*
Written when the board was a flat slab. The scene has fifteen objects now and
none of them casts a shadow. This is §3.8's generalisation, already visible.

### 6.3 The two Uno parts still not drawn — *software-only*

`Y1` (`QS`, a 16 MHz crystal) and `Y2` (`RESONATOR`). Both are recorded in
`compose_board_3d.ABSENT` with the measurement that rules the obvious
candidate out:

- Y1's body is **6.86 × 4.57 mm** by Arduino's silkscreen; every through-hole
  crystal in KiCad's `Crystal` library is an HC49 at **10.90 or 11.05 mm** —
  near enough to *pass* the footprint check and half as long again as the real
  can. The vendor's drawing is what says no, not the check.
- Y2 is a **3.20 × 1.60 mm surface-mount** resonator; KiCad's only three-pin
  resonators are 7 mm through-hole cans 12.5 mm tall, refused on mounting.

Both are timing parts a few millimetres across. The user's standing instruction
— *"if there isn't a part in any of those then look at the datasheet and make
it in blender"* — covers them; they were offered as a follow-up and the offer
is open. `tools/model_from_datasheet.py` is the tool and the USB-B is the
worked example.

### 6.4 The tickets that are open and unblocked — *software-only*

- **OH-71** (P3) — a PWM pad reports the level `PORT` holds, not the waveform
  the timer drives. Fully specified and narrowed off every path.
  `test_a_pwm_pad_reports_the_port_bit_and_not_the_waveform` is written and
  passing, and closing OH-71 must make it fail.
- **OH-8** — an EU cost table from Intel's published timings, not fitted.
- **OH-11** — three leads, in order: the 33 IDIV cases are all *prefixed*
  encodings, so check instruction *length*; solve per-case for the byte set;
  Ken Shirriff's microcode disassembly, never consulted.

### 6.5 Blocked, and why — *do not start these*

- **OH-36** — Cortex-M33, nine boards. Blocked on an oracle **and held by a
  live session lock** (`agent-oh36`). Do not steal it.
- **OH-64** — Cortex-M4, two nRF52840 boards. Blocked on an oracle.
- **OH-38** — Xtensa, three boards. Refused on evidence.
- **OH-9** — PICSimLab adapter.
- **Input parts** (a button driving a pin) — needs `PINB`/`PINC`/`PIND` on AVR
  and `PORT_IN` on the SAMD21, all recorded as returning a stored zero. Core
  work, its own ticket. **Note this is now entangled with §6.1:** a real
  circuit solver is the natural place for a switch to close a node.

### 6.6 Residuals

1. **`/api/board/load-artefact` returns 400 with an empty artefact dropdown.**
   Pre-existing and unrelated. `emulator.js` `loadArtefact` guards on the board
   and not on the path. **What triggers the call when nothing is picked was
   never traced** — start there, not at the guard.
2. **The XIAO ESP32-C3's model is on GrabCAD**, behind a login. Three runnable
   boards keep the footprint. Recorded in `MODELS`' own comment.
3. **`core.avr.abi.Cpu` after `close()` segfaults** the interpreter instead of
   raising. Two lines, in nobody's ticket. **Carried from three handoffs ago.**
4. **Wire penetration settles at 0.289 mm**, not zero — the rope's contact
   tolerance, under the wire's own radius. `penetration()` measures it.
5. **The USB-B's silk miss is 0.40 mm**, the worst of the fifteen, because its
   body is this project's drawing measured against the vendor's courtyard.
6. `sh1add`/`bset` accounted in the RISC-V sweep; `PYI034` on `__enter__` in
   all four cores; the UI does not surface which of a board's ISA the core
   executes. Unchanged.

---

## 7. Commits this session

```
2edb71e chore(tickets): close OH-78
bd680cf fix(webui): a wire went through the board and its components, and the bench was 1.42x
d1ad436 chore(tickets): close OH-77
100c13c fix(webui): the Uno's barrel jack pointed into the board, and no check could see it
278e1dd chore(tickets): close OH-76
7f6e3bf feat(webui): the canonical KiCad library, seven more Uno parts, and a USB-B built here
12f7bc6 chore(tickets): close OH-75, and tell CLAUDE.md about the composer
52a85c0 feat(webui): a real 3D Arduino Uno, composed from CAD nobody meshed
2a80c94 feat(boards): the Uno's pad map, checked against Arduino's own board file
e3fdb12 chore(tickets): close OH-74
36a645a feat(webui): a free-running clock behind Run, so a blink can be watched
```

Closed: **OH-74, OH-75, OH-76, OH-77, OH-78**. Filed and left open: **none**.
No core, no ABI and no board count changed.

---

## 8. Visual output verification

Driven in Chromium via Playwright. **0 console messages at warning level or
above on every pass.**

**`clock-blink-high.png` / `clock-blink-low.png` — the clock, from one press.**
The Uno as an extruded footprint (these predate the model). A red cable runs
from a green pad — D13 driven high — up and left to a 5 mm LED standing to the
right, lit bright orange-red in the first frame and dark red in the second. The
report between them reads `502,800,000` then `537,600,000 instructions,
2,498,455/s`, and **nothing was touched between the two**. The button reads
**Stop**.

**`uno-composed.png` — the first composed model.** A blue-grey PCB with the
Uno's real silhouette including the notch on the right edge. On it: a black
DIP-28 with white pins across the middle, four black header strips with gold
pins along the top and bottom edges, two 2×3 ICSP blocks and a 2×2. The pad
markers are visible as small dots *inset from* the headers — the 41%-too-large
bug of §3.8(c), before it was found.

**`uno-composed-aligned.png` — the markers on the pins.** The same board with
the headers now sitting exactly on the pad markers, which are consequently
hidden inside the shrouds. This is the frame that showed the markers needed to
ride the pin tips rather than the board.

**`uno-real-model.png` — markers on the pin tips.** Pale caps visible on top of
several header pins, one of them white — pin 13 driven high.

**`uno-with-usb.png` — fifteen components.** Adds a silver USB-B socket
overhanging the left edge, a black barrel jack, two black electrolytic cans, a
small dark QFN near the USB, the SOT-223 regulator and the reset button. This
is the frame in which the barrel jack is **wrong** — it sits inside the board's
outline rather than overhanging it (§3.7).

**`uno-placements-fixed.png` — the jack turned round.** The same board with the
barrel jack now protruding past the left edge beside the USB socket, its barrel
opening facing outward.

**`bench-scale-wrong.png` — the bench, oversized.** A red LED beside the board,
roughly a fifth of the board's width — about 7.4 mm for a 5.4 mm part. A red
wire runs from a pad, over the board, to it.

**`wire-on-components.png` — the wire on the chip.** The LED now small and
correctly scaled. The red wire visibly drapes *over* the top face of the
DIP-28 rather than through it.

**`wire-slab-fixed.png` — two wires from the right-hand edge.** A blue wire
from pad 0 and a red from A5, both leaving the board's right edge and running
to a lit LED and a black buzzer. Both rest on the board rather than passing
through it — the frame that shows §3.8(b) fixed.

---

## 9. Known limitations and traps

- **`test_an_upload_from_another_origin_is_refused` fails while a dev server
  is running on 8088**, and passes alone. This produced a false failure in this
  session's gate and cost a round of investigation. Kill the server before
  trusting a full run: `netstat -ano | grep ":8088" | grep -c LISTENING`.
- **`await` the async thing you are testing.** `addPart` is async; a probe that
  called `connect` after a fixed `setTimeout` reported a bug in `connect` that
  does not exist (§3.9).
- **Backslashes in a Bash heredoc that patches Python.** A search string
  written `"\\n}"` inside a heredoc reaches Python as `\n}` — a real newline —
  and silently matches nothing, so the patch reports success and changes
  nothing. Hit once this session. Use the `Edit` tool for anything containing
  an escape.
- **Backticks in a heredoc are command-substituted**, and a heredoc inside an
  `&&` chain breaks on quoting. Carried from the last handoff and still true.
- **`\n` inside a heredoc-written Python string literal** became a real newline
  in `compose_board_3d.py` and produced a syntax error. Same family.
- **Blender's stdout is not cp1252.** `subprocess.run(..., text=True)` alone
  raises inside the decode and returns `stdout=None`, which reads as "Blender
  printed nothing". Pass `encoding="utf-8", errors="replace"`.
- **`bpy.ops.mesh.primitive_cube_add(size=1.0)` spans −0.5..+0.5**, so scaling
  by the half-extent halves it again. Use `size=2.0`. The first USB-B was a
  tidy, symmetrical, half-size connector.
- **A Windows command line is rebuilt from a string**, so JSON passed as one
  argv entry arrives mangled. `tools/model_from_datasheet.py` hands Blender a
  file path instead.
- **`tools/get_board_sources.py` does not fetch an `https-archive`.** It prints
  the URL and the destination; the Pico and the Uno are both manual.
- **`tools/tickets.py stop` releases only the CURRENT pid's lock.** Stale locks
  accumulate in `.omc/ticket-locks/`; only `OH-36.lock` (`agent-oh36`) is live.
- **Two open tickets may not claim the same path.** Narrow the follow-up off
  every path and say in its body that it re-claims them.
- **A ticket-only commit needs `.omc/current-ticket` blank.**
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`; use
  `$USERPROFILE`.
- **A ralph-style run does not get an independent reviewer here.** Every ticket
  this session was self-verified with a full gate, mutation testing and a real
  browser. That is not the same as a review — say so rather than implying one
  happened.
