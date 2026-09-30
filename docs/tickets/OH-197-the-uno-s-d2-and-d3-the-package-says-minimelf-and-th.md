---
id: OH-197
title: 'The Uno''s D2 and D3: the package says MiniMELF and the part it names is a
  1206 chip diode'
status: open
priority: P3
created: '2026-09-30'
touches:
- docs/tickets/OH-197-*
---

Found by the review of OH-190 (2026-09-30). The Arduino Uno's D2 and D3 are drawn with KiCad's `D_MiniMELF`, because Arduino's board file places them on a package named MINIMELF. Their value names a specific part, Bourns CD1206-S01575, which the reviewer found listed by Bourns and by distributors as a 1206 leadless chip diode, about 3.4 x 1.7 x 0.95 mm, not a glass MiniMELF (sources the reviewer cited: Bourns' datasheet and package-change notice for CD1206-S01575, Octopart, LCSC). Two vendor statements about one part disagree: the package name and the part named in the value.

Under the rule the composer already applies to passives (OH-187), a disagreement between two statements refuses the part rather than picking one. Decide whether a value that names a manufacturer part number is a statement of body this repository reads (it would need the part's own datasheet, cited, as the ESP32 module tables are), and either refuse D2 and D3 with both statements quoted or draw them as the body the named part's datasheet states, citing it. Do not keep drawing a MiniMELF on the strength of the package name alone once the value is known to say otherwise.

Done when the Uno's D2 and D3 are refused or drawn as a body a cited source states, and the drawn list names no body the value contradicts.
