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
