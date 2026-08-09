# Feature ledgers

One file per area, each a markdown table parsed by `tools/ledger.py`.

| id | tier | oracle | tolerance | status | fixture |
|---|---|---|---|---|---|
| i8086.mov.reg | F0 | Intel 8086 ISA manual, table 2-21 | exact | planned | - |

- **tier** — `F0` functional, `F1` timing-approximate, `F2` cycle-accurate,
  `F3` electrically-accurate.
- **oracle** — the external source of truth. Required before a cell may leave
  `planned`.
- **tolerance** — `exact`, or a numeric bound such as `abs=2`.
- **status** — `planned`, `in-progress`, `done`.
- **fixture** — path to the conformance test. Required at `done`.

Ledgers are emitted by the `feature-strategy` skill, not written by hand.
