# Handoff — every pad finds its pin, and the surveys that got it there

    date          2026-08-30 (second handoff today; the morning one is
                  docs/HANDOFF_2026-08-30_the-board-not-the-parts.md)
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          ebac9f8  feat(tools): the Uno prints its silkscreen
    session base  a19a8e5  (23 commits this session)
    gate          1,905 passed, 17 skipped   (a19a8e5 was 1,850)
    checkers      all eight exit 0
    ruff          tools/ 37 (unchanged all day); webui/ 19, PRE-EXISTING —
                  verified identical with the session's changes stashed
    ticket held   none.  OH-36 is held by a LIVE session `agent-oh36`; never take it
    server        the user's `python webui/emulator_server.py` on 127.0.0.1:8088,
                  started before the morning session. **IT NEEDS A RESTART and
                  this is the one live-state trap in this handoff** — see §8.1.
    models        17 `.glb` on disk, all gitignored, all REGENERATED this
                  session. A fresh checkout must run runbook §3.

**Fifteen tickets closed, twenty-eight filed, and the closing move of the day:
every pad on every composed board now finds its own pin — 32/32, 30/30, 24/24,
22/22, 34/34, 14/14 — measured in the browser.** The route there was five
stacked root causes (§2.1–§2.5), three of them found by measuring a symptom two
earlier tickets had each mis-attributed.

The session's second act was the user's directive: *"create good 3d models and
periheral connections and modules. there are many issues with wire, 3d model,
breath, api/mcp integration, ide. Go in parrallel and create tickets then
solve."* Three read-only survey agents ran in parallel over wire/bench, the 3D
pipeline, and API/IDE; their ~35 evidenced findings became OH-119..142, and the
highest-value nine were solved the same session. ("breath" was read as the
bench/breadboard area; the user did not correct it.)

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| OH-99 nRF54LM20A green | DONE | `4c80cd2`; mask film identified by shape, two loose faces, not four solids |
| OH-106 half-turn blindness | DONE | `e97e369`; vendor pin-1 markers, 6 packages, margins 1.6–23.6 mm |
| OH-96 Uno pad-map "disagreement" | DONE — premise false | `8dd69b9`; both sources agree to 0.072 mm under one scale |
| OH-71 PWM pad honesty | DONE | `39541b6`; `unknown` via COM bits, DDR asked first |
| OH-98 vendor model statements | DONE — premise inverted | `c61ca2b`; 17 usable statements, all 17 already agree, 1 disagreement is the vendor's |
| OH-84 two-part wiring | DONE — option 2 | `bf723cf`; the junction note; the wire itself is OH-116, ten call sites costed |
| OH-117 lost GND pads | DONE | `d7d65cd`; `view.pads` holds lists; Uno 30→32 pads |
| OH-115 pads vs pins | DONE — cause was a third thing | `67bfd94`; the z-mirror, §2.1 |
| OH-118 XIAO DIP headers | DONE | `3fdb273`; flip machinery, variant split, §2.3 |
| OH-134 untypable editor | DONE | `3a121fe`; TEXTAREA joins the keydown guard |
| OH-128 wire anchors at board centre | DONE | `fbb3fce`; carved pin position on the mesh, §2.2 |
| OH-120 copper is a dielectric | DONE | `908b92a`; FINISHES entries + carve gate, §2.4 |
| OH-121 SMD scale mismatch | DONE | `f340800`; maps state `px_per_mm`, §2.5 |
| OH-119 the pin-13 LED | DONE | `2c6ee8e`; Uno 15→47 drawn parts, closed-world test |
| OH-122 the Uno's silkscreen | DONE | `ebac9f8`; ink 0→401/4, unread counted |
| OH-135..142, 123..127, 129..133, 116 | NOT STARTED | filed with evidence; §5 |
| Ledger provenance question | **NEEDS THE USER** | §5.9 |

---

## 2. Root causes — the five-layer stack under "many issues with wire"

Read §2.1–§2.5 as one story: five independent defects, each masking the next,
all under one user complaint. Fixing any one alone changed almost nothing
visible, which is why they survived so long.

### 2.1 The z-mirror: every pad sat on the row OPPOSITE its pin

**Symptom.** OH-96 measured five Uno pads 1.21–3.84 mm from any pin and eleven
more out by 0.7. Two tickets (OH-96, then OH-115) were filed against wrong
suspects — the traced pad map, then the alignment estimators — and both were
DISPROVED by measurement before the cause surfaced.

**Cause.** `board3d.js` mapped image y to scene z with a negation — and image y
is ALREADY the negation of board y, so a composed model's pins (z = −board_y)
landed on the row opposite every pad. **28 of the Uno's 32 mirrored pads still
fell within `PIN_REACH_MM` of a pin — the WRONG pin, carved silently** — because
the two header rows share a 2.54 mm grid. Only the five whose opposite-x had no
pin ever showed. The line's own comment had warned that getting this sign wrong
"mirrors the header end for end".

