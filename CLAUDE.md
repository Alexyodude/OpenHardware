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
python tools/check_board_contract.py
python tools/check_licenses.py
python tools/check_deltas.py
python tools/check_banned_symbols.py
pytest tests/rules/ tests/webui/ -v
```

Never run bare `pytest` from the repo root: upstream's `tests/python/` imports
the out-of-tree module `PICSimLab_rcontrol` and needs a built binary. Name the
suites explicitly.

## Running the UI bridge

```bash
python webui/bridge.py --rcontrol-port 5000 --ws-port 8787
```

It connects to a running `picsimlab` over rcontrol and serves a websocket on
loopback. It refuses to bind anything but loopback, checks `Origin`, and
exposes an explicit operation allowlist rather than passing raw protocol text
through — a websocket on localhost is reachable by any page you visit.

`webui/api.py` is the layer both transports share. A future WASM build calls
the same operations through `ccall`; only the transport under
`webui/rcontrol.py` changes.

**The bridge's tests run against a stub server, not a real simulator.** They
prove the client matches `src/lib/rcontrol.cc` as read, not as executed. The
differential cells in `docs/features/webui.md` stay `in-progress` until a live
session confirms it.

## What is in here

```bash
python tools/inventory.py              # tests, mechanisms, files, ledgers
python tools/inventory.py --markdown   # same, pasteable, with provenance
```

Every number it prints is computed from the repository — test counts by
parsing each file, mechanisms from rule frontmatter, files from `git diff`
against `fork-point`, ledger cells via the ledger parser.

**Do not write those counts down anywhere.** An inventory is the document that
rots fastest, and this repo has already caught two rule files describing code
they no longer matched. Run the generator instead of maintaining a list.

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
