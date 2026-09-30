---
id: OH-192
title: A manifest row from a KiCad board file, piloted on the PCBCUPID Glyph Mini
  RP2040
status: open
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-192-*
---

Part of OH-174. Every manifest row so far is an EAGLE board. Several open boards whose chips already run here publish only KiCad: the PCBCUPID Glyph Mini RP2040 (`glyph-mini-rp2040.kicad_pcb`, MIT, LICENSE file read by the OH-177 survey), the PCBCUPID Glyph C3 and C6, the Olimex ESP32-C3-DevKit-Lipo and ESP32-C6-EVB, and the SparkFun Thing Plus ESP32-C5. OH-182 made tools/import_board.py read a whole-board `.kicad_pcb` (header footprints by reference, one pad per pad number, pads labelled by net). What stops a KiCad row, per OH-181's and OH-180's notes:

1. `Row` requires an EAGLE schematic, whose connects merge one pin's pads. A `.kicad_pcb` already carries pad numbers and nets, and OH-182 merges one pin's pads without a schematic, so the schematic is optional for a KiCad row.
2. Pins: the Glyph Mini's pads are labelled `/GPIO-n`, which no variant label matches. OH-178 traces an EAGLE board's copper to the chip's pad and reads the datasheet table; do the same for a `.kicad_pcb` (pads, nets and footprints are all in the file), with the RP2040 QFN-56 table OH-181 added. A net name is a cross-check only, as for EAGLE.
3. The composer refuses a KiCad manifest row by name (OH-180). Leave that refusal in place: the model layer for KiCad rows is its own ticket.

Pilot: the Glyph Mini RP2040, whose licence is established. The other KiCad boards' licences are stated in READMEs only (the survey marks them S); adding them is a separate decision, not this ticket's.

Done when the Glyph Mini is a manifest row whose pads trace to its `.kicad_pcb` and whose pins come from the variant and the traced copper, the composer still refuses it by name, and an EAGLE row and the XIAO files are unchanged.
