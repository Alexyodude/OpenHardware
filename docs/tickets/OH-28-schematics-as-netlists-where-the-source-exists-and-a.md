---
id: OH-28
title: Schematics as netlists where the source exists, and as pictures where it does
  not
status: open
priority: P2
created: '2026-08-25'
touches:
- tools/import_schematic.py
- tests/rules/test_import_schematic.py
---

A schematic PDF is a picture of a netlist, and no amount of parsing turns one into the other. A .kicad_sch or an EAGLE .sch is the netlist itself. Those two cases must not end up in the same column of any report.

Where source exists, extract the connectivity a twin needs and nothing more: which MCU pin reaches which header pad, which LED sits on which GPIO and through which resistor, where the USB lines and the crystal go, and what the regulator feeds. That is a small subgraph of a full netlist and it is the part a running board consults.

The XIAO LED is the concrete motivation. tools/import_firmware.py's note records that XIAO ESP32-C3 defines no LED_BUILTIN, so a fixture blink had to be rewritten -- that is a question a netlist answers and a footprint does not.

Where only a PDF exists the answer is 'PDF only', recorded as a fact about the vendor, and the board's LED wiring stays unknown. An unknown that is written down is usable; one that is inferred is not.

Done when one board's LED-to-GPIO edge comes out of the vendor's schematic source and is checked against that board's own board-support definition, and a PDF-only vendor is reported as PDF-only rather than as unparsed.

**Note 2026-08-25:** Same census as OH-29's note: Seeed publishes 0 .kicad_sch and 0 .kicad_pcb across the whole repository -- 37 .kicad_mod and 1 .kicad_sym are the entire machine-readable set. The 2 .pdf are marketing slides and a use-case document, not schematics. So neither branch of this ticket has input from the current vendor: there is no schematic source to turn into a netlist, and no schematic PDF to record as PDF-only. Blocked behind OH-23 in practice.
