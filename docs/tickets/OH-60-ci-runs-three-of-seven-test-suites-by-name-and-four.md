---
id: OH-60
title: CI runs three of seven test suites by name, and four cores are outside it
status: done
priority: P2
created: '2026-08-26'
touches:
- .github/workflows/rules.yml
- tests/rules/test_checkers_are_wired_into_ci.py
---

MEASURED 2026-08-26 while closing OH-58. .github/workflows/rules.yml runs pytest against three directories by name:

    pytest tests/i8086/ -v
    pytest tests/rules/ -v
    pytest tests/webui/ -v

tests/avr, tests/cortexm0, tests/riscv32 and tests/rv32 are in none of them. Those four are the four cores. So every core except i8086 is verified only by whoever remembers to run it locally.

CLAUDE.md says 'Bare pytest is now correct and is what CI runs'. The first half is true and the second is not: CI names three directories and bare pytest reads testpaths, which after OH-58 lists seven. The two have drifted apart and the prose describes neither.

THE RELATED HOLE IS ALREADY FIXED. tests/avr was missing from testpaths entirely, so bare pytest never ran it either; tests/rules/test_testpaths.py now guards that in both directions. This ticket is the other half -- the guard checks that a suite is in the configuration, and nothing checks that CI uses the configuration.

WHY IT MAY NOT BE A ONE-LINE CHANGE. The core suites import core.<name>.abi, which calls ensure_built and compiles C++ on demand. CI does that already for i8086, so a compiler is present; whether all four build on a GitHub runner in reasonable time is the thing to measure before promising it. If one does not, the honest outcome is a named exclusion with a reason, not a quiet omission.

Done when CI runs the same command CLAUDE.md tells a person to run, or names every exclusion and why -- and tests/rules/test_checkers_are_wired_into_ci.py checks the workflow against testpaths so the two cannot drift again.

**Note 2026-08-26:** CLOSED 2026-08-26. CI now runs bare pytest, which is the command CLAUDE.md tells a person to run -- so that claim is true for the first time. It was false in both halves: CI named three directories and testpaths names seven.

NOTHING ELSE WAS NEEDED. The ticket wondered whether all four cores would build on a runner in reasonable time. They already do: tools/build_core.py has built avr, cortexm0, i8086 and riscv32 since each landed, and CI has been calling it all along. Only the step's NAME still said 'Build the i8086 core', which is how the job looked narrower than it was. No exclusion was needed and none is recorded.

THE GUARD ACCEPTS EITHER SHAPE. test_ci_runs_every_suite_in_testpaths passes for a bare pytest -- which reads testpaths and cannot miss a suite -- or for a named list that is complete. Verified red: pointing the step at tests/rules/ alone fails it.

TOGETHER WITH tests/rules/test_testpaths.py a suite cannot fall out of the gate at either end. One guards the configuration, the other guards the workflow's use of it. Both were written this session and both were written because a suite HAD fallen out: tests/avr was absent from testpaths and nothing noticed.

SKIPS ARE THE HONEST ANSWER on a runner without avr8js, rp2040js, rvcpp or the PlatformIO toolchains. Every one of those tests names what it wanted. A suite silently not collected does not.

Gate: 1,433 passed, 17 skipped locally; all eight checkers exit 0. The CI run itself will skip more and say so.
