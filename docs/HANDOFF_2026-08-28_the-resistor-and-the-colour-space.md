# Handoff — the resistor, and the colour space

    date          2026-08-28
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          28e3296  chore(tickets): file and close OH-91
    previous      6f6c458  docs: handoff for the circuit and the layout (2026-08-27)
    gate          1,719 passed, 17 skipped   (was 1,684 at 6f6c458)
    checkers      all eight exit 0
    ticket held   none
    server        the user runs `python webui/emulator_server.py` themselves on
                  127.0.0.1:8088 and it was left RUNNING at the end of this
                  session. It keeps a board SELECTION across page loads.
    models        REGENERATED THIS SESSION AND MUST BE. See runbook step 2 --
                  every `.glb` written before 7dc67fc has wrong colours.

Eight tickets closed, two filed. Six of the eight came from the user reporting
that the 3D view was wrong, and **the last one is the only one that mattered**:
every albedo in every model was an sRGB byte written into a field glTF defines
as linear. Everything above it in this document was, in part, compensation for
that.

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| An LED on an Uno can be lit without destroying it | ACHIEVED | `6c99ca4`; D13 → 220 Ω → D12 → LED → GND is 9.3 mA, browser-verified on a running blink |
| A part's current is reported when a resistor is on the bench | ACHIEVED | `analyse` no longer counts a stated resistance as `assumed`; `tests/webui/test_circuit.py::test_a_resistor_does_not_suppress_the_current_through_the_led_beside_it` |
| Periodic surfaces have no shading seam | ACHIEVED | `weld_seams`, `tools/import_3d_model.py`; Uno `#a5a392` 509 unwelded pairs → 12, **free in bytes** |
| Components sit on the board rather than floating | ACHIEVED | `27c34ec`, `34dbcfd`; three shadowed lights, `.playwright-mcp/linear-dip.png` |
| Highlights are not clipped flat | ACHIEVED | `NeutralToneMapping`; close-up clipping 0.303% → 0.011% (0.259% now, see §9.3) |
| Crevices are darker than open board | ACHIEVED | DIP-28 crop darkest tenth 0.269 → 0.170 of its mean |
| A page reload does not print a stack trace | ACHIEVED | `ea60648`; `tests/webui/test_emulator.py::test_a_client_that_hangs_up_mid_response_prints_nothing` |
| The 3D view is on screen when a board is loaded | ACHIEVED | `19409b3`; on screen at 1366×768 through 3440×1440 |
| The page says what it is waiting for | ACHIEVED | `WAITING` in `board3d-panel.js`; verified against a server with nothing loaded |
| The PCB is a coated surface, not a matte one | ACHIEVED | `KHR_materials_clearcoat`; +6.5% on the mask's mean at the default camera |
| Rendered colours match the colours the repo sourced | ACHIEVED | `7dc67fc`; mask saturation 0.29 → 0.47, black epoxy no longer 12.9× too bright |
| The board carries its artwork | BLOCKED ON A LICENCE QUESTION | `webui/assets.py` reads the Uno's `board.svg` out of the user's PICSimLab install at runtime and PICSimLab is GPL. See §6.2. |
| Two parts can be wired to each other | NOT STARTED | OH-84, filed `5e5e4b8`, claims nothing |

---

## 2. Root causes

### 2.1 A resistor counted as a part with no model, so it deleted the current it limited

**Symptom.** Not observed — found while implementing OH-80, before it could be.

`webui/static/circuit.js`'s netlist loop had, for any part that was not a diode:

```js
assumed++;
elements.push({ kind: "resistor", ..., ohms: model.ohms ?? ASSUMED_OHMS });
```

`assumed` is what makes `analyse` refuse to report a current for **any** part on
the bench: a value nobody published, standing in a circuit, decides every other
part's current. The branch was written when no part had a stated resistance, so
it was correct and untested at the same time. **The first resistor added would
have deleted the current through the LED it was limiting.**

