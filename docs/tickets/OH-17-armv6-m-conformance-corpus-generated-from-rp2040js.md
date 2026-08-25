---
id: OH-17
title: Armv6-M conformance corpus, generated from rp2040js
status: done
priority: P1
created: '2026-08-24'
touches:
- tools/gen_armv6m_tests.mjs
- tools/get_armv6m_tests.sh
- tests/armv6m/**
- tests/cortexm0/test_conformance.py
- tests/cortexm0/conftest.py
---

A Cortex-M0+ core is worth ~22 boards on the catalogue -- every Pico, every SAMD21 Arduino, the M0+ Nucleos, XIAO RP2040 and SAMD21. But this project does not ship a core without an oracle, and no Armv6-M corpus exists anywhere: SingleStepTests has 22 repos and none is M-profile. rp2040js is the oracle that exists today -- MIT, hand-written from DDI0419 so independent of QEMU, models M0+ rather than M0, and measured here at 1,188,334 cases/sec. Generate SST8088-shaped fixtures from it, so a core can be written against something. Corpus is git-ignored and fetched/generated like the 8088 one.

**Note 2026-08-24:** Generator landed (tools/gen_armv6m_tests.mjs, commit 8afe281) and verified: 150 cases over 3 families; 50/50 ADCS agree with an independently written implementation of the N/Z/C/V rules. NOT done: no Cortex-M0+ core exists to check against it, and the corpus itself is git-ignored and not yet generated at scale.

**Note 2026-08-25:** Claim on docs/tickets/** removed. It was over-broad for a conformance-corpus ticket -- it owned every ticket file plus README.md, and when write enforcement shipped in 16dceeb it blocked 15 of 16 open tickets from recording a note on their own ticket. OH-51's rule change (1a817d1) exempted ticket FILES by making each ticket own its own, but README.md still fell here, which left the ticket documentation unmaintainable by anyone but this ticket. The claim was taken by --steal after confirming pid-23432 is not running and the lock was over 24 hours old, with no OH-17 files touched in the working tree. Nothing else about this ticket is changed: tools/gen_armv6m_tests.mjs, tools/get_armv6m_tests.sh and tests/armv6m/** are untouched and still claimed, and the corpus work itself is not started.

**Note 2026-08-26:** CLOSED 2026-08-26.

THE TICKET'S NOTES WERE STALE. 'NOT done: no Cortex-M0+ core exists to check against it, and the corpus itself is git-ignored and not yet generated at scale.' Both stopped being true: OH-39 landed the core, and tests/cortexm0/test_conformance.py has been running the whole corpus against it since. Measured today:

    13,500 cases: 13,300 agreed, 200 predicted oracle bug, 0 unexplained

The 200 are rp2040js's three known shift-carry bugs. Each is PREDICTED by oracle_carry_bug rather than tolerated, and the run asserts predicted > 0 -- so a fixed oracle fails loudly instead of quietly reducing what this proves.

WHAT WAS GENUINELY MISSING was the floor, and it was worse than absent -- it was misleading. The assertion read 'total >= len(FAMILIES)', which is twenty-seven. --count is a command-line argument, so a corpus regenerated with --count 1 would be twenty-seven cases and PASS: every divergence explained, nothing wrong, and the core checked against a 399th of what it had been. Now 27 x 500, verified red by raising CASES_PER_FAMILY to 501.

tools/get_armv6m_tests.sh was claimed by this ticket and never written. It exists now. The 8088 corpus is FETCHED and this one is GENERATED -- SingleStepTests has 22 repositories and not one is M-profile -- but the contract is identical and it is the contract that matters: never committed, one command to produce, and a suite with no corpus SKIPS saying how to get one. The skip message names the script now, because the raw node command is one forgotten flag from a corpus the floor rejects.

A CLAIM WAS NARROWED to make this possible. OH-64 claimed tests/cortexm0/* whole, which swept in the Armv6-M conformance run -- nothing to do with Armv7E-M. Narrowed to the two paths it needs, under its own hold.

STILL TRUE AND WORTH REPEATING: this is a simulator oracle, not silicon. A case means 'agrees with rp2040js', which is weaker than the 8088 corpus's 'agrees with an AMD D8088'. rp2040js was gdbdiff'd against a real RP2040 once; that was a one-off, not a continuous claim.

Gate: 1,433 passed, 17 skipped; all eight checkers exit 0.
