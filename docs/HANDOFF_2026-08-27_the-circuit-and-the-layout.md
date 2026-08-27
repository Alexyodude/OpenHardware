# Handoff — a bench that solves a circuit, and a page that reads its own shape

| | |
|---|---|
| **Date** | 2026-08-27, the third of the day. **Where this and the earlier two disagree, this one wins** |
| **Repo** | `Alexyodude/OpenHardware` — not a fork, MIT |
| **Branch / HEAD** | `master` @ `66c6a7f` |
| **Working tree** | **Clean.** Nothing uncommitted, nothing stashed, no ticket held |
| **This session** | 9 commits from `08b1fb7`. **19 files, 3,857 insertions, 109 deletions** |
| **Cores built** | `build/lib/`: `avr.dll` 116,736 · `cortexm0.dll` 228,864 · `i8086.dll` 130,048 · `riscv32.dll` 146,432 — **unchanged, no core was touched** |
| **Gate** | **1,671 passed, 17 skipped** (was 1,612); all eight checkers exit 0 |
| **Boards** | 26 imported, 12 runnable, 10 with a 3D model — **all unchanged** |
| **Tickets closed** | OH-79, OH-81, OH-82, OH-83. **Filed and left open: OH-80** |

**An LED now needs a circuit.** Wire one from D13 with its other leg in mid-air
and it stays dark and says why. Ground it and it lights — and is then reported
**destroyed**, because 40 mA through a part whose absolute maximum is 30 mA is
not a working LED.

**A STANDING USER INSTRUCTION, and it arrived mid-turn near the end:**
> "don't use artefacts on claude"

No Claude artifacts. One was published before that message landed
(`cf3a8382-…`) and the user has since deleted it. Serve things locally instead.

**START HERE: §6.1. OH-80, the resistor.** It is the only open ticket this
session created and it is now load-bearing rather than a nicety — there is
currently *no way* to light an LED on an Arduino Uno without destroying it.

---

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| An ungrounded LED does not light | **ACHIEVED** | `webui/static/circuit.js`; Chromium, pin 13 genuinely high; `08b1fb7` |
| A grounded LED lights, a reversed one does not | **ACHIEVED** | `test_an_led_wired_backwards_does_not_light`; §8 |
| The current is real arithmetic | **ACHIEVED** | 40.0 mA = (5.0 − 2.2)/(40 + 30) to 1e-9; `test_the_current_is_the_series_circuit_it_claims_to_be` |
| Every drive number is a datasheet's worst case | **ACHIEVED** | `SUPPLY` in `webui/boards/atmega328p.py`, cited to DS40002061B pp. 322–323 |
| A part past its absolute maximum is drawn destroyed | **ACHIEVED** | `480a206`; latches across a 300 ms blink, verified in-browser |
| The destroyed verdict cannot clear itself | **ACHIEVED** | `test_a_destroyed_part_stays_destroyed_when_the_pin_goes_low` |
| Each surface has its own material | **ACHIEVED** | `FINISHES` in `tools/import_3d_model.py`; `2c9d891` |
| Metal has something to reflect | **ACHIEVED** | brightest pixel 237 → **255**; tonal entropy 2.14 → 2.56 bits |
| `#808080` was left alone | **ACHIEVED** | `test_the_unstyled_colour_is_given_no_material` |
| The layout reads shape, not only width | **ACHIEVED** | portrait canvas 382 → **999** px, 36% → 94%; `4727481` |
| Nothing overflows at any viewport | **ACHIEVED** | `scrollWidth == clientWidth` at all seven sizes, before and after |
| **A resistor on the bench** | **NOT STARTED** | **§6.1, START HERE.** OH-80 |
| Shadows / ambient occlusion | **NOT STARTED** | §6.2 |
| Y1 and Y2 drawn | **NOT STARTED** | §6.3, carried from the last handoff |
| i8086 cycle counts / IMUL | **BLOCKED, unchanged** | OH-8, OH-11 |
| 9 Cortex-M33 boards | **BLOCKED ON ORACLE** | OH-36, held by `agent-oh36`; do not touch |

---

## 2. The one thing to take from this session

**Four of my own fixes were measured back out.** Not four bugs found — four
changes I wrote, believed, and then deleted because a probe said they made
things worse. That is the highest-value material here and every one of them
looked obviously right at the time:

