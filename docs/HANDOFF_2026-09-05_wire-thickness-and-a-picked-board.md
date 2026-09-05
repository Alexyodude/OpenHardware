# Handoff 2026-09-05 — a lead gets a thickness, two leads stop overlapping, and a picked board stops lying

| | |
|---|---|
| Date | 2026-09-05, continuing the session that wrote `docs/HANDOFF_2026-09-04_pins-and-a-printing-sketch.md` |
| Repository | `C:\Users\Alexyodude\Desktop\AlexFolder\Code\Github\OpenHardware`, branch `master`, HEAD **`0620214`**, 318 ahead of `origin/master`, **tree clean** |
| Session id | `d4fefe50-4831-4eaf-950d-b7fd61649b25` (`OH_SESSION_ID` for `tools/tickets.py`); **holds no ticket**, pointer unset |
| Ralph | **CANCELLED.** All six PRD stories done. `ralph-state.json` deleted from `.omc/state/sessions/d4fefe50-…/`; `prd.json` left in place |
| Tests | 2,105 passed, 17 skipped across the seven suites. All 12 gate checks pass — **run individually, see §9.1** |
| Toolchains | unchanged: GCC 8.4.0 (esp-2021r2) for RV32, MSVC for the cores, node for `wires.js`, Blender 4.5/5.1, **no QEMU** |
| Other sessions | `agent-oh36` still holds **OH-36**. Never take or edit it. |
| Build quirk | `build/lib/riscv32.dll.locked-by-pid44724` (151,552 bytes) still aside; the live `riscv32.dll` is 198,144 bytes. See the previous handoff's §9.1 |

## 1. TL;DR scorecard

| Goal | Status | Evidence |
|---|---|---|
| OH-162 step 1: a lead has a thickness in the solver | ACHIEVED | `464a3da`; `proud` 0.16 → 0; reviewer APPROVE after a blocker and 12 findings |
| OH-162 step 2: two leads stop occupying the same space | ACHIEVED | `00c35d8`; crossed pair 0.2243 → 0.4086 against a wanted 0.32; reviewer APPROVE after a blocker and 11 findings |
| OH-164: a picked board stops saying its pins are in use | ACHIEVED, ticket `done` | `0620214`; 0 of 26 boards now claim it; reviewer APPROVE after a blocker and 7 findings |
| OH-162 released its claim on `tests/webui/test_board3d.py` | ACHIEVED | `0deea1c`; needed because no two open tickets may claim one file |
| OH-162 step 3: plastic set | NOT STARTED | deliberate; the ticket's own step 3 |
| OH-162 step 4: the photograph oracle | BLOCKED ON a photograph of a real lead | needs a phone and a real XIAO; §6 |
| OH-161 steps 2-5 (timer, GPIO_IN, ADC, I2C) | NOT STARTED | unchanged from the previous handoff; ticket still `open` |
| OH-163, OH-157, OH-36, OH-38, OH-64, OH-9, OH-8, OH-11, OH-159 | BLOCKED or NOT STARTED | unchanged from the previous handoff |

**Three architect reviews, three APPROVEs, and every one of them found a
BLOCKER in my own work first.** That is the headline of this session and §3 is
mostly about it.

## 2. What is open, top first

1. **OH-162 step 3 — plastic set, if it earns its place.** `software-only`.
   Cold start:
   ```bash
   cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
   export OH_SESSION_ID=d4fefe50-4831-4eaf-950d-b7fd61649b25
   python tools/tickets.py start OH-162
   ```
   The ticket's own words: "record the rest angle at each node when a wire
   stops moving and relax toward it, so a bent lead stays bent. Judgement,
   labelled; the test is that a lead dragged into an arc does not return to a
   catenary." Everything it needs is in `webui/static/wires.js` and
   `tests/webui/test_wires.py`, both of which OH-162 still claims. **It does
   NOT claim `tests/webui/test_board3d.py` any more** — see `0deea1c`.

   Read §3.2 before writing the relaxation. The step-2 blocker was exactly a
   correction that resolved itself fully in one pass, and a plastic-set term
   is the same shape.

