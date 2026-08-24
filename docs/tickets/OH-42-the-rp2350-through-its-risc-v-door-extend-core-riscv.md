---
id: OH-42
title: 'The RP2350 through its RISC-V door: extend core/riscv32 to the datasheet''s
  ISA string'
status: in-review
priority: P1
created: '2026-08-25'
touches:
- core/riscv32/**
- tests/riscv32/**
- tests/rv32/**
- tools/gen_rv32_tests.py
---

OH-36's checkpoint found no Armv8-M oracle and no ARM compiler on this machine, so the eight Armv8-M boards split. This is the half that is buildable today: the RP2350 is two architectures on one die, and its RISC-V half is Hazard3.

That matters because rvcpp is **Hazard3's own golden model, written by the author of the silicon**, and it is already built here (third_party/rvcpp-build/rvcpp.exe) and already in lockstep with core/riscv32 over 69 instructions. For Armv8-M there is no oracle, no compiler and no image. docs/architectures.md 5.4 is titled 'RP2350 -- two doors, one much cheaper' and reached this conclusion before OH-36 was filed.

Reaches 2 of the 8 boards: XIAO-RP2350-DIP and XIAO-RP2350-SMD.

## What the increment actually is

RP2350 datasheet 3.8 gives the ISA string:

    rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp

plus Xh3power, Xh3bextm, Xh3irq and Xh3pmpm. 137 mnemonics in total.

core/riscv32 today gates only kExtM, kExtA and kExtC, and its own comment says Zb*/Zc* are absent because no board needs them yet. The RP2350 is that board. So the increment is Zba, Zbb, Zbs, Zbkb, Zca, Zcb, Zcmp, and at least Xh3irq.

## The trap, flagged before anyone starts

**The ISA string has no plain `c`. It is `zca_zcb_zcmp`.** kExtC is NOT the same thing as Zca, and treating the existing gate as covering them would be a quiet wrong answer of exactly the kind that produced the GPIOn header-pad labels in OH-28 and the index-versus-GPIO reading in OH-26 -- plausible, successful-looking, wrong.

## What lockstep cannot tell you

rvcpp has no extension gating at all (architectures.md 2.1b), and its RVC decoder wrongly accepts C_LD/C_SD/C_LDSP/C_SDSP on even registers. So lockstep says 'agrees about legal code' and is silent at the illegal edge. OH-35's corpus is what closes that, which is why this ticket claims tests/rv32/** and gen_rv32_tests.py as well: every extension added here needs its gating case there, or the core will accept on an RP2350 what an ESP32-C3 must refuse.

Done when a program using the new extensions runs in lockstep with rvcpp, every added extension has a gating case that distinguishes the RP2350 from the ESP32-C3, and no board claims to run firmware -- there is still no RISC-V toolchain here, so these remain hand-encoded programs and check_board_claims must stay green.
