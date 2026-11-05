---
id: OH-11
title: Microcode-exact IMUL, DIV and IDIV
status: done
priority: P2
owner: session/oh-11-wt
created: '2026-08-23'
touches:
- tests/i8086/test_muldiv.py
- core/i8086/muldiv.*
- core/i8086/exec_core.cc
- core/i8086/decode.h
- tests/i8086/test_conformance.py
- .github/workflows/rules.yml
- tests/i8086/test_idiv_overflow.py
- docs/features/i8086.md
---

IMUL, DIV and IDIV produce correct results and correct CF/OF but do not reproduce two things that need the 8088's CORX/CORD microcode emulated step by step rather than a C++ divide.

1. The documented-undefined flags. SF, ZF, PF and AF after IMUL, and every arithmetic flag after DIV and IDIV, are intermediates of the shift-and-add loop. A single internal byte does explain SF, ZF and PF jointly in all 10,000 IMUL cases -- so the value exists and is recoverable -- but it is not the product's high half (which fits ZF 96%, SF 98%, PF only 69%), nor the magnitude product, nor any simple function of either that was tried. MUL is not affected: its flags come from the high half exactly, and it is at 100%.

2. IDIV's quotient sign. 33 of 569 non-trapping register-form cases (5.8%) want exactly the negation of the correctly-signed quotient, with the remainder correct in every one. Neither operand's sign, the quotient's sign, nor a zero remainder separates the two groups, so this is a quirk of the correction step and not a sign-handling mistake that can be reasoned out.

Where this bites: the pushed FLAGS word on a divide-error trap contains the undefined bits, so it reaches memory and no register-side flag mask can hide it. That is why the DIV and IDIV floors in tests/i8086/test_conformance.py are stated over non-trapping cases.

Measured 2026-08-23 against SST8088 v2, F6.5 F6.6 F6.7 F7.5 F7.6 F7.7.

**Note 2026-08-23:** Blocked behind nothing: OH-4 is closed and released core/i8086/muldiv.*. Also rename the claimed test file if a different name is used -- tests/i8086/test_muldiv.py does not exist yet.

**Note 2026-08-26:** STILL OPEN 2026-08-26. Attempted, not solved. No code changed and no floor lowered; what follows is the search, so the next attempt does not repeat it.

THE HARNESS IS VALIDATED, which the previous attempt could not claim. MUL r/m8 is 100% on AH for SF, ZF and PF across 1,258 clean register-form cases -- independently reproducing this ticket's own statement. And IMUL's figures reproduce exactly: AH gives SF 98.1%, ZF 96.1%, PF 70.1%, against the ticket's 'ZF 96%, SF 98%, PF only 69%'. So the extraction is right and the numbers below mean something.

ONE TRAP WORTH NAMING FIRST: `final` is a DELTA. tools/sst8088.py warns about it and a first pass here still got it wrong -- the flags key is simply absent when nothing moved, and reading it raises rather than silently misleading. Merge over `initial` before anything else.

FIVE THINGS NEWLY RULED OUT.

(1) THE NEGATION STEP IS NOT THE ANSWER. The obvious hypothesis -- IMUL differs from MUL only by the conditional negate, so the flags come from before it -- is REFUTED. Splitting by operand signs gives PF 71.2% (both non-negative), 69.8% (signs differ), 69.5% (both negative). Identical within noise. Whatever the byte is, it is not sensitive to whether the negation ran.

(2) A REAL SUB-RULE, and the only clean structure found. Every PF mismatch has CF and OF set. With CF CLEAR, parity(AH) == PF in 67 of 67 cases. With CF set, 839 of 1,226. CF clear on IMUL means the product fits in a byte, so AH is 0x00 or 0xFF -- the internal byte agrees with AH exactly when the result is small. That is a constraint on any candidate function and the first thing to check a new one against.

(3) THE FLAGS ARE NOT PRESERVED. 'The 8086 leaves undefined flags alone' is refuted: SF/ZF/PF/AF match the INCOMING flags 49.4/52.2/48.9/50.2% -- chance.

(4) MORE CANDIDATE BYTES REFUTED, with figures, on IMUL (SF/ZF/PF): magnitude high byte 59.2/96.6/69.8, magnitude low byte 53.8/93.7/51.5, product low byte 50.6/93.7/48.8, AH xor AL 53.8/95.4/49.0, the operand 47.0/95.1/52.1, the initial AL 49.4/95.3/49.7.

