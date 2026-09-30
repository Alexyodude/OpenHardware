---
id: OH-191
title: The Uno's fuse and varistors are drawn as capacitors; its own schematic says
  what they are
status: in-review
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-191-*
---

Found by OH-187's review (2026-09-30). The composed Arduino Uno draws F1, its fuse, with a C_1812 capacitor model, and Z1 and Z2, its varistors, with C_0603 capacitor models. The pads land, so every placement check passes, and the drawn list names parts they are not: the false-part-name rule CLAUDE.md gives for the QFN-56 near miss.

OH-187 made a passive's kind come from its schematic's own statements (the deviceset prefix and a value that parses as ohms or farads) and refuses a part stated as another kind, but only for manifest rows. The Uno is composed from Arduino's `.brd`, and Arduino also publishes its `.sch` in the same CAD zip (`third_party/arduino-uno/UNO-TH_Rev3e.sch`). Read the Uno's schematic the same way, so its F1, Z1 and Z2 are drawn as what the schematic says they are when a published model of that kind exists (the review notes KiCad publishes a Fuse 1812 model) and refused with their reason when none does.

Done when the Uno's drawn list names no part as a kind its schematic contradicts, the other Uno placements are unchanged, and a deliberately restated kind on the Uno is caught by a test.

**Note 2026-09-30:** 2026-09-30, correction by the orchestrator: this ticket's body says 'the review notes KiCad publishes a Fuse 1812 model'. That repeated an unverified sentence from OH-187's review; OH-191's worker found KiCad's Fuse library stops at 1210 (the review's verified finding was a Fuse_0805 model). A claim carried from a review into a ticket body is still a claim, and it was not checked here before filing.

**Note 2026-09-30:** 2026-09-30, lane2 (local, not merged): 62c837e, 65a05d3. The Uno's Composition carries UNO-TH_Rev3e.sch (same CAD zip as its .brd), read through statements_for as the manifest boards' are. What Arduino's schematic states: F1 from rcl/L-EU (INDUCTOR, prefix L), valued 'MF-MSMF050-2 500mA'; Z1 and Z2 from varistor/VARISTOR, prefix R, valued 'CG0603MLC-05E'. The prefix alone would draw the fuse as an inductor and the varistors as resistors, so neither 'draw as stated' outcome was true: a name that drops a passive's prefix letters (F1 for L, Z1 for R) is the designer contradicting the library, and the part is refused with both statements; a name that keeps them (PC1 for C) keeps the kind. No model would have been found anyway: KiCad's Fuse library stops at 1210 (28 files) and its Varistor library holds 100 disc models, none SMD, listed 2026-09-30 -- the review's 'KiCad publishes a Fuse 1812 model' is not so. RN joins PREFIX_KINDS (the Uno's 4R-N networks, which would otherwise be refused as other-kind-valued-in-ohms). Uno: 47 -> 44 drawn (F1, Z1, Z2 gone), refused 5 (QS, RESONATOR; F1, Z1, Z2 by its schematic); every other Uno placement and every other board's --check drawn list unchanged. Rows L1812 (C_1812) and CT/CN0603 (C_0603) drew nothing and are gone; three tests pinning 47 pin 44 with the reason; REFUSED_BY_SCHEMATIC holds the Uno and its passive test runs on every board that reads a schematic. Red on purpose: the rename unread, a rename read as 'does not start with the prefix' (refuses PC1), RN unread, the Uno reading no schematic. Composer and importer rule files under miniconda: 218 passed.

**Note 2026-09-30:** 2026-09-30: tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py passed on to OH-190, then OH-193; they return to OH-163 after OH-193.
