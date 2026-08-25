---
id: OH-55
title: Multiply and divide for the ESP32-C parts, which are all RV32IMC
status: open
priority: P1
created: '2026-08-25'
touches:
- tests/rv32/corpus/rv32m_op.json
- tests/riscv32/test_rv32m.py
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
