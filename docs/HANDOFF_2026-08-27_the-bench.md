# Handoff — the vendor's own boards, and a bench you can wire

| | |
|---|---|
| **Date** | 2026-08-27. The three previous handoffs are all dated 2026-08-26 — `systick-and-the-pin-view`, `the-ide-and-nine-tickets`, `the-avr-oracle-...`; where this disagrees with any of them, **this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `7cb5fe7` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed |
| **This session** | 6 commits from `8d90e52`. **22 files, 4,473 insertions, 89 deletions** |
| **Cores built** | `build/lib/`: `avr.dll` 116,736 · `cortexm0.dll` 228,864 · `i8086.dll` 130,048 · `riscv32.dll` 146,432 — **unchanged, no core was touched** |
| **Gate** | **1,557 passed, 17 skipped** (was 1,518); 1,574 collected; all eight checkers exit 0 |
| **Boards** | 26 imported, 12 runnable, 10 firmware-verified, 3 buildable — **unchanged**; now **9 draw the vendor's own 3D model** |
| **New tool dep** | `cadquery-ocp 7.9.3.1.1` (OpenCASCADE 7.9.3). **Import-time only.** node v24.11.1 also now runs a test suite |

**The emulator page is a bench now.** Open it, pick a XIAO SAMD21, type a
sketch, press Build and run — you get Seeed's own mechanical model of the
board, and you can drag a wire from a pad to a real 5 mm LED and watch it
light when the sketch drives that pin.

**Three of this session's four pieces of work came from the user mid-turn**,
not from a queue. Only the first (OH-70) came off the previous handoff.

**The second session is still quiet.** No commits but mine. Still stage by
explicit path — §9.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| The Uno's PORTC and PORTD live in the pin view | **ACHIEVED** | 22 of 32 pads; `webui/boards/atmega328p.py`; `e4ea0b1` |
| A pad the USART has taken says so | **ACHIEVED** | `USART_PINS`; measured `UCSR0B` 0b10011000 with `DDRD` 0b00000000 |
| The vendor's real 3D model, on the board | **ACHIEVED** | 4 models, 9 boards; `tools/import_3d_model.py`; `5bcac3e` |
| Alignment of model to pad map, reported not asserted | **ACHIEVED** | four files agree on DIP margins 3.025/2.875/2.853 × 1.331/1.131/1.271 mm |
| The page adapts to a wide window | **ACHIEVED** | three-column grid above 1500px; `.playwright-mcp/layout-2560-fixed.png` |
| No floating cylinders on the pins | **ACHIEVED** | `PAD_HEIGHT` 0.9 → 0.06, flush; `.playwright-mcp/pads-flush.png` |
| A physically simulated wire | **ACHIEVED** | `webui/static/wires.js`; 10 tests run under node; `fcce44c` |
| The wire collides with other objects | **ACHIEVED** | `Rope.collide`; `test_a_wire_does_not_end_a_step_inside_a_solid` |
| The wire has stiffness | **ACHIEVED** | `Rope.stiffen`, `STIFFNESS = 0.4`; `test_a_stiff_wire_hangs_less_deeply_than_a_limp_one` |
| Parts are real parts, not modelled shapes | **ACHIEVED** | KiCad `kicad-packages3D`; 3 LEDs + 1 buzzer; leads derived at 2.540 mm |
| A part is driven by the pin it is wired to | **ACHIEVED** | LED on D0 reads `unknown` → `high`; §8 |
| Wires can be removed individually | **ACHIEVED** | `disconnect(id)`, the `×` per row; part returns to `unknown` |
| Adding a part is a folders-in-folders menu | **ACHIEVED** | `KiCad packages3D › LED_THT › 5 mm LED`; §8 |
| The XIAO ESP32-C3 gets a model | **BLOCKED ON THE VENDOR** | Seeed publishes that one on GrabCAD, behind a login; §6.5 |
| A part can drive a pin (button, switch) | **BLOCKED ON THE CORE** | needs `PINB`/`PINC`/`PIND` and `PORT_IN`, all recorded unmodelled; §6.4 |
| A PWM pad reports the waveform | **NOT STARTED** | OH-71, filed and narrowed; §6.3 |
| A free-running clock behind Run | **NOT STARTED** | **§6.1, START HERE** |
| i8086 cycle counts / IMUL flags | **BLOCKED, unchanged** | OH-8, OH-11; §6.3 |
| 9 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36`; do not touch |

### What the page shows now

```
26 boards
├── 9 draw Seeed's own mechanical model   SAMD21 x2, RP2040 x2, ESP32-S3 x3, nRF52840 x2
├── 3 draw an extruded footprint and say so   XIAO-ESP32-C3-*  (model is on GrabCAD)
└── 14 the rest, unchanged

