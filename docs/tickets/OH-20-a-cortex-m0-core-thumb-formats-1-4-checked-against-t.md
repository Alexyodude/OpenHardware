---
id: OH-20
title: 'A Cortex-M0+ core: Thumb formats 1-4, checked against the rp2040js corpus'
status: done
priority: P1
created: '2026-08-24'
touches:
- core/cortexm0/**
- tests/cortexm0/**
- pyproject.toml
---

_No description yet._

**Note 2026-08-24:** Landed: core/cortexm0/ (cpu, shift, exec, abi + ctypes binding), Thumb formats 1-4 (0x0000-0x43FF), 27 encodings, register-only and all flag-setting. Builds via tools/build_core.py with no change -- the core/*/CMakeLists.txt discovery picked it up. 13,500 oracle cases from rp2040js: 13,300 match outright.

THE OTHER 200 ARE ORACLE BUGS, NOT CORE BUGS, and are predicted rather than skipped. rp2040js has three shift-carry defects: ASRS(register) and RORS have no shift-by-zero guard (its 'C = input & (1 << (shiftN-1))' becomes '1 << -1', which JavaScript masks to '1 << 31'), and LSLS(register) computes a garbage carry for amounts > 32 by the same masking. Evidence, three independent lines: (1) ARM DDI0419 Shift_C returns carry_in unchanged at amount 0; (2) the JS semantics, demonstrated in test_the_javascript_that_produces_the_wrong_carry rather than asserted; (3) rp2040js contradicts itself -- its LSLS immediate AND register forms both guard shift-by-zero, ASRS(register) and RORS do not. All 200 divergences were verified to match the buggy expressions EXACTLY (registers identical, only C differs, oracle C == the bug's output), 0 unexplained. If rp2040js is fixed, the predictions fail and we find out.

MUTATION TESTING FOUND A REAL HOLE: breaking ASR shift-by-zero to clear the carry passed the whole corpus. Only 1 of 500 asrs_reg cases shifts by zero, and for that case the mutant's wrong answer coincides with the oracle's wrong answer. Where the oracle is buggy, agreeing with it is not evidence. Fixed by tests/cortexm0/test_shift.py -- 22 edge cases pinned to the architecture, not the oracle; the escaped mutation is now caught.

NOT RUNNABLE FIRMWARE: no loads, stores, branches or exceptions. A green conformance run is not a working dev board and the UI copy says so.

Noted, not done: gen_armv6m_tests.mjs samples shift amounts from a uniform random byte, so edges (0, 32, 33, 255) appear ~1 case in 256 -- it should bias toward them (OH-17's file). tools/inventory.py's collect_tests scopes to tests/rules only, so 'TESTS - 222 across 17 files' undercounts the repo's four suites (OH-13's file).
