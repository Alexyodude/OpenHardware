---
id: OH-187
title: A passive is drawn as the kind its vendor states, not the kind its package
  shares
status: open
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
