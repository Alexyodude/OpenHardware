---
id: OH-11
title: Microcode-exact IMUL, DIV and IDIV
status: open
priority: P2
owner: session/muldiv
created: '2026-08-23'
touches:
- tests/i8086/test_muldiv.py
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
