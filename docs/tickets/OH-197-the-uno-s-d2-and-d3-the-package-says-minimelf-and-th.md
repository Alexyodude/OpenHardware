---
id: OH-197
title: 'The Uno''s D2 and D3: the package says MiniMELF and the part it names is a
  1206 chip diode'
status: open
priority: P3
created: '2026-09-30'
touches:
- docs/tickets/OH-197-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
- tools/import_3d_model.py
- tests/rules/test_import_3d_model.py
---

Found by the review of OH-190 (2026-09-30). The Arduino Uno's D2 and D3 are drawn with KiCad's `D_MiniMELF`, because Arduino's board file places them on a package named MINIMELF. Their value names a specific part, Bourns CD1206-S01575, which the reviewer found listed by Bourns and by distributors as a 1206 leadless chip diode, about 3.4 x 1.7 x 0.95 mm, not a glass MiniMELF (sources the reviewer cited: Bourns' datasheet and package-change notice for CD1206-S01575, Octopart, LCSC). Two vendor statements about one part disagree: the package name and the part named in the value.

Under the rule the composer already applies to passives (OH-187), a disagreement between two statements refuses the part rather than picking one. Decide whether a value that names a manufacturer part number is a statement of body this repository reads (it would need the part's own datasheet, cited, as the ESP32 module tables are), and either refuse D2 and D3 with both statements quoted or draw them as the body the named part's datasheet states, citing it. Do not keep drawing a MiniMELF on the strength of the package name alone once the value is known to say otherwise.

Done when the Uno's D2 and D3 are refused or drawn as a body a cited source states, and the drawn list names no body the value contradicts.

**Note 2026-10-15:** Borrows the composer, the importer and their tests from OH-163. Decided 2026-10-15: draw D2 and D3 as the body the named part's datasheet states. Bourns' CD1206-S01575 datasheet (farnell.com/datasheets/1647933.pdf): 'Switching Chip Diode', 'Case ... 1206 (3216) Molded plastic', 'Leadless', 'Polarity ... Indicated by cathode band'; LCSC C75465 and Microchip USA list it as 1206. No source found calls it a glass MiniMELF, and no package-change notice was found (only a 2020-01-10 discontinuation notice, farnell.com/datasheets/2921950.pdf). The board file's MINIMELF is the stock EAGLE diode library's land, whose own body outline is about 2.64 x 1.57 mm. No photograph of a genuine Uno Rev3's D2/D3 was found, so what is fitted is the named part's body, not a watched one.