| I wrote | The measurement | Outcome |
|---|---|---|
| `max-width: 2100px` on `main`, to stop an ultrawide stretching | board canvas 1037 → **549** px on a 3440 display | deleted |
| `(min-height: 700px)` on the three-column rule, to fix a short window | page went 2.9 → **4.1** screens | deleted |
| `#ffffff`, `#10178b`, `#000ca4`, `#ebebe5` in the material table | my own citation test asked for the evidence; 3 are 2–16 triangles | deleted |
| flex-basis `420px`, a hand-picked wrap threshold | fixed one window, did nothing for the commonest size | replaced by a derivation |

**The pattern: a fix aimed at a symptom, that is not aimed at its cause, moves
the symptom somewhere you were not measuring.** The only defence is to re-run
the probe on *your own* change with the same rigour you applied to the bug.

---

## 3. Root-cause narratives

### 3.1 A check that reads one input cannot notice a second one is missing

**Symptom.** The user, verbatim: *"the led is lighting up even though not
grounded. This issue stems from not physcially simulating the properties of the
datasheet and components."*

**Root cause, and it was four lines.** `webui/static/board3d.js`'s `applyState`:

```js
const pad = view.pads.get(wire.pin);
setPartState(wire.terminal.userData.part, pad.userData.state, view.palette);
```

One wire, one pad's logic level, straight to `lit`. No second terminal, no
ground, no current.

**Why it survived so long.** Every case it was ever tried on had both legs
wired, so it was right by the *shape of its inputs* rather than by anything in
it. The one-legged case was not a corner it handled badly — it was a question it
never asked.

**Fix.** `webui/static/circuit.js`, 615 lines, **importing nothing** so
`tests/webui/test_circuit.py` runs it under node exactly as `test_wires.py` and
`test_clock.py` do. Modified nodal analysis; diodes piecewise-linear, stamped as
their Norton companion so turning one on does not resize the matrix; states
iterated to consistency; Gaussian elimination with partial pivoting; SPICE's
`GMIN` from every node to ground so a leg in mid-air does not make the matrix
singular.

**Generalization.** *A predicate over one input is blind to the absence of a
second.* Look for functions whose correctness depends on a shape of the data
that nothing enforces.

### 3.2 Every number is a datasheet's worst case, and that decides what may be said

Not a bug — the design decision the whole solver rests on, and the thing most
likely to be broken by a well-meaning edit.

Each resistance is derived from a **guaranteed corner** of a datasheet, so it is
an *upper bound* on the real output resistance, so every computed current is a
**lower bound** on the real current.

```
ATmega328P, DS40002061B (Microchip, 2020)
  p.322  Absolute Maximum Ratings: DC Current per I/O Pin ... 40.0mA
  p.323  VOH min 4.2V at IOH = -20mA, VCC = 5V   -> source at most 40 ohm
  p.322  VOL max 0.9V at IOL =  20mA, VCC = 5V   -> sink   at most 45 ohm
Arduino UNO R3, arduino/docs-content tech-specs.yml
  I/O Voltage: 5V .  DC Current per I/O Pin: 20 mA
SAM D21, DS40001882L (Microchip, 2026)
  p.916  VOH min 0.8*VDD at IOH max 2mA, DRVSTR=0 -> source at most 330 ohm
  p.916  VOL max 0.2*VDD at IOL max 2.5mA          -> sink   at most 264 ohm
  p.906  46mA source / 65mA sink PER CLUSTER, and NO per-pin absolute maximum
```

**A lower bound over a rating is a fact. A lower bound under one is not a clean
bill of health.** So the page warns and never reassures, and `circuit.js`'s
header says so before any code.

**The one inversion, and it is deliberate.** `absolute_amps` on the LED (30 mA)
is taken at the *generous* end of its band, because it is a **limit** rather
than a term in the current. Lower-bound current over upper-bound limit holds
under every reading of both — which is what makes printing the word *destroyed*
safe. Choosing the pessimistic end there would condemn parts a more generous
datasheet allows.

### 3.3 The honest gap: KiCad's LED is generic

The two chips publish datasheets that were read to the page. **KiCad's mesh is
generic** — `LED_D5.0mm.step` carries no manufacturer and no order code, so
there is no datasheet to read.

