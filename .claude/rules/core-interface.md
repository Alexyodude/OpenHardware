---
rule: core-interface
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_layering.py
    armed: true
  - tier: CONVENTION
    checker: null
    armed: false
---

# Core interface

A new CPU architecture is a `bsim_*` pair under `src/sim_backend/` implementing
the contract declared as pure virtuals in `src/lib/board.h`. Rules are labelled
**SCRIPT-ENFORCED** or **CONVENTION**:

> Breaking the enforced rule fails CI. Breaking a convention only hurts whoever
> reads the code next.

## 1. 2026-08-09 — SCRIPT-ENFORCED: backends may not include parts or UI

`tools/check_layering.py` scans every source file in `src/sim_backend/` for
`#include` targets containing `parts/` or `lxrad`, or matching `picsimlab\d`.
Any hit exits non-zero.

Measured at `fork-point` (`cd92747`): **15 files in `src/sim_backend/`, zero
violations.** The baseline is clean, so this rule never needed an exemption
list, and `test_real_sim_backend_is_clean` pins that.

The permitted dependencies are the ones upstream already uses —
`../lib/board.h`, `../devices/*`, `../lib/serial_port.h`, and engine headers
such as `<simavr/avr_adc.h>`. A backend that reaches into `parts/` stops being
swappable, which is the entire property the `bsim_*` seam provides.

## 2. 2026-08-09 — SCRIPT-ENFORCED: an empty scan is an error

`find_violations` raises `ValueError` when the directory holds no source files.
A checker that passes because it found nothing to check reports the same green
as a checker that verified 15 files, and the two are indistinguishable in CI
output. `test_empty_directory_raises` pins it.

## 3. 2026-08-09 — CONVENTION: implement the whole board contract

`src/lib/board.h` declares the pin API as pure virtuals — `MSetPin`,
`MSetPinDOV`, `MSetAPin`, `MSetPinOAV`, `MGetPin` — plus the `MInit`/`MEnd`/
`MStep`/`MReset` lifecycle and the `DBG*` debug accessors. C++ enforces that
they exist. Nothing enforces that they are *correct*, and a backend that stubs
`MSetAPin` to a no-op compiles, links, runs, and silently produces a dead
analog pin.

Not enforced here because correctness per method is what
`.claude/rules/conformance-fixtures.md` covers, one ledger cell at a time.
