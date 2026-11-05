---
id: OH-262
title: Silkscreen circles, curves, dimensions and EAGLE arcs are counted and not drawn
status: open
priority: P3
created: '2026-11-05'
---

OH-163 step 3 drew silkscreen lines, rects, KiCad arcs and filled polygons; these are still counted and not drawn, as --check prints per board by kind. KiCad: SILK_UNREAD in tools/kicad.py -- circle, curve (bezier), bbox, dimension (a dimension's leader, arrow and text frame). EAGLE: plain and package circles on ink layers; curved wires (tools/eagle.py counts them as 'arc' on purpose since OH-235, which held the KB2040, SparkFun's Pro Micro ESP32-C3 and Qwiic Pocket ESP32-C6 still -- drawing them changes those boards); curved polygons (one OSHW gear per SparkFun board). NOT MATCHED: KiCad plots a stroke with round ends and stroke_outline draws each as the rectangle its width sweeps, stopping at its end points.

Paths it will want, claimed when it is started rather than now (open tickets may not share a claim): `tools/kicad.py`, `tests/rules/test_kicad.py`, `tools/eagle.py`, `tests/rules/test_eagle.py`, `tools/compose_board_3d.py`, `tests/rules/test_compose_board_3d.py`.
