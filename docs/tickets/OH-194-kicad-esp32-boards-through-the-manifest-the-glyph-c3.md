---
id: OH-194
title: 'KiCad ESP32 boards through the manifest: the Glyph C3 and C6, the Olimex C3
  DevKit-Lipo and C6-EVB, and the SparkFun C5 if its licence is stated'
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-194-*
---

Part of OH-174. OH-192 made a KiCad `.kicad_pcb` a manifest row, with pins traced through the copper. The survey (.omc/research/twin-candidates.md in the main checkout, 2026-09-29) lists ESP32 boards on chips that already run here that publish only KiCad, with a variant on disk:

| board | chip | variant | licence as surveyed |
|---|---|---|---|
| PCBCUPID Glyph C3 | ESP32-C3 | Pcbcupid_GLYPH_C3 | CC BY-SA 4.0 stated by the README's link; no licence file |
| PCBCUPID Glyph C6 | ESP32-C6 | Pcbcupid_GLYPH_C6 | as above |
| Olimex ESP32-C3-DevKit-Lipo | ESP32-C3 | esp32c3-devkit-lipo | hardware CERN-OHL-S-2.0 stated by the README; the LICENSE file is GPL-3.0 (software) |
| Olimex ESP32-C6-EVB | ESP32-C6 | esp32c6-evb | hardware CERN-OHL v1.2 stated by the README; LICENSE file GPL-3.0 |
| SparkFun Thing Plus ESP32-C5 | ESP32-C5 | sparkfun_esp32c5_thing_plus | not established: the README points to a LICENSE.md that is not in the tree |

Licence decision (the orchestrator's, as the owner's stand-in): a licence stated only in the vendor's README is recorded as stated, with the README fetched and quoted and the evidence class saying so, as the registry already records a stated claim for other rows. A board whose repository states no licence in anything fetched is not added; for the SparkFun C5 read its board file for a stated licence first, as the Pocket's FRAME1 was read, and drop it if nothing states one.

Each board: registry row (sparse; board file, licence evidence), manifest row (KiCad rows need no schematic), pins from the variant and the traced copper against a cited datasheet table for the part the headers reach (a module's own table where the chip sits inside a module), and a run test with a BOARD_FIRMWARE_VERIFIED entry as the other ESP32 manifest boards have. The model layer stays refused for KiCad rows until OH-195.

Done when each board holds geometry, pins and runs in TWINS, or stops at a named layer with the reason.