So the LED's forward drop (2.2 V) and series resistance (30 Ω) are **class
values for a red indicator LED**, labelled as such in `LED_ELECTRICAL`, each
taken at the end of its range that keeps the current a lower bound. A specific
part number would be strictly better than every line of it.

**Do not quietly upgrade these to look like measurements.** The label is the
point.

### 3.4 The warning measured the wrong object

**Symptom.** Found while writing a test, not by any assertion that existed.

**Root cause.** `warn()` compared the **part's** current against the **pin's**
ratings. Two LEDs across one pad draw 25 mA each and the pad delivers 51 mA — so
a pin a quarter past its absolute maximum was reported as inside it.

**The mutation that nearly missed it.** With *two* LEDs the correct and the
broken code fire the same clause: 25 mA is over the pin's 20 mA rating whichever
current you measure. Killing it took **three** LEDs, where each part draws
18.7 mA — inside every rating it has — while the pin carries 56 mA.

**Generalization.** *A mutation test needs a case that distinguishes the fault,
not a case that exercises the line.* Same lesson as §3.1 from the other side.

### 3.5 The renderer was never the problem

**Symptom.** The user: *"how would we make the 3d view more realistic? Render
engine issue?"*

**Hypothesis ruled out, and it was the previous handoff's own advice.** §6.2 of
`HANDOFF_2026-08-27_the-uno-and-the-clock.md` says the scene clips to white and
that tone mapping is the top fix. Measured with `gl.readPixels` on a drawn Uno:
**0 of 132,961 board pixels clipped**, brightest channel 237/255, mean peak
132.6, and 55% of pixels inside one 16-value band. Under-exposed and flat, not
blown out. Tone mapping alone would have made it *darker*, and after the change
0.01% clip — so it is still not wanted.

**Root cause, in the importer.** `tools/import_3d_model.py` wrote
`metallicFactor: 0.1, roughnessFactor: 0.6` for every material of every model.
Gold contacts, nickel shell, tin legs, epoxy and solder mask were one substance.

**How the assignment was made evidence rather than opinion** — the reusable
technique:

```
#a5a392  8,497 tri  DIL28, MLF32, PANASONIC_D, barrel jack, SOT223, TS42
#050505  3,598 tri  the bodies of those same six
#b58136  1,224 tri  1X10, 1X08, 1X06, 2X03, 2X02 -- AND NOTHING ELSE
```

`#b58136` on the five pin-header packages and nowhere else is contact geometry
**by construction**. `#a5a392` is every component's leg *and* is what
`lead_tips` already treats as metal by rule. Three more are named outright in
`tools/blender/usb_b_receptacle.py`, which calls its own materials `shell`,
`cavity` and `pin`.

**Ask the composer which package contributed a colour. Do not look at the
colour.**

**And the biggest group is deliberately untouched.** `#808080` is `UNSTYLED` —
48,301 triangles across four vendor models, more than every named colour on the
Uno combined. A face the vendor did not style is a face whose material nobody
knows. `test_the_unstyled_colour_is_given_no_material` keeps it that way.

### 3.6 The layout read width and nothing else

**Symptom.** The user: *"make the website usable in different proportions and
aspect ratios and resolutions."*

**Two complaints that died before they were filed**, both by measurement:
nothing overflows at any of seven viewports (`scrollWidth == clientWidth`, zero
elements escaping a scrolling ancestor), and the pin table's constant 154 px —
which looked like a column that never uses its room — is the natural width of
`Pad | Pin | State` and reads perfectly.

**Root cause, one sentence.** A **1065 × 1920 portrait monitor is 1,065 px
wide**, past every threshold in the stylesheet, so it got the two-column layout
meant for a laptop. Two columns costs *width*, and width is what a tall display
has least of. The board came out 382 px, 36% of the page.

**The rule that replaced a guess.** `.pins-stage`'s flex basis decides whether
the 32-row table sits beside the board or below it. The honest form: *the table
may sit beside the canvas only while the canvas can still be as big as the
viewport allows.* The canvas stops growing at `--stage` tall, so at 4:3 it stops
needing width at `--stage * 4 / 3` — ask for exactly that.

