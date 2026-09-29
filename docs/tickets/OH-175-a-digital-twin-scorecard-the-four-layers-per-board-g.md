---
id: OH-175
title: 'A digital-twin scorecard: the four layers per board, generated, so every board
  has a number'
status: open
priority: P1
created: '2026-09-29'
touches:
- tools/inventory.py
- tests/rules/test_inventory.py
---

Part of the digital-twin program ticket. Without a number, "every board is a twin" cannot be tracked, and CLAUDE.md forbids writing one down by hand.

Add a TWINS section to `python tools/inventory.py` (and its `--markdown` form): one row per board in webui/boards/, one cell per layer the program ticket defines (geometry, model, pins, runs), and a summary line of how many boards hold all four.

Each cell is computed by the code that already owns the fact, not re-derived:

- geometry: the board file's `source` names a vendor CAD file. Say which, and say when it does not.
- model: whatever the 3D panel would draw for this board on this disk: vendor mesh, composed, or footprint. The meshes are gitignored, so "not built on this disk" and "cannot be built" are different answers and must read differently.
- pins: non-supply pads naming a `chip_pin`, of all non-supply pads. Supply pads are excluded by whatever rule tools/import_pindefs.py already uses; do not write a second one.
- runs: the chip's `FIRMWARE_VERIFIED` entry, via webui/boards/catalogue.py.

Before trusting it, measure one thing: the existing ASSETS section prints model3d `absent` for all 25 XIAO boards while CLAUDE.md says 25 of 26 draw a vendor or composed model once the import tools run. Find out whether ASSETS is answering a different question or is wrong, and record which, with the evidence.

Done when the section is generated from the filesystem, adding a board with no model shows up as no model without anyone editing the report, and each cell has been made to fail on purpose once (rename the mesh, blank a chip_pin, drop the chip from FIRMWARE_VERIFIED in a temp copy). No @pytest.mark.parametrize, per CLAUDE.md.