**Fix.** A stated resistance is a published model:

```js
} else if (model.ohms) {
  elements.push({ kind: "resistor", id: `part:${index}`, a, b, ohms: model.ohms });
} else {
  assumed++;
  elements.push({ kind: "resistor", id: `part:${index}`, a, b, ohms: ASSUMED_OHMS });
}
```

`webui/static/parts.js` also dropped `ohms` in transit — it maps the glTF's
snake_case to camelCase by hand and the new key was not in the list. That is the
second time: `absolute_amps` did the same on 2026-08-27.

**Generalization.** A defensive branch written for a case that does not exist
yet is not tested by anything, and it is wrong in the direction nobody checks.
When a table gains its first member of a kind, read every branch that already
claims to handle that kind.

### 2.2 The ticket's "only real question" did not exist

OH-80 was filed saying KiCad's resistor mesh carries painted colour bands that
will not read 220 Ω, so a part labelled 220 Ω would have a picture contradicting
its label. **Tessellated: the mesh has exactly two styled colours** — `#a5a392`
on the leads and `#c07635` on the body — **and no bands.** The STEP defines two
`COLOUR_RGB` entries and no more.

**Generalization.** A question about a file is answered by reading the file. This
one had been carried across two handoffs as a design decision.

### 2.3 A hard line across every capacitor lid — five experiments, and it was not a defect

**Symptom.** Each electrolytic lid on the Uno cut in half by a dead-straight
diagonal, cream on one side and black on the other. Reported to myself as the
worst thing in the close-up.

**Ruled out, each with a rendered pair still on disk:**

| Hypothesis | How it was ruled out | File |
|---|---|---|
| The six-plane room's ceiling/wall corner | Replaced with a graded sphere; line survived | `.playwright-mcp/sky-cans.png` |
| A hard-edged rectangular softbox | Replaced with a disc fading to nothing; survived | `.playwright-mcp/pool-cans.png` |
| The environment at all | `scene.environment = null`; survived | `.playwright-mcp/envoff-cans.png` |
| A normal discontinuity | `MeshNormalMaterial` — the lid is smooth and uniform | `.playwright-mcp/mat-normal.png` |
| Two colour groups meeting | Unlit flat white — no line | `.playwright-mcp/mat-white.png` |

**What is left, and what all five are consistent with:** the lid is a shallow
**cone**. A cone's normal varies with azimuth and not along its generators, so a
directional light divides it with a straight line through the apex. That is
correct rendering of the geometry KiCad published; a real electrolytic has a flat
stamped lid, and the simplification is the model's.

**Not chased further.** If anyone wants it gone the question is whether to use a
different capacitor model, not whether to change the renderer.

### 2.4 Every B-rep face is meshed alone, so periodic surfaces came back creased

OCC meshes a cylinder or a sphere as **one periodic face** and duplicates the
vertices where the parametrisation wraps. Each copy then holds the average of
only the triangles on its own side, so a smooth surface arrives with a hard
shading line down it. Measured on the Uno before the fix: **509 coincident pairs
in `#a5a392` and 178 in `#050505` whose normals disagreed, the worst 22.1°** —
one whole facet's worth of normal dropped on a single edge.

`weld_seams` clusters coincident vertices by direction and merges only runs
agreeing to within `SMOOTH_DEGREES` (20° from the mean, so 40° across a pair).
A cube corner puts each of its three normals 54.7° from their mean and a 45°
chamfer puts each at 22.5°, so both stay sharp; a seam at `ANGULAR`'s own 28.6°
puts each at 14.3° and welds. After: **12 pairs and 4.**

**It is free in bytes** — no vertex is added or removed, only normals averaged.
Every `.glb` came back the size it went in.

**Generalization.** "The function is correct" and "anything calls it" are two
claims. Stubbing the call out of `tessellate` left every unit test green,
because they drive `weld_seams` directly and the shipped `.glb` on disk was
already welded. **The same gap appeared again in §2.7.**

