---
id: OH-54
title: Compressed instructions for the ESP32-C parts, because two thirds of a real
  image is 16-bit
status: done
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/exec.cc
- core/riscv32/exec.h
- core/riscv32/cpu.h
- core/riscv32/cpu.cc
- tests/riscv32/test_rvc.py
- tests/rv32/corpus/rv32c.json
- tests/riscv32/c3blink/*
- tests/riscv32/test_extension_gating.py
- tests/rv32/test_gating.py
- tests/rv32/conftest.py
---

The blocker for all seven ESP32-C boards, and it is not an optional extension in any practical sense.

MEASURED, not assumed. A bare-metal blink compiled here with the toolchain that is actually installed:

    riscv32-esp-elf-gcc 8.4.0 -march=rv32imc -mabi=ilp32 -Os -ffreestanding -nostdlib -nostartfiles

    00010054 <main>:
       10054:  60004737    lui   a4,0x60004
       10058:  531c        lw    a5,32(a4)
       1005a:  1141        addi  sp,sp,-16
       1005c:  06300693    li    a3,99
       10060:  1007e793    ori   a5,a5,256
       10064:  d31c        sw    a5,32(a4)
       ...

Eleven of its sixteen instructions are compressed. core/riscv32/exec.cc:153 answers every one of them with refuse(cpu, kExtC), so this core cannot execute a single instruction of a real ESP32-C image -- not a corner of one, the first halfword.

The width dispatch is already there and correct: exec.cc:134-155 reads the low halfword first and branches on (low & 3) != 3, with the all-zero halfword routed to Illegal rather than through refuse, for the reason the comment gives. What is missing is the decoder behind it.

## The oracle, and its measured blind spot

rvcpp is built here and tests/riscv32/test_lockstep.py runs 12 tests against it. It is the right oracle for this and it is WRONG in exactly one place, which docs/architectures.md 2.1b measures at commit 8af9929:

  Its RVC decoder has no XLEN gate. C_LD (rv_core.cpp:732), C_SD (764), C_LDSP (981) and C_SDSP (1000) are the RV64 meanings of encodings that on RV32 belong to Zcf/Zcd. rvcpp is XLEN=32 with no floating point, so on a part with no FPU all four must raise illegal-instruction. They instead execute as integer loads and stores whenever the register is EVEN; odd registers reject only because the generated opcode masks carry a spurious rd[0]==0 constraint. Half the register space rejects by coincidence.

So those four encodings are where lockstep must NOT be believed, and the divergence has to be allowed for by name the way tests/cortexm0/test_conformance.py allows for rp2040js's C-flag bug -- an allowance tied to a named defect, never a blanket tolerance. Every other RVC encoding is checked against the oracle normally.

Second check, independent of rvcpp and cheap: an exhaustive sweep against riscv32-esp-elf-objdump, the method tests/cortexm0/test_disasm.py used to compare 56,551 encodings and find three bugs four real images could not. The 16-bit space is 65,536 encodings, so it can be enumerated whole rather than sampled.

## Scope

RV32C only. Zcb, Zcmp and Zcmt are the RP2350's and the ESP32-C5's and are NOT in this slice; cpu.h already records them as absent in MODELLED rather than pretending the part lacks them, and that stays true.

tests/rv32/corpus/rv32c.json holds 10 cases today, which is not coverage of ~30 encodings. Widen it from rvcpp's own table the way tools/gen_rv32_tests.py already does, so the corpus and the oracle cannot disagree about the bits before disagreeing about the answer.

kExtC is not Zca and cpu.h:62-70 explains why the two coincide on every part here and must not be conflated. Nothing in this slice may erode that distinction.

Done when a real compiled ESP32-C3 blink executes end to end in this core, the ~30 RV32C encodings agree with rvcpp except the four named above, the 16-bit space is swept against objdump, and the extension gating still tells an ESP32-C3 from an RP2350.

**Note 2026-08-25:** Delivered. A real compiled ESP32-C3 image runs in this core: 33 transitions of GPIO8 at a constant period of 606 instructions, with GPIO_ENABLE bit 8 set. Eleven of that image's sixteen instructions are compressed, so before this the core refused the second instruction it fetched.

SHAPE: expanded, not re-implemented. Every RVC encoding is defined by the specification as exactly one base instruction, so expand_compressed turns the halfword into that 32-bit encoding and the existing execute path runs it. c.add cannot drift from add because they are the same code. What the expansion cannot carry is how far PC moves -- c.jal links to pc+2 and jal to pc+4 from an otherwise identical encoding -- so `width` travels beside the instruction. step() was split into fetch and execute for exactly that.

VERIFICATION, two sweeps, because one of them proves less than it looks:

 1. LEGALITY. All 49,152 halfwords with (c&3)!=3, laid end to end, one objdump pass. 31,232 exact agreements and 17,920 divergences, EVERY ONE accounted for and every one in the safe direction:
      8 x 2048  c.fld/flw/fsd/fsw and their sp forms -- Zcd and Zcf, needing D and F, and no part here has an FPU
      1024      c.slli with shamt >= 32
      256 + 256 c.srli / c.srai with shamt >= 32 -- RV64's six-bit field
    ZERO cases in the dangerous direction: nothing objdump refuses that this core executes.

 2. OPERANDS. 26,472 encodings executed from a known state and compared against the operands objdump decoded for the same halfword. Legality agreement cannot catch a transposed immediate bit -- the encoding stays legal and means a different offset, which does not fault. 0 failures.

FOUR TEST DEFECTS FOUND BY MUTATION, and they are the interesting part:

 a. ACCOUNTED was a TOLERANCE, not an assertion. Making c.fldsp decode left the legality sweep green, because a core that wrongly decodes it agrees with objdump perfectly -- the allowance was doing the job of a check. Now every accounted class is positively asserted illegal.
 b. Same hole for the RV64 shift amounts.
 c. The jump check watched only the PC, so expanding c.j to `jal x1` instead of `jal x0` passed: right PC, and a silently clobbered return address. Now the register file is checked too.
 d. My own harness read objdump's branch target as a displacement when it is an ABSOLUTE address inside the swept blob. 8,192 failures across all four pc-relative classes at once -- which is the shape of a harness bug, not four core bugs, and is written into the test header so the next person suspects the harness first.

DEAD CODE REMOVED, found by mutation. The explicit bit-12 refusals in C.SLLI/C.SRLI/C.SRAI were redundant: a shift amount of 32 or more puts a one in imm[5], which is funct7's low bit, and the 32-bit shift already refuses any nonzero funct7 for the same reason. No input could tell the difference. Deleted, and the BEHAVIOUR pinned by test_a_compressed_shift_of_thirty_two_or_more_is_refused so moving the enforcement did not lose it -- verified by mutating the 32-bit SLLI gate and watching the new test catch it.

TWO TRIPWIRES FIRED, both correctly, both updated deliberately rather than worked around:
 - test_a_compressed_encoding_is_illegal_without_c_and_unwritten_with_it asserted Unimplemented on a part that has C. That was honest until this slice; the name and the assertion both changed.
 - tests/rv32/test_gating.py's EXPECTED_HOLES named rv32c, and refusal_is_testable derives from it. Removing the entry tightened every compressed case from 'unimplemented is honest' to 'must be refused per part' in one edit, which is what its comment always promised.

NOT IN THIS SLICE, and cpu.h still records them as absent rather than pretending the part lacks them: Zcb, Zcmp, Zcmt. The C5 needs all three (OH-57). M is OH-55.

1,192 passed, 17 skipped; all eight checkers exit 0.
