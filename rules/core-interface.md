---
rule: core-interface
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_layering.py
    armed: true
  - tier: SCRIPT-ENFORCED
    checker: tools/check_board_contract.py
    armed: true
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

## 3. 2026-08-09 — SCRIPT-ENFORCED: a board pair must cover the whole contract

`src/lib/board.h` declares the pin API as pure virtuals — `MSetPin`,
`MSetPinDOV`, `MSetAPin`, `MSetPinOAV`, `MGetPin` — plus the `MInit`/`MEnd`/
`MStep`/`MReset` lifecycle and the `DBG*` debug accessors. **42 in total**, and
a concrete board covers them across two halves: a `bsim_*` supplying the
simulation surface and a `board_*` supplying the UI surface.

`tools/check_board_contract.py` asserts the union of a pair declares all 42.

A C++ compiler does this better, and where one is available it should be
trusted over a regex. This checker exists because a toolchain is not always
available — this fork's development machine has none, and CI cannot build until
the probe in `.github/workflows/nogui-probe.yml` succeeds. It is validated
against `bsim_ucsim.h` + `board_uCboard.h`, an upstream pair that demonstrably
compiles, so a failure there means the checker is wrong rather than the code:
`test_upstream_reference_pair_covers_the_whole_contract` pins it, and
`test_the_real_contract_is_the_expected_size` fails if the count of 42 ever
changes.

`contract_methods` raises when it finds no pure virtuals at all. An empty
contract would make every pair pass — section 2's hazard wearing different
clothes.

## 4. 2026-08-09 — CONVENTION: coverage is not correctness

Section 3 proves every method is **declared**. Nothing proves any of them is
**right**. A backend that stubs `MSetAPin` to a no-op covers the contract,
compiles, links, runs, and silently produces a dead analog pin.

Never report a passing `check_board_contract.py` as evidence that a backend
works. Correctness per method is what `rules/conformance-fixtures.md`
covers, one ledger cell at a time.
