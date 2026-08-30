# Handoff — the queue runs dry: eighteen tickets, two approvals, one bench that finally wires

    date          2026-08-31, ~03:30 (third handoff of this working day; the
                  prior two are HANDOFF_2026-08-30_the-board-not-the-parts.md
                  and HANDOFF_2026-08-30_every-pad-finds-its-pin.md)
    repo          C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware
    branch        master, clean
    HEAD          07364ba  refactor(tests): the comment-strip idiom earns a name
    session base  a19a8e5  (31 commits across the whole day; THIS handoff covers
                  15b700f..07364ba, the evening-and-night run)
    gate          1,960 passed, 17 skipped  (a19a8e5 was 1,850; the morning left
                  it at 1,905)
    checkers      all eight exit 0
    ruff          zero NEW findings all night, verified stash-vs-unstash per
                  ticket; the baselines (tools/ 37 et al.) are pre-existing
    ticket held   none. OH-36 is held by live session `agent-oh36`; never take it
    ralph         CANCELLED CLEANLY — state files really deleted (see §8.1),
                  cancel signal written and self-expired
    server        127.0.0.1:8088 runs CURRENT code, restarted twice this session
                  and now DETACHED (PowerShell Start-Process, survives task
                  reaping). Started WITHOUT --artefacts, so the "Load that
                  build" row is hidden — deliberate default, not a defect.
    models        parts/ regenerated (now SIX parts — the 5 kΩ trimmer joined);
                  all ELEVEN composed boards regenerated with the OH-125 tallies
                  aboard AND the OH-124 C3 quarter-turn fix. All gitignored; a
                  fresh checkout runs runbook §3.

**The open ticket queue is EMPTY except the blocked set.** Thirteen PRD
stories ("complete all tasks", ralph run 2) all passed, verified by TWO
independent architect approvals, desloped, and regression-proven at the same
1,960 the run finished on. Eighteen tickets closed today in this session's
span; nineteen commits.

---

## 1. Scorecard

| Ticket | Commit | One line |
|---|---|---|
| OH-135 compile recipes | 15b700f | 8 dead idioms + 3 unfindable headers → all build; `Library` opt-in rows; TWI-vector test |
| OH-130 silent 125 mA | 6716424 | `pinSentence` said at bench level; the three probed topologies are tests |
| OH-129 mid-fetch wire | 30acffb | carvePins repoints wires holding the mesh it releases |
| OH-131 removePart hatch | 8ad649c | every part row has the remove control the destroyed latch depended on; OH-81 corrected |
| OH-137 toolbar desync | 9e09481 | `panes`/`showMachine`; refresh refuses while a board owns the panes |
| OH-133 lifecycle triple | 6ab188c | colour off id; drag dies in clearBench; releasePart per-part only |
| OH-138 Serial hint | 45fa536 | `Recipe.hints` appends the Serial1/USB-CDC note under gcc's own words |
| OH-124 pin-1 spellings | c88efe0 | five spellings read; **the C3's processor was a real quarter turn wrong** (§2.1) |
| OH-136 lock split | 963450c | build before the lock (15.79 s → ms, §2.2); whole-build budget enforced |
| OH-139 error paths | 7b63386 | rc-127 missing tool; `<build>`/`<toolchain>` scrub; query errors name fields; client status-first |
| OH-141 method table | b02d064 | ROUTE_METHODS; GET /api/reset = 405 with steps proven unchanged |
| OH-142 API cleanup | 3647c42 | cold-page 400 gone; /api/target+Selection removed; entry pages per server; artefact ceiling; DEFAULT_SKETCH compiles |
| OH-140 IDE affordances | 53d5c85 | /api/board/step + button; buildable greys Build; sketch survives reload; words= rides `boardStateUrl()` |
| OH-125 tallies ride | 0edc3c1 | `artwork` + `not_drawn` in extras on all 11 boards; panel captions from the composer's numbers |
| OH-123 unread layouts | f5c23db | JUDGEMENT: imported meshes stay; hybrid named as future ticket; nothing built |
| OH-126 the trimmer | a3bee12 | `Part.terminals` tuple-of-N; lead_tips clusters (x,z); pot end to end, four hand-worked node cases |
| OH-116 two-ended wires | 8fe680e | wires between parts; junction note narrows AND retires; 9.302 mA direct pair (§2.3) |
| deslop pass | 07364ba | 24 strip-idiom copies → `stripped()` helper; gate identical both sides |
| US-13 blocked review | (no commit) | all six blockers verified current; zero edits; recorded in .omc/progress.txt |

Verification per ticket, uniformly: targeted suite green → mutations ALL
killed (~60 this run; one first-run survivor got its test bench rebuilt, one
near-equivalent excluded with its reason recorded) → close note with measured
numbers → eight checkers → full gate green → one commit.