### 2.5 The knob with the reasoning was not the knob that binds

`tools/import_3d_model.py` has two tessellation controls. `DEFLECTION = 0.05`
carried a measured paragraph; `ANGULAR = 0.5` said only "OCC's own default".
Measured, re-reading the STEP for each setting:

    5 mm LED   defl 0.05 ang 0.5      461 tri
               defl 0.01 ang 0.5    1,627      (5x finer chord: 3.5x)
               defl 0.05 ang 0.2    1,509      (2.5x tighter angle: 3.3x)
               defl 0.05 ang 0.1    4,959

**`BRepMesh_IncrementalMesh` stores its triangulation ON the shape**, so a sweep
that does not re-read the STEP measures the first setting four times. That cost a
round: the first sweep returned four identical numbers and looked like a null
result.

`ANGULAR` is **left at 0.5**. Rebuilding at 0.2 costs 4,170,400 → 9,146,360
bytes and changes 0.95% of the pixels in a board close-up. Most of what it was
buying was §2.4, which costs nothing.

### 2.6 Two settings the renderer silently overruled

Found by opening the page as a reader does. The console carried:

```
THREE.sigmaRadians, 0.06, is too large and will clip, as it requested
30 samples when the maximum is set to 20
THREE.WebGLShadowMap: PCFSoftShadowMap has been deprecated. Using PCFShadowMap instead.
```

* `STUDIO_BLUR` was 0.06 and the prefilter applied 0.04. `PMREMGenerator._blur`
  clamps at `MAX_SAMPLES = 20` (`vendor/three.module.js:3224`); samples are
  linear in sigma and 0.06 asked for 30, so **0.04 is the ceiling**.
* `PCFSoftShadowMap` is deprecated in r185 (`vendor/three.module.js:9150`), so
  the shipped shadows were always PCF while the source and its test said
  otherwise — **a test agreeing with a comment rather than with the program.**

The picture did not change: mean 195.727 → 195.734, entropy 2.710 → 2.710. Both
values were already in effect. What was wrong was the file.

### 2.7 THE ONE THAT MATTERED — every albedo was sRGB in a linear field

**Symptom, verbatim from the user, twice:** *"the pcb board needs to be more
realistic. needs shine and reflection"*, then after a whole ticket of work,
*"the board is still matte and greyish"*.

**Root cause**, `tools/import_3d_model.py`, in `write_glb`:

```python
red = int(colour[1:3], 16) / 255
```

An sRGB byte over 255, written into `baseColorFactor`, **which the glTF
specification defines as linear and three.js reads as linear.** The transfer
function was never applied, so every albedo was too bright — and, because the
function is a curve, *differently* too bright per channel, which flattens a
colour toward grey:

| surface | written → correct | too bright | saturation |
|---|---|---|---|
| Uno solder mask `#313d63` | .192 .239 .388 → .031 .047 .125 | 6.3 / 5.1 / 3.1× | .51 → .75 |
| SAMD21 mask `#116517` | .067 .396 .090 → .006 .130 .009 | 11.9 / 3.0 / 10.5× | .83 → .96 |
| gold contact `#b58136` | .710 .506 .212 → .462 .220 .037 | 1.5 / 2.3 / 5.7× | .70 → .92 |
| **black epoxy `#050505`** | .020 .020 .020 → .002 .002 .002 | **12.9× each** | — |

**The right answer was twenty lines away the whole time.** `readPalette` in
`webui/static/board3d.js` builds colours with `new THREE.Color("#313d63")`, and
the string form calls `setStyle`, which applies exactly this function. So the
extruded slab has been correct since it was written and the composed board
beside it was six times too bright — two answers to one question, in one file's
neighbourhood, disagreeing since the first model landed.

**Fix**: `linear()` in `tools/import_3d_model.py`, applied to all three channels.

**What it explains besides the complaint:**

* OH-90 measured the mask rendering at three times its own albedo and read that
  as over-lighting. It was not. The albedo really was that bright.