**Generalization.** *A hand-picked threshold fixes the size you tested it on.*
Two were tried, each fixed one viewport and missed another, because a number is
not a reason.

---

## 4. Reproduce the result, cold

```bash
cd Code/Github/OpenHardware
git log --oneline -1                      # -> 66c6a7f

python tools/build_core.py
#  -> avr 116736 · cortexm0 228864 · i8086 130048 · riscv32 146432 (unchanged)

python -m pytest -q                       # -> 1671 passed, 17 skipped (~7 min)
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_ticket_claims check_board_claims; do
  python -m tools.$c; done                # -> all exit 0
```

**Kill any dev server on 8088 first** — `test_an_upload_from_another_origin_is_refused`
fails while one runs. Carried from the last handoff and still true.

### The models, which are gitignored and must be regenerated

```bash
pip install cadquery-ocp                  # 7.9.3.1.1 here
python tools/import_3d_model.py --parts   # LEDs gain their electrical model
#  -> "circuit  diode, anode to cathode: forward_volts 2.2, series_ohms 30, ..."
#  -> "finish #720301 ... metal 0.0 rough 0.20"
python tools/import_3d_model.py --all     # the four vendor boards
python tools/compose_board_3d.py          # the Uno
#  -> finish #a5a392 10,098 tri  metal 1.0 rough 0.35
#  -> finish #6f6651    100 tri  metal 0.1 rough 0.60  DEFAULT, nothing says what this is
#  -> webui/static/models/Arduino-Uno.glb  710,216 bytes
```

**`--parts` alone is not enough.** The composed Uno carries the finishes too and
comes from `compose_board_3d.py`.

### Seeing the circuit work

```bash
python webui/emulator_server.py           # http://127.0.0.1:8088/
```

1. Pick **Arduino Uno**, type a blink on pin 13, press **Build and run**, then **Run**.
2. **Add a part ▾** → `KiCad packages3D` → `LED_THT` → **5 mm LED**.
3. Drag from pad 13 to the anode **and nothing else** — it stays dark:
   *"only its anode is wired, so no current can return — cathode is in mid-air"*.
4. Drag from `GND` to the cathode — the row turns red with a **DESTROYED** pill:
   *"at least 40 mA through a part whose absolute maximum is 30 mA"*.
5. It stays destroyed when the pin goes low. Removing the part is the only reset.

### The measurement probes (both worth keeping)

Neither is committed — they are throwaway, and both are short enough to retype.

**Renderer tone**, run in the page console after a board is drawn:
read the framebuffer with `gl.readPixels`, drop pixels matching the ground
colour, and histogram `max(r,g,b)` into 16 buckets. Report clipped %, brightest
channel, mean peak, and Shannon entropy over the buckets. Entropy is the honest
metric: it measures how many distinct tones the image uses.

**Layout**, installed once as `window.__probe()` then called after each
`browser_resize`: sideways scroll, count of elements escaping *every* scrolling
ancestor, the canvas box and its ratio, longest `.prose p` line, page height in
screens.

---

## 5. File inventory

### New this session

| File | Bytes | What |
|---|---|---|
| `webui/static/circuit.js` | 28,323 | MNA + piecewise-linear diodes. **Imports nothing** |
| `tests/webui/test_circuit.py` | 44,012 | 33 tests, run under node against the real file |
| `docs/tickets/OH-79..OH-83*.md` | — | five tickets; OH-80 is the one left open |

### Modified

`tools/import_3d_model.py` (+402 — `Electrical`, `LED_ELECTRICAL`, `Finish`,
`FINISHES`, `report_finishes`), `webui/static/board3d.js` (+277 —
`applyCircuit`, `supplyOf`, `studio`, the destroyed latch),
`webui/static/parts.js` (+140 — `DRIVES`, `electricalOf`, the `damaged` paint),
`webui/static/emulator.css` (+140 — the aspect rule, `--stage`, the derived
basis), `webui/static/board3d-panel.js` (+96 — per-part rows, the badge),
`webui/boards/atmega328p.py` (+62 — `SUPPLY`), `webui/boards/samd21.py` (+59 —
`SUPPLY`), `webui/api.py` (+11 — the supply rides the pin view),
`webui/static/emulator.html` (+4), and four test files.

### Generated, NOT in git

