---
id: OH-199
title: 'The composer''s low edges from the OH-190/191/193 review: stem citations,
  FB two ways, first word wins, and a skipped board''s stale model'
status: open
priority: P3
created: '2026-09-30'
touches:
- docs/tickets/OH-199-*
---

Low-severity edges in the composer found by the approving re-review of OH-190, OH-191 and OH-193 (2026-09-30). None changes any board's drawn list today; each is a way a future board could be drawn or refused for the wrong reason, or a message that says the wrong thing.

1. The designator stem table's comment calls FB, PTC and R-on-RN "common practice" beside "these boards", so it reads as if a board here uses them; none does (across the seven schematics only PC1/PC2, F1, Z1 and Z2 differ from their prefix). Say per entry where each stem comes from: IEEE 315 for R, C, L, F; the Uno for PC; convention with no instance here for the rest.
2. FB is treated two ways: a FERRITE deviceset with prefix FB (the usual ferrite library) is refused as disagreeing statements, while FERRITE_BEAD with prefix L, or FB1 on an L prefix, draws as an inductor. The stem table accepts FB while PREFIX_KINDS calls an FB prefix another kind. Make one decision and apply it in both places.
3. First deviceset word wins: PTC_THERMISTOR2 with prefix F reads only PTC and draws as a fuse. Two different kind words in one deviceset name should be a disagreement.
4. A VARISTOR deviceset with an empty prefix is refused with "prefix None names a kind none of R, C, L and F", though the deviceset name spoke, not the prefix. Name the statement that spoke.
5. main() now composes past a skipped board and writes the index anyway, so a .glb left from an earlier run of the skipped board stays indexed with old contents (a pre-OH-191 Uno would still draw F1 as a capacitor). Drop a skipped board from the index, or refuse to write it.
6. main() reads compose()'s return value 3 as "skipped", but a byte count of 3 would read the same; use a distinct signal.
7. test_compose_refuses_a_flip_on_a_mirrored_element goes through the Pocket module row's Espressif footprint, which is downloaded if not cached: network access in a test meant to run without OCP. Skip naming the file when it is not cached.
8. Stray-face inversion of the band reading, accepted when OH-190 closed: a face covering 1% or more of the surface further out than the band would invert the verdict. Leave it unless a model gives cause, and say so where the band rule is described.

**Note 2026-10-08:** 2026-10-08, from OH-195's confirm review; all latent (no fetched board triggers any today). 9. Several tests in tests/rules/test_compose_board_3d.py still decide absent by package name and ignore ABSENT_ONLY_FROM (the closed-world test test_every_composed_boards_placements_are_drawn_or_explained among them): a board placing KiCad's plain PinHeader_1x05/1x09 with no row would count as explained there while the composer prints no model. Use compose.absent_why(element). 10. via_in_pad's four half-lines are unbounded: same-numbered tabs 10 mm away on each side make a leg's hole a via; bound each to the hole's land plus one gap. 11. Its turned-pad test uses 90 degrees only, so a rotation-sign error passes; add 30 or 45. 12. Its docstring says an EAGLE pad carries no angle; tools/eagle.py sets rotation_deg for drilled and SMD pads; delete the clause. 13. On MOUDLE14P-XIAO-HALF-HOLE (XIAO ESP32-C6 and RP2350) the inner plated holes of pins 2, 6, 9 and 13 lie 0.113 mm outside their pad and read as legs, the other ten count as vias by 0.0045 mm: the verdict rests on micrometre margins of a custom pad's box (ABSENT today, so confirm never runs). 14. The C5's colour source says it lays the mask as KiCad's 3D view does, but with use_stackup_colors on (KiCad's default) an unnamed dielectric is opaque black there, giving #ba2918, not FR4 natural's #cd3c25: say so and why FR4 natural was chosen. 15. kicad_statements' duplicate-reference raise stops every later board in main(), which catches only Unavailable: refuse that reference's statements instead. 16. The dielectric read collects only layers that name a colour, so one named dielectric stands for all; a #hex dielectric falls back to FR4 saying it is not a colour that view names; the colour test indexes KICAD_BOARD_COLOURS[cores[0]] directly and would KeyError on an unknown name.