**How it was found.** Pairing every page pad with every vendor pad under each
sign: one sign puts all 32 on their OWN pin within 0.1 mm (SCL on AD5/SCL, 13
on SCK, IOREF on the +5V the R3 ties it to); the other reproduces the browser's
28-wrong-4-missing exactly. The 0.65–0.77 mm "middle group" OH-96 recorded was
the x-offset between the two rows' pins at those columns — the mirror's
fingerprint, unrecognised through two tickets.

**Generalization.** A mirror on a grid-symmetric field fails at 12%, not 100% —
and the failures it does produce point at the data, not the transform. When a
"which of these two sources is wrong" question measures as NEITHER, go find the
frame between them.

### 2.2 A carved pin reported the model group's origin

`carvePins` baked each pad's offset into the replacement mesh's GEOMETRY and
never set `pin.position`, so `getWorldPosition` — `anchorOf` every frame,
`beginWire`, the drag plane — answered the group origin: the pad-map centroid
on the board's UNDERSIDE, inside the PCB slab collider. Every wire on a board
with vendor pins anchored there. OH-95's close note claimed the opposite ("the
anchor goes on working"); the wire survey caught it with the vendored three.js
under node, and the fix re-bakes vertices relative to `pad.at` and puts that
point on the mesh. Fixing it exposed a second defect: claim buckets keyed by
pin NAME built three coincident z-fighting meshes for the Uno's three GNDs.

### 2.3 A XIAO DIP is the SMD board plus headers nobody composed

The published `.kicad_pcb` is the SMD board; the DIP variant's pins sit on the
vendor's own 0.6" DIP footprint rows (±7.62 mm — measured across all twelve
`XIAO-*-DIP.kicad_mod` files), INBOARD of the castellations, where the composed
model had no metal within 3.25 mm. `Component.flip` + `place(..., flip=)` hang
KiCad's header models below the board — (x, z) both negated, a proper rotation,
one axis alone would be §2.1 again — body against the underside, tails proud of
the top face on the pads. The DIP/SMD variants stopped sharing one file
(`dataclasses.replace`-derived SMD compositions, so they cannot drift);
`-DIP-SMD` keeps the DIP file because its pad map is identical, measured pad
for pad.

### 2.4 Composed copper was a dielectric, and the carve gate reads metalness

`compose_board_3d.COPPER` had no `FINISHES` entry → DEFAULT_FINISH, metalness
0.10 → matte pads AND invisible to `carvePins`' `metalness > 0.5` gate, so an
SMD XIAO's castellation copper could never be claimed. Two FINISHES entries
(keys test-pinned to the composer's constants) + `report_finishes` called
before every composed write. SMD real pins: RP2350 18→29, C3 0→20.

### 2.5 The page re-derived a stated scale from two different pad fields

`scaleFromPads` divided the page's pixel span by the model's `pad_span` — on an
SMD XIAO those describe DIFFERENT fields (28 castellation sub-pads vs one pad
per castellation) — drawing every composed SMD model 9% small. Every generated
map had said "scaled at 8.0 px/mm" in prose all along. `px_per_mm` is now a
FIELD: emitted by `tools/import_board.py`, stamped into the 25 existing maps
FROM each file's own derivation sentence (a test holds field to prose per
file), validated in `pinmap.parse`, forwarded by the pins route, preferred by
`placeModel`. The traced Uno map states none on purpose (anisotropic artwork,
no single true scale) and keeps the fit, exact there at 0.093 mm.