2. **OH-161 steps 2-5**, in the ticket's own order: the systimer (`map_counter`
   is the behaviour `core/riscv32` still lacks), then GPIO_IN against the
   solved node voltage, then the ADC, then one I2C part. `software-only`.

3. **OH-163 step 1** still needs a stroke-font licence decision before any
   glyph is drawn. `requires a decision`, not code.

4. **OH-162 step 4 — the photograph.** `requires hardware`: one photograph of
   one lead of known length on one board, and the sag it shows against the sag
   this model gives for the same span. That single number is what would retire
   `GRAVITY`, `DAMPING` and `SLACK` as judgements. It costs a phone.

5. Everything else is unchanged from the previous handoff's §2.

## 3. Root-cause narratives

### 3.1 OH-162 step 1 — growing every solid, one at a time

Symptom, found by the reviewer and reproduced by me before fixing: a wire
pinned to two pads over a board slab with one chip on it reported
`contact().inside` = 0.16, where zero is the pass and the file itself calls
this number the fault.

**Ruled out: a mistake in the growth arithmetic.** Every fixture with ONE
solid was correct — `proud` 0, `inside` 0, resting centres exactly a radius
above the face. The arithmetic was right; the composition was not.

Root cause: growth is per solid and resolution is sequential. A chip sits
flush on a board, so the chip's grown bottom face is one radius BELOW the
slab's top. A node ejected onto the chip's grown face lands inside the slab's
real box, and with the slab already resolved, nothing pushes it out again.

Fix: a radius is a preference and being outside a solid is a requirement.
`collide` resolves the grown solids, then resolves the UNGROWN ones for any
node the first pass pushed — which is character for character the guarantee
the file had before OH-162.

**And the guard on that second pass had a fixed point**, which the same review
caught. Skipping when the node had not MOVED is not the same as skipping when
nothing PUSHED: two solids 0.05 apart push a node out and straight back within
one pass, so its coordinates come out identical while both pushes really
happened, and it stays 0.11 inside the first box for ever. `outOfSolids`
returns whether a push executed and `collide` gates on that.

Generalisation: **when a correction is applied per object and objects touch,
the last one wins and the others are undone.** Ask what the invariant is,
enforce it separately from the preference, and never gate on a net effect when
what you mean is that something happened.

### 3.2 OH-162 step 2 — a divisor that goes to zero at a pinned end

Symptom, found by the reviewer: two wires pinned close together sent a
coordinate to 6.4e17 in 600 frames. Reachable through the interface —
`onPointerUp` refuses only a wire's own starting post, so two wires may land
on the same terminal.

Root cause: the pass shared each correction between a segment's two ends and
then divided by how far the contact point itself travels, so one pass resolved
the whole overlap. On a head segment that divisor is `s²`, because the pinned
end takes no share — so a contact near the pinned end moved the free end by
`push / s`.

**Ruled out: a floor under the divisor**, which is the obvious fix and which
the reviewer proposed. Measured: declining below 1e-6 still let two wires
pinned 0.1 apart reach 220, and 0.005 apart reach 303. The bad band is between
the floor and about 0.01, not at the degenerate end.

Fix: the division went. A pass under-corrects and the overlap comes out over
the following steps, which cannot diverge because nothing is divided.
Re-measured on the committed tree just now:

```
two wires pinned 0 apart, worst coordinate: 8.229
                    0.15 apart:             8.237
```

8.2 is where the wire actually is — its own length.

**That fix then falsified two things I had already written down as findings.**
A crowded bench settles after all; the residual I had documented as a property
of a pile was the over-correction. And the fixture proving the extra solids
pass was needed stopped proving anything, because corrections got smaller —
six leads crossing now give 0 either way, and what shows it is a lead pinned
LOW across a resting one, at 0.0853 inside the board without the line.

Generalisation: **an exact projection is right only where the Jacobian is well
conditioned.** Near a pinned end the constraint direction is nearly orthogonal
to the only free direction there is, and a formula that is already wrong above
a threshold cannot be rescued by picking the threshold. Under-correct and
iterate.

### 3.3 OH-164 — a third case the page could not see