* The exposure was dialled down in OH-86 and again in OH-90, each time to
  compensate for surfaces too bright for a reason nobody had looked for. Both
  are now put back: `LIGHT_TOTAL` 3.2 → 7.0, `ENVIRONMENT_SHARE` 0.28 → 0.61.
* **OH-90's clear coat measured nothing at the default camera** — 132.9 against
  132.7 — because a specular layer cannot show against a diffuse term that
  large. With the albedos corrected the same coat moves the mask's mean by
  **+6.5%**, 88.8 → 94.6.

**Generalization.** When a value crosses a boundary defined by a specification,
read the specification for what the field means, not just its type. And when two
places in one codebase answer the same question, check that they agree — this
repository had the correct conversion and the incorrect one in files that import
each other.

---

## 3. Runbook

From a clean checkout, or after `git pull`:

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. The gate.
python -m pytest -q
#    -> 1719 passed, 17 skipped in ~6m
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"
done
#    -> all eight exit 0

# 2. REGENERATE THE MESHES. Non-optional after 7dc67fc: they are gitignored,
#    and any .glb built before it carries sRGB values in a linear field.
pip install cadquery-ocp          # a tool dependency, not a runtime one
python tools/import_3d_model.py --all
#    -> "weld  N vertices on a seam given one normal" per model
#    -> 3,460,184 bytes of glTF for 4 model(s)
python tools/compose_board_3d.py
#    -> webui/static/models/Arduino-Uno.glb  710,408 bytes

# 3. Serve it.
python webui/emulator_server.py
#    -> OpenHardware on http://127.0.0.1:8088/
```

**In the browser** — and the first two steps are the ones people miss:

1. Pick **Arduino Uno** in the board selector. *Nothing is drawn yet, and the
   caption now says so.*
2. **Choose file** `tests/avr/blink/blink.bin`, and type **`0x0`** in the base
   box beside it. A raw `.bin` carries no addresses and is refused without one.
3. **Load** → the board appears and the page scrolls to it if it is not already
   in view. **Run** → pin 13 blinks.
4. **Add a part** → `Resistor_THT` → `220 Ω resistor`, and again for
   `LED_THT` → `5 mm LED`.
5. Drag D13 → the resistor's `lead A`, then D12 → its `lead B`, D12 → the LED's
   `anode`, GND → its `cathode`. Both rows read *"at least 9.3 mA through it"*
   with no warning. Take the resistor out and the same LED reads **DESTROYED**.

Series circuits go through a spare input pad because **every wire runs from a
board pad to a part terminal** — there is no part-to-part wire. That is OH-84.

---

## 4. File inventory

### Changed this session

| File | What changed |
|---|---|
| `tools/import_3d_model.py` | `linear()`; `weld_seams()`; `RESISTOR_ELECTRICAL`; `Part.lens` optional; `Electrical.forward` optional; `Finish.coat`/`coat_roughness`; `FINISHES["#c07635"]`; `KHR_materials_clearcoat` |
| `webui/static/board3d.js` | `surfaceOf()`; `SOLDER_MASK`; `castShadows()`; `LIGHTS`/`LIGHT_TOTAL`/`ENVIRONMENT_SHARE`; graded `studio()`; tone mapping; `SHADOW_*` |
| `webui/static/board3d-panel.js` | `WAITING`; `reload()` speaks on refusal; `reload()` at startup; scroll-into-view once per board |
| `webui/static/emulator.html` | the `.pins` block moved above its caption |
| `webui/static/circuit.js` | the `assumed` gate; signed vs magnitude current; a resistor's own off-sentence |
| `webui/static/parts.js` | `ohms: spec.ohms` |
| `webui/emulator_server.py` | `HUNG_UP`, `class Server`, `handle_error` |
| `tests/webui/test_circuit.py` | +8 |
| `tests/rules/test_import_3d_model.py` | +17 |
| `tests/webui/test_board3d.py` | +13 |
| `tests/webui/test_emulator.py` | +3 |

### Generated, gitignored, present on disk

| File | Bytes |
|---|---|
| `webui/static/models/Arduino-Uno.glb` | 710,408 |
| `webui/static/models/SAMD21.glb` | 1,434,412 |
| `webui/static/models/RP2040.glb` | 657,036 |
| `webui/static/models/nRF52840.glb` | 661,800 |
| `webui/static/models/ESP32-S3.glb` | 515,784 |
| `webui/static/models/parts/R_Axial_DIN0207_..._Horizontal.glb` | 60,104 |
| `webui/static/models/parts/LED_D5_0mm.glb` | 18,444 |

### The settled constants, and where

| Constant | Value | File |
|---|---|---|
| `DEFLECTION` | 0.05 | `tools/import_3d_model.py:114` |
| `ANGULAR` | 0.5 | `:138` |
| `SMOOTH_DEGREES` | 20.0 | `:158` |
| `LIGHT_TOTAL` | 7.0 | `webui/static/board3d.js:146` |
| `ENVIRONMENT_SHARE` | 0.61 | `:180` |
| `SHADOW_TEXELS` | 2048 | `:186` |
| `SHADOW_BIAS_MM` | 0.06 | `:195` |
| `SOLDER_MASK` | 0.35 / 0.85 / 0.08 | `:277` |
| `STUDIO_BLUR` | 0.04 (a ceiling, not a taste) | `:491` |
| `SOFTBOX` | bright 18.0, radius 0.16 | `:540` |

---

## 5. Measurements, in one place

All at a fixed camera on the Arduino Uno, `.playwright-mcp/`:

| | before (`before-*`) | after (`linear-*`) |
|---|---|---|
| close-up tonal entropy | 4.432 bits | **6.184 bits** |
| luminances used | 217 | 249 |
| clipped pixels | 0.303% | 0.259% (see §9.3) |
| DIP crop darkest tenth ÷ mean | 0.269 | 0.170 |
| solder mask median | rgb(115, 129, 163) sat 0.29 | rgb(77, 93, 144) **sat 0.47** |
| unwelded seam pairs, `#a5a392` | 509 | 12 |

