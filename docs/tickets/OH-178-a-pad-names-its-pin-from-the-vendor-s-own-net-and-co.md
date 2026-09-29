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