---

## 2. Root-cause narratives

### 2.1 The composed C3's processor sat a quarter turn wrong since OH-93

OH-124 widened `kicad._mark_of` (circles→polys→arcs, `.Fab` then `.SilkS`)
because the survey found four marker spellings the reader could not see —
and on its FIRST full pass the check REFUSED the C3: turn 0 put the model's
own asymmetric feature 4.621 mm from the vendor's dot while 90 put it 1.540.
Forensics settled it as a real defect, not a checker artefact: the C3 draws
its QFN32G with pad 1 on a DIFFERENT EDGE than the C6's one-letter sibling
(pad 1 local (-1.75, 2.45) vs (-2.45, -1.75) — axes swapped) and
compensates in the placement (-90 vs 0), so the C3's model pairing needed
`turn=90` where the C6's needs none. Invisible to every prior check because
a span, a centre and a silk box all survive a quarter turn on a square
package. `COMPOSITIONS` carries the turn with this evidence; the C3 glbs
are regenerated.

**A third case the margin rule had never met**, found the same hour: the
U.FL antennas' marks pass the offset floor but the connector's near-4-fold
mesh puts every turn within 0.006 mm of every other. OH-106's data always
decided by ≥1.6 mm, so "nobody wins" and "a rival won" were one conflated
condition; they are now split — rival-wins still refuses, nobody-wins
counts the part unseen. Generalization: a margin test on a symmetric field
degenerates, and the degenerate case belongs in the "cannot check" count,
not in either verdict.

### 2.2 The page froze for every second of every build

One lock wraps every route and /api/board/compile ran the WHOLE build
inside it — measured: a GET /api/state issued 0.7 s into a SAMD21 build
answered after 15.79 s. A build touches no session state until its image
loads, so `prepare_compile` now runs before `with self.lock` and the locked
handler consumes the prepared build (a source test pins the consumption —
rebuilding inside the lock is the freeze in disguise). The poll test
requires the build to be ALIVE when the poll lands; killing the prelude in
mutation testing re-froze it, which is the proof the test measures the
lock. Also: `TIMEOUT_SECONDS` was per-invocation (~24 invocations = the
better part of an hour) while its comment claimed it bounded the build;
`BUILD_BUDGET_SECONDS = 300` now actually does, via `_run` shrinking each
invocation's timeout, returncode 124 on the shared failure rail.

### 2.3 Two parts can be wired to each other now

OH-84 shipped a sentence because the wire was `{pad, part, terminal}`;
OH-116 gave the wire two ENDS (`from: {part, terminal}` present exactly
when `pad` is not) and taught every listed reader to walk both. The
junction note narrows (offers the direct drag AND the borrowed input) and
retires on any bench holding a part-to-part wire. The drag halves landed
together as the ticket demanded; the raycast half is pinned at the source,
comments stripped, its no-headless-harness absence stated. Watch for:
`padUnder() ?? terminalUnder()` ordering is load-bearing (pads win where
they overlap).

### 2.4 Test lessons this run paid for

  * **A mutation that survives is telling you which line is decorative.**
    OH-116's `wired` from-side add survived because every part in the test
    bench was also a landing end; the bench was rebuilt so the resistor is
    ONLY a from-end (11.575 mA, hand-worked). Kill by construction, not by
    coincidence.
  * **A shipped-artifact test that no mutation regenerates is a survivor
    class** (morning §2.6, confirmed again): OH-125's extras mutation is
    killed by the SOURCE pin on purpose.
  * **The float-noise boundary**: OH-130's strict `>` rides ~5e-11 at
    exactly 40 mA vs the 40 mA absolute maximum. Recorded, not changed —
    the comparison is `warn`'s own. No test pins that clause at the
    boundary.

---

## 3. Runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware

# 1. Gate.
python -m pytest -q                       # -> 1960 passed, 17 skipped, ~11-18 min
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims; do
  python tools/$c.py >/dev/null 2>&1; echo "$c exit $?"; done   # all 0

# 2. Fresh checkout only: regenerate the gitignored meshes.
python tools/model_from_datasheet.py
python tools/import_3d_model.py --all
python tools/import_3d_model.py --parts   # SIX parts now, the trimmer included
python tools/compose_board_3d.py          # 11 boards, extras carry the tallies