The clear coat, measured by switching it off and on and changing nothing else:

| camera | mask's brightest tenth, off → on |
|---|---|
| top-down | 148.0 → 172.2 (+16.3%) |
| default | 88.8 → 94.6 mean (+6.5%) |
| oblique | 132.3 → 128.2 (−3.1%) |

A coat returns what lies in the **mirror** direction, and in this room the
bright thing is overhead. OH-90 was filed predicting a grazing-angle
brightening, which is what Fresnel does under an open sky; it was the prediction
that was wrong.

---

## 6. Open work, highest priority first

### 6.1 Look at the board and decide whether it is done — *software-only, START HERE*

The user reported the 3D view wrong three times and the last fix (`7dc67fc`)
landed without their confirmation. **Open http://127.0.0.1:8088/, follow the
runbook's browser steps, and look.**

If it still reads flat, **the next lever is `SOFTBOX`'s position**, and the
analysis is done: it sits at the zenith (`height: 0.62`, centred on x = z = 0,
`webui/static/board3d.js:540`). The default camera is at
`(0.1, 0.85, 0.75) × reach`, about 48° above the board — so for a flat board the
mirror direction points **away from the camera at ~48° elevation**, not
straight up. The softbox's reflection therefore never lands in the default view.
Offsetting it toward −x −z at roughly 45° elevation would put the highlight
across the board face where a reader is looking.

**Measure it, and expect to rebuild the probe** — the script that produced
every number in §5 lived in the session's temp directory and is gone. It is ten
minutes: drive Chrome with Python Playwright (`channel="chrome"`), load the Uno
and the blink, drag the canvas by a fixed pixel delta to set the camera,
screenshot the canvas element, and classify a pixel as solder mask when
`blue > red + 18 and blue > green + 12 and blue < 250` — the mask is the only
strongly blue thing in the frame. Report the mean and the brightest tenth of
those pixels, and switch the thing under test off and on changing nothing else.

