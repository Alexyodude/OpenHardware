---
id: OH-180
title: The SparkFun Thing Plus ESP32-C6 is composed from its own EAGLE board file,
  as the Uno is
status: open
priority: P2
created: '2026-09-29'
touches:
- docs/tickets/OH-180-*
---

Part of OH-174. The SparkFun Thing Plus ESP32-C6 draws an extruded footprint, so its model layer fails in the OH-175 scorecard. SparkFun publishes no mesh in the repository the registry fetches, and does publish its EAGLE board file, which is exactly the Arduino Uno's situation. The Uno is composed from its `.brd` by an entry in `COMPOSITIONS` in tools/compose_board_3d.py.

Add the pilot as a composition from the same `.brd` and the same header elements its manifest row selects, so the model and the pad map are centred on the same pads. Every value the entry needs that the `.brd` does not state (thickness, mask colour) either cites where it was read or is marked a judgement, as `BOARD_MASK` is. Parts that cannot be drawn are refused with a reason and counted, as for every other composed board.

Better still if the entry is derived from the manifest row rather than restated in a second table: a board whose row exists and whose layout is EAGLE or KiCad should not need a second hand-written entry to be composed. If that is more than this ticket, say so and leave the restatement guarded by a test that the two agree.

**Claim conflict.** tools/compose_board_3d.py and its tests are claimed by OH-163 (open, unheld). Whoever takes this ticket coordinates: either OH-163 is taken and finished first, or its claim is narrowed. Do not edit the file under this ticket while OH-163 claims it.

Done when the pilot draws a composed model, the scorecard's model layer reads composed for it, and the refusal count for its parts is printed.
