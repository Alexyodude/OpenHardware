---
name: feature-strategy
description: Use when deciding what to build next in OpenHardware — derives a feature ledger and implementation strategy for a simulator capability gap, with every feature bound to an external oracle. Use before starting any new core, solver, peripheral, or UI area.
---

# Feature strategy

Turn a vague capability gap into an ordered ledger of features, each defined by
a conformance test against ground truth.

**Announce at start:** "Using feature-strategy to derive the ledger for <area>."

## The premise

Features are cells in a capability matrix, and every cell is defined by a
conformance test against an external oracle. A simulator is the rare domain
where ground truth is always obtainable, so "done because it looks right" is
never necessary and never acceptable.

## Phase 0 — inventory the base, with evidence

Before enumerating anything, establish what the fork already does. PICSimLab
ships six CPU engines, 21 boards, and roughly 95 parts; rebuilding any of it is
pure loss.

**Read the source, not the file names.** This project has already been burned
once: the design document rated the analog solver "invasive, needs a new layer
between parts and boards" based on a directory listing. Reading the source
showed parts reach pins through the `SpareParts` mediator and a pure-virtual
pin API that already carries float voltages. The rating was wrong by an entire
architectural layer.

Record each finding with the file and construct that proves it. A rating with
no citation is a hypothesis.

**Output:** a list of what exists, each entry citing a path.

## Phase 1 — build the capability matrix

Enumerate the axes of the gap. For a CPU core: instruction groups × addressing
modes × flag effects × interrupts × timing. For the analog solver: element
types × solver modes (DC operating point, transient, convergence) × tolerance.
For a peripheral: registers × operating modes × error conditions.

Prefer many small cells to few large ones. A cell that cannot be finished in a
day is two cells.

**Output:** the cross product, before any filtering.

## Phase 2 — assign a fidelity tier

| Tier | Meaning |
|---|---|
| `F0` | functional — right result, wrong timing |
| `F1` | timing-approximate — instruction counts right, sub-cycle wrong |
| `F2` | cycle-accurate — matches hardware cycle counts |
| `F3` | electrically-accurate — matches SPICE within tolerance |

Default to `F0`. Promote only with a reason recorded in the strategy document.

## Phase 3 — bind an oracle to every cell

Each cell names its oracle and tolerance:

- CPU cores — vendor ISA manual tables, a reference emulator, real silicon
- analog — `ngspice` on the same netlist
- peripherals — datasheet timing diagrams
- regression — a previously captured VCD

**A cell with no oracle cannot be scheduled.** Leave it `planned` and say so.
`tools/ledger.py` enforces this.

Tolerance is `exact` or a numeric bound. Upstream's `tests/python/test_blink.py`
shows the shape: `assert pcyc == pytest.approx(20, abs=2)`.

## Phase 4 — order into slices

Topologically sort by dependency, then group into slices that each end in
something demoable. A slice with no demo is a slice nobody can review.

## Phase 5 — emit

Two artifacts:

1. `docs/features/<area>.md` — the ledger. Must parse under `tools/ledger.py`.
2. `docs/superpowers/plans/<date>-<area>.md` — the strategy: slice order,
   promotion reasons, and every Phase 0 finding with its citation.

Verify before finishing:

```bash
python -c "from tools.ledger import parse_ledger; import pathlib; \
print(len(parse_ledger(pathlib.Path('docs/features/<area>.md'))), 'cells')"
pytest tests/rules/ -v
```

## Rules that bind this work

- `.claude/rules/conformance-fixtures.md` — oracle and fixture requirements
- `.claude/rules/core-interface.md` — where a new architecture may live
- `.claude/rules/upstream-sync.md` — additive by default
- `.claude/rules/determinism.md` — no nondeterministic calls in new code
- `.claude/rules/gpl-hygiene.md` — headers and dependency licences

## Red flags

| Thought | Reality |
|---|---|
| "The oracle is obvious, I'll add it later" | A cell with no oracle cannot be scheduled. Write it now. |
| "This is clearly cycle-accurate" | Declare `F0` until a fixture proves otherwise. |
| "The directory listing shows..." | Read the source. This project has been wrong that way before. |
| "I'll skip the fixture, the test passes" | A test that cannot reach its oracle passes vacuously. |
| "This cell is big but cohesive" | If it takes more than a day, it is two cells. |
