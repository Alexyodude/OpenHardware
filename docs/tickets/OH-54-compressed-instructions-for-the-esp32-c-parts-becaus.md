---
id: OH-54
title: Compressed instructions for the ESP32-C parts, because two thirds of a real
  image is 16-bit
status: open
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/exec.cc
- core/riscv32/exec.h
- core/riscv32/cpu.h
- core/riscv32/cpu.cc
- tests/riscv32/test_rvc.py
- tests/rv32/corpus/rv32c.json
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
