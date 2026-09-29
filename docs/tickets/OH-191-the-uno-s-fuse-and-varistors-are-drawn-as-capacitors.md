---
id: OH-191
title: The Uno's fuse and varistors are drawn as capacitors; its own schematic says
  what they are
status: open
priority: P2
created: '2026-09-30'
touches:
- docs/tickets/OH-191-*
---

Found by OH-187's review (2026-09-30). The composed Arduino Uno draws F1, its fuse, with a C_1812 capacitor model, and Z1 and Z2, its varistors, with C_0603 capacitor models. The pads land, so every placement check passes, and the drawn list names parts they are not: the false-part-name rule CLAUDE.md gives for the QFN-56 near miss.

OH-187 made a passive's kind come from its schematic's own statements (the deviceset prefix and a value that parses as ohms or farads) and refuses a part stated as another kind, but only for manifest rows. The Uno is composed from Arduino's `.brd`, and Arduino also publishes its `.sch` in the same CAD zip (`third_party/arduino-uno/UNO-TH_Rev3e.sch`). Read the Uno's schematic the same way, so its F1, Z1 and Z2 are drawn as what the schematic says they are when a published model of that kind exists (the review notes KiCad publishes a Fuse 1812 model) and refused with their reason when none does.

Done when the Uno's drawn list names no part as a kind its schematic contradicts, the other Uno placements are unchanged, and a deliberately restated kind on the Uno is caught by a test.
