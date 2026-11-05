---
id: OH-8
title: Cycle accuracy against SST8088 bus traces
status: open
priority: P2
owner: session/timing
created: '2026-08-23'
touches:
- core/i8086/timing.*
- tests/i8086/test_timing.py
- core/i8086/abi.h
- core/i8086/abi.cc
- core/i8086/abi.py
---

Slice 2g, the three F2 cells. Only meaningful once the full ISA is green. F2 is verifiable here rather than aspirational because the oracle carries a per-cycle bus trace.

**Note 2026-08-26:** PARTIAL 2026-08-26. The first slice landed; the three F2 cells stay `planned` and this stays OPEN, with the remaining work measured rather than estimated.

WHAT LANDED: core/i8086/timing.* and the bus-cycle floor. cycles >= 4 * (length - queued), from two architectural facts -- the 8088's eight-bit external bus and four-byte prefetch queue, so a byte not already queued costs one four-clock bus cycle. Verified over the WHOLE corpus once: 2,857,000 cases, ZERO violations, 521,944 tight. ABI 7 -> 8.

WHY ONLY THIS. All three F2 cells need a per-opcode EXECUTION cost and there is nowhere honest to get one. Fitting a table to the corpus and then testing against the same corpus proves a table was fitted. The bound is the one part derivable from the architecture instead, so it is the one part the oracle can CHECK rather than merely confirm.

WHAT WAS MEASURED ABOUT THE REST, and it is encouraging. For the register form (mod=3) the cycle count is EXACTLY deterministic: 123 of 234 fetched opcodes have a single value with a full queue. 00 is 3 clocks full / 8 empty; 05 (op AX,imm16) is 4 / 12. The pattern is max(EU, 4 * bytes fetched), which is the real 8088 behaviour -- so a table-driven model IS tractable. The 111 that vary are the genuinely data-dependent ones: conditional branches, shifts by CL, MUL/DIV, string ops.

THE HARD LIMIT ON WHAT THIS CORPUS CAN EVER PROVE, and it is new: the rig only ever starts a case with the queue EMPTY or FULL, never one, two or three bytes. Counted across 2,857,000 cases: queue lengths present are exactly {0, 4}. So the corpus adjudicates the two extremes of the fetch cost and says nothing about the middle -- which is where a real prefetch model spends most of its time. A prefetch-queue model can be built and only partly checked here. That belongs in the ticket before anyone starts one.

NEXT SLICE, if someone takes it: an EU cost table for the register form, taken from Intel's published timing table rather than fitted, verified against the 123 deterministic opcodes. That is a real conformance claim. Deriving the table from the corpus instead would need a held-out split to mean anything, and should say so loudly if chosen.

A TEST LESSON WORTH KEEPING: the first version of the corpus check read the FIRST 24 opcode files and never saw a 6-byte instruction, because the long encodings live further up the opcode space. A prefix of the opcode space is not a sample of it. It reads every 13th file now, and test_the_sample_covers_every_length_and_both_queue_states asserts the sample's adequacy rather than leaving it to a comment.

Gate: 1,446 passed, 17 skipped; all eight checkers exit 0.

**Note 2026-11-05:** Register-form slice: RegisterFormClocks / RegisterFormCycles in core/i8086/timing.*, exported as i8086_register_form_cycles (ABI 9 -> 10) and abi.register_form_cycles. Every number is Intel's, 8086 Family User's Manual (9800722-03) Table 2-21 pp. 2-51..2-68, never read off the corpus. Claimed only at queue 0 (max(EU, 4*length)) and at a queue holding the instruction and the next opcode (Intel's clocks alone). Whole corpus 2026-11-05: 516,078 cases claimed across 162 opcode files, zero mismatches; tests/i8086/test_timing.py checks one file per row (27 rows, F7.0 added after review) and fails if any of Intel's figures moves a clock (mutation-checked on CBW). Left for the rest of OH-8: (1) LAHF -- Intel says 4, the part takes 2 on every unprefixed full-queue case, pinned by a test and not tabled; (2) a 4-byte instruction from a full queue takes 7, not 4 or 8 -- when the BIU starts its next fetch, i.e. the prefetch model; (3) a segment prefix costs 2 of its own; (4) partial queues 1-3 never occur in the corpus, so nothing here can check them. F2 cells in docs/features/i8086.md stay planned: this is a partial slice, so the ticket goes back to open, not done.

**Note 2026-11-05:** Correction after review (architect, opus): the note above overclaims. From an empty queue the bus is always the slower unit (at best a tie: DAA, DAS and SAHF are 4 against 4), so those cases check decoding and length, not Intel's figure; the figure is checked only by full-queue cases, which a four-byte instruction cannot reach. So two figures are tabled and checked by nothing in this corpus: 81 reg,imm16 and F7 /0 TEST reg16,imm16. test_every_row_of_intels_table_matches_the_part_exactly now pins that the unchecked set is exactly those two (FOUR_BYTE_ROWS), and timing.h says so. Also from the review: the binding clamps a queue above 255 instead of masking it to 0, a negative queue is no claim, and the wrong-length path and the remaining not-used encodings (82, 8C/8E reg>=4, 8E /1, D0/D1 /6, F6/F7 /1) have unit tests.

**Note 2026-11-06:** Landing came back landed: a7a7d6c (the slice) and 9d9c1ac (status open, a partial slice; the F2 cells stay planned), after one push retry. It also came back with one mistake in the brief: a relative --basetemp under the repo made three tests fail (test_inventory's two not-a-repository tests and test_compile's variant-refusal test), because their tmp dirs then sat inside a git checkout. An absolute basetemp under %TEMP% fixed that, and the full suite then passed (3258 passed, 259 skipped, 1 xfailed). The bare-pytest exit 1 seen earlier was pytest's own end-of-session cleanup hitting PermissionError on the shared pytest-of-<user>/pytest-current link while other workers ran pytest; every test had passed. No sync, since there is no tickets.mjs and no tickets were filed.