Symptom, from the ticket: a board you have picked but not loaded says its pins
are "in use elsewhere". Measured over `catalogue.board_names()`, 12 of 26
boards; the Arduino Uno said 22 of its 32 pads.

**Ruled out: inferring it in the page from `unknown === pads.length`.** That
is equally true of a loaded sketch that has driven nothing, and re-deriving
what a file could state is what OH-121 paid for once already.

Root cause: `unknownWords` decided between two sentences on `chip_pin` alone,
and both are claims about a RUNNING program. A picked board satisfies neither
and took the second.

Fix: `pad_view` states `read_levels` beside `unknown`, true exactly when it was
given levels to read. `unknownWords` takes it as a third case, with the order
mattering — a pin no module models keeps "not modelled" whether or not a
program runs. Re-measured on the committed tree just now:

```
picked Uno read_levels: False | modelled pads: 22 of 32
picked boards claiming levels were read: 0
```

**Two sub-defects the review found in my own fix.** A first version had the
state poll mark the layout as having levels — but `/api/board/state` carries no
board identity and the picker does not stop the clock, so a page showing board
B while the session runs board A marked B as running a program. Nothing is
needed there: `/api/board/pins` already decides it and decides it WITH the
identity check the poll cannot make. And `pin_view` had to coalesce, because
`pin_levels` answers `None` for a description with no `pin_states`, so a
running board with no reader would have said nothing was running.

Generalisation: **a boolean about a fetch belongs to the fetch.** When a
downstream layer tries to reconstruct it, it will reconstruct it from whatever
it happens to have, and that is a different fact.

### 3.4 The class of test defect this session kept producing

Four assertions I wrote checked that a STRING was present rather than that a
VALUE was used. The worst, found by the OH-164 reviewer as a blocker:
`unknownWords(pad, true)` restored the entire defect with the whole suite
green, because the test asserted only that `renderTable` *contains*
`layout?.read_levels`. The other three were `NOT_MODELLED` compared against a
PARAMETER named earlier in the same signature; a whole-file search for a
pattern that this test's own docstring spells out; and an order pinned between
two sentences without pinning which branch reaches which.

Generalisation: **in a file that greps source because it cannot execute it,
every assertion must name a call site or a branch, never a substring.**
`stripped()` removes `//` lines only, so a `/** */` block satisfies a
whole-file search — and a docstring that quotes the thing it rejects is itself
the decoy.

### 3.5 Six stated measurements that were wrong

Recorded because the pattern matters more than any one of them.

| I wrote | actually | how it was caught |
|---|---|---|
| 0.117 units is 0.021 mm | 0.208 mm — `mmScale` is units per mm, so the Uno's is 0.5638 not 5.638 | review |
| a crowded bench never settles | it settles; 8.9e-10 by 8,000 frames | my own fix falsified it |
| mid-air crossings never reach the board | twelve do, at 0.2273 | verifier |
| leads always part by at least two radii | short by a quarter of a percent under ten pressing | verifier |
| the C3 has four board files | three; the tally came to 27 not 26 | review |
| three modules answered before OH-160 | two, over three board files | review |

The ten-times error propagates: 0.16 units of tube is 0.284 mm, so the
long-lived "0.289 mm" residual is **1.018 wire radii**, not the 10.2 that
`docs/tickets/OH-132-*.md` computes. Its pinned-end conclusion still stands on
separate evidence, but the arithmetic it offers against the alternative does
not. **That ticket and the 2026-09-04 handoff still carry the wrong figure and
were not this session's paths to edit.**

## 4. Reproduce-the-result runbook

```bash
cd C:/Users/Alexyodude/Desktop/AlexFolder/Code/Github/OpenHardware
git log --oneline -4              # 0620214, 0deea1c, 00c35d8, 464a3da

# The three headline numbers, each one command.
python -c "from webui import api; v=api.pad_view('Arduino Uno', api.description_for('Arduino Uno'), None); print(v['read_levels'], v['unknown'], len(v['pads']))"
#   False 32 32          <- picked, and nothing claims to be in use

python -m pytest tests/webui/test_wires.py -q -p no:cacheprovider      # 24 passed
python -m pytest tests/webui/test_board3d.py -q -p no:cacheprovider    # 95 passed
python -m pytest tests/webui/test_pin_view.py -q -p no:cacheprovider   # 32 passed, ~67 s
```

