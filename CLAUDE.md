# OpenHardware

A fork of [PICSimLab](https://github.com/lcgamboa/picsimlab) extended toward
simulating every class of hardware in one tool: MCU firmware with virtual
peripherals, CPU/ISA simulation, and analog circuit solving.

Upstream is GPL-2-or-later. **So is everything here.**

## Rules

`.claude/rules/` is not auto-loaded. These are listed so they enter context;
the checkers named in each file are what actually enforce them.

- `.claude/rules/gpl-hygiene.md` — no v2-only headers; dependency licences
- `.claude/rules/upstream-sync.md` — additive by default; log every upstream edit
- `.claude/rules/core-interface.md` — backends never include parts or UI
- `.claude/rules/determinism.md` — no nondeterministic calls in new code
- `.claude/rules/conformance-fixtures.md` — oracle and fixture requirements

## Before you commit

```bash
python tools/check_layering.py
python tools/check_licenses.py
python tools/check_deltas.py
python tools/check_banned_symbols.py
pytest tests/rules/ -v
```

Never run bare `pytest` from the repo root: upstream's `tests/python/` imports
the out-of-tree module `PICSimLab_rcontrol` and needs a built binary.

## Deciding what to build

Use the `feature-strategy` skill. Do not add features to a ledger by hand.

## Fork point

Tag `fork-point` = `cd92747b1a04cab56c17f4e9ac35a1406c9935f7` (2026-07-30).
Every modification to a file that existed then must appear in
`docs/upstream-deltas.md`.

CI (`.github/workflows/rules.yml`) needs the `fork-point` tag pushed to
whatever remote hosts this repo — tags are not carried by an ordinary branch
push. As of this writing that push has not happened: this repo has no
`origin` remote, only `upstream` (the read-only upstream project), so there
is nowhere of ours to push the tag to yet.
