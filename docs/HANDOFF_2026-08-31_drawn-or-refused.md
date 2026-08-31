# Handoff — drawn or refused: 220 silent placements to zero, and three reviewers who all said no

    date          2026-08-31, ~21:30 (fourth handoff of this working day; the
                  prior three are HANDOFF_2026-08-30_the-board-not-the-parts.md,
                  _every-pad-finds-its-pin.md, and
                  HANDOFF_2026-08-31_the-queue-runs-dry.md)
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean of this session's work
    HEAD          4d2ace5  fix(tools): the WLCSP claims my own correction commit got wrong
    session span  6dd37dd..4d2ace5 (12 commits mine; 0e517b7/b3bac7a/c7eaf83
                  interleaved are ANOTHER LIVE SESSION's OH-149 — never touch)
    gate          2,004 passed / 17 skipped -- BUT SEE §9.1: not reliably
                  reproducible on this box, flaky under load
    checkers      `python tools/checkall.py` -> "all 12 checks pass" (the new
                  unified runner from the concurrent session's OH-149)
    compose       `python tools/compose_board_3d.py --check` exits 0, 11 boards,
                  ZERO "no model" lines
    models        21 modelled specs, 21 meshes; all 11 composed boards
                  regenerated and carrying the new parts (verified by reading
                  each .glb's own extras)
    server        127.0.0.1:8088 running current code, detached
    ralph         CANCELLED (state files verified gone by `ls`, see §9.4)

**Three independent reviewers returned REJECTED, and all three were right.**
Two rounds of corrections landed (11fb670, 4d2ace5). **Three findings remain
OPEN, one of them a real functional defect (§6.1).**

---

## 1. Scorecard

| Goal | Status | Evidence |
|---|---|---|
| Every unaccounted placement drawn or refused | ACHIEVED | `--check` exit 0, 11 boards, 0 "no model" lines; 220 → 0 |
| 7 dims-in-name slabs modelled | ACHIEVED | `model_from_datasheet.py --check`, each agreeing 0.000–0.260 mm to F.Fab |
| CAF diplexer decided | ACHIEVED | drawn; height from Description via new fallback (b9d6bd8) |
| 3 chip diodes drawn | ACHIEVED | ESD-0201/0402 → Resistor_SMD borrow; DFN1006-2L → D_SOD-882 |
| 10 no-body packages refused with reasons | ACHIEVED | `--check` "absent" lines carry designators + reason |
| A sketch builds for the C3 AND RUNS | ACHIEVED | 174-byte image, GPIO10 first high step 31, ~24,000-step delay period (OH-148) |
| `.data`/`.bss` contract locked by test | ACHIEVED | `tests/webui/test_compile.py::test_a_sketch_s_globals_survive_the_linker_script_having_no_crt0`, mutation-proved |
| C++ global constructors run | **BLOCKED — NOT DONE** | measured 2026-08-31: ctor silently skipped, §6.1 |
| Independent review passed | **BLOCKED — 3 findings open** | §6.1–6.3 |
| Full gate reliably green | **BLOCKED ON FLAKINESS** | §9.1 — 3 runs, 1 failure each, different test |

---

## 2. Root-cause narratives

### 2.1 The lesson of the whole session: I verified with a regex that could not match

**Symptom.** Commit `f63cb37` — whose entire stated purpose was replacing
unverifiable claims with checked ones — introduced a NEW false claim: that
`Package_CSP` holds no WLCSP under twenty balls.

**How it happened.** I checked with:

```python
[n for n in files if re.search(r"WLCSP-[46]\b", n)]     # returned []
```

The filename is `WLCSP-6_1.46x1.1mm_Layout3x2_P0.4mm.step`. `\b` needs a
non-word character after the digit; `_` IS a word character; no boundary; no
match. I read the empty result as evidence of absence and wrote a confident
sentence on it.

**Ground truth** (raw listing, no pattern):

```
Package_CSP: 34 entries, 15 WLCSP files, three under twenty balls:
  WLCSP-6_1.46x1.1mm_Layout3x2_P0.4mm.step
  WLCSP-9_1.21x1.22mm_Layout3x3_P0.4mm.step
  ST_WLCSP-19_1.643x2.492mm_Layout4x11_P0.35mm_Stagger.step
```

**Fix**: `4d2ace5`. The three rows now name the near-miss they refuse and on
what ground — area (WLCSP4), 0.54 mm over the tolerance (WLCSP-0.92), and
**pitch, because the size is INSIDE the tolerance** (BGA6-0.85, 0.4 vs 0.35 mm,
the QFN-56's own argument).

**Generalization.** This repository already holds the rule —
*make the check fail on purpose; a clean result from a new check is as suspect
as an alarming one.* I applied it to a linker-script test the same hour and
failed to apply it to my own verification tooling. **When a check returns
"nothing found", prove it can find something before believing it.** Listing
beats matching: `sorted(n for n in files if "WLCSP" in n)` would not have lied.

### 2.2 `float("2_1")` is 21.0

Seeed spell the SOT8's body `2_1x1_2x0_6mm`. Python reads `_` as a digit
separator, so a naive `float()` turns a 2.1 mm body into a 21 mm one — which
would clear the regex and be caught only by the F.Fab cross-check.
`_named_float` (tools/model_from_datasheet.py) normalises `_` and `d` to `.`
**before** converting. It raises on two separators rather than guessing;
`_NAMED_NUMBER` admits at most one, so that raise is unreachable today, and
`f1f8de6` records which change would reach it.

### 2.3 The composer aborted four boards in while a grep said success

`modelled` is a separate boolean field on `Component`, **not** inferred from
`library="modelled"`. Omitting it made the composer try to fetch
`modelled.3dshapes/DFN6-0.4-....step` from KiCad's GitLab and 404, aborting the
run — while `grep -c "no model"` on the truncated output returned 1 and looked
like progress. **Verify a run COMPLETED (exit code, board count), never just
grep its output.**

### 2.4 A test that passed for the wrong reason

The new `.data`/`.bss` test passed, then survived two mutations that should
have killed it. Cause: at `-Os` gcc folded the initialised global to a constant
and kept the counter in a register across the inlined loop — **it was testing
the optimiser, not the linker script.** Both globals are now `volatile`;
pointing `dram` at an unmapped address does fail it. The two mutations that
still survive are documented in the test's own docstring as facts about ld:
deleting `*(.data .data.*)` changes nothing (orphan placement), and moving
`.bss` into flash changes nothing (NOLOAD emits no bytes). **The region is
load-bearing; the section lines are documentation of intent.**

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. The headline claim, in one command.
python tools/compose_board_3d.py --check          # exit 0, 11 boards, NO "no model" line

# 2. Everything, through the new unified runner (OH-149, other session).
python tools/checkall.py                          # -> "all 12 checks pass"
                                                  # NB flaky, see §9.1

# 3. Fresh checkout only: rebuild the meshes (needs Blender + cadquery-ocp).
python tools/model_from_datasheet.py              # 21 parts
python tools/import_3d_model.py --all
python tools/import_3d_model.py --parts
python tools/compose_board_3d.py                  # 11 boards

# 4. The C3 build path, end to end (OH-148).
python -c "import sys;sys.path.insert(0,'.');from webui import compile as c;\
b=c.build('XIAO-ESP32-C3-DIP','void setup(){pinMode(D10,OUTPUT);}void loop(){digitalWrite(D10,HIGH);delay(1);digitalWrite(D10,LOW);delay(1);}');\
print(b.ok,len(b.image))"                          # -> True 174

# 5. The server, detached so task reaping cannot kill it.
powershell -NoProfile -Command "Start-Process -FilePath 'C:\Users\Alexyodude\miniconda3\python.exe' -ArgumentList 'webui/emulator_server.py' -WorkingDirectory 'C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware' -WindowStyle Hidden"
```

---

## 4. File inventory

| File | What changed |
|---|---|
| `tools/compose_board_3d.py` | +10 ABSENT entries, +11 Component rows (7 modelled slabs, CAF, 3 diodes); `modelled=True` is a separate field |
| `tools/model_from_datasheet.py` | +8 SLABS rows; `_NAMED_BODY` widened (`_`/`d` decimals, IGNORECASE, optional unit); `_named_float`; `slab_geometry` Description-height fallback; `_MOULDED_IC`/`_BARE_DIE` constants |
| `webui/arduino/` **(new tree)** | the in-repo Arduino core: `cores/openhardware/{Arduino.h,main.c,wiring.c}`, `variants/xiao_esp32c3/{oh_board.h,link.ld}` |
| `webui/compile.py` | `ARDUINO_LITE` root, `framework_root` openhardware branch, ESP32-C3 recipe with 7 `hints` rows |
| `tests/webui/test_compile.py` | C3 block: build/run/delay-scaling/hints/header-drift + the mutation-proved globals test |
| `tests/webui/test_editor.py` | no-recipe example board moved C3 → RP2040 |
| `docs/tickets/OH-148*`, `OH-150*` | new; `OH-104*` annotated as superseded |
| `.omc/research/unmodelled/*.md` | **16 scout findings** — the evidence base, uncommitted, session-local |

---

## 5. Reviewer verdicts (all three: REJECTED)

Reachable by name via `SendMessage` if still alive: `architect-oh150`,
`critic-oh150`, `reviewer-oh150`. **All three initially went idle WITHOUT
delivering their reports; messaging them by name resumed them from transcript
and produced full reviews.** If a reviewer goes quiet, ask it directly before
concluding it died.

Fixed already (11fb670, 4d2ace5): the 191→220 count; "height exists only in
that same name" (false — the C5 places the same chip under the sound name);
"the sibling states three" (false — sibling's Description states none); the
button Description attributed to the C3 (it is the nRF54L15's); three WLCSP
claims; SOT eight-lead count 6→8; two rows each claiming to be strictly the
tightest when six tie at 0.000; F.Fab vs silk-fallback conflation; the CAF's
colour claiming a ceramic FINISHES entry that does not exist.

---

## 6. OPEN WORK — highest priority first

### 6.1 C++ global constructors silently do not run — *software-only, START HERE*

**The only silent failure in the openhardware core.** `webui/compile.py:684`
compiles the sketch as `sketch.cpp` through `g++`, but
`webui/arduino/variants/xiao_esp32c3/link.ld` never places `.init_array`, and
`cores/openhardware/main.c`'s `oh_run` calls `setup()` with no
`__libc_init_array` equivalent.

**Measured this session, not inferred:**

```python
struct Marker { int v; Marker() { v = 5; } };
Marker m;                       # global with a non-trivial constructor
# ... if (m.v == 5) digitalWrite(D10, HIGH);
# -> builds fine (188 bytes), pin rises 0 times. The constructor never ran.
```

Every other absence in this core fails at compile time with a `Recipe.hints`
row explaining it. This one compiles and lies. Fix: place `.init_array`/
`.fini_array` in `link.ld` and walk them in `oh_run` before `setup()`, then add
a test in the shape of the globals test. Reviewer also flags an untested tail
risk: `.init_array` is currently an orphan section, and if ld ever placed it
after `.bss` in `dram` the flat image would span the ~37 MB inter-region gap.

### 6.2 The height (group 3) is never cross-checked — *software-only*

`tools/model_from_datasheet.py:305-317` says the F.Fab tolerance "is what makes
widening it safe". It compares groups 1 and 2 only; **the height is compared to
nothing.** A name shaped `LxWx<not-a-thickness>` — correct plan, third field a
pitch or a count — now passes silently with a wrong height, and making `MM`
optional is what opened it (previously such a name did not match and raised).
**Not live**: all 16 current names parse correctly. Either narrow the comment
to what it actually guarantees, or gate the optional unit.

### 6.3 The button's ABSENT rationale is now false on two of three boards — *software-only*

`tools/compose_board_3d.py:800-801` says the vendor states no height "on any
layer"; the C5's and nRF54L15's copies of `BUTTON_TD1183SA` both carry
`SMD Top Button 160gf;2P-L3.0*W2.5*H1.5mm`. The **C3's** BOOT0/RST0 have empty
Descriptions, so the refusal stays true there and only there. OH-150 itself
abolished the "a property is not a layer" defence when it taught
`slab_geometry` to read the CAF's height from a Description.
`tests/rules/test_compose_board_3d.py:659` asserts the button "has an F.Fab
outline and no height anywhere" — now false, passing only because
`_STATED_ENVELOPE` cannot parse letters between the numbers. **A load-bearing
test whose stated rationale is false.** Fix the test and the entry together.

### 6.4 Smaller, from the same reviews — *software-only*

* `model_from_datasheet.py:1073` reports "its name says {…}" on BOTH height
  paths, so a Description-sourced mismatch names the wrong source.
  `socket_geometry:866` gets this right.
* DFN1006-2L's "sharing footprint UUIDs, so one drawing rather than five" holds
  for 4 of 5; the nRF54L15's D4 is a different UUID (F.Fab 1.321 × 0.711 vs
  0.749 × 0.508). `confirm` passes; the sentence overstates.
* `_BARE_DIE` says "as the WLCSP-47 and WLCSP-20 **above**" — the new block was
  inserted at the top, so those rows are now below (556 vs 396).
* "the only name in this file that states no unit at all" (DFN6-0.5) — the CAF
  has none either. "the first name here to spell its unit in lower case"
  (X2SON4) — the SOT8 precedes it.
* FINISHES has **no ceramic entry**; the CAF and the pre-existing ANT2P row
  both borrow `#c6c4a0`, documented there as a switch's metal cover at
  metalness 1.0. One ceramic entry retires both. Ceramic parts currently render
  as polished metal.

### 6.5 Carried, unchanged
14 feature-ledger cells cite `tests/webui/test_live_oracle.py` (skips without
`OPENHARDWARE_LIVE=1`) — provenance question only the user can answer.
Blocked set: OH-8, OH-9, OH-11, **OH-36 (LIVE-HELD by `agent-oh36` — never
take it)**, OH-38, OH-64.

---

## 7. Commits this session

```
4d2ace5 fix(tools): the WLCSP claims my own correction commit got wrong
11fb670 fix(tools): four claims an architect review found false (OH-150)
b343e25 test(webui): the linker script's contract, locked and mutation-proved
f1f8de6 docs(tools): _named_float says which change would make its raise reachable
d1f5a77 refactor(webui): the entry point stops going through a wrapper
9b02f39 docs(tools): the refused BGA6 says why the new fallback cannot save it
4db662e docs: OH-150 records the five claims it had to correct
f63cb37 fix(tools): five library claims the new rows could not back
71b2746 docs: OH-104's deferral is superseded, and says so where it is read
0ea2f5c refactor(tools): two colour readings the new slabs shared, named once
b9d6bd8 feat(tools): every composed placement is drawn or refused with a reason (OH-150)
6dd37dd feat(webui): a sketch builds for the C3 and runs on the board (OH-148)
```

`0e517b7`, `b3bac7a`, `c7eaf83` interleave and belong to **another live
session** (OH-149: `tools/checkall.py`, `check_facts.py`, `stale.py`,
`DUPLICATION.md`, and the CLAUDE.md edit documenting the runner). Leave alone.

---

## 8. Visual verification

* `scratchpad/shots/c5_full.png`, `c5_zoom.png` — XIAO-ESP32-C5-DIP. Crystal,
  USB-C, U.FL connector and QFN all correct; the newly drawn small silicon
  (WLCSPs, BGA6, SOT8, CAF) sits flush on its own pads at believable sizes.
  Castellated edge intact, DIP headers hanging below.
* `scratchpad/shots/c6_full.png`, `c6_zoom.png` — XIAO-ESP32-C6-DIP, the
  biggest gainer (56 → 69 drawn). One bare white silk outline is visible
  bottom-centre: that is a still-refused part showing its footprint rather than
  an invented body — the intended failure mode.
* Session-local (`%TEMP%\claude\...\scratchpad\shots\`), not committed.

Drawn counts before → after: Uno 47→47 (control, no gaps); C3-DIP 56→56 (its
only gap was H7, now refused); C6-DIP 56→69; RP2350-DIP 57→66; C5-DIP 76→86;
nRF54l15-DIP 69→78.

---

## 9. Traps and limitations

### 9.1 "Full gate green" is NOT currently demonstrable on this box
Three consecutive full runs each gave 2,003 passed / **1 failed**, with a
*different* test failing each time, and each failing test passing in isolation:
`test_a_failed_build_leaves_nothing_behind` (globs the SYSTEM-WIDE temp dir, so
any process's leftover `openhardware-build-*` fails it) and
`test_an_upload_from_another_origin_is_refused` (10-second socket timeout under
load). Nothing actually leaks. **Do not cite the gate as unqualified evidence
until this is fixed**; prefer `tools/checkall.py` plus per-suite runs.

### 9.2 The heredoc trap, SIXTH occurrence
A quoted heredoc mangled `\n` inside a Python string literal again, producing
an unterminated-string SyntaxError in `compose_board_3d.py`. **Write the script
with the Write tool and run the file** for anything containing escapes or
apostrophes. Also: these files are CRLF, so LF-only anchors silently fail to
match — read bytes and split on the file's own newline.

### 9.3 The OMC state tool reports success while deleting nothing — CONFIRMED THRICE
`state_list_active` said "No modes are currently active" while
`.omc/state/sessions/<id>/ralph-state.json` sat on disk with `"active": true`.
Fallback: `rm` the files directly, write `cancel-signal-state.json`, then `ls`.

### 9.4 Ticket-ID collisions with the concurrent session
Both sessions filed an OH-149 within minutes. `check_ticket_claims` catches it.
Mine was renumbered to OH-150. **Check `docs/tickets/` for your number before
filing.**

### 9.5 Subagents that "die" may just be silent
All 16 research scouts returned normally. All three reviewers went idle with no
report; `SendMessage` to each by name resumed them and produced complete
reviews. A trivial health-check agent also returned. **Ask before concluding
dead.**

### 9.6 Residuals unchanged
X4122 shader warning; `#6f6651` unidentified; `PYI034`; `core.avr.abi.Cpu`
close segfault; the 0.5 mA LIT_AMPS sub-threshold wording edge; six pre-existing
`ruff` RUF100 findings in `tools/` (baseline, verified stash-vs-unstash).
