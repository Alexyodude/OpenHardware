---
id: OH-187
title: A passive is drawn as the kind its vendor states, not the kind its package
  shares
status: in-review
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
