# Feature ledger — board intake at catalogue scale

Derived by the `feature-strategy` skill on 2026-10-08 for OH-205. Parsed by
`tools/ledger.py`; see `docs/features/README.md` for column meanings.

Strategy, Phase 0 evidence and the slice order live in
`docs/superpowers/plans/2026-10-08-intake.md`. What heypcb.ai did, which this
ledger answers, is in `docs/research/heypcb/README.md`.

Intake is everything between "a public repository exists" and "a row of
`tools/board_manifest.py` describes the board in it". Today a person writes
that row. Every cell here is one field of it, proposed from the vendor's own
files instead.

Oracle shorthand:

- **manifest** — the eleven rows of `tools/board_manifest.py` at `393d452`.
  Each was written by hand against the vendor's own files and is checked by
  `tests/rules/test_board_manifest.py`. They are an answer key, not ground
  truth: where a proposal and a row disagree, the vendor's file is opened and
  decides, and either side may be the one that is wrong.
- **boards.txt** — the vendor's own Arduino board package, which states the
  chip a variant builds for (`build.mcu` in arduino-esp32, `build.chip` in
  arduino-pico). It is written by people who did not write the CAD, so it can
  disagree with the CAD's value field, which is what makes it an oracle.
- **datasheet** — the pin table a `PinTable` already cites, with the PDF's
  hash: which numbered pads are ground and supply.
- **licence-api** — the host's own statement of a repository's licence
  (GitHub's `repos/{owner}/{repo}` `.license`) together with the tree listing,
  so "none declared" is a finding over a complete listing and not a fetch
  that failed.

`F1`–`F3` describe timing and electrical fidelity, which a board's
description does not have; every cell is `F0`, as in `docs/features/webui.md`.

Two cells have no oracle and stay `planned`: a search has no ground truth for
what it should have found, and a histogram is only as true as the
identification under it. heypcb.ai's counts are a comparison for both, not an
oracle — they come from the authors' own words.

Only one table may appear in this file: `tools/ledger.py` parses every
pipe-delimited row it finds.

| id | tier | oracle | tolerance | status | fixture |
|---|---|---|---|---|---|
| intake.chip.by-value | F0 | manifest: the chip of each row's `pin_table`, 11 rows | exact | planned | - |
| intake.chip.module-to-soc | F0 | datasheet: the module datasheet each `PinTable` cites names its SoC | exact | planned | - |
| intake.chip.supply-pins-confirm | F0 | datasheet: every ground and supply pad of the identified part lands on one ground and one supply net | exact | planned | - |
| intake.chip.agrees-with-variant | F0 | boards.txt: `build.mcu` or `build.chip` of the joined variant names the identified chip | exact | planned | - |
| intake.find.board-file | F0 | manifest: `cad`, 11 rows | exact | planned | - |
| intake.find.schematic | F0 | manifest: `schematic`, the 6 rows that name one | exact | planned | - |
| intake.variant.join | F0 | manifest: `package` and `variant`, 11 rows | exact | planned | - |
| intake.headers.select | F0 | manifest: `select`, 11 rows | exact | planned | - |
| intake.licence.statement | F0 | manifest: `licence_statement`, the 2 rows that carry one | exact | planned | - |
| intake.licence.refuse-undeclared | F0 | licence-api: no licence declared and no licence file in the complete tree listing | exact | planned | - |
| intake.reasons.unreached-pad | F0 | manifest: the 9 `reasons`, by the net and the part each names | exact | planned | - |
| intake.row.whole | F0 | manifest: all 11 rows, field for field | exact | planned | - |
| intake.fetch.sparse | F0 | licence-api tree listing: only the board file, its schematic and the licence file are fetched | exact | planned | - |
| intake.search.host | F0 | - | - | planned | - |
| intake.demand.chip-histogram | F0 | - | - | planned | - |
