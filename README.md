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