4 parts, in KiCad's own two folders
├── LED_THT          3 mm LED, 5 mm LED, 10 mm LED    leads 2.540 mm apart
└── Buzzer_Beeper    12 mm buzzer                     leads 7.600 mm apart
```

---

## 2. What changed, in one paragraph each

**OH-29 recorded that Seeed publishes no board 3D at all, and it was right
about the repository and looking in the wrong place.** The models are on the
wiki, and the vendor's own footprints had been naming them the whole time.
§3.1.

**Four vendor files, two axis conventions, and the first run reported a
component as the PCB.** Nothing threw. §3.2.

**A simulated wire found four different ways to stretch**, each with a number,
and none of them was the one the ticket predicted. §3.3.

**A mutation found dead code rather than a weak test** — two guards were doing
one job. §3.4.

**Two panel bugs the browser found and no assertion could**, both caused by
this session making `unknown` a thing that *moves*. §3.5.

**A lead tip was measured on the rim of a cylinder instead of its axis**, and
the wrong number looked entirely plausible. §3.6.

**The bench's own running commentary was rendered in the error style.** §3.7.

---

## 3. Root-cause narratives

### 3.1 A census that was right about the repository and looked in the wrong place

**Symptom.** The user said "get the real 3d model". `OH-29`'s note, from
2026-08-25, says:

> Verified against the vendor tree by full git ls-tree census, not a sparse
> checkout: Seeed's OSHW-XIAO-Series publishes ZERO board 3D models -- 0
> .step, 0 .stp, 0 .wrl.

**Hypotheses ruled out, and how.**

1. *A Grove module could be the part instead.* Fetched
   `wiki.seeedstudio.com/Grove-Red_LED/`: it lists a schematic PDF and a
   Codecraft zip, and **no 3D model at all**. Ruled out by reading the
   resource list.
2. *The component models already in `third_party/olimex-esp32-poe/` could
   serve.* They are real — `LED_0603_R.wrl` and 429 others — but 0603 chip
   parts are 1.6 mm long. Real LEDs, not things anybody wires a jumper to.
3. *The `.f3d` in the archive might hold a mesh.* It is a zip; opened it. It
   contains `BREP.*.smb` and `.smbh` blobs — Autodesk ShapeManager, a
   proprietary B-rep. No mesh.

**Root cause.** Two facts nobody had put together:

```bash
$ grep -h "(model" "third_party/seeed-xiao/Seeed Studio XIAO Series Library/"*.kicad_mod | sort -u
        (model "${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeeduino XIAO SAMD21 v4.step"
        (model "${AMZPATH}/3dmodels/AMz3D.3dshapes/Seeed Studio XIAO RP2040 v26.step"
        ... five in all
```

`${AMZPATH}` is a KiCad environment variable pointing at a library the vendor
does not ship, so nothing in the tree resolves it — which is exactly why a
census of the tree finds nothing. And the wiki publishes the files:

```bash
$ curl -sIL ".../Seeeduino-XIAO/res/seeeduino-xiao-samd21-3d-model.zip" | grep -i content-length
Content-Length: 18255477
```

Inside it: **`Seeeduino XIAO SAMD21 v4.step`** — character for character the
string in the footprint.

**Fix.** `tools/import_3d_model.py`, and `python tools/import_3d_model.py --all`.

**Generalization.** *A negative result is scoped to where you looked, and the
scope is the part that rots.* OH-29's census was rigorous and its conclusion
was stated without its scope — "Seeed publishes zero" rather than "Seeed's git
repository contains zero". The second sentence would have invited somebody to
look elsewhere; the first closed the question for a day. When recording that
something does not exist, record **where you searched** in the same sentence.

### 3.2 Four files, two axis conventions, and a component reported as the PCB

**Symptom.** The first `--all` run:

```
ESP32-S3:
  pcb    7.300 x 4.200 x 8.940 mm   (assembly 22.484 x 4.462 x 17.782 mm)
    XIAO-ESP32-S3-DIP: 14 pads span 15.250 x 15.237 mm; margin -3.975 x -5.519 mm
```

A **negative margin** — the pads are outside the board — and a "PCB" 7.3 mm
across on a board that is 22 mm long. **Nothing raised.** The mesh was written,
the index was written, exit code 0.

**The wrong assumption, and it was in the design.** `pcb_solid` picked the
solid with the largest area *in XY*, and `tessellate` mapped STEP's Z to
glTF's Y. Both encode "the board lies in the XY plane and Z is up", which is
KiCad's convention and most mechanical CAD's — and which two of Seeed's four
files do not use.

**Root cause**, from the assembly extents in each file's own axes:

```
SAMD21    22.601 x 17.901 x  4.511      thin in z   -> z-up
RP2040    17.514 x 22.014 x  4.419      thin in z   -> z-up
ESP32-S3  22.484 x  4.462 x 17.782      thin in y   -> y-UP
nRF52840  22.482 x  4.460 x 17.780      thin in y   -> y-UP
```

On a Y-up file the XY plane holds the board's *length* and its *thickness*, so
the largest-XY-area solid is a component standing on it.

**Fix.** `up_axis()` derives the vertical from the assembly's own smallest
extent — a property of a flat board rather than of a vendor — and `Frame`
emits one canonical frame from it. `handedness_of()` keeps the signed
permutation a rotation. After the fix all four agree:

```
SAMD21    21.300 x 17.900 x 1.610      DIP margin 3.025 x 1.331 mm
RP2040    21.000 x 17.500 x 1.200      DIP margin 2.875 x 1.131 mm
ESP32-S3  20.955 x 17.780 x 1.250      DIP margin 2.853 x 1.271 mm
nRF52840  20.955 x 17.780 x 1.250      DIP margin 2.853 x 1.271 mm
```

**Four independent files landing on the same margins is the alignment
evidence**, and it is stronger than the single residual OH-72 asked for.

**Note for whoever adds a fifth.** The SAMD21's frame reports `mirrored as
read` — `handedness_of((0, 2, 1))` is −1, so the short axis is negated and
every face's winding is flipped to match. That path is exercised by a real
file, not only by a test.

**Generalization.** *A converter that assumes a convention fails by producing
a plausible picture.* There is no exception to catch: a board lying on its side
is a board. The check that caught it cost one line — printing the PCB extent
beside the assembly extent for every file — and it would have been the first
thing cut if OH-72 had not said to *report* the residual rather than assert it.

### 3.3 Four ways a simulated wire stretches

Every one was found by printing `worstStretch()`, and every one looked fine on
screen. `Rope.worstStretch()` exists only because of this.

**(a) Dragged past its reach — 140%.** An end teleported nine units beyond
where the wire could span. The constraint cannot fix it: there is no shape a
rope that short can take between those two points. `payOut()` now lengthens the
wire, which is what a bench does — you reach for a longer lead. It only ever
grows. **A pointer never teleports**: the same nine units dragged smoothly
across ninety frames never exceeded 1.66%.

**(b) Pinned inside its own collider — 161%,** on a wire that had been still
for two seconds. The head is on a pad; the pad is on the board's top face; and
the box a board casts **includes its USB connector standing 2.4 mm proud**, so
every pad was inside the collider. The fix is two rules:

- collide against the **PCB slab**, from the model's own `pcb` extras, not the
  assembly's bounding box;
- **a wire is never blocked by the part it is plugged into** — its tail is
  inside that part by construction, so `applyColliders` filters that one out.

**(c) Contact resolved once at the end of a step — 75.6%,** against 16.3%
interleaved. This was tried on the reasoning that penetration is what must not
survive a step. An unopposed push leaves a shape the next step's constraints
have to undo, and the two argue across frames instead of within one.

**(d) Created with every node on one pad — 27.8% after 2.5 s of settling.**
`connect()` built the rope with head and tail coincident and then teleported
the tail to the terminal, so twenty-one nodes had to travel there *through the
board*. `beginWire(pad, end)` lays it out along its own line; the same wire
settles at **2.3%**.

**Where it ended up:** 2.3% and 1.0% for the two wires in §8, and 0.9% on the
Uno.

**Generalization.** *A solver's initial state is part of its answer.* (d) is
the one worth keeping: the transient was not merely slow to decay, it was
trapped — the constraint could not route nodes back out of a solid they had
been placed inside. Anything iterative that starts from a degenerate
configuration deserves a look at where it starts, not only at how it converges.

### 3.4 A mutation that found dead code, not a weak test

**Symptom.** Seven mutations were run against `tests/webui/test_wires.py`. Six
went red. One survived: replacing `taken < MAX_SUBSTEPS` in the loop with
`taken < 100000`.

**Root cause.** `advance()` clamped the accumulator *before* the loop:

```js
this.time = Math.min(this.time + Math.max(seconds, 0), SUBSTEP * MAX_SUBSTEPS);
while (this.time >= SUBSTEP && taken < MAX_SUBSTEPS) { ... }
```

The clamp already made more than `MAX_SUBSTEPS` iterations impossible, so the
loop's own bound could never fire. **The test could not catch it because
removing it changed nothing.**

**Fix.** One guard. The accumulator is not clamped; the loop caps; and the
leftover is dropped when the cap is hit:

```js
this.time += Math.max(seconds, 0);
while (this.time >= SUBSTEP && taken < MAX_SUBSTEPS) { ... }
if (taken === MAX_SUBSTEPS) this.time = 0;
```

The same mutation now fails `test_a_frame_that_never_came_does_not_run_the_whole_minute`.

**Generalization.** *A surviving mutation is not always a missing test.* Belt
and braces reads as care and is two things to keep true; when one of them is
unreachable, the mutation that survives is telling you the code is redundant,
not that the suite is thin. Check which before writing another test.

### 3.5 Two panel bugs, and the field that started moving

**Neither failed any DOM assertion**, and both are this session's own doing.

**The cause is one line of history.** Before OH-70 a pad was `unknown` because
the board's table had no row for it — fixed for the life of a board. Making
the Uno's USART take PD0 and PD1 partway through a `Serial` sketch made
`unknown` **a thing that moves**, and two places had quietly assumed it could
not.

**First: a row that contradicted itself.** `1 | PD1 | not modelled` — the pin
is named in the same row that says nothing models it. The two facts are told
apart by `chip_pin`, which `webui/api.py` fills from `PIN_NAMES`, derived from
the same `HEADER` that `pin_states` walks — so a pad carries a chip pin **if
and only if** the board answered for it. `not modelled` / `in use elsewhere`.

**Second: a count that had stopped counting.** The note read `22 of 32 pads
answerable` beside two rows that had stopped answering, because the number came
from `/api/board/pins` — correct when asked, and asked once. It is recomputed
from the pads on every state poll now.

**Generalization.** *A field that has always been constant acquires readers who
assume it.* Neither reader was wrong when it was written. When you make
something dynamic that was not, the search is for every place that cached it —
and the way both of these were found was driving the page and reading the
words, which is the third and fourth time this repository has recorded that.

### 3.6 A lead tip measured on the rim instead of the axis

**Symptom.** The first import of KiCad's 5 mm LED:

```
leads  cathode at (-1.270, -2.500, 0.200), anode at (0.870, -2.500, 0.200)
```

2.14 mm apart. `LED_D5.0mm` has leads on a **2.54 mm** pitch.

**Root cause.** `lead_tips` took the single lowest-y vertex on each side of the
origin. A lead is a tessellated cylinder, so its lowest vertices are a *ring* of
them and which one is enumerated first is an artefact of the tessellation. One
side happened to land on the lead's axis (−1.270) and the other on its rim
(0.870) — **and there is no way to tell which from the number alone.**

**Fix.** Take every vertex within `LEAD_RING` (0.05 mm, the tessellation's own
chord tolerance) of the minimum, and average:

```
leads  cathode at (-1.470, -2.500, 0.000), anode at (1.070, -2.500, 0.000)
```

2.540 mm to three decimals, and z centred. The buzzer independently gives
7.600 mm.

**Generalization.** *A measurement off a mesh must not depend on vertex order.*
The tell is a min or a max over tessellated geometry: any extremum on a curved
surface is a set, not a point, and picking one member of it is picking whatever
the mesher emitted first.

### 3.7 The error style on a normal message

**Symptom.** Found by looking at `.playwright-mcp/bench-panel-light.png`: the
bench's note — "Every part is wired. Drag from another pad to wire another." —
rendered as **red text on a red wash**.

**Root cause.** `webui/static/emulator.css:369`:

```css
.detail { color: var(--halt); background: color-mix(in srgb, var(--halt) 8%, var(--surface)); }
```

`.detail` is the *error* style. It is used for `#board-error` and
`#board-pins-fallback`, which really are errors. I reached for it because the
markup nearby used it.

**Fix.** A `.hint` class — quiet, muted, no background — for the bench note and
the tree's provenance line. `#board-pins-fallback` keeps `.detail`, because a
3D view that would not start is an error.

**Generalization.** *A class named for its shape gets used for its shape.*
`.detail` says "small print" and means "something went wrong". This is the same
defect as §3.5's wording bug in a different medium: the page said a normal
state was a failure, and no assertion about the DOM could tell.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 7cb5fe7

python tools/build_core.py
#  -> avr 116736 · cortexm0 228864 · i8086 130048 · riscv32 146432 (unchanged)

python -m pytest -q                       # -> 1557 passed, 17 skipped (~5 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0
```

### The 3D models — optional, and gitignored

**A fresh checkout has none of these and draws extruded footprints instead**,
which is the same path the ESP32-C3 takes permanently.

```bash
pip install cadquery-ocp                  # 7.9.3.1.1 here; ~81 MB wheel
python tools/import_3d_model.py --all     # boards AND parts; ~34 MB of fetches
#  -> 3,268,848 bytes of glTF for 4 model(s) + 126,008 for 4 parts
```

Report without writing anything, which is the fastest way to see the frame
each file arrives in:

```bash
python tools/import_3d_model.py --all --check
#  SAMD21:   axes  file is z-up; long side is its x; mirrored as read
#            pcb   21.300 x 17.900 x 1.610 mm
#  ESP32-S3: axes  file is y-up; long side is its x; right-handed as read
#            pcb   20.955 x 17.780 x 1.250 mm
```

**Without OCP it exits 3 and says SKIPPED**, verified by blanking the module:

```bash
python -c "
import sys
for n in ('OCP','OCP.STEPCAFControl','OCP.TDocStd','OCP.TCollection',
          'OCP.TDF','OCP.TopLoc','OCP.XCAFDoc','OCP.XCAFPrs'): sys.modules[n]=None
from tools import import_3d_model; print('exit', import_3d_model.main(['--chip','SAMD21']))"
#  -> SKIPPED: OpenCASCADE is not installed (...)  /  exit 3
```

### Driving the bench

**Kill every listener first and count them** — §9.

```bash
netstat -ano | grep ":8088" | grep LISTENING | awk '{print $5}' | sort -u \
  | while read pid; do taskkill //PID $pid //F; done
netstat -ano | grep ":8088" | grep -c LISTENING     # -> 0
python webui/emulator_server.py
```

1. Pick **XIAO-SAMD21-DIP**, type a sketch that drives `D0`, press **Build and run**.
2. The caption reads **"The vendor's own 3D model."** and the board is Seeed's.
3. **Add a part ▾** → `KiCad packages3D` → `LED_THT` → **5 mm LED**.
4. Drag from the `D0` pad to the LED's lower lead. A wire follows and drapes.
5. Press **Run**. The LED lights; the table's `D0 PA02` row reads `high` in green.
6. The chip under the buttons reads `5 mm LED — anode on D0ateral`; its `×` takes the
   wire off and the LED goes back to `unknown`.

**On an Arduino Uno** the caption stays "A footprint, extruded" — there is no
vendor model — and everything else works identically. That is the degradation
path and it is worth seeing once.

### The rope, without a browser

```bash
node --version                            # -> v24.11.1
python -m pytest tests/webui/test_wires.py -q     # -> 10 passed
```

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `tools/import_3d_model.py` | 48,501 | fetch, tessellate, emit glTF. Boards **and** parts |
| `webui/static/wires.js` | 19,174 | the rope. **Imports nothing**, which is why it is tested by running it |
| `webui/static/parts.js` | 7,955 | a loaded mesh becomes a part: terminals, lens, state |
| `tests/webui/test_wires.py` | 13,581 | 10 tests, run under node |
| `tests/rules/test_import_3d_model.py` | 12,937 | 15 tests; the frame algebra needs no OCP |
| `tests/avr/arduino/pins.cpp` | ~1.5 K | one pin per port, plus `A4` for the shared pad |
| `tests/avr/arduino/pwm.cpp` | ~1.2 K | OH-71's counter-example; needs `wiring_analog.c` |

### Modified

`webui/static/board3d.js` (+886 — a glTF reader, the bench, hit-testing,
`describe()`), `webui/static/board3d-panel.js` (+263 — the folder tree, the
wire list, two captions), `webui/static/emulator.css` (+181),
`webui/boards/atmega328p.py` (+203), `tests/webui/test_board3d.py` (+170),
`tests/avr/test_arduino_sketch.py` (+161), `tests/webui/test_pin_view.py`
(+46), `.gitignore` (+13), `CLAUDE.md` (+12), `webui/static/emulator.html`
(+17), `webui/emulator_server.py` (+6 — two content types).

### Generated, and NOT in git

`webui/static/models/` is gitignored, **for a licence reason and not a size
one** — see `.gitignore` and the tool's docstring. Present here:

| File | Bytes |
|---|---|
| `models/SAMD21.glb` | 1,434,248 |
| `models/nRF52840.glb` | 661,792 |
| `models/RP2040.glb` | 657,032 |
| `models/ESP32-S3.glb` | 515,776 |
| `models/parts/Buzzer_12x9_5RM7_6.glb` | 70,868 |
| `models/parts/LED_D10_0mm.glb` | 23,972 |
| `models/parts/LED_D5_0mm.glb` | 16,700 |
| `models/parts/LED_D3_0mm.glb` | 14,468 |
| `models/index.json` | — the catalogue the page builds its menu from |

`third_party/seeed-3d/` holds the fetched archives (~34 MB) and is gitignored
by the existing `third_party/` rule.

**A stale `models/parts/led.glb` was deleted during this handoff.** It was
written before parts were keyed by slug and nothing referenced it.

### Evidence that is NOT durable

`.playwright-mcp/*.png` — gitignored. This session's: `layout-2560.png` and
`layout-2560-fixed.png`, `model-samd21-dark.png`, `pads-flush.png`,
`wire-real-led.png`, `bench-wired.png`, `bench-panel-light.png`,
`bench-panel-dark.png`, `pins-uno-portcd-dark.png`, `pins-uno-serial.png`.
§8 describes each in words for that reason.

---

## 6. Open work, highest priority first

### 6.1 A free-running clock behind Run — *software-only, START HERE*

**This is the thing that makes everything else in the page pay off, and it is
the one piece missing.** The pins are live, a part is wired, an LED lights —
and a blink still cannot be *watched*, because Run is a fixed budget of
instructions and then it stops. You press Run repeatedly instead.

**It has no ticket. File one first.**

What is already there:

- `webui/api.py:1048` — `BoardSession.run(budget)`, and its docstring says
  plainly *"this deliberately does not run a budget of its own, because how
  long to run is a question about what is being watched, not about the board."*
  That sentence is the design decision to revisit, not a bug.
- `webui/api.py:689` — `MAX_RUN_STEPS = 200_000`, the ceiling a single request
  may ask for, with the stated reason: without one, a request pins the caller.
- `webui/static/emulator.js:765` — the page posts `{steps: BOARD_STEPS}` to
  `/api/board/run`.
- `webui/static/emulator.js:909` — the page **already** polls
  `/api/board/state` and calls `window.boardPins?.levels(state.pins)`.

**So what is missing is a server side that keeps stepping, not a UI.** The pin
view, the wires and the parts all repaint from the poll that already exists.

**The honest design question, unchanged from the last handoff and now sharper:
what does a "run" mean when the page can disconnect?** A thread stepping
forever behind an HTTP server outlives the tab that started it. Options worth
weighing before writing anything: a deadline the page renews on each poll (a
watchdog, so a closed tab stops the board); a budget-per-poll that the page
issues continuously; or a real background thread with an explicit stop route.
The first keeps the "no request pins the caller" property that `MAX_RUN_STEPS`
exists for.

**Verify it with the bench.** Wire a 5 mm LED to `D0`, load a sketch that
toggles `D0` with `delay(500)`, press Run once, and watch the LED blink
without touching anything. That is the whole acceptance test and it is visual.

### 6.2 The Uno's remaining ten pads, and its 3D model — *software-only*

Ten pads still read `not modelled` on an Arduino Uno and **all ten deserve
to**: `AREF`, `NC`, `IOREF`, `RESET`, `3V3`, `5V`, `VIN` and three `GND`s have
no MCU pin behind them. Nothing to do there.

What is missing is the Uno's **3D model**. It is a different vendor entirely
and was never looked for — `tools/import_3d_model.py`'s `MODELS` table is
Seeed's four. Arduino publishes design files for the Uno R3; whether a STEP is
among them is an open question and one fetch answers it. It is the board most
people start with and the only buildable board still drawn as a footprint.

### 6.3 The tickets that are open and unblocked — *software-only*

- **OH-71** (P3) — a PWM pad reports the level `PORT` holds, not the waveform
  the timer drives. Fully specified, measured, and **narrowed off every path**
  so it does not collide with anything; it re-claims
  `webui/boards/atmega328p.py` and `tests/avr/*` when started.
  `test_a_pwm_pad_reports_the_port_bit_and_not_the_waveform` is written and
  passing, and closing OH-71 must make it fail.
- **OH-8** — an EU cost table from Intel's published timings, not fitted.
- **OH-11** — three leads, in order: the 33 IDIV cases are all *prefixed*
  encodings, so check instruction *length*; solve per-case for the byte set;
  Ken Shirriff's microcode disassembly, never consulted.

### 6.4 Blocked, and why — *do not start these*

- **OH-36** — Cortex-M33, nine boards. Blocked on an oracle **and held by a
  live session lock** (`agent-oh36`). Do not steal it.
- **OH-64** — Cortex-M4, two nRF52840 boards. Blocked on an oracle. Note that
  those two boards **now have a vendor 3D model**, which changes nothing about
  the blocker.
- **OH-38** — Xtensa, three boards. Refused on evidence.
- **OH-9** — PICSimLab adapter.
- **Input parts** (a button that drives a pin) — needs `PINB`, `PINC`, `PIND`
  on AVR and `PORT_IN` on the SAMD21, every one of which this repository has
  already written down as returning a stored zero rather than the pin. That is
  core work and its own ticket; OH-73 declined it in as many words.

### 6.5 Residuals

1. **`/api/board/load-artefact` returns 400 with an empty artefact dropdown.**
   Observed several times across this session's browser passes; it is the only
   console noise the page produces and it is **pre-existing and unrelated to
   anything here**. `webui/static/emulator.js:548` `loadArtefact` guards on the
   board being chosen and **not** on the artefact path, so an empty
   `#artefact-pick` posts `path: ""` and the server refuses it — correctly.
   **What triggers the call when nothing has been picked was not traced**, so
   that is where to start rather than at the guard.
2. **The XIAO ESP32-C3's model is on GrabCAD**, behind a login and under
   someone else's terms. Three runnable boards keep the footprint. Recorded in
   `MODELS`' own comment so nobody re-searches.
3. **A 7-segment display would need more than two terminals.**
   `lead_tips` finds exactly two and `convert_part` refuses anything else,
   loudly. `Display_7Segment.3dshapes/7SegmentLED_LTS6760_LTS6780.step` is
   reachable (133,403 bytes) if somebody wants to generalise it.
4. **Parts cannot be dragged around the bench** — only added and removed. They
   are placed on a grid beside the board.
5. **`core.avr.abi.Cpu` after `close()` segfaults** the interpreter instead of
   raising. Two lines, in nobody's ticket. **Carried from two handoffs ago,
   still true.**
6. `sh1add`/`bset` accounted in the RISC-V sweep; `PYI034` on `__enter__` in
   all four cores; the UI does not surface which of a board's ISA the core
   executes. All unchanged.

---

## 7. Commits this session

```
7cb5fe7 chore(tickets): close OH-73
fcce44c feat(webui): wires you can drag, and real parts to drag them to
377ef11 chore(tickets): close OH-72, and file the wires it left an anchor for
5bcac3e feat(webui): the vendor's own board, not a footprint extruded
79c55fc chore(tickets): close OH-70, and file the lie it declined to fix
e4ea0b1 feat(boards): the Uno's PORTC and PORTD, so 22 of its 32 pads answer
```

Tickets closed: **OH-70, OH-72, OH-73**. Filed: **OH-71** (open, P3) and
**OH-73** (closed same session). No core, no ABI and no board count changed.

---

## 8. Visual output verification

Driven in Chromium via Playwright. Listener count verified 0 before starting
and 1 after, every time. **0 console messages at warning level or above on the
final pass**, excluding the pre-existing `load-artefact` 400s of §6.5.

**`layout-2560.png` — the fault, before.** A 2560px page. The disassembly and
registers stretch across the top; below them the board panel sits in a narrow
left column with the 3D view drawn in a wide, short letterbox, and to its right
roughly a third of the page is **empty white** below a short "Write a sketch"
panel. The sticky toolbar appears mid-page because a full-page capture paints
it where it is scrolled to — that part is a screenshot artefact, not a bug.

**`layout-2560-fixed.png` — after.** Three columns. Left: disassembly over
memory. Middle: registers, flags, and the sketch editor. Right: the whole board
panel, full height, with the 3D view now roughly square. No empty region.

**`model-samd21-dark.png` — the first render of the vendor's model**, far too
close because the camera still framed the board and not the scene. Legible in
it: **SEEEDUINO XIAO** on the white silkscreen block, the pin legend
(`IIC/I2C` yellow, `UART` blue, `ANALOG` orange, `DIGITAL` green), pin numbers
7–10 and `3V3`, gold castellated pads along both edges, and the USB-C
connector as a grey metal shell.

**`pads-flush.png` — the cylinders gone.** The same board framed properly.
Seven grey oval markers lie *on* the gold pads of the near edge rather than
standing above them. This is the frame that shows why the posts had to go: with
the vendor's real castellations underneath, a floating peg read as a mistake.

**`wire-real-led.png` — the first working wire.** A real 5 mm LED, lit bright
orange-red, its two metal leads visible, standing to the right of the board. A
**red cable** runs from its lower lead down and left, over the board's edge, to
a **green pad** — D0, driven high. The cable sags and is visibly not a straight
line.

**`bench-wired.png` — two parts.** The XIAO, a lit 5 mm LED, and a black 12 mm
buzzer with a small orange polarity mark on its top face. A red wire from a pad
to the LED and a **blue** wire from a second pad to the buzzer, both draping
over the board's near edge. The buzzer's mark is dark: D6 is driven low.

**`bench-panel-light.png` — the whole panel.** Above the canvas: the caption
*"The vendor's own 3D model. The board, its components and its connector are
Seeed's published mechanical model, tessellated by tools/import_3d_model.py;
the pad markers on it are this repository's reading of the chip's registers."*
Then **Add a part ▾**, **Unwire all**, a grey hint, and two rounded chips —
`5 mm LED — anode on D0 ×` and `12 mm buzzer — positive on D6 ×`. To the right
of the canvas the pin table: `D0 PA02 high` in green, `D6 PB08 low`, the rest
`input`, three power pads dimmed and `not modelled`.

**`bench-panel-dark.png` — the same, dark theme.** The panel and table invert;
**the board, the LED, the buzzer and the wires do not**. That is deliberate and
tested: their colours are the vendor's measurements, and only the pad markers —
this repository's reading of a register — follow the palette.

**`pins-uno-serial.png` — the Uno running a `Serial` sketch.** The note reads
`20 of 32 pads answerable`, down from 22. Rows `1 PD1 in use elsewhere` and
`0 PD0 in use elsewhere`, against `AREF — not modelled`. Two different
sentences for two different facts, which is §3.5.

---

## 9. Known limitations and traps

- **Backticks in a Bash heredoc are command-substituted**, and **a heredoc
  inside an `&&` chain breaks on quoting** — hit twice more this session, once
  on a Python note and once on a block of JavaScript. Both times the fix was
  the same: write the file with the `Write` tool and `cat` it in. That path has
  never failed.
- **`tools/tickets.py stop` releases only the CURRENT pid's lock.** Stale locks
  accumulate in `.omc/ticket-locks/`; only `OH-36.lock` (`agent-oh36`) is live.
  Delete the rest freely.
- **A ticket-only commit needs `.omc/current-ticket` blank**, because a ticket
  implicitly claims its own file.
- **Two open tickets may not claim the same path.** Filing OH-71 while holding
  OH-70 broke `test_this_repositorys_tickets_parse_and_do_not_collide`
  immediately. The convention is to **narrow the follow-up off every path** and
  say in its body that it re-claims them — which is what OH-64 did and what
  OH-71 now does.
- **`pkill -f` does not work in Git Bash here.** Count listeners before
  trusting the page: `netstat -ano | grep ':8088' | grep -c LISTENING`.
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`. Use
  `$USERPROFILE`.
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test.
- **`THREE.Clock` is deprecated in the vendored three.js** and warns in the
  console. `board3d.js` uses the timestamp `requestAnimationFrame` hands it.
  Anything else needing a delta should do the same rather than reach for
  `THREE.Timer`.
- **`setPointerCapture` throws `NotFoundError` on a synthesised pointer event**,
  which is what a Playwright-driven drag produces. It is wrapped in a
  `try`/`catch` because a drag works without it.
- **A raycast against a part's lead does not work.** A lead is a handful of
  triangles inside a mesh that is one object per colour, so a hit is the whole
  LED or nothing. `makeTarget` puts a 0.55-unit sphere on each terminal and
  that is what a wire is dropped on.
- **A ralph-style run does not get an independent reviewer here.** Every ticket
  this session was self-verified with a full gate, mutation testing, and a real
  browser. That is not the same as a review — say so rather than implying one
  happened.