# 3. The server, DETACHED so background-task reaping cannot kill it:
powershell -NoProfile -Command "Start-Process -FilePath 'C:\Users\Alexyodude\miniconda3\python.exe' -ArgumentList 'webui/emulator_server.py' -WorkingDirectory 'C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware' -WindowStyle Hidden"
curl -s "http://127.0.0.1:8088/api/boards" | head -c 100   # alive check
```

---

## 4. File inventory (this handoff's span, code only)

tools/: compose_board_3d.py (QFN32G turn, margin third case, tallies,
unmodelled count), import_3d_model.py (Part N-terminals, clustered
lead_tips, POT_ELECTRICAL, trimmer row), kicad.py (widened _mark_of/_body_of).
webui/: compile.py (full core+libraries, hints, budget, scrub, rc-127),
emulator_server.py (prepare_compile, ROUTE_METHODS+verb guard, _query_int,
_board_state+step route, buildable, artefact ceiling, /api/target+Selection
removed, index.html refused), bridge.py (emulator.html refused).
webui/static/: board3d.js (wire from-ends, releasePart, colour-by-id,
carve repoint, drag-from-terminal), circuit.js (pot stamp, two-ended joins,
junction retire, pinSentence, POT_TRAVEL), board3d-panel.js (remove control,
cold-page guard, gap captions, from-chips), emulator.js (showMachine,
boardStateUrl, sketch persistence, buildability, status-first api()),
emulator.html (machine label, step button, watch box).
tests/: eleven files grew ~45 tests; test_board3d.py holds the new
`stripped()` helper.

---

## 5. Open work, highest priority first

### 5.1 Browser-verify the night's UI affordances — **DONE 2026-08-31, see §9**

Everything above is unit/node/source-verified; NOTHING drove a real browser
over the new UI. On http://127.0.0.1:8088/ (server already current), with
playwright or by hand, walk:
  1. Drag a wire from one part's terminal to another's (OH-116) — pick two
     parts, wire them, confirm the chip reads "anode ↔ … lead A" and the
     junction note is absent.
  2. Add the 5 kΩ trimmer from the parts menu (OH-126) — three targets,
     wire wiper+ends, currents match the hand-worked numbers in
     tests/webui/test_circuit.py.
  3. The board Step button and the watch box (OH-140) — load any runnable
     board image, step once, type an address into watch and see the word.
  4. The remove control (OH-131) and the machine label (OH-137).
  5. The C3 DIP/SMD models (OH-124): the QFN's pin-1 corner should now
     agree between the DIP silk dot and the model's dimple.
The drag half of OH-116 explicitly has no headless coverage — this manual
pass is the verification the close notes defer to.

### 5.2 FOR THE USER (carried, unchanged)
  * 14 feature-ledger cells cite tests/webui/test_live_oracle.py, which
    skips without OPENHARDWARE_LIVE=1 — provenance question only the user
    can answer (morning handoff §5.9).

### 5.3 Follow-ups NOTED IN CLOSE NOTES but deliberately NOT filed
File them (or don't) as their own decisions; none is started work:
  * a knob for POT_TRAVEL (page UI; circuit.js already solves any position)
  * folding the SAMD21's eight nosys.specs link warnings (renderer polish)
  * a Ctrl-Enter build shortcut (tangled with OH-134's keydown guard)
  * imported-geometry-with-composed-artwork hybrid (OH-123's middle path)

### 5.4 Blocked, carried, all verified current 2026-08-31
OH-8, OH-9, OH-11, OH-36 (**LIVE-HELD by agent-oh36 — never take it**),
OH-38, OH-64; OH-127 stays a record. Each names its blocker and unblock
condition in its own file; OH-64's note pre-empts the checker's "likely a
typo" heuristic — do NOT "fix" its deliberate future-file claim.

---

## 6. Commits this session's span

Nineteen: 15b700f, 6716424, 30acffb, 8ad649c, 9e09481, 6ab188c, 45fa536,
c88efe0, 963450c, 7b63386, b02d064, 3647c42, 53d5c85, 0edc3c1, f5c23db,
a3bee12, 8fe680e, 07364ba, plus the morning-session's 7f972f6 handoff at
the base. `git log --oneline a19a8e5..HEAD` is the full day.

---

## 7. Visual verification

None this span — the run was solver/API/reader work verified by node,
unit tests and measured HTTP, which is exactly why §5.1 is the top item.
The C3 regeneration's only screenshot-worthy change (the QFN quarter turn)
awaits that pass.

---

## 8. Known limitations and traps

### 8.1 `state_clear` reports success while deleting nothing — CONFIRMED TWICE
The OMC state tool cleared a HOME-side tree while the live files sat in the
REPO's `.omc/state/sessions/<session-id>/`. Three "Successfully cleared"
replies; both files still on disk. The fallback that works: `rm` the files
directly and write `cancel-signal-state.json` beside them. §8.3 of the
morning handoff described the same; treat the tool's success line as
UNVERIFIED until `ls` says otherwise.

### 8.2 The heredoc trap is not about quoting — it hit a QUOTED heredoc
`<<'EOF'` still turned `\\n` into a literal newline inside a Python string
on this box (fourth-plus occurrence, ~03:00). The Write-tool-then-run
pattern is the only safe path for any script containing backslash escapes
or apostrophes. sed/python one-liners via heredoc are fine only when pure
ASCII with no escapes.

### 8.3 Stop-hook iterations are SECONDS apart — do not read them as minutes
Waiting on a subagent across ralph iterations, the iteration counter climbed
~10 while the wall clock moved ~3 minutes; "it must be dead" was clock
illusion. Check `date` before declaring an agent lost. Related: a subagent
that dies to a session limit MAY send an idle/failed notification (attempt 1
did) or may not; transcript mtime under
`~/.claude/projects/C--Users-Alexyodude/` is the ground truth.

### 8.4 Waiting on background gates: write to a log file, tail the file
`pytest -q | tail` buffers everything until exit; `pytest -q > log 2>&1`
then `tail log` gives live progress AND lets an `until grep -qE
"passed|failed|error" log; do sleep 15; done` waiter work. Foreground
`sleep` chains are blocked; a single until-loop is sanctioned.

### 8.5 Residuals unchanged: X4122 shader warning, `#6f6651` unidentified,
`PYI034`, `core.avr.abi.Cpu` close segfault, the 0.5 mA LIT_AMPS sub-threshold
wording edge (a genuinely conducting 0.45 mA part reads "no current: both
its leads are at the same voltage" — false sentence, latent, noted in
OH-126's window).

### 8.6 `tools/tickets.py`: set OH_SESSION_ID explicitly on every command;
`set --touch` takes ONE path per invocation (repeats silently keep only the
last when passed in one call).

---

## 9. Addendum, 2026-08-31 morning: §5.1 executed — all five items green

A playwright pass (headless chromium, REAL pointer events through the
canvas's own raycast path, positions from `board3d.js`'s exported
`describe()`/`toScreen()` harness) ran all of §5.1: **38/38 checks passed.**

  1. **OH-116 direct wire**: dragging pad 13 → LED anode, LED cathode →
     resistor lead A (terminal-to-terminal), GND → lead B all landed; the
     panel chip reads `lead A ↔ 5 mm LED's cathode`; the junction note is
     absent ("Every part is wired…"); and with the sketch below running,
     both parts read **9.302 mA, "at least 9.3 mA through it"** —
     2.8/301 to ten digits, matching `test_circuit`'s hand-worked case.
  2. **OH-126 trimmer**: added from the menu with three terminals offered;
     5V→lead A + GND→lead B reads **0.909 mA** (5/5500); unwiring lead B by
     its chip's × and grounding the wiper instead reads **1.818 mA**
     (5/2750). Both reasons word-for-word the tests' sentences.
  3. **OH-140 Step + watch**: a sketch built through the page (2180 bytes,
     real avr-gcc), Step advanced the pc 01F9→01FA on the stopped clock;
     the watch box `0x0000,0x0002` showed its words after load and on run
     ticks.
  4. **OH-131/137**: the remove control took the LED off with BOTH its
     wires (including the from-end one); `#machine` read `i8086` cold and
     `Arduino Uno` after the load.
  5. **OH-124 C3 QFN**: the composed DIP board's QFN renders its pin-1
     dimple at one definite corner. The vendor's silk DOT itself is in the
     deliberately-not-drawn set (silk circles are counted, not drawn), so
     the visible-agreement half of this item overstated what a render can
     show: the agreement's enforcer is the mark rule's own measurement
     (turn 0 = 4.621 mm from the vendor's dot, turn 90 = 1.540 — the
     `QFN32G` row in `COMPOSITIONS`), re-run green this morning
     (15 mark/turn tests).

Corrections and observations out of the pass:

  * **The header's "server runs CURRENT code" was FALSE at resume.** The
    detached process had started 8/30 21:22 — before the night's API
    commits — so `/api/boards` had no `buildable` and the step route was
    missing. Killed and restarted 2026-08-31 ~04:3x; verified `buildable`
    rides the entries. Trap for §8: a detached server survives task
    reaping *and code changes equally well* — after a night of server
    commits, curl for a field the night added before trusting it.
  * **A Step blanks the watch note**: the page posts `/api/board/step`
    without `words=`, so the note fills on load/run fetches (which ride
    `boardStateUrl()`) and clears on a step. Candidate follow-up beside
    OH-140; deliberately not filed (§5.3 discipline).
  * **The default blink is ~24 s per half-phase on the wall**: the sim ran
    at ~337k instr/s against the real 16 MHz, so `delay(500)` is 8M
    instructions. The pass drove D13 with a constant-HIGH sketch instead;
    anyone re-verifying by hand should expect the blink to be *slow*, not
    broken.
  * Verification script, log and screenshots are session-local
    (`scratchpad/verify_ui.py` and `shots/` of session d4fefe50); the
    numbers above are the durable record.
