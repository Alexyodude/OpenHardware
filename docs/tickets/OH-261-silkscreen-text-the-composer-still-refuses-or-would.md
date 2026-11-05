---
id: OH-261
title: Silkscreen text the composer still refuses or would draw wrong
status: open
priority: P3
created: '2026-11-05'
---

OH-163 step 1 drew KiCad silkscreen text in newstroke; what it left is carried here. STILL REFUSED, counted by name: PCBCUPID's TrueType text, Lexend and the Noto Sans dimension text (each text's outline polygons are in the file's render_cache; drawing them is new geometry); Olimex C3-DevKit-Lipo's knockout text; every EAGLE board's text (EAGLE's vector font is built into its executable); EAGLE's tNames and tValues, layers 25 and 27, which eagle._ink does not read (whether each vendor's CAM job prints them is unchecked). LATENT, named by step 1's review and not checked board by board: %R and %V (KiCad 5's reference and value shorthands) drawn literally; KiCad's UnescapeString not applied; an fp_text user's default thickness; back-side footprint text KiCad 8 mirrors without '(justify mirror)'; face 'KiCad Font', which KiCad draws in its stroke font and the composer refuses as TrueType; a 'plotfptext no' plot setting; KiCad 5's keep-upright range; private_layers. Each latent item wants a board-by-board check first: one that occurs on no composed board is a test, not a fix.

Paths it will want, claimed when it is started rather than now (open tickets may not share a claim): `tools/kicad.py`, `tests/rules/test_kicad.py`, `tools/eagle.py`, `tests/rules/test_eagle.py`, `tools/compose_board_3d.py`, `tests/rules/test_compose_board_3d.py`.
