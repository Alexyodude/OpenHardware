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
- docs/tickets/**
---

A Cortex-M0+ core is worth ~22 boards on the catalogue -- every Pico, every SAMD21 Arduino, the M0+ Nucleos, XIAO RP2040 and SAMD21. But this project does not ship a core without an oracle, and no Armv6-M corpus exists anywhere: SingleStepTests has 22 repos and none is M-profile. rp2040js is the oracle that exists today -- MIT, hand-written from DDI0419 so independent of QEMU, models M0+ rather than M0, and measured here at 1,188,334 cases/sec. Generate SST8088-shaped fixtures from it, so a core can be written against something. Corpus is git-ignored and fetched/generated like the 8088 one.
