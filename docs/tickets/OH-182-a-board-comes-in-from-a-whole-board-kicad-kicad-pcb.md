---
id: OH-182
title: A board comes in from a whole-board KiCad .kicad_pcb, as it does from an EAGLE
  .brd
status: in-progress
priority: P2
created: '2026-09-29'
touches:
- docs/tickets/OH-182-*
- tools/import_board.py
- tools/kicad.py
- tests/rules/test_import_board.py
- tests/rules/test_kicad.py
---

Part of OH-174, split out of OH-177. tools/import_board.py reads an EAGLE `.brd` and a KiCad `.kicad_mod` footprint (`import_board.READERS`), not a whole-board KiCad `.kicad_pcb`. Every XIAO came in as a footprint, and every manifest board so far is EAGLE, so nothing has needed it yet. The PCBCUPID Glyph Mini RP2040 does: its vendor publishes `glyph-mini-rp2040.kicad_pcb` (MIT) and no footprint of the board.

tools/kicad.py already parses `.kicad_pcb` for tools/compose_board_3d.py, which composes six XIAOs from Seeed's `.kicad_pcb` files. Reuse that parser. Selecting the header footprints by reference, as `--select` does for EAGLE elements, is the natural shape.

Pads must trace to the vendor's coordinates the way the EAGLE rows do, with the same position test. KiCad pads carry their net, so a pad's label is its net name as in the EAGLE rows. The Glyph Mini's nets are `/GPIO-n`: turning those into chip pins is OH-178's work, not this ticket's.

Done when a `.kicad_pcb` row imports with pad positions checked against the file, a `.kicad_pcb` naming a reference that is not there is refused naming it, and the Glyph Mini row exists once OH-181 lets its variant through (or this ticket says which of the two is still missing).

**Note 2026-09-29:** From OH-177's approving re-review, 2026-09-29, for whoever next edits tools/import_board.py: the merge in _from_eagle collapses the pads one schematic <connect> names into one pad, and nothing checks that those pads share a net. A connect like '1 1C 2 2C' would give 13 pads and silently drop one. Refuse a connect whose pads sit on more than one net, and make the KiCad path apply the same rule if a .kicad_pcb footprint maps one pin to several pads.