**The gate must be run in pieces on this machine.** `python tools/checkall.py`
was killed three times at about nine minutes; see §9.1. Run instead:

```bash
for c in check_layering check_board_contract check_part_schemas check_licenses \
         check_deltas check_banned_symbols check_board_claims check_ticket_claims \
         check_facts; do python tools/$c.py >/dev/null && echo "$c OK"; done
python tools/ticket_guard.py --self-test           # exits 0
python docs/research/board-sources/render.py --check
for s in rules webui i8086 avr cortexm0 rv32 riscv32; do
  python -m pytest tests/$s -q -p no:cacheprovider | tail -1
done
#   677 / 689+17s / 233 / 92 / 206 / 12 / 196  = 2,105 passed, 17 skipped
```

## 5. File inventory

**Committed in `464a3da` (OH-162 step 1)** — `webui/static/wires.js`
(`this.radius`, grown solids, the two-pass `collide`, `outOfSolids`),
`webui/static/board3d.js` (`applyColliders` hands the radius over),
`tests/webui/test_wires.py` (+4 tests), `tests/webui/test_board3d.py` (+1).

**Committed in `00c35d8` (OH-162 step 2)** — `webui/static/wires.js`
(`neighbours`, `offNeighbours`, `mayReach`, `partSegments`,
`nearestNeighbour`, `closestOnSegments`, `along`, `CLOSEST`),
`webui/static/board3d.js` (`view.ropes`, refilled once a frame in `animate`),
`tests/webui/test_wires.py` (+9), `tests/webui/test_board3d.py` (+1).

**Committed in `0deea1c`** — `docs/tickets/OH-162-*.md` frontmatter only:
`tests/webui/test_board3d.py` removed from its `touches`.

**Committed in `0620214` (OH-164)** — `webui/api.py` (`read_levels`, and
`pin_view` coalescing), `webui/static/board3d-panel.js` (`NOTHING_RUNNING`, the
three-way `unknownWords`, `renderTable` reading the field, the marking REMOVED
from `levels`), `tests/webui/test_pin_view.py` (+3),
`tests/webui/test_board3d.py` (+1).

**Scratchpad, session-temp and possibly gone** — 47 files under
`…/d4fefe50-…/scratchpad/oh162*` and `oh164*`. The ones worth knowing about if
they survive: `oh162_mutate.py` and `oh162b_mutate.py` (23 and 24 mutations),
`oh164_mutate.py` (14), `oh162_duty.py` (the like-for-like duty-cycle
measurement on copies), `oh162_candidates.py` (the four blocker fixes
compared), `oh162_probe_test.py` (runs a named test's own node body and prints
what it measures, so a docstring number cannot drift from its assertion).

**Not in git, left deliberately** — `build/lib/riscv32.dll.locked-by-pid44724`,
unchanged from the previous handoff.

## 6. Measurements this session

### 6.1 The wire solver, before and after

| | before OH-162 | after |
|---|---|---|
| settled wire's `proud` over a box | 0.16 (the whole tube) | 0 |
| `inside`, same wire | 0 | 0 |
| two crossed leads, nearest centre to centre | 0.2243 | 0.4086 |
| twelve leads crossing, energy at 3,000 frames | 2.9e-17 (they were overlapping) | 6.5e-15 |
| twelve leads crossing, nearest gap | 0.0053 | 0.3159 |

### 6.2 The cost the ticket asked for

Eight leads over a slab and eight component boxes, median of three runs of
1,500 steps after a 600-step warm-up, the SAME code in each position:

| | µs per rope-step | ms per 60 Hz frame |
|---|---|---|
| before step 2 | 23.1 | 0.37 |
| once a step (shipped) | 35.6 | 0.57 |
| once a pass | 184.9 | 2.96 |

**A 60 Hz frame is TWO substeps, not eight.** `advance(1/60)` returns 2;
`MAX_SUBSTEPS` 8 is only reached below 15 fps. Every per-frame figure in an
earlier draft was four times too big.

