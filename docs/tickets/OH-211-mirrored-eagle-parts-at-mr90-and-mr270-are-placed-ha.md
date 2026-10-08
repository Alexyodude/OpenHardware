---
id: OH-211
title: 'Mirrored EAGLE parts at MR90 and MR270 are placed half a turn off: EAGLE turns
  and then mirrors'
status: in-progress
priority: P1
created: '2026-10-08'
touches:
- tools/eagle.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
- tests/rules/test_import_board.py
---

Found by OH-184's review and re-measured by its fix round (2026-10-08). Mirrored EAGLE parts at MR90 and MR270 are placed turned the wrong way.

`tools/eagle.py`'s `place` mirrors x and then turns counter-clockwise by d for an `M` rotation. EAGLE's `MRd` means turn by d and then mirror x; KiCad 7's own EAGLE importer reads it that way (`pcbnew/plugins/eagle/eagle_plugin.cpp:1571-1575`: orientation d+180, then Flip). The two orders agree at MR0 and MR180 and are half a turn apart at MR90 and MR270.

Measured against each EAGLE board file's own routed copper, a contact landing within 0.01 mm of a wire end or via on its own signal:
- MR90 and MR270 contacts: 1 of 45 land as placed, 38 of 45 turned then mirrored.
- On nets with no pour, every contact on all eight EAGLE boards lands turned then mirrored (1020 of 1020, against 994 as placed).
- All routed contacts: QT Py ESP32-C3 113 -> 133 of 144, Pro Micro ESP32-C3 104 -> 108, Thing Plus ESP32-C6 149 -> 162 of 207.
- The asymmetric four-pad JP14 (USB-SOLDER-PADS, MR270) on the Pro Micro lands at 0.000 mm turned then mirrored and misses by 0.9 to 3.8 mm as placed.

`tools/eagle.py`'s docstring explains the Thing Plus's worst miss (2.08 mm) as EAGLE routing "to the jumper's other pad"; it is this order error, and that explanation should go. `test_placement_mirrors_in_x_before_it_rotates` pins today's order.

Affected composed boards: the Thing Plus C6, the QT Py C3 (including Y1 and D2), the Feather C6 (its back labels) and the Pro Micro C3: pads, bodies, marks and models of mirrored elements at MR90/MR270 are half a turn off. Check whether any traced pin (tools/import_pindefs.py's EAGLE trace) passes through such a part.

Make `place` turn first, then mirror. In the same change, `compose_board_3d.from_kicad`'s back-side rotation depends on today's convention (OH-184's review: set it to (180 - theta) mod 360 and follow it through `compose.place`), so KiCad boards must come out unchanged. Hold it with the routed-copper measurement as a test, and the existing underside KiCad test. Recompose the affected boards and report what changes.

Done when every routed contact on an EAGLE board's mirrored elements lands on its own net's copper as placed (or the misses are explained by pours), and every KiCad board's composition is unchanged.
