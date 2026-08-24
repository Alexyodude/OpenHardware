---
id: OH-18
title: Preserve the peripheral-layer research before the scratchpad is lost
status: done
priority: P2
created: '2026-08-24'
touches:
- docs/research/**
---

Nine verification agents produced a peripheral-layer design (34 KB, nine provenance rounds, three architectures) and 36 chip/regmap/contract JSON files for ESP32-C3, RP2040 and STM32C031. All of it lives only in a session-scoped scratchpad that is destroyed when the session ends. It is research output, not adopted policy -- adopting it is a separate decision, and the design's own section 6 is the scoping test for that. But losing it would mean re-deriving verified work with real citations, so it is copied into docs/research/ marked clearly as unadopted.