Once a pass is 5.2× dearer and settles the crowded case WORSE — 0.233 of energy
after 3,000 frames against 6.5e-15 — so the decision rests on quality, not
cost. An earlier justification cited 1,665 µs, which had been measured before
the bounds rejections existed and so compared two algorithms while calling them
two placements.

### 6.3 OH-164, over all 26 boards

Pads that are `unknown` with a `chip_pin`, for a board picked and not loaded —
exactly what `unknownWords` reads:

| | boards | pads |
|---|---|---|
| Arduino Uno | 1 | 22 of 32 |
| XIAO-ESP32-C3-SMD | 1 | 15 |
| the other ten modelled | 10 | 11 each |
| no module at all | 14 | 0 |
| | **26** | |

After: 0 boards report any pad as "in use elsewhere" while picked.

### 6.4 Mutation testing

| change | mutations | all killed |
|---|---|---|
| OH-162 step 1 | 23 | yes |
| OH-162 step 2 | 24 | yes |
| OH-164 | 14 | yes |

**Nine test gaps were found this way** and all are closed. Three mutations were
retired as genuinely equivalent rather than chased, each with the reason
written on the line it protects: running the wire pass twice, deleting the
`wa === 0 && wb === 0` guard, and removing either bounds rejection.

## 7. Commits this session

```
0620214 fix(webui): a board you have only picked stops claiming its pins are in use (OH-164)
0deea1c docs(tickets): OH-162 gives back the renderer's test file
00c35d8 feat(webui): two jumper leads stop occupying the same space (OH-162 step 2)
464a3da feat(webui): a jumper lead has a thickness the solver knows about (OH-162 step 1)
```

## 8. No pictures were taken, and the ticket asked for two

OH-162 step 1 says "screenshot before and after" and step 2 implies the same.
**Neither was done.** Everything in §6 is a number this session measured by
running the arithmetic under node, which is this repository's own position on
what Python can check about a WebGL scene — but it is not the same as looking,
and the ticket asked for looking. A future session with a browser should take
them; the drape changed on every board and nobody has seen it.

## 9. Known quirks

### 9.1 The gate runner is being killed at about nine minutes

`python tools/checkall.py` was started four times and killed three, each at
roughly the same elapsed time, twice leaving an `openhardware-build-*`
directory in `%TEMP%` that fails `test_a_failed_build_leaves_nothing_behind`.
Both were inspected (a compile-test sketch) and removed. The fourth run
completed and passed.

**Run the twelve checks individually** (§4). They pass. Whether the kill is a
harness task lifetime, the machine, or something in `checkall.py` itself was
not diagnosed — it was worked around, and that is worth someone's time.

### 9.2 A load-sensitive test

`tests/webui/test_emulator.py::test_a_state_poll_answers_while_a_build_runs`
failed once during this session and passed on every other run including alone.
It asserts a wall-clock latency (`waited < 3.0`) while a real build runs, and
it failed while a review agent's own pytest and a mutation batch were running
concurrently. Not a regression; do not chase it unless it fails on a quiet
machine.

### 9.3 The rest

- `python -m ruff check .` from the repo root reports 176 findings under
  ruff's default rules. **Ruff is not one of the gate's twelve checks.** The
  files this session touched carry one pre-existing finding between them.
- `docs/tickets/OH-132-*.md` and `docs/HANDOFF_2026-09-04_*.md` carry the
  ten-times millimetre error described in §3.5. Neither was this session's to
  edit.
- The worktree is CRLF (`core.autocrlf=true`) while blobs are LF. Any script
  matching multi-line anchors must normalise newlines and must treat "anchor
  not found" as a failure.
- Bash heredocs here eat backslashes: `\n` inside a quoted heredoc becomes a
  real newline. It cost two broken scripts this session. Write scripts with
  the Write tool and run `python <file>`.
- `mcp__plugin_oh-my-claudecode_t__state_*` refuses this repository as
  "a different repository", because the session's cwd is the user profile. The
  ralph state had to be removed by hand from
  `.omc/state/sessions/d4fefe50-…/ralph-state.json`.
