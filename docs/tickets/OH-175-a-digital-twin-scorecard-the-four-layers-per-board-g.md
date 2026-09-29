---
id: OH-175
title: 'A digital-twin scorecard: the four layers per board, generated, so every board
  has a number'
status: in-review
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

**Note 2026-09-29:** 897cdd0 adds TWINS to `python tools/inventory.py` and `--markdown`; dd2afed makes ASSETS say what its model3d is. Measured 2026-09-29 on branch oh-175.

TWINS, as this worktree prints it: "TWINS — 0 of 26 boards hold all four; by layer: geometry 25, model 0, pins 15, runs 12". The model layer is 0 here because webui/static/models is a junction into the main checkout, and `resolve_static` refuses a path that resolves outside static/, so this worktree's server would serve no mesh and the page would draw footprints. With the same models copied into a plain temp static dir: "TWINS — 7 of 26 boards hold all four; by layer: geometry 25, model 25, pins 15, runs 12". The seven are XIAO ESP32-C3-DIP, -DIP-SMD, -SMD, ESP32-C5-DIP, ESP32-C6-DIP, RP2040-DIP and SAMD21-DIP. The Uno misses only geometry (no `source`); XIAO-XIAO STM32C5-SMD is the one `footprint:no source`.

Supply rule: tools/import_pindefs.py has none. It resolves `D<n>` and named extras, and GND gets the same generic why_null as MTMS. The only list is OH-170's SUPPLY_LABELS in tests/rules/test_import_pindefs.py, which inventory reads by ast, applying that test's predicate. Where it should live is OH-172's question. import_pindefs.py is OH-176's claim.

ASSETS model3d is answering a different question, and it is not wrong. It searches only third_party/seeed-xiao (OSHW-XIAO-Series @ f07e6ff: 675 indexed paths, 13 with a 3D suffix, all .stl parts of one community clock case, none named for a board). The meshes the page draws come from third_party/seeed-3d (the vendor STEPs from files.seeedstudio.com, 6 chips, 13 boards) and from third_party/seeed-pcb/*.kicad_pcb plus the Uno's .brd (12 composed), and ASSETS never searches either one. With the models served, TWINS counts 25: 13 vendor and 12 composed.

Failed on purpose, in temp copies: renamed RP2040.glb -> `footprint:not built`, "/models/RP2040.glb is not served; python tools/import_3d_model.py --all builds it". Blanked D0's chip_pin on ESP32-C6-DIP -> pins 10/11, "none on D0". Dropped ESP32-C6 from FIRMWARE_VERIFIED -> runs `ESP32-C6:no`. Removed `source` -> geometry `none`. A non-XIAO board with no model or pindefs -> a row missing model, pins and runs, with no crash. Seven mutants of inventory.py were each killed by a test.

Full pytest: 2 failed, 2123 passed, 31 skipped. The 2 failures are test_import_3d_model's lens and weld tests, `No module named 'OCP'`, and they fail identically at f77cfc4. check_ticket_claims OK.

**Note 2026-09-29:** Review fixes (REQUEST CHANGES, 8 items), measured 2026-09-29. Commits b4656d3, 142d7b0 and 410c08e.

New headline, as this worktree prints it: "TWINS — 0 of 26 boards hold all four; by layer: geometry 25, model 0 (25 not built here), pins 21, runs 12". The models are not served here because of the junction. With the same models copied into a plain static dir: "TWINS — 9 of 26 boards hold all four; by layer: geometry 25, model 25, pins 21, runs 12". The review's 9 is confirmed: RP2040-SMD and SAMD21-SMD join, because their SWD pads carry specific reasons.

Pins reading: a non-supply pad answers with a `chip_pin` or a specific `why_null`. It fails on `import_pindefs.NOT_PUBLISHED`, which is imported, or on no reason. Geometry now resolves: `source.file` must be a file, `source.footprint` must be a .kicad_mod found by name or by declared name. STM32C5 resolves through `XIAO-STM32C5-SMD.kicad_mod`. Each has a `:not fetched` / `:names nothing` split.

Duplication: `inventory.is_supply` copies the condition test_import_pindefs.py's counting test applies to SUPPLY_LABELS. test_inventory_calls_supply_exactly_the_pads_test_import_pindefs_does evaluates that condition, read by ast, against every pad and five probe labels. tools/DUPLICATION.md is claimed by OH-149, so the copy is recorded here rather than there. It ends when OH-172 moves the rule into a tools module.

Mutants: the review's five (whole = len(twins), inverted tallies, reversed sort, no text rows, no markdown rows) are each killed, along with 20 more over every layer, the supply parser and the heading. That is 25 of 25.

Full pytest: 2 failed, 2129 passed, 31 skipped. The two are the same `No module named 'OCP'` tests in test_import_3d_model.py that fail at f77cfc4. check_ticket_claims OK.
