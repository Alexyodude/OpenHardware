---
id: OH-195
title: The composer composes a KiCad manifest row, reading what a .kicad_pcb states
  about colour, thickness, kind and fitting
status: in-progress
priority: P1
created: '2026-09-30'
touches:
- docs/tickets/OH-195-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
---

Part of OH-174. The composer refuses a manifest row whose board file is a `.kicad_pcb`, by name (OH-180). The PCBCUPID Glyph Mini RP2040 (OH-192) is such a row, and OH-194 adds more; their model cells read `footprint:no source`, so none of them can hold all four layers.

The composer already composes whole-board KiCad files: six XIAOs are composed from Seeed's `.kicad_pcb` (COMPOSITIONS). What the refusal stood for was the manifest path's EAGLE-only parts: the preview mask colour and the board notes (EAGLE layers and settings), the stated passive kinds read from an EAGLE schematic, and NO_POP/DNP read from EAGLE devices and values. For a KiCad row:

- colour and thickness come from what the `.kicad_pcb` states (its stackup, `(general (thickness))`, a title-block or text note), or are marked a judgement as `BOARD_MASK` is;
- a passive's kind comes from what the KiCad file states about the footprint (its library name, value, and properties such as the reference prefix), under the same rule OH-187 set: statements that agree decide, a disagreement or silence refuses that part;
- not-fitted comes from what KiCad records for it (the footprint's DNP or exclude-from-BOM attributes, or a value word in OH-187's closed vocabulary).

Back-side footprints are stored already flipped (OH-182, OH-184): do not mirror them a second time.

Done when the Glyph Mini's model cell reads composed with every placement drawn or reasoned, the six XIAO compositions are unchanged, and a KiCad row whose file states nothing about a part's kind refuses that part.
