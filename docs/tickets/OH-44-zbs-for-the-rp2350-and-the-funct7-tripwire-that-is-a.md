---
id: OH-44
title: Zbs for the RP2350, and the funct7 tripwire that is already waiting for it
status: done
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

**Note 2026-08-25:** CORRECTION to this ticket's own justification, above. The section headed 'The tripwire already in the tree' is WRONG and should be read as retracted. It claimed test_an_unassigned_encoding_under_zbas_funct7_is_still_illegal pinned bset, so that adding Zbs must change it. bset is funct7 0b0010100 (0x14); that test asserts funct7 0b0010000 (0x10), which is Zba's, and the encoding it names belongs to no extension. Verified against rvcpp's own table: RVOPC_BSET_BITS is 0b0010100...001...0110011 while RVOPC_SH1ADD_BITS is 0b0010000...010...0110011. So nothing failed when Zbs landed, and the sequencing argument rested on a transposed digit. Zbs-first was still correct for a different and better reason, found during implementation: it is the first group whose encodings span TWO opcodes -- register forms under OP, immediates under OP_IMM sharing funct3 with SLLI and SRLI/SRAI -- and that overlap is where the real hazard was. SLLI refused any nonzero funct7 because bit 25 set is RV64's six-bit shift amount; Zbs shares that funct3, so the refusal had to be threaded past with a list of named funct7 values rather than relaxed to 'nonzero is fine', which would have reopened the RV64 encoding. LESSON FOR THE NEXT TICKET: do not write 'a test is already waiting for this' into a ticket body without checking the encoding first. That framing came from the implementing session and was accepted by the lead without verification; both of us should have looked at the table.

**Note 2026-08-25:** Closed 2026-08-25. Zbs landed at 9a6e24f and Zba at 4868acb; lockstep against rvcpp passes 12 tests with the oracle built, and the ticket's own correction note already records what its justification got wrong.

RETRACTION, so the next reader does not inherit it: the Done-when says "there is still no RISC-V toolchain here, so these remain hand-encoded programs". That is no longer true and may not have been true when written. riscv32-esp-elf-gcc 8.4.0 is installed under ~/.platformio/packages/toolchain-riscv32-esp/, verified by compiling and disassembling a bare-metal ESP32-C3 blink on 2026-08-25. A real compiled RISC-V image is available to any future slice, which changes what the ESP32-C work can claim -- it can reach the standard the RP2040, SAMD21 and ATmega328P met rather than stopping at hand-encoded programs.

The paths core/riscv32/**, tests/riscv32/** and tests/rv32/** are released to the ESP32-C series programme (OH-54 onward), which needs the compressed decoder this ticket's own "suggested order" put last.