**Two traps, one round each, both worth knowing before you start.** Dragging
the mouse DOWN raises the camera toward the board's normal and dragging UP
lowers it — the first version assumed the opposite, sent the camera clean past
the horizon, and measured the board's unlit UNDERSIDE at luminance 14.8 in both
arms of the experiment. Two identical numbers is what a control looks like when
it is not measuring the thing at all. And a drag of −55 px is edge-on, where the
board is 16,000 pixels of its own rim rather than a face.

### 6.2 The PCB artwork as a texture — *blocked on a licence question*

Still the largest single visual jump available, and still blocked on the same
question as in the last handoff. The board is one flat colour with no
silkscreen, no traces and no pads. The Uno's `board.svg` is **not in the tree**:
`webui/assets.py` reads it out of the user's PICSimLab install at runtime, and
PICSimLab is GPL. **Answer `rules/licence-hygiene.md` before building on it.**
Planar UVs from x/z need no unwrap, so the work after the answer is small.

### 6.3 OH-84 — two parts cannot be wired to each other — *software-only*

Filed `5e5e4b8`, claims nothing, re-claim when starting. Every wire runs from a
board pad to a part terminal, so a series circuit borrows a spare input pin —
which is why the runbook's LED circuit goes through D12. The netlist already
copes; the change is a wire model with a nullable pad, a drag that can start on
a terminal, and the `blind`/`reaching` checks taught to read it.

### 6.4 Ambient occlusion, properly — *software-only*

