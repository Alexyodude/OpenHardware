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
      Narrowed again 2026-08-12, because the previous text had gone stale and
      described a world that no longer exists. RESOLVED since it was written:
      the PICSimLab_rcontrol dependency (this fork has webui/rcontrol.py), and
      the spare-parts blocker -- part assets are NOT absent, they resolve via
      the share/picsimlab symlink (known-issues 4a.2), and twelve peripherals
      have since been placed, wired and round-tripped against a live 0.9.3.
      Fixtures now exist and pass: tests/webui/test_live_oracle.py backs
      fourteen done cells under OPENHARDWARE_LIVE=1. What blocks ARMING is
      narrower and different -- CI has no simulator, so a test that runs the
      fixtures would either fail every CI run or skip, and section 4 forbids
      the skip. Arming needs a PICSimLab in the workflow. Still unresolved and
      unrelated to arming: writes remain unobservable (set pin[] does not move
      get pin[], and a part input reads back 16 whether 0 or 1 was written),
      so fixtures prove configuration, not conduction.
  - tier: SCRIPT-ENFORCED
    checker: tools/check_part_schemas.py
    armed: true
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

## 6. 2026-08-10 — SCRIPT-ENFORCED: a schema must cite a checkable line

`tools/check_part_schemas.py` requires every part schema's `source` to name a
file that exists and a line within it.

A part's config string is positional and the simulator will not explain it
(`src/lib/part.h` offers name-to-id lookup only), so each schema is authored by
reading that part's `WritePreferences`. A wrong schema does not raise — it
writes a valid-looking config that wires the circuit incorrectly and reports
success. The citation is what makes a schema auditable, so a citation nobody
can follow is treated as no citation at all.

`find_problems` raises on an empty directory, for the reason section 2 gives.

## 7. 2026-08-12 — CONVENTION: no cell in this repository is hardware-validated

Asked directly whether the boards were bare-metal verified, the answer was no,
and it is worth writing down rather than rediscovering.

**Every oracle this project uses is software.** Counted across both ledgers on
2026-08-12: `rcontrol` (the protocol), `sim-state` (the simulator itself),
`pzw`, `network-log`, `board.h`, and the Intel manual. Not one is a
measurement taken from a running chip.

`sim-state` is the one most easily over-read. It means *the UI agrees with the
simulator* — an LED lights in the browser when PICSimLab says that pin is
high. It says nothing about whether PICSimLab agrees with an ATmega328P.

Two consequences follow, and neither is a defect to fix:

- **The simulation cores are inherited untested.** `simavr`, `picsim` and
  `ucsim` are upstream's. Whatever accuracy they have is upstream's claim, not
  a measured property of this repository, and no test here examines it.
- **The one hardware-derived oracle is unstarted.** `SingleStepTests/8088` is
  genuine silicon ground truth, captured per-cycle from a real AMD 8088. It
  backs 31 cells in `docs/features/i8086.md` and **all 31 are `planned`**.

So the standing rule: a cell may claim what its oracle can see and nothing
further. Do not describe a board as working, accurate, or verified without
naming which of the software oracles above said so. When hardware validation
does happen it earns a new oracle name and an `F1` or better tier — see
section 5 on why declaring low fidelity is never the failure mode.

Not enforced by a script. A checker could plausibly reject an oracle string
naming hardware when no fixture reaches one, but there is no such oracle in
either ledger yet, so the checker would guard nothing — section 2's hazard
seen from the other side.
