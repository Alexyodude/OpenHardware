---
id: OH-270
title: Armv6-M executes UDF (0xDE00-0xDEFF) as a branch rather than stopping
status: open
priority: P2
created: '2026-11-05'
---

Found 2026-11-05 under OH-64. core/cortexm0/exec.cc decodes Format 16, the conditional branch, as (encoding & 0xF000) == 0xD000 -- which takes 0xDE00-0xDEFF too, so UDF #imm8 runs as a branch on condition 0xE, which condition_holds treats as always. The architecture makes 0xDExx permanently undefined: a real Cortex-M0+ takes a HardFault. GCC emits udf for __builtin_trap, so an RP2040 or SAMD21 image that traps branches somewhere instead of stopping and naming the address. SVC (0xDFxx) is caught before Format 16 and is not affected.

OH-64 refuses UDF only under the Armv7E-M profile (the guard beside the IT checks in exec.cc), and left Armv6-M as found because changing it moves the behaviour the M0+ suites pin; the m4 vectors' 'udf #0' case in tests/cortexm0/test_thumb2_exec.py covers the M4 half only.

Done when: under Armv6-M, 0xDE00-0xDEFF returns Unimplemented with the PC at the instruction, as the Armv7E-M path does; a test in tests/cortexm0 is red on the old behaviour; the M0+ suites still pass. exec.cc is OH-64's until it lands.
