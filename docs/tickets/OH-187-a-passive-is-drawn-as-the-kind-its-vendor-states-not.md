---
id: OH-187
title: A passive is drawn as the kind its vendor states, not the kind its package
  shares
status: in-progress
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-187-*
- tools/compose_board_3d.py
- tests/rules/test_compose_board_3d.py
---

Part of OH-174, found when OH-180 merged (2026-09-30). The composer draws some passives with the other kind's model. From `tools/compose_board_3d.py --board`'s own drawn list on master:



    Adafruit QT Py ESP32-C3    R1-R6 drawn as C_0402_1005Metric

    Adafruit Feather ESP32-C6  C4 and C10 drawn as R_0603_1608Metric



The pads land (a resistor's and a capacitor's KiCad land in one size are nearly the same), so every placement check passes, and the drawn list states a part name that is false: the rule CLAUDE.md gives for the QFN-56 near miss, that drawing it "would put a false part name in the model's own list".



OH-180 met this once already for SparkFun's 0603 and added a `vendor_library` field to tell the two apart. Adafruit's libraries use one package for both kinds, so the package cannot decide. Decide from what the vendor's own files state about the part, and only that: the schematic's deviceset or device for the element (the .brd carries packages only for these boards), or the element's value where it parses unambiguously as ohms or farads. Record which one decided. A passive whose kind nothing in the vendor's files states is refused with that reason rather than drawn as a guess.



Done when every drawn passive on the four composed manifest-era boards names the kind its vendor states, a deliberately swapped kind is refused or caught by a test, and the XIAO and Uno compositions are unchanged.

**Note 2026-09-30:** 2026-09-30, lane3 (local, not merged): dc69181 reads each passive's kind from its vendor's schematic, and only there: stated_kinds takes the prefix of the deviceset the part is placed from (R, C, L) and a value that parses as ohms or farads (value_kind; a bare number, henries and words state nothing). Both agreeing, either alone decides; both disagreeing, or neither, refuses the part alone (not its package), printed with the reason and carried in the model's extras beside a 'kinds' map that records which statement decided each passive. A manifest Composition carries its schematic; correspondence_for takes the stated kind and returns a passive row only of that kind; 0603-NO, 0805-NO and _0402NO each have a row per kind. Before -> after: QT Py R1-R6 C_0402 -> R_0402, L2 L_0402 -> REFUSED (microbuilder/INDUCTOR valued '0 ohm'), drawn 33 -> 32; Feather C4 and C10 R_0603 -> C_0603; KB2040 C15 R_0603 -> C_0603, eleven 0402 resistors C_0402 -> R_0402, R8 C_0805 -> R_0805 (RESISTOR valued FUSE: the prefix decides alone, a stated JUDGEMENT). Thing Plus unchanged (its libraries already agreed). XIAO and Uno: --check output byte-identical through the Thing Plus header, all 11 placement lists unchanged. 0eca71c: four tests, each failed once on purpose (bare number as ohms; value never read; the _0402NO resistor row swapped to a capacitor; a swapped statement for R1 through compose). Recomposed the four manifest boards. Composer and importer rule files under miniconda: 208 passed. Full default-python suite: 2352 passed, 35 skipped, 2 failed -- the known OCP pair in test_import_3d_model.py (OH-163). TWINS unchanged by this ticket: 12 of 30, model 29. Not done here: SparkFun's C6 is valued DNP and is drawn (a fitted-or-not question, not a kind one).

**Note 2026-09-30:** 2026-09-30: review round. tools/compose_board_3d.py and tests/rules/test_compose_board_3d.py go back to OH-186 for its review fixes, which come first; they return here for this ticket's own.

**Note 2026-09-30:** 2026-09-30, review round (lane3): d693b62 and f576810. (6) only an empty prefix is silence; D, U, FB, LED, CONN name a kind none of R, C and L, and one valued in ohms or farads is refused. (7) stated_kinds returns a Statement whose prefix and value are the ones that spoke; the console counts those fields and the model's extras carry {kind, prefix, value} per passive; the QT Py's line is pinned (21 passives: 19 by prefix and value, 2 by prefix alone, 0 by value alone -- the reviewer's 19/4/0 before TBD was refused), and L2 and C7 read back out of a written model's absent list. (8) devicesets keyed by library and urn (the Feather carries two supply1s); a written schematic with LED, CONN and FB parts kills the first-letter mutant; refusals pinned per fetched board, skip naming the unfetched; correspondence_for with a kind takes only that kind's rows and without one answers None where two unlibraried rows match; the gate is drawn_from, by what the part is, so a diode in a resistor's moulding draws from its row; the refused count includes the schematic's refusals; no 'a inductor' left. (9) KIND_WORDS = {FUSE}, closed and pinned: the KB2040's R8 (RESISTOR valued FUSE) is refused as a disagreement, not as undrawable; DNP/NC/NF/DNF/DNI and populate="no" are not fitted (the Thing Plus's C6); TBD is not drawn (the QT Py's C7, C9). (10) the 0805-NO resistor row drew nothing and is gone; a test holds every row to drawing something on some composed board; the passive rows describe their land. Eleven mutants of the composer's source, one per item or more, each failed its test and the source was restored byte for byte. Tests that asked correspondence_for without a kind ask drawn_from. f576810 restores mark_turns' docstring: cutting its counts (91fe177) staled check_facts' claude-md:mark-turns anchor, whose re-confirm writes OH-149's tools/facts_store.json. Drawn / refused now (refused = no model + by schematic): Thing Plus 34 / 4+1 (C6 DNP); QT Py 30 / 2+3 (C7, C9 TBD; L2); Feather 32 / 4+0; KB2040 34 / 3+1 (R8). Uno and XIAO placement lists unchanged. Four manifest boards recomposed. Composer and importer rule files under miniconda: 216 passed. Full default suite: 2359 passed, 36 skipped, 2 failed -- the OCP pair (OH-163). TWINS 12 of 30, model 29.
