---
id: OH-206
title: A board's chip is proposed from its own board file, by the datasheet and not
  the vendor's spelling, and checked against the eleven manifest rows
status: open
priority: P1
created: '2026-10-08'
touches:
- tools/propose_board.py
- tests/rules/test_propose_board.py
---

Slice S1 of OH-205's ledger (docs/features/intake.md): intake.chip.by-value, intake.chip.module-to-soc, intake.chip.supply-pins-confirm. A board's chip proposed from its own board file alone, scored against the eleven rows of tools/board_manifest.py. Demo: `python tools/propose_board.py --check` prints one line per row, `match` or the field that differs.

WAITING ON THE USER: .claude/CLAUDE.md rule 2 -- the shape below must be confirmed before any body is written. Full shape and call stack: docs/superpowers/plans/2026-10-08-intake.md section 8.

Files: tools/propose_board.py (new), tests/rules/test_propose_board.py (new). tools/board_manifest.py and tools/import_pindefs.py are read, not changed.

Signatures: `Datasheet(soc, stem, table)` -- one per datasheet, built by grouping the existing PinTables on (url, pdf_sha256), six today against eleven vendor keys. `Placed(reference, package, value, pads)`. `Identified(placed, datasheet, confirmed_by)`. `placed_parts(path) -> tuple[Placed, ...]` over eagle.read_board or kicad.read_board by extension. `normalise(spelling) -> str` (soft hyphens out, `_` read as `-`, case-folded). `identify(parts, datasheets) -> Identified`, raising with every candidate and why each failed when there is not exactly one. `check(rows) -> int`: 0 all match, 1 any differs, 3 a source not fetched, saying SKIPPED.

Least confident, for the user to rule on:
1. Matching the value by normalised prefix. The Feather C6's value is `ESP32-C6-MINI_MINI`, so the stem must stop at `ESP32-C6-MINI`; a tail board whose value is `~` defeats it.
2. Grouping the PinTables rather than merging them (rule 7: leave copies until three change together).
3. Confirming identity by net identity (all ground pads on one net), not by the net name `GND`; a net-tie between grounds would fail honestly.
4. Whether eleven careful vendor boards are a fair key for hobbyist KiCad boards; that is measured only in S5, which has no oracle.
