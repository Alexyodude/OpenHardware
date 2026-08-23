# OpenHardware — feature-strategy machinery

**Date:** 2026-08-09
**Status:** design approved, not yet implemented
**Scope:** the meta-layer only — a feature-derivation skill and five `rules`.
No simulator code is written in this pass.

## 1. What this project is

OpenHardware is a fork of [`lcgamboa/picsimlab`](https://github.com/lcgamboa/picsimlab)
extended toward "simulate all" — every class of hardware simulation in one tool.

The stated goal covers three things that are usually three separate products:

- MCU firmware emulation with virtual peripherals (Wokwi-style)
- CPU/ISA simulation with register and memory inspection (8086)
- analog and digital circuit solving (Falstad/SPICE-style)

These unify under one idea: **the net is the universal interface.** A CPU core
drives a pin; it never knows an LED exists. Under that model an 8086 is the
degenerate case (a core with a memory bus and no pins), an MCU board is a core
whose pins bind to digital nets, and a circuit simulator is the same net graph
resolved by an analog solver instead of by digital strength rules.

PICSimLab already implements most of that. This document is about the machinery
that decides what to build next and keeps the fork honest while it happens.

## 2. Decisions already made

| Decision | Choice | Consequence |
|---|---|---|
| Base | Fork `lcgamboa/picsimlab` | Six working CPU engines for free |
| License | GPL-2.0, mandatory | All work is open source; upstreamable |
| First slice | Skill + rules, no simulator code | Machinery before construction |

## 3. The base, as verified

Read from the repository tree on 2026-08-09, not from the README.

```
              lxrad UI · picsimlab1..6 · *.lxrad
              Makefile.{X11, SDL2, JS, JSMT, NOGUI}
   ┌───────────────────────┴───────────────────────┐
   │              boards/ board_<Name>             │  21 boards
   │   Uno · Mega · BluePill · DevKitC · McLab · … │
   └────────┬──────────────────────────┬───────────┘
            │ pins                     │ hosts
   ┌────────┴─────────┐   ┌────────────┴──────────────┐
   │ parts/  ~95      │   │ sim_backend/  bsim_<eng>  │
   │  input_*   ~35   │   │  bsim_picsim      PIC     │
   │  output_*  ~20   │   │  bsim_simavr      AVR     │
   │  other_*   ~15   │   │  bsim_ucsim  8051/STM8/Z80│
   │  virtual_*  ~5   │   │  bsim_qemu   STM32/ESP32  │
   └──────────────────┘   │  bsim_gpsim       PIC     │
                          │  bsim_remote      TCP     │
                          └───────────────────────────┘
```

Three extension seams, consistent across 60 board files and ~95 part files:

- new architecture → `sim_backend/bsim_<name>.{cc,h}`
- new board → `boards/board_<Name>.{cc,h}`
- new component → `parts/{input,output,other,virtual}_<name>.{cc,h}`

Three properties of the base matter more than anything in its README:

- **`bsim_remote.cc` + `board_RemoteTCP`** — a remote-control protocol already
  exists, so the programmatic drive-the-simulator harness starts from something
  rather than nothing. Whether it exposes *enough* is untested (§8.3).
- **`virtual_*` parts include VCD dump** — waveform output in a standard,
  diffable format. An oracle channel already exists.
- **`Makefile.NOGUI`** — headless builds, so conformance testing can run in CI
  without a display.

Together these make the conformance-fixture rule (§6.5) plausibly implementable
without upstream changes: drive headless over TCP, dump VCD, diff against
reference. Each leg of that chain is inferred from file names and sizes, not
from running it — §8.3 and §8.4 exist to convert the inference into evidence
before §6.5 is armed.

Top-level `lib/` is empty except `.gitignore` and `README`; the simulation
engines are fetched by `bscripts` at build time rather than vendored.

## 4. Gap analysis

| Target | Base today | Gap |
|---|---|---|
| PIC | `picsim`, `gpsim` | covered |
| AVR / Arduino | `simavr` | covered |
| 8051 / STM8 / Z80 | `uCsim` | covered |
| STM32 | `qemu-stm32` | covered |
| ESP32 / ESP32-C3 | `qemu-esp32` | covered |
| **8086 / x86-16** | — | **absent** |
| **Analog solver (MNA)** | behavioral parts only | **absent** |
| RP2040 | — | absent |
| Wokwi-style web UI | lxrad desktop + WASM build | UX gap |

Where each gap lands:

| Gap | Seam | Invasiveness |
|---|---|---|
| 8086 core | `bsim_i8086.*` + `board_x86.*` | **Additive** — follows the existing pattern exactly |
| Web UI | bridge to `rcontrol` (§4.2) | **Additive** — no new C++ at all |
| Analog solver | `SpareParts` mediator (§4.1) | **Contained** — extends one existing chokepoint |

Two of three additions are new files that never touch upstream code and rebase
cleanly forever. The analog solver is the exception, but a smaller one than this
document originally assumed — see §4.1.

Hence: **additive files by default; every modification to an upstream file is a
tracked, justified delta** (§6.2).

### 4.1 The part-to-pin call path, verified

An earlier draft of this document asserted that the analog solver "needs a
net/node layer between parts and boards" and rated it **Invasive**. That was
wrong, and the correction matters enough to record rather than delete.

Read from the working tree at `fork-point`, the path is three layers deep
already:

```
parts/*  →  SpareParts        →  board                →  bsim_*
            src/lib/spareparts   src/lib/board.h         sim_backend/
            (mediator singleton)  (pure-virtual pin API)  (engine)
```

Parts never address a board directly. `input_POT.cc` drives its output with
`SpareParts.SetAPin(output_pins[i], …)`; `input_LDR.cc` uses both
`SpareParts.SetPin` and `SpareParts.SetAPin`. The board base class declares the
contract as pure virtuals:

| Method | Signature |
|---|---|
| `MSetPin` | `(int pin, unsigned char value)` |
| `MSetPinDOV` | `(int pin, unsigned char ovalue)` |
| `MSetAPin` | `(int pin, float value)` |
| `MSetPinOAV` | `(int pin, float value)` |
| `MGetPin` | `(int pin)` |

Two consequences, pulling in opposite directions:

**The seam exists.** `SpareParts` is already the chokepoint through which every
part↔pin exchange passes, and `MSetAPin` already carries float voltages. The
analog solver extends an existing mediator rather than inserting a new layer
through upstream's hottest interface. This is the difference between a change
that conflicts on every sync and one that is plausibly upstreamable.

**The semantics do not.** Pins are addressed individually, by index, with scalar
values. Nothing expresses that two pins sit on the same net. `grep` across
`src/lib/` finds no net, node, or nodal construct at all. MNA requires precisely
what is missing: shared nodes solved simultaneously. The insertion point is
therefore cheap and the actual work is not.

`src/lib/oscilloscope.{cc,h}` also already exists, so the waveform display in
slice 3 is a consumer of new data rather than new UI.

The general lesson is recorded in §6 as the reason Phase 0 exists: this
document's invasiveness rating was inferred from a directory listing and was
wrong by one whole architectural layer. Ratings derived from file names are
hypotheses, not findings.

### 4.2 The remote-control surface, enumerated

Added 2026-08-10, and it is the second correction of the same kind.

An earlier reading of `src/lib/rcontrol.cc` extracted its vocabulary with a
regex over bare quoted tokens, which **missed every command matched by
`strncmp` with a trailing space**. On that partial evidence the interface looked
read-oriented and the web UI looked expensive.

Read by dispatch branch instead, `set` has four forms
(`src/lib/rcontrol.cc:1127`):

| form | reaches |
|---|---|
| `set board.in[NN] = v` | board inputs — buttons, pots, jumpers; raises `Input->update` |
| `set apin[NN] = f` | `SpareParts.SetAPin` / `Board->MSetAPin` |
| `set pin[NN] = v` | `SpareParts.SetPin` / `Board->MSetPin`, under `IoLockAccess()` |
| `set part[N].in[M] = v` | a specific spare part's input |

`get` has eight (`src/lib/rcontrol.cc:724`): `board.in[]`, `board.out[]`,
`apin[]`, `pin[]`, `pinl[]`, `pinm[]`, `part[N].in[M]`, `part[N].out[M]`.
Alongside them: `spadd` and `spdel` to place and remove parts while running,
`sprdcfg`/`spwrcfg` to configure them, `loadhex`, the `sim`/`reset`/`start`/
`stop` run controls, and the `osc*` family.

**That is the entire interaction model a Wokwi-style UI needs, already
implemented and already exercised by upstream's `tests/python/test_blink.py`.**
The web UI therefore requires no new C++ — it is a bridge plus a front-end,
which is why §9 now places it first.

Two limits worth stating so they are not rediscovered later. There is **no
CPU-register write**, so the 8086 conformance harness must still drive its core
directly rather than through this interface (§8.3 is unaffected). And the
Emscripten build in `src/Makefile.JS` is **not reproducible from this
repository** — no build script, no CI, `template.html` and `src/assets` both
absent, and hardcoded sibling checkouts including one reaching into another
project's test directory. It also links no QEMU, so ESP32 and STM32 are absent
from any browser build.

## 5. The skill — how features get derived

`skills/feature-strategy/SKILL.md`

The premise that makes this systematic rather than vibes:

> Features are cells in a capability matrix, and every cell is defined by a
> conformance test against an external oracle.

A simulator is the rare domain where ground truth is always obtainable — real
silicon, a reference emulator, vendor ISA test vectors, `ngspice` on the same
netlist, datasheet timing diagrams. A feature is never "done because it looks
right"; it is done when its fixture matches an oracle within a declared
tolerance. That is the lever that makes the rules machine-checkable rather than
aspirational.

### Phases

**Phase 0 — inventory the base.** Enumerate what the fork already provides
across all six embedded engines. Prevents rebuilding what `simavr` gives free.
Phase 0 must answer with evidence, not assumption; its blocking questions are
listed in §8.

**Phase 1 — capability matrix.** Enumerate axes for the targeted gap. A CPU
core: instruction groups × addressing modes × flag effects × interrupts ×
timing. The analog solver: element types × solver modes (DC operating point,
transient, convergence) × tolerance.

**Phase 2 — fidelity tier per cell.**

| Tier | Meaning |
|---|---|
| `F0` | functional — right result, wrong timing |
| `F1` | timing-approximate — instruction counts right, sub-cycle wrong |
| `F2` | cycle-accurate — matches hardware cycle counts |
| `F3` | electrically-accurate — analog only, matches SPICE within tolerance |

This is the anti-scope-creep device. Most cells ship at `F0` and are *declared*
`F0`. The failure mode in simulators is not shipping low fidelity; it is
shipping low fidelity while implying high.

**Phase 3 — oracle binding.** Every cell names its oracle and tolerance.
**A cell with no oracle cannot be scheduled.** Hard gate.

**Phase 4 — dependency ordering.** Topologically sort cells into vertical
slices, each ending in something demoable.

**Phase 5 — emit** a feature ledger and an implementation strategy document.

### The ledger

Markdown with a parser, matching how `finding-convention.md` already works in
`wrinkle`. One row per cell:

```
id · tier · oracle · tolerance · status · fixture path
```

Emitted to `docs/features/<area>.md`. The rules in §6 enforce against this
ledger, which is what closes the loop between derivation and construction.

## 6. The rules

`rules/`, written in the `wrinkle` house format: numbered dated
headings, each labeled with its enforcement tier, each naming the construct
that enforces it rather than a line number.

`rules/*.md` is **not** auto-loaded by Claude Code. A rules file is
advisory unless something reads it. Enforcement tiers therefore mean:

| Tier | Mechanism | Catches violation |
|---|---|---|
| `CONVENTION` | documented only | never, automatically |
| `HOOK-ENFORCED` | `PreToolUse` hook blocks the call | in-session, before the edit lands |
| `SCRIPT-ENFORCED` | named checker script in CI | at commit / PR |
| `TEST-ENFORCED` | a test fails | at test run |
| `PARSER-ENFORCED` | malformed input is silently dropped by a parser | never — the data just vanishes |

`PARSER-ENFORCED` is the tier `wrinkle` already uses, and it is the dangerous
one: breaking a parser rule does not fail loudly, it deletes data. It is listed
as an enforcement tier because the parser does constrain what is representable,
but it must always be paired with a test that asserts the drop is visible.

No rule below currently uses `HOOK-ENFORCED`. The tier is defined because the
analog work in slice 3 is expected to need it — an in-session block on editing
upstream pin-interface files is worth more than a CI failure discovered after
the edit. It stays unused until then rather than being retrofitted onto rules
that CI already covers.

The repo-root `CLAUDE.md` references the rules so they enter context; the
mechanisms above are what actually enforce them.

### 6.1 `gpl-hygiene.md` — SCRIPT-ENFORCED (`tools/check_licenses.py`)

Every new source file carries upstream's GPL-2 header; every dependency passes
a license allowlist.

The sharp edge: **Apache-2.0 is incompatible with GPL-2-only** (patent
termination clause), but is compatible with GPL-3. If upstream's per-file
headers read "version 2, or (at your option) any later version," the project can
move forward to GPL-3 and use Apache-licensed dependencies. If they read v2
only, every Apache-2.0 library is permanently unavailable. MIT and BSD are fine
either way.

`COPYING` does not settle this — it is the stock GPL-2 text, whose appendix
contains the "or any later version" boilerplate in every copy ever distributed.
Only the per-file source headers decide it.

**Resolved 2026-08-09: upstream is v2-or-later** (§8.1), so Apache-2.0
dependencies are available via GPL-3 for the combined work. The checker's job is
therefore to prove this stays true: it must fail on any file carrying a
**v2-only** header, since a single such file anywhere in the tree revokes the
GPL-3 path and every Apache-2.0 dependency with it. Checking that a header
merely *exists* would pass the exact tree that breaks the project.

### 6.2 `upstream-sync.md` — SCRIPT-ENFORCED (`tools/check_deltas.py`)

The fork commit is tagged `fork-point`. Additive files are unrestricted. Any
modification to a file existing at `fork-point` must appear in
`docs/upstream-deltas.md` with a reason. The checker diffs the working tree
against the tag and fails on an unlogged modification.

This is what keeps the analog work — the one invasive change — from silently
metastasizing across upstream's codebase and making every future merge a knife
fight.

### 6.3 `core-interface.md` — SCRIPT-ENFORCED (include-lint) + CONVENTION

A new architecture is a `bsim_*` pair implementing the same contract as the
existing six. The enforced part: nothing under `sim_backend/` may include from
`parts/` or from lxrad/UI headers. That check is a grep, and it is what stops
the 8086 core from growing UI tentacles the way ad-hoc cores always do.

### 6.4 `determinism.md` — TEST-ENFORCED (replay test) + SCRIPT-ENFORCED (banned-symbol grep)

Same firmware, same inputs, same VCD hash. Run twice headless, compare. Backed
by a grep banning `rand()`, `time()`, `clock()` and uninitialized-read patterns
in simulation paths. Simulation time stays integer — never float accumulation.

The cheapest rule to check and the one that catches the worst class of simulator
bug: the kind that produces plausible output and wastes weeks. Implementable
immediately, because `Makefile.NOGUI` and the VCD dump parts already exist.

### 6.5 `conformance-fixtures.md` — PARSER-ENFORCED (ledger schema) + TEST-ENFORCED (fixture runner)

Every ledger cell carries `id · tier · oracle · tolerance · status · fixture`.
A cell cannot reach `status=done` without a fixture passing against its oracle.
A cell with no oracle cannot be scheduled at all.

### 6.6 The meta-guard

A rule that *claims* enforcement it does not have is worse than no rule, because
it implies coverage that is not there.

Each rule file declares its checker. `tests/test_rules_are_armed.py` fails if
any rule claims `SCRIPT-ENFORCED`, `TEST-ENFORCED`, or `PARSER-ENFORCED` while
the named script, test, or parser construct does not exist. This mirrors
`wrinkle`'s `test_self_extraction.py`: the file is its own corpus, and a test
fails if it stops obeying itself.

`PARSER-ENFORCED` carries an extra obligation, for the reason given in §6: a
parser rule fails silently. Each one must name a test that asserts the drop is
*reported* — a rule whose only evidence is that malformed input disappeared is
indistinguishable from data loss.

Rules 6.1–6.3 are enforceable the day the fork lands. Rules 6.4–6.5 need a
working headless build first, so they ship `armed: false`, and the meta-guard
tracks that state explicitly rather than letting it rot silently.

## 7. Repository layout

> **Superseded 2026-08-23.** This records the fork-era layout as designed.
> OpenHardware is no longer a fork: PICSimLab is external, the rules moved
> from `.claude/rules/` to `rules/`, and the licence is MIT. The diagram is
> left as written because a spec is a record of what was decided, not a
> description of the present. See `README.md` and `PROVENANCE.md`.

```
OpenHardware/                     fork of lcgamboa/picsimlab @ GPL-2.0
├── .claude/
│   ├── skills/feature-strategy/
│   │   └── SKILL.md
│   └── rules/
│       ├── gpl-hygiene.md
│       ├── upstream-sync.md
│       ├── core-interface.md
│       ├── determinism.md
│       └── conformance-fixtures.md
├── CLAUDE.md                     references the rules
├── docs/
│   ├── superpowers/specs/        this document
│   ├── features/                 ledgers the skill emits
│   └── upstream-deltas.md        tracked modifications to upstream files
├── tools/
│   ├── check_licenses.py
│   └── check_deltas.py
├── tests/
│   └── test_rules_are_armed.py
└── src/, share/, bscripts/ …     picsimlab, unmodified at fork point
```

## 8. Phase 0 blocking questions

Each must be answered with evidence before the work it gates is scheduled.

**1. ANSWERED 2026-08-09 — upstream is GPL-2-or-later.**
`src/picsimlab1.cc` and `src/sim_backend/bsim_simavr.h` both carry "either
version 2, or (at your option) any later version." The combined work may
therefore move forward to GPL-3, which makes **Apache-2.0 dependencies
available**. Recorded in §6.1. Note this was read from two files; if
`tools/check_licenses.py` finds a v2-only header anywhere in the tree, this
answer inverts and every Apache-2.0 dependency must be removed. The checker
must assert the *absence* of v2-only headers, not merely the presence of a
header.

**2. ANSWERED 2026-08-09 — an indirection exists; network semantics do not.**
Parts reach pins through the `SpareParts` mediator, which reaches boards through
a pure-virtual pin API. Full detail and the call path in §4.1. The original
**Invasive** rating was wrong and is corrected there. Residual unknown, now the
real question for slice 3: whether `SpareParts` can carry shared-node semantics
without changing its per-pin scalar signatures, or whether the analog path needs
a parallel API alongside the existing one.

**3. OPEN — does `bsim_remote`'s protocol expose enough to drive conformance
fixtures headlessly, or does it need extending?**
Gates: whether §6.5 is additive or requires an upstream delta. `src/lib/rcontrol.{cc,h}`
is the place to read.

**4. OPEN — does the NOGUI build produce VCD output without a display?**
Gates: whether §6.4 can be armed on day one. Requires actually building
`Makefile.NOGUI`, not reading it.

## 9. Roadmap beyond this slice

Each gets its own spec → plan → build cycle. Listed for context; not in scope here.

**Reordered 2026-08-10.** The web UI was slice 5 and is now slice 2. The
original order rested on two beliefs that reading the source disproved, in
opposite directions: that `rcontrol` was too read-only to drive a UI, and that a
working browser build already existed. The interface turned out richer than
believed and the build poorer. Full evidence in
`docs/superpowers/plans/2026-08-10-webui.md`; the ledger is
`docs/features/webui.md`.

| # | Slice | Proves |
|---|---|---|
| 1 | This document's machinery | Derivation and enforcement work on real code |
| 2 | Web UI over a bridge to `rcontrol` | Wokwi-class UX, on engines that already work |
| 3 | 8086 core (`bsim_i8086`) | The `bsim_*` contract generalizes to a wildly different ISA |
| 4 | Analog solver + scope | MNA, convergence, waveforms |
| 5 | Mixed-signal bridge | Event-driven digital co-simulating with timestep-driven analog |

The web UI is first because it is the only slice that produces something visible
using engines that are already built and tested — `simavr` and `picsim` — and
because it requires **no new C++**. `rcontrol` already implements the whole
interaction model: `set board.in[]`, `set pin[]`, `set apin[]`,
`set part[N].in[M]`, eight `get` forms, `spadd`/`spdel` for placing parts, and
`loadhex`. The 8086 core by contrast shows nothing to anyone until it is nearly
finished.

The 8086 core keeps its place ahead of the analog work, and for the original
reason: it is an abstraction test. It is additive and cheap, and it either
validates the `bsim_*` seam or exposes it as AVR/PIC-shaped before anything
invasive is attempted.

## 10. Non-goals

- No simulator code in this slice.
- No RP2040 core; deferred until the `bsim_*` contract is validated by slice 2.
- No cycle-accuracy (`F2`) targets anywhere yet. Everything starts at `F0` and
  is promoted only when a fixture and oracle justify it.
- No replacement of lxrad for the desktop build. The web UI is additive.
