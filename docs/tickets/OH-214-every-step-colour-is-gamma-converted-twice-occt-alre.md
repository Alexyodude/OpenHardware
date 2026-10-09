---
id: OH-214
title: 'Every STEP colour is gamma-converted twice: OCCT already returns linear values
  and write_glb converts them again'
status: in-progress
priority: P1
created: '2026-10-09'
touches:
- docs/tickets/OH-214-*
- tools/import_3d_model.py
- tools/compose_board_3d.py
- tools/model_from_datasheet.py
- tests/rules/test_import_3d_model.py
- tests/rules/test_compose_board_3d.py
- webui/static/board3d.js
- tests/webui/test_board3d.py
- webui/static/parts.js
- tools/facts_store.json
---

Found by OH-163 step 2's worker and confirmed by its review (2026-10-09). Every base colour read from a STEP file is gamma-converted twice, so every vendor model and every KiCad, Espressif or Blender part ships darker and more saturated than its file says.

The read side: `tools/import_3d_model.py`'s `colour_of` formats `colour.Red() * 255`, and OCCT's `Quantity_Color.Red()` returns the colour's linear value (cadquery-ocp 7.9.3.1.1, OCCT 7.9.3: `Quantity_Color(0.824, 0.82, 0.781, Quantity_TOC_sRGB).Red()` is 0.6453; `.Values(Quantity_TOC_sRGB)` gives the file's 0.824). So every STEP-derived hex key is a linear byte. The write side: `write_glb` applies `linear()` to that hex again, and glTF's `baseColorFactor` is linear and `webui/static/board3d.js` passes it to `THREE.Color` as linear.

What ships, measured from the files by the review: KiCad's PIN-01 (sRGB 210,209,199 in the STEP) displays as 165,163,146; the chip-capacitor body (97,69,55, tan) as 30,15,10, near black; Seeed's SAMD21 gold (255,207,128) as 255,159,55. Composer constants (COPPER, SILKSCREEN, the masks, routing) are sRGB by origin and converted once, so they are right: the hex keyspace mixes two encodings.

Fix it on the read side (`colour.Values(Quantity_TOC_sRGB)` or the equivalent in `colour_of`), then re-key everything keyed on a STEP-derived hex: FINISHES' entries, `CONTACT_COLOURS`, hexes copied from STEPs in `tools/model_from_datasheet.py`, part lens names, the KiCad palette test's `key()`. Tests that pin today's behaviour (`test_the_written_albedos_are_linear_and_not_the_bytes`, `test_black_epoxy_renders_black_rather_than_grey`) must change with it, and the `linear()` docstring's measurements, which are wrong for at least #b58136 and #050505. Once keys are sRGB, `test_no_metal_is_darker_than_a_metal_reflects`'s threshold of 128 must become about 188 (0.5 linear), or MET-SILVER passes as bright enough. Re-import the vendor models and recompose every board; report what each changes.

Done when a STEP colour reaches the .glb converted exactly once, held by a test that reads a known STEP colour through to the written factor, and every key derived from a STEP is in one encoding.

**Note 2026-10-09:** 2026-10-09: filed claiming only this file. Its work needs tools/import_3d_model.py, tools/compose_board_3d.py, tools/model_from_datasheet.py and their tests, which OH-163 holds for its steps 3-4; lend them here when OH-163 releases them.
