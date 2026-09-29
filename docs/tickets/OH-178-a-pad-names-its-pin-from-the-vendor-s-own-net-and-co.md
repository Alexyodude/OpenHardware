---
id: OH-178
title: A pad names its pin from the vendor's own net and connector names where the
  BSP does not, and says which source it was
status: in-progress
priority: P1
created: '2026-09-29'
touches:
- docs/tickets/OH-178-*
- tools/eagle.py
- PROVENANCE.md
- tools/import_pindefs.py
- tools/board_manifest.py
- webui/boards/SparkFun*
- webui/boards/Adafruit*
- tests/rules/test_import_pindefs.py
- tests/rules/test_board_manifest.py
- README.md
---

Part of OH-174, found by OH-176. The SparkFun Thing Plus ESP32-C6 names a chip pin on 5 of its 28 pads, and the pins layer of the OH-175 scorecard fails it. The other 23 are null because the only pin source read for a manifest board is the arduino-esp32 variant, and the variant either does not define the pad's label or defines it under a name no pad carries. OH-176's ticket note records which pads fall in each case.

The vendor's own CAD says more than the variant does. The pad labels are SparkFun's net names, and OH-176 added a test that each of the five resolved pins agrees with the IO number in its net name. The schematic's connector pin names are a second vendor statement the variant's names could join through.

Precedent: OH-170 read `SWDIO/PA13` and `SWCLK/PA14` for the XIAO STM32C5 out of Seeed's own symbol library, and recorded the source as the vendor's CAD rather than firmware. This is the same class of source.

Read the pin a pad reaches from the vendor's own board and schematic files where they state it, recorded as that source and distinguishable from a BSP-sourced pin (OH-173's concern: a reader must be able to tell how a pin is known). A net name that does not parse as a pin of this chip stays null with a reason; nothing is inferred from a silkscreen or an image.

Done when the pilot's pins layer is measured again and every pad either names its pin with the file that said so or carries a specific reason, and a deliberately wrong net name has been shown to be refused rather than resolved.

**Paths this will need**, claimed when the ticket is started (they are held by other tickets at filing): `tools/import_pindefs.py`, `tools/eagle.py`, `webui/boards/SparkFun*`, `tests/rules/test_import_pindefs.py`.

**Note 2026-09-29:** From OH-176's review, 2026-09-29. (1) Nine of the pilot's null pads are GPIOs the arduino-esp32 variant names under another spelling: IO0-IO5 (A0-A5, and SS=5), IO20/PICO and IO21/POCI (MOSI/MISO), IO23/STAT (PIN_RGB_LED 23). (2) Trap: J1's SCHEMATIC pin names GPIO0-GPIO6 are Feather header positions, not ESP32 GPIO numbers (the reviewer found 'GPIO5' on net IO23, 'GPIO0' on IO18, 'GPIO4' on IO8). Joining through those names would resolve pads to the wrong pin while reading as vendor-sourced. The net names are the ones that carry the ESP GPIO number. Verify both against the files before relying on them.

**Note 2026-09-29:** From OH-177's review, 2026-09-29: the Adafruit Feather ESP32-C6's arduino-esp32 variant numbers three of the six GPIOs its pads leave generic under other names: GPIO0 as A6 and SS, GPIO9 as PIN_NEOPIXEL, GPIO15 as LED_BUILTIN. IO7, IO8 and IO14 appear nowhere in the variant. Adafruit's nets on that board are signal names (TX, SDA), not IO<n>, so this board's net-name source is weaker than the SparkFun pilot's; OH-177's test follows each resolved pad's net to the chip pad it reaches, which is the stronger join to build on.

**Note 2026-09-29:** 2026-09-29: a manifest pad names the GPIO its net reaches in the vendor's own EAGLE board file (05585a7, 084d0fa, 9d16088). tools/board_manifest.py holds one PinTable per chip part, each cited and re-read 2026-09-29: ESP32-C3 datasheet v2.4 p. 67, ESP32-C6-MINI-1 v1.5 Table 3-1, ESP32-C6-WROOM-1 v1.4 p. 11 Table 3-1. Only pads a header reaches are kept (C3 drops 6 and 15, MINI drops 26, OFF_HEADER goes). import_pindefs.read_eagle_traced reads a header net's pad on the one element placed as the table's package/value, directly or through one two-pad part whose far net holds only that part and one chip pad (QT Py TX via R4). It stops at a chip pad the table does not number: 3.3V reaches a GPIO through a pull-up on all three boards. It refuses a net on two chip pads, and an IO<n> in a net name that is not the traced GPIO. Each row's CAD is a package named by its registry key (firmware=False, `pin_table` = the cite). A manifest pad carries `chip_pin_from`, the package names keying `pindefs.packages`, and derivation and assumption say so. A variant and a trace that disagree give DISPUTED. J1's schematic pin names are never read (confirmed in the .sch: GPIO5 on IO23/STAT, GPIO0 on IO18/!CS!, GPIO4 on IO8). The nine variant-spelling pads resolve by trace. The 25 XIAO files and the module HEADER blocks regenerate unchanged. TWINS before: 9 of 29; geometry 28, model 25, pins 21, runs 13 (pilot 5+3/24, QT Py 11/11, Feather 15/21). After: 9 of 29; pins 23 (pilot 21+3/24, QT Py 11/11, Feather 21/21). Counts: naming 396 -> 418, generic 37 -> 15. The Feather's IO15, IO14, IO0, IO8, IO7 and IO9/BOOT/NEOPIX are traced: api.row_levels reads IO15 at GPIO15 (register check, not a live page), which is OH-183 item 5 as far as the file goes. RED ON PURPOSE, 13 mutants, all red: the far-net rule dropped (divider resolves), a second series hop followed, a hop past a chip contact, the name check off (and the pilot's IO8 renamed IO12 refused), the two-pad check off, two chip elements accepted, a disagreement resolved to the last claim, the whole-label merge dropped, an unused table row, the CAD dropped from a pad's chip_pin_from, a pilot pin against its net name, a supply pad naming a pin, WROOM pad 10 as GPIO9 (refused by the name check). Full pytest: 2 failed (the OCP pair), 2209 passed, 31 skipped; checkall every row PASS but the suite row, the same pair. NOT DONE: J1's pin names (A0, SCK, PICO...) as a second label join to the variant.
