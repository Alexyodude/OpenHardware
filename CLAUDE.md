# OpenHardware

A browser front-end and conformance harness for
[PICSimLab](https://github.com/lcgamboa/picsimlab), extending toward
simulating every class of hardware in one tool: MCU firmware with virtual
peripherals, CPU/ISA simulation, and analog circuit solving.

**This is not a fork.** PICSimLab is a separate program that this one drives
over its rcontrol TCP socket. Upstream's source is never vendored here; see
`docs/picsimlab-reference.md` for how to get a copy and
`PROVENANCE.md` for what is and is not derived from it.

This repository is **MIT**. `patches/` is GPL-2-or-later, because a diff
against GPL source is a derivative of it. Details in `LICENSE`.

## Where PICSimLab is

Everything resolves through `webui/picsimlab.py`, in this order:

1. `$PICSIMLAB_ROOT`
2. a sibling `../picsimlab-reference/`
3. a sibling `../picsimlab/`

`install_root()` needs only `share/` — a binary install is enough to run the
UI. `source_root()` needs `src/`, and only the rule checkers want it. A
checker that cannot find source **exits 3 and says SKIPPED**; it never passes
quietly.

```bash
git clone https://github.com/lcgamboa/picsimlab ../picsimlab-reference
tools/apply_patches.sh          # then rebuild it
```

## Rules

`rules/` is not auto-loaded. These are listed so they enter context;
the checkers named in each file are what actually enforce them.

- `rules/licence-hygiene.md` — MIT everywhere except `patches/` (GPL) and vendored trees
- `rules/upstream-sync.md` — every change to upstream is a documented patch
- `rules/core-interface.md` — backends never include parts or UI
- `rules/determinism.md` — no nondeterministic calls in new code
- `rules/conformance-fixtures.md` — oracle and fixture requirements
- `rules/ticket-claims.md` — one ticket per unit of work; a ticket owns the paths it may edit
- `rules/board-claims.md` — a board says it runs firmware only where a named test watched an image execute

## Before you commit

```bash
python tools/check_layering.py
python tools/check_board_contract.py
python tools/check_part_schemas.py
python tools/check_licenses.py
python tools/check_deltas.py
python tools/check_banned_symbols.py
python tools/check_board_claims.py
pytest
```

Bare `pytest` is now correct and is what CI runs. `pyproject.toml` sets
`--import-mode=importlib` and points `testpaths` at the two suites.

The old instruction here was the opposite — "never run bare `pytest` from the
repo root", because upstream's `tests/python/` was in the tree and imported an
out-of-tree module. That tree is gone.

The first four checkers need a PICSimLab **source** checkout and will skip
without one. `pytest` skips the same tests via the `upstream` fixture rather
than failing.

## Running the emulator

```bash
python tools/build_core.py                 # once, to build libi8086
python webui/emulator_server.py            # http://127.0.0.1:8088/
```

Optionally, once, for the vendors' own board models:

```bash
pip install cadquery-ocp                   # a TOOL dependency, not a runtime one
python tools/import_3d_model.py --all      # exits 3 and says SKIPPED without it
python tools/model_from_datasheet.py       # the parts nobody publishes at all
python tools/compose_board_3d.py           # the boards nobody publishes a mesh for
```

Twenty-three of the twenty-six boards then draw a vendor file instead of an
extruded footprint: **thirteen from Seeed's own mechanical model** and **ten
composed** from a published PCB, and the pin panel says which of the three
things it is showing. The three left are the two ESP32-C5 boards and the
STM32C5, for which Seeed publish nothing at all -- see
`docs/research/board-models/`. The meshes are gitignored -- see
`tools/import_3d_model.py` for the licence reason -- so a fresh checkout gets
the footprint until this is run.

**The last command is for a board whose vendor publishes no mesh at all**, and
the Arduino Uno is the one that does. It stands KiCad's published component
models on the outline and placements in Arduino's own EAGLE board file, so the
board draws with its notch, its DIP-28, its four headers, its barrel jack and
its USB socket without a height or a position being invented anywhere. It needs
the vendor's `.brd`, which `python tools/get_board_sources.py arduino-uno`
prints the URL for -- an `https-archive`, so it is downloaded by hand, as the
Pico's is.

**Geometry has four sources here and the page names which one it is showing.**
In order of preference: the vendor's own mechanical model; a published model of
the same package, from KiCad's `kicad-packages3D`; the manufacturer's own STEP;
and last, a mesh built in Blender by `tools/model_from_datasheet.py` because
nothing published exists. **Two parts are in that last category today**, and
every dimension in each is either read out of the vendor's own file at build
time or carries a citation beside it:

- the Uno's **USB-B**, from Arduino's EAGLE package `PN61729`, with the shell
  height from the USB specification -- `SPECS`;
- the XIAO RP2350's **QFN-60**, from Seeed's own footprint, with only the
  0.9 mm height taken from the last field of that footprint's NAME -- `PACKS`.

Nobody publishes a QFN-60 at all, and the near miss is refused on purpose:
`QFN-56-1EP_7x7mm_P0.4mm` is the right body at the right pitch with four leads
missing, and drawing it would put a false part name in the model's own list.
A part nothing can honestly draw is left off and says why.

**Fetch KiCad models from GitLab, which is the library.** `KiCad/kicad-packages3D`
on GitHub is a mirror and a different tree -- `Connector_USB` had 5 entries
there against 13 on GitLab when this was measured. `KICAD_3D` in
`tools/import_3d_model.py` is the one place that URL lives.

Registers, flags, memory and disassembly, with step and run and six sample
programs. It drives `core/i8086` directly and has nothing to do with
PICSimLab or the bridge below.

The server binds loopback only and checks `Origin`, for the reason
`webui/bridge.py` gives at length: loading a program means running arbitrary
8086 code in this process, so the boundary that matters is who can ask. The
emulated part cannot reach outside its own megabyte -- it has no way to open a
file or a socket.

`webui/emulator.py` is the session and holds all the behaviour;
`webui/emulator_server.py` is a thin JSON translation of it, so the tests
drive the session rather than the transport.

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
parsing each file, mechanisms from rule frontmatter, files from `git ls-files`
grouped by area, ledger cells via the ledger parser.

**Do not write those counts down anywhere.** An inventory is the document that
rots fastest, and this repo has already caught two rule files describing code
they no longer matched. Run the generator instead of maintaining a list.

Note that `collect_tests` counts `def test_*` with `ast`, so a parametrised
test would count once here and many times in pytest.
`test_ast_count_matches_pytest_collection` fails loudly on the divergence, so
**do not add `@pytest.mark.parametrize`** without teaching the counter about
it first. Use a loop inside one test.

## Working alongside another session

Work is tracked in `docs/tickets/`, one file per ticket, and a ticket declares
the paths it may edit. Before writing anything:

```bash
python tools/tickets.py list             # what is open, most urgent first
python tools/tickets.py start OH-3       # take it; refuses if another session holds it
python tools/tickets.py owner <path>     # who claims this file
python tools/tickets.py stop             # give it back
```

`tools/ticket_guard.py` refuses a write into another ticket's files before it
lands, and `tools/check_ticket_claims.py` catches the same thing in CI. See
`rules/ticket-claims.md`, and `docs/tickets/README.md` for installing the hook.

## Deciding what to build

Use the `feature-strategy` skill. Do not add features to a ledger by hand.

## Changing PICSimLab

Don't, if it can be avoided. 101 files of this project needed exactly one line
of upstream C++, because nearly everything goes over rcontrol instead.

When it cannot be avoided, the change is a file in `patches/` with a `### `
section in `patches/README.md` saying what and why. `tools/check_deltas.py`
enforces both directions. Sending the change upstream retires the patch, which
is always the better outcome — see `rules/upstream-sync.md` §2.

There is deliberately no pinned upstream revision. See that rule's §4.