OH-86 samples the hemisphere with three shadowed lights, which is three samples
of an integral. The two routes not taken are recorded in that ticket with what
ruled them out: **vertex-colour baking has nowhere to write** (the composed
Uno's PCB is 108 vertices over 68.6 × 53.3 mm — one every six millimetres), and
**SSAO costs the MSAA** the default framebuffer currently gives for free.

### 6.5 Carried unchanged

* **OH-71** (P3) — a PWM pad reports the level `PORT` holds.
  `test_a_pwm_pad_reports_the_port_bit_and_not_the_waveform` is written and
  passing, and closing OH-71 must make it fail.
* **Y1 and Y2**, the Uno's two undrawn parts, in `compose_board_3d.ABSENT`.
* **OH-8**, **OH-11** — i8086 timing and microcode-exact muldiv.
* **OH-36** — Cortex-M33. Blocked on an oracle **and held by a live session
  lock** (`agent-oh36`). Do not steal it.
* **OH-64**, **OH-38**, **OH-9** — blocked, see their tickets.

---

## 7. Commits this session

```
28e3296 chore(tickets): file and close OH-91
7dc67fc fix(webui): every albedo was an sRGB byte in a field glTF defines as linear
e85e1af chore(tickets): file and close OH-90
5d7bb37 feat(webui): a PCB is two layers, and it was being lit like three suns
19409b3 fix(webui): show the board, and say so when there is none
a86ea79 fix(webui): two settings the renderer was quietly overruling
ea60648 fix(webui): a page reload is not an error, so it stops printing one
a8e148f chore(tickets): file and close OH-86
34dbcfd feat(webui): light the board from three directions, all of which cast
c43aace chore(tickets): file and close OH-85
27c34ec feat(webui): seams welded, a room with no edges, shadows and a tone curve
5e5e4b8 chore(tickets): file OH-84, found while verifying the resistor
76546f1 chore(tickets): close OH-80
6c99ca4 feat(webui): a 220 ohm resistor, so an LED on an Uno is a circuit and not a warning
```

Closed: **OH-80, OH-85, OH-86, OH-87, OH-88, OH-89, OH-90, OH-91.**
Filed and left open: **OH-84.** No core, no ABI and no board count changed.

---

## 8. Visual verification

Every frame in `.playwright-mcp/`, driven in Chrome through Playwright directly
(the Playwright **MCP** server was killed mid-session — see §9.1).

**`linear-parts.png` — the current state, and the one to compare against.**
The Uno at the default camera, three-quarters from above. The PCB is a **deep
saturated blue** with a soft brightening running from the lower-left toward the
middle. The DIP-28, the barrel jack and the header shrouds are **black**, not
grey. Gold header pins carry distinct highlights down their length and cast
short shadows onto the board. The two electrolytic cans show a metallic gradient
on their lids with the straight terminator described in §2.3. A 220 Ω resistor
and a 5 mm LED stand on the bench to the right, unwired and therefore grey.

**`before-close.png` vs `linear-close.png` — the session's whole arc.** Before:
a pale periwinkle board, grey-looking black plastic, every component meeting the
board at a hard edge with nothing beneath it, and the USB shell blown to white.
After: a navy board, black components, a contact shadow under every part, and
the shell holding detail.

**`before-cans.png`, `sky-cans.png`, `pool-cans.png`, `envoff-cans.png`,
`mat-normal.png`, `mat-white.png`** — the five experiments of §2.3, at 4×
magnification. `mat-normal.png` is the decisive one: the lid painted by its own
normal is smooth and uniform, so the line is not geometry.

**`oh89-loaded.png` — 1366 × 768 at page load.** The board fills the visible
area, having scrolled itself into view. **`oh89-waiting.png`** is the same
window against a server with nothing loaded: the page sits at the top and the
Pins panel below carries the waiting caption instead of a blank rectangle.

**`resistor-limited-lit.png`** — the bench rows reading *"220 Ω resistor · lead
A on 13 × · lead B on 12 ×"* and *"at least 9.3 mA through it"*, with no red
warning line under either.

---

## 9. Known limitations, and things not to waste time on

### 9.1 The Playwright MCP server is dead in this session

Killed while clearing an orphaned browser profile lock. Everything since was
driven by **Python Playwright directly** (`from playwright.sync_api import
sync_playwright`, `channel="chrome"`), which works and is what the scratchpad
probes use. A fresh session gets the MCP server back.

### 9.2 The capacitor lid's straight line is not a bug

§2.3. Five experiments are recorded so nobody repeats them.

### 9.3 Clipping is 0.259%, not 0.011%

It rose when the softbox became compact and bright. The clipped pixels are the
softbox's reflection on the USB shell and the near-white page ground inside the
canvas screenshot. Not chased.

### 9.4 One console warning that is not ours

`X4122`, float precision from the D3D backend compiling three.js's own PMREM
shader. Confirmed by disabling the environment: 0 warnings without it, 1 with.
The repo's "0 warnings" bar has this one known exception, and the two warnings
this session added on top of it are gone (`a86ea79`).

### 9.5 The bench scrolls, and the board panel is tall

Carried from the last handoff and now partly addressed: the canvas moved above
its caption, so the panel's prose no longer sits between the reader and the
picture. At 1366 × 768 the canvas still starts 1,266 px down and the page
scrolls itself there.

### 9.6 Residuals unchanged from 2026-08-27

Wire penetration 0.289 mm; the USB-B's silk miss 0.40 mm; `PYI034` on
`__enter__` in all four cores; `core.avr.abi.Cpu` after `close()` segfaults —
two lines, in nobody's ticket, **carried from five handoffs ago**; `#6f6651`
still unidentified; a destroyed part's electrical behaviour still unmodelled.

### 9.7 Three test tripwires have now fired on their own comments

`NEUTRAL_LIGHT` (2026-08-27), `DirectionalLight`, and `PCFSoftShadowMap` — each
a test counting or forbidding an identifier that a comment then legitimately
mentioned. All three now strip comment lines first. **If you add a source-level
assertion to `tests/webui/test_board3d.py`, strip comments.** And two tests were
found passing for the wrong reason: one asserted `setScalar` was in the studio
long after the studio stopped calling it, because the word survived in a
comment.
