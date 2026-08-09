---
rule: conformance-fixtures
mechanisms:
  - tier: PARSER-ENFORCED
    checker: tools/ledger.py
    armed: true
  - tier: TEST-ENFORCED
    checker: tests/rules/test_fixtures_pass.py
    armed: false
    blocked_by: >-
      No fixtures exist yet. Requires the NOGUI build and a resolved
      PICSimLab_rcontrol dependency; spec sections 8.3 and 8.4 are open.
---

# Conformance fixtures

A feature is done when it matches an oracle within a declared tolerance. Not
when it looks right.

## 1. 2026-08-09 — PARSER-ENFORCED: every row carries six columns

`tools/ledger.py` raises `LedgerError` on any row that is not
`id · tier · oracle · tolerance · status · fixture`.

`PARSER-ENFORCED` is the dangerous tier: a parser that skips what it cannot
read deletes data silently. So this parser raises where a lenient one would
`continue`, and `test_wrong_column_count_raises` pins the difference.

## 2. 2026-08-09 — PARSER-ENFORCED: a cell with no oracle cannot be scheduled

Status `in-progress` or `done` with an empty oracle raises. Ground truth for a
simulator is always obtainable — real silicon, a reference emulator, vendor
test vectors, `ngspice` on the same netlist, datasheet timing diagrams. A cell
whose author could not name one has not been specified.

## 3. 2026-08-09 — PARSER-ENFORCED: `done` requires a fixture

An empty fixture at `done` raises. Otherwise `done` means "someone said so".

## 4. 2026-08-09 — CRITICAL: a fixture that cannot reach its oracle must fail

Upstream's `tests/python/test_blink.py` wraps its assertions in
`except ConnectionError: print(e)`. When PICSimLab is not listening, the
exception is caught, nothing is asserted, and **the test passes**. A suite of
such tests reports green on a machine where the simulator never started.

Never catch a connection or setup failure around an assertion. An unreachable
oracle is a failure, not a skip, and never a pass.

This is why every checker in this repository raises on empty input rather than
returning an empty result — the same defect wearing different clothes.

## 5. 2026-08-09 — CONVENTION: most cells ship at F0

The failure mode is not shipping low fidelity. It is shipping low fidelity
while implying high. Declare `F0` and move on; promote a cell only when a
fixture and oracle justify it.
