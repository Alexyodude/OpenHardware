---
id: OH-60
title: CI runs three of seven test suites by name, and four cores are outside it
status: open
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
