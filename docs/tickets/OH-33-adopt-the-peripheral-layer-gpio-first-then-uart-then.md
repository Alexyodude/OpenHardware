---
id: OH-33
title: 'Adopt the peripheral layer: GPIO first, then UART, then one timer'
status: open
priority: P1
created: '2026-08-25'
touches:
- webui/peripherals/**
- tests/webui/test_peripherals.py
---

docs/research/peripheral-layer/ holds a 34 KB design over nine provenance rounds and 36 chip/regmap/contract JSON files for ESP32-C3, RP2040 and STM32C031, with citations to datasheets and to pico-sdk. OH-18 preserved it and was explicit that preserving is not adopting: 'adopting it is a separate decision, and the design's own section 6 is the scoping test for that.' This is that decision.

Adopt narrowly. webui/boards/rp2040.py already adopts the slice a blink image reaches and says so per register. Widen to the three peripherals that make a board demonstrable rather than merely alive: GPIO so a pin state is observable, UART so a printf arrives, and one timer so delay() is not a spin loop. Everything else stays research.

Run section 6 as the gate before writing code and record the answer, including if it says no. A design that nine agents produced and nobody has executed is evidence, not policy, and the failure mode is adopting all 36 files because they are there.

The RP2040 atomic-alias correction in rp2040.py's docstring is the warning: the research's first reading was wrong and self-corrected once. Adopting a file wholesale adopts its uncorrected passages too.

Done when a firmware printf reaches the UI, a GPIO write is observable at a pad, and every adopted register cites the research file carrying its provenance.