(5) IDIV'S 33 CASES ARE LOCATED, and where they are is itself a finding. A strict two-byte register-form filter finds 265 non-trapping cases and ZERO disagreements. The 33 only appear once PREFIXED encodings are included -- they are 3- and 4-byte forms. Reproduced exactly: 536 agree, 33 negated, 5 other, from 569. So an attempt that filters prefixes away will conclude, wrongly, that IDIV is already correct.

TWELVE PREDICATES TESTED AGAINST THE 33, NONE SEPARATING: |q| odd, |r| odd, |d| odd, |n| odd, initial AH bit 7, initial AL bit 7, divisor bit 7, 2|r| >= |d|, 2|r| > |d|, incoming CF, |q| >= 64, |n|>>8 >= |d|. Best separation 0.288 (|r| odd) on n=33, which is noise. This confirms and extends the ticket's 'neither operand's sign, the quotient's sign, nor a zero remainder separates the two groups'.

WHAT I WOULD TRY NEXT, in order. (a) The prefix finding in (5) is suspicious: if the 33 are all 3-4 byte encodings, check whether the discriminator is the instruction LENGTH or a prefix's effect on timing rather than an arithmetic property at all -- that would move this from a microcode question to a decode one. (b) The CF sub-rule in (2) says the byte equals AH for small products; find what it becomes for large ones by solving per-case for the byte set consistent with all three flags and looking for structure against |q| and |r|. (c) Ken Shirriff's published 8086 microcode disassembly is the only source that would settle either half without guessing, and this repository has not consulted it.

Gate unchanged: 1,446 passed, 17 skipped; all eight checkers exit 0.

**Note 2026-08-30:** the claim on `tests/i8086/test_muldiv.py` is DELIBERATE
and the file does not exist yet, so `tools/check_ticket_claims.py` prints
"claims 'tests/i8086/test_muldiv.py', which matches no file, while its other
claims do match. Likely a typo." It is not a typo -- it is a forward claim on
the file this ticket would write, and the 2026-08-23 note above already says
so. Recorded here because the checker's wording invites somebody to "fix" it
by pointing the claim at a file that exists, which would release the name this
ticket is holding.

Still open, still on the same blocker: the undefined flags and IDIV's quotient
sign are intermediates of the 8088's CORX/CORD microcode, and two documented
attempts have failed to recover them. Nothing in the tree has changed that.

**Note 2026-10-10:** 2026-10-10: OH-222 filed against this ticket's core/i8086/muldiv.cc -- IDIV r/m16 with DX:AX = 0x80000000 and a divisor of 0xFFFF computes INT32_MIN / -1 on the host before the range check, which crashes the process (x64 #DE) where the part raises a divide error. Found by OH-220's review, by reading. Lend core/i8086/muldiv.* to OH-222 or take it here.

**Note 2026-10-10:** 2026-10-10: core/i8086/muldiv.* lent to OH-222 (the host-crashing IDIV), nobody holding this ticket and no session/muldiv branch or worktree existing. Return it when OH-222 closes.

**Note 2026-10-10:** 2026-10-10, from OH-222's review (by running against the fetched corpus; none of it changed here): (1) IDIV accepts a quotient of -128 (byte) where the 8088 traps: in F6.7 every case whose true quotient is -128 traps on the part (10 cases, none REP-prefixed), every -127 and +127 case does not, every +128 case traps; e.g. idx 1828, AX = -15156, BL = 118, IDIV BL -- the core writes AL = 80h, the part takes vector 0. muldiv.cc's range check uses low = wide ? -32768 : -128; the word form's edge has no F7.7 case either way. (2) The conformance floor test (tests/i8086/test_conformance.py ~401-404) drops every case where the part trapped before running it, so a core that fails to trap where the part does is never run -- which is why (1) passes; its docstring (~393-394) says it measures the trap decision. (3) The negated quotient this ticket's notes describe is exactly the REP prefix: in F7.7, 168 of 168 negated non-trapping cases are REP-prefixed and every REP-prefixed non-trapping case is negated; in F6.7, 146 of 146, plus 2 REP cases whose quotient is zero, where negation cannot show. None of the twelve predicates tried here included the prefix (note 5(a) suspected it).

