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
python tools/check_ticket_claims.py
pytest
```

Or all of it in one command, plus the ticket guard's self-test and the facts
check: `python tools/checkall.py`. That runner refuses to start if a checker
armed in `rules/` is missing from its table, and `--prove` prints how to break
each row — a check that has never failed is evidence of nothing.

Bare `pytest` is now correct and is what CI runs. `pyproject.toml` sets
`--import-mode=importlib` and points `testpaths` at the seven suites.

The old instruction here was the opposite — "never run bare `pytest` from the
repo root", because upstream's `tests/python/` was in the tree and imported an
out-of-tree module. That tree is gone.

The first three checkers need a PICSimLab **source** checkout and will skip
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

A board then draws a vendor file instead of an extruded footprint wherever
one exists -- the vendor's own mechanical model, or one composed from a
published PCB -- and the pin panel says which of the three things it is
showing. **Which boards draw which is printed, not written here.** This
paragraph carried the counts, and the first board added through
`tools/board_manifest.py` made them wrong:

```bash
python tools/inventory.py      # TWINS: the model column, per board
```

`XIAO-XIAO STM32C5-SMD` has
no page on the vendor's wiki at all -- see `docs/research/board-models/`,
whose §5 also records that the same document twice said a board could not be
drawn when the vendor was publishing its PCB the whole time. The meshes are
gitignored -- see
`tools/import_3d_model.py` for the licence reason -- so a fresh checkout gets
the footprint until this is run.

**The last command is for a board whose vendor publishes no mesh at all**, and
the Arduino Uno is the one that does. It stands KiCad's published component
models on the outline and placements in Arduino's own EAGLE board file, so the
board draws with its notch, its DIP-28, its four headers, its barrel jack and
its USB socket without a height or a position being invented anywhere. It needs
the vendor's `.brd` and `.sch` from the same CAD zip -- the schematic says what
each passive is (OH-191) -- which `python tools/get_board_sources.py arduino-uno`
prints the URL for -- an `https-archive`, so it is downloaded by hand, as the
Pico's is.

**A composed board draws its own copper, its own routing and its own
silkscreen**, and until OH-110 and OH-112 it drew none of them -- which is why
it looked like a slate with boxes on it beside a vendor's own assembly export.
Every pad is the vendor's size at the vendor's angle, every stroke their line
at their width, and copper is cut to the board's edge so a castellated
half-hole is half a hole.

A trace is drawn in that board's **own mask colour lifted**, not in copper: a
trace is under a translucent film with something brighter behind it, so what
changes is lightness and not hue. Blending toward copper instead turned the
Uno's navy into a neutral grey, which is the picture that found the bug.

**A KiCad board's silkscreen text is drawn** (OH-163), in newstroke, the
stroke font KiCad plots with, read from its author's own CC0 archive, which
a run of the composer fetches as it fetches the meshes and pins by size and
sha256 (KiCad's own copy of the font carries a GPL header, so it is never
the source), and held to two vendors' own silkscreen Gerbers.

What is NOT drawn is counted and printed: text the stroke font cannot draw
as the vendor plotted it -- a TrueType face, knockout text, and every EAGLE
board's text, which EAGLE plots in a vector font built into its executable;
the shapes on that layer the composer cannot draw yet, which `--check` names
per board by kind (a KiCad board's silkscreen arcs are drawn since OH-163);
**inner copper layers**, which are inside the laminate where nothing can see
them; and a zone's **filled polygon**, which is a keyhole outline walking into
every thermal relief and back out. One gap is not counted yet: a board's own
milled holes, which neither reader reads (OH-163). The colours are judgements and say so, as
`BOARD_MASK` does: six of Seeed's seven board files carry a full `(stackup
...)` -- six copper layers with thicknesses, five FR4 dielectrics with their
`epsilon_r`, both solder masks with a thickness -- and not one of them fills in
the mask's colour or asks for a copper finish. That is where KiCad records
both, so a vendor who completed that table and left those fields alone did not
state either.

**The one colour a vendor's file DOES carry that is overridden** is the
nRF54LM20A's (OH-99). Its STEP is the only one of six that exports the solder
mask as its own body -- two loose faces with the board's footprint to 0.0000
mm, lying 0.05 mm off each of its faces -- and the exporter painted them green
while the board under them drew `BOARD_MASK`. One missing fact answered two
ways in one mesh is the defect; `is_mask_film` identifies the film by shape and
never by colour, which is what makes repainting it safe.

**Which way round a part goes is checked against the vendor's own pin-1
marker** (OH-106), because a half turn is what every other check survives: a
span does, and so does a body centre. So `mark_turns` reads the marker out of
the footprint -- EAGLE's curved silkscreen wire, KiCad's `fp_circle` on
`F.Fab` -- and asks where the model's own asymmetric feature lands, which it
finds by seeing which of its vertices a half turn moves. Neither side is a
table written here, and the feature is never named: on the Arduino's DIP-28 it
is the notch in the top of the body, and the rule would hold as well for a
bevel. This paragraph used to count the packages that qualify and the margin
the closest turn wins by; the counts went stale as boards were added, and
nothing printed them, so they are gone rather than moved.

**A half turn that moves nothing is not a claim that can be wrong.** The
placements that a half turn does move and that nothing here can check are
listed per board by `python tools/compose_board_3d.py --check` (which needs
`cadquery-ocp`), on a `turn` line, the same way unread silkscreen is; a board
with none prints no such line.

**And the underside is lit** (OH-111), because that is where a XIAO's pin
names, its battery pads and the words "Seeed Studio" are printed. One light
from below, not casting, its share added to `LIGHT_TOTAL` rather than taken
out of the three above -- a light from below cannot brighten a surface facing
up, and the sweep that set its intensity moved the topside mean by 0.7%.

**Geometry has four sources here and the page names which one it is showing.**
In order of preference: the vendor's own mechanical model; a published model of
the same package, from KiCad's `kicad-packages3D`; the manufacturer's own STEP;
and last, a mesh built in Blender by `tools/model_from_datasheet.py` because
nothing published exists.

**What is in that last category, and why each of its numbers is defensible, is
printed rather than listed here** — the count has been wrong in this file twice:

```bash
python tools/model_from_datasheet.py --list      # every part, and its citations
python tools/model_from_datasheet.py --check     # what it reads, building nothing
```

There are four shapes of modelled part and they are separate types rather than
one with a flag, because they share a sentence and not a shape: `SPECS` reads an
EAGLE package for a through-hole connector, `PACKS` a KiCad footprint for a flat
pack, `SLABS` a moulded body whose height is the last field of its footprint
NAME, and `SOCKETS` a receptacle whose whole envelope the vendor states in the
footprint's own `Description` property. Every dimension in each is either read
out of the vendor's file at build time or carries a citation beside it, and
`test_every_modelled_dimension_cites_where_it_came_from` is what holds that.

Two of those citations are the same argument and it is worth knowing: the Uno's
USB-B shell height and the XIAO's USB-C opening are the **USB specification's**,
because a cable from any maker has to enter a socket from any other. Everything
else is arithmetic on a vendor's own body.

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
