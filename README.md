# OpenHardware

A browser front-end and conformance harness for
[PICSimLab](https://github.com/lcgamboa/picsimlab).

Place peripherals on a board, drag wires between real header pins in a 3D
view, and watch live simulator state — in a browser, over loopback, with no
CDN and no build step. Underneath, a rules engine that refuses to let a check
pass without having actually checked something.

> **Status: early.** The web UI runs against a real simulator. The x86-16 core
> is planned, not written. See `docs/features/` for per-feature ledgers, and
> `docs/known-issues.md` for what is knowingly weak.

## This is not a fork of PICSimLab

PICSimLab is a separate program. OpenHardware speaks to it over its
**rcontrol TCP socket** and reads the board artwork it already ships. No
upstream source is vendored here; `git ls-files src share` returns nothing.

That distinction is enforced, not just claimed —
`test_no_upstream_source_is_tracked_here` fails if upstream's tree ever
reappears.

This repository is **MIT**. `patches/`, which holds our one diff against
upstream's C++, is GPL-2-or-later, because a diff against GPL source is a
derivative of it. `PROVENANCE.md` audits every file and explains why the rest
is not.

## Getting started

You need Python 3.11+, a PICSimLab install, and a checkout of upstream if you
want to run the rule checkers.

```bash
git clone <this repo> OpenHardware
git clone https://github.com/lcgamboa/picsimlab picsimlab-reference
cd OpenHardware
pip install pytest PyYAML websockets
pytest
```

`docs/picsimlab-reference.md` covers where PICSimLab is looked for and what
happens when it is not there.

### Running the UI

Start PICSimLab with rcontrol enabled on port 5000, then:

```bash
python webui/run_local.py
```

The bridge binds loopback only, checks `Origin`, and exposes an explicit
operation allowlist rather than passing raw protocol text through — a
websocket on localhost is reachable by any page you visit.

## What is in here

| directory | what |
|---|---|
| `webui/` | the browser front-end, its Python API, and the rcontrol client |
| `tools/` | rule checkers, the inventory generator, the 8088 corpus reader |
| `tests/rules/` | tests for the checkers |
| `tests/webui/` | tests for the UI, against a stub simulator |
| `patches/` | our changes to PICSimLab, as diffs |
| `rules/` | the rules, each naming the checker that enforces it |
| `docs/features/` | per-feature ledgers; `docs/known-issues.md` is the honest list |

```bash
python tools/inventory.py     # computed, never claimed
```

## Boards

Board definitions live in `webui/boards/` as JSON pad maps, each XIAO's beside
an SVG outline. They are imported from vendor CAD by `tools/import_board.py`;
pad centres are exact to three decimal places in millimetres, and nothing is
measured off an image.

**Only the first group below is wired to the simulator.** The rest draw to
scale and deliberately refuse connections: a pad whose `pin` is null has no
simulator pin index, and a guessed one would wire the circuit wrongly *and
report success*. Each board file says so in its own `assumption` field.

**"Wired" here means that one field and nothing else.** Since OH-160 every
board file also carries a `chip_pin` — the MCU pin the vendor's own
board-support package says each label reaches — and on the eleven files whose
chip has a board module, a running program's pin levels are reported through
the same table. So a board in the second group below is not a board that can
do nothing; it is a board with no PICSimLab pin index, which is a different
join with a different count. `python tools/import_pindefs.py --all --summary`
prints that one.

Wired to the simulator:

- `Arduino Uno`

Outline and pad labels only, not yet wired:

- `XIAO-ESP32-C3-DIP` · `XIAO-ESP32-C3-DIP-SMD` · `XIAO-ESP32-C3-SMD`
- `XIAO-ESP32-C5-DIP` · `XIAO-ESP32-C5-SMD`
- `XIAO-ESP32-C6-DIP` · `XIAO-ESP32-C6-SMD`
- `XIAO-ESP32-S3-DIP` · `XIAO-ESP32-S3-SMD` · `XIAO-ESP32-S3-SMD_PAD`
- `XIAO-MG24-DIP` · `XIAO-MG24-SMD`
- `XIAO-RP2040-DIP` · `XIAO-RP2040-SMD`
- `XIAO-RP2350-DIP` · `XIAO-RP2350-SMD`
- `XIAO-SAMD21-DIP` · `XIAO-SAMD21-SMD`
- `XIAO-XIAO STM32C5-SMD`
- `XIAO-nRF52840-DIP` · `XIAO-nRF52840-SMD`
- `XIAO-nRF54LM20A-DIP` · `XIAO-nRF54LM20A-SMD`
- `XIAO-nRF54l15-DIP` · `XIAO-nRF54l15-SMD`
- `SparkFun Thing Plus ESP32-C6`, pad labels only: no SVG outline is generated for it
- `Adafruit QT Py ESP32-C3` · `Adafruit Feather ESP32-C6`, pad labels only, the same way

All XIAO artwork is Seeed Studio's, MIT, from
[OSHW-XIAO-Series](https://github.com/Seeed-Studio/OSHW-XIAO-Series).

A board that is not a XIAO is a row in `tools/board_manifest.py`: its CAD
file, the elements carrying its header, its chip, and the board-support
variant that names its pins. `python tools/board_manifest.py` writes its file
from that row, and writes no SVG beside it.

This list is not maintained by hand.
`test_readme_board_list_matches_the_directory` fails if it drifts from
`webui/boards/`, and `python tools/inventory.py` prints the pad and wiring
counts — which are deliberately *not* written down here, for the reason the
rest of this file gives.

## The rules engine

Each file in `rules/` declares mechanisms with a tier
(`SCRIPT-ENFORCED`, `PARSER-ENFORCED`, `TEST-ENFORCED`) and whether it is
`armed`. `tests/rules/test_checkers_are_wired_into_ci.py` fails if an armed
script-enforced rule has no `run:` line in CI, so a rule cannot claim
enforcement it does not have.

The recurring theme is refusing vacuous passes:

- A checker with nothing to scan **raises**, rather than reporting clean.
- A checker that needs upstream source and cannot find it **exits 3**, not 0.
- `check_deltas` flags orphaned documentation as well as undocumented patches,
  because stale docs read as current.
- `check_licenses` asserts the *presence* of the right licence, after an
  earlier version could be satisfied by a file with no header at all.

## Credits

[PICSimLab](https://github.com/lcgamboa/picsimlab) © Luis Claudio Gambôa
Lopes, GPL-2-or-later. This project exists to serve it and is useless without
it.

[three.js](https://threejs.org) © three.js authors, MIT — the 3D board view.

[SingleStepTests/8088](https://github.com/SingleStepTests/8088) © Daniel
Balsom, MIT — hardware-captured 8088 conformance data.

## Licence

MIT, except where noted. See `LICENSE` and `PROVENANCE.md`.