| File | Bytes |
|---|---|
| `models/Arduino-Uno.glb` | 710,216 |
| `models/SAMD21.glb` | 1,434,252 |
| `models/nRF52840.glb` | 661,792 |
| `models/RP2040.glb` | 657,032 |
| `models/ESP32-S3.glb` | 515,776 |
| `models/parts/*.glb` | 70,872 / 25,712 / 18,440 / 16,208 |

### Evidence that is NOT durable

`.playwright-mcp/*.png` — gitignored. `circuit-ungrounded-dark.png`,
`circuit-grounded-lit.png`, `circuit-reversed-and-buzzer.png`,
`circuit-led-destroyed.png`, `circuit-destroyed-light-theme.png`,
`materials-after.png`, `resp-3440.png`, `resp-portrait-after.png`. §8 describes
each in words for that reason.

---

## 6. Open work, highest priority first

### 6.1 OH-80 — a resistor on the bench — *software-only, START HERE*

**It is load-bearing now, not a nicety.** There is currently **no way to light
an LED on an Arduino Uno without destroying it**: two in series at 6 mA is the
only intact circuit the bench can build, because nothing limits current. That is
the physically correct answer and it makes the bench hard to demonstrate.

The ticket is filed and **claims no paths** — it was narrowed off every one in
`9670b71` so OH-81 could take `tools/import_3d_model.py`. **Re-claim
`tools/import_3d_model.py` and `tests/rules/test_import_3d_model.py` when you
start it**; the ticket body says so.

Three small changes to `tools/import_3d_model.py`:
* `Part.lens` becomes optional — a resistor does not light, `dressPart` already
  copes with a missing lens, and `convert_part` currently *raises* if the named
  colour is absent;
* an `Electrical` of kind `resistor` — `circuit.js` already stamps it, and
  `analyse` already reads `model.ohms` for a non-diode part;
* one entry per value offered.

**The only real question, and it is in the ticket:** KiCad's resistor mesh
carries painted colour bands, and they will not read 220 Ω. A part labelled with
a value its picture contradicts is a small version of the defect this area keeps
re-learning. Either the label says the bands are the model's, or the value comes
off the bands, or the part is named for its package.

### 6.2 Shadows, or baked ambient occlusion — *software-only*

The next thing that would make the 3D view more real, now that materials and
the environment are in. Fifteen components still **float** rather than sit on
the board; a contact shadow is what says "this is attached to that".

Two routes: a shadow map (one extra render pass), or bake AO into **vertex
colours at import time** — view-independent, free at runtime, computed where
OpenCASCADE already is, and needs no UVs, which matters because the meshes have
none (`attributes = ['NORMAL', 'POSITION']`, 0 textures).

**The stale comment that used to sit in `mount()` is gone** — it said "this
scene has one object" and had been false since OH-75. The shadows it was
refusing are still absent.

### 6.3 The cheap experiment nobody has run — *software-only*

`ANGULAR = 0.5` in `tools/import_3d_model.py` is OpenCASCADE's default: about
**29° between facets**, which is why the barrel jack, the electrolytics and the
LED domes are visibly polygonal in silhouette. Dropping it to ~0.2 costs
triangles and nothing else. One line, one re-import, one look.

### 6.4 The PCB artwork as a texture — *blocked on a licence question*

Would be the biggest single visual jump: the board is a flat colour and the
artwork it was traced from already exists. Planar UVs from x/z need no unwrap.

**Answer the licence question first.** The XIAO artwork is vendored
(`webui/boards/*.svg`), but the Uno's `board.svg` is **not in the tree** —
`webui/assets.py` reads it out of the user's PICSimLab install at runtime, and
PICSimLab is GPL. Check `rules/licence-hygiene.md` before building on it.

### 6.5 Carried from the last handoff, unchanged

* **Y1 and Y2**, the Uno's two undrawn parts, recorded in
  `compose_board_3d.ABSENT` with the measurement that rules the near miss out.
* **OH-71** (P3) — a PWM pad reports the level `PORT` holds.
  `test_a_pwm_pad_reports_the_port_bit_and_not_the_waveform` is written and
  passing, and closing OH-71 must make it fail.
* **OH-8**, **OH-11** — i8086 timing and microcode-exact muldiv.

### 6.6 Blocked, and why — *do not start these*

