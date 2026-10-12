---
id: OH-226
title: 'A composed board is solid where its file drills and mills holes: cut them
  in the slab'
status: open
priority: P2
created: '2026-10-12'
touches:
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Split out of OH-163 by its milled-holes review (2026-10-12). OH-163 now reads and counts every hole a board's file makes -- KiCad's Edge.Cuts circles and polygons on the cutouts line, EAGLE's board and package `<hole>`s and KiCad's np_thru_hole on a holes line -- and cuts none of them, because `slab()` in `tools/compose_board_3d.py` extrudes only the outer ring `outer()` returns. A real board has those holes; the composed one is solid there.

What cutting needs (OH-163's note and its review):
1. Faces triangulated with holes: bridge each interior ring into the outer ring (Eberly's rightmost-x method) and fill the result with `ear_clip`, which since OH-163 fills weakly simple rings.
2. A wall per hole (4n + 4 triangles for an n-sided hole).
3. EAGLE holes and KiCad drills turned into rings at `ARC_CHORD_MM`.
4. Artwork kept out of the holes: everything is clipped to the outer ring only and the composer has no polygon difference; drop-and-count what reaches a hole is the cheap first step (one QT Py silkscreen stroke reaches an X6 peg; ink, traces, pads and vias reach the XIAO slots by a loose measure).

Risks the review named, each to be handled with a test:
- Circles are split exactly on their centre's y, and holes share rows (the Glyph's top pair, SparkFun's standoffs, each USB-C peg pair), so a +x ray from one hole's rightmost vertex hits the next hole's leftmost vertex exactly: the bridge must handle a ray through a vertex and an outer vertex visited three or more times.
- `ear_clip`'s open gap (OH-163's 2026-10-12 note): a crossing through a vertex can return a face of winding 2 covered twice with every runtime check passing. Close it before every slab goes through `ear_clip`.
- `slab()` assumes a counter-clockwise ring and never normalises; hole rings must be made clockwise explicitly.
- Every composed .glb's binary chunk changes, so the "binary unchanged" evidence earlier slices used is gone. Replace it with: face area = outline minus holes, and a vendor oracle -- SparkFun's repositories carry EAGLE Excellon drill files (`Production/*-Panel.TXT`) for the Thing Plus C6, Qwiic Pocket C6 and Pro Micro C3, outside the sparse checkouts.

Then, and only where no header pin stands, plated drills: the same bridging (pad minus drill), with EAGLE's layer-46 slot overriding a pad's round drill.

Claims: `tools/compose_board_3d.py` and its tests are OH-163's; borrow them when this starts.

**Note 2026-10-13:** 2026-10-13: borrows tools/import_3d_model.py, tools/compose_board_3d.py and their tests from OH-163 (via OH-228, done). Return them to OH-163 when this closes.
