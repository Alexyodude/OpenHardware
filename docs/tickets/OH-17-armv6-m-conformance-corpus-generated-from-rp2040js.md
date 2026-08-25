---
id: OH-17
title: Armv6-M conformance corpus, generated from rp2040js
status: open
priority: P1
created: '2026-08-24'
touches:
- tools/gen_armv6m_tests.mjs
- tools/get_armv6m_tests.sh
- tests/armv6m/**
---

A Cortex-M0+ core is worth ~22 boards on the catalogue -- every Pico, every SAMD21 Arduino, the M0+ Nucleos, XIAO RP2040 and SAMD21. But this project does not ship a core without an oracle, and no Armv6-M corpus exists anywhere: SingleStepTests has 22 repos and none is M-profile. rp2040js is the oracle that exists today -- MIT, hand-written from DDI0419 so independent of QEMU, models M0+ rather than M0, and measured here at 1,188,334 cases/sec. Generate SST8088-shaped fixtures from it, so a core can be written against something. Corpus is git-ignored and fetched/generated like the 8088 one.

**Note 2026-08-24:** Generator landed (tools/gen_armv6m_tests.mjs, commit 8afe281) and verified: 150 cases over 3 families; 50/50 ADCS agree with an independently written implementation of the N/Z/C/V rules. NOT done: no Cortex-M0+ core exists to check against it, and the corpus itself is git-ignored and not yet generated at scale.

**Note 2026-08-25:** Claim on docs/tickets/** removed. It was over-broad for a conformance-corpus ticket -- it owned every ticket file plus README.md, and when write enforcement shipped in 16dceeb it blocked 15 of 16 open tickets from recording a note on their own ticket. OH-51's rule change (1a817d1) exempted ticket FILES by making each ticket own its own, but README.md still fell here, which left the ticket documentation unmaintainable by anyone but this ticket. The claim was taken by --steal after confirming pid-23432 is not running and the lock was over 24 hours old, with no OH-17 files touched in the working tree. Nothing else about this ticket is changed: tools/gen_armv6m_tests.mjs, tools/get_armv6m_tests.sh and tests/armv6m/** are untouched and still claimed, and the corpus work itself is not started.