* **OH-36** — Cortex-M33. Blocked on an oracle **and held by a live session
  lock** (`agent-oh36`). Do not steal it.
* **OH-64** — Cortex-M4. Blocked on an oracle.
* **OH-38** — Xtensa. Refused on evidence.
* **OH-9** — PICSimLab adapter.
* **Input parts** (a button driving a pin) — still needs `PINB`/`PINC`/`PIND`
  and `PORT_IN`. **A circuit solver is now the natural place for a switch to
  close a node**, which is half the work done.

### 6.7 Residuals

1. **The bench scrolls more than it did.** The pin table drops below the canvas
   at more sizes: 1905 × 1080 went 1.6 → 2.0 screens, 3425 × 1440 went 1.2 →
   1.8. The trade for a board 36% and 15% wider. Stated, not hidden.
2. **The board panel is 1,548 px tall at 1351 px**, mostly its own caption
   prose. Deliberately not fixed: that caption is the honest-degradation
   statement about a composed model. If anyone takes it on, the question is
   whether it can be **shorter**, not whether it can be **hidden**.
3. **One console warning that is not ours.** `X4122`, float precision from the
   D3D backend compiling three.js's own PMREM shader. Confirmed by disabling
   the environment and reloading — 0 warnings without it, 1 with. The repo's
   "0 warnings" bar now has one known exception.
4. **`#6f6651` is unidentified** — 100 triangles shared by a QFN-32 and a
   SOT-223, very probably an exposed thermal pad and not evidenced enough to
   say so. It takes the stated default and the importer prints that it did.
5. **A destroyed part's electrical behaviour is not modelled.** A burnt LED
   fails open or short depending on how it died; the netlist is unchanged and
   the panel says so.
6. **`core.avr.abi.Cpu` after `close()` segfaults.** Two lines, in nobody's
   ticket. **Carried from four handoffs ago.**
7. Wire penetration settles at 0.289 mm; the USB-B's silk miss is 0.40 mm;
   `PYI034` on `__enter__` in all four cores. Unchanged.

---

## 7. Commits this session

```
66c6a7f chore(tickets): close OH-83
4727481 fix(webui): a layout that reads the viewport's shape and not only its width
79bd618 chore(tickets): close OH-82
2c9d891 feat(webui): what each surface is made of, and something for metal to reflect
2aa79c7 chore(tickets): close OH-81
480a206 feat(webui): a part past its absolute maximum is destroyed, and says so
9670b71 chore(tickets): narrow OH-80 off every path, so OH-81 can claim one
c6adeb1 chore(tickets): close OH-79, and file OH-80 for the resistor it needs
08b1fb7 feat(webui): a circuit, so an LED needs a complete one to light
```

Closed: **OH-79, OH-81, OH-82, OH-83**. Filed and left open: **OH-80**.
No core, no ABI and no board count changed.

---

## 8. Visual output verification

Driven in Chromium via Playwright, against a **real running blink** with pin 13
observed high, not a stopped board where every pad reads `input` and an LED
would be dark either way.

**`circuit-ungrounded-dark.png` — the user's bug, fixed.** The Uno with a red
cable from a pad to a 5 mm LED standing to the right. The LED is **dark red**.
The bench row beneath reads *"5 mm LED · anode on 13 × · only its anode is
wired, so no current can return — cathode is in mid-air"*.

**`circuit-grounded-lit.png` — a complete circuit.** The same board with a
second, blue cable from GND to the cathode. The LED is bright orange-red. The
row has a green border and reads *"at least 40 mA through it"*, with a red line
under it: *"No current limiting: at least 40 mA, past the 20 mA this board rates
a pin for."* Pin 13 reads `high` in green in the table at right.

**`circuit-led-destroyed.png` — the latch.** Same wiring, after pin 13 has been
*observed low*. The LED is drawn pale pink (`--halt`), the row is red-tinted
with a **DESTROYED** pill beside the label, and the sentence reads *"destroyed
earlier by more current than its absolute maximum. What a destroyed part does
electrically is not modelled…"* It did not flicker back to dark.

**`circuit-reversed-and-buzzer.png` — two negative controls.** A 5 mm LED with
cathode on 13 and anode on GND, dark, reading *"reversed: its cathode is 5.00 V
above its anode, and a diode blocks that way"*; and a black 12 mm buzzer reading
*"no published electrical model for this part, so it is a conductor of unknown
value and no current is claimed"*.