### 2.6 Test lessons this session paid for (all now in ticket notes)

  * **A source assertion a comment can satisfy is not an assertion about the
    code.** `padMeshes`' own docstring quoted the expression the test grepped
    for; two bug-reintroducing mutations survived until assertions moved onto
    extracted function BODIES with comment lines stripped. (OH-117, reapplied
    in OH-128/120/121/122.)
  * **A right-hand side imported from the module under test agrees with itself
    however wrong the module is.** Twice more today: `TIMER_PINS` addresses
    (OH-71) and `DIP_ROW_OFFSET_MM` (OH-118). Assert vendor-header literals.
  * **A channel of 0x00/0xff is a fixed point of the sRGB transform**, so
    "linear ≠ bytes" is unsatisfiable for pure colours; the albedo test now
    exempts them with the argument (found when OH-119's fetched LED lens
    brought in #0000ff).
  * The heredoc trap hit AGAIN (apostrophes in a `<<'PY'` block) — fourth
    session running. Write the script with the Write tool, run the file.

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. Gate.
python -m pytest -q                       # -> 1905 passed, 17 skipped, ~7-9 min
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"; done   # all 0
ruff check tools/ | grep '^Found'         # Found 37 errors. (baseline)

# 2. Tool deps: pip install cadquery-ocp ; Blender 4.5 at the usual path.

# 3. REGENERATE (fresh checkout only; every mesh is gitignored).
python tools/model_from_datasheet.py      # 13 parts
python tools/import_3d_model.py --all     # 6 boards + parts
python tools/compose_board_3d.py          # ELEVEN boards now (5 DIP + 5 SMD + Uno), ~8 min
#   Uno: drawn 47, ink front 401/back 4, 1,932,400 bytes
#   every DIP board prints "mask/turn/finish" audit lines; SMD glbs have no legs

# 4. RESTART THE SERVER (see 8.1 -- required this time, unlike the morning):
python webui/emulator_server.py           # http://127.0.0.1:8088/

# 5. Browser ground truth (the measurement that closed the day):
#    python + playwright, select each board, then in page:
#      const m = await import('/board3d.js'); const d = m.describe();
#      d.padCount, d.realPins.length, d.model.scale
#    Expect: Uno 32/32 @0.5638; RP2350-DIP 24/24, RP2350-SMD 30/30,
#    C3-SMD 22/22, nRF54l15-SMD 34/34, all @0.8000. Missing lists EMPTY.
```

---

## 4. File inventory (changed this session)

| File | What |
|---|---|
| `tools/compose_board_3d.py` | `mark_turns`/`mark_of`/`half_turn_moves`/`turn_unseen`/`MARK_OFFSET_FRACTION` (OH-106); `Component.flip`, `dip_header_elements`, `DIP_ROW_*`, SMD variant derivation, `Composition.dip_headers` (OH-118); 12 new CORRESPONDENCE rows + 4 ABSENT rows (OH-119); `report_finishes` call (OH-120); `px_per_mm`-aware `pad_span` note (OH-121) |
| `tools/import_3d_model.py` | `is_mask_film`/`mask_film_faces_of`/`MASK_*` + `colour_key(is_film)` (OH-99); COMPOSED per-variant files (OH-118); FINISHES `#c8a253`/`#e9e9e4` (OH-120) |
| `tools/eagle.py` | `Element.mark` + `_silk_mark` (OH-106); `_ink` + `INK_LAYERS`, `Board.silk`/`silk_unread` filled (OH-122) |
| `tools/kicad.py` | `Placement.mark` + `_mark_of` (OH-106); `StatedModel` + `_models_of` + corrected header claim (OH-98) |
| `tools/import_board.py` | emits `px_per_mm` (OH-121) |
| `webui/pinmap.py`, `webui/api.py` | `px_per_mm` carried and served (OH-121) — **needs the server restart** |
| `webui/boards/*.json` | 25 generated maps stamped with `px_per_mm` from their own derivation |
| `webui/boards/atmega328p.py` | `TIMER_PINS`, `TCCR1A/2A`, COM masks, `pin_states` order (OH-71) |
| `webui/static/board3d.js` | pad z sign (§2.1); pads-as-lists + `padMeshes`/`addPad` (OH-117); carve per-entry buckets + `pin.position` (§2.2); stated-scale preference (§2.5); junction note consumed from circuit.js side |
| `webui/static/circuit.js` | `JUNCTION_NOTE` + midAir counting (OH-84) |
| `webui/static/emulator.js` | TEXTAREA in the keydown guard (OH-134) |
| tests | +~40 across test_compose_board_3d / test_import_3d_model / test_import_board / test_kicad / test_board3d / test_pin_view / test_circuit / test_editor / test_arduino_sketch |
| `docs/tickets/` | 15 closed with correction notes; OH-115..142 filed |

Screenshots (`.playwright-mcp/`): `oh99-lm20a-before/after.png`,
`oh99-mg24-sibling.png`, `oh118-rp2350-dip.png` (headers hanging),
`oh119-uno-parts.png` (47 parts), `oh122-uno-ink.png` (silkscreen).

---

## 5. Open work, highest priority first

### 5.1 OH-135: the compile recipes — *software-only, START HERE*

`webui/compile.py:220-224` names 11 Uno core sources; the installed
framework also ships `wiring_analog.c`, `WMath.cpp`, `WInterrupts.c`,
`Tone.cpp`, `wiring_shift.c`, `wiring_pulse.c/.S`. Measured by really
building: map/random/analogWrite/analogRead/tone/attachInterrupt/shiftOut/
pulseIn ALL "undefined reference"; blink OK. SAMD21 (`:275-282`) misses four
the same way. And there is NO libraries/ include root at all — `Wire.h`,
`SPI.h`, `EEPROM.h`, `Servo.h` are "No such file" on both boards
(`:465-466` builds includes from core+variant only).

Closing it makes OH-71's `unknown`-PWM answer REACHABLE from the IDE — that
ticket predicted exactly this. DONE WHEN the probed idioms build on both
boards and a test builds an analogWrite sketch through the API and watches
pin 3 report unknown. Toolchain is installed and on disk; the survey verified
every claim by building.

### 5.2 OH-130: the silent 125 mA short — *runtime-verified, tests written in the ticket*

D13(high)+GND on one LED terminal reports "off ... mid-air" while shorting
5 V/40 Ω past the absolute maximum. Three probed cases in the ticket; the
rail-vs-rail refusal text is the model. `webui/static/circuit.js`.

### 5.3 OH-137 toolbar desync, OH-131 removePart, OH-129 in-flight wire, OH-133 lifecycle bundle

Each small, each fully evidenced in its ticket with file:line.

### 5.4 OH-124: the pin-1 reader's four missing spellings

Widen `_mark_of`/`_body_of` (fp_poly, fp_arc, F.SilkS fallback); the C3/C6
PROCESSORS currently have no turn check of any kind. `MARK_OFFSET_FRACTION`
is the safety rail and already rejects the counter-examples.

### 5.5 OH-136 (lock), OH-138–142 (API/IDE bundles), OH-125 (tallies to extras), OH-126 (bench types)

As filed. OH-141's method-table fix is framed inside the loopback posture —
the posture itself is by design and stays.

### 5.6 OH-123: the two unread layouts — *a JUDGEMENT, decide before building*

MG24 + nRF54LM20A layouts sit on disk unread, but composing them REVERSES the
stated source-preference order (vendor mechanical first). Three options in
the ticket; record the decision either way.

### 5.7 OH-116: the two-terminal wire — costed, ten call sites listed

### 5.8 Carried: OH-8, OH-9, OH-11, OH-36 (LIVE-HELD), OH-38, OH-64, OH-127 (record)

### 5.9 **FOR THE USER**: 14 feature-ledger cells marked DONE cite
`tests/webui/test_live_oracle.py`, which skips unless `OPENHARDWARE_LIVE=1` —
their evidence does not execute on ordinary runs, and whether a real live run
earned those marks is recorded nowhere the survey could find. Ledger defect or
missing provenance note; only the user knows.

---

## 6. Commits this session

23 commits, `4c80cd2..ebac9f8` — the full list is `git log --oneline
a19a8e5..HEAD`; the scorecard in §1 maps each ticket to its commit.

---

## 7. Visual verification

**`oh119-uno-parts.png` / `oh122-uno-ink.png`** — the composed Uno: navy board,
routing tracery, DIP-28, both electrolytics, barrel jack, USB-B, QFN-32,
MSOP-8, four LEDs, arrays, diodes, ferrites, gold header pins, and (second
frame) white silkscreen outlines by the headers and ICSP. Most package
outlines sit under their parts — correct; the loud text ("ARDUINO") is
honestly unread (needs a font, OH-125/OH-122 notes).

**`oh118-rp2350-dip.png`** — the XIAO RP2350 DIP: black shrouds UNDER the
board, long breadboard legs down, tails proud on top, castellations, QFN-60,
USB-C. The product photo.

---

## 8. Known limitations and traps

### 8.1 THE SERVER ON 8088 IS SERVING STALE PYTHON — restart it

The user's server predates `webui/pinmap.py`/`webui/api.py` gaining
`px_per_mm` (OH-121). Until restarted, `/api/board/pins` omits the field and
the page falls back to the two-field fit — the SMD boards render 9% small
there and their outermost pads miss. Static files (`board3d.js`, `.glb`) ARE
current (re-read per request, `Cache-Control: no-store`); only the Python is
stale. The session verified OH-121 on a throwaway instance on port 8091,
since killed. **First action on any page complaint: restart the server.**

### 8.2 The `-k` expression trap: `pytest -k "a or b or c"` with a bare
keyword containing a space dies; quote each term.

### 8.3 `state_clear` without an explicit `session_id` reports success while
deleting nothing — the OMC ralph state needed
`session_id=d4fefe50-4831-4eaf-950d-b7fd61649b25` spelled out, then a manual
`rm` for the two files it still missed.

### 8.4 Survey agents: Explore-type subagents are READ-ONLY (no Edit/Write) —
right for surveys, wrong for delegated fixes. All three delivered; their
reports are quoted into the tickets they seeded, so nothing depends on their
transcripts.

### 8.5 Residuals unchanged from the morning handoff: X4122 shader warning,
`#6f6651` unidentified, `PYI034`, `core.avr.abi.Cpu` close segfault. The
"one console 400 on a cold page" line is now OH-142's first bullet (cause
found: `fillBoardPicker` fetches `/api/board/pins` with no `?board=`) — do
not re-diagnose it, fix it there.

### 8.6 `tools/tickets.py` still derives session id from parent pid — set
`OH_SESSION_ID` explicitly on every ticket command. `set` takes `--touch`.
