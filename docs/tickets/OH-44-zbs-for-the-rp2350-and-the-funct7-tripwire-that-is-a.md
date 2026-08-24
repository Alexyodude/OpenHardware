---
id: OH-44
title: Zbs for the RP2350, and the funct7 tripwire that is already waiting for it
status: in-review
priority: P2
created: '2026-08-25'
touches:
- core/riscv32/**
- tests/riscv32/**
- tests/rv32/**
- tools/gen_rv32_tests.py
---

The second extension slice for the RP2350, after OH-42 landed Zba. Zbs rather than Zbb, and the reason is a property of what OH-42 left behind rather than a preference about ordering.

## The tripwire already in the tree

`test_an_unassigned_encoding_under_zbas_funct7_is_still_illegal` currently pins `bset` -- funct7 `0b0010000`, funct3 `001` -- as `Illegal` on an RP2350 with Zba enabled. It exists because that funct7 is shared: enabling Zba must not open it wholesale, and rvcpp implements Zbs, so lockstep would have agreed with that bug.

`bset` is a Zbs instruction. So adding Zbs **must** change that assertion, and the slice arrives with a test that fails until the gate is genuinely per-funct3 rather than per-funct7, and passes only when it is. An additive-only extension group has no such property; this one carries its own proof that the shared-funct7 handling was done rather than assumed.

## Size and shape

8 instructions: `bclr`, `bext`, `binv`, `bset` and their immediate forms. Two funct7 values, no new instruction format. rvcpp implements all of them -- `BSET` sits two lines above `SH1ADD` in `rv_core.cpp`.

Take the encodings from the oracle's own table, as OH-42 did, so the corpus and rvcpp cannot disagree about the bits before disagreeing about the answer.

## The two-spellings hazard

`MODELLED` in `tests/rv32/conftest.py` and `abi.RP2350_MODELLED` are two spellings of one fact, and `test_the_extension_letters_match_the_abi_bitmasks` fails if a slice updates one without the other. That is deliberate. Read the failure rather than working around it -- it prints both values.

## Suggested order after this one

Zbb next (~15 instructions, the group compilers actually emit; architectures.md 2.1b already confirms rvcpp executes `clz`, `cpop`, `rev8` and `ctz`), then Zbkb, then the Zc* group **last** -- deliberately, because it needs 16-bit decode work, it is where rvcpp's measured `C_LD`/`C_SD` defect lives, and it is where OH-42's C-equals-Zca-on-a-part-without-an-FPU reasoning first becomes load-bearing rather than incidental.

Done when every added instruction has a gating case distinguishing the RP2350 from the ESP32-C3, the shared-funct7 test passes in its updated form, lockstep agrees with rvcpp, and `check_board_claims` still reports two claims -- there is still no RISC-V toolchain here, so these remain hand-encoded programs.