**`circuit-destroyed-light-theme.png` — the same in the light theme.** The
destroyed row has a pink-tinted ground and a maroon DESTROYED pill. Two 3 mm
LEDs beside it are quiet grey with *"only its anode is wired"*. **This is where
the known limitation shows:** at this size the destroyed 5 mm LED is a dark
maroon and not obviously distinct from an unlit one. The panel carries the
claim; the mesh is only a cue.

**`materials-after.png` — the materials, canvas only.** The Uno with genuinely
metallic gold header pins carrying highlights along their length; a bright
silver USB shell with a clear top-to-side gradient; metallic tops on both
electrolytic cans; bright tin DIP-28 legs; matte black plastic on the barrel
jack, shrouds and DIP body; a semi-gloss blue PCB.

**`resp-3440.png` — the ultrawide, BEFORE the layout change.** Three columns.
The left column's disassembly panel is a ~690 px box holding about 250 px of
text, with a large void beneath it before the memory panel. Kept as the
before-picture.

**`resp-portrait-after.png` — 1080 × 1920, after.** One column. The registers
table spans the full width; below it the load-and-run panel, the pins caption,
the bench bar, and then a **large** board canvas running off the bottom of the
fold. The toolbar has wrapped to two rows, which is `.bar { flex-wrap }` doing
its job.

---

## 9. Known limitations and traps

- **Do not use Claude artifacts.** Standing user instruction, given this
  session. Serve pages locally instead — `python -m http.server` from a
  scratchpad directory works and the user can open the URL.
- **A destroyed part is only unmistakable in the panel.** Colour is the only
  channel the 3D view has, and at the size a 5 mm LED is drawn a broken red one
  and a lit red one are both red. A second cue is worth having and is nobody's
  ticket.
- **`test_an_upload_from_another_origin_is_refused` fails while a dev server
  runs on 8088.** Carried from the last handoff. `netstat -ano | grep ":8088" |
  grep -c LISTENING` before trusting a gate.
- **Backslashes in a Bash heredoc that patches Python.** Hit AGAIN this session:
  `"\\n".join(...)` inside a heredoc reached the file as a real newline and
  produced `SyntaxError: unterminated string literal`. **Use the `Edit` tool for
  anything containing an escape.** Third handoff in a row for this one.
- **A comment mentioning a symbol defeats a grep-based test.** Two of my own
  tests passed for the wrong reason: `NEUTRAL_LIGHT`'s use count stayed at 2
  because a new *comment* mentioned it while the light it counted was deleted;
  and a `background` check used `in` on a string that appears twice. **Strip
  comments, and count uses against something real.**
- **`tools/tickets.py stop` releases only the CURRENT pid's lock**, and each
  `python tools/tickets.py` subprocess is a different pid. Remove
  `.omc/ticket-locks/OH-NN.lock` by hand after closing.
- **Two open tickets may not claim the same path**, and a ticket filed for work
  nobody is doing is a lock that only ever blocks. File follow-ups with
  `--touches` empty and name the paths in the body.
- **WebFetch caps at 10 MB**, which is most datasheets. Download with `urllib`
  and a browser User-Agent, then `pdftotext -layout` (it is at
  `/mingw64/bin/pdftotext`). `-layout` shuffles table columns — read 100 lines
  around a hit rather than trusting one line.
- **`gh api` reaches vendor documentation source.** Arduino's board specs are
  YAML in `arduino/docs-content` that the rendered page does not expose.
- **WebSearch has a 200-call per-session budget and this session exhausted it.**
- **Do not add `@pytest.mark.parametrize`.** `tools/inventory.py` counts
  `def test_*` with `ast`. Loop inside one test. (This conflicts with
  `.claude/rules/tests.md` rule 5; the repo-root `CLAUDE.md` is more specific
  and wins.)
- **`~` is not the home directory in Git Bash here.** `HOME=/c/SPB_Data`; use
  `$USERPROFILE`.
- **A ralph-style run does not get an independent reviewer here.** Every ticket
  this session was self-verified with a full gate, mutation testing and a real
  browser. That is not a review — say so rather than implying one happened.
