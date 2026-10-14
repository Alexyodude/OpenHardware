---
id: OH-236
title: 'Seeed''s XIAO board files state 1.6 mm and the composed XIAOs are drawn at
  1.2 from the RP2040 mesh: which is the board?'
status: done
priority: P3
created: '2026-10-14'
---

Found in the OH-231 step 3 review. The composer draws every composed Seeed XIAO at 1.2 mm, from the XIAO RP2040 mesh's PCB solid (0.00..1.20 in its extras), while the vendors' own KiCad files say otherwise. Evidence, read from third_party/seeed-pcb and the STM32C5 zip on 2026-10-14: ESP32-C6, RP2350, nRF54L15, MG24, nRF54LM20A and XIAO STM32C5: (general (thickness 1.6)) plus a (stackup) summing to 1.6; ESP32-C3: general 1.6, no stackup; ESP32-C5: 1.209108 in both places (the one deliberate-looking value). KiCad's default board thickness is 1.6 (DEFAULT_BOARD_THICKNESS_MM, include/board_design_settings.h), so a file stating 1.6 may never have set it. Question: is the family 1.2 (the RP2040 mesh, the C5) or 1.6 (six files)? Decide, then change Composition.thickness_mm for the whole family together, and the thickness test that holds the STM32C5 to its siblings. Claims nothing; the composer is OH-163's.

**Note 2026-10-15:** Decided: the family stays 1.2 and Composition.thickness_mm is unchanged. No single number is the family's -- Seeed's own meshes read 1.20, 1.21, 1.25, 1.25, 1.51 and 1.60 (the last the MG24's own KiCad export) -- and 1.6 on a KiCad file's say-so is the weaker claim, since it is KiCad's default and the C5's deliberately filled stackup says 1.209108. Seeed publishes no PCB thickness on any page found; one third-party micrometer reading (printables.com model 562613, comment 1170884, not fetched verbatim) puts XIAOs at about 1.2. Reopen on a caliper reading of a newer XIAO (MG24, nRF54L15, RP2350) or a Seeed drawing. The evidence is in compose_board_3d.py's comment on the XIAO STM32C5, under OH-163.
