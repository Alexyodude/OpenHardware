---
id: OH-209
title: The XIAO RP2350 SMD's BOOT pad says what Seeed's own file shows it reaches
status: in-progress
priority: P2
created: '2026-10-08'
touches:
- tools/import_pindefs.py
- tests/rules/test_import_pindefs.py
- webui/boards/XIAO-RP2350-*.json
- webui/boards/rp2350.py
---

Part of OH-174. Since OH-157, XIAO-RP2350-SMD holds geometry, model and runs, and misses pins on one pad: BOOT. Its why_null is the generic one the TWINS pins layer counts as unanswered, because OH-170 found no BOOT net in Seeed's `third_party/seeed-pcb/RP2350.kicad_pcb`, and Seeed's wiki calls BOOT a button, which says nothing about a pin.

The RP2350 samples BOOTSEL on QSPI_SS rather than on a GPIO (RP2350 Datasheet, its boot sequence chapter), so the honest answer for this pad may be a specific reason rather than a chip pin. Find what Seeed's own sources say the BOOT pad reaches: the board file's copper from that pad (trace it with the repository's tracer before concluding there is no net), Seeed's schematic for the XIAO RP2350 if one is published, and the footprint. If the pad reaches QSPI_SS or the flash chip-select, write that as the pad's reason, citing both the board's source and the datasheet section; if it reaches a GPIO, write the chip pin. Do not answer it from the datasheet alone.

Done when XIAO-RP2350-SMD's BOOT pad names a chip pin or a reason specific to that pad, each resting on Seeed's own file, and the board holds all four layers.