**Note 2026-11-05:** Taken 2026-11-05 in worktree oh-11. Plan: the thinnest verified slice first -- REP-prefixed IDIV (and IMUL, if the corpus agrees) negates its result, and IDIV traps on a quotient of -128/-32768, both from OH-222's review note; then the undefined flags.

**Note 2026-11-05:** SOLVED. core/i8086/muldiv.cc no longer divides or multiplies in C++: it runs the 8088's own CORX (multiply) and CORD (divide) loops with NEGATE, PREIMUL, IMULCOF, MULCOF, PREIDIV and POSTIDIV around them, ported from MartyPC's muldiv.rs (MIT, Daniel Balsom, commit f0ebca4e411e55685b661e9efe1d136a9c727a7c; the notice is in the file's header). The undefined flags are whatever those routines leave in the ALU, and they come out right without being chosen.

BOTH HALVES OF THIS TICKET HAD ONE CAUSE EACH, AND NEITHER WAS ARITHMETIC ON THE ANSWER. (1) The flags after IMUL are IMULCOF's 16-bit add of the high half and the low half's sign bit -- a 16-bit value, which is why every 8-bit candidate the 2026-08-26 note tried fit SF 98% and PF 70% and none fit exactly. After DIV and IDIV they are CORD's last flag-setting SUB with CF from its final RCL. (2) The negated IDIV quotients are the REP-prefixed cases, as lead (a) of that note suspected it was the prefix: F2 or F3 sets the microcode's F1 latch, and POSTIDIV negates the quotient (not the remainder) when it is set. Before this, 146 of F6.7's 148 untrapped REP cases and 168 of F7.7's 168 failed; none do now. Also found: IDIV r/m8 traps on a quotient of -128, which fits in a byte -- CORD's range check is on the magnitude. The old core missed 10 such traps.

MEASURED against SST8088 v2 with NO flag mask and memory compared, so the pushed FLAGS of every trapped case is held too: F6.4 F6.5 F7.4 F7.5 10000/10000 each; F6.6 4801 + 5199 trapped; F7.6 4905 + 5095 trapped; F6.7 2312 + 7060 trapped + 148 REP + 480 REP-trapped; F7.7 2243 + 7090 + 168 + 499. All 80,000 exact.

So PARTIAL is gone from tests/i8086/test_conformance.py, with its floors and the trapped-case exclusion: the full-corpus test now runs all eight files whole. The CI slice in .github/workflows/rules.yml gains F6.5 (IMUL), and its F6.7 comment no longer calls it a PARTIAL file. Ledger cell i8086.ins.muldiv is done. tests/i8086/test_muldiv.py holds twelve corpus cases without the corpus -- REP IDIV at both widths, the -128 trap, IMUL and DIV flags, a trap's pushed flags -- and all six of its tests were run against a build of 44ca5c8 (before this) and failed there.

NOT VERIFIED BY SILICON, and said so where it matters: (a) REP in front of MUL or IMUL also negates the product per the microcode, and the corpus has no such case, so that path follows MartyPC and nothing here checks it. (b) The -32768 trap for IDIV r/m16: no register-form corpus case has that quotient; test_muldiv.py asserts the trap only, as the byte rule at the other width.

FILED: OH-253, PROVENANCE.md does not record muldiv.cc as a MartyPC port (PROVENANCE.md is OH-244's, so OH-253 claims nothing until OH-244 releases it; claiming it too failed check_ticket_claims).

**Note 2026-11-05:** Verified before landing: build_core OK; pytest 2776 passed, 681 skipped, 5 failed, the five being OH-250's composer tests, which fail in any worktree with no third_party fetched and touch nothing here; every other checkall row OK, with check_ticket_claims --base origin/master.

**Note 2026-11-05:** Landing came back: the claim check failed, because one push carried the OH-11 fix and the commit filing OH-253, and check_ticket_claims holds the whole diff to one ticket, so OH-253's own ticket file read as a write into another ticket's files. Fixed by landing each commit alone, checked under its own ticket id.

**Note 2026-11-05:** Landing came back a second time, before any push: another session had filed a different OH-251 on origin/master meanwhile, so the PROVENANCE.md ticket is renumbered OH-253 and the references above follow it.

**Note 2026-11-05:** Landing came back again, before any push: other sessions filed their own tickets under each id this one took, so it is now OH-253, the next free id at the moment it was pushed. The landing agent renumbers and pushes the filing in one pass, because a filing handed over by hand lost that race twice.
