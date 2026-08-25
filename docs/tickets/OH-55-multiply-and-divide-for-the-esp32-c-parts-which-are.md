---
id: OH-55
title: Multiply and divide for the ESP32-C parts, which are all RV32IMC
status: done
priority: P1
created: '2026-08-25'
touches:
- tests/rv32/corpus/rv32m_op.json
- tests/riscv32/test_rv32m.py
- core/riscv32/exec.cc
- tests/rv32/test_gating.py
- tests/riscv32/test_extension_gating.py
- tests/riscv32/test_lockstep.py
- tests/riscv32/test_rv32i.py
- tests/riscv32/encode.py
avoid:
- core/riscv32/exec.cc
---

Eight instructions: mul, mulh, mulhsu, mulhu, div, divu, rem, remu. core/riscv32/cpu.h:56 records kExtM as "classified and then refused", so an ESP32-C part is told it has M and then trips over the first mul.

A blink does not need them -- the measured C3 image in OH-54 contains none -- so this is deliberately NOT the blocker and is filed after it. What needs them is any real firmware, and the C3, C5 and C6 are all RV32IM(A)C.

tests/rv32/corpus/rv32m_op.json already holds 128 cases, generated from rvcpp's own table. The verification is therefore mostly written; the implementation is the gap.

THE PART THAT IS NOT ARITHMETIC. RISC-V defines division by zero and signed overflow rather than leaving them undefined, and a model that inherits the host's behaviour gets a SIGFPE or a wrong answer instead:
  div  x/0  -> -1 (all ones)      divu x/0 -> 2^32-1
  rem  x/0  -> x                  remu x/0 -> x
  div  INT_MIN / -1 -> INT_MIN    rem INT_MIN / -1 -> 0
The last is the one that traps in C++: INT_MIN / -1 overflows signed division and is undefined behaviour in the host language, so it must be special-cased before the divide, not after. These four rows are the acceptance criteria, not a footnote.

mulh/mulhsu/mulhu need the high 32 bits of a 64-bit product with three different signednesses, which is where the other easy defect lives -- mulhsu is signed x unsigned and is the one every implementation gets wrong first.

Avoids core/riscv32/exec.cc while OH-54 holds it; this ticket claims its tests now and takes the exec paths when OH-54 closes.

Done when all eight agree with rvcpp in lockstep, the six defined edge cases above are asserted by name, and gating still refuses them on a part told it has no M.

**Note 2026-08-25:** Delivered. All eight -- mul, mulh, mulhsu, mulhu, div, divu, rem, remu -- in one funct7 branch, with the six defined edges answered BEFORE any divide happens rather than after.

That ordering is the whole of it. RISC-V defines division by zero and signed overflow; C++ calls both undefined, and on x86 INT_MIN / -1 raises rather than returning a wrong answer. A model that special-cased it after dividing would never reach the special case.

    div  x/0 -> -1        divu x/0 -> 2^32-1
    rem  x/0 -> x         remu x/0 -> x
    div  INT_MIN/-1 -> INT_MIN    rem INT_MIN/-1 -> 0

Each is a named test in tests/riscv32/test_rv32m.py, plus the asymmetry of mulhsu -- signed times unsigned, the only instruction here whose operands extend differently, asserted on operands where mulh, mulhsu and mulhu give three DIFFERENT answers (0, 0xFFFFFFFF, 0xFFFFFFFE for -1 x -1). A case where they agreed would pass over a decoder running any of the three.

The high halves are formed in 64 bits and shifted down UNSIGNED, the same C++17 reason sign_extend and shift_right_arithmetic are spelled out in this file: right shift of a negative signed value was implementation-defined until C++20.

Five mutations, all caught: dropping the overflow guard, DIVU/REMU by zero returning 0, MULHSU extending both operands as signed, MUL returning the high word.

FOUR TRIPWIRES FIRED, all correctly, all updated deliberately:
 - test_a_multiply_is_illegal_without_m_and_unwritten_with_it: renamed and now asserts 6*7==42.
 - tests/rv32 EXPECTED_HOLES: rv32m_op removed, so its 128 generated cases now run rather than being excused.
 - test_a_refused_step_leaves_the_processor_completely_untouched used `mul` as its example of an unwritten encoding. Now `ecall` -- SYSTEM is still genuinely unimplemented, there being no traps or CSRs here.
 - test_an_instruction_this_core_has_not_written_stops_the_run_and_says_so did the same, and had quietly gone green with agreed=4 and stopped=None: an assertion about stopping with nothing left to stop on. Now fence.i, which rvcpp runs straight through and this core has no Zifencei for. encode.py gains fence_i() and mul()'s docstring no longer advertises itself as an encoding this core refuses.

That last one is worth the next reader's attention: implementing an instruction silently REMOVES coverage from any test that used it as a stand-in for 'unimplemented'. The test does not fail loudly, it passes vacuously. Both were caught here only because they asserted something specific about stopping.

A is still absent and still recorded as absent. 1,206 passed, 17 skipped.
