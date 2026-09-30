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
