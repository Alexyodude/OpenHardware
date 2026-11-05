---
id: OH-251
title: 'A lead''s segments are not kept out of solids: OH-165''s probe measures it,
  nothing in collide prevents it'
status: blocked
priority: P2
created: '2026-11-05'
---

OH-165 step 3, split out so OH-165 can close on steps 1 and 2.

`webui/static/wire_probe.js`'s `segmentThroughSolid` (OH-165) measures how far a lead's worst SEGMENT lies inside a solid, and `tests/webui/test_wire_probe.py` holds two facts about the shipped solver: a 28-unit lead over an Arduino Uno header (2.54 by 11.54 mm at mmScale 0.5638) has a segment through the header's exact centre, 0.7160 units in, with `contact()` reading no node inside and none proud and stretch at 1.46%; and `test_a_lead_over_the_narrowest_real_solid_does_not_pass_through_it` is `xfail(strict=True)` as the statement of that defect. This ticket is the fix, and passing that test is how it is known; strict means the fix has to remove the mark.

It also owns the complementary failure OH-165 records: a segment SHORTER than the solid is wide, on a lead dipping further into it than its half-width, is ejected by opposite side faces and held across the part -- 417% over rest on a box 3 units across with a 2.5 dip, every contact number reading 0. `outOfBox`'s nearest-face rule is argued for a wide flat slab and inverts for a tall narrow one. A test for that case belongs with the fix, probably measured with `worstStretch` rather than the probe, since no segment need be inside anything.

The candidates OH-165 names: segment-against-box in `collide`; a node count that scales with span so no segment is longer than the thinnest solid; or a swept test. Each changes the drape of every lead on every board, which is what OH-162 step 4's photograph exists to justify, so this waits on OH-162. It needs `webui/static/wires.js` and `tests/webui/test_wires.py`, which OH-162 claims, and so claims nothing yet. When it can, `segmentThroughSolid` should move beside `contact()` in wires.js, as wire_probe.js's header says it is written to.

**Note 2026-11-05:** Blocked on OH-162: the fix needs webui/static/wires.js and tests/webui/test_wires.py, which OH-162 claims until its step 4 (the photograph that justifies changing every drape) is done. Unblock it when OH-162 closes.

**Note 2026-11-05:** When the fix lands, test_the_probe_sees_a_lead_the_node_readings_call_clean in tests/webui/test_wire_probe.py fails by design. It records the defect: the 12, 20 and 28 rows read through > 0. Rewrite its last assertions as every row reading 0, and remove the strict xfail on the test beside it.
